from __future__ import annotations

import hashlib
import io
import random

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, formato

PICCOLO = 256


@pytest.fixture(autouse=True)
def pezzi_piccoli(monkeypatch):
    monkeypatch.setattr(formato, "PEZZO", PICCOLO)
    monkeypatch.setattr(formato, "BLOCCO", 16 * PICCOLO - formato.ETICHETTA)
    monkeypatch.setattr(formato, "PASSO_MASSIMO", 32)


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


GRANDEZZE = [0, 1, 2, 15, 16, 17, 100, 239, 240, 241, 255, 256, 257, 4079, 4080,
             4081, 8159, 8160, 8161, 12240, 20000, 40000, 81600, 100000, 163199,
             163200, 163201, 250000, 333333, 500000]


def _scrivi(chiave, dati: bytes, informazioni=None) -> tuple[bytes, formato.Scritto]:
    fuori = io.BytesIO()
    if informazioni is None:
        informazioni = {"nome": "x"}
    scritto = formato.scrivi_byte(fuori, chiave, dati, informazioni)
    return fuori.getvalue(), scritto


def _dati(grandezza: int, seme: int = 0) -> bytes:
    return random.Random(grandezza * 7919 + seme).randbytes(grandezza)


def _apri(chiave, blob: bytes, **altro) -> formato.Contenuto:
    return formato.Contenuto(io.BytesIO(blob), chiave, **altro)


@pytest.mark.parametrize("grandezza", GRANDEZZE)
def test_si_rilegge_identico_bit_per_bit(chiave, grandezza):
    dati = _dati(grandezza)
    blob, scritto = _scrivi(chiave, dati)
    contenuto = _apri(chiave, blob)
    assert contenuto.tutto() == dati
    assert contenuto.dimensione == grandezza
    assert len(blob) == scritto.peso == contenuto.forma.peso
    assert scritto.blake2b == hashlib.blake2b(dati, digest_size=32).hexdigest()
    assert scritto.sha256 == hashlib.sha256(dati).hexdigest()
    assert contenuto.impronte == {"blake2b": scritto.blake2b, "sha256": scritto.sha256}
    assert not contenuto.da_riparare


@pytest.mark.parametrize("grandezza", GRANDEZZE)
def test_il_controllo_di_un_file_sano_e_perfetto(chiave, grandezza):
    blob, _ = _scrivi(chiave, _dati(grandezza))
    controllo = formato.controlla(io.BytesIO(blob), chiave)
    assert controllo.buono and controllo.leggibile and controllo.impronte_tornano
    assert not controllo.blocchi_rovinati and not controllo.riserve_rovinate


@pytest.mark.parametrize("grandezza", GRANDEZZE)
def test_le_riserve_sono_almeno_il_cinque_per_cento(chiave, grandezza):
    blob, _ = _scrivi(chiave, _dati(grandezza))
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    assert forma.riserve * 20 >= forma.pezzi
    for fascia in range(forma.fasce):
        dove = forma.dove_fascia(fascia)
        quanti = forma.pezzi_in(fascia)
        dati = blob[dove:dove + quanti * forma.pezzo]
        riserve = blob[dove + quanti * forma.pezzo:
                       dove + (quanti + forma.riserve_in(fascia)) * forma.pezzo]
        somma = bytearray(forma.passo * forma.pezzo)
        for inizio in range(0, len(dati), len(somma)):
            for i, byte in enumerate(dati[inizio:inizio + len(somma)]):
                somma[i] ^= byte
        assert bytes(somma[:len(riserve)]) == riserve


@pytest.mark.parametrize("grandezza", [0, 100, 4081, 100000])
def test_le_copie_di_testa_e_informazioni_sono_uguali(chiave, grandezza):
    blob, _ = _scrivi(chiave, _dati(grandezza))
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    assert blob[:formato.TESTA.size] == blob[-formato.TESTA.size:]
    assert (blob[formato.TESTA.size:forma.inizio]
            == blob[forma.peso - forma.inizio:forma.peso - formato.TESTA.size])


@pytest.mark.parametrize("informazioni", [
    {}, {"nome": "IMG_1234.jpg"}, {"nome": "perché così è più bello 🐶.heic"},
    {"cartella": "C:\\Foto\\2019\\Mare", "date": [1, 2, 3], "vuoto": None},
    {"lungo": "x" * 3000}, {"lunghissimo": "y" * 20000},
    {"nome": "rotto\udc80\ud800.jpg", "\udfff": ["\udcff"]},
])
def test_le_informazioni_tornano_uguali(chiave, informazioni):
    blob, _ = _scrivi(chiave, b"ciao", informazioni)
    assert _apri(chiave, blob).dati == informazioni


