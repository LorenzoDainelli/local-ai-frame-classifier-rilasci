from __future__ import annotations

import json

from officina.volti import insight, motore
from officina.volti.rilevatore import Faccia


def test_il_rilevatore_guarda_a_due_misure_e_tiene_i_piccoli():
    assert insight.LATI_DEL_QUADRATO == (640, 1280)
    assert insight.LATO_MINIMO == 0.015


def test_il_quadrato_ha_il_lato_chiesto():
    import numpy

    foto = numpy.zeros((300, 600, 3), dtype=numpy.uint8)
    quadro, scala = insight._rimpicciolita(foto, 1280)
    assert quadro.shape == (1280, 1280, 3) and round(scala, 4) == round(1280 / 600, 4)
    assert insight._rimpicciolita(foto)[0].shape == (640, 640, 3)


def test_riguardando_restano_i_volti_vecchi_e_si_aggiungono_solo_i_nuovi():
    vecchi = [{"fotogramma": 0, "riquadro": json.dumps([0.10, 0.10, 0.20, 0.20])}]
    stesso = Faccia((0.11, 0.10, 0.20, 0.20), 0.9)
    piccolo = Faccia((0.70, 0.70, 0.02, 0.02), 0.8)
    altro_fotogramma = Faccia((0.10, 0.10, 0.20, 0.20), 0.9)
    nuovi = motore.solo_i_nuovi(
        [(0, stesso), (0, piccolo), (3, altro_fotogramma)], vecchi)
    assert nuovi == [(0, piccolo), (3, altro_fotogramma)]


def test_la_migrazione_fa_riguardare_le_foto_gia_viste(archivio):
    from officina.archivio import migrazioni

    with archivio.scrittura() as connessione:
        for numero, stato in ((1, 0), (2, 1)):
            connessione.execute(
                "INSERT INTO scatti (id, genere, origine_data, creato_il) "
                "VALUES (?, 'foto', 'assente', '2026-01-01T00:00:00')", (numero,))
            connessione.execute(
                "INSERT INTO volti_guardati (scatto_id, modello, versione, quanti, "
                "guardato_il, da_riguardare) VALUES (?, 'volti', 'v', 0, 'x', ?)",
                (numero, stato))
        migrazioni._versione_78(connessione)
        stati = [riga[0] for riga in connessione.execute(
            "SELECT da_riguardare FROM volti_guardati ORDER BY scatto_id")]
        quanti = connessione.execute(
            "SELECT valore FROM stato WHERE chiave = 'volti_piccoli_da_cercare'").fetchone()
    assert stati == [2, 1] and tuple(quanti) == ("1",)


def test_le_gia_viste_si_riguardano_solo_con_i_piccoli_accesi():
    from officina.volti import motore

    spento = motore._domanda_da_fare("s.id")
    acceso = motore._domanda_da_fare("s.id", piccoli=True)
    assert "g.da_riguardare IN (0, 2)" in spento
    assert "g.da_riguardare = 0" in acceso


def _rilevatore_finto(per_lato, tmp_path):
    from PIL import Image

    rilevatore = insight.Rilevatore(tmp_path)
    rilevatore._trova = object()
    rilevatore._riconosce = object()
    rilevatore._impronta_di = lambda dritta, numpy: None
    rilevatore._raddrizza = lambda *altro: Image.new("RGB", (112, 112))

    def proposte(quadro):
        return per_lato[quadro.shape[0]]
    rilevatore._proposte = proposte
    return rilevatore


def _riquadro(x, y, lato, scala):
    return [x * scala, y * scala, (x + lato) * scala, (y + lato) * scala]


def test_un_volto_visto_solo_a_1280_deve_essere_sicuro_all_80(tmp_path):
    import numpy

    foto = numpy.full((640, 640, 3), 128, numpy.uint8)
    punti = [(0.0, 0.0)] * 5
    per_lato = {
        640: [(_riquadro(10, 10, 100, 1), punti, 0.90),
              (_riquadro(300, 300, 60, 1), punti, 0.35)],
        1280: [(_riquadro(300, 300, 60, 2), punti, 0.70),
               (_riquadro(500, 20, 40, 2), punti, 0.75),
               (_riquadro(500, 500, 40, 2), punti, 0.85)],
    }
    facce = _rilevatore_finto(per_lato, tmp_path).guarda(foto)
    sicurezze = sorted(round(faccia.sicurezza, 2) for faccia in facce)
    assert sicurezze == [0.70, 0.85, 0.90]


def test_con_una_passata_sola_la_regola_non_si_applica(tmp_path, monkeypatch):
    import numpy

    monkeypatch.setattr(insight, "LATI_DEL_QUADRATO", (640,))
    foto = numpy.full((640, 640, 3), 128, numpy.uint8)
    per_lato = {640: [(_riquadro(10, 10, 100, 1), [(0.0, 0.0)] * 5, 0.65)]}
    assert len(_rilevatore_finto(per_lato, tmp_path).guarda(foto)) == 1


def test_le_soglie_della_regola_scelta():
    assert insight.SICUREZZA_MINIMA == 0.60
    assert insight.SICUREZZA_SOLO_GRANDE == 0.80
