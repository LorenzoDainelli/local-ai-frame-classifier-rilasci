from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso, uno
from officina.modello import etichette, nodi, persone, telefoni
from officina.telefono import lettore, selezione
from officina.web import lavori
from officina.web import telefono as telefono_web

PAROLA = "tre parole che ricordi"


@pytest.fixture
def cliente(archivio_pieno, monkeypatch):
    from officina.web.server import app

    monkeypatch.setattr(telefono_web, "in_corso", telefono_web.InCorso())
    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def telefono(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        return telefoni.crea(connessione, "iPhone", "ios")


def _aspetta_che_finisca(quanto: float = 60.0) -> None:
    fine = time.monotonic() + quanto
    while telefono_web.in_corso.lavoro.sta_lavorando:
        if time.monotonic() > fine:
            raise AssertionError("il travaso non è finito in tempo")
        time.sleep(0.05)


def _finge_che_stia_andando(monkeypatch, finto) -> None:
    monkeypatch.setattr(lavori.Lavoro, "sta_lavorando",
                        property(lambda self: True))
    monkeypatch.setattr(telefono_web, "in_corso", finto)


def _salva(cliente, telefono_id: int, **campi) -> dict:
    risposta = cliente.post(f"/telefono/{telefono_id}/selezione", data=campi,
                            headers={"Accept": "application/json"})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def test_la_quinta_voce_porta_alla_schermata(cliente):
    pagina = cliente.get("/").text
    assert 'href="/fuori"' in pagina
    assert cliente.get("/fuori").status_code == 200


def test_la_vecchia_pagina_porta_ai_dispositivi(cliente, telefono):
    for vecchia, nuova in (("/telefono", "/fuori"),
                           (f"/telefono?quale={telefono}", f"/fuori?quale={telefono}")):
        risposta = cliente.get(vecchia, follow_redirects=False)
        assert risposta.status_code == 303
        assert risposta.headers["location"] == nuova
    risposta = cliente.post(f"/telefono/{telefono}/selezione", data={"senza_data": "1"},
                            follow_redirects=False)
    assert risposta.headers["location"] == f"/fuori?quale={telefono}"


def test_senza_telefoni_dice_come_se_ne_aggiunge_uno(cliente):
    pagina = cliente.get("/fuori").text
    assert "Aggiungi un telefono" in pagina
    assert "Visore-iPhone" in pagina


def test_un_telefono_nuovo_parte_da_tutto_l_archivio(cliente, archivio_pieno):
    risposta = cliente.post("/telefono/nuovo", data={"nome": "Redmi",
                                                     "sistema": "android"})
    assert risposta.status_code == 200

    with archivio_pieno.lettura() as connessione:
        riga = telefoni.per_nome(connessione, "Redmi")
        scelta = telefono_web.scelta_di(riga)
        tutti_gli_scatti = uno(
            connessione, "SELECT count(*) AS q FROM scatti "
            "WHERE fuori_archivio = 0 AND sembra_schermata = 0")["q"]
        stima = selezione.stima(connessione, scelta)

    assert scelta.e_tutto
    assert stima.quanti_scatti == tutti_gli_scatti


def test_due_telefoni_hanno_selezioni_che_non_si_toccano(cliente, archivio_pieno):
    cliente.post("/telefono/nuovo", data={"nome": "Uno", "sistema": "ios"})
    cliente.post("/telefono/nuovo", data={"nome": "Due", "sistema": "android"})
    with archivio_pieno.lettura() as connessione:
        uno_id = telefoni.per_nome(connessione, "Uno")["id"]
        due_id = telefoni.per_nome(connessione, "Due")["id"]

    _salva(cliente, uno_id, dal="2015-01-01", senza_data="1")

    with archivio_pieno.lettura() as connessione:
        primo = telefono_web.scelta_di(telefoni.per_id(connessione, uno_id))
        secondo = telefono_web.scelta_di(telefoni.per_id(connessione, due_id))
    assert primo.dal_giorno == "2015-01-01"
    assert secondo.e_tutto


def test_stringere_il_periodo_fa_scendere_il_conto(cliente, telefono,
                                                   archivio_pieno):
    prima = _salva(cliente, telefono, senza_data="1")
    assert prima["quanti_scatti"] > 0

    with archivio_pieno.lettura() as connessione:
        piu_recente = uno(connessione,
                          "SELECT max(giorno) AS g FROM scatti "
                          "WHERE fuori_archivio = 0 AND giorno IS NOT NULL")["g"]

    dopo = _salva(cliente, telefono, dal=piu_recente, al=piu_recente)
    assert dopo["quanti_scatti"] < prima["quanti_scatti"]
    assert dopo["quanti_scatti"] > 0


def test_il_conto_che_torna_e_quello_della_selezione_appena_salvata(
        cliente, telefono, archivio_pieno):
    detto = _salva(cliente, telefono, dal="2099-01-01", senza_data="")
    assert detto["quanti_scatti"] == 0

    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
        vero = selezione.stima(connessione, scelta).quanti_scatti
    assert vero == detto["quanti_scatti"]


def test_una_data_che_non_e_una_data_non_ferma_e_non_inventa(cliente, telefono):
    detto = _salva(cliente, telefono, dal="l'anno scorso", senza_data="1")
    assert detto["quanti_scatti"] > 0
    assert "dal" not in detto["scelta_a_parole"]


def test_la_selezione_si_ricorda_senza_un_tasto_che_lo_chieda(cliente, telefono):
    _salva(cliente, telefono, dal="2015-06-01", senza_data="1")
    pagina = cliente.get(f"/fuori?quale={telefono}").text
    assert 'value="2015-06-01"' in pagina


def test_tutto_tranne_le_foto_in_cui_c_e_una_persona(cliente, telefono,
                                                     archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        persona = persone.crea(connessione, "Marco")
        quali = [r["id"] for r in connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "AND sembra_schermata = 0 ORDER BY id LIMIT 3")]
        for scatto_id in quali:
            persone.metti_a_mano(connessione, scatto_id, persona)

    tutto = _salva(cliente, telefono, senza_data="1")
    senza = _salva(cliente, telefono, senza_data="1", persone_escluse=str(persona))

    assert senza["quanti_scatti"] == tutto["quanti_scatti"] - len(quali)
    assert "senza 1 persona" in senza["scelta_a_parole"]

    solo = _salva(cliente, telefono, senza_data="1", persone=str(persona))
    assert solo["quanti_scatti"] == len(quali)


def test_solo_le_persone_con_un_nome_si_possono_scegliere(cliente, telefono,
                                                          archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        persone.crea(connessione)
        persone.crea(connessione, "Anna")

    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
        voci = telefono_web.voci_delle_persone(connessione, scelta)
    assert [v["nome"] for v in voci] == ["Anna"]


def test_scegliere_un_ramo_prende_anche_i_figli(cliente, telefono,
                                                archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        padre = nodi.crea(connessione, "un ramo")
        figlio = nodi.crea(connessione, "un rametto", padre)
        quali = [r["id"] for r in connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "AND sembra_schermata = 0 ORDER BY id LIMIT 2")]
        for scatto_id in quali:
            etichette.metti(connessione, scatto_id, figlio, "si")

    detto = _salva(cliente, telefono, senza_data="1", nodi=str(padre))
    assert detto["quanti_scatti"] == len(quali)


def test_il_figlio_di_un_ramo_scelto_si_vede_come_ereditato(cliente, telefono,
                                                            archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        padre = nodi.crea(connessione, "padre")
        figlio = nodi.crea(connessione, "figlio", padre)

    _salva(cliente, telefono, senza_data="1", nodi=str(padre))
    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
        voci = {v["id"]: v for v in telefono_web.voci_dei_nodi(connessione, scelta)}

    assert voci[padre]["preso"]
    assert not voci[figlio]["preso"]
    assert voci[figlio]["dentro_un_ramo_gia_preso"]
    assert voci[figlio]["genitore"] == padre


def test_se_non_ci_sta_lo_dice_e_non_blocca(cliente, telefono, archivio_pieno):
    cliente.post(f"/telefono/{telefono}/dove",
                 data={"cartella": "Visore-iPhone", "spazio": "0,000001"})
    detto = _salva(cliente, telefono, senza_data="1")

    quali = [a["testo"] for a in detto["avvisi"]]
    assert any("Non ci sta per" in t for t in quali), quali

    pagina = cliente.get(f"/fuori?quale={telefono}").text
    assert "disabled" not in pagina.split('id="tasto-parti"')[1][:120]


def test_se_lo_spazio_non_si_sa_lo_dice_invece_di_dire_di_si(cliente, telefono):
    detto = _salva(cliente, telefono, senza_data="1")
    assert any("non lo so" in a["testo"] for a in detto["avvisi"])


def test_il_tasto_dice_cosa_fa(cliente, telefono):
    detto = _salva(cliente, telefono, senza_data="1")
    assert detto["tasto"].startswith("Prepara ")
    assert detto["tasto"].endswith("per iPhone")
    assert detto["tasto"] in cliente.get(f"/fuori?quale={telefono}").text


def test_dice_quante_foto_toglie_prima_di_toglierle(cliente, telefono,
                                                    archivio_pieno, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    cliente.post(f"/telefono/{telefono}/dove", data={"cartella": str(dove)})
    _salva(cliente, telefono, senza_data="1")
    cliente.post(f"/telefono/{telefono}/parti",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta_che_finisca()

    detto = _salva(cliente, telefono, dal="2099-01-01", senza_data="")
    assert detto["se_ne_vanno"] > 0
    assert any("Tolgo" in a["testo"] for a in detto["avvisi"])


def test_il_pacchetto_fatto_dalla_pagina_si_riapre(cliente, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    cliente.post(f"/telefono/{telefono}/dove",
                 data={"cartella": str(dove), "spazio": "128"})
    cliente.post(f"/telefono/{telefono}/parti",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta_che_finisca()

    detto = telefono_web.in_corso.come_va()
    assert detto["completo"], detto["guasti"]
    assert detto["scritti"] > 0

    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.completo
        assert pacchetto.quanti() > 0
        assert pacchetto.verifica().tutto_a_posto


def test_senza_cartella_non_parte_e_dice_dove_scriverla(cliente, telefono):
    risposta = cliente.post(f"/telefono/{telefono}/parti",
                            data={"password": PAROLA, "ancora": PAROLA})
    assert risposta.status_code == 400
    assert "in che cartella" in risposta.text
    assert not telefono_web.in_corso.lavoro.sta_lavorando


def test_due_password_diverse_non_toccano_niente(cliente, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    cliente.post(f"/telefono/{telefono}/dove", data={"cartella": str(dove)})
    risposta = cliente.post(f"/telefono/{telefono}/parti",
                            data={"password": PAROLA, "ancora": "un'altra cosa"})
    assert risposta.status_code == 400
    assert "non coincidono" in risposta.text
    assert not dove.exists()


def test_la_password_non_esce_mai_da_quello_che_la_pagina_legge(
        cliente, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    cliente.post(f"/telefono/{telefono}/dove", data={"cartella": str(dove)})
    cliente.post(f"/telefono/{telefono}/parti",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta_che_finisca()

    detto = repr(telefono_web.in_corso.come_va())
    assert PAROLA not in detto
    assert PAROLA not in cliente.get("/api/telefono").text
    assert PAROLA not in cliente.get(f"/fuori?quale={telefono}").text


def test_uno_alla_volta(cliente, telefono, archivio_pieno, tmp_path,
                        monkeypatch):
    cliente.post(f"/telefono/{telefono}/dove",
                 data={"cartella": str(tmp_path / "Visore-iPhone")})
    _finge_che_stia_andando(monkeypatch, telefono_web.InCorso())

    risposta = cliente.post(f"/telefono/{telefono}/parti",
                            data={"password": PAROLA, "ancora": PAROLA})
    assert risposta.status_code == 400
    assert "uno alla volta" in risposta.text


def test_il_segno_del_travaso_si_vede_da_ogni_pagina(cliente, telefono,
                                                     monkeypatch):
    finto = telefono_web.InCorso()
    finto.nome = "iPhone"
    finto.fase = "scrivo"
    finto.fatti, finto.quanti = 40, 100
    _finge_che_stia_andando(monkeypatch, finto)

    for dove in ("/", "/officina", "/stato", "/impostazioni"):
        pagina = cliente.get(dove).text
        assert "Sto preparando il pacchetto per iPhone" in pagina, dove
        assert "col-travaso" in pagina, dove


def test_un_telefono_con_un_travaso_in_corso_non_si_dimentica(
        cliente, telefono, monkeypatch):
    finto = telefono_web.InCorso()
    finto.telefono_id = telefono
    _finge_che_stia_andando(monkeypatch, finto)

    risposta = cliente.post(f"/telefono/{telefono}/dimentica")
    assert risposta.status_code == 400
    assert "Fermalo prima" in risposta.text


@pytest.mark.parametrize("scritto, byte", [
    ("128", 128_000_000_000),
    ("127,5", 127_500_000_000),
    ("127.5", 127_500_000_000),
    ("", None),
    ("   ", None),
    ("0", None),
])
def test_lo_spazio_si_scrive_come_viene(scritto, byte):
    assert telefono_web.gb_dal_campo(scritto) == byte


@pytest.mark.parametrize("byte, scritto", [
    (128_000_000_000, "128"),
    (127_500_000_000, "127,5"),
    (1_500_000_000, "1,5"),
    (1_000_000, "0,001"),
    (None, ""),
])
def test_lo_spazio_si_rilegge_come_lo_hai_scritto(byte, scritto):
    assert telefono_web.spazio_in_gb(byte) == scritto
    assert telefono_web.gb_dal_campo(scritto) == byte


def test_uno_spazio_che_non_e_un_numero_lo_dice(cliente, telefono):
    risposta = cliente.post(f"/telefono/{telefono}/dove",
                            data={"cartella": "", "spazio": "tantissimo"})
    assert risposta.status_code == 400
    assert "gigabyte" in risposta.text


@pytest.fixture
def con_diario(archivio_pieno, telefono):
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO luoghi (nome, centro_lat, centro_lon, raggio_metri, "
            "quanti, nato_il) VALUES ('casa della nonna', 44.4938, 11.3426, "
            "60, 12, ?)", (adesso(),))
        for aperto, durata, lat, lon, foto in (
                ("2026-03-02T14:32:05", 1080, 44.4939, 11.3427, 41),
                ("2026-03-01T09:10:00", 45, 45.9000, 12.9000, 3),
                ("2026-02-28T21:00:00", 3900, None, None, 210)):
            connessione.execute(
                "INSERT INTO diario_visore (telefono_id, aperto_il, durata_s, "
                "latitudine, longitudine, quante_foto, tornato_il) "
                "VALUES (?,?,?,?,?,?,?)",
                (telefono, aperto, durata, lat, lon, foto, adesso()))
    return telefono


def test_il_diario_traduce_le_coordinate_solo_quando_puo(archivio_pieno,
                                                         con_diario):
    with archivio_pieno.lettura() as connessione:
        detto = telefono_web.diario(connessione, con_diario)

    righe = detto["righe"]
    assert [r["quando"] for r in righe][0] == "2 marzo 2026, 14:32"
    assert righe[0]["dove"] == "casa della nonna"
    assert righe[0]["e_un_luogo"]
    assert not righe[1]["e_un_luogo"]
    assert "45,9000" in righe[1]["dove"]
    assert righe[2]["dove"] == ""
    assert righe[2]["quante_foto"] == 210


@pytest.mark.parametrize("secondi, detto", [
    (45, "45 secondi"),
    (1080, "18 minuti"),
    (3600, "1 ora"),
    (3900, "1 ora e 5 minuti"),
    (7500, "2 ore e 5 minuti"),
    (None, ""),
])
def test_le_durate_si_dicono_come_le_direbbe_una_persona(secondi, detto):
    assert telefono_web._durata_a_parole(secondi) == detto


def test_il_diario_si_apre_dai_dispositivi(cliente, con_diario):
    pagina = cliente.get(f"/fuori?quale={con_diario}").text
    assert 'data-apri-finestra="diario"' in pagina
    assert '<dialog class="finestra larga" id="diario"' in pagina
    dentro = pagina.split('id="diario"')[1]
    assert "casa della nonna" in dentro


def test_il_diario_non_ha_nessun_modo_di_cancellarsi(cliente, con_diario):
    from officina.web.server import tutte_le_strade

    strade = [r.path for r in tutte_le_strade() if "diario" in r.path]
    assert strade == []
    pagina = cliente.get(f"/fuori?quale={con_diario}").text
    dentro = pagina.split("Il diario")[1]
    for parola in ("cancella", "svuota", "dimentica il diario"):
        assert parola not in dentro.lower()
