from __future__ import annotations

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
