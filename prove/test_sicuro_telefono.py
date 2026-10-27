from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

from officina import registro
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import file_media, telefoni
from officina.sicuro.dall_archivio import (CHIUSO, CHIUSO_ADESSO, SENZA_ARCHIVIO, SI_APRE,
                                           TROVATA, DallArchivio)
from officina.sincronia import costruzione as sincronia
from officina.telefono import cifratura, costruzione, formato, lettore, selezione
from officina.web import telefono as pagina
from prove import test_sicuro_dall_archivio as dall_archivio_di_prova
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_dall_archivio import _impronta, _rovina, _stacca
from prove.test_sicuro_lavori import _chiudi, _diversa, _riapri

costo_leggero = servizio_di_prova.costo_leggero
foto_nell_archivio = dall_archivio_di_prova.foto_nell_archivio
PAROLA = "tre parole per il telefono"
DA_CERCARE = ("1 file non è sul disco e l'Archivio sicuro è chiuso: aprilo, se no il "
              "pacchetto non parte.")
DIVERSE = ("1 file resta fuori: nell'Archivio sicuro c'è solo una versione cambiata dopo "
           "l'importazione.")


@pytest.fixture
def sul_telefono(foto_nell_archivio, tmp_path):
    pronta = foto_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        nodo = inserisci(connessione,
                         "INSERT INTO nodi (nome, creato_il) VALUES ('per il telefono', ?)",
                         adesso())
        pronta.telefono_id = telefoni.crea(connessione, "iPhone", "ios")
        telefoni.salva_selezione(connessione, pronta.telefono_id,
                                 selezione.Selezione(nodi=[nodo]).a_json())
    pronta.nodo = nodo
    pronta.dove = tmp_path / "Visore-iPhone"
    _sul_telefono(pronta, pronta.scatto_id)
    return pronta


def _sul_telefono(pronta, scatto_id: int) -> None:
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
            "VALUES (?, ?, 'si', 'utente', ?)", (scatto_id, pronta.nodo, adesso()))


def _uno_sul_disco(pronta) -> int:
    with pronta.archivio.lettura() as connessione:
        for riga in tutti(connessione,
                          "SELECT s.id FROM scatti s WHERE s.id <> ? AND NOT EXISTS ("
                          "SELECT 1 FROM file_media f WHERE f.scatto_id = s.id AND NOT "
                          "EXISTS (SELECT 1 FROM percorsi p WHERE p.file_id = f.id "
                          "AND p.presente = 1)) ORDER BY s.id", pronta.scatto_id):
            return riga["id"]
    raise AssertionError("nessuno scatto sul disco")


def _travaso(pronta, **resto) -> costruzione.Travaso:
    return costruzione.Travaso(pronta.archivio, pronta.telefono_id, pronta.dove, PAROLA,
                               **resto)


def _scelta(pronta) -> selezione.Selezione:
    with pronta.archivio.lettura() as connessione:
        return pagina.scelta_di(telefoni.per_id(connessione, pronta.telefono_id))


def _stima(pronta) -> selezione.Stima:
    scelta = _scelta(pronta)
    with pronta.archivio.lettura() as connessione:
        return selezione.stima(connessione, scelta, ())


def _conti(stima: selezione.Stima) -> tuple:
    return (stima.quanti_file, stima.file_mancanti, stima.da_cercare,
            stima.versioni_diverse)


def _avvisi_della_pagina(pronta, stima: selezione.Stima) -> list[dict]:
    with pronta.archivio.lettura() as connessione:
        riga = telefoni.per_id(connessione, pronta.telefono_id)
        return pagina.avvisi(connessione, riga, stima, 0, None, None)


def _nel_pacchetto(pronta) -> list[str]:
    with pronta.archivio.lettura() as connessione:
        return [riga["genere"] for riga in tutti(
            connessione, "SELECT genere FROM pacchetto_file WHERE telefono_id = ? "
            "ORDER BY genere", pronta.telefono_id)]


