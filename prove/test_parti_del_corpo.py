from __future__ import annotations

import numpy
import pytest

from officina.corpi import maschere
from officina.corpi.rilevatore import Corpo
from officina.modello import corpi, parti


def _scatto(connessione) -> int:
    connessione.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    return connessione.execute("SELECT max(id) FROM scatti").fetchone()[0]


def _maschera(meta: str) -> bytes:
    piena = numpy.zeros((40, 40), dtype=bool)
    if meta == "sopra":
        piena[:20] = True
    else:
        piena[20:] = True
    return maschere.comprimi(piena)


def _due_persone(connessione, scatto_id) -> list[int]:
    corpi.salva(connessione, scatto_id, None, [
        (0, Corpo((0.0, 0.0, 0.5, 1.0), 0.95, _maschera("sopra"))),
        (0, Corpo((0.5, 0.0, 0.5, 1.0), 0.90, _maschera("sotto"))),
    ], "corpi", "1")
    return [riga[0] for riga in connessione.execute(
        "SELECT id FROM corpi WHERE scatto_id = ? ORDER BY id", (scatto_id,))]


def test_la_parola_si_pulisce_e_va_in_minuscolo():
    assert parti.controlla("  Mano  destra ", " Right   HAND ") == ("Mano destra", "right hand")


@pytest.mark.parametrize(("nome", "parola"), [
    ("", "hand"), ("Mano", ""), ("Mano", "mano è"), ("Mano", "hand; drop"),
    ("x" * 41, "hand"), ("Mano", "h" * 61), ("Mano", "123")])
def test_nomi_e_parole_sbagliati_si_rifiutano(nome, parola):
    with pytest.raises(parti.ParteSbagliata):
        parti.controlla(nome, parola)


def test_non_si_mettono_due_volte_la_stessa_parola_o_lo_stesso_nome(archivio):
    with archivio.scrittura() as connessione:
        parti.aggiungi(connessione, "Mano", "hand")
        with pytest.raises(parti.ParteSbagliata):
            parti.aggiungi(connessione, "Mani", "Hand")
        with pytest.raises(parti.ParteSbagliata):
            parti.aggiungi(connessione, "mano", "palm")
        assert [p["parola"] for p in parti.elenco(connessione)] == ["hand"]


def test_l_elenco_ha_un_tetto(archivio):
    with archivio.scrittura() as connessione:
        for numero in range(parti.QUANTE_AL_MASSIMO):
            lettere = "".join(chr(97 + int(c)) for c in f"{numero:02d}")
            parti.aggiungi(connessione, f"Parte {numero}", f"part {lettere}")
        with pytest.raises(parti.ParteSbagliata):
            parti.aggiungi(connessione, "Una di troppo", "one more")