@pytest.mark.parametrize("parola", [b"IMG_1234", b"Mare", b"2019", "perché".encode(),
                                    b"segreto-dentro-il-file"])
def test_da_fuori_non_si_legge_niente(chiave, parola):
    dati = b"segreto-dentro-il-file" * 200
    blob, _ = _scrivi(chiave, dati, {"nome": "IMG_1234.jpg", "cartella": "Mare 2019",
                                     "nota": "perché"})
    assert parola not in blob


def test_lo_stesso_file_scritto_due_volte_non_si_somiglia(chiave):
    dati = _dati(50000)
    uno, _ = _scrivi(chiave, dati)
    due, _ = _scrivi(chiave, dati)
    assert uno != due
    assert sum(a == b for a, b in zip(uno[100:5000], due[100:5000])) < 100


def test_con_un_altra_chiave_non_si_apre(chiave):
    blob, _ = _scrivi(chiave, _dati(20000))
    altra = chiavi.Chiave(bytes(range(1, 33)))
    contenuto = _apri(altra, blob)
    assert contenuto.meta is None
    with pytest.raises(formato.ContenutoRovinato):
        contenuto.tutto()
    assert not formato.controlla(io.BytesIO(blob), altra).leggibile


def test_un_contenuto_scambiato_viene_scoperto(chiave):
    blob, _ = _scrivi(chiave, b"uno")
    with pytest.raises(formato.ContenutoRovinato):
        _apri(chiave, blob, numero=b"\x00" * 16)


@pytest.mark.parametrize("dichiarata, vera", [(10, 11), (10, 9), (0, 1), (5000, 4999),
                                              (5000, 5001), (100000, 0)])
def test_un_file_che_cambia_grandezza_mentre_si_copia(chiave, dichiarata, vera):
    scrittore = formato.Scrittore(io.BytesIO(), chiave, dichiarata, {})
    with pytest.raises(formato.FileCambiato):
        scrittore.write(b"x" * vera)
        scrittore.finisci()


@pytest.mark.parametrize("passo", [1, 7, 100, 4081, 65536])
def test_scrivere_a_pezzi_di_ogni_misura_da_lo_stesso_file(chiave, passo):
    dati = _dati(123457)
    fuori = io.BytesIO()
    scrittore = formato.Scrittore(fuori, chiave, len(dati), {})
    for inizio in range(0, len(dati), passo):
        scrittore.write(dati[inizio:inizio + passo])
    scritto = scrittore.finisci()
    assert _apri(chiave, fuori.getvalue()).tutto() == dati
    assert scritto.sha256 == hashlib.sha256(dati).hexdigest()


def test_si_scrive_solo_dall_inizio_del_file(chiave):
    fuori = io.BytesIO(b"gia qualcosa")
    fuori.seek(0, io.SEEK_END)
    with pytest.raises(ValueError):
        formato.Scrittore(fuori, chiave, 3, {})


@pytest.mark.parametrize("seme", range(25))
def test_leggere_da_un_punto_qualsiasi(chiave, seme):
    dati = _dati(250000, seme)
    blob, _ = _scrivi(chiave, dati)
    lettore = _apri(chiave, blob).apri()
    caso = random.Random(seme)
    for _ in range(20):
        dove = caso.randrange(0, len(dati) + 10)
        quanti = caso.choice([0, 1, 7, 4080, 4081, 10000, 99999])
        assert lettore.seek(dove) == dove
        assert lettore.read(quanti) == dati[dove:dove + quanti]
        assert lettore.tell() == min(len(dati), dove + quanti) or dove > len(dati)


def test_leggere_dalla_fine_e_da_dove_si_e(chiave):
    dati = _dati(9000)
    lettore = _apri(chiave, _scrivi(chiave, dati)[0]).apri()
    lettore.seek(-10, io.SEEK_END)
    assert lettore.read() == dati[-10:]
    lettore.seek(100)
    lettore.seek(50, io.SEEK_CUR)
    assert lettore.read(5) == dati[150:155]
    with pytest.raises((ValueError, OSError)):
        lettore.seek(-1)


@pytest.mark.parametrize("rovina", ["magia", "crc", "tutta", "zeri"])
def test_una_testa_rovinata_si_legge_dalla_copia_in_fondo(chiave, rovina):
    dati = _dati(30000)
    blob = bytearray(_scrivi(chiave, dati)[0])
    _rovina_testa(blob, 0, rovina)
    contenuto = _apri(chiave, bytes(blob))
    assert contenuto.testa_rovinata and contenuto.da_riparare
    assert contenuto.tutto() == dati


