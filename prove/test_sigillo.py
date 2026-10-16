from __future__ import annotations

import sys

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from officina.errori import ErroreOfficina
from officina.programma import sigillo

CASSAFORTE = "tre parole lunghe e facili"
DI_WINDOWS = "cavallo batteria graffetta"


class FintoHello:

    def __init__(self, c_e: bool = True, casuale: bool = False):
        self.chiavi: dict = {}
        self._c_e = c_e
        self.casuale = casuale
        self.annulla = False
        self.firme = 0

    def c_e(self) -> bool:
        return self._c_e

    def _pubblica(self, nome: str) -> bytes:
        return self.chiavi[nome].public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    def crea(self, nome: str) -> bytes:
        self.chiavi[nome] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return self._pubblica(nome)

    def chiave_pubblica(self, nome: str) -> bytes | None:
        return self._pubblica(nome) if nome in self.chiavi else None

    def firma(self, nome: str, sfida: bytes) -> bytes:
        if self.annulla:
            raise sigillo.Annullato(sigillo.ANNULLATO)
        if nome not in self.chiavi:
            raise sigillo.SigilloRotto(sigillo.HELLO_RIFATTO)
        self.firme += 1
        if self.casuale:
            return self.chiavi[nome].sign(
                sfida, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                   salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
        return self.chiavi[nome].sign(sfida, padding.PKCS1v15(), hashes.SHA256())

    def togli(self, nome: str) -> None:
        self.chiavi.pop(nome, None)


class FintoWindows:

    def __init__(self, vera: str = DI_WINDOWS, scritte: list[str] | None = None,
                 c_e: bool = True, utente: bytes = b"utente-1"):
        self.vera = vera
        self.scritte = list(scritte) if scritte is not None else [vera] * 5
        self.chieste: list[bool] = []
        self._c_e = c_e
        self.utente = utente

    def c_e(self) -> bool:
        return self._c_e

    def chiedi(self, messaggio: str, sbagliata: bool = False) -> str:
        self.chieste.append(sbagliata)
        if not self.scritte:
            raise sigillo.Annullato(sigillo.ANNULLATO)
        return self.scritte.pop(0)

    def e_giusta(self, parola: str) -> bool | None:
        return parola == self.vera

    def proteggi(self, dati: bytes) -> bytes:
        return self.utente + bytes(b ^ 0x5A for b in dati)

    def sproteggi(self, dati: bytes) -> bytes:
        if not dati.startswith(self.utente):
            raise OSError("un altro utente di Windows")
        return bytes(b ^ 0x5A for b in dati[len(self.utente):])


@pytest.fixture(autouse=True)
def casa_finta(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    return tmp_path / "casa"


def test_con_windows_hello_la_password_della_cassaforte_si_chiude_e_si_riapre():
    hello, windows = FintoHello(), FintoWindows()
    assert sigillo.sigilla("reale", CASSAFORTE, hello, windows) == sigillo.HELLO
    file = sigillo.file_del_sigillo("reale")
    assert file.is_file()
    assert CASSAFORTE not in file.read_text(encoding="utf-8")
    assert sigillo.modo("reale") == sigillo.HELLO
    assert sigillo.apri("reale", hello, windows) == CASSAFORTE
    assert windows.chieste == []


def test_se_annulli_windows_hello_la_cassaforte_resta_chiusa_e_il_sigillo_resta():
    hello = FintoHello()
    sigillo.sigilla("reale", CASSAFORTE, hello, FintoWindows())
    hello.annulla = True
    with pytest.raises(sigillo.Annullato):
        sigillo.apri("reale", hello)
    assert sigillo.c_e("reale")
    hello.annulla = False
    assert sigillo.apri("reale", hello) == CASSAFORTE


def test_se_windows_hello_viene_rifatto_il_sigillo_si_dice_rotto():
    hello = FintoHello()
    sigillo.sigilla("reale", CASSAFORTE, hello, FintoWindows())
    hello.crea(sigillo.nome_della_chiave("reale"))
    with pytest.raises(sigillo.SigilloRotto, match="rifatto"):
        sigillo.apri("reale", hello)
    hello.togli(sigillo.nome_della_chiave("reale"))
    with pytest.raises(sigillo.SigilloRotto, match="rifatto"):
        sigillo.apri("reale", hello)
    assert hello.firme == 1


def test_se_windows_hello_non_da_sempre_la_stessa_firma_si_usa_la_password_di_windows():
    hello, windows = FintoHello(casuale=True), FintoWindows()
    assert sigillo.sigilla("reale", CASSAFORTE, hello, windows) == sigillo.WINDOWS
    assert hello.firme == 2
    assert hello.chiavi == {}
    assert windows.chieste == [False]
    assert sigillo.apri("reale", hello, windows) == CASSAFORTE


def test_senza_windows_hello_si_usa_la_password_di_windows():
    hello, windows = FintoHello(c_e=False), FintoWindows()
    assert sigillo.come_si_puo(hello, windows) == sigillo.WINDOWS
    assert sigillo.sigilla("reale", CASSAFORTE, hello, windows) == sigillo.WINDOWS
    testo = sigillo.file_del_sigillo("reale").read_text(encoding="utf-8")
    assert CASSAFORTE not in testo and DI_WINDOWS not in testo
    assert sigillo.apri("reale", hello, windows) == CASSAFORTE
    assert hello.chiavi == {}


def test_la_password_di_windows_sbagliata_si_richiede_e_dopo_tre_volte_ci_si_ferma():
    sigillo.sigilla("reale", CASSAFORTE, FintoHello(c_e=False), FintoWindows())
    tre_sbagliate = FintoWindows(scritte=["no", "nemmeno", "ancora no", DI_WINDOWS])
    with pytest.raises(sigillo.PasswordDiWindowsSbagliata):
        sigillo.apri("reale", FintoHello(c_e=False), tre_sbagliate)
    assert tre_sbagliate.chieste == [False, True, True]
    una_sbagliata = FintoWindows(scritte=["no", DI_WINDOWS])
    assert sigillo.apri("reale", FintoHello(c_e=False), una_sbagliata) == CASSAFORTE
    assert una_sbagliata.chieste == [False, True]


def test_se_la_password_di_windows_cambia_si_dice_e_non_si_apre():
    sigillo.sigilla("reale", CASSAFORTE, FintoHello(c_e=False), FintoWindows())
    cambiata = FintoWindows(vera="una password nuova")
    with pytest.raises(sigillo.PasswordDiWindowsCambiata, match="cambiata"):
        sigillo.apri("reale", FintoHello(c_e=False), cambiata)


def test_un_altro_utente_di_windows_non_apre_il_sigillo():
    sigillo.sigilla("reale", CASSAFORTE, FintoHello(c_e=False), FintoWindows())
    with pytest.raises(sigillo.SigilloRotto):
        sigillo.apri("reale", FintoHello(c_e=False), FintoWindows(utente=b"utente-2"))


@pytest.mark.parametrize("con_hello", [True, False])
def test_il_sigillo_di_un_archivio_non_apre_un_altro_archivio(con_hello):
    hello, windows = FintoHello(c_e=con_hello), FintoWindows()
    sigillo.sigilla("reale", CASSAFORTE, hello, windows)
    altro = sigillo.file_del_sigillo("prova")
    altro.write_bytes(sigillo.file_del_sigillo("reale").read_bytes())
    with pytest.raises(sigillo.SigilloRotto):
        sigillo.apri("prova", hello, windows)


def test_un_sigillo_rovinato_si_dice_rotto():
    file = sigillo.file_del_sigillo("reale")
    file.parent.mkdir(parents=True)
    file.write_text("{non è json", encoding="utf-8")
    assert sigillo.modo("reale") is None
    assert not sigillo.c_e("reale")
    with pytest.raises(sigillo.SigilloRotto):
        sigillo.apri("reale", FintoHello(), FintoWindows())
    file.write_text('{"versione": 1, "modo": "hello"}', encoding="utf-8")
    with pytest.raises(sigillo.SigilloRotto):
        sigillo.apri("reale", FintoHello(), FintoWindows())


def test_senza_sigillo_aprire_dice_che_manca():
    with pytest.raises(sigillo.SigilloRotto):
        sigillo.apri("reale", FintoHello(), FintoWindows())


def test_togliere_il_sigillo_cancella_il_file_e_la_chiave_di_windows_hello():
    hello = FintoHello()
    sigillo.sigilla("reale", CASSAFORTE, hello, FintoWindows())
    sigillo.sigilla("prova", CASSAFORTE, hello, FintoWindows())
    sigillo.togli("reale", hello)
    assert not sigillo.file_del_sigillo("reale").exists()
    assert list(hello.chiavi) == [sigillo.nome_della_chiave("prova")]
    assert sigillo.apri("prova", hello) == CASSAFORTE


def test_senza_windows_hello_ne_password_di_windows_non_si_sigilla():
    with pytest.raises(ErroreOfficina) as preso:
        sigillo.sigilla("reale", CASSAFORTE, FintoHello(c_e=False), FintoWindows(c_e=False))
    assert preso.value.codice == "sigillo_impossibile"
    assert not sigillo.file_del_sigillo("reale").exists()


def test_un_nome_strano_non_esce_dalla_cartella_dei_sigilli(casa_finta):
    file = sigillo.file_del_sigillo("../../fuori")
    assert file.parent == casa_finta / "sigilli"
    assert file.name != "fuori.json"


def test_la_firma_di_windows_hello_si_riconosce_fissa():
    chiave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pubblica = chiave.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    sfida = b"x" * sigillo.SFIDA
    fissa = chiave.sign(sfida, padding.PKCS1v15(), hashes.SHA256())
    casuale = chiave.sign(sfida, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                             salt_length=padding.PSS.MAX_LENGTH),
                          hashes.SHA256())
    assert sigillo._firma_fissa(pubblica, sfida, fissa)
    assert not sigillo._firma_fissa(pubblica, sfida, casuale)
    assert not sigillo._firma_fissa(b"non una chiave", sfida, fissa)


@pytest.mark.skipif(sys.platform == "win32", reason="fuori da Windows")
def test_fuori_da_windows_non_ci_sono_ne_hello_ne_la_password_di_windows():
    assert not sigillo.PortaHello().c_e()
    assert not sigillo.PortaWindows().c_e()
    assert sigillo.come_si_puo() is None
