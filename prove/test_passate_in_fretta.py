from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso


class Finto:

    def apri(self):
        pass

    def chiudi(self):
        pass

    def dove_gira(self):
        return "cpu"


def _riempi(archivio, quanti: int) -> None:
    quando = adesso()
    with archivio.scrittura() as c:
        c.execute("DELETE FROM impronte")
        c.execute("DELETE FROM scritte_lette")
        c.execute("DELETE FROM scatti")
        c.executemany(
            "INSERT INTO scatti (id, genere, origine_data, creato_il, istante_utc) "
            "VALUES (?, 'foto', 'assente', ?, ?)",
            [(n, quando, f"2020-01-01T00:{n // 60 % 60:02d}:{n % 60:02d}Z" if n % 7 else None)
             for n in range(1, quanti + 1)])


def _contato(spia: list[int], vero):
    def contato(connessione: sqlite3.Connection, *argomenti, **nominati):
        def conta() -> int:
            spia[0] += 1
            return 0

        connessione.set_progress_handler(conta, 100)
        try:
            return vero(connessione, *argomenti, **nominati)
        finally:
            connessione.set_progress_handler(None, 0)
    return contato


def _impronte(archivio, monkeypatch) -> tuple[int, list[int]]:
    from officina.impronte import motore

    spia = [0]
    fatti: list[int] = []

    def fai(self, descrittore, pronto):
        with archivio.scrittura() as c:
            c.executemany(
                "INSERT INTO impronte (scatto_id, descrittore, versione, inquadratura, metodo, "
                "fotogramma, dimensione, valori, calcolata_il) "
                "VALUES (?, ?, ?, 'intera', 'finto', 0, 1, x'00', ?)",
                [(r["id"], self.carta.nome, self.carta.versione, adesso()) for r in pronto])
        fatti.extend(r["id"] for r in pronto)
        return len(pronto)

    with monkeypatch.context() as m:
        m.setattr(motore, "apri_descrittore", lambda nome, dove: Finto())
        m.setattr(motore.Passata, "_prepara_gruppo", lambda self, righe: righe)
        m.setattr(motore.Passata, "_fai_un_gruppo", fai)
        m.setattr(motore.magazzino, "scatti_da_fare",
                  _contato(spia, motore.magazzino.scatti_da_fare))
        motore.Passata(archivio, "disegnato", intensita=100).esegui()
    return spia[0], fatti


def _scritte(archivio, monkeypatch) -> tuple[int, list[int]]:
    from officina.parole import magazzino, motore

    spia = [0]
    fatti: list[int] = []

    def uno(self, lettore, scatto_id):
        with archivio.scrittura() as c:
            magazzino.segna_letto(c, scatto_id, motore.SCHEDA.nome, motore.SCHEDA.versione, 0)
        fatti.append(scatto_id)
        return True

    with monkeypatch.context() as m:
        m.setattr(motore.Passata, "_uno", uno)
        m.setattr(magazzino, "da_leggere", _contato(spia, magazzino.da_leggere))
        motore.Passata(archivio, lettore=Finto(), intensita=100).esegui()
    return spia[0], fatti


def _come_cresce(archivio, monkeypatch, passata) -> float:
    misure = []
    for quanti in (300, 1200):
        _riempi(archivio, quanti)
        lavoro, fatti = passata(archivio, monkeypatch)
        assert sorted(fatti) == list(range(1, quanti + 1))
        misure.append(lavoro)
    return misure[1] / max(1, misure[0])


def test_le_impronte_non_riguardano_ogni_volta_le_foto_gia_fatte(archivio, monkeypatch):
    assert _come_cresce(archivio, monkeypatch, _impronte) < 7


def test_le_impronte_vanno_ancora_dalle_foto_piu_recenti(archivio, monkeypatch):
    _riempi(archivio, 200)
    _, fatti = _impronte(archivio, monkeypatch)
    with archivio.lettura() as c:
        atteso = [r[0] for r in c.execute(
            "SELECT id FROM scatti ORDER BY istante_utc DESC, id DESC")]
    assert fatti == atteso


def test_le_scritte_non_riguardano_ogni_volta_le_foto_gia_lette(archivio, monkeypatch):
    assert _come_cresce(archivio, monkeypatch, _scritte) < 7


def test_le_scritte_vanno_ancora_in_ordine(archivio, monkeypatch):
    _riempi(archivio, 200)
    _, fatti = _scritte(archivio, monkeypatch)
    assert fatti == list(range(1, 201))
