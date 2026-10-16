from officina.modello import etichette, nodi, scatti
from officina.modello.scatti import Filtro
from officina.archivio.database import uno
from officina.importazione.motore import Motore


def _cartella(tmp_path, quanti=3):
    from officina.finto import generatore
    dove = tmp_path / "foto"
    generatore.genera(dove, quanti=quanti, seme=7, leggero=True)
    return dove


def test_A_prepara_due_volte_non_abbandona_la_prima_fila(archivio, tmp_path):
    dove = _cartella(tmp_path, 6)
    motore = Motore(archivio)
    motore.prepara([dove])
    primo = motore.importazione_id
    motore.esegui(limite=1)
    motore.prepara([dove])
    secondo = motore.importazione_id
    assert primo != secondo
    with archivio.lettura() as c:
        rimaste = uno(c, "SELECT count(*) AS q FROM coda_importazione "
                         "WHERE importazione_id = ? AND stato = 'in_attesa'", primo)["q"]
        stato = uno(c, "SELECT stato FROM importazioni WHERE id = ?", primo)["stato"]
    assert not (rimaste and stato == "in_corso"), (
        f"{rimaste} file restano in attesa nell'importazione {primo}, ancora "
        f"«in_corso»: riprendi() prende sempre la più recente, quindi "
        "nessuno li farà mai più.")


def test_B_prepara_regge_un_file_sparito_fra_scansione_e_fila(archivio, tmp_path, monkeypatch):
    from officina.importazione import scansione
    dove = _cartella(tmp_path, 4)
    vero = scansione.elenca

    def elenca_e_poi_sparisce(cartelle):
        trovati = vero(cartelle)
        trovati.file[0].unlink()
        return trovati

    monkeypatch.setattr(scansione, "elenca", elenca_e_poi_sparisce)
    motore = Motore(archivio)
    motore.prepara([dove])
    with archivio.lettura() as c:
        assert uno(c, "SELECT count(*) AS q FROM coda_importazione")["q"] >= 3


def test_C_un_file_riuscito_esce_dai_non_importati(archivio, tmp_path):
    dove = _cartella(tmp_path, 3)
    uno_qualsiasi = sorted((dove / "2021").rglob("*.HEIC"))[0]
    motore = Motore(archivio)
    motore._segna_non_importato(uno_qualsiasi, "corrotto", "finto guasto di ieri")
    motore.prepara([dove])
    motore.esegui()
    with archivio.lettura() as c:
        resta = uno(c, "SELECT count(*) AS q FROM non_importati WHERE percorso = ?",
                    str(uno_qualsiasi))["q"]
    assert resta == 0, ("il file è entrato ma resta scritto fra i non "
                        "importati: il contatore «da guardare» non tornerà mai a zero")


def test_D_riprova_non_perde_la_riga_se_va_male_di_nuovo(archivio, tmp_path, monkeypatch):
    from officina.web import server
    from officina.web.strade import importazione
    from fastapi.testclient import TestClient
    dove = _cartella(tmp_path, 2)
    guasto = sorted((dove / "2021").rglob("*.HEIC"))[0]
    motore = importazione.motore_attuale()
    motore._segna_non_importato(guasto, "corrotto", "finto guasto")

    def scoppia(self, percorso):
        raise ValueError("difetto imprevisto, come quello che _lavora_una già prevede")

    monkeypatch.setattr(Motore, "_importa", scoppia)
    cliente = TestClient(server.app, client=("127.0.0.1", 51000),
                         raise_server_exceptions=False)
    cliente.post("/elenchi/riprova/1")
    with archivio.lettura() as c:
        resta = uno(c, "SELECT count(*) AS q FROM non_importati")["q"]
    assert resta == 1, "il riprova andato male ha cancellato la riga: il file è sparito in silenzio"