@pytest.mark.parametrize("rovina", ["magia", "crc", "tutta", "zeri"])
def test_una_testa_rovinata_in_fondo_si_nota(chiave, rovina):
    dati = _dati(30000)
    blob = bytearray(_scrivi(chiave, dati)[0])
    _rovina_testa(blob, len(blob) - formato.TESTA.size, rovina)
    contenuto = _apri(chiave, bytes(blob))
    assert contenuto.testa_rovinata
    assert contenuto.tutto() == dati


def test_due_teste_rovinate_si_aprono_con_quella_dell_elenco(chiave):
    dati = _dati(30000)
    blob, scritto = _scrivi(chiave, dati)
    rotto = bytearray(blob)
    rotto[:8] = b"xxxxxxxx"
    rotto[-8:] = b"yyyyyyyy"
    with pytest.raises(formato.ContenutoRovinato):
        _apri(chiave, bytes(rotto))
    assert _apri(chiave, bytes(rotto), testa=scritto.testa).tutto() == dati
    riparato = io.BytesIO()
    formato.ripara(io.BytesIO(bytes(rotto)), riparato, chiave, testa=scritto.testa)
    assert riparato.getvalue() == blob


@pytest.mark.parametrize("campo, valore", [
    ("versione", formato.VERSIONE + 1), ("pezzo", 100), ("pezzo", 2 ** 30),
    ("gruppo", 1), ("gruppo", 0), ("passo", 0), ("meta", 3), ("meta", 1000),
    ("blocco", 0), ("blocco", 4095),
])
def test_una_testa_con_numeri_strani_non_si_accetta(campo, valore):
    forma = formato.Forma.nuova(b"\x01" * 16, 1000, 50)
    campi = dict(forma.__dict__)
    campi[campo] = valore
    corpo = formato.TESTA.pack(
        formato.MAGIA, campi.get("versione", formato.VERSIONE), 0, campi["numero"],
        campi["blocco"], campi["pezzo"], campi["gruppo"], campi["passo"],
        campi["dimensione"], campi["meta"], bytes(8), 0)[:-4]
    import zlib
    testa = corpo + zlib.crc32(corpo).to_bytes(4, "big")
    with pytest.raises(ErroreOfficina):
        formato.Forma.da_testa(testa)


@pytest.mark.parametrize("dove", ["davanti", "dietro"])
def test_una_copia_delle_informazioni_rovinata_basta_l_altra(chiave, dove):
    dati = _dati(30000)
    blob, _ = _scrivi(chiave, dati, {"nome": "mare.jpg"})
    rotto = bytearray(blob)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    punto = formato.TESTA.size + 5 if dove == "davanti" else forma.peso - forma.inizio + 5
    rotto[punto] ^= 0xFF
    contenuto = _apri(chiave, bytes(rotto))
    assert contenuto.meta_rovinata and contenuto.dati == {"nome": "mare.jpg"}
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave)
    assert controllo.leggibile and not controllo.buono and controllo.meta_rovinata
    riparato = io.BytesIO()
    formato.ripara(io.BytesIO(bytes(rotto)), riparato, chiave)
    assert riparato.getvalue() == blob


def test_tutte_e_due_le_informazioni_rovinate_si_riparano_solo_con_l_elenco(chiave):
    dati = _dati(30000)
    blob, scritto = _scrivi(chiave, dati, {"nome": "mare.jpg"})
    rotto = bytearray(blob)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto[formato.TESTA.size + 5] ^= 1
    rotto[forma.peso - forma.inizio + 5] ^= 1
    contenuto = _apri(chiave, bytes(rotto))
    assert contenuto.meta is None and contenuto.tutto() == dati
    with pytest.raises(formato.ContenutoRovinato) as scoppio:
        formato.ripara(io.BytesIO(bytes(rotto)), io.BytesIO(), chiave)
    assert scoppio.value.codice == "senza_impronte"
    impronte = {"blake2b": scritto.blake2b, "sha256": scritto.sha256}
    with pytest.raises(formato.ContenutoRovinato) as scoppio:
        formato.ripara(io.BytesIO(bytes(rotto)), io.BytesIO(), chiave, impronte=impronte)
    assert scoppio.value.codice == "senza_informazioni"
    riparato = io.BytesIO()
    formato.ripara(io.BytesIO(bytes(rotto)), riparato, chiave, impronte=impronte,
                   dati={"nome": "mare.jpg"})
    assert _apri(chiave, riparato.getvalue()).dati == {"nome": "mare.jpg"}
    assert formato.controlla(io.BytesIO(riparato.getvalue()), chiave).buono


