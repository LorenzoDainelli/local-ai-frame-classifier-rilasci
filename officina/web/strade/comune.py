from __future__ import annotations

import threading

from officina.apprendimento import proposte, rendiconto
from officina.importazione.motore import InSottofondo
from officina.web import lavori


lavoro: InSottofondo | None = None
piano_pronto: dict | None = None

coda_impronte = None
lavoro_impronte_passata = lavori.Lavoro("le impronte", scheda=True)
ultima_misura: dict | None = None
lavoro_misura = lavori.Lavoro("la misura")

lavoro_modelli = lavori.Lavoro("i modelli")
lavoro_volti = lavori.Lavoro("i volti", scheda=True)
lavoro_corpi = lavori.Lavoro("i corpi", scheda=True)
lavoro_chi_e = lavori.Lavoro("chi è senza volto", scheda=True)
ultima_risposta_dei_corpi = {"quando": 0.0}
lavoro_parole = lavori.Lavoro("le scritte nelle foto", scheda=True)
passata_parole = None
lavoro_riferimento = lavori.Lavoro("le facce insegnate")
lavoro_raccolta = lavori.Lavoro("le foto raccolte in un posto solo")
piano_raccolta: dict | None = None
lavoro_copia_video = lavori.Lavoro("la copia del video")
lavoro_raddrizza = lavori.Lavoro("i video girati da raddrizzare")
raddrizza_basta = threading.Event()
lavoro_date = lavori.Lavoro("le date da rileggere")
date_basta = threading.Event()
lavoro_macchine = lavori.Lavoro("le macchine da rileggere")
macchine_basta = threading.Event()
passata_volti = None
passata_corpi = None

gia_ripreso = False

bottega = proposte.Bottega()

pagella_pronta = rendiconto.Sempre()


def prepara_i_conti() -> None:
    from officina.archivio import accesso
    from officina.modello import etichette

    with accesso.aperto().lettura() as connessione:
        pagella_pronta.per(connessione,
                           senza_etichetta=etichette.quanti_senza_etichetta(connessione))
        bottega.assicura(connessione)


lavoro_doppioni = lavori.Lavoro("i doppioni")
passata_doppioni = None
programma_di_qui = None
lavoro_ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
fila_ia: dict = {"scelti": [], "adesso": "", "fermata": False, "dove_guasto": ""}
scaricatore_mg = None
lavoro_qualita = lavori.Lavoro("il controllo degli scatti")
ferma_la_qualita = threading.Event()

lavoro_ia.figli = (lavoro_impronte_passata, lavoro_volti, lavoro_corpi, lavoro_parole)
