from __future__ import annotations

import json
import os
import random
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro import chiavetta, chiavi, controllo, elenco, formato, recupera
from officina.sicuro.chiavetta import CARTELLA
from officina.sicuro.diretto import ALLINEA
from officina.sicuro.recupera import (ARRIVO, CERCA, FINE, PASSWORD as FASE_PASSWORD,
                                      RAPPORTO, Recupero, Regia, accanto,
                                      dove_di_solito, e_un_archivio, misura, numero,
                                      trova)
from officina.sicuro.sottofondo import ERRORE, FERMATO, FERMO, FINITO
from prove.test_sicuro_chiavetta import _PORTA, ATTESA, LIBERO, PASSWORD, Prova, Stacca, _danneggia
from prove.test_sicuro_copia import Apri, _dati

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture(autouse=True)
def pezzi_piccoli(monkeypatch):
    monkeypatch.setattr(chiavetta, "PEZZO", 3 * ALLINEA)
    monkeypatch.setattr(controllo, "PEZZO_DI_LETTURA", 3 * ALLINEA)


@contextmanager
def _sveglio():
    yield True


def _recupero(archivio, **opzioni) -> Recupero:
    opzioni.setdefault("apri", Apri())
    opzioni.setdefault("spazio", lambda dove: LIBERO)
    opzioni.setdefault("windows", False)
    opzioni.setdefault("sveglio", _sveglio)
    return Recupero(archivio, **opzioni)


def _fabbrica(**opzioni):
    def fabbrica(archivio):
        return _recupero(archivio, **dict(opzioni))
    return fabbrica


def _fotografia(radice: Path) -> dict:
    fatto = {}
    for percorso in sorted(radice.rglob("*")):
        informazioni = os.lstat(percorso)
        dati = percorso.read_bytes() if percorso.is_file() else None
        fatto[percorso.relative_to(radice).as_posix()] = (informazioni.st_mtime_ns,
                                                          informazioni.st_size, dati)
    return fatto


def _uscite(cartella: Path) -> dict[str, bytes]:
    return {percorso.relative_to(cartella).as_posix(): percorso.read_bytes()
            for percorso in sorted(cartella.rglob("*")) if percorso.is_file()}


def _fino_in_fondo(recupero: Recupero, dove: Path) -> dict:
    assert recupero.parti(dove)
    assert recupero.aspetta_fine(ATTESA)
    return recupero.riassunto()


def _pronta(tmp_path, chiave, quante=3, **opzioni) -> Prova:
    prova = Prova(tmp_path, chiave)
    prova.foto(quante, **opzioni)
    prova.pronta()
    return prova


def _scrivi_la_chiave(prova: Prova, documento: dict) -> None:
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (prova.dove / nome).write_bytes(chiavi._in_byte(documento))


def test_tutto_esce_uguale_e_la_chiavetta_non_si_tocca(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave, 5)
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    assert recupero.sbloccato
    assert recupero.quanto() == (5, sum(len(dati) for dati in prova.file.values()))
    fuori = tmp_path / "fuori"
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["stato"] == FINITO and riassunto["verde"]
    assert riassunto["rossi"] == 0 and riassunto["rifiutate"] == 0
    assert riassunto["file"] == 5
    assert riassunto["frase"].startswith("Fatto! Sono uscite tutte: 5 file")
    assert _uscite(fuori / "foto") == prova.file
    assert riassunto["cartelle"] == [str(fuori / "foto")]
    assert not recupero.da_raccontare()
    assert recupero.rapporto() is None
    assert sorted(os.listdir(fuori)) == ["foto"]
    avanzamento = recupero.avanzamento()
    assert (avanzamento["file"], avanzamento["byte"]) == recupero.quanto()
    assert avanzamento["percorso"] is None
    recupero.chiudi()
    assert _fotografia(prova.radice) == prima


