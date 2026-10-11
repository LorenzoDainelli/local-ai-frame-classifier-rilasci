from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from officina.miglioria import motori, scaricamento, seedvr2
from officina.programma import carta, librerie


@pytest.fixture
def casa(tmp_path, monkeypatch):
    dove = tmp_path / "casa"
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(dove))
    return dove


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


@pytest.fixture
def finto(tmp_path, monkeypatch):
    testi = {"src/a.py": b"A = 1\n", "configs_7b/main.yaml": b"x: 1\n"}
    pesi = {seedvr2.DIT: b"dit-finto", seedvr2.VAE: b"vae-finto"}
    terzi = tmp_path / "terzi"
    terzi.mkdir()
    (terzi / "seedvr2.json").write_text(json.dumps({
        "deposito": "esempio/finto", "commit": "abc", "licenza": "Apache-2.0",
        "file": {n: _sha(d) for n, d in testi.items()},
        "pesi": [{"nome": n, "repo": "esempio/pesi", "sha256": _sha(d),
                  "byte_circa": len(d)} for n, d in pesi.items()]}), encoding="utf-8")
    monkeypatch.setattr(scaricamento, "TERZI", terzi)
    chiesti = []

    def prendi_testo(indirizzo):
        chiesti.append(indirizzo)
        return testi[indirizzo.split("/abc/", 1)[1]]

    def prendi_peso(repo, nome, cartella, chiave):
        chiesti.append(nome)
        (cartella / nome).write_bytes(pesi[nome])
        return cartella / nome

    return {"testi": testi, "pesi": pesi, "prendi_testo": prendi_testo,
            "prendi_peso": prendi_peso, "chiesti": chiesti, "modelli": tmp_path / "modelli"}


def test_il_manifesto_vero_e_completo():
    atteso = scaricamento.manifesto()
    assert atteso["commit"] and len(atteso["commit"]) == 40
    assert "configs_7b/main.yaml" in atteso["file"]
    assert "pos_emb.pt" in atteso["file"] and "LICENSE" in atteso["file"]
    assert not any(n.startswith("src/interfaces/") for n in atteso["file"])
    assert {p["nome"] for p in atteso["pesi"]} == {seedvr2.DIT, seedvr2.VAE}
    assert all(len(p["sha256"]) == 64 for p in atteso["pesi"])
    assert scaricamento.byte_circa() > 8 * 10 ** 9


def test_scarica_verifica_e_mette_al_posto(finto):
    arrivo = scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                                  prendi_peso=finto["prendi_peso"])
    assert scaricamento.e_in_casa(finto["modelli"])
    assert (arrivo / "codice" / "src" / "a.py").read_bytes() == b"A = 1\n"
    assert (arrivo / "pesi" / seedvr2.DIT).read_bytes() == b"dit-finto"
    assert not arrivo.with_name("seedvr2.nuova").exists()


def test_un_file_diverso_non_entra(finto):
    finto["testi"]["src/a.py"] = b"cattivo\n"
    with pytest.raises(scaricamento.ScaricamentoFallito):
        scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                             prendi_peso=finto["prendi_peso"])
    assert not scaricamento.e_in_casa(finto["modelli"])
    assert not scaricamento.dove(finto["modelli"]).exists()


def test_un_peso_diverso_non_entra(finto):
    finto["pesi"][seedvr2.VAE] = b"altro"
    with pytest.raises(scaricamento.ScaricamentoFallito):
        scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                             prendi_peso=finto["prendi_peso"])
    assert not scaricamento.e_in_casa(finto["modelli"])


def test_i_pesi_gia_buoni_non_si_riscaricano(finto):
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    casa = scaricamento.dove(finto["modelli"])
    (casa / "pronto.json").write_text(json.dumps({"commit": "vecchio"}), encoding="utf-8")
    finto["chiesti"].clear()
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    assert seedvr2.DIT not in finto["chiesti"] and seedvr2.VAE not in finto["chiesti"]
    assert scaricamento.e_in_casa(finto["modelli"])


def test_la_chiave_non_finisce_nel_messaggio(finto):
    def rotto(repo, nome, cartella, chiave):
        raise OSError(f"rifiutato con {chiave}")

    with pytest.raises(scaricamento.ScaricamentoFallito) as preso:
        scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                             prendi_peso=rotto, chiave="hf_segreto_finto")
    assert "hf_segreto_finto" not in str(preso.value)


