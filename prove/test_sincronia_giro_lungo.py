from __future__ import annotations

import hashlib

import pytest

from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import ErroreOfficina
from officina.impostazioni import Posizione
from officina.modello import cambiamenti, etichette, nodi
from officina.sincronia import costruzione, formato, fusione

PAROLA = "questa-e-una-password"


def _foto(archivio, cartella, nome: str, contenuto: bytes) -> tuple[int, str]:
    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.parent.mkdir(parents=True, exist_ok=True)
    sorgente.write_bytes(contenuto)
    impronta = hashlib.blake2b(contenuto, digest_size=32).hexdigest()

    scatto_id = inserisci(
        connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?)", adesso())
    file_id = inserisci(
        connessione,
        "INSERT INTO file_media (impronta, dimensione, genere, formato, "
        "scatto_id, ruolo, aggiunto_il) "
        "VALUES (?, ?, 'immagine', 'jpeg', ?, 'principale', ?)",
        impronta, len(contenuto), scatto_id, adesso())
    inserisci(
        connessione,
        "INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
        "VALUES (?, ?, ?, ?)", file_id, str(sorgente), nome, adesso())
    return scatto_id, impronta


def _scatto_di(archivio, impronta: str) -> int:
    riga = uno(archivio.connessione,
               "SELECT scatto_id FROM file_media WHERE impronta = ?", impronta)
    assert riga is not None, "questa fotografia qui non c'è"
    return riga["scatto_id"]


def _ritratto(archivio) -> dict:
    connessione = archivio.connessione
    albero = {}
    for riga in tutti(connessione, "SELECT id, stato FROM nodi"):
        albero[nodi.percorso(connessione, riga["id"])] = riga["stato"]

    etichettate: dict[str, dict[str, str]] = {}
    righe = tutti(
        connessione,
        "SELECT f.impronta AS impronta, e.nodo_id AS nodo_id, e.stato AS stato "
        "FROM etichette e "
        "JOIN file_media f ON f.scatto_id = e.scatto_id AND f.ruolo = 'principale' "
        "WHERE e.origine = 'utente'")
    for riga in righe:
        dove = etichettate.setdefault(riga["impronta"], {})
        dove[nodi.percorso(connessione, riga["nodo_id"])] = riga["stato"]

    impronte = {r["impronta"] for r in
                tutti(connessione, "SELECT impronta FROM file_media")}
    return {"albero": albero, "etichette": etichettate, "impronte": impronte}


def _differenza(uno_ritratto: dict, altro: dict) -> str:
    righe = []
    for chiave in ("albero", "etichette", "impronte"):
        qui, la = uno_ritratto[chiave], altro[chiave]
        if qui == la:
            continue
        if isinstance(qui, set):
            righe.append(f"{chiave}: solo qui {sorted(qui - la)}, "
                         f"solo là {sorted(la - qui)}")
            continue
        for nome in sorted(set(qui) | set(la)):
            if qui.get(nome) != la.get(nome):
                righe.append(f"{chiave}[{nome}]: qui {qui.get(nome)!r}, "
                             f"là {la.get(nome)!r}")
    return "\n".join(righe) or "nessuna"


@pytest.fixture
def due_pc(archivio, tmp_path):
    altro = Archivio(Posizione(tmp_path / "zenbook", "finto")).apri()
    try:
        yield archivio, altro, tmp_path
    finally:
        altro.chiudi(con_copia=False)


def _manda(mittente, destinatario, tmp_path, quale: str):
    altre = cambiamenti.altre_macchine(mittente.connessione)
    codice_suo = cambiamenti.questa_macchina(destinatario.connessione)["codice"]
    per = next((r["id"] for r in altre if r["codice"] == codice_suo), None)
    fatto = costruzione.costruisci(mittente, tmp_path / quale, PAROLA,
                                   per_macchina_id=per)
    return fusione.fondi(destinatario, fatto.cartella, PAROLA), fatto


def _giro_completo(fisso, zen, tmp_path, giro: str) -> None:
    _manda(fisso, zen, tmp_path, f"{giro}-andata")
    _manda(zen, fisso, tmp_path, f"{giro}-ritorno")
    _manda(fisso, zen, tmp_path, f"{giro}-ancora")


