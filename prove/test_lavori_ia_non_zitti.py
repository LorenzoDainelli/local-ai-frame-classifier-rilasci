from __future__ import annotations

import pytest

from officina import registro
from officina.immagini import fotogrammi as estrattore
from officina.modello import file_media, segnalazioni
from officina.modello import impronte as magazzino_impronte
from officina.parole.lettore import Sguardo, leggi_la_risposta
from officina.volti.rilevatore import Faccia
from prove.test_corpi import RilevatoreFinto
from prove.test_parole import _LettoreFinto, _scatto_con_foto


class _UnaFaccia:

    versione = "1-finto"

    def __init__(self, rotto=False):
        self.rotto = rotto

    def guarda(self, immagine):
        if self.rotto:
            raise RuntimeError("si è rotto")
        return [Faccia(riquadro=(0.1, 0.1, 0.2, 0.3), sicurezza=0.9, nitidezza=1.0)]

    def spegni(self):
        pass


def _ascolta(monkeypatch) -> list[tuple[str, dict]]:
    sentite = []
    monkeypatch.setattr(registro, "avviso",
                        lambda codice, **dati: sentite.append((codice, dati)))
    return sentite


def _un_video(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT id FROM scatti WHERE genere = 'video' AND fuori_archivio = 0 "
            "ORDER BY id LIMIT 1").fetchone()[0]


def _dagli_le_impronte(archivio, scatto_id: int, quanti: int = 3) -> None:
    with archivio.scrittura() as connessione:
        for numero in range(quanti):
            magazzino_impronte.scrivi(
                connessione, scatto_id, None, "finto", "1", "intera", "intera",
                None, [0.1, 0.2], fotogramma=numero, istante_ms=numero * 1000)


def _guardato(archivio, tabella: str, scatto_id: int) -> bool:
    with archivio.lettura() as connessione:
        return connessione.execute(
            f"SELECT 1 FROM {tabella} WHERE scatto_id = ?", (scatto_id,)).fetchone() is not None


def _avvisi(archivio, tipo: str, scatto_id: int) -> list[str]:
    with archivio.lettura() as connessione:
        return [r[0] for r in connessione.execute(
            "SELECT dettaglio FROM segnalazioni WHERE tipo = ? AND scatto_id = ? "
            "AND risolta = 0", (tipo, scatto_id))]


def _passata(quale: str, archivio, rilevatore):
    if quale == "volti":
        from officina.volti.motore import Passata
    else:
        from officina.corpi.motore import Passata
    return Passata(archivio, rilevatore=rilevatore, intensita=100)


QUALI = (("volti", _UnaFaccia, "volti_guardati", segnalazioni.VOLTI_NON_LETTI),
         ("corpi", RilevatoreFinto, "corpi_guardati", segnalazioni.CORPI_NON_LETTI))


@pytest.mark.parametrize("quale, finto, tabella, avviso", QUALI)
def test_un_video_senza_impronte_aspetta_e_non_risulta_fatto(
        archivio_pieno, quale, finto, tabella, avviso):
    video = _un_video(archivio_pieno)
    fatto = _passata(quale, archivio_pieno, finto()).esegui()
    assert fatto.motivi.get("aspetta_le_impronte", 0) >= 1
    assert not _guardato(archivio_pieno, tabella, video)
    assert _avvisi(archivio_pieno, avviso, video) == []
    assert _avvisi(archivio_pieno, segnalazioni.NON_SI_APRE, video) == []


@pytest.mark.parametrize("quale, finto, tabella, avviso", QUALI)
def test_un_video_che_non_da_fotogrammi_non_risulta_fatto(
        archivio_pieno, monkeypatch, quale, finto, tabella, avviso):
    video = _un_video(archivio_pieno)
    _dagli_le_impronte(archivio_pieno, video)
    monkeypatch.setattr(estrattore, "uno", lambda *a, **k: None)
    fatto = _passata(quale, archivio_pieno, finto()).esegui()
    assert fatto.motivi.get("video_senza_immagini") == 1
    assert not _guardato(archivio_pieno, tabella, video)
    assert _avvisi(archivio_pieno, avviso, video) == [
        "Il video non ha dato nessun fotogramma."]


@pytest.mark.parametrize("quale, finto, tabella, avviso", QUALI)
def test_un_video_guarda_tutti_i_fotogrammi_delle_impronte(
        archivio_pieno, monkeypatch, quale, finto, tabella, avviso):
    from PIL import Image

    video = _un_video(archivio_pieno)
    _dagli_le_impronte(archivio_pieno, video, quanti=3)
    chiesti = []

    def uno(percorso, numero, istante=None, lato=None):
        chiesti.append(numero)
        return None if numero == 1 else Image.new("RGB", (64, 48), (90, 90, 90))

    monkeypatch.setattr(estrattore, "uno", uno)
    sentite = _ascolta(monkeypatch)
    _passata(quale, archivio_pieno, finto()).esegui()
    assert chiesti == [0, 1, 2]
    assert _guardato(archivio_pieno, tabella, video)
    persi = [dati for codice, dati in sentite if codice == f"{quale}.fotogrammi_persi"]
    assert persi == [{"scatto": video, "persi": 1, "su": 3}]


