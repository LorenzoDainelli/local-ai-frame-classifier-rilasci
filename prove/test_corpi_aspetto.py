from __future__ import annotations

import json
from types import SimpleNamespace

import numpy
import pytest
from PIL import Image

from officina.corpi.rilevatore import PUNTI, Corpo


def punti_finti(x=0.2, y=0.15):
    punti = [(0.0, 0.0, 0.0)] * PUNTI
    for i in range(17):
        punti[i] = (x + i * 0.003, y + i * 0.02, 0.9)
    return punti


def corpo_finto(x=0.1):
    return Corpo((x, 0.1, 0.3, 0.8), 0.9, b"", punti_finti(x + 0.1))


class Acceso:

    def __init__(self, nome, diario):
        self.nome = nome
        self.diario = diario
        self.su = False

    def accendi(self):
        if not self.su:
            self.diario.append(("su", self.nome))
        self.su = True

    def spegni(self):
        if self.su:
            self.diario.append(("giu", self.nome))
        self.su = False


class SeparatoreFinto(Acceso):

    def trova(self, immagine):
        assert self.su
        return [((10.0, 10.0, 60.0, 90.0), 0.9, numpy.ones((80, 50), dtype=bool))]


class PoseFinta(Acceso):

    def punti(self, immagine, riquadri):
        return [punti_finti() for _ in riquadri]


class KprFinto(Acceso):

    def __init__(self, versione, diario, parti=9):
        super().__init__(versione, diario)
        self.versione = versione
        self.parti = parti

    def guarda_preparati(self, preparati):
        assert self.su
        fuori = []
        for numero, _ in enumerate(preparati):
            vettore = numpy.full((self.parti, 512), 0.1 * (numero + 1), dtype=numpy.float32)
            fuori.append((vettore, numpy.ones(self.parti, dtype=numpy.float32)))
        return fuori


class VestitiFinti:

    scheda = SimpleNamespace(lato=384)

    def __init__(self, diario):
        self.diario = diario
        self.aperto = False

    def apri(self):
        if not self.aperto:
            self.diario.append(("su", "siglip2"))
        self.aperto = True

    def chiudi(self):
        if self.aperto:
            self.diario.append(("giu", "siglip2"))
        self.aperto = False

    def descrivi(self, immagini):
        assert self.aperto
        assert all(i.size == (384, 384) for i in immagini)
        return [[1.0 / 1152 ** 0.5] * 1152 for _ in immagini]


def rilevatore_finto(tmp_path, tutti_accesi, monkeypatch):
    import officina.corpi as corpi_pacchetto

    monkeypatch.setattr(corpi_pacchetto, "cosa_manca", lambda cartella: "")
    diario = []
    rilevatore = corpi_pacchetto.Rilevatore(tmp_path, tutti_accesi=tutti_accesi)
    rilevatore.separatore = SeparatoreFinto("sam3", diario)
    rilevatore.pose = PoseFinta("rtmw", diario)
    rilevatore.aspetti = [KprFinto("posetrack", diario), KprFinto("market", diario, 6),
                          KprFinto("duke", diario)]
    rilevatore.vestiti = VestitiFinti(diario)

    def prepara(immagine, corpi):
        return ([object() for _ in corpi],
                [Image.new("RGB", (384, 384), (128, 128, 128)) for _ in corpi])

    monkeypatch.setattr(rilevatore, "_prepara", prepara)
    return rilevatore, diario


def accesi_insieme(diario):
    accesi, massimo = set(), 0
    for cosa, nome in diario:
        if nome == "rtmw":
            continue
        if cosa == "su":
            accesi.add(nome)
        else:
            accesi.discard(nome)
        massimo = max(massimo, len(accesi))
    return massimo