def test_il_giro_lungo_nei_due_sensi_finisce_con_due_archivi_uguali(due_pc):
    fisso, zen, tmp_path = due_pc
    foto = tmp_path / "foto"

    impronte = []
    for numero in range(12):
        _, impronta = _foto(fisso, foto, f"f{numero}.jpg",
                            f"contenuto numero {numero} ".encode() * 40)
        impronte.append(impronta)

    vestiti = nodi.crea(fisso.connessione, "vestiti")
    magliette = nodi.crea(fisso.connessione, "magliette", vestiti)
    scarpe = nodi.crea(fisso.connessione, "scarpe", vestiti)
    posti = nodi.crea(fisso.connessione, "posti")
    mare = nodi.crea(fisso.connessione, "mare", posti)
    for numero, impronta in enumerate(impronte):
        dove = [magliette, scarpe, mare][numero % 3]
        etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), dove,
                        "si", "utente")

    esito, _ = _manda(fisso, zen, tmp_path, "prima")
    assert esito.file_nuovi == 12
    assert _ritratto(zen) == _ritratto(fisso), _differenza(_ritratto(zen),
                                                           _ritratto(fisso))

    _, mia = _foto(fisso, foto, "solo-mia.jpg", b"solo sul fisso " * 40)
    _, sua = _foto(zen, foto, "solo-sua.jpg", b"solo sullo zenbook " * 40)

    qui_vacanze = nodi.crea(fisso.connessione, "vacanze 2026", nodi_id(
        fisso, "posti"))
    la_vacanze = nodi.crea(zen.connessione, "vacanze 2026", nodi_id(zen, "posti"))
    etichette.metti(fisso.connessione, _scatto_di(fisso, mia), qui_vacanze,
                    "si", "utente")
    etichette.metti(zen.connessione, _scatto_di(zen, sua), la_vacanze,
                    "si", "utente")

    nodi.crea(fisso.connessione, "nonna", nodi_id(fisso, "posti"))
    nodi.crea(zen.connessione, "nonna", nodi_id(zen, "vestiti"))

    nodi.rinomina(zen.connessione, nodi_id(zen, "vestiti › magliette"),
                  "magliette estive")

    nodi.sposta(fisso.connessione, nodi_id(fisso, "vestiti › scarpe"),
                nodi_id(fisso, "posti"))

    conteso = impronte[0]
    etichette.metti(fisso.connessione, _scatto_di(fisso, conteso),
                    nodi_id(fisso, "posti › mare"), "no", "utente")
    etichette.metti(zen.connessione, _scatto_di(zen, conteso),
                    nodi_id(zen, "posti › mare"), "si", "utente")

    macchina = impronte[1]
    etichette.metti(zen.connessione, _scatto_di(zen, macchina),
                    nodi_id(zen, "posti"), "si", "sistema")

    _giro_completo(fisso, zen, tmp_path, "secondo")

    qui, la = _ritratto(fisso), _ritratto(zen)
    assert qui == la, _differenza(qui, la)

    assert "posti › vacanze 2026" in qui["albero"]
    assert "vestiti › magliette estive" in qui["albero"]
    assert "vestiti › magliette" not in qui["albero"]
    assert "posti › scarpe" in qui["albero"]
    assert qui["etichette"][mia]["posti › vacanze 2026"] == "si"
    assert qui["etichette"][sua]["posti › vacanze 2026"] == "si"
    assert "posti › nonna" in qui["albero"] and "vestiti › nonna" in qui["albero"]


def nodi_id(archivio, sentiero: str) -> int:
    numero = fusione.nodo_al_sentiero(archivio.connessione, sentiero)
    assert numero is not None, f"«{sentiero}» qui non c'è"
    return numero


def test_quando_hanno_finito_non_hanno_piu_niente_da_dirsi(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "una.jpg", b"il contenuto" * 50)
    nodo = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                    "si", "utente")

    _giro_completo(fisso, zen, tmp_path, "primo")

    ancora, _ = _manda(fisso, zen, tmp_path, "vuoto-andata")
    indietro, _ = _manda(zen, fisso, tmp_path, "vuoto-ritorno")
    assert ancora.gesti_applicati == 0
    assert indietro.gesti_applicati == 0
    assert cambiamenti.quanti_da_mandare(zen.connessione) == 0


def test_rifare_tutto_il_giro_daccapo_non_cambia_niente(due_pc):
    fisso, zen, tmp_path = due_pc
    foto = tmp_path / "foto"
    for numero in range(6):
        _, impronta = _foto(fisso, foto, f"f{numero}.jpg",
                            f"numero {numero} ".encode() * 40)
        nodo = nodi.crea(fisso.connessione, f"nodo {numero}")
        etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                        "si", "utente")

    _, primo = _manda(fisso, zen, tmp_path, "uno")
    prima = _ritratto(zen)
    di_nuovo = fusione.fondi(zen, primo.cartella, PAROLA)
    assert di_nuovo.gesti_applicati == 0
    assert _ritratto(zen) == prima, _differenza(_ritratto(zen), prima)