def _errore(fare) -> tuple[str, str]:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value.codice, preso.value.messaggio


def _nessuna_copia_in_chiaro(pronta, *cartelle) -> None:
    for cartella in cartelle:
        for file in cartella.rglob("*"):
            assert not file.is_file() or pronta.dati not in file.read_bytes(), file


def test_una_foto_solo_nell_archivio_va_sul_telefono_identica(sul_telefono):
    pronta = sul_telefono
    esito = _travaso(pronta).esegui()

    assert esito.completo and not esito.saltati
    assert _nel_pacchetto(pronta) == ["dati", "miniatura", "originale"]
    with lettore.apri(pronta.dove, PAROLA) as pacchetto:
        assert pacchetto.originale(pronta.scatto_id) == pronta.dati
        with Image.open(io.BytesIO(pacchetto.miniatura(pronta.scatto_id))) as miniatura:
            assert miniatura.size == (96, 64)
        assert pacchetto.verifica().tutto_a_posto
    assert not pronta.originale.exists()
    _nessuna_copia_in_chiaro(pronta, pronta.dove, pronta.archivio.dove.radice / "lavoro")


@pytest.mark.parametrize("come", ["chiuso", "si_apre"])
def test_con_l_archivio_chiuso_il_pacchetto_non_parte_e_chiede_di_aprirlo(sul_telefono,
                                                                         come):
    pronta = sul_telefono
    _sul_telefono(pronta, _uno_sul_disco(pronta))
    if come == "chiuso":
        _chiudi(pronta)
    else:
        pronta.situazione.forzata = SI_APRE

    aprilo = ("sicuro_chiuso", costruzione.da_aprire(1))
    assert _errore(_travaso(pronta).prepara) == aprilo
    assert _errore(_travaso(pronta).esegui) == aprilo
    assert not pronta.dove.exists()
    with pronta.archivio.lettura() as connessione:
        assert telefoni.travaso_lasciato_a_meta(connessione, pronta.telefono_id) is None


def test_il_messaggio_conta_le_foto_da_cercare():
    assert costruzione.da_aprire(1) == ("Apri l'Archivio sicuro: 1 foto non è sul disco, "
                                        "e solo lì posso cercarla.")
    assert costruzione.da_aprire(1234) == ("Apri l'Archivio sicuro: 1.234 foto non sono "
                                           "sul disco, e solo lì posso cercarle.")


def test_dalla_pagina_il_travaso_non_parte_e_dice_di_aprire_l_archivio(sul_telefono):
    pronta = sul_telefono
    _chiudi(pronta)
    in_corso = pagina.InCorso()

    assert in_corso.parti(pronta.archivio, pronta.telefono_id, pronta.dove, PAROLA)
    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == costruzione.da_aprire(1)
    assert not pronta.dove.exists()


def test_una_versione_diversa_resta_fuori_col_motivo(sul_telefono):
    pronta = sul_telefono
    _diversa(pronta)

    piano = _travaso(pronta).prepara()
    assert [(s.posto, s.perche) for s in piano.saltati] == [
        (f"scatto {pronta.scatto_id}", costruzione.DIVERSA)]
    assert not piano.posti and not piano.da_scrivere
    esito = _travaso(pronta).esegui()
    assert esito.completo
    assert [s.perche for s in esito.saltati] == [costruzione.DIVERSA]
    assert _nel_pacchetto(pronta) == ["dati"]
    assert formato.Carta.leggi(pronta.dove).note == [
        "1 file non è entrato nel pacchetto: i dettagli sono sul computer."]
    with lettore.apri(pronta.dove, PAROLA) as pacchetto:
        assert pacchetto.quanti() == 0


