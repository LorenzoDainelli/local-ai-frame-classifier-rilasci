from __future__ import annotations

import builtins
import json
import os
import stat
from types import SimpleNamespace

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import disco, metadati
from officina.sicuro.disco import percorso_lungo

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")
su_windows = pytest.mark.skipif(os.name != "nt", reason="prove con Windows vero")

ANNO_2001 = 978_307_200 * 10 ** 9


def _file(cartella, nome="IMG_1.jpg", dati=b"foto"):
    percorso = cartella / nome
    percorso.write_bytes(dati)
    return percorso


def _stato_finto(modo=stat.S_IFREG | 0o644, attributi=None, rimando=0, **altro):
    valori = {"st_mode": modo, "st_size": 10, "st_mtime_ns": ANNO_2001 + 7,
              "st_atime_ns": ANNO_2001 + 9, "st_ctime_ns": ANNO_2001 + 3,
              "st_ino": 1, "st_dev": 2, "st_uid": 0, "st_gid": 0,
              "st_reparse_tag": rimando}
    if attributi is not None:
        valori["st_file_attributes"] = attributi
    valori.update(altro)
    return SimpleNamespace(**valori)


@pytest.fixture
def finto_windows(monkeypatch):
    chiamate = {"flussi": 0, "permessi": 0, "creazione": [], "attributi": []}

    def flussi(dove):
        chiamate["flussi"] += 1
        return [("Zone.Identifier", 26), ("com.apple.metadata", 4)], None

    def permessi(dove):
        chiamate["permessi"] += 1
        return "O:BAG:SYD:(A;;FA;;;SY)"

    monkeypatch.setattr(disco, "WINDOWS", True)
    monkeypatch.setattr(metadati, "_flussi_windows", flussi)
    monkeypatch.setattr(metadati, "_sddl_windows", permessi)
    monkeypatch.setattr(metadati, "_imposta_creazione",
                        lambda dove, ns: chiamate["creazione"].append((dove, ns)))
    monkeypatch.setattr(metadati, "_imposta_attributi",
                        lambda dove, valore: chiamate["attributi"].append((dove, valore)))
    return chiamate


@su_linux
def test_le_date_di_un_file_si_leggono_al_nanosecondo(tmp_path):
    percorso = _file(tmp_path)
    os.utime(percorso, ns=(ANNO_2001 + 123_456_789, ANNO_2001 + 987_654_321))
    letto = metadati.leggi(percorso)
    assert letto.tipo == metadati.FILE and letto.dimensione == 4
    assert letto.metadati["modifica"] == ANNO_2001 + 987_654_321
    assert letto.metadati["accesso"] == ANNO_2001 + 123_456_789
    assert not letto.cloud and letto.flussi == () and letto.avvisi == ()


@su_linux
def test_i_permessi_si_salvano(tmp_path):
    percorso = _file(tmp_path)
    os.chmod(percorso, 0o640)
    permessi = metadati.leggi(percorso).metadati["permessi"]
    assert permessi == {"modo": 0o640, "utente": os.getuid(), "gruppo": os.getgid()}


@su_linux
def test_leggere_non_apre_il_file(tmp_path, monkeypatch):
    percorso = _file(tmp_path)
    prima = os.stat(percorso)

    def vietato(*argomenti, **chiavi):
        raise AssertionError("il file non si apre per leggere le sue date")

    monkeypatch.setattr(builtins, "open", vietato)
    monkeypatch.setattr(os, "open", vietato)
    letto = metadati.leggi(percorso)
    monkeypatch.undo()
    assert letto.metadati["accesso"] == prima.st_atime_ns
    assert os.stat(percorso).st_atime_ns == prima.st_atime_ns


