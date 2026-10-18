from __future__ import annotations

import json

import pytest

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro import chiavi, disco

PAROLA = "tre parole che ricordo"
NUOVA = "quattro parole nuove davvero"
LEGGERO = 2 ** 10
COSTO_VERO = chiavi.COSTO
AMMESSI_VERI = chiavi.COSTI_AMMESSI


@pytest.fixture(autouse=True)
def costo_leggero(monkeypatch):
    monkeypatch.setattr(chiavi, "COSTO", LEGGERO)
    monkeypatch.setattr(chiavi, "COSTO_LENTO", LEGGERO * 2)
    monkeypatch.setattr(chiavi, "COSTI_AMMESSI", (LEGGERO, LEGGERO * 2))


@pytest.fixture
def cassetto(tmp_path):
    return tmp_path / "Archivio.sicuro"


def _segreto(chiave) -> bytes:
    return chiave._segreto


def test_si_crea_e_si_riapre_con_la_stessa_password(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    riaperta = chiavi.apri(cassetto, PAROLA)
    assert riaperta.nome == chiave.nome
    assert _segreto(riaperta) == _segreto(chiave)


def test_le_due_copie_della_chiave_sono_uguali(cassetto):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    assert ((cassetto / chiavi.FILE).read_bytes()
            == (cassetto / chiavi.RISERVA).read_bytes())


def test_il_file_della_chiave_non_contiene_la_chiave(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        dentro = (cassetto / nome).read_bytes()
        assert _segreto(chiave) not in dentro
        assert _segreto(chiave).hex().encode() not in dentro
        assert PAROLA.encode() not in dentro


def test_la_password_sbagliata_non_apre_e_lo_dice(cassetto):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    with pytest.raises(PasswordSbagliata) as scoppio:
        chiavi.apri(cassetto, "un'altra password lunga")
    assert "chiave di riserva" in scoppio.value.messaggio


@pytest.mark.parametrize("sbagliata", [
    "", "tre parole che ricord", "tre parole che ricordo ", " tre parole che ricordo",
    "Tre parole che ricordo", "tre parole che ricordò", "TRE PAROLE CHE RICORDO",
])
def test_ogni_password_quasi_giusta_e_sbagliata(cassetto, sbagliata):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(cassetto, sbagliata)


@pytest.mark.parametrize("corta", ["", "a", "undici cara", "12345678901"])
def test_una_password_corta_non_crea_niente(cassetto, corta):
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.crea(cassetto, corta, costo=LEGGERO)
    assert scoppio.value.codice == "password_corta"
    assert not cassetto.exists()


@pytest.mark.parametrize("parola", [
    "dodici caratt", "àèìòù perché così", "🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮",
    "  spazi davanti e dietro  ", "tab\tdentro la password", "a" * 500,
])
def test_password_di_ogni_tipo(cassetto, parola):
    chiave = chiavi.crea(cassetto, parola, costo=LEGGERO)
    assert chiavi.apri(cassetto, parola).nome == chiave.nome


def test_non_si_crea_due_volte(cassetto):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.crea(cassetto, NUOVA, costo=LEGGERO)
    assert scoppio.value.codice == "chiave_esiste"
    assert chiavi.apri(cassetto, PAROLA)


def test_senza_archivio_lo_dice(cassetto):
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.apri(cassetto, PAROLA)
    assert scoppio.value.codice == "sicuro_mancante"


@pytest.mark.parametrize("rovina", ["vuoto", "spazzatura", "tagliato", "json_altro",
                                    "senza_porte", "porta_storta"])
def test_se_si_rovina_il_principale_apre_la_riserva_e_lo_rimette(cassetto, rovina):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    buono = (cassetto / chiavi.FILE).read_bytes()
    _rovina(cassetto / chiavi.FILE, rovina)
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome
    assert (cassetto / chiavi.FILE).read_bytes() == buono


@pytest.mark.parametrize("rovina", ["vuoto", "spazzatura", "tagliato", "json_altro",
                                    "senza_porte", "porta_storta"])
def test_se_si_rovina_la_riserva_si_rimette(cassetto, rovina):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    buono = (cassetto / chiavi.FILE).read_bytes()
    _rovina(cassetto / chiavi.RISERVA, rovina)
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome
    assert (cassetto / chiavi.RISERVA).read_bytes() == buono


def test_se_manca_il_principale_basta_la_riserva(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    (cassetto / chiavi.FILE).unlink()
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome
    assert (cassetto / chiavi.FILE).exists()


@pytest.mark.parametrize("rovina", ["vuoto", "spazzatura", "tagliato"])
def test_se_si_rovinano_tutte_e_due_lo_dice_e_parla_della_chiavetta(cassetto, rovina):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    _rovina(cassetto / chiavi.FILE, rovina)
    _rovina(cassetto / chiavi.RISERVA, rovina)
    with pytest.raises(chiavi.ChiaveRovinata) as scoppio:
        chiavi.apri(cassetto, PAROLA)
    assert "chiavetta" in scoppio.value.messaggio


def test_un_byte_cambiato_nella_chiave_chiusa_non_da_una_chiave_sbagliata(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        documento = json.loads((cassetto / nome).read_text("utf-8"))
        chiusa = bytearray.fromhex(documento["porte"][0]["chiusa"])
        chiusa[3] ^= 0x10
        documento["porte"][0]["chiusa"] = chiusa.hex()
        (cassetto / nome).write_text(json.dumps(documento), "utf-8")
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(cassetto, PAROLA)
    assert chiave


def test_un_nome_scambiato_viene_scoperto(cassetto):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        documento = json.loads((cassetto / nome).read_text("utf-8"))
        documento["nome"] = "0" * 32
        (cassetto / nome).write_text(json.dumps(documento), "utf-8")
    with pytest.raises(chiavi.ChiaveRovinata):
        chiavi.apri(cassetto, PAROLA)


@pytest.mark.parametrize("campo, valore", [
    ("n", 2 ** 30), ("n", 3), ("n", "1024"), ("r", 1), ("p", 4), ("kdf", "pbkdf2"),
    ("sale", "zz"), ("nonce", "00"), ("chiusa", ""), ("numero", 7),
])
def test_una_porta_con_numeri_strani_non_si_prova(cassetto, campo, valore):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        documento = json.loads((cassetto / nome).read_text("utf-8"))
        documento["porte"][0][campo] = valore
        (cassetto / nome).write_text(json.dumps(documento), "utf-8")
    with pytest.raises(chiavi.ChiaveRovinata):
        chiavi.apri(cassetto, PAROLA)


def test_una_versione_piu_nuova_chiede_di_aggiornare(cassetto):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    documento = json.loads((cassetto / chiavi.FILE).read_text("utf-8"))
    documento["versione"] = chiavi.VERSIONE + 1
    (cassetto / chiavi.FILE).write_text(json.dumps(documento), "utf-8")
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.apri(cassetto, PAROLA)
    assert scoppio.value.codice == "versione_piu_nuova"


def test_cambiare_password_tiene_la_stessa_chiave_interna(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.cambia_password(cassetto, chiave, NUOVA)
    riaperta = chiavi.apri(cassetto, NUOVA)
    assert _segreto(riaperta) == _segreto(chiave)
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(cassetto, PAROLA)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        documento = json.loads((cassetto / nome).read_text("utf-8"))
        assert len(documento["porte"]) == 1


def test_cambiare_password_due_volte(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.cambia_password(cassetto, chiave, NUOVA)
    chiavi.cambia_password(cassetto, chiave, "la terza password lunga")
    assert chiavi.apri(cassetto, "la terza password lunga").nome == chiave.nome
    for vecchia in (PAROLA, NUOVA):
        with pytest.raises(PasswordSbagliata):
            chiavi.apri(cassetto, vecchia)


def test_la_password_nuova_corta_non_cambia_niente(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    prima = (cassetto / chiavi.FILE).read_bytes()
    with pytest.raises(ErroreOfficina):
        chiavi.cambia_password(cassetto, chiave, "corta")
    assert (cassetto / chiavi.FILE).read_bytes() == prima


def test_con_una_chiave_di_un_altro_archivio_non_si_cambia(cassetto, tmp_path):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    altra = chiavi.crea(tmp_path / "altro", PAROLA, costo=LEGGERO)
    with pytest.raises(chiavi.ChiaveRovinata):
        chiavi.cambia_password(cassetto, altra, NUOVA)
    assert chiavi.apri(cassetto, PAROLA)


@pytest.mark.parametrize("salta", range(1, 9))
def test_corrente_staccata_durante_il_cambio_tiene_aperta_almeno_una_password(
        cassetto, monkeypatch, salta):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    vera = chiavi.scrivi_tutto
    contatore = {"fatte": 0}

    def a_meta(percorso, dati):
        contatore["fatte"] += 1
        if contatore["fatte"] == salta:
            raise OSError("corrente staccata")
        vera(percorso, dati)

    monkeypatch.setattr(chiavi, "scrivi_tutto", a_meta)
    try:
        chiavi.cambia_password(cassetto, chiave, NUOVA)
        finito = True
    except OSError:
        finito = False
    monkeypatch.setattr(chiavi, "scrivi_tutto", vera)
    aperte = []
    for parola in (PAROLA, NUOVA):
        try:
            aperte.append(chiavi.apri(cassetto, parola).nome == chiave.nome)
        except PasswordSbagliata:
            aperte.append(False)
    if finito:
        assert aperte == [False, True]
    else:
        assert aperte[0], "finché la nuova non è provata, la vecchia vale"


def test_la_vecchia_vale_finche_la_nuova_non_e_provata(cassetto, monkeypatch):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    vera = chiavi._prova
    giri = {"n": 0}

    def prova_che_fallisce(*argomenti):
        giri["n"] += 1
        if giri["n"] == 1:
            raise chiavi.ChiaveRovinata("rileggendo non torna")
        vera(*argomenti)

    monkeypatch.setattr(chiavi, "_prova", prova_che_fallisce)
    with pytest.raises(chiavi.ChiaveRovinata):
        chiavi.cambia_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi, "_prova", vera)
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome


def test_le_sottochiavi_sono_diverse_e_sempre_le_stesse(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    uno = chiave.per_contenuto(b"\x01" * 16)
    due = chiave.per_contenuto(b"\x02" * 16)
    assert uno != due and len(uno) == len(due) == 32
    riaperta = chiavi.apri(cassetto, PAROLA)
    assert riaperta.per_contenuto(b"\x01" * 16) == uno
    assert chiave.per("elenco") != chiave.per("miniature")
    assert chiave.per("elenco") not in (uno, due, _segreto(chiave))


@pytest.mark.parametrize("vietato", ["contenuti", "nome"])
def test_le_sottochiavi_interne_non_si_chiedono(cassetto, vietato):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    with pytest.raises(ValueError):
        chiave.per(vietato)


def test_la_chiave_non_si_fa_vedere_quando_si_stampa(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    assert _segreto(chiave).hex() not in repr(chiave)
    assert _segreto(chiave).hex() not in str(chiave)


def test_due_archivi_hanno_chiavi_diverse(tmp_path):
    uno = chiavi.crea(tmp_path / "uno", PAROLA, costo=LEGGERO)
    due = chiavi.crea(tmp_path / "due", PAROLA, costo=LEGGERO)
    assert uno.nome != due.nome and _segreto(uno) != _segreto(due)


def test_la_copia_per_la_chiavetta_si_apre_da_sola(cassetto, tmp_path):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    altrove = tmp_path / "chiavetta" / "Archivio sicuro"
    chiavi.copia_in(cassetto, altrove)
    assert chiavi.apri(altrove, PAROLA).nome == chiave.nome


def test_il_costo_si_sceglie_fra_i_due_ammessi():
    assert chiavi.costo_per_questo_pc() in (chiavi.COSTO, chiavi.COSTO_LENTO)


def test_il_costo_vero_e_quello_della_regola_505():
    assert COSTO_VERO >= 2 ** 17 and chiavi.MINIMO == 12
    assert all(costo >= 2 ** 17 for costo in AMMESSI_VERI)


def test_scrivere_tutto_non_lascia_file_a_meta(tmp_path, monkeypatch):
    bersaglio = tmp_path / "dato.json"
    bersaglio.write_bytes(b"vecchio")

    def rompi(*_):
        raise OSError("disco pieno")

    monkeypatch.setattr(disco.os, "replace", rompi)
    with pytest.raises(OSError):
        disco.scrivi_tutto(bersaglio, b"nuovo")
    assert bersaglio.read_bytes() == b"vecchio"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dato.json"]


def _rovina(percorso, come: str) -> None:
    if come == "vuoto":
        percorso.write_bytes(b"")
    elif come == "spazzatura":
        percorso.write_bytes(b"\x00\xff" * 300)
    elif come == "tagliato":
        percorso.write_bytes(percorso.read_bytes()[:40])
    elif come == "json_altro":
        percorso.write_text('{"tipo": "altro"}', "utf-8")
    elif come == "senza_porte":
        documento = json.loads(percorso.read_text("utf-8"))
        documento["porte"] = []
        percorso.write_text(json.dumps(documento), "utf-8")
    elif come == "porta_storta":
        documento = json.loads(percorso.read_text("utf-8"))
        documento["porte"][0]["sale"] = "00"
        percorso.write_text(json.dumps(documento), "utf-8")