def test_a_turno_si_accende_un_modello_alla_volta(tmp_path, monkeypatch):
    rilevatore, diario = rilevatore_finto(tmp_path, False, monkeypatch)
    assert rilevatore.quanti_insieme > 1
    rilevatore.accendi()
    lotti = [rilevatore.trova_e_prepara(Image.new("RGB", (64, 100))) for _ in range(3)]
    guasti = rilevatore.completa(lotti)
    assert guasti == [None, None, None]
    assert accesi_insieme(diario) == 1
    accesi = [nome for cosa, nome in diario if cosa == "su" and nome != "rtmw"]
    assert accesi == ["sam3", "posetrack", "market", "duke", "siglip2"]
    for corpi, _ in lotti:
        corpo = corpi[0]
        assert set(corpo.aspetto) == {"kpr-posetrack", "kpr-market", "kpr-duke"}
        assert corpo.aspetto["kpr-market"][0].shape == (6, 512)
        assert len(corpo.vestiti) == 1152


def test_con_tanta_memoria_restano_tutti_accesi(tmp_path, monkeypatch):
    rilevatore, diario = rilevatore_finto(tmp_path, True, monkeypatch)
    assert rilevatore.quanti_insieme == 1
    rilevatore.accendi()
    for _ in range(3):
        rilevatore.guarda(Image.new("RGB", (64, 100)))
    assert not [cosa for cosa, _ in diario if cosa == "giu"]
    assert accesi_insieme(diario) == 5
    rilevatore.spegni()
    assert accesi_insieme(diario) == 5
    assert all(cosa == "giu" for cosa, _ in diario[-5:])


def test_la_memoria_decide_se_tenere_tutto_acceso():
    import officina.corpi as corpi_pacchetto
    from officina.descrittori.torcia import Macchina

    assert corpi_pacchetto.c_e_posto_per_tutti(Macchina("cuda", "grande", 16_000_000_000))
    assert not corpi_pacchetto.c_e_posto_per_tutti(Macchina("cuda", "piccola", 8_000_000_000))


def test_un_modello_che_non_si_accende_ferma_tutto(tmp_path, monkeypatch):
    import officina.corpi as corpi_pacchetto

    rilevatore, _ = rilevatore_finto(tmp_path, False, monkeypatch)

    def rotto():
        raise RuntimeError("memoria finita")

    monkeypatch.setattr(rilevatore.aspetti[1], "accendi", rotto)
    lotti = [rilevatore.trova_e_prepara(Image.new("RGB", (64, 100)))]
    with pytest.raises(corpi_pacchetto.NonSiAccende):
        rilevatore.completa(lotti)


def test_una_foto_che_si_rompe_non_rovina_le_altre(tmp_path, monkeypatch):
    rilevatore, _ = rilevatore_finto(tmp_path, False, monkeypatch)
    lotti = [rilevatore.trova_e_prepara(Image.new("RGB", (64, 100))) for _ in range(3)]
    originale = rilevatore.aspetti[0].guarda_preparati
    volte = {"n": 0}

    def a_volte(preparati):
        volte["n"] += 1
        if volte["n"] == 2:
            raise ValueError("ritaglio strano")
        return originale(preparati)

    monkeypatch.setattr(rilevatore.aspetti[0], "guarda_preparati", a_volte)
    guasti = rilevatore.completa(lotti)
    assert guasti[0] is None and guasti[2] is None
    assert isinstance(guasti[1], ValueError)
    assert "kpr-market" not in lotti[1][0][0].aspetto
    assert lotti[1][0][0].vestiti is None


def test_fermarsi_a_meta_interrompe_il_turno(tmp_path, monkeypatch):
    import officina.corpi as corpi_pacchetto

    rilevatore, _ = rilevatore_finto(tmp_path, False, monkeypatch)
    lotti = [rilevatore.trova_e_prepara(Image.new("RGB", (64, 100))) for _ in range(2)]
    with pytest.raises(corpi_pacchetto.Interrotta):
        rilevatore.completa(lotti, fermato=lambda: True)


def _scatto(connessione) -> int:
    connessione.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    return connessione.execute("SELECT max(id) FROM scatti").fetchone()[0]


