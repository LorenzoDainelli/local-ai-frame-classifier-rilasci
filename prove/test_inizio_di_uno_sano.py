from __future__ import annotations

from pathlib import Path

import pytest

from officina.importazione import impronta as impronta_file
from officina.modello import inizi, segnalazioni
from prove.test_impronte_giusto import _cliente, _foto


def _file_di(archivio, scatto_id: int) -> dict:
    with archivio.lettura() as connessione:
        return dict(connessione.execute(
            "SELECT f.id AS file_id, p.id AS percorso_id, p.percorso, p.nome "
            "FROM file_media f JOIN percorsi p ON p.file_id = f.id WHERE f.scatto_id = ? "
            "AND f.ruolo = 'principale' AND p.presente = 1 LIMIT 1",
            (scatto_id,)).fetchone())


def _metti(archivio, scatto_id: int, posto: Path) -> None:
    dove = _file_di(archivio, scatto_id)
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto_id,))
        connessione.execute("UPDATE file_media SET impronta = ?, dimensione = ? "
                            "WHERE id = ?",
                            (impronta_file.del_file(posto), posto.stat().st_size,
                             dove["file_id"]))
        connessione.execute("UPDATE percorsi SET percorso = ?, nome = ?, presente = 1 "
                            "WHERE id = ?", (str(posto), posto.name, dove["percorso_id"]))
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                           dettaglio="immagine_rovinata")


@pytest.fixture
def coppia(archivio_misurabile, tmp_path):
    rotto, sano = _foto(archivio_misurabile, 2)
    dati = Path(_file_di(archivio_misurabile, sano)["percorso"]).read_bytes()
    nome = _file_di(archivio_misurabile, sano)["nome"]
    posto = tmp_path / "rotti" / nome
    posto.parent.mkdir()
    posto.write_bytes(dati[: len(dati) // 2])
    return archivio_misurabile, rotto, sano, posto, dati


def _trova(archivio, scatto_id: int) -> int | None:
    inizi._ricordati.clear()
    with archivio.lettura() as connessione:
        return inizi.sano_che_lo_contiene(connessione, scatto_id)


def test_il_rotto_che_e_l_inizio_di_uno_sano_lo_trova(coppia):
    archivio, rotto, sano, posto, _ = coppia
    _metti(archivio, rotto, posto)
    assert _trova(archivio, rotto) == sano


def test_un_solo_byte_diverso_non_basta(coppia):
    archivio, rotto, sano, posto, dati = coppia
    pezzo = bytearray(dati[: len(dati) // 2])
    pezzo[-1] ^= 0xFF
    posto.write_bytes(bytes(pezzo))
    _metti(archivio, rotto, posto)
    assert _trova(archivio, rotto) is None


def test_con_altro_nome_e_altra_data_non_lo_cerca(coppia):
    archivio, rotto, sano, posto, _ = coppia
    altro = posto.with_name("altro" + posto.suffix)
    posto.rename(altro)
    _metti(archivio, rotto, altro)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET data_locale = '1999-01-01T00:00:00', "
                            "giorno = '1999-01-01' "
                            "WHERE id = ?", (rotto,))
    assert _trova(archivio, rotto) is None


def test_con_la_stessa_data_lo_trova_anche_con_altro_nome(coppia):
    archivio, rotto, sano, posto, _ = coppia
    altro = posto.with_name("altro" + posto.suffix)
    posto.rename(altro)
    _metti(archivio, rotto, altro)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET data_locale = '2001-02-03T04:05:06', "
                            "giorno = '2001-02-03' "
                            "WHERE id IN (?, ?)", (rotto, sano))
    assert _trova(archivio, rotto) == sano


def test_il_sano_senza_impronte_non_vale(coppia):
    archivio, rotto, sano, posto, _ = coppia
    _metti(archivio, rotto, posto)
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (sano,))
    assert _trova(archivio, rotto) is None


def test_le_pagine_lo_dicono_con_il_collegamento_al_sano(coppia):
    archivio, rotto, sano, posto, _ = coppia
    _metti(archivio, rotto, posto)
    inizi._ricordati.clear()
    cliente = _cliente()
    pagina = cliente.get("/intelligenza/perche-mancano").text
    assert f'data-pm-inizio="{sano}"' in pagina
    assert f'href="/scatto/{sano}">Guarda quello sano' in pagina
    sistemare = cliente.get("/sistemare").text
    assert f'data-inizio-di="{sano}"' in sistemare


def _gemelli(archivio, rotto: int, sano: int, **cambi) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET data_locale = '2001-02-03T04:05:06', "
                            "giorno = '2001-02-03' WHERE id IN (?, ?)", (rotto, sano))
        connessione.execute("UPDATE file_media SET larghezza = 3000, altezza = 4000, "
                            "marca = 'Apple', modello = 'iPhone' WHERE scatto_id IN (?, ?)",
                            (rotto, sano))
        for chiave, valore in cambi.items():
            connessione.execute(f"UPDATE file_media SET {chiave} = ? WHERE scatto_id = ?",
                                (valore, rotto))


