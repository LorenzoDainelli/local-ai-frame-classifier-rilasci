from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.programma import aggiornamenti, carta, librerie, scheda, segreti


@pytest.fixture
def casa(tmp_path, monkeypatch):
    dove = tmp_path / "casa"
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(dove))
    return dove


def _archivio_vecchio(dove: Path, scatti: int = 3) -> Path:
    reale = dove / "reale"
    reale.mkdir(parents=True)
    connessione = sqlite3.connect(reale / "archivio.sqlite")
    connessione.execute("CREATE TABLE scatti (id INTEGER, fuori_archivio INTEGER)")
    connessione.executemany("INSERT INTO scatti VALUES (?, 0)",
                            [(n,) for n in range(scatti)])
    connessione.execute("INSERT INTO scatti VALUES (99, 1)")
    connessione.commit()
    connessione.close()
    return dove


def test_la_carta_si_scrive_e_si_rilegge(casa):
    assert carta.leggi() == {}
    carta.aggiorna(cartella_dati="X:/foto", canale="beta")
    assert carta.leggi()["cartella_dati"] == "X:/foto"
    carta.aggiorna(canale=None)
    assert "canale" not in carta.leggi()
    assert not list(casa.glob("*.scrittura"))


def test_una_carta_rovinata_non_ferma_il_programma(casa):
    casa.mkdir(parents=True)
    carta.file_carta().write_text("{ rotta", encoding="utf-8")
    assert carta.leggi() == {}
    assert (casa / "programma.rovinata.json").exists()


def test_la_radice_degli_archivi_segue_la_carta(casa, monkeypatch):
    from officina.impostazioni import radice_archivi

    monkeypatch.delenv("OFFICINA_ARCHIVIO", raising=False)
    carta.aggiorna(cartella_dati=str(casa / "altrove"))
    assert radice_archivi() == casa / "altrove"
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(casa / "ambiente"))
    assert radice_archivi() == (casa / "ambiente").resolve()


def test_trova_l_archivio_della_versione_uno(casa, tmp_path, monkeypatch):
    vecchio = _archivio_vecchio(tmp_path / "Officina", scatti=5)
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: vecchio)
    monkeypatch.delenv("OFFICINA_ARCHIVIO", raising=False)
    trovato = carta.archivio_della_versione_1()
    assert trovato is not None
    assert trovato.dove == vecchio
    assert trovato.scatti == 5
    assert not trovato.nel_forziere
    assert trovato.peso > 0


def test_un_archivio_nel_forziere_si_riconosce_senza_aprirlo(tmp_path):
    dove = tmp_path / "Officina"
    dove.mkdir()
    (dove / "reale.forziere").write_bytes(b"x" * 100)
    trovato = carta.guarda(dove)
    assert trovato is not None and trovato.nel_forziere
    assert trovato.scatti is None and trovato.peso == 100


def test_sfoglia_accetta_la_cartella_o_la_sua_reale(tmp_path):
    dove = _archivio_vecchio(tmp_path / "Copia")
    assert carta.dalla_scelta(dove).dove == dove
    assert carta.dalla_scelta(dove / "reale").dove == dove
    with pytest.raises(ErroreOfficina):
        carta.dalla_scelta(tmp_path)


def test_usa_questo_archivio_non_copia_niente(casa, tmp_path):
    dove = _archivio_vecchio(tmp_path / "Officina")
    prima = sorted(p.name for p in dove.rglob("*"))
    carta.usa_questo_archivio(dove)
    assert carta.cartella_dati() == dove.resolve()
    assert sorted(p.name for p in dove.rglob("*")) == prima


def test_comincia_da_zero_prepara_la_cartella_nuova(casa):
    carta.comincia_da_zero()
    assert carta.cartella_dati() == carta.cartella_dati_nuova()
    assert carta.cartella_dati_nuova().is_dir()


class NvmlFinto:

    def __init__(self, schede, cuda=12080, driver=b"572.16"):
        self.schede = schede
        self.cuda = cuda
        self.driver = driver
        self.chiuso = False

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        self.chiuso = True

    def nvmlSystemGetDriverVersion(self):
        return self.driver

    def nvmlSystemGetCudaDriverVersion_v2(self):
        return self.cuda

    def nvmlDeviceGetCount(self):
        return len(self.schede)

    def nvmlDeviceGetHandleByIndex(self, numero):
        return numero

    def nvmlDeviceGetName(self, numero):
        return self.schede[numero][0]

    def nvmlDeviceGetMemoryInfo(self, numero):
        return type("M", (), {"total": self.schede[numero][1]})()

    def nvmlDeviceGetCudaComputeCapability(self, numero):
        return self.schede[numero][2]


