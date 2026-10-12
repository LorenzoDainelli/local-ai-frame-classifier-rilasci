from __future__ import annotations

import hashlib
import math

import numpy as np
import pytest

from officina.errori import ErroreOfficina
from officina.stanza import costruzione


def _guarda_verso_il_centro(angolo: float, raggio: float = 1.0):
    centro = np.array([raggio * math.cos(angolo), 0.0, raggio * math.sin(angolo)])
    avanti = -centro / np.linalg.norm(centro)
    giu = np.array([0.0, 1.0, 0.0])
    destra = np.cross(giu, avanti)
    rotazione = np.stack([destra, giu, avanti], axis=1)
    piena = np.eye(4)
    piena[:3, :3] = rotazione.T
    piena[:3, 3] = -rotazione.T @ centro
    return piena, centro


class ModelliFinti:

    def __init__(self, scala_della_corsa: float = 0.7, metri: float = 2.5, rotti: bool = False):
        self.scala_della_corsa = scala_della_corsa
        self.metri = metri
        self.rotti = rotti
        self.centri_veri: dict[str, np.ndarray] = {}
        self._pose: dict[str, np.ndarray] = {}
        self.chiamate = {"posizioni": 0, "forma": 0}
        self.spenti = 0

    def chiave(self, immagine) -> str:
        return hashlib.sha256(immagine.tobytes()).hexdigest()

    def _posa(self, immagine):
        chiave = self.chiave(immagine)
        if chiave not in self._pose:
            angolo = 0.45 * len(self._pose)
            self._pose[chiave], self.centri_veri[chiave] = _guarda_verso_il_centro(angolo)
        return self._pose[chiave]

    def posizioni(self, immagini) -> dict:
        self.chiamate["posizioni"] += 1
        if self.rotti:
            raise RuntimeError("si è rotta")
        pose = [self._posa(i) for i in immagini]
        prima = np.linalg.inv(pose[0])
        estrinseci, intrinseci, viaggi = [], [], []
        for immagine, posa in zip(immagini, pose, strict=True):
            relativa = posa @ prima
            relativa[:3, 3] *= self.scala_della_corsa
            estrinseci.append(relativa[:3, :4])
            larga, alta = immagine.size
            alta_qui = max(16, round(48 * alta / larga))
            intrinseci.append(np.array([[40.0, 0, 24.0], [0, 40.0, alta_qui / 2], [0, 0, 1]]))
            viaggi.append({"taglio": (0, 0), "scala": (48 / larga, alta_qui / alta), "aggiunta": (0, 0),
                           "foto": (larga, alta)})
        return {"estrinseci": np.asarray(estrinseci), "intrinseci": np.asarray(intrinseci), "viaggi": viaggi}

    def forma(self, immagini, estrinseci, intrinseci) -> dict:
        self.chiamate["forma"] += 1
        quante = len(immagini)
        larga, alta = immagini[0].size
        piccole = []
        for matrice in intrinseci:
            k = np.array(matrice, dtype=np.float64)
            k[0] *= 16 / larga
            k[1] *= 12 / alta
            piccole.append(k)
        fiducia = np.tile(np.linspace(1, 2, 12 * 16).reshape(12, 16), (quante, 1, 1))
        return {"profondita": np.full((quante, 12, 16), 2.0, dtype=np.float32), "fiducia": fiducia,
                "cielo": np.zeros((quante, 12, 16), dtype=bool),
                "estrinseci": np.asarray(estrinseci)[:, :3, :4], "intrinseci": np.asarray(piccole),
                "immagini": np.zeros((quante, 3, 12, 16), dtype=np.float32),
                "allineamento": (np.eye(3), np.zeros(3), self.metri)}

    def spegni(self):
        self.spenti += 1


def _foto_dell_archivio(archivio) -> list[int]:
    with archivio.lettura() as connessione:
        return [r["id"] for r in connessione.execute(
            "SELECT DISTINCT s.id FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "AND f.ruolo = 'principale' AND f.genere = 'immagine' "
            "WHERE s.genere IN ('foto','live') AND s.fuori_archivio = 0 ORDER BY s.id")]


def _un_posto_con(archivio, scatti: list[int], nome: str = "Cucina") -> int:
    from officina.modello import posti

    with archivio.scrittura() as connessione:
        posto_id = posti.crea(connessione, nome)
        for scatto_id in scatti:
            posti.metti(connessione, scatto_id, posto_id)
    return posto_id


def _metti(archivio, scatti: list[int], posto_id: int) -> None:
    from officina.modello import posti

    with archivio.scrittura() as connessione:
        for scatto_id in scatti:
            posti.metti(connessione, scatto_id, posto_id)