def test_impronte_sbagliate_dall_elenco_non_fanno_usare_la_riparazione(chiave):
    dati = _dati(30000)
    blob, _ = _scrivi(chiave, dati)
    rotto = bytearray(blob)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto[formato.TESTA.size + 5] ^= 1
    rotto[forma.peso - forma.inizio + 5] ^= 1
    finte = {"blake2b": "1" * 64, "sha256": "2" * 64}
    with pytest.raises(formato.ContenutoRovinato) as scoppio:
        formato.ripara(io.BytesIO(bytes(rotto)), io.BytesIO(), chiave, impronte=finte,
                       dati={})
    assert scoppio.value.codice == "riparazione_sbagliata"


def _testa_finta(forma: formato.Forma, **cambi) -> bytes:
    import zlib
    campi = dict(forma.__dict__, **cambi)
    corpo = formato.TESTA.pack(
        formato.MAGIA, formato.VERSIONE, 0, campi["numero"], campi["blocco"],
        campi["pezzo"], campi["gruppo"], campi["passo"], campi["dimensione"],
        campi["meta"], bytes(8), 0)[:-4]
    return corpo + zlib.crc32(corpo).to_bytes(4, "big")


@pytest.mark.parametrize("cambi", [
    {"passo": 7}, {"dimensione": 29999}, {"numero": b"\x09" * 16},
    {"dimensione": 10 ** 9},
])
def test_una_testa_davanti_che_sembra_buona_ma_mente_si_scopre(chiave, cambi):
    dati = _dati(30000)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto = bytearray(blob)
    rotto[:formato.TESTA.size] = _testa_finta(forma, **cambi)
    contenuto = _apri(chiave, bytes(rotto))
    assert contenuto.forma == forma and contenuto.testa_rovinata
    assert contenuto.tutto() == dati
    _ripara_e_confronta(chiave, blob, bytes(rotto))


def test_una_testa_che_chiede_troppa_memoria_non_si_accetta():
    forma = formato.Forma.nuova(b"\x01" * 16, 1000, 50)
    with pytest.raises(ErroreOfficina):
        formato.Forma.da_testa(_testa_finta(forma, gruppo=255, passo=65535,
                                            pezzo=2 ** 20,
                                            blocco=16 * 2 ** 20 - 16))


def test_impronte_diverse_fra_file_ed_elenco_non_si_ripara(chiave):
    dati = _dati(30000)
    blob, _ = _scrivi(chiave, dati)
    rotto = bytearray(blob)
    rotto[formato.TESTA.size + 5] ^= 1
    altre = {"blake2b": "1" * 64, "sha256": "2" * 64}
    with pytest.raises(formato.ContenutoRovinato) as scoppio:
        formato.ripara(io.BytesIO(bytes(rotto)), io.BytesIO(), chiave, impronte=altre)
    assert scoppio.value.codice == "impronte_diverse"
    assert not formato.controlla(io.BytesIO(bytes(rotto)), chiave,
                                 impronte=altre).leggibile


@pytest.mark.parametrize("come", ["bytes", "bytearray", "memoryview", "numeri"])
def test_si_scrive_da_ogni_genere_di_byte(chiave, come):
    import array
    numeri = array.array("I", range(200000))
    dati = numeri.tobytes()
    pezzo = {"bytes": dati, "bytearray": bytearray(dati),
             "memoryview": memoryview(dati), "numeri": numeri}[come]
    fuori = io.BytesIO()
    scrittore = formato.Scrittore(fuori, chiave, len(dati), {})
    assert scrittore.write(pezzo) == len(dati)
    scritto = scrittore.finisci()
    assert _apri(chiave, fuori.getvalue()).tutto() == dati
    assert scritto.sha256 == hashlib.sha256(dati).hexdigest()


def test_un_file_grande_scritto_tutto_insieme_non_rallenta(chiave):
    import time
    dati = _dati(24 * 1024 * 1024, 1)
    inizio = time.perf_counter()
    _scrivi(chiave, dati)
    assert time.perf_counter() - inizio < 30


DANNI_GRANDEZZE = [1, 300, 4080, 9000, 40000, 100000, 163201, 400000]


