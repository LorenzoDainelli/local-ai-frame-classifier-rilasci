from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from officina.archivio.database import tutti
from officina.impronte import motore
from officina.impronte.motore import Passata
from officina.programma import archivio_sicuro
from officina.sicuro import servizio as modulo
from officina.sicuro.dall_archivio import CHIUSO_ADESSO
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_sicuro_dall_archivio import _impronta, _jpeg, _Situazione
from prove.test_sicuro_servizio import ATTESA, LEGGERO, PAROLA, Casa, _finche

costo_leggero = servizio_di_prova.costo_leggero
QUANTE = 5


def _al_posto_di(archivio, quale: int, dati: bytes, percorso) -> int:
    with archivio.scrittura() as connessione:
        riga = connessione.execute(
            "SELECT id, scatto_id FROM file_media WHERE genere = 'immagine' "
            "AND ruolo = 'principale' AND scatto_id IS NOT NULL ORDER BY id "
            "LIMIT 1 OFFSET ?", (quale,)).fetchone()
        connessione.execute(
            "UPDATE file_media SET impronta = ?, dimensione = ?, formato = 'jpeg', "
            "miniatura = NULL WHERE id = ?", (_impronta(dati), len(dati), riga["id"]))
        connessione.execute("DELETE FROM percorsi WHERE file_id = ?", (riga["id"],))
        connessione.execute(
            "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
            "VALUES (?, ?, ?, 0, '2026-01-01T00:00:00')",
            (riga["id"], str(percorso), percorso.name))
    return riga["scatto_id"]


@pytest.fixture
def tante_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    base = tmp_path / "casa"
    base.mkdir()
    casa = Casa(base, ripara={"luoghi": lambda: []}, riparatore={"ogni": 0.05})
    dati = {f"s/foto{numero}.jpg": _jpeg(96 + numero * 8, 64, seme=numero + 2)
            for numero in range(QUANTE)}
    originali = {relativo: casa.metti(relativo, contenuto)
                 for relativo, contenuto in dati.items()}
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    scatti = []
    for quale, (relativo, originale) in enumerate(originali.items()):
        originale.unlink()
        scatti.append(_al_posto_di(archivio_pieno, quale, dati[relativo], originale))
    with archivio_pieno.scrittura() as connessione:
        segni = ",".join("?" * len(scatti))
        connessione.execute(
            f"UPDATE scatti SET fuori_archivio = 1 WHERE id NOT IN ({segni})", scatti)
        connessione.execute(f"DELETE FROM segnalazioni WHERE scatto_id IN ({segni})", scatti)
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    monkeypatch.setattr(modulo, "attuale", lambda: casa.archivio)
    yield SimpleNamespace(casa=casa, archivio=archivio_pieno, dati=dati, scatti=scatti,
                          cartella=tmp_path)
    casa.chiudi()


def _impronte(pronta) -> list[tuple]:
    with pronta.archivio.lettura() as connessione:
        colonne = [c[1] for c in connessione.execute("PRAGMA table_info(impronte)")]
        scelte = [c for c in colonne if c not in ("id", "calcolata_il")]
        return sorted(tuple(riga) for riga in tutti(
            connessione, f"SELECT {', '.join(scelte)} FROM impronte"))


def _passata(pronta, fili: int, cancella: bool = True):
    if cancella:
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("DELETE FROM impronte")
    passata = Passata(pronta.archivio, "disegnato", intensita=100)
    passata.fili = fili
    return passata, passata.esegui()


def _messe_da_parte(pronta) -> int:
    with pronta.archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT count(*) FROM segnalazioni WHERE risolta = 0").fetchone()[0]


def _quante_insieme(monkeypatch, prima=None) -> dict:
    insieme = {"ora": 0, "massimo": 0, "chiamate": 0}
    lucchetto = threading.Lock()
    vera = motore.lettura.copia_di_lavoro
    tutti_e_due = threading.Barrier(2, timeout=5)
    primo_pronto = threading.Event()

    def foto(*argomenti, **chiavi):
        with lucchetto:
            insieme["ora"] += 1
            insieme["chiamate"] += 1
            insieme["massimo"] = max(insieme["massimo"], insieme["ora"])
            chiamata = insieme["chiamate"]
        try:
            if chiamata <= 2:
                try:
                    tutti_e_due.wait()
                except threading.BrokenBarrierError:
                    pass
            if chiamata != 1:
                primo_pronto.wait(5)
            if prima is not None:
                prima(chiamata)
            if chiamata == 1:
                primo_pronto.set()
            return vera(*argomenti, **chiavi)
        finally:
            with lucchetto:
                insieme["ora"] -= 1

    monkeypatch.setattr(motore.lettura, "copia_di_lavoro", foto)
    return insieme


def test_con_piu_fili_le_foto_dall_archivio_si_leggono_insieme_e_sono_identiche(
        tante_nell_archivio, monkeypatch):
    pronta = tante_nell_archivio
    gia = _messe_da_parte(pronta)
    _, uno_solo = _passata(pronta, 1)
    attese = _impronte(pronta)
    assert uno_solo.fatti == QUANTE and uno_solo.saltati == 0 and attese
    insieme = _quante_insieme(monkeypatch)
    _, quattro = _passata(pronta, motore.FILI)
    assert quattro.fatti == QUANTE and quattro.saltati == 0
    assert insieme["massimo"] >= 2
    assert _impronte(pronta) == attese
    assert _messe_da_parte(pronta) == gia
    for contenuto in pronta.dati.values():
        _mai_in_chiaro(pronta.cartella, contenuto)


def test_se_l_archivio_si_chiude_mentre_leggono_insieme_si_fermano_tutte(
        tante_nell_archivio, monkeypatch):
    pronta = tante_nell_archivio
    gia = _messe_da_parte(pronta)
    _, _uno = _passata(pronta, 1)
    attese = _impronte(pronta)

    def chiude(chiamata: int) -> None:
        if chiamata == 1:
            assert pronta.casa.archivio.chiudi(ATTESA)

    vera = motore.lettura.copia_di_lavoro
    insieme = _quante_insieme(monkeypatch, chiude)
    passata, fatto = _passata(pronta, motore.FILI)
    assert insieme["massimo"] >= 2
    assert fatto.fatti == 0 and fatto.saltati == QUANTE
    assert fatto.motivi_saltati == {CHIUSO_ADESSO: QUANTE}
    assert fatto.messi_da_parte == 0 and _messe_da_parte(pronta) == gia
    assert _impronte(pronta) == [] and passata.quanti_mancano() == QUANTE
    monkeypatch.setattr(motore.lettura, "copia_di_lavoro", vera)
    pronta.casa.archivio.apri(PAROLA)
    _, di_nuovo = _passata(pronta, motore.FILI, cancella=False)
    assert di_nuovo.fatti == QUANTE and _impronte(pronta) == attese
    for contenuto in pronta.dati.values():
        _mai_in_chiaro(pronta.cartella, contenuto)


__all__ = ["costo_leggero"]