def test_nvml_legge_scheda_driver_e_cuda():
    finto = NvmlFinto([(b"NVIDIA GeForce RTX 4070", 12 * 2 ** 30, (8, 9))])
    esame = scheda.con_nvml(finto)
    assert esame.nvidia and finto.chiuso
    assert esame.cuda_del_driver == (12, 8)
    assert esame.la_migliore.nome == "NVIDIA GeForce RTX 4070"
    assert esame.la_migliore.memoria_a_parole == "12 GB"


def test_nvml_che_non_parte_non_e_un_guasto():
    class Rotto:
        def nvmlInit(self):
            raise OSError("niente driver")

    assert scheda.con_nvml(Rotto()) is None


def test_nvidia_smi_si_legge_anche_con_le_virgole_strane():
    elenco = "NVIDIA GeForce RTX 3060 Laptop GPU, 6144, 8.6, 560.94\n"
    intestazione = "| NVIDIA-SMI 560.94   Driver Version: 560.94   CUDA Version: 12.6 |"
    esame = scheda.leggi_nvidia_smi(elenco, intestazione)
    assert esame.schede[0].capacita == (8, 6)
    assert esame.cuda_del_driver == (12, 6)
    assert esame.schede[0].memoria == 6144 * 2 ** 20


def test_senza_nvidia_si_usa_il_processore():
    esame = scheda.esamina(nvml=lambda: None, smi=lambda: None)
    assert not esame.nvidia
    assert scheda.candidate(esame) == [scheda.CPU]


def test_nvml_senza_capacita_si_completa_con_nvidia_smi():
    prima = scheda.Esame(schede=(scheda.Scheda("RTX", 8 * 2 ** 30, None),),
                         driver="555", cuda_del_driver=None, fonte="nvml")
    dopo = scheda.Esame(schede=(scheda.Scheda("RTX", 8 * 2 ** 30, (8, 9)),),
                        driver="555", cuda_del_driver=(12, 5), fonte="nvidia-smi")
    esame = scheda.esamina(nvml=lambda: prima, smi=lambda: dopo)
    assert esame.la_migliore.capacita == (8, 9)
    assert esame.cuda_del_driver == (12, 5)


def _esame(capacita, cuda):
    return scheda.Esame(schede=(scheda.Scheda("X", 8 * 2 ** 30, capacita),),
                        driver="1", cuda_del_driver=cuda, fonte="nvml")


def test_il_driver_mette_il_tetto_alla_versione_di_cuda():
    nomi = [v.etichetta for v in scheda.candidate(_esame((8, 9), (12, 6)))]
    assert nomi[0] == "cu126"
    assert "cu128" not in nomi and nomi[-1] == "cpu"


def test_una_blackwell_non_prende_una_versione_che_non_la_conosce():
    nomi = [v.etichetta for v in scheda.candidate(_esame((12, 0), (12, 8)))]
    assert nomi[0] == "cu128"
    assert "cu126" not in nomi


def test_una_pascal_non_prende_le_versioni_che_l_hanno_lasciata():
    nomi = [v.etichetta for v in scheda.candidate(_esame((6, 1), (13, 0)))]
    assert nomi[0] == "cu126"
    assert "cu128" not in nomi and "cu130" not in nomi


def test_un_driver_troppo_vecchio_porta_al_processore():
    assert scheda.candidate(_esame((7, 5), (11, 4))) == [scheda.CPU]


PAGINA_TORCH = """
<a href="/whl/cu128/torch-2.13.0%2Bcu128-cp313-cp313-win_amd64.whl#sha256=aa">x</a>
<a href="/whl/cu128/torch-2.14.0%2Bcu128-cp313-cp313-win_amd64.whl#sha256=bb">x</a>
<a href="/whl/cu128/torch-2.14.0%2Bcu128-cp313-cp313t-win_amd64.whl#sha256=cc">x</a>
<a href="/whl/cu128/torch-2.15.0%2Bcu128-cp314-cp314-win_amd64.whl#sha256=dd">x</a>
<a href="/whl/cu128/torch-2.15.0%2Bcu128-cp313-cp313-manylinux_2_28_x86_64.whl">x</a>
"""

