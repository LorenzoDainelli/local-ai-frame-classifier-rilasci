from __future__ import annotations

import json
import os

import pytest

from officina.archivio.database import adesso
from officina.descrittori import vettori
from officina.errori import OperazioneNonPermessa
from officina.modello import persone
from officina.volti import gruppi


def impronta(seme: float, quanti: int = 8) -> bytes:
    valori = [seme] + [0.1 * (i + 1) * (1 - seme) for i in range(quanti - 1)]
    return vettori.a_byte(vettori.normalizza(valori))


def metti_scatti(connessione, quanti: int) -> list[int]:
    for _ in range(quanti):
        connessione.execute(
            "INSERT INTO scatti (genere, origine_data, creato_il) "
            "VALUES ('foto','assente','2026-01-01T00:00:00')")
    connessione.commit()
    return [r[0] for r in connessione.execute("SELECT id FROM scatti ORDER BY id")]


def metti_volto(connessione, scatto_id: int, seme: float, nitidezza: float = 1.0,
                persona_id: int | None = None) -> int:
    connessione.execute(
        """
        INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza,
                           sicurezza, impronta, modello, versione, persona_id,
                           trovato_il)
        VALUES (?, 0, ?, 0.05, ?, 0.9, ?, 'volti', '1', ?, ?)
        """,
        (scatto_id, json.dumps([0.1, 0.1, 0.2, 0.3]), nitidezza,
         impronta(seme), persona_id, adesso()))
    connessione.commit()
    return connessione.execute("SELECT max(id) FROM volti").fetchone()[0]


def test_i_volti_che_si_somigliano_finiscono_insieme(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 6)
    for scatto_id in scatti[:3]:
        metti_volto(connessione, scatto_id, 0.95)
    for scatto_id in scatti[3:]:
        metti_volto(connessione, scatto_id, 0.05)

    fatto = gruppi.raggruppa(connessione)
    connessione.commit()

    assert fatto.gruppi_nuovi == 2
    elenco = persone.elenco(connessione)
    assert sorted(voce["volti"] for voce in elenco) == [3, 3]
    assert all(voce["nome"] is None for voce in elenco), \
        "i gruppi nascono senza nome e sono già utilizzabili (regola 82)"


def test_un_volto_solo_non_diventa_una_persona(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 3)
    metti_volto(connessione, scatti[0], 0.95)
    metti_volto(connessione, scatti[1], 0.95)
    metti_volto(connessione, scatti[2], 0.02)

    fatto = gruppi.raggruppa(connessione)
    connessione.commit()
    assert fatto.gruppi_nuovi == 1
    assert fatto.volti_soli == 1


def test_alle_importazioni_successive_i_sicuri_vanno_in_silenzio(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 8)
    marco = persone.crea(connessione, "Persona A")
    altro = persone.crea(connessione, "Persona B")
    for scatto_id in scatti[:2]:
        metti_volto(connessione, scatto_id, 0.95, persona_id=marco)
    for scatto_id in scatti[2:4]:
        metti_volto(connessione, scatto_id, 0.02, persona_id=altro)
    connessione.commit()

    metti_volto(connessione, scatti[4], 0.95)
    fatto = gruppi.raggruppa(connessione)
    connessione.commit()

    assert fatto.assegnati_in_silenzio == 1
    assert "assegnati" in fatto.a_parole()
    quanti = connessione.execute(
        "SELECT count(*) FROM volti WHERE persona_id = ?", (marco,)).fetchone()[0]
    assert quanti == 3


def test_i_forse_finiscono_nel_cassetto_senza_chiedere_niente(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 8)
    for scatto_id in scatti[:3]:
        metti_volto(connessione, scatto_id, 0.95)
    for scatto_id in scatti[3:6]:
        metti_volto(connessione, scatto_id, 0.40)
    fatto = gruppi.raggruppa(connessione)
    connessione.commit()

    assert fatto.gruppi_nuovi == 2, "restano due gruppi, non uno"
    coppie = persone.cassetto(connessione)
    assert len(coppie) == 1
    assert coppie[0]["risposta"] == "da_guardare"
    assert "forse-doppioni" in fatto.a_parole()


def test_il_mazzo_va_dal_gruppo_piu_grande_al_piu_piccolo(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 6)
    piccolo = persone.crea(connessione)
    grande = persone.crea(connessione)
    for scatto_id in scatti[:1]:
        metti_volto(connessione, scatto_id, 0.9, persona_id=piccolo)
    for scatto_id in scatti[1:5]:
        metti_volto(connessione, scatto_id, 0.9, persona_id=grande)
    connessione.commit()

    ordine = [voce["id"] for voce in persone.mazzo(connessione)]
    assert ordine == [grande, piccolo]


def test_saltare_manda_in_fondo_e_non_toglie_niente(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 6)
    primo = persone.crea(connessione)
    secondo = persone.crea(connessione)
    for scatto_id in scatti[:4]:
        metti_volto(connessione, scatto_id, 0.9, persona_id=primo)
    for scatto_id in scatti[4:]:
        metti_volto(connessione, scatto_id, 0.9, persona_id=secondo)
    connessione.commit()

    assert persone.mazzo(connessione)[0]["id"] == primo
    persone.rimanda(connessione, primo)
    connessione.commit()

    ordine = [voce["id"] for voce in persone.mazzo(connessione)]
    assert ordine == [secondo, primo], "torna in fondo, non sparisce"
    assert primo in [voce["id"] for voce in persone.elenco(connessione)], \
        "resta utilizzabile come filtro (regola 82)"