def test_le_foto_escono_anche_dalla_copia_sul_computer(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    recupero = _recupero(prova.banco.archivio)
    recupero.sblocca(PASSWORD)
    riassunto = _fino_in_fondo(recupero, tmp_path / "fuori")
    assert riassunto["verde"]
    assert _uscite(tmp_path / "fuori" / "foto") == prova.file
    recupero.chiudi()


def test_prima_di_sbloccare_non_si_parte_e_il_riassunto_e_vuoto(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    recupero = _recupero(prova.dove)
    with pytest.raises(ErroreOfficina) as guasto:
        recupero.parti(tmp_path / "fuori")
    assert guasto.value.codice == "da_sbloccare"
    assert recupero.riassunto()["stato"] == FERMO
    assert recupero.avanzamento()["file"] == 0
    assert not recupero.da_raccontare()
    assert recupero.rapporto() is None
    assert recupero.aspetta_fine(0)
    recupero.ferma()
    recupero.chiudi()
    assert not (tmp_path / "fuori").exists()


def test_password_sbagliata_non_tocca_niente_e_si_riprova(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    with pytest.raises(PasswordSbagliata, match="non sono state toccate"):
        recupero.sblocca("una password sbagliata")
    assert not recupero.sbloccato
    with pytest.raises(PasswordSbagliata, match="Scrivi la password"):
        recupero.sblocca("")
    assert _fotografia(prova.radice) == prima
    recupero.sblocca(PASSWORD)
    assert recupero.sbloccato
    recupero.sblocca("adesso non conta più")
    assert _fino_in_fondo(recupero, tmp_path / "fuori")["verde"]
    recupero.chiudi()
    assert _fotografia(prova.radice) == prima


@pytest.mark.parametrize("rotta", [chiavi.FILE, chiavi.RISERVA])
def test_una_copia_della_chiave_rovinata_basta_l_altra_e_non_si_ripara(
        tmp_path, chiave, rotta):
    prova = _pronta(tmp_path, chiave)
    (prova.dove / rotta).write_bytes(b"{rotto")
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    assert _fino_in_fondo(recupero, tmp_path / "fuori")["verde"]
    recupero.chiudi()
    assert (prova.dove / rotta).read_bytes() == b"{rotto"
    assert _fotografia(prova.radice) == prima


def test_tutte_e_due_le_copie_della_chiave_rovinate(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (prova.dove / nome).write_bytes(b"rovinata")
    with pytest.raises(chiavi.ChiaveRovinata, match="altra copia dell'archivio"):
        _recupero(prova.dove).sblocca(PASSWORD)


def test_senza_la_chiave_si_dice_quale_cartella_scegliere(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (prova.dove / nome).unlink()
    with pytest.raises(ErroreOfficina, match="chiave.json") as guasto:
        _recupero(prova.dove).sblocca(PASSWORD)
    assert guasto.value.codice == "sicuro_mancante"


def test_una_chiave_di_una_versione_piu_nuova(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    (prova.dove / chiavi.FILE).write_text(
        json.dumps({"tipo": chiavi.TIPO, "versione": 99}), "utf-8")
    with pytest.raises(ErroreOfficina, match="stessa chiavetta") as guasto:
        _recupero(prova.dove).sblocca(PASSWORD)
    assert guasto.value.codice == "versione_piu_nuova"


def test_una_chiave_mescolata_con_un_altra(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    altra = chiavi.Chiave(bytes(range(1, 33)))
    _scrivi_la_chiave(prova, chiavi._documento(altra, [_PORTA["porta"]]))
    with pytest.raises(chiavi.ChiaveRovinata, match="mescolato"):
        _recupero(prova.dove).sblocca(PASSWORD)


def test_la_chiave_di_un_altro_archivio_non_apre_i_file(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    altra = chiavi.Chiave(bytes(range(1, 33)))
    _scrivi_la_chiave(prova, chiavi._documento(
        altra, [chiavi._porta(altra, PASSWORD, chiavi.COSTO)]))
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    with pytest.raises(ErroreOfficina, match="mescolata") as guasto:
        recupero.sblocca(PASSWORD)
    assert guasto.value.codice == "chiave_diversa"
    assert not recupero.sbloccato and recupero.totali == {}
    assert _fotografia(prova.radice) == prima


def test_la_chiavetta_staccata_prima_di_cominciare(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    prova.stacca()
    with pytest.raises(ErroreOfficina, match="ricollega") as guasto:
        _recupero(prova.dove).sblocca(PASSWORD)
    assert guasto.value.codice == "archivio_sparito"


def test_l_elenco_rovinato_si_ritrova_e_si_racconta(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave, 4)
    for fotografia in (prova.dove / elenco.ELENCO).iterdir():
        fotografia.write_bytes(b"rovinata")
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    assert recupero.note()
    fuori = tmp_path / "fuori"
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["verde"] and riassunto["note"] == recupero.note()
    assert _uscite(fuori / "foto") == prova.file
    assert recupero.da_raccontare()
    scritto = recupero.rapporto()
    assert scritto == fuori / RAPPORTO
    testo = scritto.read_text("utf-8-sig")
    assert "Da sapere sull'archivio:" in testo
    assert recupero.riassunto()["frase"].endswith(
        f"Trovi tutti i dettagli in «{RAPPORTO}», nella cartella dove hai messo le "
        "foto.")
    recupero.chiudi()
    assert _fotografia(prova.radice) == prima


def test_un_file_rovinato_si_dice_nel_rapporto(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[2 * formato.BLOCCO])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[1]), numeri[1], "tutto", random.Random(1))
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    fuori = tmp_path / "fuori"
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["stato"] == FINITO and not riassunto["verde"]
    assert riassunto["rossi"] == 1
    assert riassunto["esito"].startswith("Finito, ma 1 file non è uscito bene. ")
    sani = {nome: dati for nome, dati in prova.file.items() if nome != "s1/f1.jpg"}
    uscite = _uscite(fuori / "foto")
    assert {nome: uscite[nome] for nome in sani} == sani
    scritto = recupero.rapporto()
    grezzo = scritto.read_bytes()
    assert grezzo.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in grezzo.replace(b"\r\n", b"")
    testo = grezzo.decode("utf-8-sig")
    assert "Non usciti bene:" in testo and "s1/f1.jpg" in testo
    assert f"Archivio: {prova.dove}" in testo
    assert f"Foto messe in: {fuori}" in testo
    assert f"Cartella {prova.banco.sorgente}" in testo
    assert RAPPORTO in recupero.riassunto()["frase"]
    secondo = recupero.rapporto()
    assert secondo.name == "Cosa è successo nel recupero (2).txt"
    assert scritto.read_bytes() == grezzo
    recupero.chiudi()
    assert _fotografia(prova.radice) == prima


@su_linux
@pytest.mark.parametrize("quando", [1, 2, 3])
def test_la_chiavetta_staccata_a_meta(tmp_path, chiave, quando):
    prova = Prova(tmp_path, chiave)
    prova.foto(3, misure=[2 * formato.BLOCCO])
    prova.pronta()
    prima = _fotografia(prova.radice)
    apri = Apri()
    apri.regole.append(Stacca(prova, quando))
    recupero = _recupero(prova.dove, apri=apri)
    recupero.sblocca(PASSWORD)
    fuori = tmp_path / "fuori"
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["stato"] == ERRORE
    assert recupero.estrazione.codice == "archivio_sparito"
    assert riassunto["esito"] == recupera.FERMATE["archivio_sparito"]
    assert not riassunto["verde"]
    uscite = _uscite(fuori / "foto")
    for nome, dati in uscite.items():
        assert prova.file[nome] == dati, nome
    scritto = recupero.rapporto()
    assert scritto is not None and scritto.parent == fuori
    assert "Non è arrivata alla fine." in scritto.read_text("utf-8-sig")
    recupero.chiudi()
    prova.riattacca()
    assert _fotografia(prova.radice) == prima


def test_poco_spazio_si_dice_prima_di_cominciare(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    recupero = _recupero(prova.dove, spazio=lambda dove: 0)
    recupero.sblocca(PASSWORD)
    with pytest.raises(ErroreOfficina, match="Per tirare fuori tutto servono") as guasto:
        recupero.parti(tmp_path / "fuori")
    assert guasto.value.codice == "poco_spazio"
    assert not recupero.acceso and recupero.dove is None
    assert not (tmp_path / "fuori").exists()
    recupero.chiudi()


def test_appena_lo_spazio_che_serve_piu_il_margine_basta(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    _, serve = recupero.quanto()
    recupero._spazio = None
    recupero.estrazione.estrattore._spazio = lambda dove: serve + recupera.MARGINE - 1
    with pytest.raises(ErroreOfficina) as guasto:
        recupero.parti(tmp_path / "fuori")
    assert guasto.value.codice == "poco_spazio"
    recupero.estrazione.estrattore._spazio = lambda dove: serve + recupera.MARGINE
    assert _fino_in_fondo(recupero, tmp_path / "fuori")["verde"]
    recupero.chiudi()


def test_una_cartella_che_non_si_legge(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)

    def spazio(dove):
        raise OSError("finto")

    recupero = _recupero(prova.dove, spazio=spazio)
    recupero.sblocca(PASSWORD)
    with pytest.raises(ErroreOfficina) as guasto:
        recupero.parti(tmp_path / "fuori")
    assert guasto.value.codice == "dove_strano"
    recupero.chiudi()


@pytest.mark.parametrize("dentro", ["", "contenuti", "nuova/sotto"])
def test_non_si_estrae_dentro_l_archivio(tmp_path, chiave, dentro):
    prova = _pronta(tmp_path, chiave)
    prima = _fotografia(prova.radice)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    with pytest.raises(ErroreOfficina) as guasto:
        recupero.parti(prova.dove / dentro)
    assert guasto.value.codice == "estrai_nell_archivio"
    recupero.chiudi()
    assert _fotografia(prova.radice) == prima


def test_un_archivio_vuoto_non_ha_niente_da_tirare_fuori(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.banco.giro()
    prova.pronta()
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    assert recupero.quanto() == (0, 0)
    with pytest.raises(ErroreOfficina) as guasto:
        recupero.parti(tmp_path / "fuori")
    assert guasto.value.codice == "niente_da_estrarre"
    recupero.chiudi()


def test_due_cartelle_con_lo_stesso_nome_non_si_mescolano(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    altra = tmp_path / "altro" / "foto"
    altra.mkdir(parents=True)
    altri = {"b.jpg": _dati(500, 7), "dentro/c.jpg": _dati(70, 8)}
    for nome, dati in altri.items():
        (altra / nome).parent.mkdir(parents=True, exist_ok=True)
        (altra / nome).write_bytes(dati)
    prova.banco.elenco.registra([elenco.fatto_radice("r2", str(altra), quando=1000.0)])
    prova.banco.copiatore.copia_radice(prova.banco.radice("r2"))
    prova.pronta()
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    assert recupero.quanto()[0] == 4
    fuori = tmp_path / "fuori"
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["verde"] and riassunto["file"] == 4
    cartelle = {Path(cartella).name: cartella for cartella in riassunto["cartelle"]}
    assert set(cartelle) == {"foto", "foto (2)"}
    trovati = sorted([_uscite(fuori / "foto"), _uscite(fuori / "foto (2)")],
                     key=len)
    assert trovati == sorted([prova.file, altri], key=len)
    recupero.chiudi()


def test_una_cartella_gia_piena_non_si_tocca(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    fuori = tmp_path / "fuori"
    (fuori / "foto").mkdir(parents=True)
    (fuori / "foto" / "mia.txt").write_bytes(b"non toccare")
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    riassunto = _fino_in_fondo(recupero, fuori)
    assert riassunto["verde"]
    assert _uscite(fuori / "foto") == {"mia.txt": b"non toccare"}
    assert _uscite(fuori / "foto (2)") == prova.file
    recupero.chiudi()


def test_la_seconda_volta_esce_accanto_alla_prima(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    recupero = _recupero(prova.dove)
    recupero.sblocca(PASSWORD)
    fuori = tmp_path / "fuori"
    assert _fino_in_fondo(recupero, fuori)["verde"]
    assert recupero.avanzamento()["file"] == 3
    assert _fino_in_fondo(recupero, fuori)["verde"]
    assert _uscite(fuori / "foto") == prova.file
    assert _uscite(fuori / "foto (2)") == prova.file
    recupero.chiudi()


class Trattieni:

    def __init__(self):
        self.dentro = threading.Event()
        self.porta = threading.Event()

    def __call__(self, nome, senza_cache, volta, lettore):
        self.dentro.set()
        self.porta.wait(ATTESA)
        return lettore


def test_l_avanzamento_non_torna_mai_indietro(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave, 6)
    apri = Apri()
    porte = []

    def piano(nome, senza_cache, volta, lettore):
        evento = threading.Event()
        porte.append(evento)
        evento.wait(ATTESA)
        return lettore

    apri.regole.append(piano)
    recupero = _recupero(prova.dove, apri=apri)
    recupero.sblocca(PASSWORD)
    assert recupero.parti(tmp_path / "fuori")
    assert not recupero.parti(tmp_path / "altrove")
    visti = []
    aperte = 0
    while recupero.acceso:
        visti.append(recupero.avanzamento())
        while aperte < len(porte):
            porte[aperte].set()
            aperte += 1
        recupero.aspetta_fine(0.01)
    visti.append(recupero.avanzamento())
    for prima, dopo in zip(visti, visti[1:]):
        assert dopo["file"] >= prima["file"] and dopo["byte"] >= prima["byte"]
    assert (visti[-1]["file"], visti[-1]["byte"]) == recupero.quanto()
    assert recupero.riassunto()["verde"]
    assert not (tmp_path / "altrove").exists()
    recupero.chiudi()


def test_mentre_lavora_la_frase_dice_quanto_e_uscito(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    trattieni = Trattieni()
    apri = Apri()
    apri.regole.append(trattieni)
    recupero = _recupero(prova.dove, apri=apri)
    recupero.sblocca(PASSWORD)
    assert recupero.parti(tmp_path / "fuori")
    assert trattieni.dentro.wait(ATTESA)
    riassunto = recupero.riassunto()
    assert riassunto["esito"].startswith("Sto tirando fuori le foto: finora ")
    assert not recupero.da_raccontare()
    assert recupero.avanzamento()["percorso"] is not None
    trattieni.porta.set()
    assert recupero.aspetta_fine(ATTESA)
    recupero.chiudi()


def test_fermato_a_meta_si_racconta(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    trattieni = Trattieni()
    apri = Apri()
    apri.regole.append(trattieni)
    recupero = _recupero(prova.dove, apri=apri)
    recupero.sblocca(PASSWORD)
    assert recupero.parti(tmp_path / "fuori")
    assert trattieni.dentro.wait(ATTESA)
    recupero.ferma()
    trattieni.porta.set()
    assert recupero.aspetta_fine(ATTESA)
    riassunto = recupero.riassunto()
    assert riassunto["stato"] == FERMATO and not riassunto["verde"]
    assert riassunto["esito"].startswith("Fermato. Quello che è già uscito resta: ")
    assert recupero.rapporto() is not None
    recupero.chiudi()


def test_chiudi_mentre_lavora_ferma_tutto(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    trattieni = Trattieni()
    apri = Apri()
    apri.regole.append(trattieni)
    recupero = _recupero(prova.dove, apri=apri)
    recupero.sblocca(PASSWORD)
    assert recupero.parti(tmp_path / "fuori")
    assert trattieni.dentro.wait(ATTESA)
    threading.Timer(0.2, trattieni.porta.set).start()
    recupero.chiudi()
    assert not recupero.acceso
    assert recupero.elenco is None
    assert recupero.riassunto()["stato"] == FERMATO
    recupero.chiudi()


def test_la_regia_porta_fino_in_fondo(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    prima = _fotografia(prova.radice)
    fuori = tmp_path / "fuori"
    regia = Regia(prova.dove, fuori, fabbrica=_fabbrica())
    quadro = regia.quadro()
    assert quadro["fase"] == FASE_PASSWORD and quadro["frazione"] is None
    assert quadro["archivio"] == str(prova.dove) and quadro["dove"] == str(fuori)
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FINE and quadro["verde"]
    assert quadro["frazione"] == 1.0
    assert quadro["testo"].startswith("3 di 3 file · ")
    assert quadro["cartella"] == str(fuori) and quadro["rapporto"] is None
    assert quadro["stato"] == FINITO and quadro["file"] == 3 and quadro["rossi"] == 0
    assert quadro["frase"].startswith("Fatto!")
    assert not regia.inizia(PASSWORD)
    assert _uscite(fuori / "foto") == prova.file
    regia.chiudi()
    assert _fotografia(prova.radice) == prima


def test_la_regia_con_la_password_sbagliata_torna_indietro(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    fatti = []

    def fabbrica(archivio):
        fatti.append(_recupero(archivio))
        return fatti[-1]

    regia = Regia(prova.dove, tmp_path / "fuori", fabbrica=fabbrica)
    assert regia.inizia("una password sbagliata")
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FASE_PASSWORD
    assert quadro["codice"] == "password_sbagliata"
    assert "non sono state toccate" in quadro["errore"]
    assert not (tmp_path / "fuori").exists()
    assert regia.inizia(PASSWORD, tmp_path / "altrove")
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FINE and quadro["verde"] and quadro["errore"] is None
    assert len(fatti) == 1
    assert _uscite(tmp_path / "altrove" / "foto") == prova.file
    regia.chiudi()


def test_la_regia_racconta_un_file_rovinato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[2 * formato.BLOCCO])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[0]), numeri[0], "tutto", random.Random(2))
    regia = Regia(prova.dove, tmp_path / "fuori", fabbrica=_fabbrica())
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FINE and not quadro["verde"]
    assert quadro["rossi"] == 1
    assert quadro["rapporto"] == str(tmp_path / "fuori" / RAPPORTO)
    assert RAPPORTO in quadro["frase"]
    regia.chiudi()


def test_la_regia_con_poco_spazio_torna_alla_password(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    regia = Regia(prova.dove, tmp_path / "fuori",
                  fabbrica=_fabbrica(spazio=lambda dove: 0))
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FASE_PASSWORD and quadro["codice"] == "poco_spazio"
    assert "servono" in quadro["errore"]
    regia.chiudi()


def test_la_regia_non_parte_fuori_dalla_fase_password(tmp_path, chiave):
    regia = Regia(None, tmp_path / "fuori", fabbrica=_fabbrica())
    assert regia.fase == CERCA
    assert not regia.inizia(PASSWORD)
    assert regia.aspetta(0)
    assert regia.quadro()["fase"] == CERCA
    regia.chiudi()


def test_la_regia_fermata_mentre_lavora(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    trattieni = Trattieni()
    apri = Apri()
    apri.regole.append(trattieni)
    regia = Regia(prova.dove, tmp_path / "fuori", fabbrica=_fabbrica(apri=apri))
    assert regia.inizia(PASSWORD)
    assert trattieni.dentro.wait(ATTESA)
    regia.ferma()
    trattieni.porta.set()
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FINE and quadro["stato"] == FERMATO
    assert not quadro["verde"]
    assert quadro["frase"].startswith("Fermato.")
    regia.chiudi()


def test_la_regia_fermata_mentre_apre_l_archivio(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    dentro = threading.Event()
    porta = threading.Event()

    class Lento(Recupero):

        def sblocca(self, password):
            dentro.set()
            porta.wait(ATTESA)
            super().sblocca(password)

    def fabbrica(archivio):
        return Lento(archivio, apri=Apri(), spazio=lambda dove: LIBERO,
                     windows=False, sveglio=_sveglio)

    regia = Regia(prova.dove, tmp_path / "fuori", fabbrica=fabbrica)
    assert regia.inizia(PASSWORD)
    assert dentro.wait(ATTESA)
    assert regia.quadro()["fase"] == recupera.SBLOCCO
    assert not regia.inizia(PASSWORD)
    regia.ferma()
    porta.set()
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FASE_PASSWORD and quadro["errore"] is None
    assert not (tmp_path / "fuori").exists()
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    assert regia.quadro()["verde"]
    regia.chiudi()


def test_la_regia_dice_quando_qualcosa_va_storto(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)

    def fabbrica(archivio):
        raise RuntimeError("guasto finto")

    regia = Regia(prova.dove, tmp_path / "fuori", fabbrica=fabbrica)
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    quadro = regia.quadro()
    assert quadro["fase"] == FASE_PASSWORD
    assert quadro["errore"] == "Qualcosa è andato storto: guasto finto"
    assert quadro["codice"] == "RuntimeError"
    regia.chiudi()


def test_la_regia_sceglie_l_archivio(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    regia = Regia(fabbrica=_fabbrica())
    assert regia.fase == CERCA and regia.archivio is None
    assert regia.dove == dove_di_solito() == Path.home() / ARRIVO
    (tmp_path / "vuota").mkdir()
    assert not regia.scegli_archivio(tmp_path / "vuota")
    assert regia.codice == "non_e_un_archivio" and regia.fase == CERCA
    assert not regia.scegli_archivio("")
    assert regia.scegli_archivio(prova.radice)
    assert regia.archivio == prova.dove and regia.fase == FASE_PASSWORD
    assert regia.errore is None and regia.codice is None
    assert regia.scegli_archivio(prova.dove / elenco.CONTENUTI)
    assert regia.archivio == prova.dove
    regia.scegli_dove("")
    assert regia.dove == Path.home() / ARRIVO
    regia.scegli_dove(tmp_path / "fuori")
    assert regia.dove == tmp_path / "fuori"
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    assert regia.quadro()["verde"]
    assert not regia.scegli_archivio(prova.radice) or regia.fase == FASE_PASSWORD
    regia.chiudi()


def test_cambiare_archivio_chiude_quello_di_prima(tmp_path, chiave):
    (tmp_path / "uno").mkdir()
    (tmp_path / "due").mkdir()
    prima = _pronta(tmp_path / "uno", chiave, 2)
    seconda = _pronta(tmp_path / "due", chiave, 1, seme=5)
    fatti = []

    def fabbrica(archivio):
        fatti.append(_recupero(archivio))
        return fatti[-1]

    regia = Regia(prima.dove, tmp_path / "fuori", fabbrica=fabbrica)
    assert regia.inizia("una password sbagliata")
    assert regia.aspetta(ATTESA)
    assert regia.scegli_archivio(seconda.radice)
    assert regia.recupero is None
    assert regia.inizia(PASSWORD)
    assert regia.aspetta(ATTESA)
    assert regia.quadro()["verde"]
    assert [recupero.archivio for recupero in fatti] == [prima.dove, seconda.dove]
    assert _uscite(tmp_path / "fuori" / "foto") == seconda.file
    regia.chiudi()


def test_trova_la_cartella_dell_archivio(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    assert trova(prova.radice) == prova.dove
    assert trova(str(prova.radice)) == prova.dove
    assert trova(prova.dove) == prova.dove
    assert trova(prova.dove / elenco.CONTENUTI) == prova.dove
    assert trova(prova.dove / elenco.ELENCO) == prova.dove
    assert trova(prova.banco.archivio) == prova.banco.archivio
    assert trova(None) is None
    assert trova(tmp_path / "non c'è") is None
    assert trova(tmp_path / "foto") is None
    assert e_un_archivio(prova.dove)
    assert not e_un_archivio(prova.radice)
    assert not e_un_archivio(tmp_path / "non c'è")
    assert not e_un_archivio("\x00")


def test_trova_anche_senza_chiave_se_ci_sono_i_contenuti(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (prova.dove / nome).unlink()
    assert trova(prova.radice) == prova.dove
    falsa = tmp_path / "falsa" / CARTELLA
    falsa.mkdir(parents=True)
    (falsa / elenco.CONTENUTI).write_bytes(b"non sono una cartella")
    assert trova(falsa.parent) is None


def test_accanto_guarda_dove_sta_il_programmino(tmp_path, monkeypatch):
    programmino = tmp_path / "E" / "Recupera foto.exe"
    programmino.parent.mkdir()
    programmino.write_bytes(b"finto")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(programmino))
    assert accanto() == programmino.parent.resolve()
    monkeypatch.setattr(sys, "frozen", False)
    monkeypatch.chdir(tmp_path)
    assert accanto() == Path.cwd()


@pytest.mark.parametrize("quanti, scritto", [(0, "0"), (999, "999"), (1000, "1.000"),
                                             (1234567, "1.234.567")])
def test_i_numeri_si_scrivono_all_italiana(quanti, scritto):
    assert numero(quanti) == scritto


@pytest.mark.parametrize("byte, scritto", [
    (0, "0 byte"), (1023, "1023 byte"), (1024, "1,0 KB"), (1536, "1,5 KB"),
    (5 * 1024 ** 2, "5,0 MB"), (3 * 1024 ** 3, "3,0 GB"),
    (1500 * 1024 ** 3, "1500,0 GB")])
def test_le_misure_si_scrivono_all_italiana(byte, scritto):
    assert misura(byte) == scritto


def test_il_percorso_lungo_si_accorcia_dal_fondo():
    assert recupera._corto(None) == ""
    assert recupera._corto("breve") == "breve"
    lungo = "x" * 30 + "fine"
    accorciato = recupera._corto(lungo, 10)
    assert accorciato == "…" + lungo[-9:] and len(accorciato) == 10


def test_i_messaggi_hanno_tutti_i_codici_della_fine(tmp_path):
    from officina.sicuro.estrai import FATALI, ROSSI

    assert set(recupera.FERMATE) == set(FATALI)
    assert ROSSI <= set(recupera.SPIEGAZIONI)


def _richiesta(tmp_path, **cambi) -> Path:
    richiesta = {"risultato": str(tmp_path / "esito.json"), "attesa": ATTESA}
    richiesta.update(cambi)
    percorso = tmp_path / "richiesta.json"
    percorso.write_text(json.dumps(richiesta), "utf-8")
    return percorso


def _esito(tmp_path) -> dict:
    return json.loads((tmp_path / "esito.json").read_text("utf-8"))


def test_il_collaudo_senza_finestra_tira_fuori_tutto(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    prima = _fotografia(prova.radice)
    fuori = tmp_path / "fuori"
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove), password=PASSWORD,
                           dove=str(fuori))
    assert recupera.collaudo(richiesta) == 0
    esito = _esito(tmp_path)
    assert esito["fase"] == FINE and esito["verde"]
    assert esito["frozen"] is False
    assert esito["riassunto"]["file"] == 3
    assert "eccezione" not in esito
    assert _uscite(fuori / "foto") == prova.file
    assert not (tmp_path / "esito.json.nuovo").exists()
    assert _fotografia(prova.radice) == prima


def test_il_collaudo_trova_l_archivio_accanto(tmp_path, chiave, monkeypatch):
    prova = _pronta(tmp_path, chiave)
    monkeypatch.setattr(recupera, "accanto", lambda: prova.radice)
    richiesta = _richiesta(tmp_path, password=PASSWORD, dove=str(tmp_path / "fuori"))
    assert recupera.collaudo(richiesta) == 0
    assert _esito(tmp_path)["archivio"] == str(prova.dove)


def test_il_collaudo_con_la_password_sbagliata(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove),
                           password="una password sbagliata",
                           dove=str(tmp_path / "fuori"))
    assert recupera.collaudo(richiesta) == 2
    esito = _esito(tmp_path)
    assert esito["fase"] == FASE_PASSWORD
    assert esito["codice"] == "password_sbagliata"
    assert esito["riassunto"]["stato"] == FERMO


def test_il_collaudo_senza_archivio(tmp_path, monkeypatch):
    (tmp_path / "vuota").mkdir()
    monkeypatch.setattr(recupera, "accanto", lambda: tmp_path / "vuota")
    richiesta = _richiesta(tmp_path, password=PASSWORD, dove=str(tmp_path / "fuori"))
    assert recupera.collaudo(richiesta) == 2
    esito = _esito(tmp_path)
    assert esito["fase"] == CERCA and esito["archivio"] is None
    assert "riassunto" not in esito


def test_il_collaudo_che_si_rompe_lo_dice(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove), password=PASSWORD,
                           dove=str(tmp_path / "fuori"), attesa="x")
    assert recupera.collaudo(richiesta) == 3
    assert _esito(tmp_path)["eccezione"].startswith("ValueError")


@pytest.mark.parametrize("scritto", [None, "non è json", "[]", "{}",
                                     '{"risultato": 3}'])
def test_il_collaudo_con_una_richiesta_strana_esce_con_tre(tmp_path, scritto):
    richiesta = tmp_path / "richiesta.json"
    if scritto is not None:
        richiesta.write_text(scritto, "utf-8")
    assert recupera.collaudo(richiesta) == 3
    assert not (tmp_path / "esito.json").exists()


def test_il_collaudo_con_un_file_rovinato_finisce_ma_non_verde(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[2 * formato.BLOCCO])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[0]), numeri[0], "tutto", random.Random(3))
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove), password=PASSWORD,
                           dove=str(tmp_path / "fuori"))
    assert recupera.collaudo(richiesta) == 1
    esito = _esito(tmp_path)
    assert esito["fase"] == FINE and esito["rossi"] == 1
    assert (tmp_path / "fuori" / RAPPORTO).is_file()


def test_principale_passa_al_collaudo(tmp_path, chiave):
    prova = _pronta(tmp_path, chiave)
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove), password=PASSWORD,
                           dove=str(tmp_path / "fuori"))
    assert recupera.principale(["--collaudo", str(richiesta)]) == 0


def test_principale_apre_la_finestra_sull_archivio_giusto(tmp_path, chiave,
                                                         monkeypatch):
    prova = _pronta(tmp_path, chiave)
    aperte = []

    class Finta:

        def __init__(self, regia):
            aperte.append(regia)

        def gira(self):
            pass

    monkeypatch.setattr(recupera, "Finestra", Finta)
    monkeypatch.setattr(recupera, "accanto", lambda: tmp_path / "foto")
    assert recupera.principale([str(prova.radice)]) == 0
    assert aperte[-1].archivio == prova.dove
    assert recupera.principale(["--qualcosa"]) == 0
    assert aperte[-1].archivio is None and aperte[-1].fase == CERCA
    monkeypatch.setattr(recupera, "accanto", lambda: prova.radice)
    assert recupera.principale([]) == 0
    assert aperte[-1].archivio == prova.dove


def _schermo() -> bool:
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@pytest.mark.skipif(not _schermo(), reason="serve uno schermo")
def test_la_finestrina_tira_fuori_tutto(tmp_path, chiave):
    pytest.importorskip("tkinter")
    prova = _pronta(tmp_path, chiave)
    prima = _fotografia(prova.radice)
    fuori = tmp_path / "fuori"
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove), password=PASSWORD,
                           dove=str(fuori), finestra=True)
    assert recupera.collaudo(richiesta) == 0, _esito(tmp_path)
    esito = _esito(tmp_path)
    assert FINE in esito["fasi_viste"]
    assert esito["scritte"]["frase"].startswith("Fatto!")
    assert esito["tasto_apri"] and not esito["scaduto"]
    assert _uscite(fuori / "foto") == prova.file
    assert _fotografia(prova.radice) == prima


@pytest.mark.skipif(not _schermo(), reason="serve uno schermo")
def test_la_finestrina_con_la_password_sbagliata(tmp_path, chiave):
    pytest.importorskip("tkinter")
    prova = _pronta(tmp_path, chiave)
    richiesta = _richiesta(tmp_path, archivio=str(prova.dove),
                           password="una password sbagliata",
                           dove=str(tmp_path / "fuori"), finestra=True)
    assert recupera.collaudo(richiesta) == 2, _esito(tmp_path)
    esito = _esito(tmp_path)
    assert "non sono state toccate" in esito["scritte"]["errore"]
    assert not esito["tasto_apri"] and not esito["scaduto"]
