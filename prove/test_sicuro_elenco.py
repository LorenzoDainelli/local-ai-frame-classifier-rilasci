from __future__ import annotations

import hashlib
import random
import threading
import time
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, diario, elenco, formato
from officina.sicuro.elenco import Elenco, ElencoRovinato


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture
def cartella(tmp_path):
    return tmp_path / "archivio"


def _metti(cartella: Path, chiave, dati: bytes, percorso: str, radice: str = "r1",
           metadati: dict | None = None, registra: Elenco | None = None,
           informazioni: dict | None = None) -> tuple[formato.Scritto, dict]:
    numero = formato.nuovo_numero()
    posto = elenco.fatto_posto(radice, percorso, "file", numero.hex(),
                               metadati or {"modifica": 10 ** 18})
    radice_fatto = elenco.fatto_radice(radice, f"C:\\Foto\\{radice}")
    dove = elenco.percorso_contenuto(cartella, numero.hex())
    dove.parent.mkdir(parents=True, exist_ok=True)
    if informazioni is None:
        informazioni = {"fatti": [radice_fatto, posto], "scritto": time.time()}
    with open(dove, "wb") as file:
        scritto = formato.scrivi_byte(file, chiave, dati, informazioni, numero)
    if registra is not None:
        registra.registra([radice_fatto, elenco.fatto_contenuto(scritto), posto])
    return scritto, posto


def _stato(aperto: Elenco) -> dict:
    return {
        "contenuti": {numero: {chiave: valore for chiave, valore
                               in aperto.contenuto(numero).items()
                               if chiave not in ("scritto",)}
                      for numero in aperto.numeri()},
        "posti": sorted((posto.radice, posto.percorso, posto.contenuto, posto.sparito)
                        for radice in [r["id"] for r in aperto.radici()]
                        for posto in aperto.dentro(radice, anche_spariti=True)),
        "radici": [(r["id"], r["percorso"], r["tolta"]) for r in aperto.radici()],
    }


def _riempi(cartella, chiave, quanti: int = 12, seme: int = 0) -> Elenco:
    aperto = Elenco.apri(cartella, chiave)
    caso = random.Random(seme)
    for i in range(quanti):
        _metti(cartella, chiave, caso.randbytes(caso.randrange(0, 3000)),
               f"{2000 + i % 3}/IMG_{i:04d}.jpg", registra=aperto)
    return aperto


def _impronta_cartella(cartella: Path) -> dict:
    return {str(percorso.relative_to(cartella)): hashlib.sha256(percorso.read_bytes()).hexdigest()
            for percorso in sorted(cartella.rglob("*")) if percorso.is_file()}