def test_ignorare_e_una_scelta_diversa_da_saltare(archivio):
    connessione = archivio.connessione
    quale = persone.crea(connessione)
    connessione.commit()
    persone.ignora(connessione, quale)
    connessione.commit()
    assert quale not in [voce["id"] for voce in persone.mazzo(connessione)]
    assert quale not in [voce["id"] for voce in persone.elenco(connessione)]
    assert quale in [voce["id"] for voce in persone.elenco(connessione, "ignora")]


def test_un_nome_gia_esistente_fa_una_domanda_non_un_unione(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 4)
    uno_ = persone.crea(connessione, "Persona A")
    metti_volto(connessione, scatti[0], 0.9, persona_id=uno_)
    altro = persone.crea(connessione)
    metti_volto(connessione, scatti[1], 0.1, persona_id=altro)
    connessione.commit()

    gia_visti = persone.omonimi(connessione, "Persona A", tranne=altro)
    assert [voce["id"] for voce in gia_visti] == [uno_]

    persone.chiama(connessione, altro, "Persona A")
    connessione.commit()
    assert len(persone.elenco(connessione)) == 2


def test_unire_sposta_i_volti_e_congela_il_primo(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 4)
    prima = persone.crea(connessione, "Persona A")
    seconda = persone.crea(connessione)
    metti_volto(connessione, scatti[0], 0.9, persona_id=prima)
    metti_volto(connessione, scatti[1], 0.9, persona_id=seconda)
    metti_volto(connessione, scatti[2], 0.9, persona_id=seconda)
    connessione.commit()

    fatto = persone.unisci(connessione, seconda, prima)
    connessione.commit()
    assert fatto["volti_spostati"] == 2
    assert persone.per_id(connessione, seconda)["stato"] == "congelata"
    assert connessione.execute(
        "SELECT count(*) FROM volti WHERE persona_id = ?", (prima,)).fetchone()[0] == 3


def test_l_intruso_diventa_un_gruppo_nuovo_senza_nome(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 4)
    quale = persone.crea(connessione, "Persona A")
    dentro = [metti_volto(connessione, s, 0.9, persona_id=quale) for s in scatti[:3]]
    connessione.commit()

    nuova = persone.non_e_lui(connessione, [dentro[2]])
    connessione.commit()
    assert persone.per_id(connessione, nuova)["nome"] is None
    assert connessione.execute(
        "SELECT persona_id, deciso_da FROM volti WHERE id = ?",
        (dentro[2],)).fetchone()[0] == nuova
    assert connessione.execute(
        "SELECT deciso_da FROM volti WHERE id = ?", (dentro[2],)).fetchone()[0] == "utente"


def test_una_persona_si_puo_mettere_a_mano_su_uno_scatto_senza_volto(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 2)
    quale = persone.crea(connessione, "Persona A")
    connessione.commit()

    persone.metti_a_mano(connessione, scatti[0], quale)
    connessione.commit()

    quanti = connessione.execute(
        "SELECT count(*) FROM persone_negli_scatti WHERE persona_id = ?",
        (quale,)).fetchone()[0]
    assert quanti == 1
    assert connessione.execute(
        "SELECT count(*) FROM volti WHERE persona_id = ?", (quale,)).fetchone()[0] == 0


def test_dimenticare_una_persona_cancella_davvero_e_lascia_le_foto(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 3)
    quale = persone.crea(connessione, "Persona A")
    for scatto_id in scatti:
        metti_volto(connessione, scatto_id, 0.9, persona_id=quale)
    persone.metti_a_mano(connessione, scatti[0], quale)
    connessione.commit()

    fatto = persone.dimentica(connessione, quale)
    connessione.commit()

    assert fatto["volti_cancellati"] == 3
    assert persone.per_id(connessione, quale) is None
    assert connessione.execute("SELECT count(*) FROM volti").fetchone()[0] == 0
    assert connessione.execute(
        "SELECT count(*) FROM persone_negli_scatti").fetchone()[0] == 0
    assert connessione.execute("SELECT count(*) FROM scatti").fetchone()[0] == 3


def test_non_so_rimanda_in_fondo_e_non_cancella(archivio):
    connessione = archivio.connessione
    una = persone.crea(connessione)
    altra = persone.crea(connessione)
    persone.segna_forse(connessione, una, altra, 0.51)
    connessione.commit()

    coppia = persone.cassetto(connessione)[0]
    persone.rispondi_al_forse(connessione, coppia["id"], "non_so")
    connessione.commit()
    assert persone.cassetto(connessione) == []

    assert persone.riapri_i_non_so(connessione) == 1
    connessione.commit()
    assert len(persone.cassetto(connessione)) == 1


def test_si_al_forse_unisce_i_due_gruppi(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 3)
    una = persone.crea(connessione)
    altra = persone.crea(connessione)
    metti_volto(connessione, scatti[0], 0.9, persona_id=una)
    metti_volto(connessione, scatti[1], 0.9, persona_id=altra)
    persone.segna_forse(connessione, una, altra, 0.55)
    connessione.commit()

    coppia = persone.cassetto(connessione)[0]
    fatto = persone.rispondi_al_forse(connessione, coppia["id"], "si")
    connessione.commit()
    assert fatto["unite"] is True
    assert len(persone.elenco(connessione)) == 1


