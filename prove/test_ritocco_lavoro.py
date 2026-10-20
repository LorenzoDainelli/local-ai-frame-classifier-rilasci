from __future__ import annotations

import time
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio.database import leggi_stato, tutti, uno
from officina.importazione import impronta
from officina.importazione.motore import Motore
from officina.miglioria import attesa
from officina.modello import file_media
from officina.ritocco import coda, copia, elenco, lavoro, maschere, pellicola, pixela, seguiti
from officina.ritocco.copia import RitoccoFermato
from officina.web import coda_ritocco, in_disparte, lavori
from officina.web import ritocco as ritocco_web
from prove import sceglitore_finto
from prove.test_ritocco_coda import ALTA, LARGA, QUANTI, _quadri, _quadrato, _sotto, _video

FOTO_LARGA, FOTO_ALTA = 64, 48
FISSO = (20, 70, 44, 90)


def _aspetta(condizione, entro: float = 20.0) -> bool:
    scadenza = time.monotonic() + entro
    while time.monotonic() < scadenza:
        if condizione():
            return True
        time.sleep(0.02)
    return condizione()


@pytest.fixture(autouse=True)
def turno_pulito(monkeypatch):
    monkeypatch.setattr(lavoro, "ASPETTA_IL_SEGUITO", 0.05)
    yield
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)
    coda_ritocco.ferma(5.0)
    coda_ritocco._ritoccatore = None


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _video(dove / "2018" / "giro.mp4")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


@pytest.fixture
def sam3(tmp_path) -> Path:
    dove = tmp_path / "sam3"
    dove.mkdir()
    return dove


@pytest.fixture
def strumento():
    fatti: list[ritocco_web.AlClic] = []

    def fai(come: str = "Finto") -> ritocco_web.AlClic:
        nuovo = ritocco_web.AlClic("prove.sceglitore_finto:" + come)
        fatti.append(nuovo)
        return nuovo

    yield fai
    for fatto in fatti:
        fatto.chiudi()


def _file_di(archivio, nome: str) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT file_id FROM percorsi WHERE nome = ?", nome)["file_id"]


def _fisso() -> bytes:
    piena = numpy.zeros((ALTA, LARGA), dtype=bool)
    x0, y0, x1, y1 = FISSO
    piena[y0:y1, x0:x1] = True
    return maschere.comprimi(piena, (0, 0), LARGA, ALTA)


def _seguito(archivio, file_id: int, quali=range(10), seguito: bool = True,
             maschera=None) -> int:
    with archivio.scrittura() as connessione:
        media = file_media.per_id(connessione, file_id)
        seguito_id = seguiti.nuovo(connessione, file_id, cosa=elenco.OGGETTO,
                                   impronta=media["impronta"], larghezza=LARGA, altezza=ALTA,
                                   quanti=QUANTI,
                                   istanti_ms=[indice * 100 for indice in range(QUANTI)])
        primo = min(quali)
        seguiti.metti_scelta(connessione, seguito_id, primo,
                             maschera(primo) if maschera else _quadrato(primo))
        if seguito:
            arrivati = [(indice, primo,
                         (maschera(indice) if maschera else _quadrato(indice))
                         if indice in quali else b"", 0.9) for indice in range(QUANTI)]
            seguiti.scrivi(connessione, seguito_id, arrivati, {primo: 1})
            seguiti.segna(connessione, seguito_id, seguiti.SEGUITO)
    return seguito_id


def _ritoccatore(archivio, **altro) -> lavoro.Ritoccatore:
    altro.setdefault("a_parte", False)
    return lavoro.Ritoccatore(archivio, **altro)


def _gira(ritoccatore: lavoro.Ritoccatore) -> None:
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert not ritoccatore.lavoro.guasto, ritoccatore.lavoro.guasto


def _lavoro(archivio, lavoro_id: int):
    with archivio.lettura() as connessione:
        return coda.per_id(connessione, lavoro_id)


def _pronti(archivio, lavoro_id: int):
    with archivio.lettura() as connessione:
        return coda.pronti(connessione, lavoro_id)


