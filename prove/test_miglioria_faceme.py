from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from officina.miglioria import faceme, faceme_pesi, motori, persone, scaricamento

FRONTALE = ((192.98, 239.95), (318.90, 240.19), (256.63, 314.02),
            (201.26, 371.41), (313.09, 371.15))


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def test_il_manifesto_vero_e_completo():
    atteso = faceme_pesi.manifesto()
    assert len(atteso["commit"]) == 40 and "Pi-Lab" in atteso["licenza"]
    assert atteso["antelope"]["indirizzo"].startswith(
        "https://github.com/deepinsight/insightface/releases/download/")
    assert {n.rsplit("/", 1)[1] for n in atteso["antelope"]["file"]} == {
        faceme_pesi.RILEVATORE, faceme_pesi.IMPRONTA}
    assert all(len(s) == 64 for s in atteso["antelope"]["file"].values())
    assert atteso["base"] == "SG161222/RealVisXL_V3.0"
    assert atteso["photomaker"]["file"] == "photomaker-v1.bin"
    assert motori.VOLTI[motori.FACEME] == "officina.miglioria.faceme:FaceMe"


def test_la_posa_frontale_e_quella_girata():
    girata, alzata = faceme.posa(FRONTALE)
    assert abs(girata) < 0.05 and 0.4 < alzata < 0.7
    storta = list(FRONTALE)
    storta[2] = (300.0, 314.0)
    assert faceme.posa(storta)[0] > 0.3


def test_sceglie_le_4_piu_nitide_fra_le_8_con_la_posa_piu_vicina():
    riferimenti = [{"posa": (i / 10, 0.5), "nitidezza": n, "nome": i}
                   for i, n in enumerate([1, 9, 2, 8, 3, 7, 4, 6, 99, 99])]
    scelti = faceme.scegli(riferimenti, (0.0, 0.5))
    assert [r["nome"] for r in scelti] == [1, 3, 5, 7]
    pochi = faceme.scegli(riferimenti[:2], (0.0, 0.5))
    assert len(pochi) == 4 and {r["nome"] for r in pochi} == {0, 1}
    assert faceme.scegli([], (0.0, 0.5)) == []


def test_il_volto_si_riconosce_dal_riquadro_dell_archivio():
    anna = {"persona_id": 1, "riquadri": [[0.40, 0.20, 0.10, 0.12]]}
    bruno = {"persona_id": 2, "riquadri": [[0.70, 0.20, 0.10, 0.12]]}
    assert faceme.chi_e((0.41, 0.21, 0.10, 0.12), [anna, bruno]) is anna
    assert faceme.chi_e((0.71, 0.19, 0.09, 0.12), [anna, bruno]) is bruno
    assert faceme.chi_e((0.10, 0.60, 0.10, 0.12), [anna, bruno]) is None


def test_della_base_prende_la_versione_a_sedici_bit():
    file = {n: (1, None) for n in (
        "unet/config.json", "unet/diffusion_pytorch_model.safetensors",
        "unet/diffusion_pytorch_model.fp16.safetensors",
        "vae/config.json", "vae/diffusion_pytorch_model.safetensors",
        "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
        "text_encoder_2/config.json", "text_encoder_2/model.safetensors",
        "scheduler/scheduler_config.json", "tokenizer/vocab.json",
        "tokenizer_2/merges.txt", "RealVisXL_V3.0.safetensors")}
    scelti = faceme_pesi.scegli_della_base(file)
    assert scelti["unet/diffusion_pytorch_model.fp16.safetensors"] == \
        "base/unet/diffusion_pytorch_model.safetensors"
    assert "unet/diffusion_pytorch_model.safetensors" not in scelti
    assert scelti["text_encoder/model.fp16.safetensors"] == \
        "appunti/text_encoder/model.safetensors"
    assert scelti["tokenizer/vocab.json"] == "appunti/tokenizer/vocab.json"
    assert "RealVisXL_V3.0.safetensors" not in scelti
    del file["vae/diffusion_pytorch_model.safetensors"]
    with pytest.raises(faceme_pesi.PreparazioneFallita):
        faceme_pesi.scegli_della_base(file)


def test_di_faceme_trova_la_rete_di_controllo_e_il_miscelatore():
    file = {n: (1, None) for n in (
        "README.md", "controlnet/config.json",
        "controlnet/diffusion_pytorch_model.safetensors", "mix/mix.safetensors")}
    assert faceme_pesi.scegli_di_faceme(file) == {
        "mix/mix.safetensors": "mix.safetensors",
        "controlnet/config.json": "controlnet/config.json",
        "controlnet/diffusion_pytorch_model.safetensors":
            "controlnet/diffusion_pytorch_model.safetensors"}
    with pytest.raises(faceme_pesi.PreparazioneFallita):
        faceme_pesi.scegli_di_faceme({"README.md": (1, None)})