def test_si_vedono_i_volti_piu_diversi_non_i_piu_belli(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 6)
    quale = persone.crea(connessione)
    for scatto_id in scatti[:5]:
        metti_volto(connessione, scatto_id, 0.95, nitidezza=90.0, persona_id=quale)
    strano = metti_volto(connessione, scatti[5], 0.40, nitidezza=2.0,
                         persona_id=quale)
    connessione.commit()

    scelti = [v["id"] for v in persone.volti_di(connessione, quale, quanti=3)]
    assert strano in scelti, "quello diverso deve esserci: è la prova più dura"


def test_la_copertina_e_la_faccia_piu_nitida(archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 3)
    quale = persone.crea(connessione)
    metti_volto(connessione, scatti[0], 0.9, nitidezza=3.0, persona_id=quale)
    piu_nitido = metti_volto(connessione, scatti[1], 0.9, nitidezza=42.0,
                             persona_id=quale)
    connessione.commit()
    assert persone.copertina(connessione, quale)["id"] == piu_nitido


def test_un_gruppo_senza_volti_non_ha_copertina_e_non_esplode(archivio):
    connessione = archivio.connessione
    quale = persone.crea(connessione)
    connessione.commit()
    assert persone.copertina(connessione, quale) is None
    assert persone.volti_di(connessione, quale) == []


def test_non_si_unisce_un_gruppo_a_se_stesso(archivio):
    connessione = archivio.connessione
    quale = persone.crea(connessione)
    connessione.commit()
    with pytest.raises(OperazioneNonPermessa):
        persone.unisci(connessione, quale, quale)


@pytest.fixture
def cliente(archivio):
    from fastapi.testclient import TestClient

    from officina.web import server

    return TestClient(server.app, client=("127.0.0.1", 51000))


def test_dare_un_nome_nuovo_non_chiede_niente(cliente, archivio):
    connessione = archivio.connessione
    quale = persone.crea(connessione)
    connessione.commit()
    risposta = cliente.post(f"/api/persone/{quale}/nome", data={"nome": "Persona A"})
    assert risposta.json()["chiede"] == []
    assert persone.per_id(connessione, quale)["nome"] == "Persona A"


def test_un_nome_gia_preso_fa_la_domanda_e_non_unisce(cliente, archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 2)
    primo = persone.crea(connessione, "Persona A")
    metti_volto(connessione, scatti[0], 0.9, persona_id=primo)
    secondo = persone.crea(connessione)
    connessione.commit()

    risposta = cliente.post(f"/api/persone/{secondo}/nome",
                            data={"nome": "Persona A"}).json()
    assert risposta["unito"] is False
    assert [voce["persona_id"] for voce in risposta["chiede"]] == [primo]
    assert persone.per_id(connessione, secondo)["nome"] is None, \
        "non ha unito niente e non ha nemmeno dato il nome: aspetta la risposta"

    cliente.post(f"/api/persone/{secondo}/nome",
                 data={"nome": "Persona A", "unisci_a": primo})
    assert persone.per_id(connessione, secondo)["stato"] == "congelata"


def test_due_persone_possono_chiamarsi_uguale(cliente, archivio):
    connessione = archivio.connessione
    persone.crea(connessione, "Persona A")
    secondo = persone.crea(connessione)
    connessione.commit()

    cliente.post(f"/api/persone/{secondo}/nome",
                 data={"nome": "Persona A", "accetta_omonimo": "1"})
    assert persone.per_id(connessione, secondo)["nome"] == "Persona A"
    assert persone.per_id(connessione, secondo)["stato"] == "attiva"


def test_il_filtro_per_persona_trova_anche_chi_e_stato_messo_a_mano(archivio):
    from officina.modello.scatti import Filtro
    from officina.modello import scatti as magazzino

    connessione = archivio.connessione
    elenco = metti_scatti(connessione, 3)
    quale = persone.crea(connessione, "Persona A")
    metti_volto(connessione, elenco[0], 0.9, persona_id=quale)
    persone.metti_a_mano(connessione, elenco[1], quale)
    connessione.commit()

    trovati = magazzino.conta(connessione, Filtro(persone=[quale]))
    assert trovati == 2, "uno dal volto, uno detto da te"


def test_dimenticare_una_persona_dalla_rotta(cliente, archivio):
    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 2)
    quale = persone.crea(connessione, "Persona A")
    metti_volto(connessione, scatti[0], 0.9, persona_id=quale)
    connessione.commit()

    risposta = cliente.post(f"/api/persone/{quale}/dimentica")
    assert risposta.json()["volti_cancellati"] == 1
    assert persone.per_id(connessione, quale) is None
    assert connessione.execute("SELECT count(*) FROM scatti").fetchone()[0] == 2