@su_linux
def test_una_cartella_anche_vuota(tmp_path):
    cartella = tmp_path / "Vuota"
    cartella.mkdir()
    os.utime(cartella, ns=(ANNO_2001, ANNO_2001 + 5))
    letto = metadati.leggi(cartella)
    assert letto.tipo == metadati.CARTELLA and letto.dimensione == 0
    assert letto.metadati["modifica"] == ANNO_2001 + 5


@su_linux
@pytest.mark.parametrize("bersaglio", ["IMG_1.jpg", "../fuori/IMG_2.jpg", "/assoluto/x",
                                       "non_esiste", "Cartella", "lettere è 🐶"])
def test_un_collegamento_si_salva_senza_seguirlo(tmp_path, bersaglio):
    _file(tmp_path)
    (tmp_path / "Cartella").mkdir()
    collegamento = tmp_path / "collegamento"
    os.symlink(bersaglio, collegamento)
    letto = metadati.leggi(collegamento)
    assert letto.tipo == metadati.COLLEGAMENTO and letto.dimensione == 0
    assert letto.metadati["bersaglio"] == bersaglio
    assert letto.metadati["collegamento"] == "simbolico"
    assert "permessi" not in letto.metadati and letto.flussi == ()


@su_linux
def test_un_collegamento_che_gira_in_tondo_non_blocca(tmp_path):
    os.symlink("b", tmp_path / "a")
    os.symlink("a", tmp_path / "b")
    assert metadati.leggi(tmp_path / "a").metadati["bersaglio"] == "b"


@su_linux
def test_un_file_speciale_si_riconosce(tmp_path):
    os.mkfifo(tmp_path / "tubo")
    letto = metadati.leggi(tmp_path / "tubo")
    assert letto.tipo == metadati.SPECIALE and "file_speciale" in letto.avvisi


@su_linux
def test_nomi_con_lettere_rotte(tmp_path):
    nome = os.fsdecode(b"foto \xff\xfe.jpg")
    percorso = _file(tmp_path, nome)
    os.symlink(os.fsdecode(b"\xff"), tmp_path / "rotto")
    assert metadati.leggi(percorso).tipo == metadati.FILE
    bersaglio = metadati.leggi(tmp_path / "rotto").metadati["bersaglio"]
    assert bersaglio == os.fsdecode(b"\xff")
    assert json.loads(json.dumps(bersaglio)) == bersaglio


def test_il_segno_cambia_se_il_file_cambia(tmp_path):
    percorso = _file(tmp_path)
    os.utime(percorso, ns=(ANNO_2001, ANNO_2001))
    prima = metadati.leggi(percorso).segno
    assert metadati.leggi(percorso).segno == prima
    percorso.write_bytes(b"altro!")
    os.utime(percorso, ns=(ANNO_2001, ANNO_2001))
    assert metadati.leggi(percorso).segno != prima


def test_il_segno_non_cambia_leggendo(tmp_path):
    percorso = _file(tmp_path)
    prima = metadati.leggi(percorso).segno
    percorso.read_bytes()
    assert metadati.leggi(percorso).segno == prima


@pytest.mark.parametrize("modo, tipo", [
    (stat.S_IFREG | 0o644, metadati.FILE), (stat.S_IFDIR | 0o755, metadati.CARTELLA),
    (stat.S_IFLNK | 0o777, metadati.COLLEGAMENTO), (stat.S_IFIFO | 0o644, metadati.SPECIALE),
    (stat.S_IFSOCK | 0o644, metadati.SPECIALE), (stat.S_IFCHR | 0o644, metadati.SPECIALE),
])
def test_i_tipi(modo, tipo):
    assert metadati.tipo_di(_stato_finto(modo)) == tipo


@pytest.mark.parametrize("rimando, tipo", [
    (metadati.GIUNZIONE, metadati.COLLEGAMENTO), (metadati.SIMBOLICO, metadati.COLLEGAMENTO),
    (0x9000001A, metadati.CARTELLA), (0x80000013, metadati.CARTELLA),
    (0x8000001B, metadati.CARTELLA), (0, metadati.CARTELLA),
])
def test_i_rimandi_di_windows_su_una_cartella(rimando, tipo):
    stato = _stato_finto(stat.S_IFDIR | 0o777, attributi=0x10 | 0x400, rimando=rimando)
    assert metadati.tipo_di(stato) == tipo


