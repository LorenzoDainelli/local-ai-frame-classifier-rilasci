from __future__ import annotations

import threading

from officina.apprendimento import proposte, rendiconto
from officina.importazione.motore import InSottofondo
from officina.web import lavori


lavoro: InSottofondo | None = None
piano_pronto: dict | None = None

coda_impronte = None
lavoro_impronte_passata = lavori.Lavoro("le impronte")
ultima_misura: dict | None = None
lavoro_misura = lavori.Lavoro("la misura")

lavoro_modelli = lavori.Lavoro("i modelli")
lavoro_volti = lavori.Lavoro("i volti")
lavoro_corpi = lavori.Lavoro("i corpi")
lavoro_parole = lavori.Lavoro("le scritte nelle foto")
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
lavoro_doppioni = lavori.Lavoro("i doppioni")
passata_doppioni = None
programma_di_qui = None
lavoro_ia = lavori.Lavoro("l'intelligenza artificiale")
fila_ia: dict = {"scelti": [], "adesso": "", "fermata": False, "dove_guasto": ""}
scaricatore_mg = None
lavoro_qualita = lavori.Lavoro("il controllo degli scatti")
ferma_la_qualita = threading.Event()