def test_il_ritaglio_di_un_volto_su_un_video_si_apre(archivio_pieno):
    from officina.web import server

    connessione = archivio_pieno.connessione
    riga = connessione.execute(
        "SELECT s.id, f.id AS file FROM scatti s "
        "JOIN file_media f ON f.scatto_id = s.id AND f.ruolo = 'principale' "
        "WHERE s.genere = 'video' LIMIT 1").fetchone()
    if riga is None:
        pytest.skip("in questo archivio finto non ci sono video")

    connessione.execute(
        """
        INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro, area,
                           nitidezza, sicurezza, modello, versione, trovato_il)
        VALUES (?, ?, 0, ?, 0.09, 4.0, 0.9, 'volti', '1', ?)
        """,
        (riga["id"], riga["file"], json.dumps([0.3, 0.2, 0.3, 0.3]), adesso()))
    connessione.commit()
    volto_id = connessione.execute("SELECT max(id) FROM volti").fetchone()[0]

    from fastapi.testclient import TestClient

    con_video = TestClient(server.app, client=("127.0.0.1", 51000))
    risposta = con_video.get(f"/volto/{volto_id}?lato=80")
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store", \
        "regola 339: i ritagli dei volti non restano nella cache del browser"


def _errore_di(nome: str, codice: int):
    errori = pytest.importorskip("huggingface_hub.errors")

    class Risposta:
        status_code = codice
        headers: dict = {}
        url = "https://huggingface.co"
        request = None

    try:
        guasto = getattr(errori, nome)("così ha risposto il sito")
    except TypeError:
        guasto = getattr(errori, nome)("così ha risposto il sito",
                                       response=Risposta())
    guasto.response = Risposta()
    return guasto


def test_i_due_file_dei_volti_hanno_due_posti_diversi():
    from officina.volti import rilevatore, scaricamento

    posti = {fonte.repo for fonte in scaricamento.DA_DOVE.values()}
    assert len(posti) == 2, "due modelli, due pagine"
    assert set(scaricamento.DA_DOVE) == {rilevatore.FILE_RILEVATORE,
                                         rilevatore.FILE_RICONOSCITORE}


def test_e_scritto_quale_dei_due_posti_e_stato_provato():
    from officina.volti import rilevatore, scaricamento

    assert scaricamento.DA_DOVE[rilevatore.FILE_RILEVATORE].provata is True
    assert scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE].provata is True


def test_il_file_che_manca_non_diventa_un_posto_che_non_esiste():
    from officina.descrittori import scaricamento as descrittori
    from officina.volti import rilevatore, scaricamento

    guasto = _errore_di("EntryNotFoundError", 404)
    assert descrittori._che_genere(guasto) == "manca_il_file"

    fonte = scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE]
    testo = scaricamento._perche(
        guasto, rilevatore.FILE_RICONOSCITORE, fonte, [], None)
    assert f"«{fonte.repo}» c'è" in testo
    assert "non esiste" not in testo
    assert f"--file-{scaricamento.come_si_chiama(rilevatore.FILE_RICONOSCITORE)}" in testo


def test_il_posto_che_non_esiste_resta_un_posto_che_non_esiste(monkeypatch):
    from dataclasses import replace

    from officina.volti import rilevatore, scaricamento

    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: [])
    fonte = replace(scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE],
                    provata=False)
    testo = scaricamento._perche(
        _errore_di("RepositoryNotFoundError", 404),
        rilevatore.FILE_RICONOSCITORE, fonte, [], None)
    assert "non esiste, o ha cambiato nome" in testo
    assert "mai stato verificato" in testo, \
        "di un posto dedotto va detto che è dedotto"


def test_quando_il_file_manca_dice_quali_ci_sono_davvero(monkeypatch):
    from officina.volti import rilevatore, scaricamento

    monkeypatch.setattr(scaricamento, "_gli_onnx_di",
                        lambda repo, chiave: ["sface_2021dec.onnx",
                                              "sface_2021dec_int8.onnx"])
    testo = scaricamento._perche(
        _errore_di("EntryNotFoundError", 404),
        rilevatore.FILE_RICONOSCITORE,
        scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE], [], None)
    assert "sface_2021dec_int8.onnx" in testo
    assert "--file-adaface_ir101 sface_2021dec.onnx" in testo


def test_se_non_si_riesce_a_guardare_dentro_manda_alla_pagina(monkeypatch):
    from officina.volti import rilevatore, scaricamento

    monkeypatch.setattr(scaricamento, "_gli_onnx_di", lambda repo, chiave: None)
    fonte = scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE]
    testo = scaricamento._perche(
        _errore_di("EntryNotFoundError", 404),
        rilevatore.FILE_RICONOSCITORE, fonte, [], None)
    assert fonte.pagina in testo


def test_una_pagina_senza_onnx_e_la_pagina_sbagliata(monkeypatch):
    from officina.volti import rilevatore, scaricamento

    monkeypatch.setattr(scaricamento, "_gli_onnx_di", lambda repo, chiave: [])
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: ["tale/sface"])
    testo = scaricamento._perche(
        _errore_di("EntryNotFoundError", 404),
        rilevatore.FILE_RICONOSCITORE,
        scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE], [], None)
    assert "posto sbagliato" in testo
    assert "--repo-adaface_ir101 tale/sface" in testo


def test_quello_che_e_gia_arrivato_viene_detto():
    from officina.volti import rilevatore, scaricamento

    testo = scaricamento._perche(
        _errore_di("EntryNotFoundError", 404),
        rilevatore.FILE_RICONOSCITORE,
        scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE],
        [rilevatore.FILE_RILEVATORE], None)
    assert "il scrfd_10g è arrivato" in testo
    assert "manca solo il adaface_ir101" in testo


