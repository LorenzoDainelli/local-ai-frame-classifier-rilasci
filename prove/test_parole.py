from __future__ import annotations

import pytest

from officina import parole
from officina.archivio.database import adesso, inserisci
from officina.parole import magazzino
from officina.parole.motore import Passata


class _Scritta:
    def __init__(self, testo, riquadro=None):
        self.testo = testo
        self.riquadro = riquadro


class _LettoreFinto:

    def __init__(self, risposte=None, rompiti_su=()):
        self.risposte = list(risposte or [])
        self.rompiti_su = set(rompiti_su)
        self.viste = 0
        self.aperture = 0
        self.chiuso = False

    def apri(self):
        self.aperture += 1
        return self

    def chiudi(self):
        self.chiuso = True

    def dove_gira(self):
        return "un lettore finto"

    def leggi(self, immagine):
        indice = self.viste
        self.viste += 1
        if indice in self.rompiti_su:
            raise RuntimeError("questa immagine non si lascia leggere")
        if indice < len(self.risposte):
            return [_Scritta(t) for t in self.risposte[indice]]
        return []


def _scatto_con_foto(archivio, cartella, nome: str) -> int:
    import hashlib

    from PIL import Image

    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.parent.mkdir(parents=True, exist_ok=True)
    immagine = Image.new("RGB", (60, 40), (200, 180, 160))
    lato = 4 + (sum(nome.encode()) % 20)
    for x in range(lato):
        for y in range(lato):
            immagine.putpixel((x, y), (10, 20, 30))
    immagine.save(sorgente)
    contenuto = sorgente.read_bytes()

    scatto_id = inserisci(
        connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?)", adesso())
    file_id = inserisci(
        connessione,
        "INSERT INTO file_media (impronta, dimensione, genere, formato, "
        "scatto_id, ruolo, aggiunto_il) VALUES (?, ?, 'immagine', 'jpeg', ?, "
        "'principale', ?)",
        hashlib.blake2b(contenuto, digest_size=32).hexdigest(),
        len(contenuto), scatto_id, adesso())
    inserisci(connessione,
              "INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
              "VALUES (?, ?, ?, ?)", file_id, str(sorgente), nome, adesso())
    connessione.commit()
    return scatto_id


@pytest.mark.parametrize("scritto, cercato", [
    ("Caffe' dell'Angolo", "caffe angolo"),
    ("BAR SPORT", "bar sport"),
    ("Trattoria da Gino", "TRATTORIA"),
    ("Museo Egizio", "egizio"),
])
def test_si_trova_come_capita_di_scriverlo(archivio, tmp_path, scritto, cercato):
    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.scrittura() as connessione:
        magazzino.scrivi(connessione, scatto, None, scritto, "parole", "1")

    with archivio.lettura() as connessione:
        trovati = magazzino.cerca(connessione, cercato)
    assert [r["scatto_id"] for r in trovati] == [scatto]


def test_due_parole_vogliono_dire_tutte_e_due(archivio, tmp_path):
    primo = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    secondo = _scatto_con_foto(archivio, tmp_path / "foto", "due.jpg")
    with archivio.scrittura() as connessione:
        magazzino.scrivi(connessione, primo, None, "Bar Sport", "parole", "1")
        magazzino.scrivi(connessione, secondo, None, "Bar Centrale", "parole", "1")

    with archivio.lettura() as connessione:
        trovati = magazzino.cerca(connessione, "bar sport")
    assert [r["scatto_id"] for r in trovati] == [primo]


def test_una_scritta_vuota_non_finisce_nel_database(archivio, tmp_path):
    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.scrittura() as connessione:
        assert magazzino.scrivi(connessione, scatto, None, "   ", "parole", "1") is None
        assert magazzino.quante_ce_ne_sono(connessione) == 0