def test_un_posto_con_meno_di_cinque_foto_non_si_costruisce(archivio_pieno):
    _un_posto_con(archivio_pieno, _foto_dell_archivio(archivio_pieno)[:4])
    with archivio_pieno.lettura() as connessione:
        assert costruzione.da_fare(connessione) == []


def test_la_stanza_si_costruisce_e_poi_si_mettono_le_foto_nuove(archivio_pieno):
    from officina.modello import stanze

    foto = _foto_dell_archivio(archivio_pieno)
    assert len(foto) >= 9
    posto_id = _un_posto_con(archivio_pieno, foto[:7])
    with archivio_pieno.lettura() as connessione:
        assert costruzione.da_fare(connessione) == [(posto_id, "costruisci")]
    finti = ModelliFinti()
    passata = costruzione.Passata(archivio_pieno, modelli=finti)
    fatto = passata.esegui()
    assert fatto.stanze == 1 and fatto.non_riuscite == 0 and fatto.foto_messe == 7
    assert finti.spenti == 1 and finti.chiamate["forma"] >= 1
    assert "1 costruite" in fatto.a_parole()
    with archivio_pieno.lettura() as connessione:
        stanza = stanze.di_posto(connessione, posto_id)
        messe = stanze.foto_di(connessione, posto_id)
        assert costruzione.da_fare(connessione) == []
    assert stanza["stato"] == stanze.FATTA and stanza["versione"] == costruzione.VERSIONE
    assert stanza["foto_usate"] == 7 and stanza["foto_viste"] == 7
    assert stanza["metri"] == pytest.approx(2.5)
    assert stanza["punti"] > 0 and stanza["larga"] > 0 and stanza["lunga"] > 0
    punti, colori = costruzione.leggi_la_nuvola(archivio_pieno.dove.stanze / stanza["file"])
    assert len(punti) == stanza["punti"] == len(colori)
    assert np.percentile(punti[:, 1], 2) == pytest.approx(0.0, abs=0.15)
    assert len(messe) == 7 and all(m["usata"] for m in messe)
    assert sorted(m["ordine"] for m in messe) == list(range(7))
    assert all(0 < m["campo"] < math.pi for m in messe)
    for m in messe:
        rotazione = np.asarray(m["rotazione"])
        assert rotazione @ rotazione.T == pytest.approx(np.eye(3), abs=1e-4)

    _metti(archivio_pieno, foto[7:9], posto_id)
    with archivio_pieno.lettura() as connessione:
        assert costruzione.da_fare(connessione) == [(posto_id, "metti")]
    fatto = costruzione.Passata(archivio_pieno, modelli=finti).esegui()
    assert fatto.stanze == 0 and fatto.foto_messe == 2
    with archivio_pieno.lettura() as connessione:
        messe = stanze.foto_di(connessione, posto_id)
        assert costruzione.da_fare(connessione) == []
        assert stanze.di_posto(connessione, posto_id)["foto_viste"] == 9
        assert [s["nome"] for s in stanze.di_scatto(connessione, foto[8])] == ["Cucina"]
    assert len(messe) == 9
    nuove = [m for m in messe if not m["usata"]]
    assert sorted(m["scatto_id"] for m in nuove) == foto[7:9]
    assert all(m["ordine"] is None for m in nuove)

    lettrice = costruzione.Passata(archivio_pieno)
    vere = {m["scatto_id"]: finti.centri_veri[finti.chiave(lettrice._leggi(m["scatto_id"]).immagine)]
            for m in messe}
    nella_stanza = {m["scatto_id"]: np.asarray(m["centro"]) for m in messe}
    rapporti = []
    for a in nuove:
        for b in messe:
            vera = np.linalg.norm(vere[a["scatto_id"]] - vere[b["scatto_id"]])
            if vera > 1e-6:
                rapporti.append(np.linalg.norm(nella_stanza[a["scatto_id"]] - nella_stanza[b["scatto_id"]]) / vera)
    assert rapporti and np.allclose(rapporti, 2.5 * 0.7, rtol=1e-3)


def test_le_persone_restano_fuori_dalla_nuvola():
    esito = {"profondita": np.full((1, 10, 20), 2.0), "fiducia": np.ones((1, 10, 20)),
             "cielo": np.zeros((1, 10, 20), dtype=bool), "estrinseci": np.eye(4)[None, :3, :4],
             "intrinseci": np.array([[[10.0, 0, 10.0], [0, 10.0, 5.0], [0, 0, 1]]]),
             "immagini": np.zeros((1, 3, 10, 20))}
    tutti, _ = costruzione.punti_di_una_foto(esito, 0)
    persone = np.zeros((100, 200), dtype=bool)
    persone[:, :100] = True
    senza, colori = costruzione.punti_di_una_foto(esito, 0, persone)
    assert len(tutti) == 200
    assert 0 < len(senza) < 100 and len(colori) == len(senza)
    assert (senza[:, 0] > 0).all()