def test_senza_modello_il_motore_lo_dice(tmp_path):
    with pytest.raises(seedvr2.MancaSeedVR2):
        seedvr2.SeedVR2(cartella_modelli=str(tmp_path))
    with pytest.raises(seedvr2.MancaSeedVR2):
        seedvr2.SeedVR2()


def test_seedvr2_e_nei_motori():
    assert motori.FOTO[motori.SEEDVR2] == "officina.miglioria.seedvr2:SeedVR2"
    assert motori.VIDEO[motori.SEEDVR2] == "officina.miglioria.seedvr2:SeedVR2"


def test_i_lati_e_le_impostazioni():
    assert seedvr2.lati(1920, 1080) == (1080, 1920)
    assert seedvr2.lati(1080, 1920) == (1080, 1920)
    assert seedvr2.impostazioni()["blocks_to_swap"] == seedvr2.BLOCCHI_NORMALI
    stretto = seedvr2.impostazioni(stretto=True)
    assert stretto["blocks_to_swap"] == seedvr2.BLOCCHI_STRETTI and stretto["swap_io_components"]


def _motore_finto(finto, monkeypatch):
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    motore = seedvr2.SeedVR2(cartella_modelli=str(finto["modelli"]))
    visti = []

    def ingrandisci(quadri, larghezza, altezza):
        visti.append([int(q[0, 0, 0]) for q in quadri])
        return np.stack([np.full((altezza, larghezza, 3), q[0, 0, 0], np.uint8)
                         for q in quadri])

    monkeypatch.setattr(motore, "_ingrandisci", ingrandisci)
    return motore, visti


def test_il_video_esce_intero_e_in_ordine(finto, monkeypatch):
    motore, visti = _motore_finto(finto, monkeypatch)
    quadri = [np.full((4, 6, 3), i, np.uint8) for i in range(100)]
    usciti = list(motore.video(iter(quadri), 12, 8))
    assert [int(q[0, 0, 0]) for q in usciti] == list(range(100))
    assert all(q.shape == (8, 12, 3) for q in usciti)
    assert visti[0][0] == 0
    assert visti[1][:seedvr2.CONTESTO] == list(range(seedvr2.QUADRI_PER_VOLTA - seedvr2.CONTESTO,
                                                     seedvr2.QUADRI_PER_VOLTA))


def test_la_foto_esce_della_misura_chiesta(finto, monkeypatch):
    motore, _visti = _motore_finto(finto, monkeypatch)
    grande = motore.foto(Image.new("RGB", (6, 4), (9, 9, 9)), 12, 8)
    assert grande.size == (12, 8)


def test_se_la_memoria_finisce_riprova_stretto(finto, monkeypatch):
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    motore = seedvr2.SeedVR2(cartella_modelli=str(finto["modelli"]))
    giri = []
    pulito = []

    class Memoria:
        @staticmethod
        def clear_memory(**_):
            pulito.append(True)

    motore._s = {"memoria": Memoria, "debug": None}

    def una_volta(quadri, larghezza, altezza):
        giri.append(motore.stretto)
        if not motore.stretto:
            raise RuntimeError("CUDA out of memory")
        return quadri

    monkeypatch.setattr(motore, "_una_volta", una_volta)
    motore._ingrandisci(np.zeros((1, 2, 2, 3), np.uint8), 4, 4)
    assert giri == [False, True] and pulito


def test_le_richieste_della_miglioria(casa):
    richieste = librerie.richieste_della_miglioria()
    nomi = [librerie._nome(r) for r in richieste]
    assert "diffusers" in nomi and "omegaconf" in nomi
    assert "torch" not in nomi and "transformers" not in nomi
    assert all("==" in r for r in richieste)
    assert set(librerie.SOLO_SORGENTE) <= set(nomi)
    assert "pyyaml" in [n.lower() for n in nomi]
    dei_modelli = [librerie._nome(r) for r in librerie.richieste_dei_modelli()]
    assert set(librerie.SENZA_DIPENDENZE) <= set(nomi) | set(dei_modelli)
    assert {"accelerate", "bitsandbytes"} <= set(dei_modelli)