def test_una_foto_rovinata_nell_archivio_resta_fuori_e_si_riprova_dopo(sul_telefono):
    pronta = sul_telefono
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)

    esito = _travaso(pronta).esegui()
    assert not esito.interrotto
    assert [s.perche for s in esito.saltati] == [costruzione.ROVINATA] * 2
    assert _nel_pacchetto(pronta) == ["dati"]
    assert [c.genere for c in _travaso(pronta).prepara().da_scrivere] == [
        "originale", "miniatura"]


def test_se_l_archivio_si_chiude_a_meta_il_travaso_si_ferma_e_riparte_da_li(sul_telefono):
    pronta = sul_telefono

    def a_che_punto(fase: str, fatti: int, quanti: int) -> None:
        if fase == "scrivo" and fatti == 2:
            _chiudi(pronta)

    travaso = _travaso(pronta, quando_cambia=a_che_punto)
    assert _errore(travaso.esegui) == (CHIUSO_ADESSO, costruzione.SI_E_CHIUSO)
    assert formato.Carta.leggi(pronta.dove).stato == formato.INTERROTTO
    assert _nel_pacchetto(pronta) == ["originale"]
    with pronta.archivio.lettura() as connessione:
        assert telefoni.travaso_lasciato_a_meta(connessione, pronta.telefono_id)

    _riapri(pronta)
    di_nuovo = _travaso(pronta)
    piano = di_nuovo.prepara()
    assert piano.ripresa and piano.gia_dentro == 1
    assert [c.genere for c in piano.da_scrivere] == ["miniatura"]
    assert di_nuovo.esegui(piano).completo
    assert formato.Carta.leggi(pronta.dove).stato == formato.COMPLETO
    with lettore.apri(pronta.dove, PAROLA) as pacchetto:
        assert pacchetto.originale(pronta.scatto_id) == pronta.dati


def _con_un_volto(pronta) -> int:
    with pronta.archivio.scrittura() as connessione:
        persona = inserisci(connessione, "INSERT INTO persone (nome, stato, nata_il) "
                            "VALUES ('Anna', 'attiva', ?)", adesso())
        connessione.execute(
            "INSERT INTO volti (scatto_id, file_id, riquadro, area, nitidezza, sicurezza, "
            "modello, versione, persona_id, trovato_il) "
            "VALUES (?, ?, '[0.25, 0.25, 0.5, 0.5]', 0.25, 1.0, 0.9, 'prova', '1', ?, ?)",
            (pronta.scatto_id, pronta.file_id, persona, adesso()))
    return persona


def test_il_volto_di_una_persona_si_ritaglia_dalla_foto_dell_archivio(sul_telefono):
    pronta = sul_telefono
    _con_un_volto(pronta)
    travaso = _travaso(pronta)

    esito = travaso.esegui()
    assert esito.completo and not esito.saltati
    with pronta.archivio.lettura() as connessione:
        posto = uno(connessione, "SELECT posto FROM pacchetto_file WHERE telefono_id = ? "
                    "AND genere = 'volto'", pronta.telefono_id)["posto"]
    volto = travaso._chiave.leggi_tutto(formato.dentro(pronta.dove, posto), posto)
    with Image.open(io.BytesIO(volto)) as immagine:
        assert immagine.size == (costruzione.LATO_VOLTO, costruzione.LATO_VOLTO)
    with lettore.apri(pronta.dove, PAROLA) as pacchetto:
        assert "Anna" in [riga["nome"] for riga in pacchetto.persone()]


def test_il_volto_non_si_ritaglia_da_una_versione_diversa(sul_telefono):
    pronta = sul_telefono
    persona = _con_un_volto(pronta)
    travaso = _travaso(pronta)

    with pronta.archivio.lettura() as connessione:
        compito, = travaso._volti(connessione, {pronta.scatto_id}, {}, set())
    assert compito.persona_id == persona and isinstance(compito.sorgente, DallArchivio)
    _diversa(pronta)
    with pronta.archivio.lettura() as connessione:
        assert travaso._volti(connessione, {pronta.scatto_id}, {}, set()) == []


