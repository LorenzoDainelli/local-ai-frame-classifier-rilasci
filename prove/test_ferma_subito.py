from __future__ import annotations

import threading
import time

from officina.impronte.motore import Passata
from officina.modello import impronte as magazzino


def test_fermare_a_meta_non_perde_nessuna_fotografia(archivio_pieno):
    passata = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    tutte = passata.quanti_mancano()
    assert tutte > 1, "l'archivio di prova non ha abbastanza scatti"

    quante = {"gruppi": 0}
    vero = passata._fai_un_gruppo

    def conta(descrittore, pronto):
        fuori = vero(descrittore, pronto)
        quante["gruppi"] += 1
        passata.ferma()
        return fuori

    passata._fai_un_gruppo = conta
    passata.esegui()

    assert quante["gruppi"] >= 1
    restano = Passata(archivio_pieno, "disegnato").quanti_mancano()
    assert passata.avanzamento.fatti + restano == tutte, (
        "dopo il «Ferma» qualche fotografia non è né fatta né in coda")


def test_chi_prepara_smette_fra_una_fotografia_e_l_altra(archivio_pieno):
    passata = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    passata.ferma()
    righe = [{"id": 1, "genere": "foto", "durata_ms": None}] * 40
    pronto = passata._prepara_gruppo(righe)
    assert pronto.lavori == []
    assert pronto.righe == [], (
        "un gruppo abbandonato deve tornare vuoto: se tornasse pieno, quelle "
        "fotografie verrebbero segnate come «niente da fare» e non "
        "tornerebbero mai più in coda")


def test_quello_che_torna_sono_le_righe_guardate_non_quelle_chieste(archivio_pieno):
    passata = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    with archivio_pieno.lettura() as connessione:
        righe = magazzino.scatti_da_fare(connessione, "disegnato",
                                         passata.carta.versione, quanti=3)
    pronto = passata._prepara_gruppo(righe)
    assert [r["id"] for r in pronto.righe] == [r["id"] for r in righe]


def test_ferma_risponde_mentre_la_passata_gira(archivio_pieno):
    passata = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    if passata.quanti_mancano() == 0:
        return
    filo = threading.Thread(target=passata.esegui, daemon=True)
    filo.start()
    time.sleep(0.05)
    premuto = time.perf_counter()
    passata.ferma()
    filo.join(timeout=20)
    assert not filo.is_alive(), "la passata non si è fermata"
    assert time.perf_counter() - premuto < 20


def test_il_freno_guarda_il_segnale_dieci_volte_al_secondo():
    from officina.descrittori import torcia

    assert torcia.FETTA_DI_RIPOSO <= 0.2


def test_il_freno_smette_subito_se_gli_si_dice_di_fermarsi():
    from officina.descrittori import torcia

    fermo = {"si": False}
    freno = torcia.Freno(50, fermato=lambda: fermo["si"])
    fermo["si"] = True
    cominciato = time.perf_counter()
    freno.riposa(10.0)
    assert time.perf_counter() - cominciato < 1.0


def test_la_coda_dice_cosa_sta_aspettando_solo_dopo_un_ferma(archivio_pieno):
    from officina.impronte.motore import Coda

    coda = Coda(archivio_pieno, ["disegnato"])
    assert coda.perche_ci_mette() == "", "non si sta fermando niente"

    coda.ferma()
    assert coda.perche_ci_mette() == "mi sto fermando", (
        "fra un modello e l'altro non si aspetta nessuna delle tre cose lunghe")


def test_la_coda_distingue_le_tre_attese_lunghe(archivio_pieno):
    from officina.impronte.motore import Coda, Passata

    coda = Coda(archivio_pieno, ["disegnato"])
    coda.passata = Passata(archivio_pieno, "disegnato")
    coda.ferma()

    coda.passata.avanzamento.sta_aprendo = True
    assert "aprire il modello" in coda.perche_ci_mette()

    coda.passata.avanzamento.sta_aprendo = False
    assert "gruppo" in coda.perche_ci_mette()

    coda.passata.avanzamento.sta_chiudendo = True
    assert "scheda video" in coda.perche_ci_mette()