def test_su_windows_una_giunzione_e_un_collegamento(finto_windows, monkeypatch):
    monkeypatch.setattr(metadati, "_bersaglio", lambda dove: "\\\\?\\D:\\Foto vere")
    stato = _stato_finto(stat.S_IFDIR | 0o777, attributi=0x10 | 0x400,
                         rimando=metadati.GIUNZIONE)
    letto = metadati.leggi("C:\\Foto\\Giunzione", stato)
    assert letto.tipo == metadati.COLLEGAMENTO
    assert letto.metadati["collegamento"] == "giunzione"
    assert letto.metadati["verso_cartella"] is True
    assert letto.metadati["bersaglio"] == "\\\\?\\D:\\Foto vere"
    assert letto.metadati["rimando"] == metadati.GIUNZIONE
    assert finto_windows["flussi"] == 0 and finto_windows["permessi"] == 0


def test_su_windows_un_collegamento_a_un_file(finto_windows, monkeypatch):
    monkeypatch.setattr(metadati, "_bersaglio", lambda dove: "..\\IMG_1.jpg")
    stato = _stato_finto(stat.S_IFLNK | 0o777, attributi=0x20 | 0x400,
                         rimando=metadati.SIMBOLICO)
    letto = metadati.leggi("C:\\Foto\\link.jpg", stato)
    assert letto.metadati["collegamento"] == "simbolico"
    assert letto.metadati["verso_cartella"] is False


def test_su_windows_un_bersaglio_illeggibile_si_dice(finto_windows, monkeypatch):
    def guasto(dove):
        raise OSError(5, "Accesso negato")

    monkeypatch.setattr(metadati, "_bersaglio", guasto)
    stato = _stato_finto(stat.S_IFLNK | 0o777, attributi=0x400, rimando=metadati.SIMBOLICO)
    letto = metadati.leggi("C:\\x", stato)
    assert "bersaglio_illeggibile" in letto.avvisi and "bersaglio" not in letto.metadati


def test_su_windows_attributi_flussi_e_permessi(finto_windows):
    stato = _stato_finto(attributi=0x1 | 0x2 | 0x20, st_birthtime_ns=ANNO_2001 + 1)
    letto = metadati.leggi("C:\\Foto\\IMG_1.jpg", stato)
    assert letto.metadati["attributi"] == 0x23
    assert letto.metadati["creazione"] == ANNO_2001 + 1
    assert letto.metadati["permessi"] == {"sddl": "O:BAG:SYD:(A;;FA;;;SY)"}
    assert letto.flussi == (("Zone.Identifier", 26), ("com.apple.metadata", 4))
    assert letto.avvisi == ()


def test_su_windows_senza_data_di_nascita_vale_la_vecchia(finto_windows):
    letto = metadati.leggi("C:\\x", _stato_finto(attributi=0x20))
    assert letto.metadati["creazione"] == ANNO_2001 + 3


def test_fuori_da_windows_la_data_di_creazione_non_si_inventa(monkeypatch):
    monkeypatch.setattr(disco, "WINDOWS", False)
    letto = metadati.leggi("/x", _stato_finto())
    assert "creazione" not in letto.metadati


def test_la_data_di_nascita_del_mac(monkeypatch):
    monkeypatch.setattr(disco, "WINDOWS", False)
    letto = metadati.leggi("/x", _stato_finto(st_birthtime=978_307_200.5))
    assert letto.metadati["creazione"] == ANNO_2001 + 500_000_000