def test_E_non_si_prepara_una_fila_mentre_il_motore_lavora(archivio, tmp_path, monkeypatch):
    from officina.web import server
    from officina.web.strade import comune, importazione
    from fastapi.testclient import TestClient
    dove = _cartella(tmp_path, 4)
    cliente = TestClient(server.app, client=("127.0.0.1", 51000),
                         raise_server_exceptions=False)
    cliente.post("/importazione/cartella", data={"percorso": str(dove)})
    importazione.motore_attuale()

    class FintoFilo:
        is_alive = staticmethod(lambda: True)

    comune.lavoro._filo = FintoFilo()
    assert comune.lavoro.sta_lavorando
    cliente.post("/importazione/prepara", follow_redirects=False)
    comune.lavoro._filo = None
    with archivio.lettura() as c:
        quante = uno(c, "SELECT count(*) AS q FROM importazioni")["q"]
    assert quante == 0, "ha aperto un'importazione nuova mentre il motore lavorava"


def test_dopo_aver_etichettato_dentro_un_filtro_si_va_avanti(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        nodo = nodi.crea(c, "prova coda")
    filtro = Filtro(senza_etichetta=True)
    with archivio_pieno.lettura() as c:
        elenco = [r["id"] for r in scatti.pagina(c, filtro, 0, 100)]
    assert len(elenco) >= 3
    primo = elenco[0]
    with archivio_pieno.scrittura() as c:
        etichette.metti(c, primo, nodo, "si")
    with archivio_pieno.lettura() as c:
        vicini = scatti.vicini(c, filtro, primo)
    assert vicini["dopo"] is not None, (
        "appena etichettato, lo scatto esce dal filtro e «avanti» non sa più "
        f"dove andare: restano {len(elenco) - 1} scatti da fare")


def test_G_un_video_senza_istante_trova_lo_stesso_la_sua_foto(archivio):
    from officina.importazione import abbinamento

    with archivio.scrittura() as c:
        scatto = c.execute(
            "INSERT INTO scatti (genere, creato_il) "
            "VALUES ('foto', '2026-01-01T00:00:00')").lastrowid
        foto_id = c.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, istante_utc, "
            "scatto_id, ruolo, aggiunto_il) VALUES ('bytefoto', 900000, "
            "'immagine', '2026-05-04T10:00:02Z', ?, 'principale', "
            "'2026-01-01T00:00:00')",
            (scatto,)).lastrowid
        c.execute("INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
                  "VALUES (?, 'C:/foto/IMG_9001.HEIC', 'IMG_9001.HEIC', 1, "
                  "'2026-01-01T00:00:00')",
                  (foto_id,))

    video = abbinamento.Candidato(
        id=-1, nome="IMG_9001.MOV", istante_utc=None,
        data_locale="2026-05-04T10:00:00", identificatore_ios=None,
        durata_ms=2100)

    motore = Motore(archivio)
    with archivio.lettura() as c:
        possibili = motore._foto_possibili(c, video)

    assert foto_id in [p.id for p in possibili], (
        "la foto gemella non è nemmeno fra le possibili: la finestra "
        "dell'istante si è chiusa a zero")
    esito = abbinamento.cerca_gemella(video, possibili)
    assert esito.e_live, "due indizi su tre concordano, doveva essere certa"


def test_H_se_il_filo_dell_importazione_si_rompe_la_pagina_lo_dice(archivio, tmp_path):
    import time

    from officina.errori import ErroreOfficina
    from officina.importazione.motore import InSottofondo

    class MotoreCheSiRompe:
        def __init__(self, cosa):
            self.cosa = cosa

        def esegui(self):
            raise self.cosa

        def ferma(self):
            pass

    def aspetta(lavoro):
        for _ in range(200):
            if not lavoro.sta_lavorando:
                return
            time.sleep(0.01)
        raise AssertionError("il filo non ha finito")

    previsto = InSottofondo(MotoreCheSiRompe(
        ErroreOfficina("Il disco esterno non c'è più.")))
    previsto.parti()
    aspetta(previsto)
    assert previsto.guasto == "Il disco esterno non c'è più."

    imprevisto = InSottofondo(MotoreCheSiRompe(
        KeyError(r"C:\Users\qualcuno\Foto\vacanza-2019")))
    imprevisto.parti()
    aspetta(imprevisto)
    assert imprevisto.guasto, "il filo si è rotto e non l'ha detto a nessuno"
    assert "qualcuno" not in imprevisto.guasto
    assert "vacanza" not in imprevisto.guasto
    assert "Dettaglio tecnico: KeyError" in imprevisto.guasto