def _un_pacchetto(fisso, zen, tmp_path, quale="brutto"):
    _, impronta = _foto(fisso, tmp_path / "foto", "una.jpg", b"contenuto" * 60)
    nodo = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                    "si", "utente")
    return costruzione.costruisci(fisso, tmp_path / quale, PAROLA)


def test_un_pacchetto_copiato_a_meta_non_si_apre(due_pc):
    fisso, zen, tmp_path = due_pc
    fatto = _un_pacchetto(fisso, zen, tmp_path)
    dati = fatto.cartella / formato.DATI
    dati.write_bytes(dati.read_bytes()[: len(dati.read_bytes()) // 2])

    prima = _ritratto(zen)
    with pytest.raises(ErroreOfficina):
        fusione.fondi(zen, fatto.cartella, PAROLA)
    assert _ritratto(zen) == prima


def test_un_pacchetto_dichiarato_interrotto_non_si_apre(due_pc):
    fisso, zen, tmp_path = due_pc
    fatto = _un_pacchetto(fisso, zen, tmp_path)
    carta = formato.Carta.leggi(fatto.cartella)
    carta.stato = formato.INTERROTTO
    carta.scrivi(fatto.cartella)

    with pytest.raises(ErroreOfficina) as guasto:
        fusione.fondi(zen, fatto.cartella, PAROLA)
    assert guasto.value.codice == "pacchetto_interrotto"


def test_la_password_sbagliata_non_tocca_niente(due_pc):
    fisso, zen, tmp_path = due_pc
    fatto = _un_pacchetto(fisso, zen, tmp_path)
    prima = _ritratto(zen)
    with pytest.raises(ErroreOfficina):
        fusione.fondi(zen, fatto.cartella, "una-password-diversa")
    assert _ritratto(zen) == prima


def test_un_pacchetto_dell_archivio_sbagliato_non_si_mescola(due_pc, tmp_path):
    fisso, zen, _ = due_pc
    fatto = _un_pacchetto(fisso, zen, tmp_path)
    carta = formato.Carta.leggi(fatto.cartella)
    carta.archivio = "vero"
    carta.scrivi(fatto.cartella)

    with pytest.raises(ErroreOfficina) as guasto:
        fusione.fondi(zen, fatto.cartella, PAROLA)
    assert guasto.value.codice == "archivio_sbagliato"


def test_un_pacchetto_che_comincia_dopo_dove_ero_arrivato_si_ferma(due_pc):
    fisso, zen, tmp_path = due_pc
    _un_pacchetto(fisso, zen, tmp_path, "primo")
    _manda(fisso, zen, tmp_path, "primo-giro")
    _manda(zen, fisso, tmp_path, "primo-ritorno")

    _, impronta = _foto(fisso, tmp_path / "foto", "due.jpg", b"la seconda" * 60)
    nodo = nodi.crea(fisso.connessione, "montagna")
    etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                    "si", "utente")
    _, secondo = _manda(fisso, zen, tmp_path, "secondo-giro")
    assert secondo.carta.dal_seriale > 0

    with zen.scrittura() as connessione:
        connessione.execute("UPDATE macchine SET visto_fino_a = 0 "
                            "WHERE questa = 0")

    prima = _ritratto(zen)
    with pytest.raises(ErroreOfficina) as guasto:
        fusione.fondi(zen, secondo.cartella, PAROLA)
    assert guasto.value.codice == "buco_nei_cambiamenti"
    assert _ritratto(zen) == prima


def test_due_pacchetti_nell_ordine_sbagliato_non_perdono_niente(due_pc):
    fisso, zen, tmp_path = due_pc
    foto = tmp_path / "foto"
    _, prima_impronta = _foto(fisso, foto, "uno.jpg", b"la prima" * 60)
    mare = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, _scatto_di(fisso, prima_impronta), mare,
                    "si", "utente")
    vecchio = costruzione.costruisci(fisso, tmp_path / "vecchio", PAROLA)

    _, seconda_impronta = _foto(fisso, foto, "due.jpg", b"la seconda" * 60)
    monte = nodi.crea(fisso.connessione, "montagna")
    etichette.metti(fisso.connessione, _scatto_di(fisso, seconda_impronta),
                    monte, "si", "utente")
    nuovo = costruzione.costruisci(fisso, tmp_path / "nuovo", PAROLA)

    fusione.fondi(zen, nuovo.cartella, PAROLA)
    fusione.fondi(zen, vecchio.cartella, PAROLA)

    ritratto = _ritratto(zen)
    assert ritratto["etichette"][prima_impronta]["mare"] == "si"
    assert ritratto["etichette"][seconda_impronta]["montagna"] == "si"
    assert ritratto == _ritratto(fisso), _differenza(ritratto, _ritratto(fisso))


