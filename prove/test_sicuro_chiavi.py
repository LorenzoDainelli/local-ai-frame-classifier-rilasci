from __future__ import annotations

import json
import os

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


@pytest.mark.parametrize("storta", [chiavi.FILE, chiavi.RISERVA])
def test_se_il_nome_e_storto_in_una_copia_si_apre_dall_altra_e_si_rimette(
        cassetto, storta):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    buono = (cassetto / chiavi.FILE).read_bytes()
    (cassetto / storta).write_bytes(_guasta(buono, "nome"))
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == [buono, buono]


def _chiave_di_un_altro(cassetto, tmp_path, dove: str, parola: str,
                        col_nostro_nome: bool = False) -> list[bytes]:
    altro = tmp_path / "altro"
    chiavi.crea(altro, parola, costo=LEGGERO)
    documento = json.loads((altro / chiavi.FILE).read_text("utf-8"))
    if col_nostro_nome:
        documento["nome"] = json.loads((cassetto / dove).read_text("utf-8"))["nome"]
    (cassetto / dove).write_bytes(chiavi._in_byte(documento))
    return [(cassetto / nome).read_bytes() for nome in (chiavi.FILE, chiavi.RISERVA)]


@pytest.mark.parametrize("col_nostro_nome", [False, True])
@pytest.mark.parametrize("dove", [chiavi.FILE, chiavi.RISERVA])
def test_la_chiave_di_un_altro_archivio_con_la_stessa_password_non_apre_e_non_si_tocca(
        cassetto, tmp_path, dove, col_nostro_nome):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    prima = _chiave_di_un_altro(cassetto, tmp_path, dove, PAROLA, col_nostro_nome)
    with pytest.raises(chiavi.ChiaveRovinata, match="mescolato") as scoppio:
        chiavi.apri(cassetto, PAROLA)
    assert scoppio.value.codice == "chiave_mescolata"
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == prima


@pytest.mark.parametrize("dove", [chiavi.FILE, chiavi.RISERVA])
def test_la_chiave_di_un_altro_archivio_con_un_altra_password_resta_dov_e(
        cassetto, tmp_path, dove):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    altra = "la password dell'altro archivio"
    prima = _chiave_di_un_altro(cassetto, tmp_path, dove, altra)
    assert chiavi.apri(cassetto, PAROLA).nome == chiave.nome
    assert chiavi.apri(cassetto, altra).nome != chiave.nome
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == prima


@pytest.mark.parametrize("dove", [chiavi.FILE, chiavi.RISERVA])
def test_una_porta_di_un_altra_chiave_nella_stessa_copia_non_apre(
        cassetto, tmp_path, dove):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.crea(tmp_path / "altro", NUOVA, costo=LEGGERO)
    estranea = json.loads((tmp_path / "altro" / chiavi.FILE).read_text("utf-8"))
    documento = json.loads((cassetto / dove).read_text("utf-8"))
    documento["porte"].append(estranea["porte"][0])
    (cassetto / dove).write_bytes(chiavi._in_byte(documento))
    prima = [(cassetto / nome).read_bytes() for nome in (chiavi.FILE, chiavi.RISERVA)]
    with pytest.raises(chiavi.ChiaveRovinata, match="mescolato"):
        chiavi.apri(cassetto, NUOVA)
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == prima
    assert chiavi.apri(cassetto, PAROLA, ripara=False).nome == chiave.nome


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


def _apre(cartella, parola, chiave) -> bool:
    try:
        return chiavi.apri(cartella, parola, ripara=False).nome == chiave.nome
    except PasswordSbagliata:
        return False


def _porte_nei_file(cartella) -> list[int]:
    return [len(json.loads((cartella / nome).read_text("utf-8"))["porte"])
            for nome in (chiavi.FILE, chiavi.RISERVA)]