@pytest.mark.parametrize("grandezza", DANNI_GRANDEZZE)
@pytest.mark.parametrize("seme", range(8))
def test_un_bit_rovinato_nei_dati_si_ripara_da_solo(chiave, grandezza, seme):
    dati = _dati(grandezza, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    rotto = bytearray(blob)
    blocco = caso.randrange(forma.blocchi)
    dove = forma.dove_blocco(blocco) + caso.randrange(forma.lunghezza(blocco) + 16)
    rotto[dove] ^= 1 << caso.randrange(8)
    _deve_ripararsi(chiave, blob, bytes(rotto), dati, rovinati=[blocco])


@pytest.mark.parametrize("grandezza", DANNI_GRANDEZZE)
@pytest.mark.parametrize("seme", range(5))
def test_un_bit_rovinato_nelle_riserve_si_rifa(chiave, grandezza, seme):
    dati = _dati(grandezza, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    fascia = caso.randrange(forma.fasce)
    inizio = forma.dove_fascia(fascia) + forma.pezzi_in(fascia) * forma.pezzo
    rotto = bytearray(blob)
    rotto[inizio + caso.randrange(forma.riserve_in(fascia) * forma.pezzo)] ^= 0x80
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave)
    assert controllo.leggibile and not controllo.buono
    assert controllo.riserve_rovinate and not controllo.blocchi_rovinati
    _ripara_e_confronta(chiave, blob, bytes(rotto))


@pytest.mark.parametrize("grandezza", [1, 300, 4081, 9000, 100001])
def test_lo_spazio_vuoto_in_fondo_ai_dati_si_rimette_a_zero(chiave, grandezza):
    dati = _dati(grandezza)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    fine = forma.cifrato % forma.pezzo
    if not fine:
        pytest.skip("niente spazio vuoto per questa grandezza")
    ultima = forma.fasce - 1
    dove = (forma.dove_fascia(ultima)
            + (forma.pezzi_in(ultima) - 1) * forma.pezzo + fine)
    rotto = bytearray(blob)
    rotto[dove] ^= 0x01
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave)
    assert controllo.leggibile and controllo.riserve_rovinate
    _ripara_e_confronta(chiave, blob, bytes(rotto))