def test_la_stima_conta_le_foto_solo_nell_archivio(sul_telefono, monkeypatch):
    pronta = sul_telefono
    assert _conti(_stima(pronta)) == (1, 0, 0, 0)

    with monkeypatch.context() as stanza:
        stanza.setattr(file_media, "cerca_nell_archivio",
                       lambda *_: pytest.fail("la ricerca veloce bastava"))
        assert _conti(_stima(pronta)) == (1, 0, 0, 0)

    pronta.situazione.forzata = SI_APRE
    assert _conti(_stima(pronta)) == (0, 0, 1, 0)
    pronta.situazione.forzata = SENZA_ARCHIVIO
    assert _conti(_stima(pronta)) == (0, 1, 0, 0)
    pronta.situazione.forzata = None
    _chiudi(pronta)
    chiusa = _stima(pronta)
    assert _conti(chiusa) == (0, 0, 1, 0)
    assert {"testo": DA_CERCARE, "forte": True} in _avvisi_della_pagina(pronta, chiusa)
    _riapri(pronta)
    _diversa(pronta)
    diversa = _stima(pronta)
    assert _conti(diversa) == (0, 0, 0, 1)
    assert {"testo": DIVERSE, "forte": False} in _avvisi_della_pagina(pronta, diversa)


def test_la_stima_con_la_ricerca_rotta_la_aspetta_e_lo_dice(sul_telefono, monkeypatch):
    pronta = sul_telefono
    detti: list = []
    monkeypatch.setattr(registro, "avviso",
                        lambda nome, **campi: detti.append((nome, campi)))

    def rotta(*_, **__):
        raise ErroreOfficina("si è rotta", codice="prova_rotta")

    monkeypatch.setattr(pronta.casa.archivio, "cerca", rotta)
    assert _conti(_stima(pronta)) == (0, 0, 1, 0)
    assert [(nome, str(campi["motivo"])) for nome, campi in detti] == [
        ("sicuro.ricerca_non_riuscita", "prova_rotta")]


def test_la_pagina_conta_le_foto_da_cercare_e_le_versioni_diverse(sul_telefono):
    pronta = sul_telefono
    testi = [detto["testo"] for detto in _avvisi_della_pagina(
        pronta, selezione.Stima(quanti_scatti=1, da_cercare=1234, versioni_diverse=2))]
    assert ("1.234 file non sono sul disco e l'Archivio sicuro è chiuso: aprilo, se no il "
            "pacchetto non parte.") in testi
    assert ("2 file restano fuori: nell'Archivio sicuro c'è solo una versione cambiata "
            "dopo l'importazione.") in testi
    nessuna = _avvisi_della_pagina(pronta, selezione.Stima(quanti_scatti=1))
    assert not [detto for detto in nessuna if "Archivio sicuro" in detto["testo"]]


def test_cosa_mostrare_dice_anche_perche_non_c_e(sul_telefono):
    pronta = sul_telefono

    def guarda(file_id: int = pronta.file_id):
        with pronta.archivio.lettura() as connessione:
            return file_media.da_mostrare_con_ricerca(connessione, file_id)

    percorso, impronta, ricerca = guarda()
    assert isinstance(percorso, DallArchivio) and impronta is None
    assert ricerca.perche == TROVATA and ricerca.trovata is percorso
    with pronta.archivio.lettura() as connessione:
        sul_disco = uno(connessione, "SELECT file_id FROM percorsi WHERE presente = 1 "
                        "ORDER BY file_id LIMIT 1")["file_id"]
    percorso, _, ricerca = guarda(sul_disco)
    assert percorso.is_file() and ricerca is None
    _chiudi(pronta)
    percorso, impronta, ricerca = guarda()
    assert (percorso, impronta, ricerca.perche) == (None, None, CHIUSO)
    _riapri(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
            "impronta_base, base_e) VALUES (?, 'in_scambio', ?, ?, ?, 'originale')",
            (pronta.file_id, str(pronta.originale), str(pronta.originale),
             _impronta(pronta.dati)))
    assert guarda() == (None, None, None)


