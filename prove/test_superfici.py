from __future__ import annotations

import numpy as np
import pytest

from officina.corpi import superfici


def _palla(righe: int = 16, giri: int = 24, raggio: float = 0.3):
    vertici = [[0.0, -raggio, 0.0]]
    for i in range(1, righe):
        alto = np.pi * i / righe
        for j in range(giri):
            giro = 2 * np.pi * j / giri
            vertici.append([raggio * np.sin(alto) * np.cos(giro), -raggio * np.cos(alto),
                            raggio * np.sin(alto) * np.sin(giro)])
    vertici.append([0.0, raggio, 0.0])
    facce = []
    for j in range(giri):
        facce.append([0, 1 + (j + 1) % giri, 1 + j])
    for i in range(righe - 2):
        for j in range(giri):
            a, b = 1 + i * giri + j, 1 + i * giri + (j + 1) % giri
            c, d = a + giri, b + giri
            facce.append([a, b, d])
            facce.append([a, d, c])
    ultimo = len(vertici) - 1
    for j in range(giri):
        a = 1 + (righe - 2) * giri + j
        facce.append([a, 1 + (righe - 2) * giri + (j + 1) % giri, ultimo])
    return np.asarray(vertici), np.asarray(facce)


class PelleFinta:

    def __init__(self, rovescia: bool = False):
        self.vertici_palla, facce = _palla()
        self._facce = facce[:, ::-1] if rovescia else facce
        self.chiamate = 0
        self.spenta = 0

    def facce(self):
        return self._facce

    def vertici(self, forme, parametri):
        self.chiamate += 1
        return [self.vertici_palla.copy() for _ in forme]

    def spegni(self):
        self.spenta += 1


def test_si_vede_solo_il_davanti_della_palla():
    vertici, facce = _palla()
    vertici = vertici + [0, 0, 2.0]
    profondita = superfici.profondita_davanti([vertici], [facce], 1.2, 1.5, 200, 300)
    tutta = np.ones((200, 300), dtype=bool)
    visti, uv = superfici.visti_dalla_foto(vertici, facce, profondita, tutta, 1.2, 1.5)
    davanti = vertici[:, 2] < 2.0 - 0.05
    dietro = vertici[:, 2] > 2.0 + 0.05
    assert visti[davanti].mean() > 0.95
    assert not visti[dietro].any()
    assert (uv >= 0).all() and (uv <= 1).all()
    assert uv[np.argmin(vertici[:, 2])] == pytest.approx([0.5, 0.5], abs=0.02)


def test_le_facce_girate_al_contrario_non_cambiano_cosa_si_vede():
    vertici, facce = _palla()
    vertici = vertici + [0, 0, 2.0]
    profondita = superfici.profondita_davanti([vertici], [facce], 1.2, 1.5, 200, 300)
    tutta = np.ones((200, 300), dtype=bool)
    dritte, _ = superfici.visti_dalla_foto(vertici, facce, profondita, tutta, 1.2, 1.5)
    rovesce, _ = superfici.visti_dalla_foto(vertici, facce[:, ::-1], profondita, tutta, 1.2, 1.5)
    assert (dritte == rovesce).all()


def test_chi_sta_dietro_un_altro_non_prende_i_suoi_colori():
    vertici, facce = _palla()
    davanti = vertici + [0, 0, 2.0]
    dietro = vertici + [0, 0, 3.5]
    profondita = superfici.profondita_davanti([davanti, dietro], [facce, facce], 1.2, 1.5, 200, 300)
    tutta = np.ones((200, 300), dtype=bool)
    visti, _ = superfici.visti_dalla_foto(dietro, facce, profondita, tutta, 1.2, 1.5)
    centro = (np.abs(dietro[:, 0]) < 0.1) & (np.abs(dietro[:, 1]) < 0.1)
    assert centro.any() and not visti[centro].any()