def test_un_guasto_imprevisto_dei_volti_lascia_una_riga(archivio_pieno, monkeypatch):
    sentite = _ascolta(monkeypatch)
    _passata("volti", archivio_pieno, _UnaFaccia(rotto=True)).esegui()
    rotti = [dati for codice, dati in sentite if codice == "volti.scatto_rotto"]
    assert rotti and "RuntimeError" in str(rotti[0]["guasto"])
    assert isinstance(rotti[0]["scatto"], int)


def test_un_guasto_imprevisto_dei_corpi_lascia_una_riga(archivio_pieno, monkeypatch):
    sentite = _ascolta(monkeypatch)
    _passata("corpi", archivio_pieno, RilevatoreFinto(rotto_su={1})).esegui()
    rotti = [dati for codice, dati in sentite if codice == "corpi.scatto_rotto"]
    assert rotti and "RuntimeError" in str(rotti[0]["guasto"])


def test_la_risposta_fuori_schema_si_riconosce():
    assert leggi_la_risposta("DESCRIZIONE: un cane\nSCRITTE:\nnessuna").capita
    assert leggi_la_risposta("SCRITTE: Bar Sport").capita
    assert not leggi_la_risposta("").capita
    assert not leggi_la_risposta("Mi dispiace, non posso aiutarti.").capita
    assert not leggi_la_risposta("<think>DESCRIZIONE: x</think>").capita


class _LettoreStrano(_LettoreFinto):

    def __init__(self, capite):
        super().__init__()
        self.capite = list(capite)

    def guarda(self, immagine):
        indice = self.viste
        self.viste += 1
        return Sguardo(descrizione="una cosa" if self.capite[indice] else "",
                       capita=self.capite[indice])


def test_una_risposta_fuori_schema_non_segna_lo_scatto_come_letto(
        archivio, tmp_path, monkeypatch):
    from officina.parole.motore import Passata

    sentite = _ascolta(monkeypatch)
    strano = _scatto_con_foto(archivio, tmp_path / "foto", "strano.jpg")
    buono = _scatto_con_foto(archivio, tmp_path / "foto", "buono.jpg")
    passata = Passata(archivio, lettore=_LettoreStrano([False, True]), intensita=100)
    fatto = passata.esegui()
    assert fatto.letti == 1 and fatto.saltati == 1
    assert fatto.motivi_saltati == {"risposta_strana": 1}
    assert not _guardato(archivio, "scritte_lette", strano)
    assert _guardato(archivio, "scritte_lette", buono)
    strane = [dati for codice, dati in sentite if codice == "parole.risposta_strana"]
    assert strane == [{"scatto": strano, "strane": 1, "su": 1}]
    assert passata.quanti_mancano() == 1


def test_una_lettura_che_si_rompe_lascia_una_riga(archivio, tmp_path, monkeypatch):
    from officina.parole.motore import Passata

    sentite = _ascolta(monkeypatch)
    rotto = _scatto_con_foto(archivio, tmp_path / "foto", "rotto.jpg")
    _scatto_con_foto(archivio, tmp_path / "foto", "buono.jpg")
    Passata(archivio, lettore=_LettoreFinto([[], ["Bar"]], rompiti_su={0}),
            intensita=100).esegui()
    fallite = [dati for codice, dati in sentite if codice == "parole.lettura_fallita"]
    assert fallite and fallite[0]["scatto"] == rotto
    assert "RuntimeError" in str(fallite[0]["guasto"])


def test_uno_scatto_che_non_si_prepara_lascia_una_riga(archivio, tmp_path, monkeypatch):
    from officina.parole import motore

    sentite = _ascolta(monkeypatch)
    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")

    def rotta(*a, **k):
        raise ValueError("pixel storti")

    monkeypatch.setattr(motore.lettura, "copia_di_lavoro", rotta)
    fatto = motore.Passata(archivio, lettore=_LettoreFinto(), intensita=100).esegui()
    assert fatto.motivi_saltati == {"errore_imprevisto": 1}
    rotti = [dati for codice, dati in sentite if codice == "parole.scatto_rotto"]
    assert rotti and rotti[0]["scatto"] == scatto
    assert _avvisi(archivio, segnalazioni.NON_SI_APRE, scatto) == []


def _riga(ruolo: str, genere: str, numero: int) -> dict:
    return {"id": numero, "ruolo": ruolo, "genere": genere}