class _SiRompeAlSecondo(io.BytesIO):

    def read(self, quanti=-1):
        if self.tell():
            raise ErroreOfficina("L'Archivio sicuro è chiuso.", codice="archivio_chiuso")
        return super().read(quanti)


def _dall_archivio(dati: bytes, flussi: list, rotto: bool) -> DallArchivio:
    def prendi(_):
        flusso = (_SiRompeAlSecondo if rotto else io.BytesIO)(dati)
        flussi.append(flusso)
        return flusso

    return DallArchivio("ab" * 16, "grande.jpg", len(dati),
                        hashlib.blake2b(dati, digest_size=32).hexdigest(), False, False,
                        prendi)


def test_un_originale_dall_archivio_si_cifra_e_se_si_rompe_non_lascia_mezzi_file(tmp_path):
    chiave = cifratura.Chiave.dalla_password(PAROLA, b"un sale qualsiasi", cifratura.COSTO,
                                             cifratura.BLOCCO_SCRYPT, cifratura.PARALLELO)
    dati = bytes(range(256)) * (cifratura.BLOCCO // 128)
    flussi: list = []
    dove = tmp_path / "pacchetto" / "foto" / "uno"

    scritto = chiave.cifra_file(_dall_archivio(dati, flussi, False), dove, "foto/uno")
    assert scritto.impronta == hashlib.blake2b(dati, digest_size=32).hexdigest()
    assert chiave.leggi_tutto(dove, "foto/uno") == dati
    dove.unlink()
    assert _errore(lambda: chiave.cifra_file(_dall_archivio(dati, flussi, True), dove,
                                             "foto/uno"))[0] == "archivio_chiuso"
    assert list(dove.parent.iterdir()) == []
    assert all(flusso.closed for flusso in flussi)


def _rotta(*_, **__):
    raise ErroreOfficina("si è rotta", codice="prova_rotta")


NOTE = {
    "aperto": "originale solo nell'Archivio sicuro: ",
    "chiuso": "originale non sul disco, e l'Archivio sicuro era chiuso: ",
    "si_apre": "originale non sul disco, e l'Archivio sicuro era chiuso: ",
    "rotto": "originale non sul disco, e l'Archivio sicuro era chiuso: ",
    "senza": "originale non trovato sul disco: ",
}


@pytest.mark.parametrize("come", NOTE)
def test_la_sincronia_non_porta_le_foto_solo_nell_archivio_e_lo_dice(foto_nell_archivio,
                                                                    tmp_path, monkeypatch,
                                                                    come):
    pronta = foto_nell_archivio
    if come == "chiuso":
        _chiudi(pronta)
    elif come == "si_apre":
        pronta.situazione.forzata = SI_APRE
    elif come == "senza":
        pronta.situazione.forzata = SENZA_ARCHIVIO
    elif come == "rotto":
        monkeypatch.setattr(pronta.casa.archivio, "cerca", _rotta)
    copiati: list = []
    cifra = cifratura.Chiave.cifra_file

    def spia(chiave, sorgente, *resto):
        copiati.append(sorgente)
        return cifra(chiave, sorgente, *resto)

    monkeypatch.setattr(cifratura.Chiave, "cifra_file", spia)
    fatto = sincronia.costruisci(pronta.archivio, tmp_path / "fuori", PAROLA)

    impronta = _impronta(pronta.dati)[:12]
    assert [nota for nota in fatto.note if impronta in nota] == [NOTE[come] + impronta]
    assert copiati and not [s for s in copiati if isinstance(s, DallArchivio)]
    assert str(pronta.originale) not in [str(sorgente) for sorgente in copiati]
    _nessuna_copia_in_chiaro(pronta, tmp_path / "fuori")