def test_le_librerie_dei_modelli_chiedono_torch_senza_scaricarne_un_altro(casa):
    comandi = []

    def esegui(comando, **_):
        comandi.append(comando)
        destinazione = comando[comando.index("--target") + 1]
        from pathlib import Path

        Path(destinazione).mkdir(parents=True, exist_ok=True)
        return True

    installatore = librerie.Installatore(esegui=esegui, prendi=lambda _: b"")
    installatore._esegui_pip = lambda comando: esegui(comando) or True
    installatore._installa_i_modelli()
    assert len(comandi) == 2
    assert "--no-deps" not in comandi[0] and "--no-deps" in comandi[1]
    assert any(c.startswith("bitsandbytes==") for c in comandi[1])
    assert any(c.startswith("transformers==5.") for c in comandi[0])


def test_il_comando_lascia_il_sorgente_solo_a_chi_serve(tmp_path):
    comando = librerie.comando_pip("python.exe", tmp_path, ["a==1"],
                                   sorgenti=("qualcosa",),
                                   extra_opzioni=["--no-deps"])
    assert comando[comando.index("--no-binary") + 1] == "qualcosa"
    assert "--only-binary" in comando and "--no-deps" in comando
    assert comando[-1] == "a==1"


def test_manca_la_miglioria_segue_lo_stato(casa):
    sue, modelli = ["diffusers==1"], ["transformers==1"]
    assert librerie.manca_la_miglioria(sue, modelli)
    librerie.cartella("miglioria").mkdir(parents=True)
    carta.aggiorna(librerie={"miglioria": {
        "impronta": librerie.impronta_della_miglioria(sue, modelli)}})
    assert not librerie.manca_la_miglioria(sue, modelli)
    assert librerie.manca_la_miglioria(sue, ["transformers==2"])
    assert librerie.manca_la_miglioria(["diffusers==2"], modelli)
    assert "miglioria" not in librerie.cosa_manca(modelli)


def test_l_installatore_mette_la_miglioria_in_due_giri(casa, monkeypatch):
    comandi = []

    def esegui(comando, stato, fermati):
        comandi.append(comando)
        destinazione = comando[comando.index("--target") + 1]
        from pathlib import Path

        Path(destinazione).mkdir(parents=True, exist_ok=True)
        return True

    import io
    import tarfile

    dentro = librerie.SOLO_SORGENTE["antlr4-python3-runtime"][2]
    pacco = io.BytesIO()
    with tarfile.open(fileobj=pacco, mode="w:gz") as scrivi:
        for nome, testo in ((dentro + "__init__.py", b"x = 1\n"),
                            (dentro + "error/Errori.py", b""),
                            ("antlr4-python3-runtime-4.9.3/setup.py", b"")):
            voce = tarfile.TarInfo(nome)
            voce.size = len(testo)
            scrivi.addfile(voce, io.BytesIO(testo))
    contenuto = pacco.getvalue()
    monkeypatch.setitem(librerie.SOLO_SORGENTE, "antlr4-python3-runtime",
                        ("finto", hashlib.sha256(contenuto).hexdigest(), dentro))

    installatore = librerie.Installatore(esegui=esegui, prendi=lambda _: contenuto)
    installatore.installa(["miglioria"])
    assert len(comandi) == 2
    assert "--no-binary" not in comandi[0] and "--no-deps" not in comandi[0]
    assert not any(c.startswith("antlr4") for c in comandi[0] + comandi[1])
    casa_nuova = librerie.cartella("miglioria")
    assert (casa_nuova / "antlr4" / "__init__.py").read_text() == "x = 1\n"
    assert (casa_nuova / "antlr4" / "error" / "Errori.py").exists()
    assert not (casa_nuova / "antlr4" / "setup.py").exists()
    assert (casa_nuova / "antlr4_python3_runtime-4.9.3.dist-info" / "METADATA").exists()
    assert "--no-deps" in comandi[1]
    sue = {librerie._nome(r) for r in librerie.richieste_della_miglioria()}
    for nome in librerie.SENZA_DIPENDENZE:
        if nome not in sue:
            continue
        assert any(c.startswith(nome + "==") for c in comandi[1])
        assert not any(c.startswith(nome + "==") for c in comandi[0])
    assert librerie.cartella("miglioria").is_dir()
    assert not librerie.manca_la_miglioria()