def test_un_archivio_nuovo_e_vuoto(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    assert aperto.numeri() == [] and aperto.problemi == [] and aperto.generazione == 0
    assert not aperto.ricostruito
    assert (cartella / "elenco" / "diario-00000000.ofd").exists()
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.problemi == [] and riaperto.generazione == 0


def test_quello_che_si_registra_si_ritrova_riaprendo(cartella, chiave):
    aperto = _riempi(cartella, chiave)
    prima = _stato(aperto)
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert _stato(riaperto) == prima
    assert riaperto.problemi == [] and riaperto.ritrovati == 0
    assert len(prima["contenuti"]) == 12


def test_dopo_la_fotografia_si_ritrova_tutto(cartella, chiave):
    aperto = _riempi(cartella, chiave)
    aperto.fissa()
    _metti(cartella, chiave, b"dopo", "2001/IMG_9999.jpg", registra=aperto)
    prima = _stato(aperto)
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert _stato(riaperto) == prima and riaperto.generazione == 1
    assert riaperto.problemi == []


def test_le_fotografie_vecchie_si_tengono_solo_due(cartella, chiave):
    aperto = _riempi(cartella, chiave, 3)
    for giro in range(6):
        _metti(cartella, chiave, bytes([giro]), f"g/{giro}.jpg", registra=aperto)
        aperto.fissa()
    nomi = sorted(percorso.name for percorso in (cartella / "elenco").iterdir())
    assert nomi == ["diario-00000005.ofd", "diario-00000005.riserva.ofd",
                    "diario-00000006.ofd", "diario-00000006.riserva.ofd",
                    "fotografia-00000005.ofs", "fotografia-00000006.ofs"]


def test_senza_salvare_quello_che_c_e_nei_file_si_ritrova(cartella, chiave, monkeypatch):
    monkeypatch.setattr(elenco, "SECONDI_PER_SALVARE", 10 ** 6)
    aperto = Elenco.apri(cartella, chiave)
    aperto.registra([elenco.fatto_radice("r1", "C:\\Foto")])
    aperto.salva()
    scritti = [_metti(cartella, chiave, f"foto {i}".encode(), f"a/IMG_{i}.jpg",
                      registra=aperto)[0] for i in range(4)]
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.ritrovati == 4 and "file_ritrovati" in riaperto.problemi
    assert sorted(riaperto.numeri()) == sorted(s.numero for s in scritti)
    assert sorted(p.percorso for p in riaperto.dentro("r1")) == [
        f"a/IMG_{i}.jpg" for i in range(4)]
    di_nuovo = Elenco.apri(cartella, chiave)
    assert di_nuovo.ritrovati == 0 and di_nuovo.problemi == []


def test_senza_cartella_dell_elenco_si_ricostruisce_dai_file(cartella, chiave):
    aperto = _riempi(cartella, chiave, 20)
    prima = _stato(aperto)
    aperto.chiudi()
    for percorso in (cartella / "elenco").iterdir():
        percorso.unlink()
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.ricostruito and riaperto.ritrovati == 20
    assert _stato(riaperto) == prima
    riaperto.chiudi()
    di_nuovo = Elenco.apri(cartella, chiave)
    assert _stato(di_nuovo) == prima and di_nuovo.problemi == []


def test_la_fotografia_nuova_rovinata_si_usa_la_vecchia(cartella, chiave):
    aperto = _riempi(cartella, chiave, 6)
    aperto.fissa()
    _metti(cartella, chiave, b"in mezzo", "m/IMG_1.jpg", registra=aperto)
    aperto.fissa()
    _metti(cartella, chiave, b"ultimo", "m/IMG_2.jpg", registra=aperto)
    prima = _stato(aperto)
    aperto.chiudi()
    ultima = cartella / "elenco" / "fotografia-00000002.ofs"
    dati = bytearray(ultima.read_bytes())
    dati[:64] = bytes(64)
    dati[-64:] = bytes(64)
    ultima.write_bytes(bytes(dati))
    riaperto = Elenco.apri(cartella, chiave)
    assert "fotografia_rovinata" in riaperto.problemi
    assert _stato(riaperto) == prima and riaperto.generazione == 3
    assert (cartella / "elenco" / "fotografia-00000001.ofs").exists()
    riaperto.chiudi()
    assert _stato(Elenco.apri(cartella, chiave)) == prima


def test_tutte_le_fotografie_rovinate_si_rifa_dai_file_e_dai_diari(cartella, chiave):
    aperto = _riempi(cartella, chiave, 5)
    aperto.fissa()
    _metti(cartella, chiave, b"a", "x/IMG_1.jpg", registra=aperto)
    aperto.fissa()
    _metti(cartella, chiave, b"b", "x/IMG_2.jpg", registra=aperto)
    prima = _stato(aperto)
    aperto.chiudi()
    for percorso in (cartella / "elenco").glob("fotografia-*"):
        percorso.write_bytes(b"rotta")
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.ricostruito and "storia_persa" in riaperto.problemi
    assert _stato(riaperto) == prima


def test_un_piccolo_danno_nella_fotografia_si_ripara_coi_pezzetti(cartella, chiave):
    aperto = _riempi(cartella, chiave, 8)
    aperto.fissa()
    prima = _stato(aperto)
    aperto.chiudi()
    fotografia = cartella / "elenco" / "fotografia-00000001.ofs"
    dati = bytearray(fotografia.read_bytes())
    forma = formato.Forma.da_testa(bytes(dati[:64]))
    dati[forma.inizio + 100] ^= 0xFF
    fotografia.write_bytes(bytes(dati))
    riaperto = Elenco.apri(cartella, chiave)
    assert _stato(riaperto) == prima and "fotografia_rovinata" not in riaperto.problemi


def test_con_un_altra_chiave_non_si_tocca_niente(cartella, chiave):
    aperto = _riempi(cartella, chiave, 5)
    aperto.fissa()
    _metti(cartella, chiave, b"z", "z/IMG_1.jpg", registra=aperto)
    aperto.chiudi()
    prima = _impronta_cartella(cartella)
    with pytest.raises(ElencoRovinato) as scoppio:
        Elenco.apri(cartella, chiavi.Chiave(bytes(32)))
    assert scoppio.value.codice == "chiave_diversa"
    assert _impronta_cartella(cartella) == prima


def test_con_un_altra_chiave_e_solo_i_file_non_si_tocca_niente(cartella, chiave):
    _riempi(cartella, chiave, 3).chiudi()
    for percorso in (cartella / "elenco").iterdir():
        percorso.unlink()
    prima = _impronta_cartella(cartella)
    with pytest.raises(ElencoRovinato):
        Elenco.apri(cartella, chiavi.Chiave(bytes(32)))
    assert _impronta_cartella(cartella) == prima


def test_i_doppioni_si_trovano_con_grandezza_e_due_impronte(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"stessa foto", "a/IMG_1.jpg", registra=aperto)
    assert aperto.uguali(scritto.dimensione, scritto.blake2b, scritto.sha256) == [scritto.numero]
    assert aperto.uguali(scritto.dimensione + 1, scritto.blake2b, scritto.sha256) == []
    assert aperto.uguali(scritto.dimensione, "0" * 64, scritto.sha256) == []
    assert aperto.uguali(scritto.dimensione, scritto.blake2b, "0" * 64) == []


def test_un_contenuto_in_due_posti_e_il_principale(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, primo = _metti(cartella, chiave, b"foto", "Mare/IMG_1234 (1).jpg",
                            registra=aperto)
    aperto.registra([elenco.fatto_posto("r1", "Backup/IMG_1234.jpg", "file",
                                        scritto.numero, {"modifica": 10 ** 18})])
    posti = aperto.posti_di(scritto.numero)
    assert sorted(p.percorso for p in posti) == ["Backup/IMG_1234.jpg",
                                                 "Mare/IMG_1234 (1).jpg"]
    assert aperto.principale(scritto.numero).percorso == "Backup/IMG_1234.jpg"
    assert aperto.usato(scritto.numero)


def test_le_versioni_e_la_storia_dei_posti(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    primo, posto_primo = _metti(cartella, chiave, b"v1", "a/nota.txt", registra=aperto)
    secondo, posto_secondo = _metti(cartella, chiave, b"v2", "a/nota.txt",
                                    registra=aperto)
    storia = aperto.storia("r1", "a/nota.txt")
    assert [p.contenuto for p in storia] == [primo.numero, secondo.numero]
    assert aperto.attuale("r1", "a/nota.txt").contenuto == secondo.numero
    aperto.registra([elenco.fatto_sparito(posto_secondo["chiave"])])
    assert aperto.attuale("r1", "a/nota.txt").contenuto == primo.numero
    aperto.registra([elenco.fatto_sparito(posto_primo["chiave"])])
    assert aperto.attuale("r1", "a/nota.txt") is None
    assert len(aperto.storia("r1", "a/nota.txt")) == 2
    assert aperto.contenuto(primo.numero) is not None
    assert aperto.principale(primo.numero).percorso == "a/nota.txt"


def test_cartelle_vuote_collegamenti_e_flussi(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    vuota = elenco.fatto_posto("r1", "Vuota", "cartella", None, {"attributi": 16})
    link = elenco.fatto_posto("r1", "Scorciatoia", "collegamento", None,
                              {"bersaglio": "D:\\Altro"})
    scritto, posto = _metti(cartella, chiave, b"foto", "IMG_1.jpg", registra=aperto)
    zona, _ = _metti(cartella, chiave, b"[ZoneTransfer]", "IMG_1.jpg:flusso",
                     informazioni={"fatti": []})
    aperto.registra([vuota, link, elenco.fatto_contenuto(zona),
                     elenco.fatto_flusso(posto["chiave"], "Zone.Identifier", zona.numero)])
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    tipi = {p.percorso: p.tipo for p in riaperto.dentro("r1")}
    assert tipi == {"Vuota": "cartella", "Scorciatoia": "collegamento", "IMG_1.jpg": "file"}
    assert riaperto.attuale("r1", "Scorciatoia").metadati == {"bersaglio": "D:\\Altro"}
    assert riaperto.flussi_di(posto["chiave"]) == [("Zone.Identifier", zona.numero)]
    assert riaperto.usato(zona.numero)


def test_stato_dei_contenuti(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"x", "IMG_1.jpg", registra=aperto)
    aperto.registra([elenco.fatto_stato(scritto.numero, "riparato", "pezzetti di riserva",
                                        quando=123.0)])
    riga = aperto.contenuto(scritto.numero)
    assert riga["stato"] == "riparato" and riga["controllato"] == 123.0
    assert riga["testa"] == scritto.testa


def test_le_radici_tolte_restano(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    aperto.registra([elenco.fatto_radice("r1", "C:\\Foto", quando=1.0),
                     elenco.fatto_radice("r2", "D:\\Vecchie", quando=2.0)])
    aperto.registra([elenco.fatto_radice("r2", "D:\\Vecchie", tolta=True, quando=3.0)])
    aperto.chiudi()
    radici = Elenco.apri(cartella, chiave).radici()
    assert radici == [{"id": "r1", "percorso": "C:\\Foto", "aggiunta": 1.0, "tolta": False,
                       "cambiata": 1.0},
                      {"id": "r2", "percorso": "D:\\Vecchie", "aggiunta": 2.0, "tolta": True,
                       "cambiata": 3.0}]


def test_conta(cartella, chiave):
    aperto = _riempi(cartella, chiave, 7)
    conta = aperto.conta()
    assert conta["contenuti"] == 7 and conta["posti"] == 7
    assert conta["peso"] == sum(aperto.contenuto(n)["peso"] for n in aperto.numeri())


@pytest.mark.parametrize("cattivo", [
    {}, {"fatto": "boh"}, "testo", None,
    {"fatto": "radice", "id": "", "percorso": "C:\\", "tolta": False, "quando": 1},
    {"fatto": "radice", "id": "r", "percorso": "C:\\", "tolta": 0, "quando": 1},
    {"fatto": "radice", "id": "r", "percorso": "C:\\", "tolta": False, "quando": -1},
    {"fatto": "stato", "numero": "0" * 32, "stato": "felice", "perche": None, "quando": 1},
    {"fatto": "stato", "numero": "0" * 31, "stato": "buono", "perche": None, "quando": 1},
    {"fatto": "sparito", "chiave": "XYZ", "quando": 1},
    {"fatto": "sparito", "chiave": "0" * 32, "quando": "ieri"},
    {"fatto": "flusso", "posto": "0" * 32, "nome": "", "contenuto": "1" * 32},
    {"fatto": "flusso", "posto": "0" * 32, "nome": "z", "contenuto": "G" * 32},
])
def test_i_fatti_strani_non_si_accettano(cartella, chiave, cattivo):
    aperto = Elenco.apri(cartella, chiave)
    assert not elenco.valido(cattivo)
    with pytest.raises(ValueError):
        aperto.registra([elenco.fatto_radice("r1", "C:\\Foto"), cattivo])
    assert aperto.radici() == []


def _posto_buono(**cambi) -> dict:
    fatto = elenco.fatto_posto("r1", "a/b.jpg", "file", "0" * 32, {})
    fatto.update(cambi)
    return fatto


@pytest.mark.parametrize("cambi", [
    {"percorso": "../fuori.jpg"}, {"percorso": "/assoluto.jpg"}, {"percorso": "a//b.jpg"},
    {"percorso": "C:/x.jpg"}, {"percorso": "a\\b.jpg"}, {"percorso": "a/./b.jpg"},
    {"tipo": "dispositivo"}, {"contenuto": "corto"}, {"metadati": []},
    {"segni": ["In Uso"]}, {"segni": "in_uso"}, {"chiave": "0"}, {"radice": ""},
    {"quando": 2 ** 41}, {"percorso": "a/\x00.jpg"},
])
def test_i_posti_strani_non_si_accettano(cambi):
    assert elenco.valido(_posto_buono())
    assert not elenco.valido(_posto_buono(**cambi))


@pytest.mark.parametrize("dato, atteso", [
    ("a/b/c.jpg", "a/b/c.jpg"), ("a\\b\\c.jpg", "a/b/c.jpg"), ("a//b", "a/b"),
    ("./a", "a"), ("a/", "a"), ("", ""), ("perché/🐶.jpg", "perché/🐶.jpg"),
])
def test_percorsi_puliti(dato, atteso):
    assert elenco.percorso_pulito(dato) == atteso


@pytest.mark.parametrize("dato", ["../a", "a/../../b", "/a", "\\a", "C:\\a", "c:", "a\x00b"])
def test_percorsi_che_escono(dato):
    with pytest.raises(ValueError):
        elenco.percorso_pulito(dato)


def test_un_file_illeggibile_non_fa_ricominciare_ogni_volta(cartella, chiave):
    aperto = _riempi(cartella, chiave, 2)
    aperto.chiudi()
    finto = elenco.percorso_contenuto(cartella, "ab" + "0" * 30)
    finto.parent.mkdir(parents=True, exist_ok=True)
    finto.write_bytes(b"non sono un file cifrato")
    primo = Elenco.apri(cartella, chiave)
    assert primo.illeggibili == ["ab" + "0" * 30] and "file_illeggibili" in primo.problemi
    generazione = primo.generazione
    primo.chiudi()
    secondo = Elenco.apri(cartella, chiave)
    assert secondo.generazione == generazione and secondo.illeggibili == ["ab" + "0" * 30]
    assert finto.read_bytes() == b"non sono un file cifrato"


def test_un_file_senza_informazioni_si_ritrova_con_le_impronte_rifatte(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"senza nome" * 100, "IMG_1.jpg")
    dove = elenco.percorso_contenuto(cartella, scritto.numero)
    dati = bytearray(dove.read_bytes())
    forma = formato.Forma.da_testa(bytes(dati[:64]))
    dati[70] ^= 1
    dati[forma.peso - forma.inizio + 6] ^= 1
    dove.write_bytes(bytes(dati))
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    riga = riaperto.contenuto(scritto.numero)
    assert riga["stato"] == "senza_informazioni"
    assert riga["sha256"] == scritto.sha256 and riga["blake2b"] == scritto.blake2b


def test_un_file_nella_sottocartella_sbagliata_si_lascia_stare(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"x", "IMG_1.jpg")
    giusto = elenco.percorso_contenuto(cartella, scritto.numero)
    sbagliato = cartella / "contenuti" / "zz" / giusto.name
    sbagliato.parent.mkdir()
    giusto.rename(sbagliato)
    aperto.chiudi()
    assert Elenco.apri(cartella, chiave).numeri() == []


def test_i_fatti_strani_dentro_un_file_si_saltano(cartella, chiave):
    numero = formato.nuovo_numero().hex()
    posto = elenco.fatto_posto("r1", "IMG_1.jpg", "file", numero, {})
    _metti(cartella, chiave, b"x", "ignorato.jpg", informazioni={
        "fatti": [posto, {"fatto": "posto", "percorso": "../../fuori"}, "boh",
                  {"fatto": "contenuto", "numero": "1" * 32}]})
    aperto = Elenco.apri(cartella, chiave)
    assert len(aperto.numeri()) == 1
    assert [p.percorso for p in aperto.dentro("r1")] == ["IMG_1.jpg"]


def test_dopo_tante_righe_si_fa_la_fotografia_da_sola(cartella, chiave, monkeypatch):
    monkeypatch.setattr(elenco, "FATTI_PER_FOTOGRAFIA", 10)
    monkeypatch.setattr(elenco, "FATTI_PER_SALVARE", 3)
    aperto = Elenco.apri(cartella, chiave)
    for i in range(10):
        _metti(cartella, chiave, bytes([i]), f"IMG_{i}.jpg", registra=aperto)
    assert aperto.generazione >= 2
    prima = _stato(aperto)
    aperto.chiudi()
    assert _stato(Elenco.apri(cartella, chiave)) == prima


def test_si_salva_da_solo_dopo_un_po(cartella, chiave, monkeypatch):
    orologio = [1000.0]
    monkeypatch.setattr(elenco.time, "monotonic", lambda: orologio[0])
    aperto = Elenco.apri(cartella, chiave)
    aperto.registra([elenco.fatto_radice("r1", "C:\\A")])
    assert aperto._in_attesa
    orologio[0] += elenco.SECONDI_PER_SALVARE + 0.1
    aperto.registra([elenco.fatto_radice("r2", "C:\\B")])
    assert not aperto._in_attesa
    assert len(Elenco.apri(cartella, chiave).radici()) == 2


def test_se_il_diario_si_rompe_si_passa_alla_fotografia(cartella, chiave, monkeypatch):
    aperto = _riempi(cartella, chiave, 3)

    def rotto(self, fatti):
        self.rotto = True
        raise OSError(28, "Disco pieno")

    monkeypatch.setattr(diario.Diario, "aggiungi", rotto)
    _metti(cartella, chiave, b"y", "IMG_x.jpg", registra=aperto)
    aperto.salva()
    monkeypatch.undo()
    prima = _stato(aperto)
    assert aperto.generazione == 1
    aperto.chiudi()
    assert _stato(Elenco.apri(cartella, chiave)) == prima


def test_tanti_insieme_dallo_stesso_elenco(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    errori = []

    def lavora(quale):
        try:
            for i in range(25):
                aperto.registra([elenco.fatto_radice(f"r{quale}-{i}", f"C:\\{quale}\\{i}")])
        except Exception as errore:
            errori.append(errore)

    fili = [threading.Thread(target=lavora, args=(n,)) for n in range(4)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join()
    assert not errori
    aperto.chiudi()
    assert len(Elenco.apri(cartella, chiave).radici()) == 100


def test_da_fuori_non_si_legge_niente(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    _metti(cartella, chiave, b"x", "Sardegna_segreta/IMG_1.jpg", registra=aperto)
    aperto.registra([elenco.fatto_radice("r9", "C:\\Utenti\\Mario\\Riservato")])
    aperto.fissa()
    aperto.chiudi()
    for percorso in cartella.rglob("*"):
        if percorso.is_file():
            dati = percorso.read_bytes()
            assert b"Sardegna" not in dati and b"Riservato" not in dati
            assert b"IMG_1" not in dati and b"SQLite" not in dati


def test_quello_che_si_salva_insieme_entra_tutto_o_niente(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    for giro in range(3):
        for i in range(4):
            _metti(cartella, chiave, bytes([giro, i]), f"g{giro}/IMG_{i}.jpg",
                   registra=aperto)
        aperto.salva()
    aperto.chiudi()
    _, righe = diario.Diario.apri(*Elenco(cartella, chiave)._diari(0), chiave, 0)
    assert len(righe) == 3 and all(len(riga["fatti"]) == 12 for riga in righe)


def test_un_salvataggio_grande_si_divide_in_piu_righe(cartella, chiave, monkeypatch):
    monkeypatch.setattr(elenco, "PESO_PER_RIGA", 600)
    aperto = Elenco.apri(cartella, chiave)
    for i in range(10):
        _metti(cartella, chiave, bytes([i]), f"IMG_{i}.jpg", registra=aperto)
    prima = _stato(aperto)
    aperto.chiudi()
    _, righe = diario.Diario.apri(*Elenco(cartella, chiave)._diari(0), chiave, 0)
    assert len(righe) > 3 and sum(len(riga["fatti"]) for riga in righe) == 30
    riaperto = Elenco.apri(cartella, chiave)
    assert _stato(riaperto) == prima and riaperto.problemi == []


def test_metadati_troppo_grandi_non_passano(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    posto = elenco.fatto_posto("r1", "IMG_1.jpg", "file", "0" * 32,
                               {"tanto": "x" * (elenco.METADATI_MASSIMI + 1)})
    with pytest.raises(ValueError):
        aperto.registra([posto])


def test_un_nome_perso_si_riprende_dal_file(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, posto = _metti(cartella, chiave, b"mare", "Mare/IMG_1.jpg")
    aperto.registra([elenco.fatto_radice("r1", "C:\\Foto\\r1"),
                     elenco.fatto_contenuto(scritto)])
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert "nomi_ritrovati" in riaperto.problemi and riaperto.ritrovati == 1
    assert [p.percorso for p in riaperto.posti_di(scritto.numero)] == ["Mare/IMG_1.jpg"]
    prima = _stato(riaperto)
    riaperto.chiudi()
    di_nuovo = Elenco.apri(cartella, chiave)
    assert di_nuovo.problemi == [] and _stato(di_nuovo) == prima


def test_una_cartella_di_partenza_persa_si_riprende_dai_file(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritti = []
    for i in range(3):
        scritto, posto = _metti(cartella, chiave, bytes([i]), f"IMG_{i}.jpg", radice="r7")
        aperto.registra([elenco.fatto_contenuto(scritto), posto])
        scritti.append(scritto)
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert [r["id"] for r in riaperto.radici()] == ["r7"]
    assert riaperto.radici()[0]["percorso"] == "C:\\Foto\\r7"
    assert riaperto.ritrovati == 1 and "nomi_ritrovati" in riaperto.problemi
    riaperto.chiudi()
    assert Elenco.apri(cartella, chiave).problemi == []


def test_i_file_ritrovati_non_rimettono_una_cartella_tolta(cartella, chiave):
    aperto = _riempi(cartella, chiave, 2)
    aperto.registra([elenco.fatto_radice("r1", "C:\\Foto\\r1", tolta=True)])
    aperto.chiudi()
    _metti(cartella, chiave, b"orfano", "IMG_orfano.jpg")
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.ritrovati == 1
    assert riaperto.radici()[0]["tolta"] is True
    riaperto.chiudi()
    assert Elenco.apri(cartella, chiave).radici()[0]["tolta"] is True


def test_un_contenuto_senza_nome_nel_file_non_fa_lavorare_ogni_volta(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"solo", "x.jpg", informazioni={"nome": "x"})
    aperto.registra([elenco.fatto_contenuto(scritto)])
    aperto.chiudi()
    prima = _impronta_cartella(cartella)
    for _ in range(3):
        riaperto = Elenco.apri(cartella, chiave)
        assert riaperto.problemi == [] and riaperto.ritrovati == 0
        assert riaperto.generazione == 0
        riaperto.chiudi()
    assert _impronta_cartella(cartella) == prima


def _tutto(aperto: Elenco) -> list:
    return [(r["id"], r["percorso"], [(p.percorso, p.metadati,
                                       aperto.flussi_di(p.chiave))
                                      for p in aperto.dentro(r["id"])])
            for r in aperto.radici()]


@pytest.mark.parametrize("come", ["diario", "fotografia", "dai_file"])
def test_nomi_con_lettere_rotte_si_salvano_e_tornano_uguali(cartella, chiave, come):
    aperto = Elenco.apri(cartella, chiave)
    radice = "r\udcff"
    scritto, posto = _metti(cartella, chiave, b"strano", "Mare\udc80/IMG_\ud800 1.jpg",
                            radice=radice,
                            metadati={"modifica": 1, "bersaglio": "C:\\\udfff"})
    flusso, _ = _metti(cartella, chiave, b"zona", "x", radice=radice)
    aperto.registra([elenco.fatto_radice(radice, "C:\\Foto\\\udc81"),
                     elenco.fatto_contenuto(scritto), posto,
                     elenco.fatto_contenuto(flusso),
                     elenco.fatto_flusso(posto["chiave"], "Zone\udc80", flusso.numero),
                     elenco.fatto_stato(scritto.numero, "rovinato", "perché\udc80")])
    prima = _tutto(aperto)
    assert prima[0][2][0][0] == "Mare\udc80/IMG_\ud800 1.jpg"
    assert aperto.storia(radice, "Mare\udc80/IMG_\ud800 1.jpg")
    if come == "fotografia":
        aperto.fissa()
    aperto.chiudi()
    if come == "dai_file":
        for percorso in (cartella / "elenco").iterdir():
            percorso.unlink()
    riaperto = Elenco.apri(cartella, chiave)
    dopo = _tutto(riaperto)
    if come == "dai_file":
        assert dopo[0][0] == radice
        assert prima[0][2][0][:2] in [voce[:2] for voce in dopo[0][2]]
    else:
        assert dopo == prima
        assert riaperto.contenuto(scritto.numero)["perche"] == "perché\udc80"


def test_la_fotografia_non_e_un_contenuto_dell_archivio(cartella, chiave):
    aperto = _riempi(cartella, chiave, 2)
    aperto.fissa()
    aperto.chiudi()
    assert len(Elenco.apri(cartella, chiave).numeri()) == 2


@pytest.mark.parametrize("seme", range(120))
def test_danni_a_caso_nell_elenco_non_perdono_mai_i_contenuti(cartella, chiave, seme):
    caso = random.Random(seme)
    aperto = Elenco.apri(cartella, chiave)
    scritti = []
    for giro in range(caso.randint(1, 3)):
        for i in range(caso.randint(1, 5)):
            scritti.append(_metti(cartella, chiave, caso.randbytes(caso.randrange(200)),
                                  f"g{giro}/IMG_{i}.jpg", registra=aperto)[0])
        if caso.random() < 0.6:
            aperto.fissa()
    aperto.chiudi()
    file_elenco = sorted((cartella / "elenco").iterdir())
    for _ in range(caso.randint(1, 5)):
        percorso = caso.choice(file_elenco)
        dati = bytearray(percorso.read_bytes())
        come = caso.randrange(5)
        if come == 0 and dati:
            dati[caso.randrange(len(dati))] ^= 1 << caso.randrange(8)
        elif come == 1:
            del dati[caso.randrange(len(dati) + 1):]
        elif come == 2 and dati:
            dove = caso.randrange(len(dati))
            dati[dove:dove + 300] = caso.randbytes(min(300, len(dati) - dove))
        elif come == 3:
            percorso.unlink()
            file_elenco.remove(percorso)
            if not file_elenco:
                break
            continue
        else:
            dati = bytearray(caso.randbytes(caso.randrange(0, 500)))
        percorso.write_bytes(bytes(dati))
    riaperto = Elenco.apri(cartella, chiave)
    assert sorted(riaperto.numeri()) == sorted(s.numero for s in scritti)
    for scritto in scritti:
        riga = riaperto.contenuto(scritto.numero)
        assert riga["sha256"] == scritto.sha256 and riga["dimensione"] == scritto.dimensione
        assert riaperto.posti_di(scritto.numero)
    stato = _stato(riaperto)
    riaperto.chiudi()
    di_nuovo = Elenco.apri(cartella, chiave)
    assert _stato(di_nuovo) == stato
    assert di_nuovo.problemi == []


def _numeri_in_fila(monkeypatch):
    fila = iter(bytes([n]) * 16 for n in range(1, 255))
    monkeypatch.setattr(formato, "nuovo_numero", lambda: next(fila))


def _via_l_elenco(cartella: Path) -> None:
    for percorso in (cartella / "elenco").iterdir():
        percorso.unlink()


def test_una_nota_sta_tra_i_contenuti_ma_non_e_un_contenuto(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    cartella_fatto = elenco.fatto_posto("r1", "2001", "cartella", None, {"modifica": 5})
    numero = aperto.scrivi_nota([elenco.fatto_radice("r1", "C:\\Foto"), cartella_fatto])
    assert numero and aperto.note() == [numero]
    assert aperto.numeri() == []
    assert elenco.percorso_contenuto(cartella, numero).exists()
    assert not list(cartella.rglob("*.nuovo"))
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert riaperto.note() == [numero] and riaperto.ritrovati == 0
    assert riaperto.problemi == []


def test_una_nota_vuota_non_si_scrive(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"x", "a.jpg")
    assert aperto.scrivi_nota([]) is None
    assert aperto.scrivi_nota([elenco.fatto_contenuto(scritto)]) is None
    assert aperto.note() == []


def test_una_nota_con_un_fatto_sbagliato_non_si_scrive(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    with pytest.raises(ValueError):
        aperto.scrivi_nota([{"fatto": "posto", "chiave": "x"}])
    assert aperto.note() == [] and not (cartella / "contenuti").exists()


def test_senza_elenco_le_note_rimettono_tutto(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, posto = _metti(cartella, chiave, b"mare", "2001/IMG_1.jpg", registra=aperto)
    doppione = elenco.fatto_posto("r1", "2002/IMG_1 (1).jpg", "file", scritto.numero,
                                  {"modifica": 7})
    cartella_fatto = elenco.fatto_posto("r1", "2001", "cartella", None, {"modifica": 5})
    legame = elenco.fatto_posto("r1", "scorciatoia", "collegamento", None,
                                {"collegamento": "simbolico", "bersaglio": "2001"})
    vecchio = elenco.fatto_posto("r1", "2003/via.jpg", "file", scritto.numero,
                                 {"modifica": 1})
    sparito = elenco.fatto_sparito(vecchio["chiave"])
    flusso = elenco.fatto_flusso(doppione["chiave"], "Zone.Identifier", scritto.numero)
    giro = elenco.fatto_giro("r1", 100.0, 200.0, [("solo_nel_cloud", "2004/c.jpg")],
                             {"file": 3})
    fatti = [doppione, cartella_fatto, legame, vecchio, sparito, flusso, giro]
    aperto.registra(fatti)
    aperto.scrivi_nota(fatti)
    prima = _tutto(aperto)
    spariti = sorted(p.percorso for p in aperto.dentro("r1", anche_spariti=True)
                     if p.sparito is not None)
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.ricostruito
    assert _tutto(rifatto) == prima
    assert sorted(p.percorso for p in rifatto.dentro("r1", anche_spariti=True)
                  if p.sparito is not None) == spariti == ["2003/via.jpg"]
    assert rifatto.giro("r1")["problemi"] == [{"codice": "solo_nel_cloud",
                                               "percorso": "2004/c.jpg"}]
    assert len(rifatto.note()) == 1
    assert rifatto.contenuto(scritto.numero)["stato"] == "buono"


@pytest.mark.parametrize("ordine", ["sparito_prima", "posto_prima"])
def test_lo_sparito_si_ricorda_in_qualunque_ordine(cartella, chiave, monkeypatch, ordine):
    _numeri_in_fila(monkeypatch)
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"mare", "a.jpg", registra=aperto)
    via = elenco.fatto_posto("r1", "b.jpg", "file", scritto.numero, {"modifica": 1})
    sparito = elenco.fatto_sparito(via["chiave"], quando=via["quando"] + 1)
    aperto.registra([via, sparito])
    prime, seconde = ([sparito], [via]) if ordine == "sparito_prima" else ([via], [sparito])
    aperto.scrivi_nota(prime)
    aperto.scrivi_nota(seconde)
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    tutti = {p.percorso: p.sparito for p in rifatto.dentro("r1", anche_spariti=True)}
    assert tutti["b.jpg"] == sparito["quando"] and tutti["a.jpg"] is None


def test_lo_stato_si_ricorda_anche_prima_del_contenuto(cartella, chiave, monkeypatch):
    numeri = [bytes([200]) * 16, bytes([1]) * 16]
    monkeypatch.setattr(formato, "nuovo_numero", lambda: numeri.pop())
    aperto = Elenco.apri(cartella, chiave)
    aperto.scrivi_nota([elenco.fatto_stato(bytes([200]).hex() * 16, "riparato",
                                           "controllo_del_mese")])
    scritto, _ = _metti(cartella, chiave, b"mare", "a.jpg", registra=aperto)
    assert scritto.numero == bytes([200]).hex() * 16
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.contenuto(scritto.numero)["stato"] == "riparato"


def test_uno_stato_vecchio_ritrovato_non_copre_quello_nuovo(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"mare", "a.jpg", registra=aperto)
    aperto.registra([elenco.fatto_stato(scritto.numero, "riparato", "y", quando=300.0)])
    vecchio = elenco.fatto_stato(scritto.numero, "rovinato", "x", quando=100.0)
    assert aperto._applica_tutti([vecchio], ritrovati=True) == []
    assert aperto.contenuto(scritto.numero)["stato"] == "riparato"
    nuovo = elenco.fatto_stato(scritto.numero, "rovinato", "z", quando=400.0)
    assert aperto._applica_tutti([nuovo], ritrovati=True) == [nuovo]
    assert aperto.contenuto(scritto.numero)["stato"] == "rovinato"


@pytest.mark.parametrize("ordine", ["nota_prima", "file_prima"])
def test_i_segni_della_nota_non_si_perdono(cartella, chiave, monkeypatch, ordine):
    numeri = ([bytes([9]) * 16, bytes([1]) * 16] if ordine == "nota_prima"
              else [bytes([1]) * 16, bytes([9]) * 16])
    monkeypatch.setattr(formato, "nuovo_numero", lambda: numeri.pop())
    aperto = Elenco.apri(cartella, chiave)
    scritto, posto = _metti(cartella, chiave, b"in uso", "a.jpg")
    pieno = dict(posto, segni=["in_uso"])
    aperto.registra([elenco.fatto_radice("r1", "C:\\Foto\\r1"),
                     elenco.fatto_contenuto(scritto), pieno])
    aperto.scrivi_nota([pieno])
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.posto(posto["chiave"]).segni == ("in_uso",)


def test_una_cartella_tolta_resta_tolta_anche_ricostruendo(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    aperto.scrivi_nota([elenco.fatto_radice("r1", "C:\\Foto\\r1", quando=100.0)])
    aperto.scrivi_nota([elenco.fatto_radice("r1", "C:\\Foto\\r1", tolta=True,
                                            quando=200.0)])
    _metti(cartella, chiave, b"dopo", "a.jpg")
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.radici()[0]["tolta"] is True


def test_ricostruendo_vale_il_percorso_piu_nuovo(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    aperto.scrivi_nota([elenco.fatto_radice("r1", "D:\\Nuovo", quando=300.0)])
    aperto.scrivi_nota([elenco.fatto_radice("r1", "C:\\Vecchio", quando=100.0)])
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.radici()[0]["percorso"] == "D:\\Nuovo"


def test_il_giro_si_ricorda(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    assert aperto.giro("r1") is None
    aperto.registra([elenco.fatto_giro("r1", 10.0, None)])
    assert aperto.giro("r1")["fine"] is None
    aperto.registra([elenco.fatto_giro("r1", 10.0, 20.0, [("in_uso", "a.jpg")],
                                       {"file": 2, "byte": 99})])
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    giro = riaperto.giro("r1")
    assert giro == {"radice": "r1", "inizio": 10.0, "fine": 20.0,
                    "problemi": [{"codice": "in_uso", "percorso": "a.jpg"}],
                    "contati": {"file": 2, "byte": 99}}


@pytest.mark.parametrize("ordine", [0, 1, 2])
def test_ricostruendo_vale_il_giro_piu_nuovo_e_finito(cartella, chiave, ordine):
    giri = [elenco.fatto_giro("r1", 10.0, 20.0, [("in_uso", "vecchio.jpg")]),
            elenco.fatto_giro("r1", 30.0, None),
            elenco.fatto_giro("r1", 30.0, 40.0, [("in_uso", "nuovo.jpg")])]
    giri = giri[ordine:] + giri[:ordine]
    aperto = Elenco.apri(cartella, chiave)
    for giro in giri:
        aperto._applica_tutti([giro], ritrovati=True)
    assert aperto.giro("r1")["fine"] == 40.0
    assert aperto.giro("r1")["problemi"][0]["percorso"] == "nuovo.jpg"


def test_un_giro_con_troppi_problemi_si_accorcia():
    problemi = [("in_uso", f"{i}.jpg") for i in range(elenco.PROBLEMI_PER_GIRO + 7)]
    giro = elenco.fatto_giro("r1", 1.0, 2.0, problemi)
    assert len(giro["problemi"]) == elenco.PROBLEMI_PER_GIRO
    assert giro["contati"]["problemi_in_piu"] == 7
    assert elenco.valido(giro)


@pytest.mark.parametrize("guasto", [
    {"problemi": [{"codice": "Strano Codice", "percorso": None}]},
    {"problemi": [{"codice": "in_uso"}]},
    {"problemi": "tanti"},
    {"contati": {"file": -1}},
    {"contati": {"file": 1.5}},
    {"fine": "domani"},
    {"inizio": None},
    {"radice": ""},
    {"problemi": [{"codice": "in_uso", "percorso": None}] * (elenco.PROBLEMI_PER_GIRO + 1)},
])
def test_un_giro_strano_non_vale(guasto):
    giro = dict(elenco.fatto_giro("r1", 1.0, 2.0), **guasto)
    assert not elenco.valido(giro)


@pytest.mark.parametrize("guasto", ["json", "lista", "rovinata", "senza_data"])
def test_una_nota_strana_si_dice_e_non_rompe_niente(cartella, chiave, guasto):
    aperto = Elenco.apri(cartella, chiave)
    _metti(cartella, chiave, b"mare", "a.jpg", registra=aperto)
    aperto.chiudi()
    numero = formato.nuovo_numero()
    dati = {"json": b"{non json", "lista": b'{"fatto": "radice"}',
            "rovinata": b"[]", "senza_data": b"[]"}[guasto]
    informazioni = {"tipo": "nota", "scritto": 5.0}
    if guasto == "senza_data":
        informazioni = {"tipo": "nota"}
    dove = elenco.percorso_contenuto(cartella, numero.hex())
    dove.parent.mkdir(parents=True, exist_ok=True)
    with open(dove, "wb") as file:
        formato.scrivi_byte(file, chiave, dati, informazioni, numero)
    if guasto == "rovinata":
        rotto = bytearray(dove.read_bytes())
        forma = formato.Forma.da_testa(bytes(rotto[:formato.TESTA.size]))
        for i in range(forma.inizio, len(rotto) - forma.inizio):
            rotto[i] ^= 0xFF
        dove.write_bytes(bytes(rotto))
    riaperto = Elenco.apri(cartella, chiave)
    assert numero.hex() in riaperto.illeggibili
    assert "file_illeggibili" in riaperto.problemi
    assert len(riaperto.numeri()) == 1 and riaperto.note() == []


def test_una_nota_non_porta_contenuti_finti(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    scritto, _ = _metti(cartella, chiave, b"mare", "a.jpg")
    finto = elenco.fatto_contenuto(scritto)
    finto["numero"] = "ab" * 16
    numero = formato.nuovo_numero()
    dove = elenco.percorso_contenuto(cartella, numero.hex())
    dove.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(dove, "wb") as file:
        formato.scrivi_byte(file, chiave, json.dumps([finto]).encode(),
                            {"tipo": "nota", "scritto": 5.0}, numero)
    aperto.chiudi()
    riaperto = Elenco.apri(cartella, chiave)
    assert "ab" * 16 not in riaperto.numeri()
    assert riaperto.note() == [numero.hex()]


def test_una_nota_gia_nota_non_si_rilegge(cartella, chiave, monkeypatch):
    aperto = Elenco.apri(cartella, chiave)
    aperto.scrivi_nota([elenco.fatto_radice("r1", "C:\\Foto")])
    aperto.chiudi()
    letture = []
    vera = Elenco._fatti_dal_file
    monkeypatch.setattr(Elenco, "_fatti_dal_file",
                        lambda self, *a: letture.append(a) or vera(self, *a))
    Elenco.apri(cartella, chiave).chiudi()
    assert letture == []


def test_una_nota_con_nomi_rotti(cartella, chiave):
    aperto = Elenco.apri(cartella, chiave)
    fatti = [elenco.fatto_radice("r\udcff", "C:\\\udc81"),
             elenco.fatto_posto("r\udcff", "Mare\udc80", "cartella", None,
                                {"bersaglio": "\ud800"})]
    aperto.scrivi_nota(fatti)
    aperto.chiudi()
    _via_l_elenco(cartella)
    rifatto = Elenco.apri(cartella, chiave)
    assert rifatto.radici()[0]["percorso"] == "C:\\\udc81"
    assert rifatto.dentro("r\udcff")[0].percorso == "Mare\udc80"


def _solo_lettura(cartella, chiave) -> Elenco:
    prima = _impronta_cartella(cartella)
    aperto = Elenco.apri(cartella, chiave, sola_lettura=True)
    assert aperto.sola_lettura
    assert _impronta_cartella(cartella) == prima
    return aperto


@pytest.mark.parametrize("guasto", ["niente", "senza_elenco", "fotografie_rotte",
                                    "diario_rotto", "solo_diario"])
def test_in_sola_lettura_non_si_scrive_mai_niente(cartella, chiave, guasto):
    aperto = _riempi(cartella, chiave, 7)
    if guasto != "solo_diario":
        aperto.fissa()
    _metti(cartella, chiave, b"dopo", "y/IMG_9.jpg", registra=aperto)
    prima = _stato(aperto)
    aperto.chiudi()
    for percorso in sorted((cartella / "elenco").iterdir()):
        if guasto == "senza_elenco":
            percorso.unlink()
        elif guasto == "fotografie_rotte" and percorso.name.startswith("fotografia"):
            percorso.write_bytes(b"rotta")
        elif guasto == "diario_rotto" and percorso.name.startswith("diario"):
            percorso.write_bytes(b"rotto")
    letto = _solo_lettura(cartella, chiave)
    if guasto == "diario_rotto":
        assert set(_stato(letto)["contenuti"]) <= set(prima["contenuti"])
    else:
        assert _stato(letto) == prima
    impronta = _impronta_cartella(cartella)
    for scrivi in (lambda: letto.registra([elenco.fatto_radice("r9", "C:\\Altro")]),
                   letto.fissa,
                   lambda: letto.scrivi_nota([elenco.fatto_radice("r9", "C:\\Altro")])):
        with pytest.raises(ErroreOfficina) as scoppio:
            scrivi()
        assert scoppio.value.codice == "solo_lettura"
    letto.salva()
    letto.chiudi()
    assert _impronta_cartella(cartella) == impronta


def test_in_sola_lettura_un_altra_chiave_non_apre(cartella, chiave):
    _riempi(cartella, chiave, 3).chiudi()
    prima = _impronta_cartella(cartella)
    with pytest.raises(ElencoRovinato):
        Elenco.apri(cartella, chiavi.Chiave(bytes(32)), sola_lettura=True)
    assert _impronta_cartella(cartella) == prima


def test_in_sola_lettura_una_cartella_vuota_resta_vuota(cartella, chiave):
    cartella.mkdir()
    letto = Elenco.apri(cartella, chiave, sola_lettura=True)
    assert letto.numeri() == [] and list(cartella.iterdir()) == []
    letto.chiudi()
    assert list(cartella.iterdir()) == []