def _zip(contenuti: dict[str, bytes]) -> bytes:
    fuori = io.BytesIO()
    with zipfile.ZipFile(fuori, "w") as pacco:
        for nome, dati in contenuti.items():
            pacco.writestr(nome, dati)
    return fuori.getvalue()


@pytest.fixture
def finto(tmp_path, monkeypatch):
    onnx = {"antelopev2/glintr100.onnx": b"impronta-finta",
            "antelopev2/scrfd_10g_bnkps.onnx": b"rilevatore-finto"}
    pacco = _zip(onnx)
    terzi = tmp_path / "terzi"
    terzi.mkdir()
    (terzi / "faceme.json").write_text(json.dumps({
        "deposito": "esempio/faceme", "commit": "abc", "licenza": "Pi-Lab License 1.0",
        "antelope": {"indirizzo": "https://esempio/antelopev2.zip", "sha256": _sha(pacco),
                     "byte": len(pacco), "file": {n: _sha(d) for n, d in onnx.items()}},
        "base": "esempio/base", "faceme": "esempio/faceme",
        "photomaker": {"repo": "esempio/pm", "file": "photomaker-v1.bin"},
        "byte_circa": 1000}), encoding="utf-8")
    monkeypatch.setattr(scaricamento, "TERZI", terzi)
    monkeypatch.setattr(faceme_pesi, "_controlla_lo_spazio", lambda cartella, serve: None)
    depositi = {
        "esempio/base": {n: b"x-" + n.encode() for n in (
            "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
            "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors",
            "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
            "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
            "scheduler/scheduler_config.json", "tokenizer/vocab.json",
            "tokenizer_2/vocab.json")},
        "esempio/faceme": {n: b"x-" + n.encode() for n in (
            "controlnet/config.json", "controlnet/diffusion_pytorch_model.safetensors",
            "mix/mix.safetensors")},
        "esempio/pm": {"photomaker-v1.bin": b"pickle-finto"},
    }
    rete = {"accesa": False}
    stato = {"chiesti": [], "rete_alle_conversioni": [], "dichiarate": {}}

    def accendi():
        prima = dict(rete)
        rete["accesa"] = True
        return prima

    monkeypatch.setattr(faceme_pesi.torcia, "con_la_rete_accesa", accendi)
    monkeypatch.setattr(faceme_pesi.torcia, "rimetti_la_rete_com_era",
                        lambda prima: rete.update(prima))

    def elenca(repo, chiave):
        return f"rev-{repo}", {n: (len(d), stato["dichiarate"].get(n, _sha(d)))
                               for n, d in depositi[repo].items()}

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        assert revisione == f"rev-{repo}"
        stato["chiesti"].append(nome)
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(depositi[repo][nome])
        return posto

    def prendi_url(indirizzo, arrivo, al_byte):
        arrivo.write_bytes(pacco)

    def occhio(sorgente, arrivo):
        stato["rete_alle_conversioni"].append(rete["accesa"])
        assert sorgente.read_bytes() == b"pickle-finto"
        arrivo.write_bytes(b"occhio")

    def testo(appunti, arrivo):
        stato["rete_alle_conversioni"].append(rete["accesa"])
        assert (appunti / "text_encoder_2" / "model.safetensors").is_file()
        arrivo.write_bytes(b"testo")

    stato.update(modelli=tmp_path / "modelli", rete=rete, depositi=depositi, opzioni={
        "elenca": elenca, "prendi_hf": prendi_hf, "prendi_url": prendi_url,
        "occhio": occhio, "testo": testo})
    return stato


def test_scarica_verifica_prepara_e_mette_al_posto(finto):
    arrivo = faceme_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert faceme_pesi.e_in_casa(finto["modelli"])
    assert not (arrivo / "appunti").exists()
    assert (arrivo / "base" / "unet" / "diffusion_pytorch_model.safetensors").is_file()
    assert (arrivo / "controlnet" / "diffusion_pytorch_model.safetensors").is_file()
    assert (arrivo / faceme_pesi.RILEVATORE).read_bytes() == b"rilevatore-finto"
    scritto = json.loads((arrivo / "pronto.json").read_text(encoding="utf-8"))
    assert scritto["fonti"]["esempio/base"] == "rev-esempio/base"
    assert not any(n.startswith("appunti/") for n in scritto["file"])
    assert finto["rete_alle_conversioni"] == [False, False]
    assert not finto["rete"]["accesa"]
    assert not arrivo.with_name("faceme.nuova").exists()


def test_gia_in_casa_non_riscarica(finto):
    faceme_pesi.scarica(finto["modelli"], **finto["opzioni"])
    finto["chiesti"].clear()
    faceme_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert finto["chiesti"] == []


