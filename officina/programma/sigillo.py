from __future__ import annotations

import hashlib
import json
import re
import secrets
import sys
import threading
import time
from pathlib import Path

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import NOME

VERSIONE = 1
HELLO = "hello"
WINDOWS = "windows"

SFIDA = 32
SALE = 16
NONCE = 12
COSTO = 2 ** 15
BLOCCO_SCRYPT = 8
PARALLELO = 1
TENTATIVI_WINDOWS = 3

ENTROPIA = f"{NOME}/sigillo/{VERSIONE}".encode("utf-8")
FINESTRA_DI_HELLO = "Credential Dialog Xaml Host"
ATTESA_DAVANTI = 15.0

CREDUIWIN_ENUMERATE_CURRENT_USER = 0x200
CRED_PACK_PROTECTED_CREDENTIALS = 0x1
CRYPTPROTECT_UI_FORBIDDEN = 0x1
LOGON32_LOGON_INTERACTIVE = 2
LOGON32_PROVIDER_DEFAULT = 0
ERROR_CANCELLED = 1223
ERROR_LOGON_FAILURE = 1326

ANNULLATO = "Hai chiuso la finestra di Windows senza confermare."
SBAGLIATA = "La password di Windows non è giusta."
TROPPE = ("La password di Windows non è giusta per tre volte. Per non bloccare il tuo "
          "account di Windows non la chiedo più: apri con la password della cassaforte.")
CAMBIATA = ("La password di Windows è cambiata. Scrivi una volta la password della "
            "cassaforte e la rilego a quella nuova.")
HELLO_RIFATTO = ("Windows Hello su questo computer è stato rifatto, per esempio dopo aver "
                 "azzerato il PIN. Scrivi una volta la password della cassaforte e la "
                 "rilego a Windows Hello.")
ROTTO = ("Il sigillo di Windows di questa cassaforte non si legge più. Scrivi la "
         "password della cassaforte e lo rifaccio da capo.")
BLOCCATO = ("Windows Hello è bloccato dopo troppi tentativi. Sbloccalo con il PIN di "
            "Windows e riprova.")
NON_RISPONDE = ("Windows Hello non ha risposto. Riprova, oppure apri con la password "
                "della cassaforte.")
NON_FISSO = ("Windows Hello su questo computer non dà sempre la stessa risposta, quindi "
             "per la cassaforte uso la password di Windows.")
NIENTE = ("Su questo computer non trovo né Windows Hello né la password di Windows: "
          "la cassaforte si apre solo con la sua password.")
FINESTRA_NON_APERTA = "La finestra di Windows per la password non si è aperta."
MESSAGGIO_PER_LEGARE = ("Scrivi la password con cui entri in Windows: la cassaforte si "
                        "aprirà con quella.")
MESSAGGIO_PER_APRIRE = "Scrivi la password di Windows per aprire la cassaforte."

_NOME_PULITO = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


class Annullato(ErroreOfficina):
    codice = "sigillo_annullato"


class SigilloRotto(ErroreOfficina):
    codice = "sigillo_rotto"


class PasswordDiWindowsSbagliata(ErroreOfficina):
    codice = "password_windows_sbagliata"


class PasswordDiWindowsCambiata(SigilloRotto):
    codice = "password_windows_cambiata"


class HelloNonFisso(ErroreOfficina):
    codice = "hello_non_fisso"


def file_del_sigillo(nome_archivio: str) -> Path:
    from officina.programma import carta

    nome = nome_archivio if _NOME_PULITO.match(nome_archivio or "") else \
        hashlib.sha256(str(nome_archivio).encode("utf-8")).hexdigest()[:32]
    return carta.casa() / "sigilli" / f"{nome}.json"


def nome_della_chiave(nome_archivio: str) -> str:
    return f"{NOME} - cassaforte - {file_del_sigillo(nome_archivio).stem}"


def c_e(nome_archivio: str) -> bool:
    return modo(nome_archivio) is not None


def modo(nome_archivio: str) -> str | None:
    try:
        testa = _leggi(nome_archivio)
    except SigilloRotto:
        return None
    return testa["modo"] if testa else None


def come_si_puo(hello=None, windows=None) -> str | None:
    hello = hello if hello is not None else PortaHello()
    windows = windows if windows is not None else PortaWindows()
    if hello.c_e():
        return HELLO
    if windows.c_e():
        return WINDOWS
    return None