def test_fuori_dalla_maschera_e_argilla():
    vertici, facce = _palla()
    vertici = vertici + [0, 0, 2.0]
    profondita = superfici.profondita_davanti([vertici], [facce], 1.2, 1.5, 200, 300)
    meta = np.zeros((200, 300), dtype=bool)
    meta[:, 150:] = True
    visti, _ = superfici.visti_dalla_foto(vertici, facce, profondita, meta, 1.2, 1.5)
    assert visti.any()
    assert not visti[vertici[:, 0] < -0.02].any()


def test_la_superficie_va_e_torna_dal_file(tmp_path):
    vertici, _ = _palla()
    visti = vertici[:, 2] < 0
    uv = np.clip(vertici[:, :2] + 0.5, 0, 1)
    superfici.salva(tmp_path / "7.npz", vertici, [0.1, 0.2, 3.0], visti, uv)
    letta = superfici.leggi(tmp_path / "7.npz")
    assert letta["vertici"] == pytest.approx(vertici + [0.1, 0.2, 3.0], abs=1e-3)
    assert (letta["visti"] == visti).all()
    assert letta["uv"] == pytest.approx(uv, abs=2e-5)


def _con_le_figure(archivio):
    from officina.corpi import figure
    from prove.test_figure import FigureFinte, _con_i_corpi

    _con_i_corpi(archivio)
    figure.Passata(archivio, figure=FigureFinte()).esegui()


def test_ogni_corpo_con_la_figura_prende_la_sua_superficie(archivio_pieno):
    _con_le_figure(archivio_pieno)
    passata = superfici.Passata(archivio_pieno, pelle=PelleFinta())
    totale = passata.quanti_mancano()
    assert totale > 0
    fatto = passata.esegui()
    assert fatto.fatti == totale and fatto.saltati == 0 and fatto.superfici == 2 * totale
    assert passata.pelle.spenta == 1
    assert "corpi veri in 3D" in fatto.a_parole()
    assert superfici.leggi_le_facce(archivio_pieno.dove.superfici).shape[1] == 3
    with archivio_pieno.lettura() as connessione:
        righe = connessione.execute("SELECT * FROM superfici").fetchall()
        scatto_id = connessione.execute(
            "SELECT c.scatto_id FROM corpi c JOIN superfici f ON f.corpo_id = c.id LIMIT 1").fetchone()[0]
        dello_scatto = superfici.di_scatto(connessione, scatto_id)
    assert len(righe) == 2 * totale
    assert all(r["versione"] == superfici.VERSIONE and 0 <= r["visti"] < r["vertici"] for r in righe)
    assert any(r["visti"] > 0 for r in righe)
    assert len(dello_scatto) == 2
    letta = superfici.leggi(archivio_pieno.dove.superfici / righe[0]["file"])
    assert len(letta["vertici"]) == righe[0]["vertici"]
    assert superfici.Passata(archivio_pieno, pelle=PelleFinta()).quanti_mancano() == 0


def test_i_file_senza_corpo_si_tolgono(archivio_pieno):
    _con_le_figure(archivio_pieno)
    superfici.Passata(archivio_pieno, pelle=PelleFinta()).esegui()
    cartella = archivio_pieno.dove.superfici
    with archivio_pieno.scrittura() as connessione:
        tolto = connessione.execute("SELECT corpo_id, file FROM superfici LIMIT 1").fetchone()
        connessione.execute("DELETE FROM corpi WHERE id = ?", (tolto["corpo_id"],))
    assert (cartella / tolto["file"]).exists()
    superfici.Passata(archivio_pieno, pelle=PelleFinta()).esegui()
    assert not (cartella / tolto["file"]).exists()
    assert (cartella / superfici.FILE_DELLE_FACCE).exists()


def test_una_superficie_rotta_si_segna_e_non_si_riprova(archivio_pieno):
    class Rotta(PelleFinta):
        def vertici(self, forme, parametri):
            raise RuntimeError("rotta")

    _con_le_figure(archivio_pieno)
    fatto = superfici.Passata(archivio_pieno, pelle=Rotta()).esegui()
    assert fatto.saltati == fatto.totale > 0
    with archivio_pieno.lettura() as connessione:
        assert superfici.quanti_mancano_senza_aprire(connessione) == 0
        assert connessione.execute("SELECT count(*) FROM superfici WHERE vertici = 0").fetchone()[0] > 0
