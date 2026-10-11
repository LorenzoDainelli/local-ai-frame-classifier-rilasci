from __future__ import annotations

import pytest

from officina.descrittori import preparazione, vettori
from officina.descrittori.disegnato import Disegnato
from officina.finto import immagini
from officina.modello import impronte as magazzino


def _impronta_di(tema: str, seme: int) -> list[float]:
    immagine = immagini.disegna(tema, seme, (480, 360))
    return Disegnato().descrivi_una(preparazione.in_quadrato(immagine, 224))


def test_la_scheda_non_mente_sulla_propria_misura():
    carta = Disegnato.scheda
    assert len(_impronta_di("tema_a", 1)) == carta.dimensione


def test_la_stessa_immagine_da_sempre_la_stessa_impronta():
    assert _impronta_di("tema_b", 7) == _impronta_di("tema_b", 7)


def test_le_scene_uguali_si_somigliano_piu_di_quelle_diverse():
    dentro, fuori = [], []
    for tema in ("tema_a", "tema_b", "tema_c"):
        impronte = [_impronta_di(tema, seme) for seme in range(4)]
        for prima in range(4):
            for dopo in range(prima + 1, 4):
                dentro.append(vettori.somiglianza(impronte[prima], impronte[dopo]))
    a = [_impronta_di("tema_a", s) for s in range(3)]
    b = [_impronta_di("tema_d", s) for s in range(3)]
    fuori = [vettori.somiglianza(x, y) for x in a for y in b]
    assert min(dentro) > max(fuori), (
        "due foto della stessa scena si somigliano meno di due foto di scene "
        "diverse: il descrittore non descrive niente")


def test_impronta_scritta_e_riletta_uguale():
    valori = _impronta_di("tema_e", 2)
    dati = vettori.a_byte(valori)
    assert vettori.quanti_numeri(dati) == len(valori)
    riletta = list(vettori.da_byte(dati))
    assert vettori.somiglianza(valori, riletta) == pytest.approx(1.0, abs=1e-5)


def test_le_impronte_si_conservano_intere():
    dati = vettori.a_byte([0.1] * 100)
    assert len(dati) == 100 * 4


def test_lunghezze_diverse_non_si_mescolano():
    from officina.errori import ErroreOfficina

    with pytest.raises(ErroreOfficina):
        vettori.matrice([vettori.a_byte([1.0, 0.0]), vettori.a_byte([1.0, 0.0, 0.0])])


