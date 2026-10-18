from __future__ import annotations

import pytest

from officina import lingua, ricerca
from officina.lingua import riformulatore as rif


def test_le_riflessioni_ad_alta_voce_si_buttano():
    grezzo = "<think>vediamo, il cane...</think>\na dog in someones arms"
    assert rif._tieni_le_didascalie(grezzo, gia="x") == ["a dog in someones arms"]


def test_le_riflessioni_mai_chiuse_non_diventano_una_domanda():
    modi = rif._tieni_le_didascalie("il cane\n</think>\na dog", gia="x")
    assert "</think>" not in " ".join(modi)


def test_si_butta_tutto_quello_che_spiega_invece_di_chiedere():
    grezzo = ("Ecco le tre righe:\n"
              "traduzione: a dog\n"
              "1. a dog held in arms\n"
              "- a puppy carried by someone\n"
              + "x" * 200 + "\n")
    assert rif._tieni_le_didascalie(grezzo, gia="x") == [
        "a dog held in arms", "a puppy carried by someone"]


def test_non_si_ripete_la_frase_che_hai_gia_scritto_tu():
    modi = rif._tieni_le_didascalie("cane in braccio\na dog in arms",
                                    gia="Cane in braccio")
    assert modi == ["a dog in arms"]


def test_non_piu_di_tre_modi():
    grezzo = "\n".join(f"foto numero {n}" for n in range(20))
    assert len(rif._tieni_le_didascalie(grezzo, gia="x")) == rif.QUANTI_MODI


class ModelloCheScoppia(rif.Riformulatore):
    def __init__(self):
        super().__init__(__import__("pathlib").Path("."))
        self.chiuso = False

    def _chiedi(self, frase):
        raise RuntimeError("il percorso segreto /casa/foto/nonna.heic")

    def chiudi(self):
        self.chiuso = True


class ModelloMuto(rif.Riformulatore):
    def __init__(self, risposta):
        super().__init__(__import__("pathlib").Path("."))
        self.risposta = risposta

    def _chiedi(self, frase):
        return self.risposta


def test_un_modello_che_scoppia_da_le_forme_fisse():
    esito = ModelloCheScoppia().riformula("cane in braccio")
    assert esito.modi == ["cane in braccio", "una foto di cane in braccio"]
    assert not esito.dal_modello


def test_il_motivo_non_contiene_mai_il_dettaglio_dell_errore():
    esito = ModelloCheScoppia().riformula("cane in braccio")
    assert "nonna" not in esito.perche_no
    assert "/casa" not in esito.perche_no


def test_una_risposta_senza_capo_ne_coda_torna_alle_forme_fisse():
    esito = ModelloMuto("Certo! Ecco:\n").riformula("cane in braccio")
    assert not esito.dal_modello
    assert esito.perche_no


def test_la_frase_che_hai_scritto_tu_resta_la_prima():
    esito = ModelloMuto("a dog in arms\na puppy held").riformula("cane in braccio")
    assert esito.modi[0] == "cane in braccio"
    assert esito.modi[1:] == ["a dog in arms", "a puppy held"]
    assert esito.dal_modello


def test_una_frase_vuota_non_fa_partire_niente():
    esito = ModelloCheScoppia().riformula("   ")
    assert esito.modi == []


def test_senza_il_modello_si_dice_come_si_scarica(tmp_path):
    assert not lingua.in_casa(tmp_path)
    with pytest.raises(rif.ModelloNonInCasa) as scoppio:
        lingua.apri(tmp_path).apri()
    detto = str(scoppio.value)
    assert "python -m officina modelli --scarica parole" in detto
    assert "funziona lo stesso" in detto


def test_la_ricerca_non_lo_apre_se_non_c_e(tmp_path, monkeypatch):
    def mai(*_, **__):
        raise AssertionError("ha provato ad aprire un modello che non c'è")

    monkeypatch.setattr(lingua, "apri", mai)
    assert ricerca._riscrivi("cane", tmp_path, True).modi


