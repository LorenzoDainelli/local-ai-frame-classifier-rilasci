from __future__ import annotations

from pathlib import Path

import numpy
import pytest
from PIL import Image

from officina.archivio.database import uno
from officina.importazione import impronta
from officina.importazione.motore import Motore
from officina.miglioria import attesa
from officina.ritocco import coda, copia, elenco, lavoro, maschere, togli_stanza
from officina.descrittori import torcia

LARGA, ALTA = 160, 120
COSA = (60, 40, 100, 80)


def _scena(percorso: Path) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    pixel = numpy.zeros((ALTA, LARGA, 3), dtype=numpy.uint8)
    pixel[:] = (40, 120, 200)
    x0, y0, x1, y1 = COSA
    pixel[y0:y1, x0:x1] = (250, 10, 10)
    Image.fromarray(pixel, "RGB").save(percorso, "PNG")


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _scena(dove / "2019" / "gita.png")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


def _file_id(archivio) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT file_id FROM percorsi WHERE nome = ?",
                   "gita.png")["file_id"]


def _da_togliere() -> dict:
    piena = numpy.zeros((ALTA, LARGA), dtype=bool)
    x0, y0, x1, y1 = COSA
    piena[y0:y1, x0:x1] = True
    return {"genere": elenco.TOGLI, "cosa": elenco.OGGETTO, "larghezza": LARGA,
            "altezza": ALTA, "maschera": maschere.comprimi(piena, (0, 0), LARGA, ALTA)}


class Togliere:

    def __init__(self, guasto: str | None = None):
        self.lavori: list[dict] = []
        self.guasto = guasto

    def __call__(self, lavoro_togli: dict, _ricorda) -> dict:
        self.lavori.append(lavoro_togli)
        if self.guasto:
            return {"guasto": self.guasto}
        return {"fatto": togli_stanza.esegui(lavoro_togli, torcia.Freno(100))}


def _gira(archivio, togliere: Togliere) -> None:
    ritoccatore = lavoro.Ritoccatore(archivio, a_parte=False, toglie=togliere)
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert not ritoccatore.lavoro.guasto, ritoccatore.lavoro.guasto


def _rosso(percorso: Path) -> float:
    with Image.open(percorso) as aperta:
        pixel = numpy.asarray(aperta.convert("RGB"), dtype=float)
    x0, y0, x1, y1 = COSA
    return float(pixel[y0:y1, x0:x1, 0].mean())


def test_una_cosa_tolta_dalla_foto_si_rivede_e_poi_prende_il_posto(importato, cartella):
    scatto = cartella / "2019" / "gita.png"
    prima = impronta.del_file(scatto)
    file_id = _file_id(importato)

    lavoro_id = coda.metti(importato, [{"file_id": file_id, **_da_togliere()}])
    togliere = Togliere()
    _gira(importato, togliere)

    with importato.lettura() as connessione:
        assert coda.per_id(connessione, lavoro_id)["stato"] == coda.DA_RIVEDERE
        [pronto] = coda.pronti(connessione, lavoro_id)
        [ritocco] = coda.nuovi(connessione, lavoro_id)
    assert len(togliere.lavori) == 1 and togliere.lavori[0]["motore"]
    assert impronta.del_file(scatto) == prima
    assert _rosso(Path(pronto["pronta"])) < 120
    toppa = Path(ritocco["risultato"])
    assert toppa.parent == cartella / "2019" / attesa.ORIGINALI / copia.CARTELLA
    assert toppa.is_file() and copia.toppa_pronta(ritocco)
    assert not list((cartella / "2019").glob("*sotto*"))

    coda.approva(importato, lavoro_id)

    assert _rosso(scatto) < 120
    assert impronta.del_file(cartella / "2019" / attesa.ORIGINALI / "gita.png") == prima
    with importato.lettura() as connessione:
        assert elenco.per_id(connessione, ritocco["id"])["stato"] == elenco.FATTO


def test_una_cosa_tolta_si_rifa_senza_chiamare_di_nuovo_il_modello(importato, cartella):
    scatto = cartella / "2019" / "gita.png"
    file_id = _file_id(importato)
    coda.metti(importato, [{"file_id": file_id, **_da_togliere()}])
    togliere = Togliere()
    _gira(importato, togliere)
    with importato.lettura() as connessione:
        [lavoro_id] = [riga["id"] for riga in coda.in_stato(connessione, coda.DA_RIVEDERE)]
    coda.approva(importato, lavoro_id)

    secondo = coda.metti(importato, [{
        "file_id": file_id, "cosa": elenco.OGGETTO, "larghezza": LARGA, "altezza": ALTA,
        "maschera": maschere.comprimi(numpy.ones((10, 10), dtype=bool), (0, 0), LARGA, ALTA),
        "misura": 30}])
    _gira(importato, togliere)
    coda.approva(importato, secondo)

    assert len(togliere.lavori) == 1
    assert _rosso(scatto) < 120