def _pixelato(percorso: Path, numeri=range(10)) -> bool:
    quadri = _quadri(percorso)
    return len(quadri) == QUANTI and all(_sotto(quadri[n], n).std() < 15 for n in numeri)


def _intatto(percorso: Path, numeri=range(10)) -> bool:
    quadri = _quadri(percorso)
    return all(_sotto(quadri[n], n).std() > 60 for n in numeri)


def test_un_video_in_coda_si_pixela_si_rivede_e_dopo_il_si_si_scambia(importato, cartella):
    scatto = cartella / "2018" / "giro.mp4"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "giro.mp4")
    seguito_id = _seguito(importato, file_id)

    lavoro_id = coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id,
                                        "cosa": elenco.OGGETTO}])

    riga = _lavoro(importato, lavoro_id)
    assert riga["stato"] == coda.IN_CODA and riga["stima"] >= 1
    with importato.lettura() as connessione:
        [ritocco] = coda.nuovi(connessione, lavoro_id)
    assert ritocco["seguito_id"] == seguito_id and ritocco["quadretto"]
    _gira(_ritoccatore(importato))

    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    [pronto] = _pronti(importato, lavoro_id)
    pronta = Path(pronto["pronta"])
    assert pronta.is_file() and pronto["fotogrammi"] == QUANTI
    assert pronto["impronta_base"] == prima
    assert attesa.e_dentro(pronta) and pronta.name.startswith(copia.PREFISSO)
    assert not pronta.with_name(pronta.name + attesa.PARZIALE).exists()
    assert impronta.del_file(scatto) == prima
    assert _pixelato(pronta)

    coda.approva(importato, lavoro_id)

    assert _lavoro(importato, lavoro_id)["stato"] == coda.FATTO
    assert not pronta.exists()
    assert _pixelato(scatto) and impronta.del_file(scatto) != prima
    spostato = cartella / "2018" / attesa.ORIGINALI / "giro.mp4"
    assert impronta.del_file(spostato) == prima
    with importato.lettura() as connessione:
        assert elenco.per_id(connessione, ritocco["id"])["stato"] == elenco.FATTO
        assert file_media.da_mostrare_sotto(connessione, file_id) == (spostato, prima)

    assert coda.togli(importato, ritocco["id"]) is None
    assert impronta.del_file(scatto) == prima
    assert not spostato.exists()


