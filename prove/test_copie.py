from __future__ import annotations

from pathlib import Path

import pytest

from officina.archivio import copie
from officina.errori import DatabaseIncoerente
from officina.modello import nodi


def test_una_copia_nasce_gia_verificata(archivio):
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_1")
    copia = archivio.copia_adesso("prova")
    assert copia.percorso.exists()
    copie.verifica(copia.percorso)


def test_una_copia_rovinata_viene_riconosciuta(archivio, tmp_path):
    copia = archivio.copia_adesso("prova")
    rovinata = tmp_path / "rotta.sqlite"
    rovinata.write_bytes(copia.percorso.read_bytes()[:200] + b"\x00" * 400)
    with pytest.raises(DatabaseIncoerente):
        copie.verifica(rovinata)


def test_se_ne_tengono_trenta(archivio):
    for _ in range(35):
        archivio.copia_adesso("prova")
    assert len(archivio.copie_esistenti()) == copie.QUANTE_SE_NE_TENGONO


def test_il_ripristino_riporta_indietro_e_si_annulla(archivio, tmp_path, monkeypatch):
    from officina.archivio import accesso

    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    copia = archivio.copia_adesso("punto_di_ripristino")

    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_dopo")
    assert len(nodi.elenco(archivio.connessione)) == 2

    dove = archivio.dove
    accesso.chiudi(con_copia=False)
    copie.ripristina(dove, copia.nome)

    riaperto = accesso.apri("finto")
    nomi = [n["nome"] for n in nodi.elenco(riaperto.connessione)]
    assert nomi == ["nodo_prima"]

    assert any(c.motivo == "prima_del_ripristino" for c in riaperto.copie_esistenti())


def test_un_ripristino_che_si_interrompe_lascia_l_archivio_com_era(archivio, monkeypatch):
    from officina.archivio import accesso

    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    copia = archivio.copia_adesso("punto_di_ripristino")
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_dopo")
    dove = archivio.dove
    accesso.chiudi(con_copia=False)

    def si_spegne(sorgente, destinazione, **_):
        with open(sorgente, "rb") as dentro, open(destinazione, "wb") as fuori:
            fuori.write(dentro.read(4096))
        raise OSError("il computer si è spento")

    with monkeypatch.context() as cambio:
        cambio.setattr(copie.shutil, "copy2", si_spegne)
        with pytest.raises(OSError):
            copie.ripristina(dove, copia.nome)

    copie.verifica(dove.database)
    assert not list(dove.database.parent.glob("*" + copie.IN_ARRIVO + "*"))
    riaperto = accesso.apri("finto")
    assert sorted(n["nome"] for n in nodi.elenco(riaperto.connessione)) == [
        "nodo_dopo", "nodo_prima"]


class _SiSpegneACopiaIniziata:

    def backup(self, dentro):
        dentro.execute("CREATE TABLE mezza (a)")
        dentro.commit()
        raise OSError("il disco si è riempito")


def test_una_copia_che_si_interrompe_non_compare_fra_le_copie(archivio):
    prima = [c.nome for c in archivio.copie_esistenti()]
    with pytest.raises(OSError):
        copie.fai_copia(_SiSpegneACopiaIniziata(), archivio.dove, "prova")
    assert [c.nome for c in archivio.copie_esistenti()] == prima
    assert sorted(f.name for f in archivio.dove.copie.iterdir()) == sorted(prima)


def test_una_copia_che_non_si_rilegge_non_compare_fra_le_copie(archivio, monkeypatch):
    prima = [c.nome for c in archivio.copie_esistenti()]

    def rovinata(percorso):
        raise DatabaseIncoerente(f"La copia {percorso.name} non è integra.")

    with monkeypatch.context() as cambio:
        cambio.setattr(copie, "verifica", rovinata)
        with pytest.raises(DatabaseIncoerente):
            archivio.copia_adesso("prova")
    assert [c.nome for c in archivio.copie_esistenti()] == prima
    assert sorted(f.name for f in archivio.dove.copie.iterdir()) == sorted(prima)


def test_i_resti_di_una_copia_interrotta_si_tolgono_alla_prossima_apertura(archivio):
    from officina.archivio import accesso

    dove = archivio.dove
    copia = archivio.copia_adesso("prova")
    accesso.chiudi(con_copia=False)
    resti = [dove.copie / ("20260101-000000.chiusura.sqlite" + copie.IN_ARRIVO),
             dove.copie / ("20260101-000000.chiusura.sqlite" + copie.IN_ARRIVO + "-journal"),
             Path(str(dove.database) + copie.IN_ARRIVO)]
    for resto in resti:
        resto.write_bytes(b"a meta" * 1000)
    accesso.apri("finto")
    assert not any(resto.exists() for resto in resti)
    assert copia.percorso.exists()
    copie.verifica(copia.percorso)


def test_chiudere_senza_cambiare_niente_non_rifa_la_copia(tmp_path, monkeypatch):
    from officina.archivio import accesso, copie

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    accesso.apri("finto")
    accesso.chiudi()
    dove = accesso.apri("finto").dove
    prima = len(copie.elenco(dove))
    accesso.aperto().salva_stato("ultimo_filtro", {"q": "mare"})
    accesso.chiudi()
    assert len(copie.elenco(dove)) == prima

    accesso.apri("finto").salva_stato("guida_fatta", True)
    accesso.chiudi()
    assert len(copie.elenco(dove)) == prima + 1