def _gemello(archivio, scatto_id: int) -> int | None:
    with archivio.lettura() as connessione:
        return inizi.gemello_probabile(connessione, scatto_id)


@pytest.fixture
def rovinato(coppia):
    archivio, rotto, sano, posto, dati = coppia
    pezzo = bytearray(dati[: len(dati) // 2])
    pezzo[-1] ^= 0xFF
    posto.write_bytes(bytes(pezzo))
    _metti(archivio, rotto, posto)
    return archivio, rotto, sano


def test_un_rovinato_con_stessa_ora_misura_e_telefono_e_un_probabile_doppione(rovinato):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano)
    assert _trova(archivio, rotto) is None
    assert _gemello(archivio, rotto) == sano


def test_anche_girato_e_lo_stesso(rovinato):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano, larghezza=4000, altezza=3000)
    assert _gemello(archivio, rotto) == sano


@pytest.mark.parametrize("cambi", [{"larghezza": 2999}, {"modello": "altro"}])
def test_misura_o_telefono_diversi_non_sono_doppioni(rovinato, cambi):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano, **cambi)
    assert _gemello(archivio, rotto) is None


def test_un_altra_ora_non_e_un_doppione(rovinato):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET data_locale = '2001-02-03T04:05:07' "
                            "WHERE id = ?", (sano,))
    assert _gemello(archivio, rotto) is None


def test_se_i_gemelli_sono_due_non_ne_sceglie_uno(rovinato):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano)
    with archivio.scrittura() as connessione:
        terzo = connessione.execute(
            "SELECT s.id FROM scatti s WHERE s.id NOT IN (?, ?) AND s.genere = 'foto' "
            "AND s.fuori_archivio = 0 AND EXISTS (SELECT 1 FROM impronte i "
            "WHERE i.scatto_id = s.id) LIMIT 1", (rotto, sano)).fetchone()[0]
        connessione.execute("UPDATE scatti SET data_locale = '2001-02-03T04:05:06', "
                            "giorno = '2001-02-03' WHERE id = ?", (terzo,))
        connessione.execute("UPDATE file_media SET larghezza = 3000, altezza = 4000, "
                            "marca = 'Apple', modello = 'iPhone' WHERE scatto_id = ?",
                            (terzo,))
    assert _gemello(archivio, rotto) is None


def test_le_pagine_dicono_il_probabile_doppione(rovinato):
    archivio, rotto, sano = rovinato
    _gemelli(archivio, rotto, sano)
    inizi._ricordati.clear()
    cliente = _cliente()
    pagina = cliente.get("/intelligenza/perche-mancano").text
    assert f'data-pm-gemello="{sano}"' in pagina
    assert "Probabilmente è un doppione rovinato" in pagina
    assert f'data-gemello-di="{sano}"' in cliente.get("/sistemare").text