def sigilla(nome_archivio: str, password: str, hello=None, windows=None) -> str:
    if not password:
        raise ErroreOfficina("Manca la password della cassaforte da chiudere nel sigillo.")
    hello = hello if hello is not None else PortaHello()
    windows = windows if windows is not None else PortaWindows()
    testa = None
    if hello.c_e():
        try:
            testa = _sigilla_con_hello(nome_archivio, password, hello)
        except HelloNonFisso:
            registro.avviso("sigillo.hello_non_fisso")
            try:
                hello.togli(nome_della_chiave(nome_archivio))
            except Exception as guasto:
                registro.avviso("sigillo.chiave_non_tolta", tipo=registro.tipo_di(guasto))
    if testa is None:
        if not windows.c_e():
            raise ErroreOfficina(NIENTE, codice="sigillo_impossibile")
        testa = _sigilla_con_windows(nome_archivio, password, windows)
    _scrivi(nome_archivio, testa)
    registro.evento("sigillo.fatto", modo=registro.Parola(testa["modo"]))
    return testa["modo"]


def apri(nome_archivio: str, hello=None, windows=None) -> str:
    testa = _leggi(nome_archivio)
    if testa is None:
        raise SigilloRotto(ROTTO)
    if testa["modo"] == HELLO:
        password = _apri_con_hello(nome_archivio, testa,
                                   hello if hello is not None else PortaHello())
    else:
        password = _apri_con_windows(nome_archivio, testa,
                                     windows if windows is not None else PortaWindows())
    registro.evento("sigillo.aperto", modo=registro.Parola(testa["modo"]))
    return password


def togli(nome_archivio: str, hello=None) -> None:
    file = file_del_sigillo(nome_archivio)
    try:
        testa = _leggi(nome_archivio)
    except SigilloRotto:
        testa = None
    file.unlink(missing_ok=True)
    if testa and testa.get("modo") == HELLO:
        porta = hello if hello is not None else PortaHello()
        try:
            porta.togli(nome_della_chiave(nome_archivio))
        except Exception as guasto:
            registro.avviso("sigillo.chiave_non_tolta", tipo=registro.tipo_di(guasto))
    registro.evento("sigillo.tolto")


def _accompagnamento(nome_archivio: str, quale: str) -> bytes:
    return f"{NOME}/sigillo/{VERSIONE}/{quale}/{nome_archivio}".encode("utf-8")


def _aead():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


def _dalla_firma(firma: bytes, sale: bytes, accompagnamento: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=sale,
                info=accompagnamento).derive(firma)


def _dalla_password(parola: str, sale: bytes, costo: int, blocco: int, parallelo: int) -> bytes:
    return hashlib.scrypt(parola.encode("utf-8"), salt=sale, n=costo, r=blocco, p=parallelo,
                          dklen=32, maxmem=costo * blocco * 200)