@pytest.mark.parametrize("attributi", [0x400000, 0x40000, 0x1000, 0x400000 | 0x400 | 0x20])
def test_su_windows_un_file_solo_nel_cloud_non_si_tocca(finto_windows, attributi):
    letto = metadati.leggi("C:\\OneDrive\\IMG_1.jpg",
                           _stato_finto(attributi=attributi, rimando=0x9000001A))
    assert letto.cloud and letto.tipo == metadati.FILE and "solo_nel_cloud" in letto.avvisi
    assert finto_windows["flussi"] == 0 and finto_windows["permessi"] == 0
    assert letto.metadati["attributi"] == attributi


def test_su_windows_una_cartella_del_cloud_si_legge(finto_windows):
    letto = metadati.leggi("C:\\OneDrive", _stato_finto(stat.S_IFDIR | 0o777,
                                                       attributi=0x10 | 0x400000))
    assert letto.tipo == metadati.CARTELLA and not letto.cloud


def test_su_windows_permessi_e_flussi_illeggibili_si_dicono(finto_windows, monkeypatch):
    monkeypatch.setattr(metadati, "_sddl_windows", lambda dove: None)
    monkeypatch.setattr(metadati, "_flussi_windows", lambda dove: ([("a", 1)], 5))
    letto = metadati.leggi("C:\\x", _stato_finto(attributi=0x20))
    assert set(letto.avvisi) == {"permessi_illeggibili", "flussi_illeggibili"}
    assert "permessi" not in letto.metadati and letto.flussi == (("a", 1),)


def test_su_windows_permessi_lunghissimi_non_bloccano(finto_windows, monkeypatch):
    monkeypatch.setattr(metadati, "_sddl_windows",
                        lambda dove: "D:" + "(A;;FA;;;S-1-5-21-1)" * 5000)
    letto = metadati.leggi("C:\\x", _stato_finto(attributi=0x20))
    assert "permessi" not in letto.metadati and "permessi_troppo_lunghi" in letto.avvisi


@pytest.mark.parametrize("nome", ["Zone.Identifier", "com.apple.ResourceFork", "è 🐶",
                                  "x" * 255, "con spazio", "punto."])
def test_nomi_di_flusso_buoni(nome):
    assert metadati.nome_di_flusso_buono(nome)


@pytest.mark.parametrize("nome", ["", "a:b", "a\\b", "a/b", "a\x00b", "x" * 256, None, 5,
                                  ":$DATA"])
def test_nomi_di_flusso_strani(nome):
    assert not metadati.nome_di_flusso_buono(nome)


def test_il_percorso_del_flusso(finto_windows):
    assert metadati.percorso_del_flusso("C:\\Foto\\IMG_1.jpg", "Zone.Identifier") == (
        "C:\\Foto\\IMG_1.jpg:Zone.Identifier:$DATA")
    with pytest.raises(ErroreOfficina) as scoppio:
        metadati.percorso_del_flusso("C:\\x", "a:b")
    assert scoppio.value.codice == "flusso_strano"


def test_i_flussi_ci_sono_solo_su_windows(monkeypatch):
    monkeypatch.setattr(disco, "WINDOWS", False)
    with pytest.raises(ErroreOfficina) as scoppio:
        metadati.apri_flusso("/x", "Zone.Identifier")
    assert scoppio.value.codice == "flussi_solo_windows"


def test_rimettere_le_date_al_nanosecondo(tmp_path):
    percorso = _file(tmp_path)
    avvisi = metadati.rimetti(percorso, {"modifica": ANNO_2001 + 111,
                                         "accesso": ANNO_2001 + 222}, metadati.FILE)
    stato = os.stat(percorso)
    assert avvisi == []
    assert stato.st_mtime_ns == ANNO_2001 + 111 and stato.st_atime_ns == ANNO_2001 + 222