PAGINA_VISIONE = """
<a href="/whl/cu128/torchvision-0.28.0%2Bcu128-cp313-cp313-win_amd64.whl">x</a>
<a href="/whl/cu128/torchvision-0.29.0%2Bcu128-cp313-cp313-win_amd64.whl">x</a>
"""


def test_legge_le_versioni_giuste_dall_indice():
    trovate = scheda.versioni_nell_indice(PAGINA_TORCH, "torch", "cu128",
                                          python="cp313", dove="win_amd64")
    assert trovate == ["2.14.0", "2.13.0"]
    linux = scheda.versioni_nell_indice(PAGINA_TORCH, "torch", "cu128",
                                        python="cp313", dove="linux_x86_64")
    assert linux == ["2.15.0"]


def test_torchvision_si_abbina_alla_sua_torch():
    assert scheda.torchvision_per("2.14.0", ["0.29.0", "0.28.0"]) == "0.29.0"
    assert scheda.torchvision_per("2.13.0", ["0.29.0", "0.28.0"]) == "0.28.0"
    assert scheda.torchvision_per("2.12.0", ["0.29.0"]) is None


def test_il_piano_prende_la_prima_candidata_che_esiste_davvero():
    pagine = {
        "https://download.pytorch.org/whl/cu128/torch/": PAGINA_TORCH,
        "https://download.pytorch.org/whl/cu128/torchvision/": PAGINA_VISIONE,
    }
    piano = scheda.prepara_il_piano(_esame((8, 9), (12, 9)), leggi=pagine.get,
                                    python="cp313", dove="win_amd64")
    assert piano.variante.etichetta == "cu128"
    assert piano.torch == "2.14.0+cu128"
    assert piano.torchvision == "0.29.0+cu128"
    assert "CUDA 12.8" in piano.perche


def test_senza_internet_il_piano_lo_dice():
    piano = scheda.prepara_il_piano(_esame((8, 9), (12, 9)), leggi=lambda _: None)
    assert piano.variante is scheda.CPU
    assert "indice_irraggiungibile" in piano.avvisi


def test_la_prova_della_scheda_vuole_il_conto_giusto():
    cuda = scheda.Variante("cu128", (12, 8))
    assert scheda.la_scheda_lavora({"ok": True, "conto_giusto": True, "disponibile": True}, cuda)
    assert not scheda.la_scheda_lavora({"ok": True, "conto_giusto": True, "disponibile": False}, cuda)
    assert not scheda.la_scheda_lavora({"ok": True, "conto_giusto": False, "disponibile": True}, cuda)
    assert scheda.la_scheda_lavora({"ok": True, "conto_giusto": True}, scheda.CPU)


def test_le_richieste_dei_modelli_non_contengono_torch():
    richieste = librerie.richieste_dei_modelli()
    nomi = [r.split("==")[0].lower() for r in richieste]
    assert "transformers" in nomi
    assert "torch" not in nomi and "torchvision" not in nomi
    assert all("#" not in r for r in richieste)


def test_l_avanzamento_di_pip_si_legge():
    stato = librerie.Avanzamento()
    for riga in ("Collecting torch==2.14.0+cu128",
                 "Downloading torch-2.14.0%2Bcu128-cp313-cp313-win_amd64.whl (2.6 GB)",
                 "Progress 262144 of 2600000000"):
        librerie.leggi_una_riga(riga, stato)
    assert stato.fase == "scarico"
    assert stato.file.startswith("torch-2.14.0")
    assert stato.come_dati()["totale"] == 2600000000
    librerie.leggi_una_riga("Installing collected packages: torch", stato)
    assert stato.fase == "installo" and stato.totale == 0


def test_il_comando_di_pip_non_esce_dalla_sua_cartella(tmp_path):
    comando = librerie.comando_pip("python.exe", tmp_path / "t", ["torch==1"],
                                   indice="https://x/cu128", extra=["https://pypi"],
                                   file_vincoli=tmp_path / "v.txt")
    assert comando[:4] == ["python.exe", "-m", "pip", "install"]
    assert comando[comando.index("--target") + 1] == str(tmp_path / "t")
    assert "--only-binary" in comando and "--no-cache-dir" in comando
    assert comando[-1] == "torch==1"