def test_corporatura_e_vestiti_si_salvano_a_32_bit_identici(archivio):
    from officina.corpi import VESTITI
    from officina.modello import corpi

    rng = numpy.random.default_rng(5)
    corpo = corpo_finto()
    vettore = rng.standard_normal((9, 512)).astype(numpy.float32)
    visibili = numpy.array([1, 1, 0, 1, 1, 0, 0, 1, 1], dtype=numpy.float32)
    corpo.aspetto = {"kpr-posetrack": (vettore, visibili)}
    corpo.vestiti = rng.standard_normal(1152).astype(numpy.float32).tolist()
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        corpi.salva(connessione, scatto_id, None, [(0, corpo)], "corpi", "2")
        corpo_id = connessione.execute("SELECT id FROM corpi WHERE scatto_id = ?",
                                       (scatto_id,)).fetchone()[0]
    with archivio.lettura() as connessione:
        letto = corpi.aspetto_di(connessione, corpo_id)
        peso = connessione.execute(
            "SELECT sum(length(vettore)) FROM aspetti WHERE corpo_id = ?", (corpo_id,)).fetchone()[0]
    assert numpy.array_equal(letto["kpr-posetrack"][0], vettore)
    assert letto["kpr-posetrack"][0].dtype == numpy.dtype("<f4")
    assert letto["kpr-posetrack"][1].tolist() == [bool(v) for v in visibili]
    assert numpy.array_equal(letto[VESTITI][0], numpy.asarray(corpo.vestiti, dtype=numpy.float32))
    assert letto[VESTITI][1] is None
    assert peso == (9 * 512 + 1152) * 4


def test_rifare_lo_scatto_toglie_anche_la_versione_vecchia(archivio):
    from officina.modello import corpi

    corpo = corpo_finto()
    corpo.aspetto = {"kpr-duke": (numpy.zeros((9, 512), numpy.float32), numpy.ones(9))}
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        corpi.salva(connessione, scatto_id, None, [(0, corpo)], "corpi", "1-vecchia")
        corpi.salva(connessione, scatto_id, None, [(0, corpo), (0, corpo_finto(0.5))],
                    "corpi", "2-nuova")
    with archivio.lettura() as connessione:
        versioni = [r[0] for r in connessione.execute(
            "SELECT versione FROM corpi WHERE scatto_id = ?", (scatto_id,))]
        guardati = [r[0] for r in connessione.execute(
            "SELECT versione FROM corpi_guardati WHERE scatto_id = ?", (scatto_id,))]
        aspetti = connessione.execute(
            "SELECT count(*) FROM aspetti a JOIN corpi c ON c.id = a.corpo_id "
            "WHERE c.scatto_id = ?", (scatto_id,)).fetchone()[0]
        orfani = connessione.execute(
            "SELECT count(*) FROM aspetti WHERE corpo_id NOT IN (SELECT id FROM corpi)").fetchone()[0]
    assert versioni == ["2-nuova", "2-nuova"]
    assert guardati == ["2-nuova"]
    assert aspetti == 1 and orfani == 0


def test_togliere_lo_scatto_toglie_corporatura_e_vestiti(archivio):
    from officina.modello import corpi

    corpo = corpo_finto()
    corpo.vestiti = [0.5] * 1152
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        corpi.salva(connessione, scatto_id, None, [(0, corpo)], "corpi", "2")
        connessione.execute("DELETE FROM scatti WHERE id = ?", (scatto_id,))
    with archivio.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM aspetti").fetchone()[0] == 0