def test_il_video_si_pixela_anche_nel_processo_a_parte(importato, cartella, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    ritoccatore = _ritoccatore(importato, a_parte=True)
    _gira(ritoccatore)
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert _pixelato(Path(_pronti(importato, lavoro_id)[0]["pronta"]))
    assert not in_disparte.sta_girando(lavoro.A)


def test_un_no_butta_la_copia_e_si_puo_rimettere_in_coda(importato, cartella):
    scatto = cartella / "2018" / "giro.mp4"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    _gira(_ritoccatore(importato))
    pronta = Path(_pronti(importato, lavoro_id)[0]["pronta"])

    coda.rifiuta(importato, lavoro_id)

    assert not pronta.exists() and impronta.del_file(scatto) == prima
    assert _lavoro(importato, lavoro_id)["stato"] == coda.RIFIUTATO
    with importato.lettura() as connessione:
        assert len(elenco.di_file(connessione, file_id, elenco.RIFIUTATO)) == 1
        assert not elenco.di_file(connessione, file_id)
    with pytest.raises(RitoccoFermato):
        coda.approva(importato, lavoro_id)

    coda.rimetti(importato, lavoro_id)

    riga = _lavoro(importato, lavoro_id)
    assert riga["stato"] == coda.IN_CODA and riga["rifatto"] == 1
    _gira(_ritoccatore(importato))
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE


def test_un_ritocco_aggiunto_mentre_lavora_fa_ricominciare(importato, monkeypatch):
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    vero = pellicola.pixela_il_video
    giri = []

    def con_un_cambio(*argomenti, **altro):
        giri.append(1)
        if len(giri) == 1:
            with importato.scrittura() as connessione:
                coda.cambiato(connessione, lavoro_id)
        return vero(*argomenti, **altro)

    monkeypatch.setattr(pellicola, "pixela_il_video", con_un_cambio)
    ritoccatore = _ritoccatore(importato)
    _gira(ritoccatore)
    assert len(giri) == 2
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert len(_pronti(importato, lavoro_id)) == 1
    assert any("li rifaccio" in riga for riga in ritoccatore.lavoro.righe)
    pronta = Path(_pronti(importato, lavoro_id)[0]["pronta"])
    assert list(pronta.parent.glob(f"{copia.PREFISSO}-*")) == [pronta]


def test_fermato_a_meta_torna_in_coda_senza_lasciare_pezzi(importato, cartella):
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    ritoccatore = _ritoccatore(importato)
    vero = ritoccatore._al_passo

    def ferma_presto(fatti: int, totale: int) -> None:
        vero(fatti, totale)
        if fatti >= 3:
            ritoccatore.ferma()

    ritoccatore._al_passo = ferma_presto
    _gira(ritoccatore)
    assert _lavoro(importato, lavoro_id)["stato"] == coda.IN_CODA
    assert not _pronti(importato, lavoro_id)
    assert not list(cartella.rglob(f"{copia.PREFISSO}-*"))


def test_se_il_video_cambia_il_lavoro_non_riesce_e_niente_si_tocca(importato, cartella):
    scatto = cartella / "2018" / "giro.mp4"
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    _video(scatto, quanti=12)
    cambiato = impronta.del_file(scatto)
    _gira(_ritoccatore(importato))
    riga = _lavoro(importato, lavoro_id)
    assert riga["stato"] == coda.FALLITO and riga["guasto"] == copia.CAMBIATO
    assert impronta.del_file(scatto) == cambiato
    with importato.lettura() as connessione:
        assert len(elenco.di_file(connessione, file_id, elenco.FALLITO)) == 1
        assert not elenco.di_file(connessione, file_id)


def test_un_seguito_vecchio_non_entra_in_coda(importato):
    file_id = _file_di(importato, "giro.mp4")
    seguito_id = _seguito(importato, file_id)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE seguiti SET impronta = 'altro' WHERE id = ?", (seguito_id,))
    with pytest.raises(RitoccoFermato) as vecchio:
        coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id}])
    assert vecchio.value.messaggio == coda.SEGUITO_VECCHIO
    with pytest.raises(RitoccoFermato) as solo:
        coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id,
                                "genere": elenco.TOGLI}])
    assert solo.value.messaggio in (coda.SOLO_PIXELA, coda.SEGUITO_VECCHIO)
    with importato.lettura() as connessione:
        assert not tutti(connessione, "SELECT id FROM ritocchi_lavori")


def test_se_la_copia_sparisce_il_si_non_tocca_niente(importato, cartella):
    scatto = cartella / "2018" / "giro.mp4"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])
    _gira(_ritoccatore(importato))
    Path(_pronti(importato, lavoro_id)[0]["pronta"]).unlink()
    with pytest.raises(RitoccoFermato):
        coda.approva(importato, lavoro_id)
    riga = _lavoro(importato, lavoro_id)
    assert riga["stato"] == coda.DA_RIVEDERE and riga["guasto"]
    assert impronta.del_file(scatto) == prima


def test_all_avvio_la_coda_si_ripara_e_riparte(importato, cartella):
    scatto = cartella / "2018" / "giro.mp4"
    file_id = _file_di(importato, "giro.mp4")
    seguito_id = _seguito(importato, file_id)
    primo = coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id}])
    _gira(_ritoccatore(importato))
    with importato.scrittura() as connessione:
        coda.segna(connessione, primo, coda.IN_SCAMBIO)
        connessione.execute("UPDATE seguiti SET stato = ? WHERE id = ?",
                            (seguiti.IN_LAVORO, seguito_id))
        connessione.execute("INSERT INTO stato (chiave, valore, aggiornato_il) "
                            "VALUES (?, 'true', '')", (coda_ritocco.ACCESA,))

    esito = coda_ritocco.ripara(importato)

    assert esito["finiti"] == 1 and esito["seguiti"] == 1 and not esito["ripartita"]
    assert _lavoro(importato, primo)["stato"] == coda.FATTO and _pixelato(scatto)
    with importato.lettura() as connessione:
        assert seguiti.per_id(connessione, seguito_id)["stato"] == seguiti.FERMATO

    secondo = coda.metti(importato, [{"file_id": file_id, "seguito_id": _seguito(
        importato, file_id, quali=range(14, QUANTI))}])
    with importato.scrittura() as connessione:
        coda.segna(connessione, secondo, coda.IN_LAVORO)
        coda.scrivi_i_pronti(connessione, secondo, [{"file_id": file_id, "impronta_base": "x"}])

    esito = coda_ritocco.ripara(importato)

    assert esito["rimessi"] == 1 and esito["ripartita"]
    ritoccatore = coda_ritocco.il_ritoccatore(importato)
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert _lavoro(importato, secondo)["stato"] == coda.DA_RIVEDERE