def test_cosa_manca_segue_lo_stato_scritto(casa):
    richieste = ["transformers==1"]
    assert librerie.cosa_manca(richieste) == ["torch", "modelli"]
    librerie.cartella("torch").mkdir(parents=True)
    librerie.cartella("modelli").mkdir(parents=True)
    carta.aggiorna(librerie={
        "torch": {"python": scheda.etichetta_di_python(), "torch": "2.14.0+cu128"},
        "modelli": {"impronta": librerie.impronta_delle_richieste(richieste)}})
    assert librerie.cosa_manca(richieste) == []
    assert librerie.cosa_manca(["transformers==2"]) == ["modelli"]


def test_l_installatore_ripiega_sul_processore_se_la_scheda_non_passa(casa, monkeypatch):
    monkeypatch.setattr(librerie, "spazio_libero", lambda _: 500 * 1024 ** 3)
    esami = _esame((8, 9), (12, 8))
    piani = {
        True: scheda.Piano(scheda.Variante("cu128", (12, 8)), "https://i/cu128",
                           "2.14.0+cu128", "0.29.0+cu128", "Con la scheda."),
        False: scheda.Piano(scheda.CPU, "https://i/cpu", "2.14.0+cpu",
                            "0.29.0+cpu", "Col processore."),
    }
    comandi = []

    def esegui(comando, stato, fermati):
        comandi.append(comando)
        destinazione = Path(comando[comando.index("--target") + 1])
        (destinazione / "segno").write_text("x")
        return True

    def prova(_, cartella):
        if "cu128" in " ".join(comandi[-1]):
            return {"ok": True, "conto_giusto": True, "disponibile": False}
        return {"ok": True, "conto_giusto": True, "torch": "2.14.0+cpu"}

    lavoratore = librerie.Installatore(esegui=esegui, prova=prova,
                                       esamina=lambda: esami,
                                       prepara=lambda e: piani[e.nvidia])
    lavoratore.installa(["torch"])
    scritto = librerie.stato_scritto()["torch"]
    assert scritto["variante"] == "cpu"
    assert "prova sulla scheda non è andata" in scritto["perche"]
    assert (librerie.cartella("torch") / "segno").exists()
    assert not librerie.cartella("torch").with_name("torch.nuova").exists()


def test_se_pip_fallisce_la_cartella_vecchia_resta(casa):
    vecchia = librerie.cartella("modelli")
    vecchia.mkdir(parents=True)
    (vecchia / "c_era").write_text("x")
    lavoratore = librerie.Installatore(esegui=lambda *a: False)
    with pytest.raises(ErroreOfficina):
        lavoratore.installa(["modelli"])
    assert (vecchia / "c_era").exists()
    assert not vecchia.with_name("modelli.nuova").exists()


def test_la_chiave_hf_dall_ambiente_vince(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", " hf_dallambiente ")
    assert segreti.chiave_hf() == "hf_dallambiente"


def test_la_chiave_hf_custodita_non_finisce_su_file(casa, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(segreti, "si_puo_custodire", lambda: False)
    chiave = "hf_" + "a" * 34
    segreti.custodisci(segreti.CHIAVE_HF, chiave)
    try:
        assert segreti.chiave_hf() == chiave
        carta.aggiorna(qualcosa=1)
        assert chiave not in carta.file_carta().read_text(encoding="utf-8")
    finally:
        segreti.togli(segreti.CHIAVE_HF)
    assert segreti.chiave_hf() is None


def test_riconosce_la_forma_di_una_chiave_hf():
    assert segreti.sembra_una_chiave_hf("hf_" + "Ab1" * 12)
    assert not segreti.sembra_una_chiave_hf("password123")
    assert not segreti.sembra_una_chiave_hf("hf_ con spazi dentro e basta ok ok")


def test_le_versioni_si_confrontano_come_si_deve():
    assert aggiornamenti.e_piu_nuova("2.0.0-beta.10", "2.0.0-beta.9")
    assert aggiornamenti.e_piu_nuova("2.0.0", "2.0.0-beta.40")
    assert not aggiornamenti.e_piu_nuova("2.0.0-beta.3", "2.0.0")
    assert aggiornamenti.e_piu_nuova("2.1.0-beta.1", "2.0.9")
    assert not aggiornamenti.e_piu_nuova("pippo", "2.0.0")
    assert aggiornamenti.e_piu_nuova("2.0.0", "0.5.0")


def _rilascio(tag, nome="local-ai-frame-classifier-2.0.0.exe", digest="sha256:" + "a" * 64,
              bozza=False):
    return {"tag_name": tag, "draft": bozza, "body": "note",
            "published_at": "2026-09-25T10:00:00Z",
            "assets": [{"name": nome, "size": 10, "digest": digest,
                        "browser_download_url": f"https://github.com/x/{nome}"}]}


def test_il_canale_decide_quali_rilasci_contano():
    dati = [_rilascio("v2.0.0-beta.5"), _rilascio("v2.0.0-beta.6"),
            _rilascio("v1.9.0"), _rilascio("v2.0.0-beta.7", bozza=True)]
    rilasci = aggiornamenti.rilasci_da(dati, lambda _: None)
    assert [r.versione for r in rilasci] == ["2.0.0-beta.5", "2.0.0-beta.6", "1.9.0"]
    beta = aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.BETA, "2.0.0-beta.5")
    assert beta.versione == "2.0.0-beta.6"
    assert aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.FINALE, "1.8.0").versione == "1.9.0"
    assert aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.FINALE, "2.0.0") is None
    assert aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.SVILUPPO, "0.1.0") is None