class RilevatoreATurni:

    versione = "2-finto"
    quanti_insieme = 4
    quadri_insieme = 3

    def __init__(self, rotto_su=(), non_si_accende=False):
        self.rotto_su = set(rotto_su)
        self.non_si_accende = non_si_accende
        self.trovati = 0
        self.completati = []
        self.spento = False
        self.interi = []

    def accendi(self):
        pass

    def trova_e_prepara(self, lavoro, intera=None):
        self.trovati += 1
        self.interi.append((lavoro.size, intera.size if intera is not None else None))
        return [corpo_finto()], ("preparati", self.trovati)

    def completa(self, lotti, fermato=None):
        if self.non_si_accende:
            import officina.corpi as corpi_pacchetto

            raise corpi_pacchetto.NonSiAccende("la scheda video non risponde")
        self.completati.append(len(lotti))
        guasti = []
        for corpi, (_, numero) in lotti:
            if numero in self.rotto_su:
                guasti.append(ValueError("rotto"))
                continue
            for corpo in corpi:
                corpo.aspetto["kpr-posetrack"] = (numpy.ones((9, 512), numpy.float32),
                                                  numpy.ones(9))
                corpo.vestiti = [0.25] * 1152
            guasti.append(None)
        return guasti

    def spegni(self):
        self.spento = True


def test_la_passata_a_turni_salva_corporatura_e_vestiti(archivio_pieno):
    from officina.corpi.motore import Passata

    finto = RilevatoreATurni()
    passata = Passata(archivio_pieno, rilevatore=finto, intensita=100)
    totale = passata.quanti_mancano()
    fatto = passata.esegui()
    assert fatto.fatti + fatto.saltati == totale
    assert finto.spento
    assert finto.completati and max(finto.completati) <= finto.quadri_insieme + 2
    assert sum(finto.completati) == finto.trovati
    with archivio_pieno.lettura() as connessione:
        con_aspetto = connessione.execute(
            "SELECT count(DISTINCT corpo_id) FROM aspetti").fetchone()[0]
        corpi_salvati = connessione.execute("SELECT count(*) FROM corpi").fetchone()[0]
    assert con_aspetto == corpi_salvati == fatto.corpi


def test_la_foto_intera_arriva_ai_ritagli(archivio_pieno):
    from officina.corpi.motore import LATO_DI_LAVORO, Passata

    finto = RilevatoreATurni()
    Passata(archivio_pieno, rilevatore=finto, intensita=100).esegui()
    assert finto.interi
    for lavoro, intera in finto.interi:
        assert intera is not None
        assert max(lavoro) <= LATO_DI_LAVORO
        assert max(intera) >= max(lavoro)


def test_nella_passata_a_turni_una_foto_rotta_si_segnala(archivio_pieno):
    from officina.corpi.motore import Passata
    from officina.modello import segnalazioni

    passata = Passata(archivio_pieno, rilevatore=RilevatoreATurni(rotto_su={2}), intensita=100)
    fatto = passata.esegui()
    assert fatto.saltati >= 1
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.CORPI_NON_LETTI) >= 1


def test_se_un_modello_non_si_accende_a_meta_nessuno_scatto_viene_segnato(archivio_pieno):
    from officina.corpi.motore import Passata
    from officina.errori import ErroreOfficina
    from officina.modello import segnalazioni

    passata = Passata(archivio_pieno, rilevatore=RilevatoreATurni(non_si_accende=True),
                      intensita=100)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "corpi_non_si_accendono"
    assert passata.quanti_mancano() == prima
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.CORPI_NON_LETTI) == 0


def test_fermare_la_passata_a_turni_non_salva_il_gruppo_a_meta(archivio_pieno):
    from officina.corpi.motore import Passata

    class SiFerma(RilevatoreATurni):
        def completa(self, lotti, fermato=None):
            import officina.corpi as corpi_pacchetto

            passata.ferma()
            if fermato and fermato():
                raise corpi_pacchetto.Interrotta()
            return super().completa(lotti, fermato)

    passata = Passata(archivio_pieno, rilevatore=SiFerma(), intensita=100)
    prima = passata.quanti_mancano()
    fatto = passata.esegui()
    assert fatto.fatti == 0
    assert passata.quanti_mancano() == prima