def test_I_due_clic_sullo_stesso_tasto_non_fanno_due_importazioni(archivio):
    import threading
    import time

    from officina.importazione.motore import InSottofondo

    class MotoreLento:
        def __init__(self):
            self.giri = 0
            self.mio = threading.Lock()

        def esegui(self):
            with self.mio:
                self.giri += 1
            time.sleep(0.25)

        def ferma(self):
            pass

    motore = MotoreLento()
    lavoro = InSottofondo(motore)
    pronti = threading.Barrier(20)

    def prova():
        pronti.wait()
        lavoro.parti()

    fili = [threading.Thread(target=prova) for _ in range(20)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join()
    lavoro.ferma()
    time.sleep(0.4)

    assert motore.giri == 1, f"sono partite {motore.giri} importazioni insieme"


def test_I_una_live_rimasta_staccata_si_riattacca_alla_sua_foto(archivio):
    from officina.importazione.motore import riattacca_i_live

    with archivio.scrittura() as c:
        foto_scatto = c.execute(
            "INSERT INTO scatti (genere, creato_il) "
            "VALUES ('foto', '2026-01-01T00:00:00')").lastrowid
        foto_id = c.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, data_locale, "
            "scatto_id, ruolo, aggiunto_il) VALUES ('fotolive', 900000, "
            "'immagine', '2026-05-04T12:00:01', ?, 'principale', "
            "'2026-01-01T00:00:00')", (foto_scatto,)).lastrowid
        c.execute("INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
                  "VALUES (?, 'C:/foto/IMG_7001.HEIC', 'IMG_7001.HEIC', 1, "
                  "'2026-01-01T00:00:00')", (foto_id,))
        video_scatto = c.execute(
            "INSERT INTO scatti (genere, creato_il, durata_ms) "
            "VALUES ('video', '2026-01-01T00:00:00', 2400)").lastrowid
        video_id = c.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, istante_utc, "
            "data_locale, durata_ms, scatto_id, ruolo, aggiunto_il) VALUES "
            "('videolive', 3000000, 'video', '2026-05-04T10:00:00Z', "
            "'2026-05-04T12:00:00', 2400, ?, 'principale', '2026-01-01T00:00:00')",
            (video_scatto,)).lastrowid
        c.execute("INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
                  "VALUES (?, 'C:/foto/IMG_7001.MOV', 'IMG_7001.MOV', 1, "
                  "'2026-01-01T00:00:00')", (video_id,))
        assert riattacca_i_live(c) == 1
    with archivio.lettura() as c:
        assert uno(c, "SELECT genere FROM scatti WHERE id = ?", foto_scatto)["genere"] == "live"
        assert uno(c, "SELECT ruolo, scatto_id FROM file_media WHERE id = ?",
                   video_id)["scatto_id"] == foto_scatto
        assert uno(c, "SELECT count(*) AS q FROM scatti WHERE id = ?", video_scatto)["q"] == 0


def test_date_ai_bordi_del_calendario_non_rompono_l_abbinamento():
    from officina.importazione import motore
    assert motore._istante_meno("0001-01-01T00:00:00Z", 10) == "0001-01-01T00:00:00Z"
    assert motore._istante_piu("9999-12-31T23:59:59Z", 10) == "9999-12-31T23:59:59Z"