def test_un_rilascio_senza_impronta_non_si_installa():
    dati = [_rilascio("v2.0.0", digest="")]
    rilasci = aggiornamenti.rilasci_da(dati, lambda _: None)
    assert rilasci[0].sha256 is None
    assert aggiornamenti.il_piu_nuovo(rilasci, aggiornamenti.FINALE, "1.0.0") is None


def test_l_impronta_puo_stare_in_un_file_accanto():
    dati = [_rilascio("v2.0.0", digest="")]
    dati[0]["assets"].append({"name": "local-ai-frame-classifier-2.0.0.exe.sha256",
                              "browser_download_url": "https://github.com/x/s"})
    rilasci = aggiornamenti.rilasci_da(dati, lambda _: "b" * 64 + "  file.exe\n")
    assert rilasci[0].sha256 == "b" * 64


class RispostaFinta(io.BytesIO):

    def __init__(self, dati):
        super().__init__(dati)
        self.headers = {"Content-Length": str(len(dati))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _rilascio_vero(contenuto: bytes, versione="2.0.0-beta.9") -> aggiornamenti.Rilascio:
    return aggiornamenti.Rilascio(
        versione=versione, indirizzo="https://github.com/x/i.exe",
        nome_file=f"local-ai-frame-classifier-{versione}.exe", peso=len(contenuto),
        sha256=hashlib.sha256(contenuto).hexdigest(), note="", pubblicato="")


def test_lo_scaricamento_controlla_l_impronta(casa):
    contenuto = b"installatore" * 1000
    rilascio = _rilascio_vero(contenuto)
    visti = []
    file = aggiornamenti.scarica(rilascio, al_passo=lambda f, t: visti.append((f, t)),
                                 apri=lambda *a, **k: RispostaFinta(contenuto))
    assert file.read_bytes() == contenuto
    assert visti[-1] == (len(contenuto), len(contenuto))
    pronto = aggiornamenti.pronto_da_installare(attuale="2.0.0-beta.8")
    assert pronto is not None and pronto[1] == file


def test_uno_scaricamento_rovinato_si_butta(casa):
    rilascio = _rilascio_vero(b"quello giusto")
    with pytest.raises(aggiornamenti.ImprontaSbagliata):
        aggiornamenti.scarica(rilascio, apri=lambda *a, **k: RispostaFinta(b"un altro"))
    assert not list(carta.cartella_scaricati().glob("*"))
    assert aggiornamenti.pronto_da_installare(attuale="1.0.0") is None


def test_uno_scaricato_gia_superato_si_dimentica(casa):
    contenuto = b"vecchio"
    aggiornamenti.scarica(_rilascio_vero(contenuto, "2.0.0-beta.2"),
                          apri=lambda *a, **k: RispostaFinta(contenuto))
    assert aggiornamenti.pronto_da_installare(attuale="2.0.0-beta.3") is None
    assert "aggiornamento_scaricato" not in carta.leggi()
    assert not list(carta.cartella_scaricati().glob("*.exe"))


def test_cerca_senza_rete_non_si_ferma(casa):
    assert aggiornamenti.cerca(chiedi=lambda _: None, canale="beta", attuale="2.0.0") is None
    assert carta.leggi()["aggiornamenti_ultimo_controllo"]["esito"] == "irraggiungibile"


def test_cerca_trova_e_rifiuta_resta_in_sospeso(casa, monkeypatch):
    dati = json.dumps([_rilascio("v2.0.1")]).encode()
    trovato = aggiornamenti.cerca(chiedi=lambda _: dati, canale="finale", attuale="2.0.0")
    assert trovato.versione == "2.0.1"
    aggiornamenti.rifiuta(trovato)
    monkeypatch.setattr(aggiornamenti, "versione_attuale", lambda: "2.0.0")
    assert aggiornamenti.in_sospeso()["versione"] == "2.0.1"
    monkeypatch.setattr(aggiornamenti, "versione_attuale", lambda: "2.0.1")
    assert aggiornamenti.in_sospeso() is None


def test_l_installatore_parte_in_silenzio_e_si_riapre(casa, tmp_path):
    lanciati = []
    aggiornamenti.installa(tmp_path / "x.exe", lancia=lambda c, **k: lanciati.append(c))
    assert "/SILENT" in lanciati[0] and "/RIAPRI=1" in lanciati[0]


def test_l_installatore_non_parte_dalla_cartella_del_programma(casa, tmp_path):
    opzioni = []
    aggiornamenti.installa(tmp_path / "x.exe", lancia=lambda c, **k: opzioni.append(k))
    assert opzioni[0]["cwd"] == str(tmp_path)


def test_uno_scaricamento_interrotto_riprende_da_dove_era(casa):
    contenuto = b"installatore" * 100000
    rilascio = _rilascio_vero(contenuto)
    fermati = threading.Event()
    with pytest.raises(ErroreOfficina):
        aggiornamenti.scarica(rilascio, fermati=fermati,
                              al_passo=lambda f, t: fermati.set(),
                              apri=lambda *a, **k: RispostaFinta(contenuto))
    [mezzo] = carta.cartella_scaricati().glob("*.parziale")
    arrivati = mezzo.stat().st_size
    assert 0 < arrivati < len(contenuto)
    assert aggiornamenti.pulisci_gli_scaricati() == 0 and mezzo.is_file()
    chieste = []

    def apri(richiesta, **_):
        chieste.append(richiesta.get_header("Range"))
        risposta = RispostaFinta(contenuto[arrivati:])
        risposta.status = 206
        return risposta

    visti = []
    file = aggiornamenti.scarica(rilascio, apri=apri, al_passo=lambda f, t: visti.append((f, t)))
    assert chieste == [f"bytes={arrivati}-"]
    assert file.read_bytes() == contenuto and visti[-1] == (len(contenuto), len(contenuto))
    assert not list(carta.cartella_scaricati().glob("*.parziale"))


def test_se_il_server_non_riprende_si_ricomincia(casa):
    contenuto = b"abcdef" * 1000
    rilascio = _rilascio_vero(contenuto)
    cartella = carta.cartella_scaricati()
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / (rilascio.nome_file + ".parziale")).write_bytes(contenuto[:500])
    (cartella / "vecchia.exe.parziale").write_bytes(b"x")
    file = aggiornamenti.scarica(rilascio, apri=lambda *a, **k: RispostaFinta(contenuto))
    assert file.read_bytes() == contenuto
    assert not list(cartella.glob("*.parziale"))