def test_senza_siglip2_i_corpi_non_partono(tmp_path, monkeypatch):
    from officina.corpi import kpr_pesi, rilevatore

    monkeypatch.setattr(rilevatore, "c_e_onnxruntime", lambda: True)
    monkeypatch.setattr(rilevatore, "c_e_transformers", lambda: True)
    casa = rilevatore.dove_stanno(tmp_path)
    (casa / rilevatore.CARTELLA_SAM3).mkdir(parents=True)
    (casa / rilevatore.CARTELLA_SAM3 / rilevatore.PROVA_SAM3).write_text("{}")
    (casa / rilevatore.FILE_POSE).write_bytes(b"onnx finto")
    assert "scaricati" in rilevatore.cosa_manca(tmp_path)
    kpr_casa = kpr_pesi.dove_stanno(tmp_path)
    kpr_casa.mkdir(parents=True)
    for pesi in kpr_pesi.PESI:
        (kpr_casa / f"kpr-{pesi.versione}.safetensors").write_bytes(b"finto")
        (kpr_casa / f"kpr-{pesi.versione}.json").write_text("{}")
    assert "SigLIP 2" in rilevatore.cosa_manca(tmp_path)
    (tmp_path / "siglip2").mkdir()
    (tmp_path / "siglip2" / "config.json").write_text("{}")
    assert rilevatore.cosa_manca(tmp_path) == ""


def test_scaricare_i_corpi_porta_anche_kpr(tmp_path, monkeypatch):
    from officina.corpi import kpr_pesi, rilevatore, scaricamento

    casa = rilevatore.dove_stanno(tmp_path)

    def sam3(dove, *_):
        dove.mkdir(parents=True, exist_ok=True)
        (dove / rilevatore.PROVA_SAM3).write_text("{}")

    def pose(dove, *_):
        dove.write_bytes(b"onnx finto")

    chiesti = []

    def kpr(cartella_modelli, al_passo=None, a_che_punto=None, rifai=False):
        chiesti.append(cartella_modelli)
        kpr_casa = kpr_pesi.dove_stanno(cartella_modelli)
        kpr_casa.mkdir(parents=True, exist_ok=True)
        for numero, pesi in enumerate(kpr_pesi.PESI):
            if a_che_punto:
                a_che_punto(10, pesi.byte)
                a_che_punto(pesi.byte, pesi.byte)
            (kpr_casa / f"kpr-{pesi.versione}.safetensors").write_bytes(b"finto")
            (kpr_casa / f"kpr-{pesi.versione}.json").write_text("{}")
        return []

    def figure(casa, *_):
        for pezzo in scaricamento.FIGURE:
            (casa / pezzo.dove).parent.mkdir(parents=True, exist_ok=True)
            (casa / pezzo.dove).write_bytes(b"finto")

    monkeypatch.setattr(scaricamento, "_scarica_sam3", sam3)
    monkeypatch.setattr(scaricamento, "_scarica_la_pose", pose)
    monkeypatch.setattr(kpr_pesi, "scarica", kpr)
    monkeypatch.setattr(scaricamento, "_scarica_le_figure", figure)
    punti = []
    scaricamento.scarica(tmp_path, a_che_punto=lambda fatti, totale: punti.append((fatti, totale)))
    assert chiesti == [tmp_path]
    assert scaricamento.gia_in_casa(tmp_path)
    assert punti and all(totale == scaricamento.BYTE_IN_TUTTO for _, totale in punti)
    assert [f for f, _ in punti] == sorted(f for f, _ in punti)
    scheda = json.loads((casa / scaricamento.SCHEDA_SUL_DISCO).read_text(encoding="utf-8"))
    assert "kpr" in scheda["da_dove"]
    assert "kpr/kpr-duke.safetensors" in scheda["impronte"]
    assert "corpo3d/model.ckpt" in scheda["impronte"] and "obiettivo/lingua/config.json" in scheda["impronte"]
    assert scaricamento.verifica(tmp_path)["stato"] == "intatto"