def _live(archivio, cartella: Path) -> tuple[int, int]:
    Image.new("RGB", (FOTO_LARGA, FOTO_ALTA), (30, 60, 90)).save(
        cartella / "2018" / "giro.jpg", "JPEG", quality=95)
    righe = numpy.indices((FOTO_ALTA, FOTO_LARGA))[1] % 2 * 240
    scacchi = Image.fromarray(numpy.stack([righe.astype(numpy.uint8)] * 3, axis=-1), "RGB")
    scacchi.save(cartella / "2018" / "giro.jpg", "JPEG", quality=98, subsampling=0)
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    foto_id, video_id = _file_di(archivio, "giro.jpg"), _file_di(archivio, "giro.mp4")
    with archivio.scrittura() as connessione:
        scatto_id = file_media.per_id(connessione, foto_id)["scatto_id"]
        file_media.collega_a_scatto(connessione, video_id, scatto_id, "movimento")
    return foto_id, video_id


def _nella_foto(x0: int, y0: int, x1: int, y1: int) -> dict:
    piena = numpy.zeros((FOTO_ALTA, FOTO_LARGA), dtype=bool)
    piena[y0:y1, x0:x1] = True
    return {"cosa": elenco.OGGETTO, "larghezza": FOTO_LARGA, "altezza": FOTO_ALTA,
            "maschera": maschere.comprimi(piena, (0, 0), FOTO_LARGA, FOTO_ALTA),
            "misura": 4 * pixela.QUADRATI_SUL_VOLTO}


def _varia(percorso: Path, zona) -> float:
    x0, y0, x1, y1 = zona
    with Image.open(percorso) as immagine:
        pixel = numpy.asarray(immagine.convert("L"), dtype=float)
    return float(pixel[y0:y1, x0:x1].std())


def test_una_foto_live_si_ritocca_insieme_al_suo_video(importato, cartella):
    foto_id, video_id = _live(importato, cartella)
    foto, film = cartella / "2018" / "giro.jpg", cartella / "2018" / "giro.mp4"
    primo = (8, 8, 24, 24)
    secondo = (40, 20, 56, 36)
    fermo = _seguito(importato, video_id, quali=range(QUANTI), maschera=lambda _: _fisso())

    lavoro_id = coda.metti(importato, [
        {"file_id": foto_id, **_nella_foto(*primo),
         "gemello": {"file_id": video_id, "seguito_id": _seguito(importato, video_id)}},
        {"file_id": foto_id, **_nella_foto(*secondo),
         "gemello": {"file_id": video_id, "seguito_id": fermo}}])
    _gira(_ritoccatore(importato))

    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert {riga["file_id"] for riga in _pronti(importato, lavoro_id)} == {foto_id, video_id}
    coda.approva(importato, lavoro_id)
    assert _varia(foto, primo) < 12 and _varia(foto, secondo) < 12
    assert _pixelato(film)
    with importato.lettura() as connessione:
        ritocchi = elenco.di_file(connessione, foto_id)
        gemelli = {riga["id"]: riga["gemello_id"] for riga in ritocchi}
        assert all(elenco.per_id(connessione, gemello)["gemello_id"] == ritocco
                   for ritocco, gemello in gemelli.items())

    altro = coda.togli(importato, ritocchi[0]["id"])

    assert altro is not None and altro != lavoro_id
    with importato.lettura() as connessione:
        assert elenco.per_id(connessione, ritocchi[0]["gemello_id"])["stato"] == elenco.TOLTO
    _gira(_ritoccatore(importato))
    assert _lavoro(importato, altro)["stato"] == coda.FATTO
    assert _varia(foto, primo) > 80 and _varia(foto, secondo) < 12
    assert _intatto(film)
    quadri = _quadri(film)
    x0, y0, x1, y1 = FISSO
    assert quadri[5][y0 + 4:y1 - 4, x0 + 4:x1 - 4, 0].std() < 15

    coda.togli(importato, ritocchi[1]["id"])
    with importato.lettura() as connessione:
        assert not elenco.di_file(connessione, foto_id)
        assert not elenco.di_file(connessione, video_id)
        assert copia.ritoccata(connessione, foto_id) is None
        assert copia.ritoccata(connessione, video_id) is None