def test_un_pezzo_rovinato_si_butta_e_si_riscarica(casa):
    contenuto = b"giusto" * 1000
    rilascio = _rilascio_vero(contenuto)
    cartella = carta.cartella_scaricati()
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / (rilascio.nome_file + ".parziale")).write_bytes(b"sbagliato")

    def apri(richiesta, **_):
        if richiesta.get_header("Range"):
            risposta = RispostaFinta(contenuto[9:])
            risposta.status = 206
            return risposta
        return RispostaFinta(contenuto)

    assert aggiornamenti.scarica(rilascio, apri=apri).read_bytes() == contenuto


def test_nel_programma_le_istruzioni_non_chiedono_comandi(monkeypatch):
    from officina import istruzioni

    monkeypatch.setenv("OFFICINA_NEL_PROGRAMMA", "1")
    for testo in (istruzioni.motori(), istruzioni.motori(aggiorna=True),
                  istruzioni.modello("dinov3"), istruzioni.chiave("dinov3"),
                  istruzioni.motori_in_una_riga(), istruzioni.cosa_fare_per("numpy"),
                  istruzioni.cosa_fare_per_i_motori()):
        assert "pip" not in testo and "python -m" not in testo, testo
    monkeypatch.setenv("OFFICINA_NEL_PROGRAMMA", "0")
    assert "pip install -r requirements-modelli.txt" in istruzioni.motori()
    assert "--scarica dinov3" in istruzioni.modello("dinov3")