def test_legge_tutto_e_scrive_quello_che_ha_letto(archivio, tmp_path):
    scatti = [_scatto_con_foto(archivio, tmp_path / "foto", f"{i}.jpg")
              for i in range(3)]
    lettore = _LettoreFinto([["Bar Sport"], [], ["Museo", "Egizio"]])

    passata = Passata(archivio, lettore=lettore, intensita=100)
    avanzamento = passata.esegui()

    assert avanzamento.letti == 3
    assert avanzamento.scritte == 3
    assert avanzamento.con_qualcosa == 2
    assert lettore.chiuso, "il modello va spento alla fine (regola 329)"
    with archivio.lettura() as connessione:
        assert len(magazzino.di_scatto(connessione, scatti[2])) == 2


def test_una_foto_senza_insegne_viene_segnata_come_letta(archivio, tmp_path):
    _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    Passata(archivio, lettore=_LettoreFinto([[]]), intensita=100).esegui()

    with archivio.lettura() as connessione:
        assert magazzino.quanti_da_leggere(connessione, "parole", parole.SCHEDA.versione) == 0


def test_riprende_da_dove_era(archivio, tmp_path):
    for i in range(4):
        _scatto_con_foto(archivio, tmp_path / "foto", f"{i}.jpg")

    prima = Passata(archivio, lettore=_LettoreFinto(), intensita=100)
    prima.esegui(quanti_al_massimo=2)
    assert prima.avanzamento.letti == 2

    with archivio.lettura() as connessione:
        assert magazzino.quanti_da_leggere(connessione, "parole", parole.SCHEDA.versione) == 2

    dopo = Passata(archivio, lettore=_LettoreFinto(), intensita=100)
    dopo.esegui()
    with archivio.lettura() as connessione:
        assert magazzino.quanti_da_leggere(connessione, "parole", parole.SCHEDA.versione) == 0


def test_una_foto_che_non_si_lascia_leggere_non_ferma_la_notte(archivio, tmp_path):
    for i in range(3):
        _scatto_con_foto(archivio, tmp_path / "foto", f"{i}.jpg")

    passata = Passata(archivio, lettore=_LettoreFinto(rompiti_su=[1]),
                      intensita=100)
    avanzamento = passata.esegui()
    assert avanzamento.letti == 2
    assert avanzamento.saltati == 1
    assert avanzamento.motivi_saltati == {"lettura_fallita": 1}


def test_lo_scatto_saltato_si_riprova_la_prossima_volta(archivio, tmp_path):
    _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    Passata(archivio, lettore=_LettoreFinto(rompiti_su=[0]), intensita=100).esegui()

    with archivio.lettura() as connessione:
        assert magazzino.quanti_da_leggere(connessione, "parole", parole.SCHEDA.versione) == 1


def test_il_tasto_ferma_si_sente(archivio, tmp_path):
    for i in range(5):
        _scatto_con_foto(archivio, tmp_path / "foto", f"{i}.jpg")

    passata = Passata(archivio, lettore=_LettoreFinto(), intensita=100)

    def al_passo(avanzamento):
        if avanzamento.letti >= 2:
            passata.ferma()

    avanzamento = passata.esegui(al_passo=al_passo)
    assert avanzamento.letti == 2


def test_la_scheda_dice_che_non_esegue_codice_di_terzi():
    assert parole.SCHEDA.esegue_codice_di_terzi is False
    assert parole.SCHEDA.identificatore == "Qwen/Qwen3.5-9B"
    assert parole.SCHEDA.versione != "1", "le letture di Florence-2 vanno rifatte"
    assert not any(cosa.endswith(".py") for cosa in parole.SCHEDA.cosa_serve)


def test_gli_altri_modelli_dicono_di_no():
    from officina.descrittori import SCHEDE

    for carta in SCHEDE.values():
        assert carta.esegue_codice_di_terzi is False, carta.nome


def test_senza_il_modello_lo_dice_e_non_lo_scarica(tmp_path):
    from officina.parole.lettore import Lettore, ModelloNonInCasa
    from officina.descrittori import torcia

    if not (torcia.c_e_torch() and torcia.c_e_transformers()):
        pytest.skip("senza torch il messaggio è l'altro, ed è provato altrove")
    with pytest.raises(ModelloNonInCasa) as errore:
        Lettore(tmp_path).apri()
    detto = str(errore.value)
    assert "modelli --scarica" in detto