def test_rimettere_le_date_di_una_cartella(tmp_path):
    cartella = tmp_path / "c"
    cartella.mkdir()
    metadati.rimetti(cartella, {"modifica": ANNO_2001, "accesso": ANNO_2001}, metadati.CARTELLA)
    assert os.stat(cartella).st_mtime_ns == ANNO_2001


def test_senza_ultimo_accesso_vale_la_modifica(tmp_path):
    percorso = _file(tmp_path)
    metadati.rimetti(percorso, {"modifica": ANNO_2001}, metadati.FILE)
    assert os.stat(percorso).st_atime_ns == ANNO_2001


def test_letto_e_rimesso_torna_uguale(tmp_path):
    percorso = _file(tmp_path)
    os.utime(percorso, ns=(ANNO_2001 + 5, ANNO_2001 + 6))
    letto = metadati.leggi(percorso)
    copia = _file(tmp_path, "copia.jpg")
    metadati.rimetti(copia, letto.metadati, letto.tipo)
    assert metadati.leggi(copia).metadati["modifica"] == letto.metadati["modifica"]
    assert metadati.leggi(copia).metadati["accesso"] == letto.metadati["accesso"]


@su_linux
def test_i_permessi_non_si_rimettono(tmp_path):
    percorso = _file(tmp_path)
    os.chmod(percorso, 0o600)
    metadati.rimetti(percorso, {"modifica": ANNO_2001,
                                "permessi": {"modo": 0o777, "utente": 0, "gruppo": 0}},
                     metadati.FILE)
    assert stat.S_IMODE(os.stat(percorso).st_mode) == 0o600


@pytest.mark.parametrize("strano", [{"modifica": "ieri"}, {"modifica": 1.5}, {"modifica": None},
                                    {"modifica": True}, {}, {"accesso": 5}])
def test_date_strane_non_si_rimettono(tmp_path, strano):
    percorso = _file(tmp_path)
    prima = os.stat(percorso).st_mtime_ns
    assert metadati.rimetti(percorso, strano, metadati.FILE) == []
    assert os.stat(percorso).st_mtime_ns == prima


def test_date_fuori_misura_si_dicono(tmp_path):
    percorso = _file(tmp_path)
    avvisi = metadati.rimetti(percorso, {"modifica": 10 ** 40}, metadati.FILE)
    assert avvisi == ["date_non_rimesse"]


def test_un_file_sparito_non_fa_crollare(tmp_path):
    avvisi = metadati.rimetti(tmp_path / "non_c_e", {"modifica": ANNO_2001}, metadati.FILE)
    assert avvisi == ["date_non_rimesse"]


def test_ai_collegamenti_non_si_rimette_niente(tmp_path, finto_windows):
    assert metadati.rimetti(tmp_path / "x", {"modifica": 1, "attributi": 1},
                            metadati.COLLEGAMENTO) == []
    assert finto_windows["attributi"] == [] and finto_windows["creazione"] == []


@pytest.mark.parametrize("letti, rimessi", [
    (0x1 | 0x2 | 0x20, 0x23), (0x10, metadati.NORMALE), (0x10 | 0x2, 0x2),
    (0x1 | 0x400 | 0x800 | 0x4000 | 0x200 | 0x400000 | 0x80000, 0x1),
    (0x4 | 0x2000 | 0x100, 0x2104), (0, metadati.NORMALE), (0x80, metadati.NORMALE),
])
def test_su_windows_si_rimettono_solo_gli_attributi_sicuri(tmp_path, finto_windows,
                                                           letti, rimessi):
    percorso = _file(tmp_path)
    assert metadati.rimetti(percorso, {"modifica": ANNO_2001, "attributi": letti,
                                       "creazione": ANNO_2001 - 5}, metadati.FILE) == []
    assert finto_windows["attributi"] == [(str(percorso), rimessi)]
    assert finto_windows["creazione"] == [(str(percorso), ANNO_2001 - 5)]


