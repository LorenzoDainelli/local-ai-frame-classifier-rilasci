from __future__ import annotations

import sqlite3

import pytest

from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.telefono import (costruzione, formato, lettore,
                               ritorno, selezione)

PAROLA = "tre parole che ricordi"


@pytest.fixture
def telefono(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        return telefoni.crea(connessione, "iPhone", "ios")


def _travaso(archivio, telefono_id, dove, **resto) -> costruzione.Travaso:
    return costruzione.Travaso(archivio, telefono_id, dove, PAROLA, **resto)


def _fai(archivio, telefono_id, dove) -> costruzione.Esito:
    return _travaso(archivio, telefono_id, dove).esegui()


def test_si_costruisce_e_si_riapre(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    esito = _fai(archivio_pieno, telefono, dove)

    assert esito.completo
    assert esito.scritti > 0
    assert not esito.guasti

    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.completo
        assert pacchetto.quanti() > 0
        assert pacchetto.giorni()
        verifica = pacchetto.verifica()
        assert verifica.tutto_a_posto, [g.perche for g in verifica.guasti]
        assert verifica.letti >= pacchetto.quanti()


def test_un_originale_torna_fuori_identico(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    with lettore.apri(dove, PAROLA) as pacchetto:
        riga = pacchetto.scatti(1)[0]
        grezzo = pacchetto.originale(riga["id"])
        vero = uno(archivio_pieno.connessione,
                   "SELECT dimensione FROM file_media WHERE impronta = ?",
                   riga["impronta"])
        assert len(grezzo) == vero["dimensione"]

        fuori = tmp_path / "tirato-fuori.bin"
        assert pacchetto.tira_fuori(riga["id"], fuori) == riga["impronta"]
        assert fuori.read_bytes() == grezzo


def test_le_live_photo_portano_il_loro_movimento(archivio_pieno, telefono,
                                                 tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    with lettore.apri(dove, PAROLA) as pacchetto:
        live = [r for r in pacchetto.scatti(500) if r["genere"] == "live"]
        assert live, "l'archivio finto ha delle live photo"
        for riga in live:
            assert riga["posto_movimento"]
            assert pacchetto.movimento(riga["id"])


def test_il_pacchetto_non_contiene_niente_in_chiaro(archivio_pieno, telefono,
                                                    tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    percorso = uno(archivio_pieno.connessione,
                   "SELECT p.percorso FROM percorsi p LIMIT 1")["percorso"]
    from pathlib import Path
    originale = Path(percorso).read_bytes()
    for file in (dove / formato.FOTO).rglob("*"):
        if file.is_file():
            assert originale[:2048] not in file.read_bytes()

    carta = (dove / formato.CARTA).read_text(encoding="utf-8")
    assert "nodo_" not in carta


def test_la_password_sbagliata_non_apre_il_pacchetto(archivio_pieno, telefono,
                                                     tmp_path):
    from officina.errori import PasswordSbagliata

    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    with pytest.raises(PasswordSbagliata):
        lettore.apri(dove, "un'altra password lunga")


def test_un_file_rovinato_la_verifica_lo_trova(archivio_pieno, telefono,
                                               tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    vittima = next(f for f in (dove / formato.FOTO).rglob("*") if f.is_file())
    grezzo = bytearray(vittima.read_bytes())
    grezzo[-20] ^= 0x02
    vittima.write_bytes(bytes(grezzo))

    with lettore.apri(dove, PAROLA) as pacchetto:
        verifica = pacchetto.verifica()
    assert not verifica.tutto_a_posto
    assert any(g.posto.endswith(vittima.name) for g in verifica.guasti)


def test_un_file_che_sparisce_la_verifica_lo_dice(archivio_pieno, telefono,
                                                  tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    vittima = next(f for f in (dove / formato.MINI).rglob("*") if f.is_file())
    vittima.unlink()
    with lettore.apri(dove, PAROLA) as pacchetto:
        verifica = pacchetto.verifica()
    assert any("manca" in g.perche for g in verifica.guasti)


def test_il_secondo_travaso_non_ricopia_le_foto(archivio_pieno, telefono,
                                                tmp_path):
    dove = tmp_path / "Visore-iPhone"
    primo = _fai(archivio_pieno, telefono, dove)
    secondo = _fai(archivio_pieno, telefono, dove)

    assert primo.scritti > 10
    assert secondo.scritti == 1
    assert secondo.completo


def test_un_file_cancellato_a_mano_torna(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    vittima = next(f for f in (dove / formato.FOTO).rglob("*") if f.is_file())
    vittima.unlink()

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.scritti == 2
    assert vittima.is_file()


def test_stringere_la_selezione_toglie_le_foto_e_lo_dice(archivio_pieno,
                                                         telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    quanti_prima = sum(1 for f in dove.rglob("*") if f.is_file())

    meta = uno(archivio_pieno.connessione,
               "SELECT giorno FROM scatti WHERE giorno IS NOT NULL "
               "ORDER BY giorno LIMIT 1 OFFSET 5")["giorno"]
    with archivio_pieno.scrittura() as connessione:
        telefoni.salva_selezione(
            connessione, telefono,
            selezione.Selezione(dal_giorno=meta).a_json())

    travaso = _travaso(archivio_pieno, telefono, dove)
    piano = travaso.prepara()
    assert piano.da_togliere
    assert not piano.da_scrivere

    esito = travaso.esegui(piano)
    assert esito.tolti == len(piano.da_togliere)
    assert sum(1 for f in dove.rglob("*") if f.is_file()) < quanti_prima

    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto


def test_il_piano_si_guarda_senza_toccare_niente(archivio_pieno, telefono,
                                                 tmp_path):
    dove = tmp_path / "Visore-iPhone"
    piano = _travaso(archivio_pieno, telefono, dove).prepara()
    assert piano.da_scrivere
    assert piano.stima.quanti_scatti > 0
    assert not dove.exists()


def test_due_archivi_non_si_mescolano(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    carta = formato.Carta.leggi(dove)
    carta.archivio = "un altro archivio"
    carta.scrivi(dove)

    with pytest.raises(ErroreOfficina) as guaio:
        _fai(archivio_pieno, telefono, dove)
    assert guaio.value.codice == "archivio_diverso"


def test_il_pacchetto_di_un_altro_telefono_non_si_riempie(archivio_pieno,
                                                          telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    with archivio_pieno.scrittura() as connessione:
        altro = telefoni.crea(connessione, "Redmi", "android")
    with pytest.raises(ErroreOfficina) as guaio:
        _fai(archivio_pieno, altro, dove)
    assert guaio.value.codice == "telefono_diverso"


def test_un_pacchetto_piu_nuovo_non_si_apre(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    carta = formato.Carta.leggi(dove)
    carta.versione_formato = formato.VERSIONE_FORMATO + 1
    carta.scrivi(dove)
    with pytest.raises(ErroreOfficina) as guaio:
        lettore.apri(dove, PAROLA)
    assert guaio.value.codice == "formato_troppo_nuovo"


def test_si_ferma_a_meta_e_riprende(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    travaso = _travaso(archivio_pieno, telefono, dove)
    piano = travaso.prepara()

    fatti = []

    def a_meta(fase, numero, totale):
        if fase == "scrivo":
            fatti.append(numero)
            if numero >= 3:
                travaso.ferma()

    travaso.quando_cambia = a_meta
    esito = travaso.esegui(piano)

    assert esito.interrotto
    assert not esito.completo
    assert formato.Carta.leggi(dove).stato == formato.INTERROTTO
    assert esito.scritti < len(piano.da_scrivere)

    ancora = _travaso(archivio_pieno, telefono, dove)
    ripreso = ancora.prepara()
    assert ripreso.ripresa
    assert ripreso.gia_dentro == esito.scritti
    finito = ancora.esegui(ripreso)
    assert finito.completo
    assert formato.Carta.leggi(dove).stato == formato.COMPLETO

    with lettore.apri(dove, PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto


def test_un_pacchetto_incompleto_si_apre_lo_stesso(archivio_pieno, telefono,
                                                   tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    carta = formato.Carta.leggi(dove)
    carta.stato = formato.INTERROTTO
    carta.scrivi(dove)
    with lettore.apri(dove, PAROLA) as pacchetto:
        assert not pacchetto.completo
        assert pacchetto.quanti() > 0


def test_un_originale_sparito_non_ferma_il_travaso(archivio_pieno, telefono,
                                                   tmp_path):
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "UPDATE percorsi SET percorso = '/non/c/e/piu-' || id || '.heic', "
            "presente = 0 WHERE file_id = (SELECT id FROM file_media LIMIT 1)")
    esito = _fai(archivio_pieno, telefono, tmp_path / "Visore-iPhone")
    assert esito.completo
    assert esito.saltati
    assert "non si trova" in esito.saltati[0].perche


def _scrivi_ritorno(dove, chiave, tmp_path, **cosa):
    grezzo = tmp_path / "ritorno-finto.sqlite"
    ritorno.scrivi_ritorno_finto(grezzo, **cosa)
    chiave.cifra_file(grezzo, formato.dentro(dove, formato.RITORNO), formato.RITORNO)
    grezzo.unlink()


def test_cuori_raccolte_e_diario_tornano_al_pc(archivio_pieno, telefono,
                                               tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)

    impronte = [r["impronta"] for r in tutti(
        archivio_pieno.connessione,
        "SELECT impronta FROM file_media WHERE scatto_id IS NOT NULL LIMIT 3")]
    _scrivi_ritorno(
        dove, chiave, tmp_path,
        cuori=[(impronte[0], "2026-08-01T10:00:00"),
               (impronte[1], "2026-08-02T11:00:00")],
        raccolte=[(1, "Vacanze", "2026-08-01T10:00:00")],
        raccolte_scatti={1: impronte[:2]},
        diario=[("2026-08-10T09:00:00", 620, 43.8, 11.29, 47)])

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.tornato.c_era
    assert esito.tornato.cuori_nuovi == 2
    assert esito.tornato.raccolte == 1
    assert esito.tornato.giornate_di_diario == 1

    connessione = archivio_pieno.connessione
    cuore = uno(connessione, "SELECT * FROM cuori WHERE impronta = ?",
                impronte[0])
    assert cuore["telefono_id"] == telefono
    assert cuore["scatto_id"] is not None
    assert uno(connessione, "SELECT count(*) AS quanti FROM diario_visore"
               )["quanti"] == 1

    ancora = _fai(archivio_pieno, telefono, dove)
    assert ancora.tornato.cuori_nuovi == 0
    assert uno(connessione, "SELECT count(*) AS quanti FROM cuori")["quanti"] == 2
    assert uno(connessione, "SELECT count(*) AS quanti FROM diario_visore"
               )["quanti"] == 1


def test_il_ritorno_si_legge_prima_di_riscrivere(archivio_pieno, telefono,
                                                 tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronta = uno(archivio_pieno.connessione,
                   "SELECT impronta FROM file_media LIMIT 1")["impronta"]
    _scrivi_ritorno(dove, chiave, tmp_path,
                    cuori=[(impronta, "2026-08-01T10:00:00")])

    _fai(archivio_pieno, telefono, dove)
    assert formato.dentro(dove, formato.RITORNO).is_file()
    assert uno(archivio_pieno.connessione,
               "SELECT count(*) AS quanti FROM cuori")["quanti"] == 1


def test_il_cuore_tolto_sul_pc_arriva_al_telefono(archivio_pieno, telefono,
                                                  tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronta = uno(archivio_pieno.connessione,
                   "SELECT impronta FROM file_media LIMIT 1")["impronta"]

    _scrivi_ritorno(dove, chiave, tmp_path,
                    cuori=[(impronta, "2026-08-01T10:00:00")])
    _fai(archivio_pieno, telefono, dove)

    with archivio_pieno.scrittura() as connessione:
        ritorno.togli_cuore(connessione, telefono, impronta)

    _fai(archivio_pieno, telefono, dove)
    with lettore.apri(dove, PAROLA) as pacchetto:
        tolti = pacchetto.dentro.execute(
            "SELECT impronta FROM cuori_tolti").fetchall()
        cuori = pacchetto.dentro.execute("SELECT impronta FROM cuori").fetchall()
    assert [r["impronta"] for r in tolti] == [impronta]
    assert not cuori

    _scrivi_ritorno(dove, chiave, tmp_path, cuori=[])
    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.tornato.cuori_tolti_applicati == 1
    assert uno(archivio_pieno.connessione,
               "SELECT count(*) AS quanti FROM cuori")["quanti"] == 0


def test_la_copia_di_scorta_dei_cuori_viaggia_nel_pacchetto(archivio_pieno,
                                                            telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronte = [r["impronta"] for r in tutti(
        archivio_pieno.connessione, "SELECT impronta FROM file_media LIMIT 2")]
    _scrivi_ritorno(dove, chiave, tmp_path,
                    cuori=[(impronte[0], "2026-08-01T10:00:00")],
                    raccolte=[(1, "Vacanze", "2026-08-01T10:00:00")],
                    raccolte_scatti={1: impronte})
    _fai(archivio_pieno, telefono, dove)

    with lettore.apri(dove, PAROLA) as pacchetto:
        cuori = pacchetto.dentro.execute("SELECT impronta FROM cuori").fetchall()
        raccolte = pacchetto.dentro.execute(
            "SELECT nome FROM raccolte").fetchall()
        dentro = pacchetto.dentro.execute(
            "SELECT count(*) AS quanti FROM raccolte_scatti").fetchone()
    assert [r["impronta"] for r in cuori] == [impronte[0]]
    assert [r["nome"] for r in raccolte] == ["Vacanze"]
    assert dentro["quanti"] == 2


def test_un_ritorno_rovinato_non_ferma_il_travaso(archivio_pieno, telefono,
                                                  tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    formato.dentro(dove, formato.RITORNO).write_bytes(b"spazzatura" * 100)

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo
    assert esito.tornato.guai


def test_un_ritorno_che_si_rompe_a_meta_non_lascia_niente_a_meta(
        archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronte = [r["impronta"] for r in tutti(
        archivio_pieno.connessione, "SELECT impronta FROM file_media LIMIT 2")]
    grezzo = tmp_path / "ritorno-storto.sqlite"
    dentro = sqlite3.connect(grezzo)
    dentro.executescript(
        "CREATE TABLE cuori (impronta TEXT, messo_il TEXT);"
        "CREATE TABLE raccolte (id INTEGER, nome TEXT, creata_il TEXT);")
    dentro.executemany("INSERT INTO cuori VALUES (?, ?)",
                       [(x, "2026-08-01T10:00:00") for x in impronte])
    dentro.execute("INSERT INTO raccolte VALUES (1, NULL, NULL)")
    dentro.commit()
    dentro.close()
    chiave.cifra_file(grezzo, formato.dentro(dove, formato.RITORNO), formato.RITORNO)

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo
    assert esito.tornato.guai
    assert esito.tornato.cuori_nuovi == 0
    connessione = archivio_pieno.connessione
    assert uno(connessione, "SELECT count(*) AS q FROM cuori")["q"] == 0
    assert uno(connessione, "SELECT count(*) AS q FROM raccolte")["q"] == 0


def test_il_travaso_non_scrive_mai_dalla_via_di_sola_lettura(
        archivio_pieno, telefono, tmp_path, monkeypatch):
    lettori = []
    vero = Archivio._lettore_a_parte

    def niente_nell_archivio(azione, _1, _2, database, _3):
        if azione in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                      sqlite3.SQLITE_DELETE) and database == "main":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def di_sola_lettura(self):
        lettore = vero(self)
        if lettore is not None:
            lettore[0].set_authorizer(niente_nell_archivio)
            lettori.append(lettore)
        return lettore

    monkeypatch.setattr(Archivio, "_lettore_a_parte", di_sola_lettura)
    dove = tmp_path / "Visore-iPhone"
    assert _fai(archivio_pieno, telefono, dove).completo
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronta = uno(archivio_pieno.connessione,
                   "SELECT impronta FROM file_media LIMIT 1")["impronta"]
    _scrivi_ritorno(dove, chiave, tmp_path,
                    cuori=[(impronta, "2026-08-01T10:00:00")],
                    raccolte=[(1, "Vacanze", "2026-08-01T10:00:00")],
                    raccolte_scatti={1: [impronta]})
    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo
    assert esito.tornato.cuori_nuovi == 1
    assert lettori
    connessione = archivio_pieno.connessione
    assert uno(connessione, "SELECT count(*) AS q FROM pacchetto_file "
               "WHERE telefono_id = ?", telefono)["q"] == esito.verificati
    assert uno(connessione, "SELECT stato FROM travasi ORDER BY id DESC LIMIT 1"
               )["stato"] == "finito"


def test_il_ritorno_si_decifra_con_l_archivio_libero(archivio_pieno, telefono,
                                                     tmp_path, monkeypatch):
    from officina.telefono import cifratura

    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    impronta = uno(archivio_pieno.connessione,
                   "SELECT impronta FROM file_media LIMIT 1")["impronta"]
    _scrivi_ritorno(dove, chiave, tmp_path, cuori=[(impronta, "2026-08-01T10:00:00")])
    letture = []
    vera = cifratura.Chiave.leggi_tutto

    def leggi_tutto(self, sorgente, posto):
        if posto == formato.RITORNO:
            letture.append(archivio_pieno._lucchetto._is_owned())
        return vera(self, sorgente, posto)

    with monkeypatch.context() as cambio:
        cambio.setattr(cifratura.Chiave, "leggi_tutto", leggi_tutto)
        esito = _fai(archivio_pieno, telefono, dove)
    assert esito.tornato.cuori_nuovi == 1
    assert letture == [False]


def test_l_identificativo_non_cambia_se_due_lo_creano_insieme(archivio_pieno,
                                                              monkeypatch):
    with archivio_pieno.scrittura() as connessione:
        primo = telefoni.identificativo(connessione)
    vero = telefoni.leggi_stato
    chiamate = []

    def non_ancora(connessione, chiave, predefinito=None):
        chiamate.append(chiave)
        if len(chiamate) == 1:
            return None
        return vero(connessione, chiave, predefinito)

    monkeypatch.setattr(telefoni, "leggi_stato", non_ancora)
    with archivio_pieno.scrittura() as connessione:
        assert telefoni.identificativo(connessione) == primo


def test_senza_ritorno_non_e_un_errore(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.completo
    assert not esito.tornato.c_era
    assert esito.tornato.a_parole().startswith("il telefono non ha")


def test_un_cuore_su_una_foto_fuori_archivio_resta_segnato(archivio_pieno,
                                                            telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    _scrivi_ritorno(dove, chiave, tmp_path,
                    cuori=[("f" * 64, "2026-08-01T10:00:00")])

    esito = _fai(archivio_pieno, telefono, dove)
    assert esito.tornato.cuori_nuovi == 1
    assert esito.tornato.non_trovati == 1
    riga = uno(archivio_pieno.connessione,
               "SELECT * FROM cuori WHERE impronta = ?", "f" * 64)
    assert riga is not None and riga["scatto_id"] is None


def test_il_pacchetto_dice_quante_foto_ha_portato_il_travaso(archivio_pieno,
                                                             telefono,
                                                             tmp_path):
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    with lettore.apri(dove, PAROLA) as pacchetto:
        detto = pacchetto.informazioni()
        assert int(detto["nuove_ultimo_travaso"]) == pacchetto.quanti()

    _fai(archivio_pieno, telefono, dove)
    with lettore.apri(dove, PAROLA) as pacchetto:
        assert int(pacchetto.informazioni()["nuove_ultimo_travaso"]) == 0


def _con_nota_e_etichetta(archivio, testo: str) -> int:
    with archivio.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT id FROM scatti ORDER BY id")["id"]
        connessione.execute("UPDATE scatti SET nota = ? WHERE id = ?",
                            (testo, scatto_id))
        connessione.execute(
            "INSERT INTO nodi (nome, creato_il) VALUES ('nodo_di_prova', "
            "'2026-01-01T00:00:00Z')")
        nodo_id = uno(connessione,
                      "SELECT id FROM nodi WHERE nome = 'nodo_di_prova'")["id"]
        connessione.execute(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, "
            "creata_il) VALUES (?,?,'si','sistema','2026-01-01T00:00:00Z')",
            (scatto_id, nodo_id))
    return scatto_id


def test_i_dettagli_di_uno_scatto_portano_addosso_la_loro_origine(
        archivio_pieno, telefono, tmp_path):
    _con_nota_e_etichetta(archivio_pieno, "la nota che avevo scritto sul PC")
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    with lettore.apri(dove, PAROLA) as pacchetto:
        quale = next(r["id"] for r in pacchetto.scatti(quanti=500)
                     if r["nota"])
        dettagli = pacchetto.dettagli(quale)
        assert dettagli["scatto"]["nota"] == "la nota che avevo scritto sul PC"
        nomi = {(r["nome"], r["origine"]) for r in dettagli["nodi"]}
        assert ("nodo_di_prova", "sistema") in nomi
        assert isinstance(dettagli["persone"], list)


def test_la_ricerca_trova_un_anno_e_una_nota(archivio_pieno, telefono,
                                             tmp_path):
    _con_nota_e_etichetta(archivio_pieno, "scritta a mano sul PC")
    dove = tmp_path / "Visore-iPhone"
    _fai(archivio_pieno, telefono, dove)

    with lettore.apri(dove, PAROLA) as pacchetto:
        anno = next(r["giorno"][:4] for r in pacchetto.scatti(quanti=500)
                    if r["giorno"])
        trovato = pacchetto.cerca(anno)
        assert trovato["date"], "un anno che c'è deve rispondere"
        assert trovato["date"][0]["quanti"] > 0

        assert not pacchetto.cerca("3")["date"]
        assert not pacchetto.cerca("1970")["date"]

        note = pacchetto.cerca("scritta a mano")["note"]
        assert [r for r in note if r["nota"] == "scritta a mano sul PC"]
        assert not pacchetto.cerca("una frase che non c'è")["note"]
