import threading

from officina.archivio import accesso, migrazioni


def test_chiudere_mentre_si_apre_aspetta_la_fine_dell_apertura(tmp_path, monkeypatch):
    with monkeypatch.context() as m:
        m.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
        archivio = accesso.Archivio(accesso.posizione("finto"))
        dentro = threading.Event()
        via = threading.Event()
        vero = migrazioni.aggiorna

        def lento(connessione):
            dentro.set()
            via.wait(5)
            return vero(connessione)

        m.setattr(migrazioni, "aggiorna", lento)
        errori = []

        def apri():
            try:
                archivio.apri()
            except Exception as errore:
                errori.append(errore)

        filo = threading.Thread(target=apri)
        filo.start()
        assert dentro.wait(5)
        chiusura = threading.Thread(target=archivio.chiudi, kwargs={"con_copia": False})
        chiusura.start()
        chiusura.join(0.3)
        assert chiusura.is_alive()
        via.set()
        filo.join(5)
        chiusura.join(5)
        assert errori == []
        assert not archivio.e_aperto


def test_scrivere_mentre_si_apre_aspetta_la_fine_degli_aggiornamenti(tmp_path, monkeypatch):
    with monkeypatch.context() as m:
        m.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
        archivio = accesso.Archivio(accesso.posizione("finto"))
        dentro = threading.Event()
        via = threading.Event()
        vero = migrazioni.aggiorna

        def lento(connessione):
            dentro.set()
            via.wait(5)
            return vero(connessione)

        m.setattr(migrazioni, "aggiorna", lento)
        filo = threading.Thread(target=archivio.apri)
        filo.start()
        assert dentro.wait(5)
        visto = []

        def scrivi():
            try:
                with archivio.scrittura() as connessione:
                    visto.append(connessione.execute("PRAGMA user_version").fetchone()[0])
            except Exception as errore:
                visto.append(errore)

        scrittore = threading.Thread(target=scrivi)
        scrittore.start()
        scrittore.join(0.3)
        assert scrittore.is_alive()
        via.set()
        filo.join(5)
        scrittore.join(5)
        assert len(visto) == 1 and not isinstance(visto[0], Exception)
        assert not migrazioni.da_applicare(archivio.connessione)
        archivio.chiudi(con_copia=False)