def test_un_ritocco_in_coda_aspetta_e_si_aggiunge_allo_stesso_lavoro(importato):
    file_id = _file_di(importato, "giro.mp4")
    primo = coda.metti(importato, [{"file_id": file_id, "seguito_id": _seguito(importato,
                                                                               file_id)}])
    secondo = coda.metti(importato, [{"file_id": file_id, "seguito_id": _seguito(
        importato, file_id, quali=range(14, QUANTI))}])
    assert primo == secondo
    assert _lavoro(importato, primo)["versione"] == 2
    _gira(_ritoccatore(importato))
    pronta = Path(_pronti(importato, primo)[0]["pronta"])
    assert _pixelato(pronta, range(10)) and _pixelato(pronta, range(14, QUANTI))

    terzo = coda.metti(importato, [{"file_id": file_id, "seguito_id": _seguito(
        importato, file_id, quali=range(11, 13))}])
    assert terzo == primo and not pronta.exists()
    assert _lavoro(importato, primo)["stato"] == coda.IN_CODA


def test_la_coda_segue_quello_che_manca_e_poi_lascia_la_scheda(importato, strumento, sam3):
    file_id = _file_di(importato, "giro.mp4")
    seguito_id = _seguito(importato, file_id, seguito=False)
    al_clic = strumento()
    lavoro_id = coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id}])
    _gira(_ritoccatore(importato, seguitore=coda_ritocco.Seguitore(importato, al_clic, sam3)))

    with importato.lettura() as connessione:
        assert seguiti.per_id(connessione, seguito_id)["stato"] == seguiti.SEGUITO
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert sceglitore_finto.seguiti(sam3)[0]["dove"] == "scheda"
    assert lavori.turno.chi is None and not al_clic.acceso


def test_senza_sam3_un_video_da_seguire_non_riesce(importato):
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id,
                                                               seguito=False)}])
    _gira(_ritoccatore(importato))
    riga = _lavoro(importato, lavoro_id)
    assert riga["stato"] == coda.FALLITO and riga["guasto"] == lavoro.SENZA_SEGUIRE


def test_se_la_scheda_e_occupata_la_coda_aspetta_il_suo_turno(importato, strumento, sam3):
    file_id = _file_di(importato, "giro.mp4")
    al_clic = strumento()
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id,
                                                               seguito=False)}])
    miglioramento = lavori.Lavoro("miglioramento")
    assert lavori.turno.prendi_se_libera(miglioramento)
    ritoccatore = _ritoccatore(importato,
                               seguitore=coda_ritocco.Seguitore(importato, al_clic, sam3))
    assert ritoccatore.parti()
    assert _aspetta(lambda: any("la sta usando il miglioramento" in riga
                                for riga in ritoccatore.lavoro.righe))
    assert ritoccatore.lavoro.numeri.get("in_attesa_della_scheda")
    assert not sceglitore_finto.seguiti(sam3)

    lavori.turno.lascia(miglioramento)

    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert not ritoccatore.lavoro.numeri.get("in_attesa_della_scheda")