def test_la_chiave_non_finisce_nel_messaggio_dei_volti(monkeypatch):
    from officina.volti import rilevatore, scaricamento

    monkeypatch.setattr(scaricamento, "_gli_onnx_di", lambda repo, chiave: None)
    testo = scaricamento._perche(
        RuntimeError("fallito con hf_unsegreto dentro"),
        rilevatore.FILE_RICONOSCITORE,
        scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE], [], "hf_unsegreto")
    assert "hf_unsegreto" not in testo


def test_la_scheda_dice_da_dove_viene_ogni_file(tmp_path):
    from officina.volti import rilevatore, scaricamento

    (tmp_path / rilevatore.FILE_RILEVATORE).write_bytes(b"finto")
    scaricamento._annota(tmp_path, dict(scaricamento.DA_DOVE))
    scheda = json.loads(
        (tmp_path / scaricamento.SCHEDA_SUL_DISCO).read_text(encoding="utf-8"))

    da_dove = scheda["da_dove"]
    assert (da_dove[rilevatore.FILE_RILEVATORE]["repo"]
            != da_dove[rilevatore.FILE_RICONOSCITORE]["repo"])
    assert list(scheda["impronte"]) == [rilevatore.FILE_RILEVATORE], \
        "l'impronta si scrive solo di ciò che c'è davvero"


def _argomenti(**campi):
    import argparse

    base = {"repo": None, "repo_rilevatore": None, "repo_riconoscitore": None,
            "file_rilevatore": None, "file_riconoscitore": None}
    base.update(campi)
    return argparse.Namespace(**base)


def test_dalla_riga_di_comando_si_cambia_un_posto_solo():
    from officina.riga_di_comando import _fonti_dei_volti
    from officina.volti import rilevatore, scaricamento

    fonti = _fonti_dei_volti(_argomenti(repo_riconoscitore="tale/sface"))
    assert fonti[rilevatore.FILE_RICONOSCITORE].repo == "tale/sface"
    assert (fonti[rilevatore.FILE_RILEVATORE]
            == scaricamento.DA_DOVE[rilevatore.FILE_RILEVATORE]), \
        "cambiarne uno non deve toccare l'altro"


def test_repo_da_solo_vale_per_tutti_e_due():
    from officina.riga_di_comando import _fonti_dei_volti

    fonti = _fonti_dei_volti(_argomenti(repo="tale/tutti-e-due"))
    assert {f.repo for f in fonti.values()} == {"tale/tutti-e-due"}
    assert all(f.provata is False for f in fonti.values()), \
        "un posto scelto a mano non è un posto provato"


def test_un_posto_cambiato_non_si_spaccia_per_provato():
    from officina.riga_di_comando import _fonti_dei_volti
    from officina.volti import rilevatore

    fonti = _fonti_dei_volti(_argomenti(repo_rilevatore="altro/posto"))
    assert fonti[rilevatore.FILE_RILEVATORE].provata is False


def test_scaricando_si_ferma_al_primo_guasto_ma_tiene_cio_che_e_arrivato(
        tmp_path, monkeypatch):
    huggingface_hub = pytest.importorskip("huggingface_hub")

    from officina.descrittori.scaricamento import ScaricamentoFallito
    from officina.volti import rilevatore, scaricamento

    def finto_scarica(repo_id, filename, token=None, **_):
        if repo_id == scaricamento.DA_DOVE[rilevatore.FILE_RILEVATORE].repo:
            preso = tmp_path / "preso.onnx"
            preso.write_bytes(b"un rilevatore finto")
            return str(preso)
        raise _errore_di("EntryNotFoundError", 404)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", finto_scarica)
    monkeypatch.setattr(scaricamento, "_dentro_la_pagina", lambda repo, chiave: None)
    monkeypatch.setattr(scaricamento, "_gli_onnx_di", lambda repo, chiave: [])
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: [])

    modelli = tmp_path / "modelli"
    with pytest.raises(ScaricamentoFallito) as guasto:
        scaricamento.scarica(modelli, al_passo=lambda _: None)

    testo = str(guasto.value)
    assert "il scrfd_10g è arrivato" in testo
    assert "senza i volti" in testo, "il resto del programma funziona lo stesso"

    casa = rilevatore.dove_stanno(modelli)
    assert (casa / rilevatore.FILE_RILEVATORE).exists()
    assert not (casa / scaricamento.SCHEDA_SUL_DISCO).exists(), \
        "la scheda si scrive solo quando sono arrivati tutti e due"


def test_la_rete_si_richiude_anche_quando_lo_scaricamento_fallisce(
        tmp_path, monkeypatch):
    huggingface_hub = pytest.importorskip("huggingface_hub")

    from officina.descrittori.scaricamento import ScaricamentoFallito
    from officina.volti import scaricamento

    visto = {}

    def finto_scarica(repo_id, filename, token=None, **_):
        visto["aperta"] = os.environ.get("HF_HUB_OFFLINE")
        raise RuntimeError("niente")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", finto_scarica)
    monkeypatch.setattr(scaricamento, "_dentro_la_pagina", lambda repo, chiave: None)
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: [])
    prima = os.environ.get("HF_HUB_OFFLINE")
    with pytest.raises(ScaricamentoFallito):
        scaricamento.scarica(tmp_path / "modelli", al_passo=lambda _: None)
    assert visto["aperta"] == "0", "durante il comando la rete è aperta"
    assert os.environ.get("HF_HUB_OFFLINE") == prima, "e dopo torna com'era"