def test_senza_spazio_non_comincia_e_lo_dice(finto, monkeypatch):
    from collections import namedtuple

    Disco = namedtuple("Disco", "total used free")
    monkeypatch.setattr(scaricamento.shutil, "disk_usage", lambda _p: Disco(1, 1, 1000))
    with pytest.raises(scaricamento.ScaricamentoFallito) as preso:
        scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                             prendi_peso=finto["prendi_peso"])
    assert "GB liberi" in str(preso.value)
    assert finto["chiesti"] == []


def test_lo_scaricamento_dei_pesi_dice_a_che_punto(finto):
    punti = []
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"],
                         a_che_punto=lambda fatti, attesi: punti.append((fatti, attesi)))
    assert punti and all(attesi == scaricamento.byte_circa() for _f, attesi in punti)


class _InstallatoreFinto:

    def __init__(self):
        self.stato = librerie.Avanzamento()
        self.fatte = []

    def installa(self, parti):
        self.stato.detto = "Scarico le librerie che migliorano foto e video."
        self.fatte.append(list(parti))


def test_un_clic_prima_le_librerie_poi_il_modello(finto, monkeypatch):
    from officina.miglioria import preparazione

    monkeypatch.setattr(librerie, "cosa_manca", lambda *_a: [])
    monkeypatch.setattr(librerie, "manca_la_miglioria", lambda *_a: True)
    ordine, righe = [], []
    installatore = _InstallatoreFinto()
    vero = installatore.installa
    installatore.installa = lambda parti: (ordine.append("librerie"), vero(parti))

    def scarica(cartella, **opzioni):
        ordine.append("modello")
        return scaricamento.scarica(cartella, prendi_testo=finto["prendi_testo"],
                                    prendi_peso=finto["prendi_peso"], **opzioni)

    preparazione.prepara(finto["modelli"], di=righe.append, installatore=installatore,
                         scarica=scarica)
    assert ordine == ["librerie", "modello"]
    assert installatore.fatte == [["miglioria"]]
    assert scaricamento.e_in_casa(finto["modelli"])
    assert righe[-1].startswith("SeedVR2 è in casa")


def test_con_le_librerie_gia_pronte_scarica_soltanto(finto, monkeypatch):
    from officina.miglioria import preparazione

    monkeypatch.setattr(librerie, "cosa_manca", lambda *_a: [])
    monkeypatch.setattr(librerie, "manca_la_miglioria", lambda *_a: False)
    installatore = _InstallatoreFinto()
    preparazione.prepara(finto["modelli"], di=lambda _t: None, installatore=installatore,
                         scarica=lambda c, **o: scaricamento.scarica(
                             c, prendi_testo=finto["prendi_testo"],
                             prendi_peso=finto["prendi_peso"], **o))
    assert installatore.fatte == []
    assert preparazione.e_pronto(finto["modelli"])


def test_se_manca_anche_torch_lo_mette_prima(monkeypatch):
    from officina.miglioria import preparazione

    monkeypatch.setattr(librerie, "cosa_manca", lambda *_a: ["torch"])
    monkeypatch.setattr(librerie, "manca_la_miglioria", lambda *_a: True)
    assert preparazione.librerie_che_mancano() == ["torch", "miglioria"]


def test_senza_le_librerie_non_e_pronto_anche_col_modello(finto, monkeypatch):
    from officina.miglioria import preparazione

    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    monkeypatch.setattr(librerie, "manca_la_miglioria", lambda *_a: True)
    assert not preparazione.e_pronto(finto["modelli"])


def test_se_il_racconto_si_rompe_l_installazione_va_avanti(monkeypatch):
    import time

    from officina.miglioria import preparazione

    monkeypatch.setattr(preparazione, "OGNI_QUANTO", 0.01)
    installatore = _InstallatoreFinto()

    def rotto(_testo):
        raise RuntimeError("pagina chiusa")

    finito = []
    preparazione._col_resoconto(installatore, rotto, None,
                                lambda: (installatore.installa(["miglioria"]),
                                         time.sleep(0.1), finito.append(True)))
    assert finito == [True]


def test_il_modello_mancante_si_legge_a_parole(tmp_path):
    from officina.miglioria import lavoro

    with pytest.raises(seedvr2.MancaSeedVR2) as preso:
        seedvr2.SeedVR2(cartella_modelli=str(tmp_path))
    assert lavoro.a_parole(preso.value.codice) != preso.value.codice