def test_un_clic_nello_strumento_ferma_il_seguito_della_coda(importato, strumento, sam3,
                                                              cartella):
    file_id = _file_di(importato, "giro.mp4")
    seguito_id = _seguito(importato, file_id, seguito=False)
    al_clic = strumento("Lento")
    lavoro_id = coda.metti(importato, [{"file_id": file_id, "seguito_id": seguito_id}])
    ritoccatore = _ritoccatore(importato,
                               seguitore=coda_ritocco.Seguitore(importato, al_clic, sam3))
    assert ritoccatore.parti()
    assert _aspetta(lambda: _quanti_fatti(importato, seguito_id) >= 3)
    foto = cartella / "una.jpg"
    Image.new("RGB", (FOTO_LARGA, FOTO_ALTA), (10, 20, 30)).save(foto)

    guardato = al_clic.guarda(sam3, "foto", foto)

    assert guardato["dove"] == "scheda" and lavori.turno.chi is al_clic.lavoro

    def fermato() -> bool:
        with importato.lettura() as connessione:
            return seguiti.per_id(connessione, seguito_id)["stato"] == seguiti.FERMATO

    assert _aspetta(fermato)
    assert _quanti_fatti(importato, seguito_id) < QUANTI
    assert _aspetta(lambda: any("lo strumento Ritocca" in riga
                                for riga in ritoccatore.lavoro.righe))

    al_clic.chiudi()

    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    with importato.lettura() as connessione:
        assert seguiti.per_id(connessione, seguito_id)["stato"] == seguiti.SEGUITO


def _quanti_fatti(archivio, seguito_id: int) -> int:
    with archivio.lettura() as connessione:
        return seguiti.quanti_fatti(connessione, seguito_id)


def test_dal_programma_la_coda_si_guarda_si_approva_e_si_ferma(importato, monkeypatch):
    from officina.archivio import accesso
    from officina.web.server import app
    from officina.web.strade import generale

    monkeypatch.setattr(accesso, "aperto", lambda: importato)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id,
                                        "seguito_id": _seguito(importato, file_id)}])

    risposta = cliente.post("/api/ritocco/coda/avvia")

    assert risposta.status_code == 200
    ritoccatore = coda_ritocco.il_ritoccatore(importato)
    assert ritoccatore.lavoro in generale._tutti_i_lavori()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    with importato.lettura() as connessione:
        assert leggi_stato(connessione, coda_ritocco.ACCESA) is True
    dati = cliente.get("/api/ritocco/coda").json()
    [visto] = dati["lavori"]
    assert visto["id"] == lavoro_id and visto["stato"] == coda.DA_RIVEDERE
    assert visto["nuovi"] == 1 and visto["file"][0]["nome"] == "giro.mp4"
    assert dati["conteggi"][coda.DA_RIVEDERE] == 1

    assert cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva").status_code == 200
    assert _lavoro(importato, lavoro_id)["stato"] == coda.FATTO
    assert cliente.get("/api/ritocco/coda").json()["lavori"] == []
    rifatto = cliente.post(f"/api/ritocco/coda/{lavoro_id}/rifiuta")
    assert rifatto.status_code >= 400 and coda.NON_DA_RIVEDERE in rifatto.text

    with importato.lettura() as connessione:
        [ritocco] = elenco.di_file(connessione, file_id)
    tolto = cliente.post(f"/api/ritocco/togli/{ritocco['id']}").json()
    assert tolto["fatto"] and not tolto["in_coda"] and tolto["ritocchi"] == []

    assert cliente.post("/api/ritocco/coda/ferma").status_code == 200
    with importato.lettura() as connessione:
        assert leggi_stato(connessione, coda_ritocco.ACCESA) is False


def test_chiudendo_il_programma_la_coda_si_ferma(importato, monkeypatch):
    from officina.web.strade import generale

    file_id = _file_di(importato, "giro.mp4")
    coda.metti(importato, [{"file_id": file_id, "seguito_id": _seguito(importato, file_id)}])
    ritoccatore = coda_ritocco.il_ritoccatore(importato)
    fermato = []
    monkeypatch.setattr(ritoccatore, "ferma", lambda aspetta=0.0: fermato.append(aspetta))
    generale.ferma_tutto(0.1)
    assert fermato