def test_l_impronta_pubblicata_riconosce_il_file_giusto(tmp_path):
    import hashlib

    from officina.volti import scaricamento

    percorso = tmp_path / "un.onnx"
    percorso.write_bytes(b"il modello vero")
    giusta = hashlib.sha256(b"il modello vero").hexdigest()

    buona = scaricamento.Fonte("tale/quale", "un.onnx", provata=True,
                               sha256=giusta)
    assert scaricamento.e_quello_giusto(percorso, buona) is True

    sbagliata = scaricamento.Fonte("tale/quale", "un.onnx", provata=True,
                                   sha256="0" * 64)
    assert scaricamento.e_quello_giusto(percorso, sbagliata) is False


def test_di_un_file_scelto_a_mano_non_si_finge_di_sapere(tmp_path):
    from officina.volti import scaricamento

    percorso = tmp_path / "un.onnx"
    percorso.write_bytes(b"chissa'")
    senza = scaricamento.Fonte("tale/quale", "un.onnx", provata=False)
    assert scaricamento.e_quello_giusto(percorso, senza) is None


def test_cambiare_il_nome_del_file_toglie_l_impronta():
    from officina.riga_di_comando import _fonti_dei_volti
    from officina.volti import rilevatore

    fonti = _fonti_dei_volti(_argomenti(file_riconoscitore="un_altro.onnx"))
    riconoscitore = fonti[rilevatore.FILE_RICONOSCITORE]
    assert riconoscitore.sha256 == "" and riconoscitore.licenza == ""


def test_cambiare_solo_il_posto_tiene_l_impronta():
    from officina.riga_di_comando import _fonti_dei_volti
    from officina.volti import rilevatore, scaricamento

    fonti = _fonti_dei_volti(_argomenti(repo_riconoscitore="altro/posto"))
    atteso = scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE]
    assert fonti[rilevatore.FILE_RICONOSCITORE].sha256 == atteso.sha256


def test_se_il_file_non_corrisponde_lo_dice_e_lo_tiene(tmp_path, monkeypatch):
    huggingface_hub = pytest.importorskip("huggingface_hub")

    from officina.volti import rilevatore, scaricamento

    preso = tmp_path / "preso.onnx"
    preso.write_bytes(b"non e' il modello di nessuno")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download",
                        lambda repo_id, filename, token=None, **_: str(preso))
    monkeypatch.setattr(scaricamento, "_dentro_la_pagina", lambda repo, chiave: None)
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: [])

    from dataclasses import replace

    fonti = {nome: replace(fonte, sha256="0" * 64)
             for nome, fonte in scaricamento.DA_DOVE.items()}
    detto = []
    modelli = tmp_path / "modelli"
    scaricamento.scarica(modelli, fonti=fonti, al_passo=detto.append)

    avvisi = [riga for riga in detto if "non corrisponde" in riga]
    assert len(avvisi) == 2, "due file, due avvisi"
    assert "attesa:" in avvisi[0] and "trovata:" in avvisi[0]

    casa = rilevatore.dove_stanno(modelli)
    assert (casa / rilevatore.FILE_RILEVATORE).exists(), "il file resta"

    scheda = json.loads(
        (casa / scaricamento.SCHEDA_SUL_DISCO).read_text(encoding="utf-8"))
    assert all(riga["corrisponde_all_originale"] is False
               for riga in scheda["da_dove"].values())
    assert "non corrispondono all'originale" in \
        scaricamento.verifica(modelli)["dettaglio"]


def test_la_scheda_dice_con_quale_licenza(tmp_path):
    from officina.volti import scaricamento

    scaricamento._annota(tmp_path, dict(scaricamento.DA_DOVE))
    scheda = json.loads(
        (tmp_path / scaricamento.SCHEDA_SUL_DISCO).read_text(encoding="utf-8"))
    licenze = {riga["licenza"] for riga in scheda["da_dove"].values()}
    assert all("non commerciale" in licenza for licenza in licenze)


def test_lo_zero_dell_archivio_finto_non_e_un_guasto():
    import types

    from officina.volti.spiegazione import perche_nessun_volto
    from officina.volti.rilevatore import Conteggio

    passata = types.SimpleNamespace(rilevatore=types.SimpleNamespace(
        conteggio=Conteggio(immagini=40), sicurezza_minima=0.6))

    finto = "\n".join(perche_nessun_volto(passata, True))
    assert "archivio finto" in finto and "non un guasto" in finto

    vero = "\n".join(perche_nessun_volto(passata, False))
    assert "è un difetto" in vero, "sulle foto vere invece è un difetto"


class RilevatoreFinto:

    versione = "1"

    def __init__(self, seme: float = 0.9):
        self.seme = seme
        self.spento = False

    def guarda(self, immagine):
        from officina.volti.rilevatore import Faccia

        nome = getattr(immagine, "nome_finto", "")
        quante = 2 if "due-facce" in nome else (0 if "nessuna" in nome else 1)
        impronta = vettori.normalizza(
            [self.seme] + [0.05 * (i + 1) for i in range(7)])
        return [Faccia(riquadro=(0.1, 0.1, 0.2, 0.3), sicurezza=0.9,
                       nitidezza=1.0, impronta=impronta)
                for _ in range(quante)]

    def spegni(self):
        self.spento = True


