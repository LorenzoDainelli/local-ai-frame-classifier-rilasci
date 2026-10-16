from __future__ import annotations

import json
import secrets
import time

import pytest

from prove.conftest import tutto_pronto_per_il_telefono

from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.telefono import cifratura, costruzione, formato, lettore

PAROLA = "tre parole che ricordi"


@pytest.fixture
def telefono(archivio_pieno):
    tutto_pronto_per_il_telefono(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        return telefoni.crea(connessione, "iPhone", "ios")


def _fai(archivio, telefono_id, dove) -> costruzione.Esito:
    return costruzione.Travaso(archivio, telefono_id, dove, PAROLA).esegui()


def _posti(dove) -> set[str]:
    return {file.relative_to(dove).as_posix() for file in dove.rglob("*") if file.is_file()}


def _ritocca_la_carta(dove, **cambi) -> None:
    carta = json.loads((dove / formato.CARTA).read_text(encoding="utf-8"))
    carta.update(cambi)
    (dove / formato.CARTA).write_text(json.dumps(carta), encoding="utf-8")


def test_sul_telefono_non_si_leggono_ne_nomi_ne_date(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo

    nomi = {riga["nome"] for riga in tutti(archivio_pieno.connessione,
                                           "SELECT nome FROM percorsi")}
    posti = _posti(dove) - {formato.CARTA, formato.DATI}
    assert posti
    for posto in posti:
        assert formato.e_a_caso(posto), posto
        assert not any(nome and nome in posto for nome in nomi)
    for file in dove.rglob("*"):
        if file.is_file() and file.name != formato.CARTA:
            assert b"SQLite format" not in file.read_bytes()[:64]
    carta = formato.Carta.leggi(dove)
    assert all("/" not in nota and "." not in nota.rstrip(".") for nota in carta.note)


def test_i_nomi_a_caso_restano_gli_stessi_da_un_travaso_all_altro(archivio_pieno, telefono,
                                                                  tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    prima = _posti(dove)
    secondo = _fai(archivio_pieno, telefono, dove)
    assert secondo.completo
    assert secondo.scritti == 1
    assert secondo.tolti == 0
    assert _posti(dove) == prima


def test_un_pacchetto_della_versione_di_prima_si_riscrive_tutto(archivio_pieno, telefono,
                                                                tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    with archivio_pieno.scrittura() as connessione:
        righe = tutti(connessione, "SELECT posto FROM pacchetto_file WHERE telefono_id = ? "
                                   "AND posto <> ?", telefono, formato.DATI)
        for numero, riga in enumerate(righe):
            vecchio = f"foto/2019/07/IMG_{numero:04d}.JPG"
            (dove / vecchio).parent.mkdir(parents=True, exist_ok=True)
            formato.dentro(dove, riga["posto"]).rename(dove / vecchio)
            connessione.execute("UPDATE pacchetto_file SET posto = ? WHERE telefono_id = ? "
                                "AND posto = ?", (vecchio, telefono, riga["posto"]))
    _ritocca_la_carta(dove, versione_formato=1)

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo
    assert esito.scritti == len(righe) + 1
    assert esito.tolti == len(righe)
    assert not (dove / "foto" / "2019").exists()
    assert all(formato.e_a_caso(posto) for posto in _posti(dove) - {formato.CARTA, formato.DATI})
    assert formato.Carta.leggi(dove).versione_formato == formato.VERSIONE_FORMATO
    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto


def test_un_pacchetto_vecchio_tiene_i_suoi_conti_della_password(archivio_pieno, telefono,
                                                                tmp_path, monkeypatch):
    dove = tmp_path / "Visore-iPhone"
    with monkeypatch.context() as finto:
        finto.setattr(cifratura, "COSTO", 2 ** 15)
        _fai(archivio_pieno, telefono, dove)
    assert formato.Carta.leggi(dove).n == 2 ** 15

    assert _fai(archivio_pieno, telefono, dove).completo
    assert formato.Carta.leggi(dove).n == 2 ** 15
    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto


def test_un_pacchetto_nuovo_usa_i_conti_piu_cari(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    carta = formato.Carta.leggi(dove)
    assert (carta.n, carta.r, carta.p) == (2 ** 16, 8, 1)
    assert carta.versione_formato == 2


def test_due_file_scambiati_non_passano_la_verifica(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    miniature = sorted(file for file in (dove / formato.MINI).rglob("*") if file.is_file())
    assert len(miniature) >= 2
    uno, due = miniature[0].read_bytes(), miniature[1].read_bytes()
    miniature[0].write_bytes(due)
    miniature[1].write_bytes(uno)
    with lettore.apri(dove, PAROLA) as pacchetto:
        assert not pacchetto.verifica().tutto_a_posto


def test_un_file_della_versione_di_prima_non_si_accetta(tmp_path):
    sale = cifratura.sale_nuovo()
    chiave = cifratura.Chiave.dalla_password(PAROLA, sale, 2 ** 15)
    dati = b"un file finto della versione uno"
    prefisso = secrets.token_bytes(cifratura.PREFISSO)
    vecchio = (cifratura._intestazione(prefisso, len(dati), cifratura.VERSIONE)
               + chiave._cifratore.encrypt(cifratura._nonce(prefisso, 0), dati,
                                           cifratura._accompagnamento(0, True, len(dati))))
    dove = tmp_path / "vecchio.bin"
    dove.write_bytes(vecchio)
    with pytest.raises(cifratura.PacchettoRovinato) as guaio:
        chiave.leggi_tutto(dove, "mini/ab/" + "ab" * 16)
    assert "precedente" in guaio.value.messaggio


@pytest.mark.parametrize("costo", [2 ** 20, 2 ** 30, 1024, 3])
def test_una_carta_che_chiede_conti_strani_si_ferma_subito(tmp_path, costo):
    sale = cifratura.sale_nuovo()
    chiave = cifratura.Chiave.dalla_password(PAROLA, sale)
    formato.Carta(telefono="t", archivio="x", sale=sale.hex(), prova=chiave.prova()).scrivi(tmp_path)
    _ritocca_la_carta(tmp_path, n=costo)
    inizio = time.monotonic()
    with pytest.raises(ErroreOfficina) as guaio:
        formato.Carta.leggi(tmp_path).chiave(PAROLA)
    assert guaio.value.codice == "parametri_sconosciuti"
    assert time.monotonic() - inizio < 1


@pytest.mark.parametrize("cambi", [{"n": "65536"}, {"sale": 5}, {"note": "non una lista"},
                                   {"n": 2.5}, {"sale": "non esadecimale"}])
def test_una_carta_coi_tipi_sbagliati_e_rovinata(tmp_path, cambi):
    sale = cifratura.sale_nuovo()
    chiave = cifratura.Chiave.dalla_password(PAROLA, sale)
    formato.Carta(telefono="t", archivio="x", sale=sale.hex(), prova=chiave.prova()).scrivi(tmp_path)
    _ritocca_la_carta(tmp_path, **cambi)
    with pytest.raises(ErroreOfficina) as guaio:
        formato.Carta.leggi(tmp_path).chiave(PAROLA)
    assert guaio.value.codice == "carta_rovinata"


@pytest.mark.parametrize("posto", ["../fuori.db", "foto/../../fuori.db", "mini/../../../fuori"])
def test_un_percorso_non_esce_dal_pacchetto(tmp_path, posto):
    with pytest.raises(ErroreOfficina) as guaio:
        formato.dentro(tmp_path, posto)
    assert guaio.value.codice == "percorso_sospetto"


def test_un_percorso_assoluto_resta_dentro_il_pacchetto(tmp_path):
    dove = formato.dentro(tmp_path, "/etc/passwd")
    assert tmp_path.resolve() in dove.parents