def test_la_parte_va_alla_persona_che_la_contiene(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        sopra, sotto = _due_persone(connessione, scatto_id)
        mano = parti.aggiungi(connessione, "Mano", "hand")
        quante = parti.salva(connessione, scatto_id, None, mano, [
            (0, (0.1, 0.1, 0.2, 0.2), 0.9),
            (0, (0.6, 0.7, 0.2, 0.2), 0.8),
            (0, (0.1, 0.7, 0.2, 0.2), 0.7),
        ], "sam3", "1")
        trovate = parti.di_scatto(connessione, scatto_id)
    assert quante == 3
    assert [t["corpo_id"] for t in trovate] == [sopra, sotto, None]
    assert trovate[0]["nome"] == "Mano" and trovate[0]["copertura"] == 1.0


def test_senza_sagoma_conta_il_riquadro_della_persona(archivio):
    assert parti.assegna((0.1, 0.1, 0.2, 0.2), [
        {"id": 7, "riquadro": "[0.0, 0.0, 0.5, 1.0]", "maschera": None}]) == (7, 1.0)
    assert parti.assegna((0.7, 0.1, 0.2, 0.2), [
        {"id": 7, "riquadro": [0.0, 0.0, 0.5, 1.0], "maschera": None}]) == (None, 0.0)


def test_una_parola_nuova_si_cerca_solo_lei_anche_sulle_foto_gia_fatte(archivio):
    with archivio.scrittura() as connessione:
        primo, secondo = _scatto(connessione), _scatto(connessione)
        senza_corpi = _scatto(connessione)
        _due_persone(connessione, primo)
        _due_persone(connessione, secondo)
        mano = parti.aggiungi(connessione, "Mano", "hand")
        assert parti.quanti_mancano(connessione) == 2
        assert parti.da_fare(connessione, 10) == [(secondo, [mano]), (primo, [mano])]
        parti.salva(connessione, primo, None, mano, [], "sam3", "1")
        parti.salva(connessione, secondo, None, mano, [], "sam3", "1")
        assert parti.quanti_mancano(connessione) == 0
        piede = parti.aggiungi(connessione, "Piede", "foot")
        assert parti.da_fare(connessione, 1) == [(secondo, [piede])]
        assert parti.da_fare(connessione, 10, tranne=[secondo]) == [(primo, [piede])]
        assert senza_corpi not in [s for s, _ in parti.da_fare(connessione, 10)]


def test_cambiare_la_parola_cancella_il_trovato_cambiare_il_nome_no(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        _due_persone(connessione, scatto_id)
        mano = parti.aggiungi(connessione, "Mano", "hand")
        parti.salva(connessione, scatto_id, None, mano, [(0, (0.1, 0.1, 0.2, 0.2), 0.9)],
                    "sam3", "1")
        assert parti.cambia(connessione, mano, "Mani", "hand") is False
        assert len(parti.di_scatto(connessione, scatto_id)) == 1
        assert parti.cambia(connessione, mano, "Mani", "hands") is True
        assert parti.di_scatto(connessione, scatto_id) == []
        assert parti.quanti_mancano(connessione) == 1


def test_togliere_una_parola_cancella_anche_quello_che_aveva_trovato(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        _due_persone(connessione, scatto_id)
        mano = parti.aggiungi(connessione, "Mano", "hand")
        piede = parti.aggiungi(connessione, "Piede", "foot")
        for parte in (mano, piede):
            parti.salva(connessione, scatto_id, None, parte,
                        [(0, (0.1, 0.1, 0.2, 0.2), 0.9)], "sam3", "1")
        assert parti.togli(connessione, mano) is True
        assert [t["nome"] for t in parti.di_scatto(connessione, scatto_id)] == ["Piede"]
        assert connessione.execute(
            "SELECT count(*) FROM parti_guardate").fetchone()[0] == 1
        assert parti.scatti_con(connessione, piede) == [scatto_id]


def test_se_i_corpi_si_rifanno_le_parti_si_ricercano(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        _due_persone(connessione, scatto_id)
        mano = parti.aggiungi(connessione, "Mano", "hand")
        parti.salva(connessione, scatto_id, None, mano, [(0, (0.1, 0.1, 0.2, 0.2), 0.9)],
                    "sam3", "1")
        connessione.execute(
            "UPDATE parti_guardate SET guardata_il = '2020-01-01T00:00:00'")
        _due_persone(connessione, scatto_id)
        assert parti.di_scatto(connessione, scatto_id)[0]["corpo_id"] is None
        assert parti.da_fare(connessione, 10) == [(scatto_id, [mano])]


class _Preparatore:

    def __call__(self, text=None, images=None, return_tensors=None):
        torch = pytest.importorskip("torch")
        if text is not None:
            return {"input_ids": torch.tensor([[len(text)]]),
                    "attention_mask": torch.tensor([[1]])}
        return {"pixel_values": torch.zeros(1, 3, 8, 8)}

    def post_process_instance_segmentation(self, uscita, threshold, mask_threshold,
                                           target_sizes):
        torch = pytest.importorskip("torch")
        alta, larga = target_sizes[0]
        lunga = float(uscita.pred_logits.reshape(-1)[0])
        return [{"scores": torch.tensor([0.9]),
                 "boxes": torch.tensor([[0.0, 0.0, larga / 2, alta / lunga]]),
                 "masks": torch.zeros(1, alta, larga)}]


class _Modello:

    def __init__(self, con_la_vista: bool):
        self.con_la_vista = con_la_vista
        self.viste = 0
        self.intere = 0
        if not con_la_vista:
            self.get_vision_features = None

    def get_vision_features(self, pixel_values):
        self.viste += 1
        return "vista"

    def __call__(self, pixel_values=None, vision_embeds=None, input_ids=None,
                 attention_mask=None):
        from types import SimpleNamespace

        torch = pytest.importorskip("torch")
        if vision_embeds is None:
            self.intere += 1
        return SimpleNamespace(pred_logits=input_ids.float(), pred_boxes=torch.zeros(1),
                               pred_masks=torch.zeros(1), presence_logits=None)


def _separatore(tmp_path, modello):
    from officina.corpi.sam3 import Separatore

    separatore = Separatore(tmp_path)
    separatore._modello = modello
    separatore._preparatore = _Preparatore()
    separatore._tipo = pytest.importorskip("torch").float32
    return separatore


def test_sam3_guarda_la_foto_una_volta_sola_per_tutte_le_parole(tmp_path):
    from PIL import Image

    modello = _Modello(True)
    separatore = _separatore(tmp_path, modello)
    trovato = separatore.cerca(Image.new("RGB", (200, 100)), ["hand", "foot"])
    assert modello.viste == 1 and modello.intere == 0
    assert trovato["hand"] == [((0.0, 0.0, 0.5, 0.25), pytest.approx(0.9))]
    assert trovato["foot"] == [((0.0, 0.0, 0.5, 0.25), pytest.approx(0.9))]
    separatore.cerca(Image.new("RGB", (200, 100)), ["hand"])
    assert modello.viste == 2 and set(separatore._parole) == {"hand", "foot"}


def test_sam3_senza_la_vista_separata_cerca_lo_stesso(tmp_path):
    from PIL import Image

    modello = _Modello(False)
    separatore = _separatore(tmp_path, modello)
    trovato = separatore.cerca(Image.new("RGB", (200, 100)), ["hand", "elbow"])
    assert modello.intere == 2 and separatore.una_volta_sola is False
    assert trovato["elbow"] == [((0.0, 0.0, 0.5, 0.2), pytest.approx(0.9))]


class _Cercatore:

    def __init__(self, guasto_su: str | None = None):
        self.viste = 0
        self.chieste: list[list[str]] = []
        self.spento = 0
        self.guasto_su = guasto_su

    def cerca(self, immagine, parole, sicurezza_minima=None):
        self.viste += 1
        self.chieste.append(list(parole))
        if self.guasto_su in parole:
            raise RuntimeError("rotto")
        return {parola: [((0.1, 0.1, 0.2, 0.2), 0.9)] if parola == "hand" else []
                for parola in parole}

    def spegni(self):
        self.spento += 1


def _foto_con_persone(archivio, quante: int) -> list[int]:
    with archivio.scrittura() as connessione:
        scatti = [riga[0] for riga in connessione.execute(
            "SELECT id FROM scatti WHERE genere = 'foto' ORDER BY id LIMIT ?", (quante,))]
        for scatto_id in scatti:
            _due_persone(connessione, scatto_id)
    return scatti


def test_la_passata_cerca_tutte_le_parole_guardando_ogni_foto_una_volta(archivio_pieno):
    from officina.corpi import parti as lavoro

    scatti = _foto_con_persone(archivio_pieno, 3)
    with archivio_pieno.scrittura() as connessione:
        mano = parti.aggiungi(connessione, "Mano", "hand")
        parti.aggiungi(connessione, "Piede", "foot")
    cercatore = _Cercatore()
    passata = lavoro.Passata(archivio_pieno, cercatore=cercatore)
    assert passata.quanti_mancano() == 3
    fatto = passata.esegui()
    assert (fatto.fatti, fatto.parti, fatto.saltati) == (3, 3, 0)
    assert cercatore.viste == 3 and cercatore.spento == 1
    assert all(parole == ["hand", "foot"] for parole in cercatore.chieste)
    with archivio_pieno.lettura() as connessione:
        assert sorted(parti.scatti_con(connessione, mano)) == sorted(scatti)
        assert parti.quanti_mancano(connessione) == 0
        prima = parti.di_scatto(connessione, scatti[0])
    assert len(prima) == 1 and prima[0]["corpo_id"] is not None

    with archivio_pieno.scrittura() as connessione:
        parti.aggiungi(connessione, "Gomito", "elbow")
    dopo = _Cercatore()
    lavoro.Passata(archivio_pieno, cercatore=dopo).esegui()
    assert dopo.chieste == [["elbow"]] * 3


def test_la_passata_si_ferma_quando_glielo_dicono(archivio_pieno):
    from officina.corpi import parti as lavoro

    _foto_con_persone(archivio_pieno, 3)
    with archivio_pieno.scrittura() as connessione:
        parti.aggiungi(connessione, "Mano", "hand")
    cercatore = _Cercatore()
    passata = lavoro.Passata(archivio_pieno, cercatore=cercatore,
                             fermato=lambda: cercatore.viste >= 1)
    passata.esegui()
    assert cercatore.viste == 1 and passata.quanti_mancano() == 2


def test_una_foto_che_non_si_lascia_guardare_non_ferma_le_altre(archivio_pieno):
    from officina.corpi import parti as lavoro

    _foto_con_persone(archivio_pieno, 2)
    with archivio_pieno.scrittura() as connessione:
        parti.aggiungi(connessione, "Mano", "hand")
    cercatore = _Cercatore(guasto_su="hand")
    fatto = lavoro.Passata(archivio_pieno, cercatore=cercatore).esegui()
    assert (fatto.fatti, fatto.saltati) == (0, 2)
    with archivio_pieno.lettura() as connessione:
        assert parti.quanti_mancano(connessione) == 0
        assert [riga[0] for riga in connessione.execute(
            "SELECT quante FROM parti_guardate")] == [lavoro.NON_LETTO] * 2


def test_la_prova_mostra_cosa_trova_senza_salvare_niente(archivio_pieno):
    from officina.corpi import parti as lavoro

    scatti = _foto_con_persone(archivio_pieno, 2)
    cercatore = _Cercatore()
    esito = lavoro.prova(archivio_pieno, " Hand ", quanti=5, cercatore=cercatore)
    assert sorted(voce["scatto_id"] for voce in esito) == sorted(scatti)
    assert esito[0]["trovate"] == [{"riquadro": [0.1, 0.1, 0.2, 0.2], "sicurezza": 0.9}]
    assert all(voce["file_id"] for voce in esito)
    assert cercatore.spento == 0
    with archivio_pieno.lettura() as connessione:
        assert parti.elenco(connessione) == []
        assert connessione.execute("SELECT count(*) FROM parti_trovate").fetchone()[0] == 0
    with pytest.raises(parti.ParteSbagliata):
        lavoro.prova(archivio_pieno, "mano è", cercatore=cercatore)


def test_la_galleria_si_filtra_per_parte(archivio):
    from officina.modello import scatti
    from officina.web import vista

    with archivio.scrittura() as connessione:
        con, senza = _scatto(connessione), _scatto(connessione)
        mano = parti.aggiungi(connessione, "Mani", "hand")
        piede = parti.aggiungi(connessione, "Piedi", "foot")
        parti.salva(connessione, con, None, mano, [(0, (0.1, 0.1, 0.2, 0.2), 0.9)],
                    "sam3", "1")
        parti.salva(connessione, senza, None, mano, [], "sam3", "1")
        filtro = vista.filtro_da_parametri({"parte": str(mano)})
        trovati = [riga["id"] for riga in scatti.pagina(connessione, filtro, 0, 10)]
        nessuno = scatti.pagina(connessione, scatti.Filtro(parti=[mano, piede]), 0, 10)
    assert trovati == [con]
    assert nessuno == []
    assert vista.parametri_da_filtro(filtro) == {"parte": str(mano)}
    assert not filtro.e_vuoto()
    assert filtro.copia_con().parti == [mano] and filtro.copia_con().parti is not filtro.parti


def test_la_ricerca_capisce_il_nome_di_una_parte(archivio):
    from officina import ricerca

    with archivio.scrittura() as connessione:
        mano = parti.aggiungi(connessione, "Mani", "hand")
        capiti = [capito for _pezzo, capito in ricerca._cosa_riconosco(
            connessione, "foto con mani")]
    assert [(c.genere, c.numero) for c in capiti] == [("parte", mano)]


def test_il_nodo_lo_sceglie_chi_usa_il_programma(archivio):
    from officina.modello import nodi

    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        nodo = nodi.crea(connessione, "Un nodo", None)
        mano = parti.aggiungi(connessione, "Mani", "hand")
        piede = parti.aggiungi(connessione, "Piedi", "foot")
        parti.scegli_il_nodo(connessione, mano, nodo)
        for parte in (mano, piede):
            parti.salva(connessione, scatto_id, None, parte,
                        [(0, (0.1, 0.1, 0.2, 0.2), 0.9), (0, (0.6, 0.6, 0.2, 0.2), 0.7)],
                        "sam3", "1")
        consigli = parti.consigli(connessione, scatto_id)
        with pytest.raises(parti.ParteSbagliata):
            parti.scegli_il_nodo(connessione, piede, 999999)
        parti.scegli_il_nodo(connessione, mano, None)
        senza = parti.consigli(connessione, scatto_id)
    assert [(c["nome"], c["nodo_id"], len(c["zone"])) for c in consigli] == [
        ("Mani", nodo, 2), ("Piedi", None, 2)]
    assert consigli[0]["nodo_nome"] == "Un nodo"
    assert consigli[0]["zone"][0]["riquadro"] == [0.1, 0.1, 0.2, 0.2]
    assert [c["nodo_id"] for c in senza] == [None, None]
