from __future__ import annotations

from pathlib import Path

import pytest

from officina.importazione import impronta as impronta_file, raccolta, storico


@pytest.fixture
def mandata(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        return storico.mandate(connessione)[0]


def _la_prima_copia(cartella: Path) -> Path:
    return sorted(p for p in cartella.iterdir() if p.is_file())[0]


def _riga(sorgente: Path, nome: str) -> dict:
    return {"nome": nome, "percorso": str(sorgente), "dimensione": sorgente.stat().st_size,
            "impronta": impronta_file.del_file(sorgente)}


def _raccogli(archivio, mandata, dove):
    with archivio.lettura() as connessione:
        return raccolta.raccogli(connessione, mandata.id, mandata.come_si_chiama, dove)


def _prepara(archivio, mandata, dove):
    with archivio.lettura() as connessione:
        return raccolta.prepara(connessione, mandata.id, mandata.come_si_chiama, dove)


def test_un_file_diverso_di_altra_misura_non_viene_sovrascritto(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    primo = _raccogli(archivio_pieno, mandata, dove)
    cartella = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    vittima = _la_prima_copia(cartella)
    vittima.write_bytes(b"un altro file, di un'altra misura")
    prima = len(list(cartella.iterdir()))

    secondo = _raccogli(archivio_pieno, mandata, dove)

    assert vittima.read_bytes() == b"un altro file, di un'altra misura"
    assert secondo.copiati == 1
    assert secondo.saltati == primo.copiati - 1
    assert len(list(cartella.iterdir())) == prima + 1


def test_un_file_diverso_della_stessa_misura_non_e_gia_c_era(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    primo = _raccogli(archivio_pieno, mandata, dove)
    cartella = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    vittima = _la_prima_copia(cartella)
    misura = vittima.stat().st_size
    vittima.write_bytes(b"\x07" * misura)
    prima = {p.name for p in cartella.iterdir()}

    secondo = _raccogli(archivio_pieno, mandata, dove)

    assert vittima.read_bytes() == b"\x07" * misura
    assert secondo.copiati == 1
    assert secondo.saltati == primo.copiati - 1
    nuovi = {p.name for p in cartella.iterdir()} - prima
    assert len(nuovi) == 1
    nuovo = cartella / nuovi.pop()
    assert nuovo.stat().st_size == misura
    assert nuovo.read_bytes() != b"\x07" * misura
    assert nuovo.suffix == vittima.suffix


def test_rifare_la_raccolta_dopo_un_nome_occupato_non_moltiplica_i_file(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    primo = _raccogli(archivio_pieno, mandata, dove)
    cartella = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    _la_prima_copia(cartella).write_bytes(b"occupato")

    _raccogli(archivio_pieno, mandata, dove)
    quanti = len(list(cartella.iterdir()))
    terzo = _raccogli(archivio_pieno, mandata, dove)

    assert terzo.copiati == 0
    assert terzo.saltati == primo.copiati
    assert len(list(cartella.iterdir())) == quanti
    assert not list(cartella.glob("*.parziale"))


def test_il_piano_vede_il_nome_occupato_da_un_altro_file(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    _raccogli(archivio_pieno, mandata, dove)
    cartella = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    misura = _la_prima_copia(cartella).stat().st_size
    _la_prima_copia(cartella).write_bytes(b"\x07" * misura)

    piano = _prepara(archivio_pieno, mandata, dove)
    assert piano.da_copiare == 1

    _raccogli(archivio_pieno, mandata, dove)
    assert _prepara(archivio_pieno, mandata, dove).da_copiare == 0


def test_una_copia_identica_gia_presente_si_riconosce_dal_contenuto(archivio_pieno, mandata, tmp_path):
    dove = tmp_path / "raccolta"
    primo = _raccogli(archivio_pieno, mandata, dove)
    cartella = dove / raccolta.nome_cartella(mandata.id, mandata.come_si_chiama)
    prima = sorted(p.name for p in cartella.iterdir())
    secondo = _raccogli(archivio_pieno, mandata, dove)
    assert secondo.copiati == 0 and secondo.saltati == primo.copiati
    assert sorted(p.name for p in cartella.iterdir()) == prima


def test_se_l_originale_e_cambiato_dopo_la_copia_non_si_rifa_ogni_volta(tmp_path):
    sorgente = tmp_path / "sorgente.jpg"
    sorgente.write_bytes(b"contenuto cambiato dopo l'importazione")
    riga = _riga(sorgente, "foto.jpg")
    riga["impronta"] = "0" * 64
    riga["dimensione"] = 5
    arrivo = tmp_path / "arrivo" / "foto.jpg"
    arrivo.parent.mkdir()
    arrivo.write_bytes(sorgente.read_bytes())
    scelto, uguale = raccolta._dove_metterlo(arrivo, sorgente, riga)
    assert scelto == arrivo and uguale


def test_i_nomi_possibili_passano_al_segno_piu_lungo_se_quello_corto_e_occupato(tmp_path):
    sorgente = tmp_path / "s.jpg"
    sorgente.write_bytes(b"contenuto vero")
    riga = _riga(sorgente, "foto.jpg")
    arrivo = tmp_path / "foto.jpg"
    breve = tmp_path / f"foto-{riga['impronta'][:8]}.jpg"
    for occupato in (arrivo, breve):
        occupato.write_bytes(b"occupato")
    scelto, uguale = raccolta._dove_metterlo(arrivo, sorgente, riga)
    assert scelto == tmp_path / f"foto-{riga['impronta'][:16]}.jpg"
    assert not uguale
    assert arrivo.read_bytes() == b"occupato" and breve.read_bytes() == b"occupato"


def test_se_proprio_tutti_i_nomi_sono_presi_non_si_scrive_niente(tmp_path):
    sorgente = tmp_path / "s.jpg"
    sorgente.write_bytes(b"contenuto vero")
    riga = _riga(sorgente, "foto.jpg")
    arrivo = tmp_path / "foto.jpg"
    for candidato in raccolta._nomi_possibili(arrivo, riga["impronta"]):
        candidato.write_bytes(b"occupato")
    assert raccolta._dove_metterlo(arrivo, sorgente, riga) == (None, False)


def test_un_collegamento_al_posto_del_file_non_si_attraversa(tmp_path):
    sorgente = tmp_path / "s.jpg"
    sorgente.write_bytes(b"contenuto vero")
    riga = _riga(sorgente, "foto.jpg")
    bersaglio = tmp_path / "bersaglio.txt"
    bersaglio.write_bytes(b"da non toccare")
    arrivo = tmp_path / "foto.jpg"
    try:
        arrivo.symlink_to(tmp_path / "non_esiste.txt")
    except OSError:
        pytest.skip("i collegamenti non si possono fare qui")
    scelto, uguale = raccolta._dove_metterlo(arrivo, sorgente, riga)
    assert scelto != arrivo and not uguale
    assert bersaglio.read_bytes() == b"da non toccare"


def test_i_nomi_strani_non_escono_dalla_cartella():
    presi: dict[str, str] = {}
    for nome in ("..", ".", ""):
        scelto = raccolta._come_si_chiamera({"nome": nome, "impronta": "ab" * 32}, presi)
        assert scelto not in ("..", ".", "")
        assert "/" not in scelto and "\\" not in scelto
