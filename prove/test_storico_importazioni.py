from officina.archivio.database import tutti
from officina.importazione import storico
from officina.importazione.motore import Motore


def _cartella(tmp_path, nome="foto", quanti=3):
    from officina.finto import generatore
    dove = tmp_path / nome
    generatore.genera(dove, quanti=quanti, seme=7, leggero=True)
    return dove


def _mandate(archivio):
    with archivio.lettura() as connessione:
        return storico.mandate(connessione)


def test_una_mandata_per_volta_che_hai_premuto_comincia(archivio, tmp_path):
    dove = _cartella(tmp_path, quanti=3)
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    motore.prepara([dove])
    motore.esegui()

    elenco = _mandate(archivio)
    assert len(elenco) == 2, "due «Comincia» devono lasciare due righe"


def test_la_seconda_volta_sono_tutti_gia_presenti(archivio, tmp_path):
    dove = _cartella(tmp_path, quanti=3)
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    motore.prepara([dove])
    motore.esegui()

    recente, prima = _mandate(archivio)
    assert prima.nuovi_scatti > 0, "la prima mandata ha portato scatti nuovi"
    assert recente.nuovi_scatti == 0
    assert recente.gia_presenti >= prima.nuovi_scatti, (
        "ridando la stessa cartella ogni file deve risultare già presente: "
        "l'impronta è del contenuto, non del momento (regola 39)")


def test_di_ogni_mandata_si_sa_quale_cartella_era(archivio, tmp_path):
    prima = _cartella(tmp_path, "vacanze", quanti=2)
    seconda = _cartella(tmp_path, "montagna", quanti=2)
    motore = Motore(archivio)
    motore.prepara([prima])
    motore.esegui()
    motore.prepara([seconda])
    motore.esegui()

    recente, vecchia = _mandate(archivio)
    assert vecchia.cartelle == ["vacanze"]
    assert recente.cartelle == ["montagna"], (
        "la cartella nuova non deve trascinarsi dietro quella di prima")


def test_il_percorso_non_si_mostra_solo_il_nome(archivio, tmp_path):
    dove = _cartella(tmp_path, "private", quanti=2)
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()

    (mandata,) = _mandate(archivio)
    assert mandata.cartelle == ["private"]
    assert str(tmp_path) not in " ".join(mandata.cartelle), (
        "regola 106: il percorso non ha ragione di stare scritto in una pagina")


def test_due_cartelle_in_una_volta_restano_una_riga_sola(archivio, tmp_path):
    prima = _cartella(tmp_path, "una", quanti=2)
    seconda = _cartella(tmp_path, "due", quanti=2)
    motore = Motore(archivio)
    motore.prepara([prima, seconda])
    motore.esegui()

    elenco = _mandate(archivio)
    assert len(elenco) == 1
    assert sorted(elenco[0].cartelle) == ["due", "una"]


def test_si_mostrano_le_ultime_non_tutte(archivio, tmp_path):
    dove = _cartella(tmp_path, quanti=1)
    motore = Motore(archivio)
    for _ in range(4):
        motore.prepara([dove])
        motore.esegui()

    with archivio.lettura() as connessione:
        elenco = storico.mandate(connessione, quante=2)
        tutte = tutti(connessione, "SELECT id FROM importazioni")
    assert len(tutte) == 4
    assert [m.id for m in elenco] == [tutte[-1]["id"], tutte[-2]["id"]], (
        "si mostrano le più recenti, in ordine dalla più nuova")


def test_l_ora_e_quella_di_qui_non_quella_universale():
    from datetime import datetime, timezone

    istante = "2026-09-04T20:15:00Z"
    atteso = datetime(2026, 9, 4, 20, 15, tzinfo=timezone.utc).astimezone()
    detto = storico.quando_a_parole(istante)
    assert detto == f"{atteso.day} {storico.MESI[atteso.month - 1]}, {atteso:%H:%M}"


def test_la_durata_si_dice_come_la_direbbe_una_persona():
    assert storico.durata_a_parole("2026-09-04T20:00:00Z",
                                   "2026-09-04T20:00:30Z") == "30 secondi"
    assert storico.durata_a_parole("2026-09-04T20:00:00Z",
                                   "2026-09-04T20:41:00Z") == "41 minuti"
    assert storico.durata_a_parole("2026-09-04T20:00:00Z",
                                   "2026-09-04T22:10:00Z") == "2 ore e 10 min"
    assert storico.durata_a_parole("2026-09-04T20:00:00Z",
                                   "2026-09-04T21:00:00Z") == "1 ora"


def test_di_una_mandata_non_finita_non_si_inventa_la_durata():
    assert storico.durata_a_parole("2026-09-04T20:00:00Z", None) == ""


def test_il_nome_della_cartella_si_taglia_su_tutt_e_due_le_barre():
    assert storico.nome_corto("C:\\Users\\loren\\Foto") == "Foto"
    assert storico.nome_corto("C:\\Users\\loren\\Foto\\") == "Foto"
    assert storico.nome_corto("/home/loren/Foto") == "Foto"


def test_la_pagina_mostra_le_mandate_di_prima_e_non_i_percorsi(archivio, tmp_path):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    dove = _cartella(tmp_path, "vacanze", quanti=2)
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    motore.prepara([dove])
    motore.esegui()

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/importazione").text

    assert "Le importazioni di prima" in pagina
    storico_in_pagina = pagina.split("Le importazioni di prima", 1)[1]
    assert "vacanze" in storico_in_pagina
    assert str(tmp_path) not in storico_in_pagina, (
        "regola 106: il percorso non ha ragione di comparire nello storico")