def _impronta(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def _firma_fissa(pubblica: bytes, sfida: bytes, firma: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        chiave = serialization.load_der_public_key(pubblica)
    except (ValueError, TypeError):
        return False
    if not isinstance(chiave, rsa.RSAPublicKey):
        return False
    try:
        chiave.verify(firma, sfida, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False
    return True


def _sigilla_con_hello(nome_archivio: str, password: str, hello) -> dict:
    chiave = nome_della_chiave(nome_archivio)
    pubblica = hello.crea(chiave)
    sfida = secrets.token_bytes(SFIDA)
    firma = hello.firma(chiave, sfida)
    if not _firma_fissa(pubblica, sfida, firma) and hello.firma(chiave, sfida) != firma:
        raise HelloNonFisso(NON_FISSO)
    sale = secrets.token_bytes(SALE)
    nonce = secrets.token_bytes(NONCE)
    accompagnamento = _accompagnamento(nome_archivio, HELLO)
    chiuso = _aead()(_dalla_firma(firma, sale, accompagnamento)).encrypt(
        nonce, password.encode("utf-8"), accompagnamento)
    return {"versione": VERSIONE, "modo": HELLO, "chiave": _impronta(pubblica),
            "sfida": sfida.hex(), "sale": sale.hex(), "nonce": nonce.hex(),
            "chiuso": chiuso.hex()}


def _apri_con_hello(nome_archivio: str, testa: dict, hello) -> str:
    chiave = nome_della_chiave(nome_archivio)
    pubblica = hello.chiave_pubblica(chiave)
    if pubblica is None or _impronta(pubblica) != testa["chiave"]:
        raise SigilloRotto(HELLO_RIFATTO)
    firma = hello.firma(chiave, bytes.fromhex(testa["sfida"]))
    accompagnamento = _accompagnamento(nome_archivio, HELLO)
    try:
        aperto = _aead()(_dalla_firma(firma, bytes.fromhex(testa["sale"]), accompagnamento)
                         ).decrypt(bytes.fromhex(testa["nonce"]),
                                   bytes.fromhex(testa["chiuso"]), accompagnamento)
    except Exception as guasto:
        raise SigilloRotto(HELLO_RIFATTO) from guasto
    return aperto.decode("utf-8")


def _sigilla_con_windows(nome_archivio: str, password: str, windows) -> dict:
    parola = _chiedi_a_windows(windows, MESSAGGIO_PER_LEGARE)
    sale = secrets.token_bytes(SALE)
    nonce = secrets.token_bytes(NONCE)
    accompagnamento = _accompagnamento(nome_archivio, WINDOWS)
    chiuso = _aead()(_dalla_password(parola, sale, COSTO, BLOCCO_SCRYPT, PARALLELO)).encrypt(
        nonce, password.encode("utf-8"), accompagnamento)
    protetto = windows.proteggi(nonce + chiuso)
    return {"versione": VERSIONE, "modo": WINDOWS, "n": COSTO, "r": BLOCCO_SCRYPT,
            "p": PARALLELO, "sale": sale.hex(), "protetto": protetto.hex()}


def _apri_con_windows(nome_archivio: str, testa: dict, windows) -> str:
    parola = _chiedi_a_windows(windows, MESSAGGIO_PER_APRIRE)
    try:
        dentro = windows.sproteggi(bytes.fromhex(testa["protetto"]))
    except OSError as guasto:
        raise SigilloRotto(ROTTO) from guasto
    nonce, chiuso = dentro[:NONCE], dentro[NONCE:]
    accompagnamento = _accompagnamento(nome_archivio, WINDOWS)
    chiave = _dalla_password(parola, bytes.fromhex(testa["sale"]),
                             int(testa["n"]), int(testa["r"]), int(testa["p"]))
    try:
        aperto = _aead()(chiave).decrypt(nonce, chiuso, accompagnamento)
    except Exception as guasto:
        raise PasswordDiWindowsCambiata(CAMBIATA) from guasto
    return aperto.decode("utf-8")


def _chiedi_a_windows(windows, messaggio: str) -> str:
    sbagliata = False
    for _ in range(TENTATIVI_WINDOWS):
        parola = windows.chiedi(messaggio, sbagliata)
        giusta = windows.e_giusta(parola)
        if giusta is not False:
            return parola
        registro.avviso("sigillo.password_windows_sbagliata")
        sbagliata = True
    raise PasswordDiWindowsSbagliata(TROPPE)


def _leggi(nome_archivio: str) -> dict | None:
    file = file_del_sigillo(nome_archivio)
    try:
        testo = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as guasto:
        raise SigilloRotto(ROTTO) from guasto
    try:
        testa = json.loads(testo)
    except ValueError as guasto:
        raise SigilloRotto(ROTTO) from guasto
    if not isinstance(testa, dict) or testa.get("versione") != VERSIONE \
            or testa.get("modo") not in (HELLO, WINDOWS):
        raise SigilloRotto(ROTTO)
    chiavi = ("chiave", "sfida", "sale", "nonce", "chiuso") if testa["modo"] == HELLO \
        else ("n", "r", "p", "sale", "protetto")
    if any(chiave not in testa for chiave in chiavi):
        raise SigilloRotto(ROTTO)
    return testa


def _scrivi(nome_archivio: str, testa: dict) -> None:
    file = file_del_sigillo(nome_archivio)
    file.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = file.with_suffix(".nuovo")
    provvisorio.write_text(json.dumps(testa), encoding="utf-8")
    provvisorio.replace(file)


def _nel_suo_filo(lavoro, davanti: bool = False):
    esito: dict = {}

    def dentro() -> None:
        try:
            from winrt import runtime

            try:
                runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
            except Exception:
                pass
            esito["valore"] = lavoro()
        except BaseException as guasto:
            esito["guasto"] = guasto

    filo = threading.Thread(target=dentro, name="windows-hello", daemon=True)
    filo.start()
    if davanti:
        _porta_davanti(filo)
    filo.join()
    if "guasto" in esito:
        raise esito["guasto"]
    return esito.get("valore")


def _porta_davanti(filo: threading.Thread) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
    except (OSError, AttributeError):
        return
    scadenza = time.monotonic() + ATTESA_DAVANTI
    while filo.is_alive() and time.monotonic() < scadenza:
        finestra = user32.FindWindowW(FINESTRA_DI_HELLO, None)
        if finestra:
            user32.SetForegroundWindow(finestra)
            return
        filo.join(0.1)


class PortaHello:

    def _moduli(self):
        from winrt.windows.security import credentials
        from winrt.windows.security.cryptography import CryptographicBuffer

        return credentials, CryptographicBuffer

    def c_e(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            credentials, _ = self._moduli()
            return bool(_nel_suo_filo(
                lambda: credentials.KeyCredentialManager.is_supported_async().get()))
        except Exception as guasto:
            registro.avviso("sigillo.hello_assente", tipo=registro.tipo_di(guasto))
            return False

    def _controlla(self, stato) -> None:
        credentials, _ = self._moduli()
        quale = credentials.KeyCredentialStatus
        if stato == quale.SUCCESS:
            return
        if stato in (quale.USER_CANCELED, quale.USER_PREFERS_PASSWORD):
            raise Annullato(ANNULLATO)
        if stato == quale.NOT_FOUND:
            raise SigilloRotto(HELLO_RIFATTO)
        if stato == quale.SECURITY_DEVICE_LOCKED:
            raise ErroreOfficina(BLOCCATO, codice="hello_bloccato")
        raise ErroreOfficina(NON_RISPONDE, codice="hello_non_risponde")

    def _in_byte(self, contenitore) -> bytes:
        _, CryptographicBuffer = self._moduli()
        return bytes(CryptographicBuffer.copy_to_byte_array(contenitore))

    def crea(self, nome: str) -> bytes:
        credentials, _ = self._moduli()
        risultato = _nel_suo_filo(lambda: credentials.KeyCredentialManager.request_create_async(
            nome, credentials.KeyCredentialCreationOption.REPLACE_EXISTING).get(),
            davanti=True)
        self._controlla(risultato.status)
        return self._in_byte(risultato.credential.retrieve_public_key_with_default_blob_type())

    def chiave_pubblica(self, nome: str) -> bytes | None:
        credentials, _ = self._moduli()
        risultato = _nel_suo_filo(
            lambda: credentials.KeyCredentialManager.open_async(nome).get())
        if risultato.status == credentials.KeyCredentialStatus.NOT_FOUND:
            return None
        self._controlla(risultato.status)
        return self._in_byte(risultato.credential.retrieve_public_key_with_default_blob_type())

    def firma(self, nome: str, sfida: bytes) -> bytes:
        credentials, CryptographicBuffer = self._moduli()

        def lavoro():
            aperta = credentials.KeyCredentialManager.open_async(nome).get()
            if aperta.status != credentials.KeyCredentialStatus.SUCCESS:
                return aperta
            return aperta.credential.request_sign_async(
                CryptographicBuffer.create_from_byte_array(sfida)).get()

        risultato = _nel_suo_filo(lavoro, davanti=True)
        self._controlla(risultato.status)
        return self._in_byte(risultato.result)

    def togli(self, nome: str) -> None:
        credentials, _ = self._moduli()
        _nel_suo_filo(lambda: credentials.KeyCredentialManager.delete_async(nome).get())


class PortaWindows:

    def c_e(self) -> bool:
        return sys.platform == "win32"

    def _librerie(self):
        import ctypes
        from ctypes import wintypes

        class CREDUI_INFOW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hwndParent", wintypes.HWND),
                        ("pszMessageText", wintypes.LPCWSTR),
                        ("pszCaptionText", wintypes.LPCWSTR),
                        ("hbmBanner", wintypes.HBITMAP)]

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        credui = ctypes.WinDLL("credui", use_last_error=True)
        credui.CredUIPromptForWindowsCredentialsW.argtypes = [
            ctypes.POINTER(CREDUI_INFOW), wintypes.DWORD, ctypes.POINTER(wintypes.ULONG),
            ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.BOOL), wintypes.DWORD]
        credui.CredUIPromptForWindowsCredentialsW.restype = wintypes.DWORD
        credui.CredUnPackAuthenticationBufferW.argtypes = [
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        credui.CredUnPackAuthenticationBufferW.restype = wintypes.BOOL
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
        advapi.LogonUserW.restype = wintypes.BOOL
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        user32 = ctypes.WinDLL("user32")
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        return (ctypes, wintypes, CREDUI_INFOW, DATA_BLOB, credui, advapi, crypt32, kernel,
                ole32, user32)

    def chiedi(self, messaggio: str, sbagliata: bool = False) -> str:
        (ctypes, wintypes, CREDUI_INFOW, _, credui, _, _, _, ole32,
         user32) = self._librerie()
        info = CREDUI_INFOW()
        info.cbSize = ctypes.sizeof(CREDUI_INFOW)
        info.hwndParent = user32.GetForegroundWindow()
        info.pszMessageText = messaggio
        info.pszCaptionText = NOME
        pacchetto = wintypes.ULONG(0)
        uscita = ctypes.c_void_p()
        quanto = wintypes.ULONG(0)
        salva = wintypes.BOOL(False)
        esito = credui.CredUIPromptForWindowsCredentialsW(
            ctypes.byref(info), ERROR_LOGON_FAILURE if sbagliata else 0,
            ctypes.byref(pacchetto), None, 0, ctypes.byref(uscita), ctypes.byref(quanto),
            ctypes.byref(salva), CREDUIWIN_ENUMERATE_CURRENT_USER)
        if esito == ERROR_CANCELLED:
            raise Annullato(ANNULLATO)
        if esito != 0 or not uscita.value:
            raise ErroreOfficina(FINESTRA_NON_APERTA, codice="credui_non_aperta")
        utente = ctypes.create_unicode_buffer(514)
        dominio = ctypes.create_unicode_buffer(338)
        parola = ctypes.create_unicode_buffer(514)
        lunghezze = [wintypes.DWORD(514), wintypes.DWORD(338), wintypes.DWORD(514)]
        try:
            if not credui.CredUnPackAuthenticationBufferW(
                    CRED_PACK_PROTECTED_CREDENTIALS, uscita, quanto.value,
                    utente, ctypes.byref(lunghezze[0]), dominio, ctypes.byref(lunghezze[1]),
                    parola, ctypes.byref(lunghezze[2])):
                raise ErroreOfficina(FINESTRA_NON_APERTA, codice="credui_non_letta")
            self._chi = (utente.value, dominio.value)
            return parola.value
        finally:
            ctypes.memset(uscita, 0, quanto.value)
            ole32.CoTaskMemFree(uscita)
            ctypes.memset(parola, 0, ctypes.sizeof(parola))

    def e_giusta(self, parola: str) -> bool | None:
        (ctypes, wintypes, _, _, _, advapi, _, kernel, _, _) = self._librerie()
        utente, dominio = getattr(self, "_chi", ("", ""))
        if "\\" in utente:
            dominio, utente = utente.split("\\", 1)
        if not dominio and "@" not in utente:
            dominio = "."
        maniglia = wintypes.HANDLE()
        if advapi.LogonUserW(utente, dominio or None, parola, LOGON32_LOGON_INTERACTIVE,
                             LOGON32_PROVIDER_DEFAULT, ctypes.byref(maniglia)):
            kernel.CloseHandle(maniglia)
            return True
        if ctypes.get_last_error() == ERROR_LOGON_FAILURE:
            return False
        registro.avviso("sigillo.password_windows_non_controllabile",
                        numero=ctypes.get_last_error())
        return None

    def _dpapi(self, dati: bytes, chiudi: bool) -> bytes:
        (ctypes, _, _, DATA_BLOB, _, _, crypt32, kernel, _, _) = self._librerie()
        sorgente = ctypes.create_string_buffer(dati, len(dati))
        dentro = DATA_BLOB(len(dati), ctypes.cast(sorgente, ctypes.POINTER(ctypes.c_char)))
        sale = ctypes.create_string_buffer(ENTROPIA, len(ENTROPIA))
        aggiunta = DATA_BLOB(len(ENTROPIA), ctypes.cast(sale, ctypes.POINTER(ctypes.c_char)))
        fuori = DATA_BLOB()
        if chiudi:
            fatto = crypt32.CryptProtectData(ctypes.byref(dentro), NOME, ctypes.byref(aggiunta),
                                             None, None, CRYPTPROTECT_UI_FORBIDDEN,
                                             ctypes.byref(fuori))
        else:
            fatto = crypt32.CryptUnprotectData(ctypes.byref(dentro), None,
                                               ctypes.byref(aggiunta), None, None,
                                               CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(fuori))
        if not fatto:
            raise OSError(ctypes.get_last_error(), "DPAPI")
        try:
            return ctypes.string_at(fuori.pbData, fuori.cbData)
        finally:
            ctypes.memset(fuori.pbData, 0, fuori.cbData)
            kernel.LocalFree(fuori.pbData)

    def proteggi(self, dati: bytes) -> bytes:
        return self._dpapi(dati, True)

    def sproteggi(self, dati: bytes) -> bytes:
        return self._dpapi(dati, False)