def test_i_quattro_lavori_scelgono_lo_stesso_file():
    from officina.impronte import motore as impronte

    principale = _riga("principale", "video", 1)
    foto = _riga("compagno", "immagine", 2)
    filmato = _riga("compagno", "video", 3)
    assert file_media.quello_da_guardare([foto, principale]) is principale
    assert file_media.quello_da_guardare([filmato, foto]) is foto
    assert file_media.quello_da_guardare([filmato]) is filmato
    assert file_media.quello_da_guardare([]) is None
    assert impronte._il_file_da_guardare is file_media.quello_da_guardare


@pytest.mark.parametrize("modulo", ["officina.volti.motore", "officina.corpi.motore",
                                    "officina.parole.motore", "officina.impronte.perche"])
def test_nessun_lavoro_sceglie_il_file_a_modo_suo(modulo):
    import importlib
    import inspect

    testo = inspect.getsource(importlib.import_module(modulo))
    assert 'f["ruolo"] == "principale"' not in testo
    assert 'r["ruolo"] == "principale"' not in testo
    assert "quello_da_guardare" in testo or "_il_file_da_guardare" in testo


def _segna_da_riguardare(archivio, tabella: str, scatto_id: int) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            f"UPDATE {tabella} SET da_riguardare = 1 WHERE scatto_id = ?", (scatto_id,))


def _fotogrammi_di(archivio, tabella: str, scatto_id: int) -> list[tuple[int, int]]:
    with archivio.lettura() as connessione:
        return [tuple(r) for r in connessione.execute(
            f"SELECT fotogramma, id FROM {tabella} WHERE scatto_id = ? "
            "ORDER BY fotogramma, id", (scatto_id,))]


@pytest.mark.parametrize("quale, finto, tabella, cose", [
    ("volti", _UnaFaccia, "volti_guardati", "volti"),
    ("corpi", RilevatoreFinto, "corpi_guardati", "corpi")])
def test_un_video_da_riguardare_aggiunge_e_non_tocca_quello_che_c_era(
        archivio_pieno, monkeypatch, quale, finto, tabella, cose):
    from PIL import Image

    video = _un_video(archivio_pieno)
    _dagli_le_impronte(archivio_pieno, video, quanti=1)
    monkeypatch.setattr(estrattore, "uno",
                        lambda *a, **k: Image.new("RGB", (64, 48), (90, 90, 90)))
    _passata(quale, archivio_pieno, finto()).esegui()
    prima = _fotogrammi_di(archivio_pieno, cose, video)
    assert [f for f, _ in prima] == [0]

    with archivio_pieno.scrittura() as connessione:
        for numero in (1, 2):
            magazzino_impronte.scrivi(
                connessione, video, None, "finto", "1", "intera", "intera",
                None, [0.1, 0.2], fotogramma=numero, istante_ms=numero * 1000)
    altri = _passata(quale, archivio_pieno, finto()).quanti_mancano()
    _segna_da_riguardare(archivio_pieno, tabella, video)
    passata = _passata(quale, archivio_pieno, finto())
    assert passata.quanti_mancano() == altri + 1
    passata.esegui()

    dopo = _fotogrammi_di(archivio_pieno, cose, video)
    assert [f for f, _ in dopo] == [0, 1, 2]
    assert dopo[0] == prima[0]
    with archivio_pieno.lettura() as connessione:
        riga = connessione.execute(
            f"SELECT quanti, da_riguardare FROM {tabella} WHERE scatto_id = ?",
            (video,)).fetchone()
    assert tuple(riga) == (3, 0)
    assert _passata(quale, archivio_pieno, finto()).quanti_mancano() == altri


def test_la_migrazione_76_segna_solo_i_video(tmp_path):
    import sqlite3

    from officina.archivio import migrazioni

    connessione = sqlite3.connect(tmp_path / "prova.db", isolation_level=None)
    connessione.execute("CREATE TABLE scatti (id INTEGER PRIMARY KEY, genere TEXT)")
    connessione.execute(
        "CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, aggiornato_il TEXT)")
    connessione.executemany("INSERT INTO scatti VALUES (?, ?)",
                            [(1, "foto"), (2, "video"), (3, "video")])
    for tabella in ("volti_guardati", "corpi_guardati"):
        connessione.execute(
            f"CREATE TABLE {tabella} (scatto_id INTEGER, modello TEXT, versione TEXT, "
            "quanti INTEGER, guardato_il TEXT)")
        connessione.executemany(
            f"INSERT INTO {tabella} VALUES (?, 'm', '1', 0, 'ieri')", [(1,), (2,)])
    settantasei = next(m for m in migrazioni.MIGRAZIONI if m.versione == 76)
    settantasei.applica(connessione)
    for tabella in ("volti_guardati", "corpi_guardati"):
        assert connessione.execute(
            f"SELECT scatto_id, da_riguardare FROM {tabella} ORDER BY scatto_id"
        ).fetchall() == [(1, 0), (2, 1)]
    assert connessione.execute(
        "SELECT valore FROM stato WHERE chiave = 'video_da_riguardare'").fetchone() == ("2",)
    assert migrazioni.MIGRAZIONI[-1].versione >= 76