def test_la_licenza_c_e_e_dice_qualcosa():
    assert "Apache" in lingua.SCHEDA.licenza
    assert lingua.SCHEDA.va_scaricato
    assert lingua.SCHEDA.identificatore


def test_non_e_un_descrittore():
    from officina import descrittori

    assert lingua.SCHEDA.nome not in descrittori.SCHEDE
    assert lingua.SCHEDA.dimensione == 0


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_il_primo_tempo_risponde_senza_riformulare(cliente, monkeypatch):
    def mai(*_, **__):
        raise AssertionError("il primo tempo ha aperto il modello linguistico")

    monkeypatch.setattr(lingua, "apri", mai)
    risposta = cliente.get("/api/cerca?frase=cappello di paglia")
    assert risposta.status_code == 200
    assert risposta.json()["modi_da_dove"] == "forme fisse"


def test_la_pagina_sa_se_il_secondo_tempo_e_possibile(cliente):
    dati = cliente.get("/api/cerca?frase=cappello").json()
    assert "c_e_da_riscrivere" in dati
    assert dati["c_e_da_riscrivere"] is False


def test_senza_il_modello_delle_parole_non_si_dichiara_nessun_modo(cliente):
    dati = cliente.get("/api/cerca?frase=cappello di paglia").json()
    assert dati["modi"] == []
    assert dati["con_le_parole"] is False


def test_nessuno_zip_accoppia_in_silenzio_due_liste_diverse():
    import ast
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent / "officina"
    nudi = []
    for sorgente in sorted(radice.rglob("*.py")):
        albero = ast.parse(sorgente.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            if not (isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Name)
                    and nodo.func.id == "zip"):
                continue
            if any(chiave.arg == "strict" for chiave in nodo.keywords):
                continue
            nudi.append(f"{sorgente.relative_to(radice.parent)}:{nodo.lineno}")

    assert not nudi, (
        "questi `zip` si fermano alla lista più corta senza dirlo: o le due "
        "liste devono combaciare, e allora ci va `strict=True`, o non devono, "
        "e allora ci va `strict=False` scritto apposta con il perché. "
        + "; ".join(nudi))