def test_su_windows_le_date_vanno_prima_degli_attributi(tmp_path, finto_windows, monkeypatch):
    ordine = []
    monkeypatch.setattr(metadati.os, "utime", lambda *a, **k: ordine.append("date"))
    monkeypatch.setattr(metadati, "_imposta_creazione", lambda d, n: ordine.append("nascita"))
    monkeypatch.setattr(metadati, "_imposta_attributi", lambda d, v: ordine.append("attributi"))
    metadati.rimetti(tmp_path / "x", {"modifica": 1, "creazione": 1, "attributi": 1},
                     metadati.FILE)
    assert ordine == ["date", "nascita", "attributi"]


def test_su_windows_i_guasti_si_dicono_e_non_fermano(tmp_path, finto_windows, monkeypatch):
    def guasto(*argomenti):
        raise OSError(5, "Accesso negato")

    monkeypatch.setattr(metadati, "_imposta_creazione", guasto)
    monkeypatch.setattr(metadati, "_imposta_attributi", guasto)
    percorso = _file(tmp_path)
    avvisi = metadati.rimetti(percorso, {"modifica": ANNO_2001, "creazione": 1,
                                         "attributi": 1}, metadati.FILE)
    assert avvisi == ["creazione_non_rimessa", "attributi_non_rimessi"]
    assert os.stat(percorso).st_mtime_ns == ANNO_2001


@su_linux
@pytest.mark.parametrize("bersaglio", ["IMG_1.jpg", "../su", "/assoluto", "non_esiste",
                                       "è 🐶"])
def test_un_collegamento_si_rifa_uguale(tmp_path, bersaglio):
    nuovo = tmp_path / "nuovo"
    metadati.crea_collegamento(nuovo, {"bersaglio": bersaglio, "collegamento": "simbolico"})
    assert os.readlink(nuovo) == bersaglio
    assert metadati.leggi(nuovo).metadati["bersaglio"] == bersaglio


@su_linux
def test_una_giunzione_fuori_da_windows_diventa_un_collegamento(tmp_path):
    nuovo = tmp_path / "giunzione"
    metadati.crea_collegamento(nuovo, {"bersaglio": "/foto", "collegamento": "giunzione",
                                       "verso_cartella": True})
    assert os.readlink(nuovo) == "/foto"


@pytest.mark.parametrize("dati", [{}, {"bersaglio": ""}, {"bersaglio": None},
                                  {"bersaglio": 5}, {"bersaglio": "a\x00b"}])
def test_un_collegamento_senza_bersaglio_non_si_rifa(tmp_path, dati):
    with pytest.raises(ErroreOfficina) as scoppio:
        metadati.crea_collegamento(tmp_path / "x", dati)
    assert scoppio.value.codice == "collegamento_senza_bersaglio"


def test_un_collegamento_sopra_un_file_che_c_e_non_si_rifa(tmp_path):
    percorso = _file(tmp_path)
    with pytest.raises(ErroreOfficina) as scoppio:
        metadati.crea_collegamento(percorso, {"bersaglio": "altro"})
    assert scoppio.value.codice == "collegamento_non_creato"
    assert percorso.read_bytes() == b"foto"


def test_su_windows_la_giunzione_si_rifa_col_suo_disco(tmp_path, finto_windows, monkeypatch):
    fatte = []
    monkeypatch.setattr(metadati, "_crea_giunzione", lambda verso, dove: fatte.append(verso))
    metadati.crea_collegamento(tmp_path / "g", {"bersaglio": "\\\\?\\D:\\Foto",
                                                "collegamento": "giunzione"})
    assert fatte == ["D:\\Foto"]


def test_su_windows_una_giunzione_verso_un_disco_senza_lettera(tmp_path, finto_windows):
    with pytest.raises(ErroreOfficina) as scoppio:
        metadati.crea_collegamento(tmp_path / "g", {
            "bersaglio": "\\\\?\\Volume{1b3b1146-4076-11e1-84aa-806e6f6e6963}\\",
            "collegamento": "giunzione"})
    assert scoppio.value.codice == "collegamento_non_creato"