def test_se_il_modello_non_riesce_lo_scatto_resta_e_si_dice_perche(importato, cartella):
    scatto = cartella / "2019" / "gita.png"
    prima = impronta.del_file(scatto)
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])

    _gira(importato, Togliere("togli_motore_sconosciuto"))

    with importato.lettura() as connessione:
        riga = coda.per_id(connessione, lavoro_id)
    assert riga["stato"] == coda.FALLITO
    assert "non è installato" in riga["guasto"]
    assert impronta.del_file(scatto) == prima
    assert not list((cartella / "2019" / attesa.ORIGINALI).glob("**/togli-*"))


def test_un_no_butta_la_cosa_tolta(importato, cartella):
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    _gira(importato, Togliere())
    with importato.lettura() as connessione:
        [ritocco] = coda.nuovi(connessione, lavoro_id)

    coda.rifiuta(importato, lavoro_id)

    assert not Path(ritocco["risultato"]).exists()
    with importato.lettura() as connessione:
        assert elenco.per_id(connessione, ritocco["id"])["risultato"] is None


def test_con_la_memoria_finita_torna_in_coda(importato, monkeypatch):
    monkeypatch.setattr(lavoro, "ASPETTA_IL_SEGUITO", 0.01)
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    ritoccatore = lavoro.Ritoccatore(importato, a_parte=False,
                                     toglie=Togliere("memoria_scheda_finita"))
    ritoccatore._uno(_riga_in_lavoro(importato, lavoro_id))
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, lavoro_id)["stato"] == coda.IN_CODA


def _riga_in_lavoro(archivio, lavoro_id: int):
    with archivio.scrittura() as connessione:
        coda.segna(connessione, lavoro_id, coda.IN_LAVORO)
        return coda.per_id(connessione, lavoro_id)


def _traccia(archivio, lavoro_id: int) -> dict:
    import json

    with archivio.lettura() as connessione:
        [ritocco] = coda.nuovi(connessione, lavoro_id)
    return json.loads(ritocco["traccia"])


def test_se_la_cosa_si_vede_ancora_riprova_piu_largo(importato):
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    togliere = Togliere()
    piena = numpy.zeros((ALTA, LARGA), dtype=bool)
    x0, y0, x1, y1 = COSA
    piena[y0:y1, x0:x1] = True
    vista = maschere.comprimi(piena, (0, 0), LARGA, ALTA)
    ritoccatore = lavoro.Ritoccatore(importato, a_parte=False, toglie=togliere,
                                     cerca=lambda *_: (vista, 0.95))
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)

    margini = [lavoro_togli["margine"] for lavoro_togli in togliere.lavori]
    assert margini == list(lavoro.togliere.MARGINI)
    traccia = _traccia(importato, lavoro_id)
    assert traccia["resta"] and traccia["rifatto"] == len(margini) - 1


def test_se_la_cosa_non_si_vede_piu_basta_una_volta(importato):
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    togliere = Togliere()
    ritoccatore = lavoro.Ritoccatore(importato, a_parte=False, toglie=togliere,
                                     cerca=lambda *_: None)
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)

    assert len(togliere.lavori) == 1
    traccia = _traccia(importato, lavoro_id)
    assert traccia == {"rifatto": 0, "resta": False, "bordo": False, "dove": []}


class _Seguitore:

    def __init__(self, libera: bool):
        self.libera = libera
        self.lasciata = 0

    def prendi_la_scheda(self, _lavoro) -> bool:
        return self.libera

    def cerca(self, _lavoro):
        return lambda *_: None

    def lascia(self, _lavoro) -> None:
        self.lasciata += 1

    def ferma(self) -> None:
        pass


def test_con_la_scheda_occupata_aspetta_il_suo_turno(importato, monkeypatch):
    monkeypatch.setattr(lavoro, "ASPETTA_IL_SEGUITO", 0.01)
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    togliere, seguitore = Togliere(), _Seguitore(libera=False)
    ritoccatore = lavoro.Ritoccatore(importato, seguitore, a_parte=False, toglie=togliere)
    ritoccatore._uno(_riga_in_lavoro(importato, lavoro_id))
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, lavoro_id)["stato"] == coda.IN_CODA
    assert not togliere.lavori and seguitore.lasciata == 1


def test_con_la_scheda_libera_toglie_e_poi_la_lascia(importato):
    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    togliere, seguitore = Togliere(), _Seguitore(libera=True)
    ritoccatore = lavoro.Ritoccatore(importato, seguitore, a_parte=False, toglie=togliere)
    ritoccatore._uno(_riga_in_lavoro(importato, lavoro_id))
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert len(togliere.lavori) == 1 and seguitore.lasciata == 1


def test_nella_revisione_si_legge_il_ricontrollo(importato):
    import json

    from officina.ritocco import racconto

    lavoro_id = coda.metti(importato, [{"file_id": _file_id(importato), **_da_togliere()}])
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET traccia = ? WHERE lavoro_id = ?", (json.dumps(
            {"rifatto": 2, "resta": True, "bordo": False, "dove": [0, 0, 20, 20]}), lavoro_id))
        [parte] = racconto.del_lavoro(connessione, lavoro_id, _file_id(importato))
    assert "rifatto 2 volte" in parte["dettaglio"]
    assert parte["avviso"].endswith("in alto a sinistra")