def test_un_file_diverso_da_quello_dichiarato_non_entra(finto):
    finto["dichiarate"]["mix/mix.safetensors"] = "0" * 64
    with pytest.raises(scaricamento.ScaricamentoFallito):
        faceme_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert not faceme_pesi.e_in_casa(finto["modelli"])
    assert not faceme_pesi.dove(finto["modelli"]).exists()
    assert not finto["rete"]["accesa"]


def test_un_antelope_diverso_non_entra(finto):
    finto["opzioni"]["prendi_url"] = lambda i, arrivo, b: arrivo.write_bytes(b"altro")
    with pytest.raises(scaricamento.ScaricamentoFallito):
        faceme_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert not faceme_pesi.e_in_casa(finto["modelli"])


def test_la_chiave_non_finisce_nel_messaggio(finto):
    def rotto(repo, chiave):
        raise OSError(f"rifiutato con {chiave}")

    finto["opzioni"]["elenca"] = rotto
    with pytest.raises(scaricamento.ScaricamentoFallito) as preso:
        faceme_pesi.scarica(finto["modelli"], chiave="hf_segreto_finto", **finto["opzioni"])
    assert "hf_segreto_finto" not in str(preso.value)


def test_senza_faceme_il_motore_lo_dice(tmp_path):
    from officina.miglioria import lavoro

    with pytest.raises(faceme.MancaFaceMe) as preso:
        faceme.FaceMe(cartella_modelli=str(tmp_path))
    assert lavoro.a_parole(preso.value.codice) != preso.value.codice


def test_senza_persone_con_riferimenti_passa_tutto_da_codeformer():
    motore = object.__new__(faceme.FaceMe)
    chiamate = []

    class Volti:
        def sistema(self, immagine):
            chiamate.append("codeformer")
            return immagine

    motore.volti = Volti()
    assert motore.sistema("foto", [{"persona_id": 1, "riquadri": [], "riferimenti": []}]) \
        == "foto"
    assert chiamate == ["codeformer"]


def test_i_volti_con_un_nome_vanno_a_faceme_gli_altri_a_codeformer():
    from officina.miglioria import codeformer

    motore = object.__new__(faceme.FaceMe)
    usati = []

    class Volti:
        def _rifai(self, ritaglio):
            return "codeformer"

        def sistema_con(self, immagine, chi_rifa):
            for volto in (codeformer.Volto(FRONTALE, (0.4, 0.2, 0.1, 0.12)),
                          codeformer.Volto(FRONTALE, (0.1, 0.6, 0.1, 0.12))):
                usati.append(chi_rifa(volto)("ritaglio"))
            return immagine

    motore.volti = Volti()
    motore._visti = {1: [{"posa": (0.0, 0.5), "nitidezza": 1.0, "nome": "a"}]}
    motore._rifai = lambda ritaglio, scelti: ("faceme", len(scelti))
    anna = {"persona_id": 1, "riquadri": [[0.4, 0.2, 0.1, 0.12]],
            "riferimenti": [{"file": "a.jpg"}]}
    motore.sistema("foto", [anna])
    assert usati == [("faceme", 4), "codeformer"]