@pytest.mark.parametrize("bersaglio, giusto", [
    ("\\\\?\\C:\\Foto", "C:\\Foto"), ("\\??\\C:\\Foto", "C:\\Foto"), ("C:\\Foto", "C:\\Foto"),
    ("\\\\?\\UNC\\nas\\foto", "\\\\nas\\foto"), ("\\\\nas\\foto", "\\\\nas\\foto"),
    ("\\\\?\\unc\\nas\\foto", "\\\\nas\\foto"),
    ("\\\\?\\Volume{1b3b1146-4076-11e1-84aa-806e6f6e6963}\\", None),
    ("relativo\\x", None), ("", None),
])
def test_il_bersaglio_di_una_giunzione(bersaglio, giusto):
    assert metadati.bersaglio_per_giunzione(bersaglio) == giusto


@pytest.mark.parametrize("percorso, lungo", [
    ("C:\\Foto\\IMG_1.jpg", "\\\\?\\C:\\Foto\\IMG_1.jpg"),
    ("C:/Foto/IMG_1.jpg", "\\\\?\\C:\\Foto\\IMG_1.jpg"),
    ("c:\\Foto", "\\\\?\\c:\\Foto"),
    ("\\\\nas\\foto\\x.jpg", "\\\\?\\UNC\\nas\\foto\\x.jpg"),
    ("\\\\?\\C:\\già lungo", "\\\\?\\C:\\già lungo"),
    ("\\\\.\\PhysicalDrive0", "\\\\.\\PhysicalDrive0"),
    ("C:\\Foto\\finisce col punto.", "\\\\?\\C:\\Foto\\finisce col punto."),
    ("C:\\Foto\\finisce con lo spazio ", "\\\\?\\C:\\Foto\\finisce con lo spazio "),
    ("C:\\Foto\\..\\Altro\\.\\x", "\\\\?\\C:\\Altro\\x"),
    ("C:\\Foto\\\\doppio", "\\\\?\\C:\\Foto\\doppio"),
    ("C:\\" + "cartella lunga\\" * 30 + "IMG_1.jpg",
     "\\\\?\\C:\\" + "cartella lunga\\" * 30 + "IMG_1.jpg"),
])
def test_i_percorsi_lunghi_di_windows(percorso, lungo):
    assert percorso_lungo(percorso, windows=True) == lungo


def test_fuori_da_windows_il_percorso_resta_quello(tmp_path):
    assert percorso_lungo(tmp_path / "x", windows=False) == str(tmp_path / "x")


@su_windows
def test_windows_vero_date_attributi_e_permessi(tmp_path):
    percorso = _file(tmp_path)
    letto = metadati.leggi(percorso)
    assert letto.tipo == metadati.FILE and "creazione" in letto.metadati
    assert letto.metadati["permessi"]["sddl"].startswith("O:")
    assert letto.avvisi == ()


@su_windows
def test_windows_vero_flussi_nascosti(tmp_path):
    percorso = _file(tmp_path)
    with metadati.apri_flusso(percorso, "Zone.Identifier", "wb") as flusso:
        flusso.write(b"[ZoneTransfer]\r\nZoneId=3\r\n")
    with metadati.apri_flusso(percorso, "secondo è", "wb") as flusso:
        flusso.write(b"")
    letto = metadati.leggi(percorso)
    assert sorted(letto.flussi) == [("Zone.Identifier", 26), ("secondo è", 0)]
    with metadati.apri_flusso(percorso, "Zone.Identifier") as flusso:
        assert flusso.read() == b"[ZoneTransfer]\r\nZoneId=3\r\n"
    assert percorso.read_bytes() == b"foto"


