from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.errori import ErroreOfficina
from officina.web import esplora


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_senza_niente_mostra_i_dischi():
    detto = esplora.dentro("")
    assert detto["dove"] == "" and detto["voci"]
    assert all(voce["disco"] for voce in detto["voci"])


def test_mostra_solo_le_cartelle_e_non_quelle_nascoste(tmp_path):
    (tmp_path / "Viaggi").mkdir()
    (tmp_path / "anni").mkdir()
    (tmp_path / ".nascosta").mkdir()
    (tmp_path / "$Cestino").mkdir()
    (tmp_path / "foto.jpg").write_bytes(b"x")
    detto = esplora.dentro(str(tmp_path))
    assert [voce["nome"] for voce in detto["voci"]] == ["anni", "Viaggi"]
    assert detto["su"] == str(tmp_path.parent)
    assert detto["libero"] and not detto["troppe"]


def test_tante_cartelle_si_tagliano_e_lo_dice(tmp_path, monkeypatch):
    monkeypatch.setattr(esplora, "QUANTE_AL_MASSIMO", 3)
    for numero in range(5):
        (tmp_path / f"c{numero}").mkdir()
    detto = esplora.dentro(str(tmp_path))
    assert len(detto["voci"]) == 3 and detto["troppe"]


@pytest.mark.parametrize("scritto", ["\\\\casa\\foto", "//casa/foto", "foto/viaggi",
                                     "/non/ce/proprio"])
def test_le_cartelle_di_rete_relative_o_assenti_non_si_aprono(scritto):
    with pytest.raises(ErroreOfficina):
        esplora.dentro(scritto)


def test_una_cartella_nuova_si_crea_dentro(tmp_path):
    fatta = esplora.nuova(str(tmp_path), "  Visore iPhone ")
    assert fatta == str(tmp_path / "Visore iPhone")
    assert (tmp_path / "Visore iPhone").is_dir()
    with pytest.raises(ErroreOfficina, match="già"):
        esplora.nuova(str(tmp_path), "Visore iPhone")


@pytest.mark.parametrize("nome", ["", "..", "a/b", "a\\b", "con", "LPT1.txt", "fine.",
                                  "x" * 121, "due:punti"])
def test_i_nomi_sbagliati_non_creano_niente(tmp_path, nome):
    with pytest.raises(ErroreOfficina):
        esplora.nuova(str(tmp_path), nome)
    assert not list(tmp_path.iterdir())


def test_le_strade_sfogliano_e_creano(cliente, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("sfoglia")
    (tmp_path / "dentro").mkdir()
    detto = cliente.get("/api/cartelle", params={"dove": str(tmp_path)}).json()
    assert [voce["nome"] for voce in detto["voci"]] == ["dentro"]
    fatta = cliente.post("/api/cartelle/nuova",
                         data={"dove": str(tmp_path), "nome": "nuova"},
                         headers={"accept": "application/json"}).json()
    assert fatta["percorso"] == str(tmp_path / "nuova")
    sbagliata = cliente.get("/api/cartelle", params={"dove": "//casa/foto"},
                            headers={"accept": "application/json"})
    assert sbagliata.status_code == 400 and "rete" in sbagliata.json()["messaggio"]


def test_la_cartella_del_telefono_si_salva_e_ridà_il_conto(cliente, tmp_path):
    cliente.post("/telefono/nuovo", data={"nome": "iPhone", "sistema": "ios"},
                 follow_redirects=False)
    vuota = tmp_path / "vuota"
    vuota.mkdir()
    detto = cliente.post("/telefono/1/dove",
                         data={"cartella": str(vuota), "spazio": "100"},
                         headers={"accept": "application/json"}).json()
    assert detto["cartella"] == str(vuota)
    assert detto["spazio_byte"] and "peso_byte" in detto and "senza_etichetta" in detto