@pytest.mark.parametrize("grandezza", [9000, 40000, 100000, 163201, 400000])
@pytest.mark.parametrize("seme", range(6))
def test_un_buco_lungo_quanto_una_riga_si_ripara(chiave, grandezza, seme):
    dati = _dati(grandezza, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    fascia = caso.randrange(forma.fasce)
    quanti = min(forma.passo, forma.pezzi_in(fascia))
    primo = caso.randrange(0, forma.pezzi_in(fascia) - quanti + 1)
    inizio = forma.dove_fascia(fascia) + primo * forma.pezzo
    lungo = quanti * forma.pezzo
    rotto = bytearray(blob)
    rotto[inizio:inizio + lungo] = caso.randbytes(lungo)
    _deve_ripararsi(chiave, blob, bytes(rotto), dati)


@pytest.mark.parametrize("grandezza", [9000, 40000, 100000, 163201, 400000])
@pytest.mark.parametrize("seme", range(6))
def test_un_buco_storto_un_po_piu_corto_si_ripara(chiave, grandezza, seme):
    dati = _dati(grandezza, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme + 100)
    fascia = caso.randrange(forma.fasce)
    dati_fascia = forma.pezzi_in(fascia) * forma.pezzo
    lungo = min((forma.passo - 1) * forma.pezzo + 1, dati_fascia)
    inizio = forma.dove_fascia(fascia) + caso.randrange(0, dati_fascia - lungo + 1)
    rotto = bytearray(blob)
    rotto[inizio:inizio + lungo] = caso.randbytes(lungo)
    _deve_ripararsi(chiave, blob, bytes(rotto), dati)


@pytest.mark.parametrize("grandezza", [9000, 40000, 163201, 400000])
@pytest.mark.parametrize("seme", range(6))
def test_pezzi_che_non_si_leggono_si_rifanno(chiave, grandezza, seme):
    dati = _dati(grandezza, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    fascia = caso.randrange(forma.fasce)
    quanti = caso.randint(1, max(1, min(forma.passo, forma.pezzi_in(fascia))))
    primo = caso.randrange(0, forma.pezzi_in(fascia) - quanti + 1)
    inizio = forma.dove_fascia(fascia) + primo * forma.pezzo
    cattivo = DiscoConBuchi(blob, [(inizio, inizio + quanti * forma.pezzo)])
    controllo = formato.controlla(cattivo, chiave)
    assert controllo.leggibile and not controllo.buono
    riparato = io.BytesIO()
    formato.ripara(DiscoConBuchi(blob, [(inizio, inizio + quanti * forma.pezzo)]),
                   riparato, chiave)
    assert riparato.getvalue() == blob
    lettura = formato.Contenuto(DiscoConBuchi(blob, [(inizio, inizio + quanti * forma.pezzo)]),
                                chiave)
    assert lettura.tutto() == dati and lettura.da_riparare


@pytest.mark.parametrize("seme", range(10))
def test_due_pezzi_rovinati_nella_stessa_colonna_non_si_inventano(chiave, seme):
    dati = _dati(100000, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    colonna = caso.randrange(forma.passo)
    righe = caso.sample(range(forma.pezzi_in(0) // forma.passo), 2)
    rotto = bytearray(blob)
    for riga in righe:
        dove = forma.dove_fascia(0) + (riga * forma.passo + colonna) * forma.pezzo
        rotto[dove + caso.randrange(forma.pezzo)] ^= 0x04
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave)
    assert not controllo.leggibile and controllo.blocchi_persi
    with pytest.raises(formato.ContenutoRovinato) as scoppio:
        formato.ripara(io.BytesIO(bytes(rotto)), io.BytesIO(), chiave)
    assert scoppio.value.codice == "pezzo_perso"
    contenuto = _apri(chiave, bytes(rotto))
    with pytest.raises(formato.ContenutoRovinato):
        contenuto.tutto()


@pytest.mark.parametrize("taglio", ["meta_finale", "testa_finale", "riserve", "un_byte"])
def test_un_file_tagliato_in_fondo_si_ripara(chiave, taglio):
    dati = _dati(60000)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    via = {"meta_finale": forma.inizio, "testa_finale": formato.TESTA.size,
           "riserve": forma.inizio + forma.riserve_in(forma.fasce - 1) * forma.pezzo,
           "un_byte": 1}[taglio]
    corto = blob[:-via]
    contenuto = _apri(chiave, corto)
    assert contenuto.tagliato and contenuto.tutto() == dati
    _ripara_e_confronta(chiave, blob, corto)


@pytest.mark.parametrize("taglio", [0.1, 0.5, 0.9])
def test_un_file_tagliato_a_meta_non_da_dati_sbagliati(chiave, taglio):
    dati = _dati(60000)
    blob, scritto = _scrivi(chiave, dati)
    corto = blob[:int(len(blob) * taglio)]
    controllo = formato.controlla(io.BytesIO(corto), chiave, testa=scritto.testa)
    assert not controllo.buono and not controllo.leggibile


@pytest.mark.parametrize("seme", range(60))
def test_danni_a_caso_non_danno_mai_dati_sbagliati(chiave, seme):
    caso = random.Random(seme)
    dati = _dati(caso.choice([0, 50, 5000, 40000, 170000]), seme)
    blob, _ = _scrivi(chiave, dati)
    rotto = bytearray(blob)
    for _ in range(caso.randint(1, 40)):
        dove = caso.randrange(len(rotto))
        lungo = caso.choice([1, 1, 1, 3, 50, 300])
        rotto[dove:dove + lungo] = caso.randbytes(min(lungo, len(rotto) - dove))
    rotto = bytes(rotto)
    try:
        letto = _apri(chiave, rotto).tutto()
    except formato.ContenutoRovinato:
        letto = None
    assert letto is None or letto == dati
    controllo = formato.controlla(io.BytesIO(rotto), chiave)
    if controllo.leggibile:
        assert letto == dati
    riparato = io.BytesIO()
    try:
        formato.ripara(io.BytesIO(rotto), riparato, chiave)
    except formato.ContenutoRovinato:
        return
    assert _apri(chiave, riparato.getvalue()).tutto() == dati
    assert formato.controlla(io.BytesIO(riparato.getvalue()), chiave).buono


def test_un_pezzo_rovinato_si_ripara_anche_leggendo_a_salti(chiave):
    dati = _dati(170000)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto = bytearray(blob)
    rotto[forma.dove_blocco(20) + 7] ^= 1
    contenuto = _apri(chiave, bytes(rotto))
    lettore = contenuto.apri()
    lettore.seek(20 * forma.blocco + 5)
    assert lettore.read(100) == dati[20 * forma.blocco + 5:20 * forma.blocco + 105]
    assert contenuto.da_riparare


@pytest.mark.parametrize("grandezza", [0, 1, 4080, 4081, 70000])
def test_le_misure_vere_del_formato(monkeypatch, chiave, grandezza):
    monkeypatch.setattr(formato, "PEZZO", 4096)
    monkeypatch.setattr(formato, "BLOCCO", 16 * 4096 - 16)
    monkeypatch.setattr(formato, "PASSO_MASSIMO", 1024)
    dati = _dati(grandezza)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    assert forma.pezzo == 4096 and forma.blocco + 16 == 65536
    assert forma.inizio % 4096 == 0 and len(blob) % 4096 == 0
    assert _apri(chiave, blob).tutto() == dati


@pytest.mark.parametrize("spostato", [1, 5, 8, 11, 15])
def test_un_buco_a_cavallo_di_tre_blocchi_si_ripara(chiave, spostato):
    dati = _dati(100000, spostato)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    assert forma.passo == 2 * forma.per_blocco
    primo = 5 * forma.per_blocco + spostato
    inizio = forma.dove_fascia(0) + primo * forma.pezzo
    rotto = bytearray(blob)
    rotto[inizio:inizio + forma.passo * forma.pezzo] = random.Random(
        spostato).randbytes(forma.passo * forma.pezzo)
    _deve_ripararsi(chiave, blob, bytes(rotto), dati, rovinati=[5, 6, 7])


def test_un_file_rovinatissimo_non_fa_provare_all_infinito(monkeypatch, chiave):
    dati = _dati(500000, 3)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto = bytearray(blob)
    caso = random.Random(3)
    for blocco in range(0, forma.blocchi, 2):
        dove = forma.dove_blocco(blocco)
        for _ in range(6):
            rotto[dove + caso.randrange(forma.lunghezza(blocco))] ^= 0x10
    provate = []
    vera = formato._Sistemazione._prova_scelta

    def contata(self, *argomenti):
        provate.append(1)
        return vera(self, *argomenti)

    monkeypatch.setattr(formato._Sistemazione, "_prova_scelta", contata)
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave)
    assert not controllo.leggibile and controllo.blocchi_persi
    buchi = forma.per_blocco * (forma.per_blocco + 1) // 2
    assert len(provate) <= (forma.fasce * formato.TENTATIVI * 4
                            + forma.blocchi * buchi * 4)


def _rovina_testa(blob: bytearray, dove: int, come: str) -> None:
    if come == "magia":
        blob[dove] ^= 0xFF
    elif come == "crc":
        blob[dove + formato.TESTA.size - 1] ^= 0x01
    elif come == "tutta":
        blob[dove:dove + formato.TESTA.size] = bytes(range(formato.TESTA.size))
    else:
        blob[dove:dove + formato.TESTA.size] = bytes(formato.TESTA.size)


def _deve_ripararsi(chiave, blob: bytes, rotto: bytes, dati: bytes,
                    rovinati: list[int] | None = None) -> None:
    controllo = formato.controlla(io.BytesIO(rotto), chiave)
    assert controllo.leggibile and not controllo.buono, controllo
    if rovinati is not None:
        assert controllo.blocchi_rovinati == rovinati
    contenuto = _apri(chiave, rotto)
    assert contenuto.tutto() == dati and contenuto.da_riparare
    _ripara_e_confronta(chiave, blob, rotto)


def _ripara_e_confronta(chiave, blob: bytes, rotto: bytes) -> None:
    riparato = io.BytesIO()
    controllo = formato.ripara(io.BytesIO(rotto), riparato, chiave)
    assert controllo.buono
    assert riparato.getvalue() == blob


class DiscoConBuchi(io.RawIOBase):

    def __init__(self, dati: bytes, buchi: list[tuple[int, int]]):
        super().__init__()
        self._dati = dati
        self._buchi = buchi
        self._dove = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, dove, da=io.SEEK_SET):
        if da == io.SEEK_END:
            dove += len(self._dati)
        elif da == io.SEEK_CUR:
            dove += self._dove
        self._dove = dove
        return dove

    def tell(self):
        return self._dove

    def read(self, quanti=-1):
        fine = len(self._dati) if quanti < 0 else min(len(self._dati), self._dove + quanti)
        for inizio, chiusura in self._buchi:
            if self._dove < chiusura and fine > inizio:
                raise OSError(23, "Errore di dati (controllo di ridondanza ciclico)")
        letto = self._dati[self._dove:fine]
        self._dove = fine
        return letto


@pytest.mark.parametrize("grandezza", GRANDEZZE)
def test_il_controllo_passa_ogni_pezzo_in_ordine(chiave, grandezza):
    dati = _dati(grandezza)
    blob, _ = _scrivi(chiave, dati)
    visti = []
    controllo = formato.controlla(io.BytesIO(blob), chiave, ogni_pezzo=visti.append)
    assert controllo.buono
    assert b"".join(visti) == dati
    assert len(visti) == formato.Forma.da_testa(blob[:formato.TESTA.size]).blocchi


@pytest.mark.parametrize("seme", range(6))
def test_il_controllo_passa_i_pezzi_riparati(chiave, seme):
    dati = _dati(100000, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto = bytearray(blob)
    rotto[forma.dove_blocco(random.Random(seme).randrange(forma.blocchi)) + 3] ^= 0x10
    visti = []
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave,
                                  ogni_pezzo=visti.append)
    assert controllo.leggibile and not controllo.buono
    assert b"".join(visti) == dati


@pytest.mark.parametrize("seme", range(4))
def test_dopo_un_pezzo_perso_non_si_passa_piu_niente(chiave, seme):
    dati = _dati(100000, seme)
    blob, _ = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    caso = random.Random(seme)
    colonna = caso.randrange(forma.passo)
    rotto = bytearray(blob)
    for riga in caso.sample(range(forma.pezzi_in(0) // forma.passo), 2):
        dove = forma.dove_fascia(0) + (riga * forma.passo + colonna) * forma.pezzo
        rotto[dove + caso.randrange(forma.pezzo)] ^= 0x04
    visti = []
    controllo = formato.controlla(io.BytesIO(bytes(rotto)), chiave,
                                  ogni_pezzo=visti.append)
    assert not controllo.leggibile
    assert b"".join(visti) == dati[:len(b"".join(visti))]
    assert len(b"".join(visti)) < len(dati)


def test_chi_riceve_i_pezzi_puo_fermare_il_controllo(chiave):
    dati = _dati(50000)
    blob, _ = _scrivi(chiave, dati)

    class Basta(Exception):
        pass

    def ferma(pezzo):
        raise Basta

    with pytest.raises(Basta):
        formato.controlla(io.BytesIO(blob), chiave, ogni_pezzo=ferma)


@pytest.mark.parametrize("grandezza", GRANDEZZE)
def test_il_peso_previsto_e_quello_vero(chiave, grandezza):
    informazioni = {"nome": "IMG_0001.jpg"}
    blob, scritto = _scrivi(chiave, _dati(grandezza), informazioni)
    vere = len(formato._meta_in_byte({"blake2b": formato.VUOTA,
                                      "sha256": formato.VUOTA}, informazioni))
    assert formato.peso_previsto(grandezza, meta=vere) == scritto.peso
    assert formato.peso_previsto(grandezza) >= scritto.peso


@pytest.mark.parametrize("grandezza", [0, 1, 4080, 4081, 100000, 250000])
def test_la_rilettura_da_i_pezzi_e_poi_il_controllo(chiave, grandezza):
    dati = _dati(grandezza)
    blob, scritto = _scrivi(chiave, dati)
    impronte = {"blake2b": scritto.blake2b, "sha256": scritto.sha256}
    rilettura = formato.Rilettura(io.BytesIO(blob), chiave,
                                  numero=bytes.fromhex(scritto.numero),
                                  testa=scritto.testa, impronte=impronte)
    assert rilettura.controllo is None
    pezzi = list(rilettura)
    assert b"".join(pezzi) == dati
    assert rilettura.controllo == formato.controlla(io.BytesIO(blob), chiave)
    assert rilettura.controllo.buono and rilettura.controllo.impronte_tornano
    assert list(rilettura) == []
    assert rilettura.controllo.buono


def test_una_rilettura_lasciata_a_meta_non_ha_controllo(chiave):
    dati = _dati(100000)
    blob, _ = _scrivi(chiave, dati)
    rilettura = formato.Rilettura(io.BytesIO(blob), chiave)
    pezzi = iter(rilettura)
    primo = next(pezzi)
    assert primo and dati.startswith(primo) and len(primo) < len(dati)
    assert rilettura.controllo is None
    pezzi.close()
    assert rilettura.controllo is None
    assert list(rilettura) == []
    assert rilettura.controllo is None


@pytest.mark.parametrize("rovina", [0, 3, formato.TESTA.size - 1])
def test_una_rilettura_senza_testa_buona_non_da_niente(chiave, rovina):
    blob, _ = _scrivi(chiave, _dati(30000))
    rotto = bytearray(blob)
    rotto[rovina] ^= 0x20
    rotto[-formato.TESTA.size + rovina] ^= 0x20
    rilettura = formato.Rilettura(io.BytesIO(bytes(rotto)), chiave)
    assert rilettura.controllo is not None
    assert not rilettura.controllo.leggibile and rilettura.controllo.testa_rovinata
    assert list(rilettura) == []
    assert not rilettura.controllo.buono


def test_una_rilettura_con_le_impronte_sbagliate_non_e_leggibile(chiave):
    dati = _dati(30000)
    blob, scritto = _scrivi(chiave, dati)
    altre = {"blake2b": "1" * 64, "sha256": scritto.sha256}
    rilettura = formato.Rilettura(io.BytesIO(blob), chiave, impronte=altre)
    assert b"".join(rilettura) == dati
    assert not rilettura.controllo.leggibile and not rilettura.controllo.buono
    assert not rilettura.controllo.impronte_tornano


def test_una_rilettura_con_un_pezzo_riparato_e_leggibile_ma_non_buona(chiave):
    dati = _dati(100000, 3)
    blob, scritto = _scrivi(chiave, dati)
    forma = formato.Forma.da_testa(blob[:formato.TESTA.size])
    rotto = bytearray(blob)
    rotto[forma.dove_blocco(1) + 9] ^= 0x01
    rilettura = formato.Rilettura(io.BytesIO(bytes(rotto)), chiave,
                                  impronte={"blake2b": scritto.blake2b,
                                            "sha256": scritto.sha256})
    assert b"".join(rilettura) == dati
    assert rilettura.controllo.leggibile and not rilettura.controllo.buono
    assert rilettura.controllo.blocchi_rovinati