def test_senza_le_librerie_lo_dice_in_italiano(tmp_path, monkeypatch):
    from officina.parole import lettore as modulo

    monkeypatch.setattr(modulo.torcia, "c_e_torch", lambda: False)
    with pytest.raises(modulo.MancanoLeLibrerie) as errore:
        modulo.Lettore(tmp_path).apri()
    assert "pip install" in str(errore.value)
    assert "funziona lo stesso" in str(errore.value)


@pytest.mark.parametrize("grezzo, descrizione, scritte", [
    ("DESCRIZIONE: Un bar con i tavolini all'aperto.\nSCRITTE:\nBar Sport\nAperto",
     "Un bar con i tavolini all'aperto.", ["Bar Sport", "Aperto"]),
    ("DESCRIZIONE: Una spiaggia al tramonto\nSCRITTE: nessuna",
     "Una spiaggia al tramonto", []),
    ("<think>\nci penso\n</think>\nDESCRIZIONE: un cane\nSCRITTE:\n- «Museo Egizio»\n2) Museo Egizio",
     "un cane", ["Museo Egizio"]),
    ("Descrizione:\nDue persone su una barca\nScritte:\n1. TAXI",
     "Due persone su una barca", ["TAXI"]),
    ("", "", []),
    ("qualcosa che non segue il formato", "", []),
])
def test_la_risposta_del_modello_si_legge_in_tutti_i_modi(grezzo, descrizione, scritte):
    from officina.parole.lettore import leggi_la_risposta

    sguardo = leggi_la_risposta(grezzo)
    assert sguardo.descrizione == descrizione
    assert [s.testo for s in sguardo.scritte] == scritte


def test_le_scritte_al_massimo_sono_venti():
    from officina.parole.lettore import SCRITTE_AL_MASSIMO, leggi_la_risposta

    righe = "\n".join(f"scritta {i}" for i in range(50))
    assert len(leggi_la_risposta("SCRITTE:\n" + righe).scritte) == SCRITTE_AL_MASSIMO


def test_la_ricerca_trova_quello_che_c_e_scritto_sopra(archivio, tmp_path):
    from officina import ricerca

    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.scrittura() as connessione:
        magazzino.scrivi(connessione, scatto, None, "Trattoria del Ponte",
                         "parole", "1")

    with archivio.lettura() as connessione:
        risposta = ricerca.cerca(connessione, archivio.dove.modelli,
                                 "trattoria ponte")

    scritte = [t for t in risposta.trovati if t.sorgente == "scritta"]
    assert [t.scatto_id for t in scritte] == [scatto]
    assert scritte[0].testo == "Trattoria del Ponte"
    assert any(c.genere == "scritta" for c in risposta.capito)


def test_senza_nessuna_scritta_la_ricerca_e_quella_di_prima(archivio, tmp_path):
    from officina import ricerca

    _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.lettura() as connessione:
        risposta = ricerca.cerca(connessione, archivio.dove.modelli, "bar sport")
    assert [t for t in risposta.trovati if t.sorgente == "scritta"] == []


def test_se_nessuna_foto_si_lascia_leggere_si_ferma_con_il_guasto_vero(archivio, tmp_path):
    for i in range(5):
        _scatto_con_foto(archivio, tmp_path / "foto", f"{i}.jpg")

    passata = Passata(archivio, lettore=_LettoreFinto(rompiti_su=range(5)),
                      intensita=100)
    with pytest.raises(RuntimeError):
        passata.esegui()
    with archivio.lettura() as connessione:
        assert magazzino.quanti_da_leggere(connessione, "parole", parole.SCHEDA.versione) == 5


class _LettoreCheGuarda(_LettoreFinto):

    def __init__(self, descrizioni, risposte=None):
        super().__init__(risposte)
        self.descrizioni = list(descrizioni)

    def guarda(self, immagine):
        from officina.parole.lettore import Sguardo

        indice = self.viste
        scritte = self.leggi(immagine)
        testo = self.descrizioni[indice] if indice < len(self.descrizioni) else ""
        return Sguardo(descrizione=testo, scritte=scritte)