@pytest.fixture
def cartella_ritratti(tmp_path, monkeypatch):
    cartella = tmp_path / "ritratti"
    cartella.mkdir()
    for nome in ("uno.jpg", "due-facce.jpg", "nessuna.jpg"):
        (cartella / nome).write_bytes(b"non e' una foto, e non serve che lo sia")

    from officina.volti import riferimento

    def finta_lettura(percorso, lato=None):
        finta = type("Immagine", (), {})()
        finta.nome_finto = percorso.name
        return finta

    monkeypatch.setattr(riferimento.lettura, "copia_di_lavoro", finta_lettura)
    return cartella


def test_una_foto_con_due_facce_viene_saltata_e_detta(archivio, cartella_ritratti):
    from officina.volti import riferimento

    with archivio.scrittura() as connessione:
        chi = persone.crea(connessione, "Marco")

    fuori = riferimento.insegna(archivio, chi, cartella_ritratti,
                                rilevatore=RilevatoreFinto())

    assert fuori.imparate == 1
    assert fuori.con_piu_facce == ["due-facce.jpg"]
    assert fuori.senza_faccia == ["nessuna.jpg"]
    assert "due-facce.jpg" in fuori.a_parole() or "più facce" in fuori.a_parole()


def test_le_facce_insegnate_non_diventano_scatti(archivio, cartella_ritratti):
    from officina.volti import riferimento

    with archivio.lettura() as connessione:
        scatti_prima = connessione.execute(
            "SELECT count(*) FROM scatti").fetchone()[0]
        file_prima = connessione.execute(
            "SELECT count(*) FROM file_media").fetchone()[0]
    with archivio.scrittura() as connessione:
        chi = persone.crea(connessione, "Marco")

    riferimento.insegna(archivio, chi, cartella_ritratti,
                        rilevatore=RilevatoreFinto())

    with archivio.lettura() as connessione:
        assert connessione.execute(
            "SELECT count(*) FROM scatti").fetchone()[0] == scatti_prima
        assert connessione.execute(
            "SELECT count(*) FROM file_media").fetchone()[0] == file_prima
        assert connessione.execute(
            "SELECT count(*) FROM volti").fetchone()[0] == 0
        righe = riferimento.elenco(connessione, chi)
    assert [riga["da_file"] for riga in righe] == ["uno.jpg"]
    assert not any("ritratti" in str(riga.get("da_file")) for riga in righe) \
        or "/" not in righe[0]["da_file"]


def test_ridare_la_stessa_cartella_non_raddoppia_niente(archivio, cartella_ritratti):
    from officina.volti import riferimento

    with archivio.scrittura() as connessione:
        chi = persone.crea(connessione, "Marco")

    riferimento.insegna(archivio, chi, cartella_ritratti,
                        rilevatore=RilevatoreFinto())
    secondo = riferimento.insegna(archivio, chi, cartella_ritratti,
                                  rilevatore=RilevatoreFinto())

    assert secondo.imparate == 0
    assert secondo.gia_avute == 1
    with archivio.lettura() as connessione:
        assert riferimento.quante(connessione, chi) == 1


def test_una_faccia_insegnata_fa_riconoscere_chi_in_archivio_viene_male(archivio):

    connessione = archivio.connessione
    scatti = metti_scatti(connessione, 3)
    marco = persone.crea(connessione, "Marco")
    metti_volto(connessione, scatti[0], 0.20, persona_id=marco)
    metti_volto(connessione, scatti[1], 0.22, persona_id=marco)
    nuovo = metti_volto(connessione, scatti[2], 0.95)

    prima = gruppi.raggruppa(connessione)
    assert prima.assegnati_in_silenzio == 0, \
        "senza riferimento non doveva riconoscerlo: la prova non prova niente"
    connessione.execute("UPDATE volti SET persona_id = NULL WHERE id = ?",
                        (nuovo,))
    connessione.execute(
        "DELETE FROM persone WHERE id != ? AND nome IS NULL", (marco,))
    connessione.execute(
        """
        INSERT INTO volti_riferimento
            (persona_id, da_file, riquadro, area, nitidezza, sicurezza,
             impronta, modello, versione, letto_il)
        VALUES (?, 'ritratto-buono.jpg', '[0,0,1,1]', 0.5, 1.0, 0.99,
                ?, 'volti', '1', ?)
        """,
        (marco, impronta(0.95), adesso()))
    connessione.commit()

    dopo = gruppi.raggruppa(connessione)

    assert dopo.assegnati_in_silenzio == 1
    with archivio.lettura() as connessione:
        assert connessione.execute(
            "SELECT persona_id FROM volti WHERE id = ?", (nuovo,)).fetchone()[0] \
            == marco