def test_la_copia_in_sottofondo_aspetta_che_sia_fermo_e_ne_tiene_una(archivio):
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_1")
    assert archivio.copia_se_fermo() is False
    assert archivio.copia_se_fermo() is True
    assert archivio.copia_se_fermo() is False
    assert not archivio._serve_la_copia()
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_2")
    archivio.copia_se_fermo()
    assert archivio.copia_se_fermo() is True
    fatte = [c for c in archivio.copie_esistenti() if c.motivo == "in_sottofondo"]
    assert len(fatte) == 1


def test_la_copia_prenotata_torna_alla_prossima_apertura(archivio):
    from officina.archivio import accesso

    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    copia = archivio.copia_adesso("manuale")
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_dopo")

    copie.prenota(archivio.dove, copia.nome)
    for _ in range(35):
        archivio.copia_adesso("prova")
    assert copie.prenotata(archivio.dove) == copia.nome
    assert copia.percorso.exists()

    accesso.chiudi(con_copia=False)
    riaperto = accesso.apri("finto")
    assert [n["nome"] for n in nodi.elenco(riaperto.connessione)] == ["nodo_prima"]
    assert copie.prenotata(riaperto.dove) is None
    assert any(c.motivo == "prima_del_ripristino" for c in riaperto.copie_esistenti())


def test_non_si_prenota_un_file_qualsiasi(archivio):
    with pytest.raises(DatabaseIncoerente):
        copie.prenota(archivio.dove, "../../reale.sqlite")
    assert copie.prenotata(archivio.dove) is None


def test_lascia_stare_disdice(archivio):
    copia = archivio.copia_adesso("manuale")
    copie.prenota(archivio.dove, copia.nome)
    copie.disdici(archivio.dove)
    assert copie.prenotata(archivio.dove) is None


def test_prenotazione_rovinata_non_blocca(archivio):
    archivio.dove.copie.mkdir(parents=True, exist_ok=True)
    (archivio.dove.copie / copie.PRENOTAZIONE).write_bytes(b"\xff\xfe\x00rotto")
    assert copie.prenotata(archivio.dove) is None


def _scrivi_da_un_altro_filo(archivio, nome: str) -> bool:
    import threading

    fatto = threading.Event()

    def scrivi():
        with archivio.scrittura() as connessione:
            nodi.crea(connessione, nome)
        fatto.set()

    threading.Thread(target=scrivi, daemon=True).start()
    return fatto.wait(10)


@pytest.mark.parametrize("come", ["in_sottofondo", "adesso"])
def test_mentre_si_fa_la_copia_si_puo_scrivere(archivio, monkeypatch, come):
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    archivio.copia_se_fermo()
    vera = copie.verifica
    visto = {}

    def verifica(percorso):
        visto["chiuso"] = archivio._lucchetto._is_owned()
        visto["scritto"] = _scrivi_da_un_altro_filo(archivio, "nodo_durante")
        vera(percorso)

    with monkeypatch.context() as cambio:
        cambio.setattr(copie, "verifica", verifica)
        if come == "adesso":
            copia = archivio.copia_adesso("prova")
        else:
            assert archivio.copia_se_fermo() is True
            copia = max(archivio.copie_esistenti(), key=lambda c: c.nato_il)
    assert visto == {"chiuso": False, "scritto": True}
    import sqlite3

    dentro = sqlite3.connect(copia.percorso)
    try:
        nomi = [r[0] for r in dentro.execute("SELECT nome FROM nodi ORDER BY nome")]
    finally:
        dentro.close()
    assert nomi == ["nodo_prima"]


def test_quello_scritto_durante_la_copia_vuole_un_altra_copia(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    archivio.copia_se_fermo()
    vera = copie.verifica

    def verifica(percorso):
        assert _scrivi_da_un_altro_filo(archivio, "nodo_durante")
        vera(percorso)

    with monkeypatch.context() as cambio:
        cambio.setattr(copie, "verifica", verifica)
        assert archivio.copia_se_fermo() is True
    assert archivio._serve_la_copia()
    archivio.copia_se_fermo()
    assert archivio.copia_se_fermo() is True
    assert not archivio._serve_la_copia()


def test_chiudere_aspetta_la_copia_in_sottofondo(archivio, monkeypatch):
    import threading

    from officina.archivio import accesso

    with archivio.scrittura() as connessione:
        nodi.crea(connessione, "nodo_prima")
    archivio.copia_se_fermo()
    vera = copie.verifica
    partita, via = threading.Event(), threading.Event()
    esiti = {}

    def verifica(percorso):
        if percorso.name.endswith(copie.IN_ARRIVO) and ".in_sottofondo." in percorso.name:
            partita.set()
            via.wait(10)
        vera(percorso)

    def copia():
        esiti["copia"] = archivio.copia_se_fermo()

    def chiudi():
        accesso.chiudi()
        esiti["chiuso"] = True

    with monkeypatch.context() as cambio:
        cambio.setattr(copie, "verifica", verifica)
        filo_della_copia = threading.Thread(target=copia, daemon=True)
        filo_della_copia.start()
        assert partita.wait(10)
        filo_della_chiusura = threading.Thread(target=chiudi, daemon=True)
        filo_della_chiusura.start()
        filo_della_chiusura.join(0.5)
        assert "chiuso" not in esiti
        via.set()
        filo_della_copia.join(10)
        filo_della_chiusura.join(10)
    assert esiti == {"copia": True, "chiuso": True}
    assert not archivio.e_aperto
    assert any(c.motivo == "in_sottofondo" for c in copie.elenco(archivio.dove))