def test_il_cielo_e_i_punti_incerti_restano_fuori():
    cielo = np.zeros((1, 4, 4), dtype=bool)
    cielo[0, 3] = True
    fiducia = np.tile(np.arange(16, dtype=float).reshape(4, 4), (1, 1, 1))
    esito = {"profondita": np.ones((1, 4, 4)), "fiducia": fiducia, "cielo": cielo,
             "estrinseci": np.eye(4)[None, :3, :4], "intrinseci": np.array([[[2.0, 0, 2], [0, 2.0, 2], [0, 0, 1]]]),
             "immagini": np.zeros((1, 3, 4, 4))}
    punti, _ = costruzione.punti_di_una_foto(esito, 0)
    assert len(punti) == 6


def test_i_punti_vanno_nel_mondo_con_la_posa_della_macchina():
    posa, centro = _guarda_verso_il_centro(0.3)
    esito = {"profondita": np.ones((1, 1, 1)), "fiducia": np.ones((1, 1, 1)), "cielo": np.zeros((1, 1, 1), bool),
             "estrinseci": posa[None, :3, :4], "intrinseci": np.array([[[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1]]]),
             "immagini": np.zeros((1, 3, 1, 1))}
    punti, _ = costruzione.punti_di_una_foto(esito, 0)
    assert punti[0] == pytest.approx(centro + (-centro / np.linalg.norm(centro)))


def test_le_piu_diverse_prendono_una_foto_per_ogni_gruppo():
    caso = np.random.default_rng(1)
    gruppi = [np.eye(8)[i] for i in (0, 3, 6)]
    vettori = [g + caso.normal(0, 0.01, 8) for g in gruppi for _ in range(5)]
    scelte = costruzione.le_piu_diverse(vettori, 3)
    assert len(set(scelte)) == 3
    assert {s // 5 for s in scelte} == {0, 1, 2}
    assert costruzione.le_piu_diverse(vettori[:2], 5) == [0, 1]


def test_raddrizza_mette_il_su_in_alto_e_la_prima_foto_verso_meno_z():
    posa, _ = _guarda_verso_il_centro(1.1)
    rotazione = costruzione.raddrizza(posa[None, :3, :4])
    assert np.linalg.det(rotazione) == pytest.approx(1.0)
    assert rotazione @ rotazione.T == pytest.approx(np.eye(3), abs=1e-9)
    avanti = posa[2, :3]
    giu = posa[1, :3]
    assert rotazione @ avanti == pytest.approx([0, 0, -1], abs=1e-9)
    assert rotazione @ giu == pytest.approx([0, -1, 0], abs=1e-9)


def test_sistema_mette_il_pavimento_a_zero_e_la_stanza_al_centro():
    posa = np.eye(4)[None, :3, :4]
    caso = np.random.default_rng(2)
    punti = caso.uniform([-1, -0.5, 1], [3, 1.5, 4], size=(5000, 3))
    sistemazione, misure = costruzione.sistema(posa, punti, 2.0)
    messi = sistemazione.punti(punti)
    basso, alto = np.percentile(messi, [2, 98], axis=0)
    assert basso[1] == pytest.approx(0.0, abs=1e-9)
    assert (basso[0] + alto[0]) / 2 == pytest.approx(0.0, abs=1e-9)
    assert (basso[2] + alto[2]) / 2 == pytest.approx(0.0, abs=1e-9)
    assert misure[0] == pytest.approx(2.0 * 4 * 0.96, rel=0.03)
    assert misure[1] == pytest.approx(2.0 * 3 * 0.96, rel=0.03)
    assert misure[2] == pytest.approx(2.0 * 2 * 0.96, rel=0.03)


def test_a_cubetti_toglie_i_doppi_e_tiene_al_massimo_quelli_chiesti():
    punti = np.array([[0.001, 0.001, 0.001], [0.002, 0.002, 0.002], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]])
    colori = np.arange(12, dtype=np.uint8).reshape(4, 3)
    tenuti, tinte = costruzione.a_cubetti(punti, colori, lato=0.01)
    assert len(tenuti) == 3 and tinte[0].tolist() == [0, 1, 2]
    pochi, _ = costruzione.a_cubetti(punti, colori, lato=0.01, massimi=2)
    assert len(pochi) == 2


def test_le_foto_si_dividono_per_misura_e_a_gruppi_non_troppo_grandi():
    from PIL import Image

    grandi = [costruzione.Foto(i, Image.new("RGB", (40, 30))) for i in range(30)]
    dritte = [costruzione.Foto(100 + i, Image.new("RGB", (30, 40))) for i in range(3)]
    pezzi = costruzione._a_gruppi(grandi + dritte)
    assert sorted(len(p) for p in pezzi) == [3, 15, 15]
    assert sorted(i for p in pezzi for i in p) == list(range(33))