@pytest.fixture
def con_persone(archivio_pieno, tmp_path):
    from officina.archivio.database import adesso

    with archivio_pieno.lettura() as connessione:
        foto = [dict(r) for r in connessione.execute(
            "SELECT id, scatto_id FROM file_media WHERE genere = 'immagine' "
            "AND scatto_id IS NOT NULL ORDER BY id LIMIT 3")]
    assert len(foto) == 3
    cartella = tmp_path / "riferimenti-anna"
    cartella.mkdir()
    (cartella / "anna-1.jpg").write_bytes(b"finta")
    with archivio_pieno.scrittura() as c:
        anna = c.execute("INSERT INTO persone (nome, stato, nata_il) "
                         "VALUES ('Anna', 'attiva', ?)", (adesso(),)).lastrowid
        muto = c.execute("INSERT INTO persone (nome, stato, nata_il) "
                         "VALUES (NULL, 'attiva', ?)", (adesso(),)).lastrowid
        via = c.execute("INSERT INTO persone (nome, stato, nata_il) "
                        "VALUES ('Via', 'cestino', ?)", (adesso(),)).lastrowid
        for file, persona, riquadro, nitidezza in (
                (foto[0], anna, "[0.4,0.2,0.1,0.12]", 1.0),
                (foto[0], muto, "[0.7,0.2,0.1,0.12]", 1.0),
                (foto[0], via, "[0.1,0.6,0.1,0.12]", 1.0),
                (foto[1], anna, "[0.3,0.3,0.2,0.2]", 5.0),
                (foto[2], anna, "[0.3,0.3,0.2,0.2]", 2.0)):
            c.execute("INSERT INTO volti (scatto_id, file_id, riquadro, area, nitidezza, "
                      "sicurezza, modello, versione, persona_id, trovato_il) "
                      "VALUES (?, ?, ?, 0.01, ?, 0.9, 'volti', '1', ?, ?)",
                      (file["scatto_id"], file["id"], riquadro, nitidezza, persona, adesso()))
        c.execute("INSERT INTO cartelle_riferimento (persona_id, percorso, data_il) "
                  "VALUES (?, ?, ?)", (anna, str(cartella), adesso()))
        for nome, riquadro, nitidezza, versione in (
                ("anna-1.jpg", "[0.2,0.2,0.5,0.5]", 3.0, "1"),
                ("anna-1.jpg", "[0.21,0.2,0.5,0.5]", 4.0, "2"),
                ("sparita.jpg", "[0.2,0.2,0.5,0.5]", 9.0, "1")):
            c.execute("INSERT INTO volti_riferimento (persona_id, da_file, riquadro, area, "
                      "nitidezza, sicurezza, impronta, modello, versione, letto_il) "
                      "VALUES (?, ?, ?, 0.25, ?, 0.9, x'00', 'volti', ?, ?)",
                      (anna, nome, riquadro, nitidezza, versione, adesso()))
    return {"archivio": archivio_pieno, "foto": foto, "anna": anna, "cartella": cartella}


def test_nella_foto_ci_sono_solo_le_persone_con_un_nome(con_persone):
    with con_persone["archivio"].lettura() as connessione:
        chi = persone.nella_foto(connessione, con_persone["foto"][0]["id"])
    assert [p["persona_id"] for p in chi] == [con_persone["anna"]]
    anna = chi[0]
    assert anna["riquadri"] == [[0.4, 0.2, 0.1, 0.12]]
    assert anna["riferimenti"] == [{
        "file": str(con_persone["cartella"] / "anna-1.jpg"),
        "riquadro": [0.21, 0.2, 0.5, 0.5], "nitidezza": 4.0}]


def test_se_la_cartella_non_c_e_piu_usa_i_suoi_volti_nell_archivio(con_persone):
    import shutil

    shutil.rmtree(con_persone["cartella"])
    with con_persone["archivio"].lettura() as connessione:
        anna = persone.nella_foto(connessione, con_persone["foto"][0]["id"])[0]
    assert [r["nitidezza"] for r in anna["riferimenti"]] == [5.0, 2.0]
    assert all(r["riquadro"] == [0.3, 0.3, 0.2, 0.2] for r in anna["riferimenti"])
    assert con_persone["foto"][0]["id"] not in [r["file"] for r in anna["riferimenti"]]


def test_i_volti_si_accendono_da_soli(tmp_path, monkeypatch):
    from officina.miglioria import codeformer_pesi, lavoro, preparazione
    from officina.volti import rilevatore

    monkeypatch.setattr(codeformer_pesi, "e_in_casa", lambda d: False)
    monkeypatch.setattr(rilevatore, "ci_sono_i_modelli", lambda d: True)
    assert lavoro.volti_da_soli(tmp_path) is None
    monkeypatch.setattr(codeformer_pesi, "e_in_casa", lambda d: True)
    monkeypatch.setattr(preparazione, "e_pronto", lambda d, nome="seedvr2": False)
    assert lavoro.volti_da_soli(tmp_path) == motori.CODEFORMER
    monkeypatch.setattr(preparazione, "e_pronto", lambda d, nome="seedvr2": nome == "faceme")
    assert lavoro.volti_da_soli(tmp_path) == motori.FACEME


def test_la_licenza_sta_accanto_al_codice_copiato():
    from pathlib import Path

    casa = Path(faceme.__file__).parent
    testo = (casa / "LICENZA-FaceMe.txt").read_text(encoding="ascii")
    assert "Pi-Lab License 1.0" in testo and "Copyright 2024 Pi-Lab" in testo
    assert faceme_pesi.manifesto()["commit"] in testo


def test_i_pezzi_copiati_hanno_i_nomi_dei_pesi():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from officina.miglioria import faceme_rete

    with torch.device("meta"):
        mix = set(faceme_rete.Mix().state_dict())
        occhio = set(faceme_rete.occhio().state_dict())
    assert {"pro_id.mlp1.fc1.weight", "mlp1.layernorm.weight", "norm1.bias",
            "mlp2.fc2.bias"} <= mix
    assert {"visual_projection.weight", "visual_projection_2.weight",
            "vision_model.embeddings.patch_embedding.weight"} <= occhio
    assert len(occhio) == 393