def test_se_drive_non_lascia_scaricare_kpr_si_spiega(tmp_path, monkeypatch):
    from officina.corpi import kpr_pesi, rilevatore, scaricamento
    from officina.descrittori.scaricamento import ScaricamentoFallito
    from officina.errori import ErroreOfficina

    def sam3(dove, *_):
        dove.mkdir(parents=True, exist_ok=True)
        (dove / rilevatore.PROVA_SAM3).write_text("{}")

    def chiuso(*_, **__):
        raise ErroreOfficina("Google Drive in questo momento non lascia scaricare il file.",
                             codice="drive_chiuso")

    monkeypatch.setattr(scaricamento, "_scarica_sam3", sam3)
    monkeypatch.setattr(scaricamento, "_scarica_la_pose", lambda dove, *_: dove.write_bytes(b"x"))
    monkeypatch.setattr(kpr_pesi, "scarica", chiuso)
    with pytest.raises(ScaricamentoFallito) as preso:
        scaricamento.scarica(tmp_path)
    assert "KPR" in preso.value.messaggio and "Google Drive" in preso.value.messaggio
    assert not scaricamento.gia_in_casa(tmp_path)


def test_la_sagoma_esce_della_misura_di_siglip2():
    from officina.corpi import maschere, vestiti

    immagine = Image.new("RGB", (1000, 800), (200, 30, 30))
    forma = numpy.zeros((40, 20), dtype=bool)
    forma[5:35, 5:15] = True
    quadro = vestiti.sagoma(immagine, (0.1, 0.1, 0.2, 0.5), maschere.comprimi(forma),
                            lato_finale=384)
    assert quadro.size == (384, 384)
    assert quadro.getpixel((2, 2)) == vestiti.GRIGIO
    assert quadro.getpixel((192, 192))[0] > 150


def test_i_ritagli_preparati_danno_gli_stessi_numeri_di_prima(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from safetensors.torch import save_file

    from officina.corpi import kpr, kpr_pesi, kpr_rete

    scheda = kpr_pesi.scheda_dal_pacco(
        {"config": {"model": {"kpr": {"masks": {"parts_num": 5, "prompt_parts_num": 6},
                                      "keypoints": {"prompt_preprocess": "cck6"}}}}},
        kpr_pesi.PESI[1])
    torch.manual_seed(0)
    modello = kpr_rete.KPR(kpr_rete.Configurazione(scheda)).eval()
    save_file({k: v.contiguous() for k, v in modello.state_dict().items()
               if not k.startswith(kpr_rete.DOPPIONE)}, str(tmp_path / "kpr-prova.safetensors"))
    (tmp_path / "kpr-prova.json").write_text(json.dumps(scheda))
    riconoscitore = kpr.Riconoscitore(tmp_path, "prova")
    rng = numpy.random.default_rng(1)
    immagine = Image.fromarray(rng.integers(0, 255, (600, 400, 3), dtype=numpy.uint8))
    persone = [((20, 30, 180, 560), punti_finti(0.1, 0.1)),
               ((150, 40, 390, 590), punti_finti(0.5, 0.1))]
    nuovi = riconoscitore.guarda(immagine, persone)
    riconoscitore.accendi()
    conf = riconoscitore.conf
    immagini, suggerimenti = [], []
    for indice, (riquadro, punti) in enumerate(persone):
        tensore, tagliato = kpr.ritaglio(immagine, riquadro, conf)
        mio = kpr.nel_ritaglio(punti, tagliato, 400, 600, conf.larghezza, conf.altezza)
        altri = [kpr.nel_ritaglio(p, tagliato, 400, 600, conf.larghezza, conf.altezza)
                 for j, (_, p) in enumerate(persone) if j != indice]
        immagini.append(tensore)
        suggerimenti.append(torch.from_numpy(kpr.suggerimento(mio, altri, conf)))
    with torch.inference_mode():
        vecchi, visibili = riconoscitore._modello(torch.stack(immagini), torch.stack(suggerimenti))
    for (nuovo, suoi), vecchio, vis in zip(nuovi, vecchi.numpy(), visibili.numpy(), strict=True):
        assert numpy.allclose(nuovo, vecchio, atol=1e-6)
        assert numpy.array_equal(suoi, vis.astype(numpy.float32))
