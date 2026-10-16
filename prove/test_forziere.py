from __future__ import annotations

import pytest

from officina import forziere
from officina.errori import ErroreOfficina
from officina.impostazioni import Posizione

PAROLA = "tre parole che ricordo"


@pytest.fixture
def cassetto(tmp_path):
    radice = tmp_path / "finto"
    (radice / "miniature").mkdir(parents=True)
    (radice / "archivio.sqlite").write_bytes(b"SQLite format 3\x00" + b"x" * 5000)
    (radice / "miniature" / "una.avif").write_bytes(b"\x00\x01\x02" * 900)
    (radice / "registro").mkdir()
    (radice / "registro" / "oggi.jsonl").write_text("{}\n", encoding="utf-8")
    return forziere.Forziere(Posizione(radice, "finto"))


def contenuto(radice) -> dict:
    return {
        str(p.relative_to(radice)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(radice.rglob("*"))
        if p.name != forziere.MARCATORE_APERTO
    }


def test_accendere_apre_e_richiude_senza_perdere_niente(cassetto):
    prima = contenuto(cassetto.cartella)

    cassetto.accendi(PAROLA)
    assert cassetto.acceso
    assert not cassetto.aperto
    assert contenuto(cassetto.cartella) == {}, "il chiaro non resta sul disco"

    cassetto.apri(PAROLA)
    assert cassetto.aperto
    assert contenuto(cassetto.cartella) == prima

    cassetto.chiudi(PAROLA)
    assert not cassetto.aperto
    assert contenuto(cassetto.cartella) == {}


def test_il_forziere_non_dice_cosa_contiene(cassetto):
    cassetto.accendi(PAROLA)
    dentro = cassetto.file.read_bytes()
    for parola in (b"archivio.sqlite", b"miniature", b"oggi.jsonl",
                   b"SQLite format 3"):
        assert parola not in dentro


def test_la_password_sbagliata_non_apre_e_lo_dice_bene(cassetto):
    cassetto.accendi(PAROLA)
    with pytest.raises(forziere.PasswordSbagliata) as scoppio:
        cassetto.apri("un'altra password lunga")
    messaggio = scoppio.value.messaggio
    assert "password dimenticata" in messaggio
    assert "foto originali" in messaggio


def test_una_password_corta_viene_rifiutata_prima_di_toccare_qualcosa(cassetto):
    prima = contenuto(cassetto.cartella)
    with pytest.raises(ErroreOfficina):
        cassetto.accendi("corta")
    assert not cassetto.acceso
    assert contenuto(cassetto.cartella) == prima


def test_spegnere_riporta_tutto_in_chiaro(cassetto):
    prima = contenuto(cassetto.cartella)
    cassetto.accendi(PAROLA)
    cassetto.spegni(PAROLA)
    assert not cassetto.acceso
    assert contenuto(cassetto.cartella) == prima


def test_non_si_spegne_con_la_password_sbagliata(cassetto):
    cassetto.accendi(PAROLA)
    with pytest.raises(forziere.PasswordSbagliata):
        cassetto.spegni("questa non è quella giusta")
    assert cassetto.acceso


def test_un_forziere_tagliato_a_meta_non_diventa_un_archivio_piu_corto(cassetto):
    cassetto.accendi(PAROLA)
    intero = cassetto.file.read_bytes()
    cassetto.file.write_bytes(intero[: len(intero) // 2])

    with pytest.raises(ErroreOfficina) as scoppio:
        cassetto.apri(PAROLA)
    assert "meta" in scoppio.value.messaggio or "blocco" in scoppio.value.messaggio


def test_un_blocco_toccato_si_accorge(cassetto):
    cassetto.accendi(PAROLA)
    dati = bytearray(cassetto.file.read_bytes())
    dati[-20] ^= 0xFF
    cassetto.file.write_bytes(bytes(dati))
    with pytest.raises(ErroreOfficina):
        cassetto.apri(PAROLA)


def test_un_file_rovinato_non_viene_scambiato_per_una_password_sbagliata(cassetto):
    cassetto.accendi(PAROLA)
    dati = bytearray(cassetto.file.read_bytes())
    dati[-20] ^= 0xFF
    cassetto.file.write_bytes(bytes(dati))

    with pytest.raises(ErroreOfficina) as scoppio:
        cassetto.apri(PAROLA)
    assert not isinstance(scoppio.value, forziere.PasswordSbagliata)
    assert "la password è giusta" in scoppio.value.messaggio


def test_un_file_che_non_e_un_forziere_lo_dice(cassetto, tmp_path):
    cassetto.file.write_bytes(b"questo non e' un forziere")
    with pytest.raises(ErroreOfficina) as scoppio:
        cassetto.apri(PAROLA)
    assert "non è un forziere" in scoppio.value.messaggio


def test_se_il_programma_si_chiude_male_il_chiaro_resta_e_vince(cassetto):
    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    (cassetto.cartella / "archivio.sqlite").write_bytes(b"roba nuova")

    assert cassetto.aperto
    cassetto.apri(PAROLA)
    assert (cassetto.cartella / "archivio.sqlite").read_bytes() == b"roba nuova"


def test_se_si_spegne_mentre_si_richiude_il_lavoro_dell_ultima_volta_resta(
        cassetto, monkeypatch):
    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    (cassetto.cartella / "archivio.sqlite").write_bytes(b"il lavoro di oggi")
    vecchio = cassetto.file.read_bytes()

    def si_spegne(flusso, *_):
        flusso.write(b"x" * 100)
        raise OSError("il computer si è spento")

    with monkeypatch.context() as cambio:
        cambio.setattr(forziere, "_impacchetta", lambda cartella, flusso: si_spegne(flusso))
        with pytest.raises(OSError):
            cassetto.chiudi(PAROLA)
    assert cassetto.file.read_bytes() == vecchio
    assert not cassetto.file.with_suffix(cassetto.file.suffix + ".nuovo").exists()

    cassetto.apri(PAROLA)
    assert (cassetto.cartella / "archivio.sqlite").read_bytes() == b"il lavoro di oggi"
    cassetto.chiudi(PAROLA)
    cassetto.apri(PAROLA)
    assert (cassetto.cartella / "archivio.sqlite").read_bytes() == b"il lavoro di oggi"


def test_un_forziere_nuovo_che_non_si_rilegge_non_prende_il_posto_del_vecchio(
        cassetto, monkeypatch):
    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    vecchio = cassetto.file.read_bytes()

    def rotto(file, password):
        raise ErroreOfficina("Il forziere appena scritto finisce a metà.")

    with monkeypatch.context() as cambio:
        cambio.setattr(forziere, "_rileggi_per_controllo", rotto)
        with pytest.raises(ErroreOfficina):
            cassetto.chiudi(PAROLA)
    assert cassetto.file.read_bytes() == vecchio
    assert cassetto.aperto
    assert (cassetto.cartella / "archivio.sqlite").exists()


def test_chiudere_non_lascia_copie_in_chiaro_accanto(cassetto):
    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    cassetto.chiudi(PAROLA)
    accanto = sorted(p.name for p in cassetto.cartella.parent.iterdir())
    assert accanto == sorted([cassetto.cartella.name, cassetto.file.name])


def test_il_blocco_finale_pieno_si_riconosce(cassetto, monkeypatch):
    monkeypatch.setattr(forziere, "BLOCCO", 10240)
    prima = contenuto(cassetto.cartella)
    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    assert contenuto(cassetto.cartella) == prima


def test_accendere_due_volte_non_si_puo(cassetto):
    cassetto.accendi(PAROLA)
    with pytest.raises(ErroreOfficina) as scoppio:
        cassetto.accendi(PAROLA)
    assert "già un forziere" in scoppio.value.messaggio


def test_regge_un_archivio_piu_grande_di_un_blocco(cassetto, monkeypatch):
    monkeypatch.setattr(forziere, "BLOCCO", 64 * 1024)
    grosso = cassetto.cartella / "miniature" / "grossa.avif"
    grosso.write_bytes(bytes(range(256)) * 1400)
    prima = contenuto(cassetto.cartella)

    cassetto.accendi(PAROLA)
    cassetto.apri(PAROLA)
    assert contenuto(cassetto.cartella) == prima


def test_lo_stato_si_dice_a_parole(cassetto):
    assert "spento" in cassetto.stato().a_parole()
    cassetto.accendi(PAROLA)
    assert cassetto.stato().a_parole() == "chiuso"
    cassetto.apri(PAROLA)
    assert cassetto.stato().a_parole() == "aperto"
    assert cassetto.stato().peso > 0


def test_l_archivio_si_apre_e_si_chiude_dentro_il_forziere(tmp_path, monkeypatch):
    from officina.archivio import accesso
    from officina.modello import nodi

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)

    archivio = accesso.apri("finto")
    nodi.crea(archivio.connessione, "nodo_prima_del_forziere", None)
    archivio.connessione.commit()
    dove = archivio.dove
    accesso.chiudi(con_copia=False)

    cassa = forziere.Forziere(dove)
    cassa.accendi(PAROLA)
    assert not (dove.radice / "archivio.sqlite").exists()

    with pytest.raises(forziere.ForziereChiuso):
        accesso.apri("finto")
    accesso.chiudi(con_copia=False)

    archivio = accesso.apri("finto", password=PAROLA)
    nomi = [r["nome"] for r in nodi.elenco(archivio.connessione)]
    assert "nodo_prima_del_forziere" in nomi
    accesso.chiudi(con_copia=False)

    assert cassa.acceso
    assert not (dove.radice / "archivio.sqlite").exists()


def test_senza_forziere_niente_cambia(tmp_path, monkeypatch):
    from officina.archivio import accesso

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    archivio = accesso.apri("finto")
    assert archivio.e_aperto
    accesso.chiudi(con_copia=False)
    assert (tmp_path / "archivio" / "finto" / "archivio.sqlite").exists()