def test_i_messaggi_dei_modelli_seguono_le_istruzioni(monkeypatch, tmp_path):
    from officina.volti import insight, rilevatore

    monkeypatch.setenv("OFFICINA_NEL_PROGRAMMA", "1")
    for testo in (insight.cosa_manca(tmp_path), rilevatore.cosa_manca(tmp_path)):
        assert "python -m" not in testo and "pip install" not in testo, testo


def test_nessun_comando_resta_scritto_a_mano_nei_messaggi():
    import re
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent / "officina"
    colpevoli = []
    for file in radice.rglob("*.py"):
        if file.name in ("riga_di_comando.py", "istruzioni.py", "finestra.py") or "programma" in file.parts:
            continue
        for numero, riga in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if "_come_si_riprova(" in riga:
                continue
            if re.search(r'"\s*(pip install -r requirements-modelli|python -m officina modelli --scarica)', riga):
                colpevoli.append(f"{file.name}:{numero}")
    assert not colpevoli, colpevoli


def test_il_deposito_dei_rilasci_si_sceglie_alla_costruzione(tmp_path, monkeypatch):
    file = tmp_path / "costruzione.json"
    monkeypatch.setattr(aggiornamenti, "FILE_COSTRUZIONE", file)
    assert aggiornamenti.deposito_dei_rilasci() == "LorenzoDainelli/Local-AI-Frame-Classifier"
    file.write_text(json.dumps({"rilasci": "Qualcuno/Rilasci-Pubblici"}), encoding="utf-8")
    assert "repos/Qualcuno/Rilasci-Pubblici/releases" in aggiornamenti.indirizzo_dei_rilasci()
    file.write_text(json.dumps({"rilasci": "https://male.example/x"}), encoding="utf-8")
    assert aggiornamenti.deposito_dei_rilasci() == "LorenzoDainelli/Local-AI-Frame-Classifier"


def test_fermare_uccide_subito_pip(casa):
    import sys

    lavoratore = librerie.Installatore()
    comando = [sys.executable, "-c", "import time\nwhile True:\n    print('Progress 1 of 2', flush=True)\n    time.sleep(0.05)"]
    esito = {}

    def gira():
        try:
            esito["ok"] = librerie.esegui_pip(
                comando, lavoratore.stato, lavoratore.fermati,
                quando_parte=lambda p: setattr(lavoratore, "_processo", p))
        except librerie.Interrotto:
            esito["ok"] = False

    filo = threading.Thread(target=gira)
    filo.start()
    for _ in range(100):
        if lavoratore._processo is not None:
            break
        threading.Event().wait(0.02)
    lavoratore.ferma()
    filo.join(timeout=10)
    assert not filo.is_alive()
    assert lavoratore._processo.poll() is not None


def test_gli_installatori_vecchi_si_buttano(casa):
    contenuto = b"nuovo"
    tenuto = aggiornamenti.scarica(_rilascio_vero(contenuto, "9.0.0-beta.1"),
                                   apri=lambda *a, **k: RispostaFinta(contenuto))
    vecchio = carta.cartella_scaricati() / "local-ai-frame-classifier-1.0.0.exe"
    vecchio.write_bytes(b"vecchio")
    assert aggiornamenti.pulisci_gli_scaricati() == 1
    assert tenuto.exists() and not vecchio.exists()
    carta.aggiorna(aggiornamento_scaricato=None)
    assert aggiornamenti.pulisci_gli_scaricati() == 1
    assert not tenuto.exists()


def test_lo_spegnimento_bloccato_non_tiene_aperto_il_programma(casa):
    from officina.programma import avvio

    programma = avvio.Programma.__new__(avvio.Programma)
    fermo = threading.Event()
    programma.spegni = lambda avanza=None: fermo.wait(5)
    partenza = time.monotonic()
    assert programma.spegni_entro(secondi=0.2) is False
    assert time.monotonic() - partenza < 2
    fermo.set()
    programma.spegni = lambda avanza=None: None
    assert programma.spegni_entro(secondi=1) is True