def test_aggiungere_una_password_tiene_aperte_tutte_e_due(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    assert _apre(cassetto, PAROLA, chiave) and _apre(cassetto, NUOVA, chiave)
    assert _segreto(chiavi.apri(cassetto, NUOVA)) == _segreto(chiave)
    assert chiavi.porte(cassetto) == 2 and _porte_nei_file(cassetto) == [2, 2]


def test_aggiungere_una_password_corta_non_scrive_niente(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    prima = [(cassetto / nome).read_bytes() for nome in (chiavi.FILE, chiavi.RISERVA)]
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.aggiungi_password(cassetto, chiave, "corta")
    assert scoppio.value.codice == "password_corta"
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == prima


def test_aggiungere_non_perde_le_porte_che_sono_solo_nella_riserva(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    documento = json.loads((cassetto / chiavi.RISERVA).read_text("utf-8"))
    documento["porte"] = documento["porte"][:1]
    (cassetto / chiavi.FILE).write_text(json.dumps(documento), "utf-8")
    chiavi.aggiungi_password(cassetto, chiave, "la terza password lunga")
    for parola in (PAROLA, NUOVA, "la terza password lunga"):
        assert _apre(cassetto, parola, chiave)
    assert chiavi.porte(cassetto) == 3


def test_tenere_solo_una_password_chiude_le_altre(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    chiavi.tieni_solo(cassetto, chiave, NUOVA)
    assert not _apre(cassetto, PAROLA, chiave) and _apre(cassetto, NUOVA, chiave)
    assert chiavi.porte(cassetto) == 1 and _porte_nei_file(cassetto) == [1, 1]


def test_tenere_solo_la_vecchia_chiude_la_nuova(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    chiavi.tieni_solo(cassetto, chiave, PAROLA)
    assert _apre(cassetto, PAROLA, chiave) and not _apre(cassetto, NUOVA, chiave)
    assert chiavi.porte(cassetto) == 1


@pytest.mark.parametrize("sbagliata", ["", "un'altra password lunga", PAROLA + " "])
def test_tenere_solo_una_password_sbagliata_non_tocca_niente(cassetto, sbagliata):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    prima = [(cassetto / nome).read_bytes() for nome in (chiavi.FILE, chiavi.RISERVA)]
    with pytest.raises(PasswordSbagliata):
        chiavi.tieni_solo(cassetto, chiave, sbagliata)
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == prima
    assert _apre(cassetto, PAROLA, chiave) and _apre(cassetto, NUOVA, chiave)


def test_tenere_solo_la_porta_che_e_rimasta_solo_nella_riserva(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    documento = json.loads((cassetto / chiavi.RISERVA).read_text("utf-8"))
    documento["porte"] = documento["porte"][1:]
    (cassetto / chiavi.FILE).write_text(json.dumps(documento), "utf-8")
    chiavi.tieni_solo(cassetto, chiave, PAROLA)
    assert _apre(cassetto, PAROLA, chiave) and not _apre(cassetto, NUOVA, chiave)


@pytest.mark.parametrize("funzione", ["aggiungi_password", "tieni_solo"])
def test_con_la_chiave_di_un_altro_archivio_non_si_tocca_niente(
        cassetto, tmp_path, funzione):
    chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    altra = chiavi.crea(tmp_path / "altro", PAROLA, costo=LEGGERO)
    prima = (cassetto / chiavi.FILE).read_bytes()
    with pytest.raises(chiavi.ChiaveRovinata):
        getattr(chiavi, funzione)(cassetto, altra, NUOVA if funzione ==
                                  "aggiungi_password" else PAROLA)
    assert (cassetto / chiavi.FILE).read_bytes() == prima


def test_se_la_riserva_e_di_un_altro_archivio_non_si_tocca_niente(cassetto, tmp_path):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.crea(tmp_path / "altro", PAROLA, costo=LEGGERO)
    (cassetto / chiavi.RISERVA).write_bytes(
        (tmp_path / "altro" / chiavi.RISERVA).read_bytes())
    prima = (cassetto / chiavi.FILE).read_bytes()
    for funzione, parola in ((chiavi.aggiungi_password, NUOVA),
                             (chiavi.tieni_solo, PAROLA)):
        with pytest.raises(chiavi.ChiaveRovinata):
            funzione(cassetto, chiave, parola)
    assert (cassetto / chiavi.FILE).read_bytes() == prima


def test_le_porte_si_contano_una_volta_sola_anche_se_sono_in_tutti_e_due(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    assert chiavi.porte(cassetto) == 1
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    documento = json.loads((cassetto / chiavi.FILE).read_text("utf-8"))
    documento["porte"] = documento["porte"][:1]
    (cassetto / chiavi.FILE).write_text(json.dumps(documento), "utf-8")
    assert chiavi.porte(cassetto) == 2
    (cassetto / chiavi.RISERVA).write_text(json.dumps(documento), "utf-8")
    assert chiavi.porte(cassetto) == 1


def test_le_porte_senza_archivio_lo_dicono(cassetto):
    with pytest.raises(ErroreOfficina) as scoppio:
        chiavi.porte(cassetto)
    assert scoppio.value.codice == "sicuro_mancante"


def test_la_porta_nuova_usa_il_costo_dell_ultima(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO * 2)
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    documento = json.loads((cassetto / chiavi.FILE).read_text("utf-8"))
    assert [porta["n"] for porta in documento["porte"]] == [LEGGERO * 2] * 2


@pytest.mark.parametrize("costi", [(LEGGERO, LEGGERO * 2), (LEGGERO * 2, LEGGERO)])
def test_con_piu_porte_la_nuova_usa_il_costo_dell_ultima(cassetto, costi):
    chiave = chiavi.crea(cassetto, PAROLA, costo=costi[0])
    chiavi.aggiungi_password(cassetto, chiave, NUOVA, costo=costi[1])
    chiavi.aggiungi_password(cassetto, chiave, "la terza password lunga")
    documento = json.loads((cassetto / chiavi.FILE).read_text("utf-8"))
    assert [porta["n"] for porta in documento["porte"]] == [*costi, costi[1]]


@pytest.mark.parametrize("passo", ["aggiungi_password", "tieni_solo"])
@pytest.mark.parametrize("salta", [1, 2])
def test_corrente_staccata_in_ogni_scrittura_lascia_aperta_la_password_giusta(
        cassetto, monkeypatch, passo, salta):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    if passo == "tieni_solo":
        chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    vera = chiavi.scrivi_tutto
    contatore = {"fatte": 0}

    def a_meta(percorso, dati):
        contatore["fatte"] += 1
        if contatore["fatte"] == salta:
            raise OSError("corrente staccata")
        vera(percorso, dati)

    monkeypatch.setattr(chiavi, "scrivi_tutto", a_meta)
    with pytest.raises(OSError):
        if passo == "tieni_solo":
            chiavi.tieni_solo(cassetto, chiave, NUOVA)
        else:
            chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi, "scrivi_tutto", vera)
    if passo == "tieni_solo":
        assert _apre(cassetto, NUOVA, chiave)
        assert salta == 2 or _apre(cassetto, PAROLA, chiave)
    else:
        assert _apre(cassetto, PAROLA, chiave)


@pytest.mark.parametrize("usata", [PAROLA, NUOVA])
@pytest.mark.parametrize("passo", ["aggiungi_password", "tieni_solo"])
def test_dopo_un_cambio_fermato_a_meta_le_copie_tornano_uguali(
        cassetto, monkeypatch, passo, usata):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    if passo == "tieni_solo":
        chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    vero = chiavi.os.replace

    def solo_il_primo(sorgente, arrivo):
        if os.fspath(arrivo) == os.fspath(cassetto / chiavi.RISERVA):
            raise OSError("corrente staccata")
        vero(sorgente, arrivo)

    monkeypatch.setattr(chiavi.os, "replace", solo_il_primo)
    with pytest.raises(OSError):
        if passo == "tieni_solo":
            chiavi.tieni_solo(cassetto, chiave, NUOVA)
        else:
            chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi.os, "replace", vero)
    primo, riserva = [(cassetto / nome).read_bytes()
                      for nome in (chiavi.FILE, chiavi.RISERVA)]
    assert primo != riserva
    atteso = riserva if (passo, usata) == ("tieni_solo", PAROLA) else primo
    assert chiavi.apri(cassetto, usata).nome == chiave.nome
    assert [(cassetto / nome).read_bytes()
            for nome in (chiavi.FILE, chiavi.RISERVA)] == [atteso, atteso]
    assert _apre(cassetto, NUOVA, chiave)
    assert _apre(cassetto, PAROLA, chiave) is ((passo, usata) != ("tieni_solo", NUOVA))


def test_dopo_ogni_scambio_la_cartella_si_fissa_sul_disco(cassetto, monkeypatch):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    fatti = []
    vero = chiavi.os.replace

    def scambia(sorgente, arrivo):
        vero(sorgente, arrivo)
        fatti.append(("scambio", os.path.basename(arrivo)))

    monkeypatch.setattr(chiavi.os, "replace", scambia)
    monkeypatch.setattr(chiavi, "fissa_cartella",
                        lambda cartella: fatti.append(("fissa", cartella)))
    chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi.os, "replace", vero)
    assert [fatto for fatto in fatti
            if fatto[0] == "fissa" or fatto[1] in (chiavi.FILE, chiavi.RISERVA)] == [
        ("scambio", chiavi.FILE), ("fissa", cassetto),
        ("scambio", chiavi.RISERVA), ("fissa", cassetto)]


def _guasta(dati: bytes, guasto: str) -> bytes:
    documento = json.loads(dati)
    if guasto == "chiusa":
        chiusa = bytearray.fromhex(documento["porte"][-1]["chiusa"])
        chiusa[0] ^= 1
        documento["porte"][-1]["chiusa"] = chiusa.hex()
    else:
        nome = documento["nome"]
        documento["nome"] = ("1" if nome[0] == "0" else "0") + nome[1:]
    return json.dumps(documento).encode()


def _da_provare(cartella) -> list[str]:
    return sorted(percorso.name for percorso in cartella.iterdir()
                  if percorso.name.endswith((chiavi.DA_PROVARE, ".nuovo")))


@pytest.mark.parametrize("guasto", ["chiusa", "nome"])
@pytest.mark.parametrize("passo", ["aggiungi_password", "tieni_solo"])
@pytest.mark.parametrize("rotto", [chiavi.FILE, chiavi.RISERVA])
def test_se_rileggendo_un_file_non_torna_ci_si_ferma_e_l_altro_resta_buono(
        cassetto, monkeypatch, passo, rotto, guasto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    if passo == "tieni_solo":
        chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    prima = (cassetto / rotto).read_bytes()
    vera = chiavi.scrivi_tutto
    scritti = []

    def scrive_male(percorso, dati):
        scritti.append(percorso.name)
        if percorso.name == rotto + chiavi.DA_PROVARE:
            dati = _guasta(dati, guasto)
        vera(percorso, dati)

    monkeypatch.setattr(chiavi, "scrivi_tutto", scrive_male)
    with pytest.raises(chiavi.ChiaveRovinata):
        if passo == "tieni_solo":
            chiavi.tieni_solo(cassetto, chiave, NUOVA)
        else:
            chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi, "scrivi_tutto", vera)
    assert scritti == [nome + chiavi.DA_PROVARE for nome in (chiavi.FILE, chiavi.RISERVA)
                       ][:1 + (rotto == chiavi.RISERVA)]
    assert (cassetto / rotto).read_bytes() == prima
    assert _da_provare(cassetto) == []
    if passo == "tieni_solo":
        assert _apre(cassetto, NUOVA, chiave)
    else:
        assert _apre(cassetto, PAROLA, chiave)
    assert chiavi.apri(cassetto, PAROLA if passo == "aggiungi_password" else NUOVA
                       ).nome == chiave.nome


@pytest.mark.parametrize("guasto", ["chiusa", "nome"])
@pytest.mark.parametrize("passo", ["aggiungi_password", "tieni_solo"])
@pytest.mark.parametrize("rotto", [chiavi.FILE, chiavi.RISERVA])
def test_se_dopo_lo_scambio_il_file_non_torna_ci_si_ferma(
        cassetto, monkeypatch, passo, rotto, guasto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    if passo == "tieni_solo":
        chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    altro = chiavi.RISERVA if rotto == chiavi.FILE else chiavi.FILE
    prima = (cassetto / altro).read_bytes()
    vero = chiavi.os.replace

    def scambia_male(sorgente, arrivo):
        vero(sorgente, arrivo)
        if os.fspath(arrivo) == os.fspath(cassetto / rotto):
            (cassetto / rotto).write_bytes(_guasta((cassetto / rotto).read_bytes(), guasto))

    monkeypatch.setattr(chiavi.os, "replace", scambia_male)
    with pytest.raises(chiavi.ChiaveRovinata):
        if passo == "tieni_solo":
            chiavi.tieni_solo(cassetto, chiave, NUOVA)
        else:
            chiavi.aggiungi_password(cassetto, chiave, NUOVA)
    monkeypatch.setattr(chiavi.os, "replace", vero)
    assert _da_provare(cassetto) == []
    if rotto == chiavi.FILE:
        assert (cassetto / altro).read_bytes() == prima
    tenuta = PAROLA if passo == "aggiungi_password" else NUOVA
    assert chiavi.apri(cassetto, tenuta).nome == chiave.nome
    assert _apre(cassetto, tenuta, chiave)


def test_cambiare_password_lascia_un_solo_file_per_tipo(cassetto):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    chiavi.cambia_password(cassetto, chiave, NUOVA)
    assert sorted(p.name for p in cassetto.iterdir()) == sorted(
        [chiavi.FILE, chiavi.RISERVA])


@pytest.mark.parametrize("avanzo", [b"", b"{mezzo", b"\x00\xff" * 300])
def test_gli_avanzi_di_un_cambio_interrotto_non_lo_fermano(cassetto, avanzo):
    chiave = chiavi.crea(cassetto, PAROLA, costo=LEGGERO)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (cassetto / (nome + chiavi.DA_PROVARE)).write_bytes(avanzo)
        (cassetto / (nome + chiavi.DA_PROVARE + ".nuovo")).write_bytes(avanzo)
    chiavi.cambia_password(cassetto, chiave, NUOVA)
    assert sorted(p.name for p in cassetto.iterdir()) == sorted(
        [chiavi.FILE, chiavi.RISERVA])
    assert _apre(cassetto, NUOVA, chiave) and not _apre(cassetto, PAROLA, chiave)


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