def test_la_nuvola_va_e_torna_dal_file(tmp_path):
    punti = np.array([[0.5, 1.25, -2.0]], dtype=np.float64)
    colori = np.array([[10, 20, 30]], dtype=np.uint8)
    costruzione._salva_la_nuvola(tmp_path / "1.npz", punti, colori)
    letti, tinte = costruzione.leggi_la_nuvola(tmp_path / "1.npz")
    assert letti.tolist() == [[0.5, 1.25, -2.0]] and tinte.tolist() == [[10, 20, 30]]
    assert [p.name for p in tmp_path.iterdir()] == ["1.npz"]


def test_una_stanza_rotta_si_segna_e_non_si_riprova_finche_non_cambiano_le_foto(archivio_pieno):
    from officina.modello import stanze

    foto = _foto_dell_archivio(archivio_pieno)
    posto_id = _un_posto_con(archivio_pieno, foto[:6])
    fatto = costruzione.Passata(archivio_pieno, modelli=ModelliFinti(rotti=True)).esegui()
    assert fatto.non_riuscite == 1 and fatto.stanze == 0
    with archivio_pieno.lettura() as connessione:
        stanza = stanze.di_posto(connessione, posto_id)
        assert stanza["stato"] == stanze.NON_RIUSCITA and stanza["perche"]
        assert costruzione.da_fare(connessione) == []
        assert stanze.di_scatto(connessione, foto[0]) == []
    _metti(archivio_pieno, foto[6:7], posto_id)
    with archivio_pieno.lettura() as connessione:
        assert costruzione.da_fare(connessione) == [(posto_id, "costruisci")]


def test_se_le_foto_non_si_aprono_la_stanza_non_si_costruisce(archivio_pieno, monkeypatch):
    from officina.modello import stanze

    foto = _foto_dell_archivio(archivio_pieno)
    posto_id = _un_posto_con(archivio_pieno, foto[:5])
    monkeypatch.setattr(costruzione.Passata, "_leggi", lambda self, scatto_id: None)
    finti = ModelliFinti()
    fatto = costruzione.Passata(archivio_pieno, modelli=finti).esegui()
    assert fatto.non_riuscite == 1 and finti.chiamate["posizioni"] == 0
    with archivio_pieno.lettura() as connessione:
        assert "almeno 5" in stanze.di_posto(connessione, posto_id)["perche"]


def test_una_versione_nuova_rifa_la_stanza(archivio_pieno, monkeypatch):
    foto = _foto_dell_archivio(archivio_pieno)
    posto_id = _un_posto_con(archivio_pieno, foto[:5])
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti()).esegui()
    monkeypatch.setattr(costruzione, "VERSIONE", "2-prova")
    with archivio_pieno.lettura() as connessione:
        assert costruzione.da_fare(connessione) == [(posto_id, "costruisci")]


def test_i_modelli_mancanti_si_dicono(tmp_path):
    assert not costruzione.ci_sono(tmp_path)
    assert "VGGT-Omega" in costruzione.cosa_manca(tmp_path)
    casa = costruzione.dove_stanno(tmp_path)
    for nome in (costruzione.FILE_VGGT, costruzione.FILE_DA3):
        (casa / nome).parent.mkdir(parents=True, exist_ok=True)
        (casa / nome).write_bytes(b"0")
    assert costruzione.ci_sono(tmp_path) and costruzione.cosa_manca(tmp_path) == ""


def test_le_tabelle_delle_stanze_ci_sono(archivio):
    with archivio.lettura() as connessione:
        colonne = {r["name"] for r in connessione.execute("PRAGMA table_info(stanze_foto)")}
        assert {"macchina", "campo", "usata", "ordine"} <= colonne
        assert connessione.execute("SELECT count(*) FROM stanze").fetchone()[0] == 0


def test_la_macchina_va_e_torna_dai_byte():
    from officina.modello import stanze

    centro, rotazione = stanze._macchina_da_byte(stanze._macchina_a_byte([1, 2, 3], np.eye(3)))
    assert centro == [1, 2, 3] and rotazione == np.eye(3).tolist()


def test_senza_memoria_si_riprova_con_meno_foto_e_poi_si_dice(archivio):
    from PIL import Image

    class Piena:
        def __init__(self):
            self.quante = []

        def posizioni(self, immagini):
            self.quante.append(len(immagini))
            raise MemoryError

    piena = Piena()
    passata = costruzione.Passata(archivio, modelli=piena)
    with pytest.raises(ErroreOfficina, match="memoria"):
        passata._posizioni_robuste([costruzione.Foto(i, Image.new("RGB", (8, 6))) for i in range(30)])
    assert piena.quante == [30, 20, 13, 10]