def test_scrive_anche_la_descrizione_e_la_ricerca_la_trova(archivio, tmp_path):
    from officina import ricerca

    primo = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    _scatto_con_foto(archivio, tmp_path / "foto", "due.jpg")
    lettore = _LettoreCheGuarda(["Due persone su una barca al tramonto",
                                 "Un gatto sul divano"])
    avanzamento = Passata(archivio, lettore=lettore, intensita=100).esegui()
    assert avanzamento.descritte == 2

    with archivio.lettura() as connessione:
        assert magazzino.descrizione_di(connessione, primo) == \
            "Due persone su una barca al tramonto"
        risposta = ricerca.cerca(connessione, archivio.dove.modelli,
                                 "barca al tramonto")
    descritte = [t for t in risposta.trovati if t.sorgente == "descrizione"]
    assert [t.scatto_id for t in descritte] == [primo]
    assert any("descrizione" in d for d in risposta.detto)


def test_le_parole_vuote_non_bastano_a_trovare_una_descrizione(archivio, tmp_path):
    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.scrittura() as connessione:
        magazzino.scrivi_descrizione(connessione, scatto, None,
                                     "Una foto di un gatto", "parole", "2")
    with archivio.lettura() as connessione:
        assert magazzino.cerca_descrizioni(connessione, "una foto di") == []
        assert [r["scatto_id"] for r in
                magazzino.cerca_descrizioni(connessione, "il gatto")] == [scatto]


def test_la_nuova_lettura_butta_le_scritte_di_florence(archivio, tmp_path):
    scatto = _scatto_con_foto(archivio, tmp_path / "foto", "una.jpg")
    with archivio.scrittura() as connessione:
        magazzino.scrivi(connessione, scatto, None, "B4R SP0RT", "parole", "1")
        magazzino.segna_letto(connessione, scatto, "parole", "1", 1)
        assert magazzino.ci_sono_letture_vecchie(
            connessione, "parole", parole.SCHEDA.versione)
        assert magazzino.quanti_da_leggere(
            connessione, "parole", parole.SCHEDA.versione) == 1

    Passata(archivio, lettore=_LettoreCheGuarda(["un bar"], [["Bar Sport"]]),
            intensita=100).esegui()

    with archivio.lettura() as connessione:
        assert [r["testo"] for r in magazzino.di_scatto(connessione, scatto)] == ["Bar Sport"]
        assert magazzino.cerca(connessione, "sp0rt") == []


def test_un_video_si_legge_fotogramma_per_fotogramma(archivio, tmp_path, monkeypatch):
    from PIL import Image

    from officina.immagini import fotogrammi
    from officina.modello import segnalazioni

    scatto_id = _scatto_con_foto(archivio, tmp_path / "video", "gita.jpg")
    archivio.connessione.execute(
        "UPDATE file_media SET genere = 'video', formato = 'mov' WHERE scatto_id = ?",
        (scatto_id,))
    archivio.connessione.execute("UPDATE scatti SET genere = 'video' WHERE id = ?",
                                 (scatto_id,))
    archivio.connessione.commit()
    chiesti = []

    def prendi(percorso, quanti=40, lato=None, basta=None):
        chiesti.append(quanti)
        return fotogrammi.Resa([fotogrammi.Fotogramma(n, n * 100, Image.new("RGB", (8, 8)))
                                for n in range(3)], "finta", 3)

    monkeypatch.setattr(fotogrammi, "prendi", prendi)
    lettore = _LettoreFinto([["Bar Sport"], ["Bar Sport", "Molo"], ["Faro"]])
    avanzamento = Passata(archivio, lettore=lettore, intensita=100).esegui()

    assert lettore.viste == 3
    assert chiesti == [40]
    assert avanzamento.letti == 1 and avanzamento.scritte == 3
    with archivio.lettura() as connessione:
        trovate = {(r["testo"], r["fotogramma"]) for r in magazzino.di_scatto(connessione, scatto_id)}
        assert trovate == {("Bar Sport", 0), ("Molo", 1), ("Faro", 2)}
        assert segnalazioni.quante(connessione, segnalazioni.NON_SI_APRE) == 0