@su_windows
def test_windows_vero_flussi_su_una_cartella(tmp_path):
    cartella = tmp_path / "c"
    cartella.mkdir()
    assert metadati.leggi(cartella).flussi == ()
    with metadati.apri_flusso(cartella, "nascosto", "wb") as flusso:
        flusso.write(b"abc")
    assert metadati.leggi(cartella).flussi == (("nascosto", 3),)


@su_windows
def test_windows_vero_rimettere_creazione_e_attributi(tmp_path):
    percorso = _file(tmp_path)
    avvisi = metadati.rimetti(percorso, {"modifica": ANNO_2001 + 100,
                                         "accesso": ANNO_2001 + 200,
                                         "creazione": ANNO_2001 - 10 ** 11,
                                         "attributi": 0x1 | 0x2 | 0x20}, metadati.FILE)
    assert avvisi == []
    letto = metadati.leggi(percorso)
    assert letto.metadati["modifica"] == ANNO_2001 + 100
    assert letto.metadati["creazione"] == ANNO_2001 - 10 ** 11
    assert letto.metadati["attributi"] & 0x23 == 0x23
    metadati.rimetti(percorso, {"attributi": 0x20}, metadati.FILE)


@su_windows
def test_windows_vero_giunzione(tmp_path):
    vera = tmp_path / "vera"
    vera.mkdir()
    giunzione = tmp_path / "giunzione"
    import _winapi
    _winapi.CreateJunction(str(vera), str(giunzione))
    letto = metadati.leggi(giunzione)
    assert letto.tipo == metadati.COLLEGAMENTO
    assert letto.metadati["collegamento"] == "giunzione"
    rifatta = tmp_path / "rifatta"
    metadati.crea_collegamento(rifatta, letto.metadati)
    assert metadati.leggi(rifatta).metadati["collegamento"] == "giunzione"
    assert os.path.samefile(rifatta, vera)


@su_windows
def test_windows_vero_percorso_piu_lungo_di_260(tmp_path):
    cartella = tmp_path
    for _ in range(12):
        cartella = cartella / ("cartella lunga " * 2).strip()
    os.makedirs(percorso_lungo(cartella))
    percorso = cartella / "IMG_1.jpg"
    assert len(str(percorso)) > 260
    with open(percorso_lungo(percorso), "wb") as file:
        file.write(b"lontano")
    assert metadati.leggi(percorso).dimensione == 7


@su_windows
def test_windows_vero_nome_che_finisce_col_punto(tmp_path):
    percorso = str(tmp_path) + "\\strano."
    with open(percorso_lungo(percorso), "wb") as file:
        file.write(b"punto")
    assert metadati.leggi(percorso).dimensione == 5


def test_quello_che_si_legge_entra_nell_elenco_e_torna_uguale(tmp_path):
    from officina.sicuro import chiavi, elenco

    chiave = chiavi.Chiave(bytes(range(32)))
    sorgente = tmp_path / "foto"
    sorgente.mkdir()
    percorso = _file(sorgente)
    (sorgente / "Vuota").mkdir()
    os.symlink("IMG_1.jpg", sorgente / "collegamento")
    aperto = elenco.Elenco.apri(tmp_path / "archivio", chiave)
    fatti = [elenco.fatto_radice("r1", str(sorgente))]
    attesi = {}
    for voce in (percorso, sorgente / "Vuota", sorgente / "collegamento"):
        letto = metadati.leggi(voce)
        contenuto = "0" * 32 if letto.tipo == metadati.FILE else None
        fatti.append(elenco.fatto_posto("r1", voce.name, letto.tipo, contenuto,
                                        letto.metadati))
        attesi[voce.name] = (letto.tipo, letto.metadati)
    aperto.registra(fatti)
    aperto.fissa()
    aperto.chiudi()
    riaperto = elenco.Elenco.apri(tmp_path / "archivio", chiave)
    assert {posto.percorso: (posto.tipo, posto.metadati)
            for posto in riaperto.dentro("r1")} == attesi