def test_tutti_gli_scatti_hanno_le_tre_inquadrature(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        assert magazzino.quanti_da_fare(connessione, "disegnato", "2") == 0
        righe = connessione.execute(
            "SELECT inquadratura, count(*) AS q FROM impronte "
            "WHERE fotogramma = 0 GROUP BY inquadratura").fetchall()
    quante = {riga["inquadratura"]: riga["q"] for riga in righe}
    assert set(quante) == set(preparazione.INQUADRATURE)
    assert len(set(quante.values())) == 1, (
        "le tre inquadrature devono esserci tutte e tre per ogni scatto")


def test_ogni_impronta_sa_da_dove_viene(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        riga = connessione.execute("SELECT * FROM impronte LIMIT 1").fetchone()
    assert riga["descrittore"] == "disegnato"
    assert riga["versione"] == "2"
    assert riga["metodo"] in ("intera", "centrale", "dettaglio", "rilevatore")
    assert riga["dimensione"] == Disegnato.scheda.dimensione


def test_rifare_le_impronte_non_tocca_le_etichette(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        prima = connessione.execute("SELECT count(*) AS q FROM etichette").fetchone()["q"]
    assert prima > 0

    with archivio_misurabile.scrittura() as connessione:
        buttate = magazzino.togli_di(connessione, "disegnato", "2")
    assert buttate > 0

    with archivio_misurabile.lettura() as connessione:
        dopo = connessione.execute("SELECT count(*) AS q FROM etichette").fetchone()["q"]
        assert connessione.execute("SELECT count(*) AS q FROM impronte").fetchone()["q"] == 0
    assert dopo == prima


def test_riprende_da_dove_era(archivio_misurabile):
    from officina.impronte.motore import Passata

    with archivio_misurabile.scrittura() as connessione:
        magazzino.togli_di(connessione, "disegnato", "2")

    passata = Passata(archivio_misurabile, "disegnato", fotogrammi_per_video=2)
    tutti = passata.quanti_mancano()
    assert tutti > 4

    fatti = Passata(archivio_misurabile, "disegnato", fotogrammi_per_video=2)
    fatti.esegui(quanti_al_massimo=3)
    restano = fatti.quanti_mancano()
    assert 0 < restano < tutti

    fine = Passata(archivio_misurabile, "disegnato", fotogrammi_per_video=2).esegui()
    assert fine.fatti == restano
    assert Passata(archivio_misurabile, "disegnato").quanti_mancano() == 0


def test_il_freno_riposa_quanto_gli_si_chiede():
    from officina.descrittori.torcia import Freno

    assert Freno(100).riposa(0.05) == 0.0
    assert Freno(50).riposa(0.05) == pytest.approx(0.05, rel=0.3)
    assert Freno(25).riposa(0.02) == pytest.approx(0.06, rel=0.3)


class _OrologioFinto:

    def __init__(self):
        self.adesso = 0.0
        self.dormito: list[float] = []

    def sleep(self, secondi: float) -> None:
        self.dormito.append(secondi)
        self.adesso += secondi

    def monotonic(self) -> float:
        return self.adesso


def test_una_pausa_lunga_non_viene_tagliata_a_meta(monkeypatch):
    from officina.descrittori import torcia

    orologio = _OrologioFinto()
    monkeypatch.setattr(torcia.time, "sleep", orologio.sleep)
    monkeypatch.setattr(torcia.time, "monotonic", orologio.monotonic)

    torcia.Freno(50).riposa(120.0)

    assert sum(orologio.dormito) == pytest.approx(120.0, rel=0.05)
    assert max(orologio.dormito) <= 1.0


def test_il_tasto_ferma_interrompe_anche_la_pausa(monkeypatch):
    from officina.descrittori import torcia

    orologio = _OrologioFinto()
    monkeypatch.setattr(torcia.time, "sleep", orologio.sleep)
    monkeypatch.setattr(torcia.time, "monotonic", orologio.monotonic)

    freno = torcia.Freno(50, fermato=lambda: len(orologio.dormito) >= 3)
    freno.riposa(120.0)

    assert len(orologio.dormito) == 3


def test_il_cursore_vale_subito_anche_a_lavoro_gia_partito(archivio_misurabile):
    from officina.impronte.motore import Passata

    passata = Passata(archivio_misurabile, "disegnato")
    archivio_misurabile.imposta("intensita_scheda", 40)
    assert passata._intensita_ora() == 40
    archivio_misurabile.imposta("intensita_scheda", 100)
    assert passata._intensita_ora() == 100

    fissata = Passata(archivio_misurabile, "disegnato", intensita=100)
    archivio_misurabile.imposta("intensita_scheda", 10)
    assert fissata._intensita_ora() == 100


def test_il_freno_cambia_passo_senza_ricominciare():
    from officina.descrittori.torcia import Freno

    freno = Freno(100)
    assert freno.riposa(0.02) == 0.0
    freno.cambia(50)
    assert freno.riposa(0.02) == pytest.approx(0.02, abs=0.005)


def test_la_cpu_prepara_mentre_la_scheda_video_guarda(archivio_misurabile,
                                                      monkeypatch):
    import threading
    import time as orologio

    from officina.impronte import motore
    from officina.impronte.motore import Passata

    with archivio_misurabile.scrittura() as connessione:
        magazzino.togli_di(connessione, "disegnato", "2")

    monkeypatch.setattr(motore, "IMMAGINI_PER_GRUPPO", 1)

    sta_preparando = threading.Event()
    sovrapposti: list[bool] = []

    passata = Passata(archivio_misurabile, "disegnato", fotogrammi_per_video=2)
    prepara_davvero = passata._prepara_gruppo

    def prepara(righe):
        sta_preparando.set()
        try:
            orologio.sleep(0.05)
            return prepara_davvero(righe)
        finally:
            sta_preparando.clear()

    passata._prepara_gruppo = prepara

    apri_davvero = motore.apri_descrittore

    def apri(nome, dove):
        descrittore = apri_davvero(nome, dove)
        descrivi_davvero = descrittore.descrivi

        def spia(immagini):
            orologio.sleep(0.05)
            sovrapposti.append(sta_preparando.is_set())
            return descrivi_davvero(immagini)

        descrittore.descrivi = spia
        return descrittore

    monkeypatch.setattr(motore, "apri_descrittore", apri)

    passata.esegui(quanti_al_massimo=4)

    assert sovrapposti, "non ha guardato niente: la prova non prova nulla"
    assert any(sovrapposti), (
        "la scheda video ha sempre aspettato che la CPU finisse: "
        "il gruppo successivo non si sta preparando in parallelo")


def test_la_tabella_delle_impronte_e_una_finestra_e_non_una_copia():
    numpy = pytest.importorskip("numpy")

    tabella = vettori.matrice([vettori.a_byte([1.0, 0.0]),
                               vettori.a_byte([0.0, 1.0])])
    assert tabella.shape == (2, 2)
    assert not tabella.flags.writeable
    with pytest.raises(ValueError):
        tabella[0, 0] = 9.0
    mia = tabella.copy()
    mia[0, 0] = 9.0
    assert float(mia[0, 0]) == 9.0
    assert float(tabella[0, 0]) == 1.0
    assert numpy is not None