def test_nessun_filo_puo_morire_in_silenzio():
    import ast
    from pathlib import Path

    SAPUTI = {
        "officina/archivio/riserva.py":
            "`_fai` prende dentro qualunque errore, lo scrive nel registro e lo "
            "tiene per la pagina: quello già copiato resta copiato",
        "officina/web/strade/galleria.py":
            "`_gli_altri_pezzi` prende dentro qualunque errore, lo scrive nel "
            "registro e lo mostra sotto la barra",
        "officina/schermo/porta.py":
            "`Porta._ascolta` prende dentro qualunque errore e lo scrive nel "
            "registro: se non si risponde alla ricerca, il portatile lo dice",
        "officina/schermo/collega.py":
            "il filo del `Ponte` è `serve_forever` di socketserver, che prende "
            "gli errori di ogni richiesta: una richiesta rotta non ferma il ponte",
        "officina/archivio/spazio.py":
            "`_conta_e_ricorda` prende dentro qualunque errore e lo scrive nel "
            "registro: un conto dello spazio mancato non ferma niente",
        "officina/web/lavori.py":
            "è la macchina che prende il guasto e lo racconta: è lei che "
            "rende sicuri gli altri",
        "officina/importazione/motore.py":
            "`InSottofondo._dentro` prende il guasto, lo scrive nel registro "
            "e lo tiene per la pagina",
        "officina/descrittori/scaricamento.py":
            "il filo del `Sorvegliante` chiama solo `guarda_una_volta`, che si "
            "prende dentro qualunque errore: chi racconta non deve poter "
            "fermare chi lavora",
        "officina/riga_di_comando.py":
            "apre la finestra del browser, e prende dentro tutto: non "
            "riuscire ad aprirla non è un motivo per rovinare l'avvio",
        "officina/programma/servitore.py":
            "`Servitore._dentro` prende anche i BaseException e li tiene: chi "
            "aspetta la partenza vede il filo morto e lo dice con parole sue",
        "officina/programma/avvio.py":
            "ogni filo del programma passa da un metodo che prende dentro "
            "tutto (apertura, chiusura, aggiornamenti), e sopra c'è "
            "`threading.excepthook` che lo scrive nel registro",
        "officina/programma/aggiornarsi.py":
            "pezzo del `Programma` di `avvio.py`: stessi fili, stessi metodi che "
            "prendono dentro tutto, stesso `threading.excepthook` sopra",
        "officina/programma/finestre.py":
            "pezzo del `Programma` di `avvio.py`: stessi fili, stessi metodi che "
            "prendono dentro tutto, stesso `threading.excepthook` sopra",
        "officina/programma/schermo_fisso.py":
            "pezzo del `Programma` di `avvio.py`: stessi fili, stessi metodi che "
            "prendono dentro tutto, stesso `threading.excepthook` sopra",
        "officina/programma/collaudo.py":
            "il filo che guida il collaudo prende dentro tutto e scrive il "
            "guasto nel risultato, che è la cosa che il collaudo deve dire",
        "officina/programma/librerie.py":
            "`Installatore._dentro` prende qualunque guasto e lo tiene per la "
            "finestra della preparazione, che lo mostra con «Riprova»",
        "officina/importazione/miniature.py":
            "`_scrivi_i_colori` prende dentro qualunque errore e lo scrive nel "
            "registro: un colore non salvato si rifà alla prossima pagina",
        "officina/web/strade/base.py":
            "il filo che ricorda l'ultimo filtro prende dentro qualunque errore "
            "e lo scrive nel registro: il filtro dimenticato non rompe la galleria",
        "officina/web/in_disparte.py":
            "il filo `gira` del processo dell'intelligenza prende dentro "
            "qualunque guasto, lo scrive nel registro e lo manda al programma",
        "officina/miglioria/preparazione.py":
            "il filo che racconta le librerie prende dentro qualunque errore: "
            "chi racconta non deve poter fermare chi installa",
        "officina/programma/sigillo.py":
            "il filo di Windows Hello prende dentro anche i BaseException e chi "
            "lo aspetta li rilancia: il guasto arriva a chi ha chiesto il sigillo",
        "officina/apprendimento/rendiconto.py":
            "il filo che rifà la pagella prende dentro qualunque errore e lo "
            "scrive nel registro: la pagella vecchia resta, e la prossima "
            "pagina ne chiede un'altra",
        "officina/sicuro/sottofondo.py":
            "`Sottofondo._gira` prende dentro qualunque guasto, anche quello "
            "di `_alla_fine`, e lo tiene in `errore` e `codice` per la pagina",
        "officina/sicuro/chiavetta.py":
            "il filo del `Guardiano` prende dentro qualunque errore di un giro, "
            "lo segna come problema e riprova al giro dopo",
        "officina/sicuro/recupera.py":
            "`Regia._prepara` prende dentro qualunque guasto e torna alla "
            "password con il messaggio, che la finestrina mostra",
    }

    radice = Path(__file__).resolve().parent.parent
    trovati = set()
    for sorgente in sorted((radice / "officina").rglob("*.py")):
        albero = ast.parse(sorgente.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            if (isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr == "Thread"):
                trovati.add(str(sorgente.relative_to(radice)).replace("\\", "/"))

    nuovi = trovati - set(SAPUTI)
    assert not nuovi, (
        "qui si fa partire un filo e nessuno ha scritto cosa succede se si "
        "rompe: aggiungilo all'elenco di questa prova con la sua ragione, "
        "oppure fallo passare da `web/lavori.py`. " + ", ".join(sorted(nuovi)))

    spariti = set(SAPUTI) - trovati
    assert not spariti, (
        "l'elenco nomina posti dove non si fa più partire nessun filo: "
        + ", ".join(sorted(spariti)))