def test_un_originale_sparito_non_ferma_le_etichette(due_pc):
    fisso, zen, tmp_path = due_pc
    foto = tmp_path / "foto"
    _, c_e = _foto(fisso, foto, "c-e.jpg", b"questa c'e'" * 60)
    _, sparita = _foto(fisso, foto, "sparita.jpg", b"questa no" * 60)
    nodo = nodi.crea(fisso.connessione, "mare")
    for impronta in (c_e, sparita):
        etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                        "si", "utente")
    (foto / "sparita.jpg").unlink()

    esito, fatto = _manda(fisso, zen, tmp_path, "senza-originale")

    assert fatto.note, "il pacchetto doveva dire che un originale non c'era"
    ritratto = _ritratto(zen)
    assert ritratto["etichette"][sparita]["mare"] == "si"
    assert ritratto["etichette"][c_e]["mare"] == "si"


def test_due_decisioni_nello_stesso_secondo_finiscono_uguali(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "una.jpg", b"contesa" * 60)
    nodo = nodi.crea(fisso.connessione, "mare")
    etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), nodo,
                    "si", "utente")
    _manda(fisso, zen, tmp_path, "prima")

    etichette.togli(fisso.connessione, _scatto_di(fisso, impronta),
                    nodi_id(fisso, "mare"))
    etichette.metti(zen.connessione, _scatto_di(zen, impronta),
                    nodi_id(zen, "mare"), "si", "utente")
    istante = "2026-06-01T12:00:00Z"
    for archivio in (fisso, zen):
        with archivio.scrittura() as connessione:
            connessione.execute("UPDATE cambiamenti SET avvenuto_il = ? "
                                "WHERE cosa = 'etichetta'", (istante,))
            connessione.execute("UPDATE etichette SET creata_il = ?", (istante,))

    _giro_completo(fisso, zen, tmp_path, "pareggio")

    qui, la = _ritratto(fisso), _ritratto(zen)
    assert qui == la, _differenza(qui, la)
    assert qui["etichette"].get(impronta, {}).get("mare") in (None, "si")


def test_un_albero_piu_vecchio_del_registro_viaggia_lo_stesso(due_pc):
    fisso, zen, tmp_path = due_pc
    _, impronta = _foto(fisso, tmp_path / "foto", "una.jpg", b"il contenuto " * 40)
    vestiti = nodi.crea(fisso.connessione, "vestiti")
    magliette = nodi.crea(fisso.connessione, "magliette", vestiti)
    etichette.metti(fisso.connessione, _scatto_di(fisso, impronta), magliette,
                    "si", "utente")
    fisso.connessione.execute("DELETE FROM cambiamenti")

    esito, fatto = _manda(fisso, zen, tmp_path, "primo")

    assert fatto.carta.quanti_cambiamenti == 3
    assert esito.nodi_creati == 2
    assert esito.etichette_messe == 1
    assert _ritratto(zen)["albero"] == _ritratto(fisso)["albero"]
    assert _ritratto(zen)["etichette"] == _ritratto(fisso)["etichette"]


def test_la_storia_scritta_a_ritroso_tiene_le_date_vere(due_pc):
    fisso, _zen, _tmp = due_pc
    nodi.crea(fisso.connessione, "vestiti")
    nato = uno(fisso.connessione, "SELECT creato_il FROM nodi")["creato_il"]
    fisso.connessione.execute("DELETE FROM cambiamenti")

    assert cambiamenti.recupera_larretrato(fisso.connessione) == 1
    riga = uno(fisso.connessione, "SELECT * FROM cambiamenti")
    assert riga["avvenuto_il"] == nato
    assert cambiamenti.recupera_larretrato(fisso.connessione) == 0


def test_un_registro_gia_scritto_non_si_riscrive(due_pc):
    fisso, _zen, _tmp = due_pc
    nodi.crea(fisso.connessione, "vestiti")
    nodi.crea(fisso.connessione, "posti")
    quanti = uno(fisso.connessione,
                 "SELECT count(*) AS quanti FROM cambiamenti")["quanti"]
    assert cambiamenti.recupera_larretrato(fisso.connessione) == 0
    assert uno(fisso.connessione,
               "SELECT count(*) AS quanti FROM cambiamenti")["quanti"] == quanti


