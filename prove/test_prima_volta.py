from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno

PASSI = ["/benvenuto", "/benvenuto/chiave", "/benvenuto/modelli",
         "/benvenuto/cartella", "/benvenuto/lavoro", "/benvenuto/pronto"]


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def cliente_vuoto(archivio):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.mark.parametrize("indirizzo", PASSI)
def test_i_sei_passi_rispondono(cliente, indirizzo):
    assert cliente.get(indirizzo).status_code == 200


@pytest.mark.parametrize("indirizzo", PASSI)
def test_ogni_passo_porta_agli_altri(cliente, indirizzo):
    testo = cliente.get(indirizzo).text
    altri = [p for p in PASSI if p != indirizzo]
    for altro in altri:
        assert f'href="{altro}"' in testo, f"da {indirizzo} non si arriva a {altro}"


def test_dentro_la_guida_non_ci_sono_comandi_da_copiare(cliente):
    for indirizzo in PASSI[1:]:
        testo = cliente.get(indirizzo).text
        assert "python -m officina" not in testo, indirizzo
        assert "pip install" not in testo, indirizzo


def test_la_password_e_un_campo_dentro_la_guida(cliente):
    testo = cliente.get("/benvenuto").text
    assert 'action="/forziere/accendi"' in testo
    assert 'name="password"' in testo
    assert "forziere --accendi" not in testo


def test_la_conferma_della_password_e_seria(cliente):
    testo = cliente.get("/benvenuto").text
    assert 'name="ancora"' in testo
    assert 'name="su_carta"' in testo
    assert "password dimenticata" in testo


def test_senza_la_spunta_non_si_accende_niente(cliente):
    risposta = cliente.post("/forziere/accendi", data={
        "password": "tre parole che ricordo",
        "ancora": "tre parole che ricordo",
    }, follow_redirects=False)
    assert risposta.status_code != 303
    assert "spunta" in risposta.text


def test_due_password_diverse_non_accendono_niente(cliente):
    risposta = cliente.post("/forziere/accendi", data={
        "password": "tre parole che ricordo",
        "ancora": "tre parole che ricordavo",
        "su_carta": "1",
    }, follow_redirects=False)
    assert risposta.status_code != 303
    assert "coincidono" in risposta.text


def test_finche_manca_la_password_si_vede(cliente):
    testo = cliente.get("/").text
    assert "senza password" in testo
    assert 'href="/impostazioni#c6"' in testo


def test_la_guida_prova_la_macchina_invece_di_rassicurare(cliente):
    testo = cliente.get("/benvenuto").text
    assert "Questo computer ce la fa" in testo
    assert "Le miniature si fanno" in testo
    assert "archivio si scrive" in testo


def test_la_guida_ha_un_tasto_solo_per_quel_che_manca(cliente):
    testo = cliente.get("/benvenuto/modelli").text
    assert 'action="/modelli/scarica-quel-che-manca"' in testo


def test_la_guida_offre_il_giro_sulle_foto_finte(cliente):
    testo = cliente.get("/benvenuto/pronto").text
    assert 'action="/giro/parti"' in testo
    assert "un archivio a parte" in testo


@pytest.fixture
def come_appena_aperto(monkeypatch):
    from officina.web.strade import comune

    monkeypatch.setattr(comune, "gia_ripreso", False)


def test_il_primo_avvio_porta_qui_da_solo(cliente_vuoto, come_appena_aperto):
    risposta = cliente_vuoto.get("/", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/benvenuto"


def test_con_le_foto_dentro_non_si_rivede_piu(cliente, come_appena_aperto):
    risposta = cliente.get("/", follow_redirects=False)
    assert risposta.headers.get("location") != "/benvenuto"


def test_una_volta_mostrata_non_torna_piu_nemmeno_da_vuota(cliente_vuoto,
                                                           come_appena_aperto,
                                                           monkeypatch, archivio):
    from officina.web.strade import comune

    prima = cliente_vuoto.get("/", follow_redirects=False)
    assert prima.headers["location"] == "/benvenuto"

    monkeypatch.setattr(comune, "gia_ripreso", False)
    dopo = cliente_vuoto.get("/", follow_redirects=False)
    assert dopo.headers.get("location") != "/benvenuto"


def test_chi_la_vuole_rileggere_la_ritrova_dalle_impostazioni(cliente):
    testo = cliente.get("/impostazioni").text
    assert 'href="/benvenuto"' in testo


def test_una_cartella_aggiunta_dalla_guida_torna_alla_guida(cliente, tmp_path):
    risposta = cliente.post("/importazione/cartella",
                            data={"percorso": str(tmp_path),
                                  "dove_torno": "/benvenuto/cartella"},
                            follow_redirects=False)
    assert risposta.headers["location"] == "/benvenuto/cartella"


def test_la_stessa_azione_dall_importazione_torna_all_importazione(cliente, tmp_path):
    risposta = cliente.post("/importazione/cartella",
                            data={"percorso": str(tmp_path)},
                            follow_redirects=False)
    assert risposta.headers["location"] == "/importazione"


@pytest.mark.parametrize("furbata", [
    "https://qualcosa.example/rubami",
    "//qualcosa.example/rubami",
    "/benvenuto-di-un-altro",
    "javascript:alert(1)",
])
def test_non_si_finisce_dove_dice_il_modulo(cliente, tmp_path, furbata):
    risposta = cliente.post("/importazione/cartella",
                            data={"percorso": str(tmp_path),
                                  "dove_torno": furbata},
                            follow_redirects=False)
    assert risposta.headers["location"] == "/importazione"


def test_il_conto_viene_prima_del_tasto_che_comincia(cliente, tmp_path):
    testo = cliente.get("/benvenuto/cartella").text
    assert "Conta i file" in testo or "Nessuna cartella" in testo
    assert "Va bene, comincia" not in testo


def test_dice_che_i_modelli_sono_facoltativi_davvero(cliente):
    testo = cliente.get("/benvenuto/modelli").text
    assert "facoltativi" in testo
    assert "disegnato a mano" in testo


def test_dice_che_all_inizio_non_propone_niente(cliente):
    testo = cliente.get("/benvenuto/pronto").text
    assert "niente" in testo
    assert "/officina" in testo


def test_senza_scatti_l_ultimo_passo_rimanda_indietro(cliente_vuoto):
    testo = cliente_vuoto.get("/benvenuto/pronto").text
    assert "/benvenuto/cartella" in testo
    assert "Comincia a etichettare" not in testo


def test_l_ultimo_passo_apre_uno_scatto_vero(cliente, archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        primo = uno(connessione, "SELECT min(id) AS id FROM scatti "
                                 "WHERE fuori_archivio = 0")["id"]
    assert f"/officina?scatto={primo}" in cliente.get("/benvenuto/pronto").text


def test_la_chiave_si_spiega_senza_mostrarla_mai(cliente):
    testo = cliente.get("/benvenuto/chiave").text
    assert "huggingface.co/settings/tokens" in testo
    assert "Read access to contents of all public gated repos" in testo
    assert "black-forest-labs/FLUX.1-dev" in testo
    assert "Agree and access repository" in testo
    assert "huggingface.co/facebook/sam3" in testo
    assert "huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m" in testo
    assert 'type="password"' in testo
    assert 'href="https' not in testo


def test_lucidflux_si_scarica_solo_dal_suo_tasto_anche_nella_guida(cliente):
    testo = cliente.get("/benvenuto/modelli").text
    assert "passo della chiave" in testo or "LucidFlux" not in testo


def test_la_guida_si_riapre_dal_menu(cliente):
    assert 'href="/benvenuto"' in cliente.get("/impostazioni").text