def test_unire_due_gruppi_porta_con_se_le_facce_insegnate(archivio):
    from officina.volti import riferimento

    connessione = archivio.connessione
    uno_id = persone.crea(connessione, "Marco")
    due_id = persone.crea(connessione, "Marco con la barba")
    connessione.execute(
        """
        INSERT INTO volti_riferimento
            (persona_id, da_file, riquadro, area, nitidezza, sicurezza,
             impronta, modello, versione, letto_il)
        VALUES (?, 'barba.jpg', '[0,0,1,1]', 0.5, 1.0, 0.99, ?, 'volti', '1', ?)
        """,
        (due_id, impronta(0.5), adesso()))
    connessione.commit()

    persone.unisci(connessione, due_id, uno_id)
    connessione.commit()

    assert riferimento.quante(connessione, uno_id) == 1
    assert riferimento.quante(connessione, due_id) == 0


def test_dimenticare_una_persona_porta_via_anche_le_facce_insegnate(archivio):

    connessione = archivio.connessione
    chi = persone.crea(connessione, "Marco")
    connessione.execute(
        """
        INSERT INTO volti_riferimento
            (persona_id, da_file, riquadro, area, nitidezza, sicurezza,
             impronta, modello, versione, letto_il)
        VALUES (?, 'uno.jpg', '[0,0,1,1]', 0.5, 1.0, 0.99, ?, 'volti', '1', ?)
        """,
        (chi, impronta(0.5), adesso()))
    connessione.commit()
    persone.dimentica(connessione, chi)
    connessione.commit()
    assert connessione.execute(
        "SELECT count(*) FROM volti_riferimento").fetchone()[0] == 0


def test_una_cartella_enorme_si_ferma_e_lo_dice(archivio, tmp_path):
    from officina.errori import ErroreOfficina
    from officina.volti import riferimento

    cartella = tmp_path / "troppe"
    cartella.mkdir()
    for numero in range(riferimento.TROPPE + 1):
        (cartella / f"{numero}.jpg").write_bytes(b"x")

    with pytest.raises(ErroreOfficina) as guasto:
        riferimento.immagini_nella(cartella)
    assert guasto.value.codice == "cartella_troppo_grande"


def test_la_scheda_di_una_persona_si_apre_e_mostra_le_facce_insegnate(
        cliente, archivio):
    connessione = archivio.connessione
    chi = persone.crea(connessione, "Marco")
    connessione.execute(
        """
        INSERT INTO volti_riferimento
            (persona_id, da_file, riquadro, area, nitidezza, sicurezza,
             impronta, modello, versione, letto_il)
        VALUES (?, 'ritratto-buono.jpg', '[0,0,1,1]', 0.5, 1.0, 0.99,
                ?, 'volti', '1', ?)
        """,
        (chi, impronta(0.9), adesso()))
    connessione.commit()

    risposta = cliente.get(f"/persone/{chi}")
    assert risposta.status_code == 200
    assert "ritratto-buono.jpg" in risposta.text
    assert "Marco" in risposta.text


def test_insegnare_senza_cartella_non_parte_e_lo_dice(cliente, archivio):
    connessione = archivio.connessione
    chi = persone.crea(connessione, "Marco")
    connessione.commit()

    risposta = cliente.post(f"/persone/{chi}/insegna", data={"cartella": "  "},
                            follow_redirects=False)
    assert risposta.status_code != 303
    import re

    messaggio = re.search(r'<p class="prosa">(.*?)</p>', risposta.text, re.S)
    assert messaggio, "il messaggio d'errore non c'è più: la prova va rifatta"
    detto = messaggio.group(1)
    assert "cartella" in detto
    assert "modelli" not in detto


@pytest.mark.skipif(not vettori.C_E_NUMPY, reason="senza numpy non si conta")
def test_i_gruppi_a_blocchi_sono_gli_stessi_di_prima():
    import numpy

    caso = numpy.random.default_rng(4242)
    quanti = 700
    quante_misure = 16

    persone_finte = caso.normal(size=(12, quante_misure))
    tabella = numpy.empty((quanti, quante_misure), dtype=numpy.float32)
    for quale in range(quanti):
        chi = persone_finte[quale % 12] + caso.normal(scale=0.25,
                                                      size=quante_misure)
        tabella[quale] = chi / numpy.linalg.norm(chi)

    def come_prima(tavola, soglia):
        vicini = (tavola @ tavola.T) >= soglia
        visti = numpy.zeros(tavola.shape[0], dtype=bool)
        fatti = []
        for partenza in range(tavola.shape[0]):
            if visti[partenza]:
                continue
            da_guardare, gruppo = [partenza], []
            visti[partenza] = True
            while da_guardare:
                quale = da_guardare.pop()
                gruppo.append(quale)
                for altro in numpy.nonzero(vicini[quale] & ~visti)[0]:
                    visti[altro] = True
                    da_guardare.append(int(altro))
            fatti.append(sorted(gruppo))
        return sorted(fatti)

    for soglia in (0.55, 0.62, 0.8):
        vecchi = come_prima(tabella, soglia)
        nuovi = sorted(gruppi._amici_degli_amici(tabella, soglia))
        assert nuovi == vecchi, f"a soglia {soglia} i gruppi non combaciano"
    di_mezzo = gruppi._amici_degli_amici(tabella, 0.62)
    assert 1 < len(di_mezzo) < quanti


@pytest.mark.skipif(not vettori.C_E_NUMPY, reason="senza numpy non si conta")
def test_la_memoria_dei_gruppi_non_cresce_col_quadrato():
    assert gruppi.QUANTI_ALLA_VOLTA <= 1024, (
        "con un blocco così grande la memoria torna a dipendere dal quadrato "
        "del numero dei volti")