def test_le_impostazioni_viaggiano_col_pacchetto(due_pc):
    fisso, zen, tmp_path = due_pc
    fisso.imposta("quante_proposte", 9)

    esito, _ = _manda(fisso, zen, tmp_path, "primo")

    assert esito.impostazioni_arrivate >= 1
    assert zen.impostazione("quante_proposte") == 9


def test_un_impostazione_rovinata_dall_altro_computer_non_entra(due_pc):
    fisso, zen, tmp_path = due_pc
    for chiave, valore in (("fotogrammi_per_video", '"tanti"'),
                           ("miniatura_lato", "999999"),
                           ("volti_prudenza", '"spericolato"')):
        fisso.connessione.execute(
            "INSERT INTO impostazioni (chiave, valore, cambiata_il) "
            "VALUES (?, ?, '2026-06-01T00:00:00Z') ON CONFLICT(chiave) DO UPDATE "
            "SET valore = excluded.valore, cambiata_il = excluded.cambiata_il",
            (chiave, valore))
    fisso.imposta("quante_proposte", 9)
    prima = {chiave: uno(zen.connessione,
                         "SELECT valore FROM impostazioni WHERE chiave = ?", chiave)
             for chiave in ("fotogrammi_per_video", "miniatura_lato", "volti_prudenza")}

    esito, _ = _manda(fisso, zen, tmp_path, "primo")

    assert zen.impostazione("quante_proposte") == 9
    for chiave, riga in prima.items():
        dopo = uno(zen.connessione,
                   "SELECT valore FROM impostazioni WHERE chiave = ?", chiave)
        assert (dict(dopo) if dopo else None) == (dict(riga) if riga else None), chiave
        assert any(chiave in nota for nota in esito.note), chiave
    assert esito.impostazioni_arrivate == 1


def test_quelle_di_questa_macchina_restano_di_questa_macchina(due_pc):
    fisso, zen, tmp_path = due_pc
    fisso.imposta("intensita_scheda", 40)
    fisso.imposta("blocco_dopo_minuti", 15)
    prima = zen.impostazione("intensita_scheda")

    _manda(fisso, zen, tmp_path, "primo")

    assert zen.impostazione("intensita_scheda") == prima
    assert zen.impostazione("blocco_dopo_minuti") == 0


def test_fra_due_valori_decisi_vince_quello_deciso_dopo(due_pc):
    fisso, zen, tmp_path = due_pc
    zen.imposta("quante_proposte", 3)
    zen.connessione.execute(
        "UPDATE impostazioni SET cambiata_il = '2026-01-01T00:00:00Z' "
        "WHERE chiave = 'quante_proposte'")
    fisso.imposta("quante_proposte", 9)
    fisso.connessione.execute(
        "UPDATE impostazioni SET cambiata_il = '2026-06-01T00:00:00Z' "
        "WHERE chiave = 'quante_proposte'")

    _manda(fisso, zen, tmp_path, "primo")

    assert zen.impostazione("quante_proposte") == 9


def test_una_scelta_non_la_scavalca_un_valore_di_partenza(due_pc):
    fisso, zen, tmp_path = due_pc
    zen.imposta("quante_proposte", 3)
    zen.connessione.execute("UPDATE impostazioni SET cambiata_il = NULL")
    fisso.connessione.execute("UPDATE impostazioni SET cambiata_il = NULL")

    _manda(fisso, zen, tmp_path, "primo")

    assert zen.impostazione("quante_proposte") == 3


def test_decise_da_tutti_e_due_e_senza_date_lo_segnala_e_non_sceglie(due_pc):
    fisso, zen, tmp_path = due_pc
    fisso.imposta("quante_proposte", 9)
    zen.imposta("quante_proposte", 3)
    fisso.connessione.execute("UPDATE impostazioni SET cambiata_il = NULL")
    zen.connessione.execute("UPDATE impostazioni SET cambiata_il = NULL")

    esito, _ = _manda(fisso, zen, tmp_path, "primo")

    assert esito.impostazioni_contese == 1
    assert zen.impostazione("quante_proposte") == 3
    assert any("quante_proposte" in nota for nota in esito.note)


def test_le_impostazioni_uguali_non_si_riapplicano(due_pc):
    fisso, zen, tmp_path = due_pc
    fisso.imposta("quante_proposte", 9)
    _manda(fisso, zen, tmp_path, "primo")

    esito, _ = _manda(fisso, zen, tmp_path, "secondo")

    assert esito.impostazioni_arrivate == 0
