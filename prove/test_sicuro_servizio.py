from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro import chiavi, formato
from officina.sicuro import elenco as registro
from officina.sicuro import servizio as modulo
from officina.sicuro.cestino import DA_FARE, DA_GUARDARE, ESTRATTA, FATTO, NEL_CESTINO
from officina.sicuro.chiavetta import PUOI_STACCARLA
from officina.sicuro.elenco import CONTENUTI
from officina.sicuro.servizio import ArchivioSicuro
from officina.sicuro.sottofondo import FINITO
from prove.test_sicuro_cestino import CestinoFinto
from prove.test_sicuro_chiavetta import LIBERO, TESTO, _sveglio, pezzi_piccoli
from prove.test_sicuro_copia import _dati

PAROLA = "tre parole che ricordo"
NUOVA = "quattro parole nuove davvero"
LEGGERO = 2 ** 10
ATTESA = 20.0

assert pezzi_piccoli


@pytest.fixture(autouse=True)
def costo_leggero(monkeypatch):
    monkeypatch.setattr(chiavi, "COSTO", LEGGERO)
    monkeypatch.setattr(chiavi, "COSTO_LENTO", LEGGERO * 2)
    monkeypatch.setattr(chiavi, "COSTI_AMMESSI", (LEGGERO, LEGGERO * 2))


def _finche(condizione, quanto: float = ATTESA) -> None:
    fine = time.monotonic() + quanto
    while not condizione():
        assert time.monotonic() < fine, "non è successo in tempo"
        time.sleep(0.01)


class Casa:

    def __init__(self, cartella: Path, **cambi):
        self.base = cartella
        self.cartella = cartella / "Officina.sicuro"
        self.foto = cartella / "foto"
        self.foto.mkdir()
        self.chiavetta = cartella / "E"
        self.chiavetta.mkdir()
        self.cestino = CestinoFinto(cartella)
        self.avvisi: list = []
        opzioni = self._opzioni()
        for nome, altro in cambi.items():
            opzioni[nome] = {**opzioni.get(nome, {}), **altro}
        self.archivio = ArchivioSicuro(self.cartella, salta=(cartella / "dati",),
                                       cestino=self.cestino, avvisa=self.avvisi.append,
                                       opzioni=opzioni)

    def _dischi(self) -> list[Path]:
        return [self.chiavetta]

    def _opzioni(self) -> dict:
        esaminatore = {"dischi": self._dischi, "speciali": lambda: [],
                       "nuvole": lambda: []}
        return {
            "copia": {"sveglio": _sveglio, "disco": lambda dove: (LIBERO, LIBERO)},
            "chiavetta": {"sveglio": _sveglio, "spazio": lambda radice: LIBERO,
                          "stesso_disco": lambda uno, altro: False,
                          "sistema": lambda radice: "exFAT", "leggimi": TESTO},
            "controllo": {"sveglio": _sveglio},
            "ripara": {"sveglio": _sveglio},
            "fresco": {"sveglio": _sveglio, **esaminatore},
            "spedizioniere": dict(esaminatore),
            "estrai": {"sveglio": _sveglio, "spazio": lambda dove: LIBERO},
            "verifica": {"sveglio": _sveglio},
            "mandata": {"sveglio": _sveglio},
            "ricontrollo": {"sveglio": _sveglio},
            "ronda": {"ogni": 0.01},
            "custode": {"ogni_giro": 0.01, "dischi": self._dischi, "ogni": 0.01},
        }

    @property
    def aperto(self):
        return self.archivio._aperto

    def metti(self, relativo: str, dati: bytes) -> Path:
        percorso = self.foto / relativo
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(dati)
        return percorso

    def radici(self) -> list[dict]:
        return self.aperto.elenco.radici()

    def copiato(self) -> bool:
        aperto = self.aperto
        radici = aperto.elenco.radici()
        return bool(radici) and not aperto.copia.acceso and all(
            (aperto.elenco.giro(radice["id"]) or {}).get("fine") is not None
            for radice in radici)

    def con_la_chiavetta(self) -> None:
        aperto = self.aperto
        aperto.chiavetta.chiavetta.prepara(self.chiavetta)
        aperto.custode.guardiano.ricomincia()
        _finche(lambda: aperto.custode.guardiano.stato == PUOI_STACCARLA)

    def chiudi(self) -> None:
        if self.archivio.aperto or self.archivio.si_chiude:
            assert self.archivio.chiudi(ATTESA)


@pytest.fixture
def casa(tmp_path):
    casa = Casa(tmp_path)
    yield casa
    casa.chiudi()


def _codice(fare) -> str:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value.codice


def _nomi(cartella: Path) -> list[str]:
    return sorted(voce.name for voce in cartella.iterdir())


def test_si_crea_si_chiude_e_si_riapre(casa):
    archivio = casa.archivio
    assert not archivio.esiste and not archivio.aperto
    archivio.crea(PAROLA, costo=LEGGERO)
    assert archivio.esiste and archivio.aperto
    assert (casa.cartella / CONTENUTI).is_dir()
    assert archivio.chiudi(ATTESA)
    assert not archivio.aperto and not archivio.si_chiude
    with pytest.raises(PasswordSbagliata):
        archivio.apri("un'altra password lunga")
    assert not archivio.aperto
    archivio.apri(PAROLA)
    assert archivio.aperto


def test_chiudere_due_volte_va_bene(casa):
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    assert casa.archivio.chiudi(ATTESA)
    assert casa.archivio.chiudi(ATTESA)


def test_aprire_quando_e_gia_aperto_controlla_lo_stesso_la_password(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    aperto = casa.aperto
    archivio.apri(PAROLA)
    assert casa.aperto is aperto
    with pytest.raises(PasswordSbagliata):
        archivio.apri("un'altra password lunga")
    assert casa.aperto is aperto


@pytest.mark.parametrize("cosa", ["file", "cartella", "contenuti", "nascosto"])
def test_non_si_crea_sopra_una_cartella_con_dentro_qualcosa(casa, cosa):
    casa.cartella.mkdir()
    if cosa == "file":
        (casa.cartella / "foto.jpg").write_bytes(b"qualcosa")
    elif cosa == "cartella":
        (casa.cartella / registro.ELENCO).mkdir()
    elif cosa == "contenuti":
        (casa.cartella / CONTENUTI).mkdir()
    else:
        (casa.cartella / ".nascosto").write_bytes(b"")
    prima = _nomi(casa.cartella)
    assert _codice(lambda: casa.archivio.crea(PAROLA, costo=LEGGERO)) == (
        "cartella_non_vuota")
    assert _nomi(casa.cartella) == prima and not casa.archivio.aperto
    assert not chiavi.esiste(casa.cartella)


def test_non_si_crea_due_volte(casa):
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    assert _codice(lambda: casa.archivio.crea(NUOVA, costo=LEGGERO)) == "chiave_esiste"
    assert casa.archivio.chiudi(ATTESA)
    assert _codice(lambda: casa.archivio.crea(NUOVA, costo=LEGGERO)) == "chiave_esiste"
    casa.archivio.apri(PAROLA)


def test_con_la_password_corta_non_si_crea_niente(casa):
    assert _codice(lambda: casa.archivio.crea("corta", costo=LEGGERO)) == "password_corta"
    assert not casa.cartella.exists() and not casa.archivio.aperto


@pytest.mark.parametrize("avanzo", [b"", b"{mezzo", bytes(300)])
@pytest.mark.parametrize("nome", [chiavi.FILE + ".nuovo", chiavi.RISERVA + ".nuovo"])
def test_un_file_a_meta_della_prima_creazione_non_la_blocca(casa, nome, avanzo):
    casa.cartella.mkdir()
    (casa.cartella / nome).write_bytes(avanzo)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    assert casa.archivio.aperto and (casa.cartella / CONTENUTI).is_dir()
    assert not (casa.cartella / nome).exists()
    assert casa.archivio.chiudi(ATTESA)
    casa.archivio.apri(PAROLA)


def test_una_chiave_intera_lasciata_a_meta_non_si_scrive_sopra(casa, tmp_path):
    altrove = tmp_path / "altra"
    chiavi.crea(altrove, NUOVA, costo=LEGGERO)
    casa.cartella.mkdir()
    intera = (altrove / chiavi.FILE).read_bytes()
    (casa.cartella / (chiavi.FILE + ".nuovo")).write_bytes(intera)
    assert _codice(lambda: casa.archivio.crea(PAROLA, costo=LEGGERO)) == (
        "cartella_non_vuota")
    assert (casa.cartella / (chiavi.FILE + ".nuovo")).read_bytes() == intera
    assert _nomi(casa.cartella) == [chiavi.FILE + ".nuovo"]


@pytest.mark.parametrize("cosa", ["cartella", "altro_nome"])
def test_solo_i_file_a_meta_della_chiave_non_contano(casa, cosa):
    casa.cartella.mkdir()
    if cosa == "cartella":
        (casa.cartella / (chiavi.FILE + ".nuovo")).mkdir()
    else:
        (casa.cartella / "elenco.nuovo").write_bytes(b"")
    prima = _nomi(casa.cartella)
    assert _codice(lambda: casa.archivio.crea(PAROLA, costo=LEGGERO)) == (
        "cartella_non_vuota")
    assert _nomi(casa.cartella) == prima and not chiavi.esiste(casa.cartella)


def test_una_creazione_interrotta_si_finisce_quando_si_apre(casa):
    chiavi.crea(casa.cartella, PAROLA, costo=LEGGERO)
    (casa.cartella / (chiavi.FILE + ".nuovo")).write_bytes(b"")
    assert not (casa.cartella / CONTENUTI).exists()
    casa.archivio.apri(PAROLA)
    assert (casa.cartella / CONTENUTI).is_dir()


def test_se_sparisce_la_cartella_dei_contenuti_non_la_rifaccio(casa):
    casa.metti("s/a.jpg", _dati(100, 1))
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    assert archivio.chiudi(ATTESA)
    os.rename(casa.cartella / CONTENUTI, casa.base / "altrove")
    archivio.apri(PAROLA)
    assert not (casa.cartella / CONTENUTI).exists()
    assert "archivio_sparito" in archivio.istantanea()["problemi_quaderno"]


def test_aprendo_con_due_password_resta_solo_quella_usata(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.aggiungi_password(NUOVA)
    assert chiavi.porte(casa.cartella) == 2
    assert archivio.chiudi(ATTESA)
    archivio.apri(NUOVA)
    assert chiavi.porte(casa.cartella) == 1
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(casa.cartella, PAROLA)
    assert archivio.istantanea()["problemi"] == []


def test_aprendo_senza_pulire_restano_tutte_e_due(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.aggiungi_password(NUOVA)
    assert archivio.chiudi(ATTESA)
    archivio.apri(PAROLA, pulisci=False)
    assert chiavi.porte(casa.cartella) == 2


def test_se_non_riesco_a_togliere_la_vecchia_lo_dico_e_apro_lo_stesso(casa, monkeypatch):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.aggiungi_password(NUOVA)
    assert archivio.chiudi(ATTESA)

    def rotto(*_):
        raise OSError("disco pieno")

    monkeypatch.setattr(chiavi, "tieni_solo", rotto)
    archivio.apri(NUOVA)
    assert archivio.aperto
    assert archivio.istantanea()["problemi"] == ["password_vecchia_ancora_buona"]
    assert chiavi.porte(casa.cartella) == 2


def test_una_chiave_di_un_altro_archivio_nella_cartella_si_dice_e_non_si_tocca(
        casa, tmp_path):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    assert archivio.chiudi(ATTESA)
    altro = tmp_path / "altro"
    chiavi.crea(altro, NUOVA, costo=LEGGERO)
    estranea = (altro / chiavi.FILE).read_bytes()
    (casa.cartella / chiavi.RISERVA).write_bytes(estranea)
    archivio.apri(PAROLA)
    assert archivio.aperto
    assert archivio.istantanea()["problemi"] == ["chiave_mescolata"]
    assert (casa.cartella / chiavi.RISERVA).read_bytes() == estranea


def test_cambiare_password_dall_archivio_aperto(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.aggiungi_password(NUOVA)
    archivio.tieni_solo(NUOVA)
    assert chiavi.porte(casa.cartella) == 1
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(casa.cartella, PAROLA)
    with pytest.raises(PasswordSbagliata):
        archivio.tieni_solo(PAROLA)
    assert chiavi.apri(casa.cartella, NUOVA)


def test_prima_di_copia_tutto_non_entra_niente_e_dopo_entra_tutto_da_solo(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    b = casa.metti("B/due.jpg", _dati(200, 2)).parent
    casa.metti("A/sotto/tre.jpg", _dati(300, 3))
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    assert archivio.metti_le_cartelle([a, b]) == []
    assert casa.radici() == []
    assert _codice(lambda: archivio.aggiungi(a)) == "prima_copia_tutto"
    nuove = archivio.copia_tutto([a])
    assert [radice["percorso"] for radice in nuove] == [str(a)]
    _finche(casa.copiato)
    assert len(casa.aperto.elenco.numeri()) == 2
    nuove = archivio.metti_le_cartelle([a, a / "sotto", b])
    assert [radice["percorso"] for radice in nuove] == [str(b)]
    _finche(lambda: len(casa.aperto.elenco.numeri()) == 3 and casa.copiato())
    assert archivio.metti_le_cartelle([a, b]) == []
    assert [radice["percorso"] for radice in casa.radici()] == [str(a), str(b)]


def test_una_cartella_che_contiene_quelle_gia_copiate_entra_lo_stesso(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([a])
    nuove = archivio.metti_le_cartelle([casa.foto])
    assert [radice["percorso"] for radice in nuove] == [str(casa.foto)]
    assert [radice["percorso"] for radice in casa.radici()] == [str(a), str(casa.foto)]


def test_una_cartella_che_non_c_e_piu_si_mette_lo_stesso(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    sparita = casa.base / "sparita"
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    nuove = archivio.copia_tutto([a, sparita])
    assert [radice["percorso"] for radice in nuove] == [str(a), str(sparita)]
    _finche(casa.copiato)
    assert len(casa.aperto.elenco.numeri()) == 1


def test_la_stessa_cartella_scritta_due_volte_entra_una_volta(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    nuove = archivio.copia_tutto([a, str(a) + os.sep, a / "." , a])
    assert len(nuove) == 1 and len(casa.radici()) == 1


def test_la_cartella_dell_archivio_non_si_copia_dentro_se_stessa(casa):
    casa.metti("A/uno.jpg", _dati(100, 1))
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([casa.base])
    _finche(casa.copiato)
    assert len(casa.aperto.elenco.numeri()) == 1
    assert os.fspath(casa.cartella) in archivio.salta


def test_le_cartelle_dentro_l_archivio_non_entrano(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    nuove = archivio.copia_tutto([casa.cartella, casa.cartella / CONTENUTI, a])
    assert [radice["percorso"] for radice in nuove] == [str(a)]
    assert archivio.metti_le_cartelle([casa.cartella / CONTENUTI]) == []
    assert [radice["percorso"] for radice in casa.radici()] == [str(a)]


def test_un_percorso_impossibile_non_ferma_gli_altri(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    nuove = archivio.copia_tutto(["con\x00dentro", a])
    assert [radice["percorso"] for radice in nuove] == [str(a)]


def test_aggiungere_una_cartella_dopo_copia_tutto(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    c = casa.metti("C/quattro.jpg", _dati(400, 4)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([a])
    esito = archivio.aggiungi(c)
    assert esito["nuova"] and esito["percorso"] == str(c)
    assert not archivio.aggiungi(c)["nuova"]
    assert not archivio.aggiungi(a)["nuova"]
    _finche(lambda: len(casa.aperto.elenco.numeri()) == 2 and casa.copiato())


def test_le_cartelle_messe_da_due_parti_insieme_non_si_doppiano(casa):
    cartelle = [casa.metti(f"C{indice}/f.jpg", _dati(100 + indice, indice)).parent
                for indice in range(8)]
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([cartelle[0]])
    barriera = threading.Barrier(4)

    def metti():
        barriera.wait(ATTESA)
        archivio.metti_le_cartelle(cartelle)

    fili = [threading.Thread(target=metti) for _ in range(4)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join(ATTESA)
    percorsi = [radice["percorso"] for radice in casa.radici()]
    assert sorted(percorsi) == sorted(map(str, cartelle))


def test_una_cartella_messa_mentre_parte_copia_tutto_non_si_perde(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    b = casa.metti("B/due.jpg", _dati(200, 2)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    aperto = casa.aperto
    risposte: list = []
    with aperto._registra:
        filo = threading.Thread(
            target=lambda: risposte.append(archivio.metti_le_cartelle([b])))
        filo.start()
        filo.join(0.2)
        archivio.copia_tutto([a])
    filo.join(ATTESA)
    nuove, = risposte
    assert [radice["percorso"] for radice in nuove] == [str(b)]
    assert sorted(radice["percorso"] for radice in casa.radici()) == sorted(
        [str(a), str(b)])


def test_chiudere_aspetta_la_cartella_che_si_sta_registrando(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    b = casa.metti("B/due.jpg", _dati(200, 2)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([a])
    _finche(casa.copiato)
    aperto = casa.aperto
    dentro, libera = threading.Event(), threading.Event()
    vera = aperto.elenco.registra

    def lenta(fatti):
        dentro.set()
        libera.wait(ATTESA)
        vera(fatti)

    aperto.elenco.registra = lenta
    esiti: list = []

    def metti():
        try:
            esiti.append(archivio.metti_le_cartelle([b]))
        except BaseException as errore:
            esiti.append(errore)

    mette = threading.Thread(target=metti)
    mette.start()
    assert dentro.wait(ATTESA)
    chiusa: list = []
    chiude = threading.Thread(target=lambda: chiusa.append(archivio.chiudi(ATTESA)))
    chiude.start()
    chiude.join(0.3)
    assert chiude.is_alive()
    libera.set()
    mette.join(ATTESA)
    chiude.join(ATTESA)
    nuove, = esiti
    assert [radice["percorso"] for radice in nuove] == [str(b)]
    assert chiusa == [True]
    archivio.apri(PAROLA)
    assert [radice["percorso"] for radice in casa.radici()] == [str(a), str(b)]


def test_dopo_la_chiusura_non_si_registra_niente(casa):
    a = casa.metti("A/uno.jpg", _dati(100, 1)).parent
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([a])
    aperto = casa.aperto
    assert archivio.chiudi(ATTESA)
    assert _codice(lambda: aperto.registra([casa.foto], prima=True)) == "archivio_chiuso"
    assert _codice(lambda: aperto.aggiungi(casa.foto)) == "archivio_chiuso"
    assert aperto.salva() and aperto.chiudi_elenco()
    archivio.apri(PAROLA)
    assert [radice["percorso"] for radice in casa.radici()] == [str(a)]


def test_la_password_scritta_ad_archivio_aperto_rimette_a_posto_la_chiave(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    buona = (casa.cartella / chiavi.FILE).read_bytes()
    os.unlink(casa.cartella / chiavi.RISERVA)
    archivio.apri(PAROLA)
    assert (casa.cartella / chiavi.RISERVA).read_bytes() == buona


def test_chiudere_ferma_tutto_e_chiude_l_elenco(casa):
    casa.metti("A/uno.jpg", _dati(100, 1))
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    aperto = casa.aperto
    assert archivio.chiudi(ATTESA)
    assert aperto.fermo and not aperto.custode.guardiano.acceso
    assert not aperto.ronda.acceso and not aperto.copia.acceso
    with pytest.raises(sqlite3.ProgrammingError):
        aperto.elenco.radici()
    archivio.apri(PAROLA)
    assert len(casa.aperto.elenco.numeri()) == 1


def test_se_un_lavoro_non_si_ferma_non_si_riapre_finche_non_ha_finito(tmp_path):
    dentro, libera = threading.Event(), threading.Event()

    def disco(dove):
        dentro.set()
        libera.wait(ATTESA)
        return LIBERO, LIBERO

    casa = Casa(tmp_path, copia={"disco": disco})
    try:
        casa.metti("A/uno.jpg", _dati(100, 1))
        archivio = casa.archivio
        archivio.crea(PAROLA, costo=LEGGERO)
        aperto = casa.aperto
        archivio.copia_tutto([casa.foto])
        assert dentro.wait(ATTESA)
        assert not archivio.chiudi(0.2)
        assert not archivio.aperto and archivio.si_chiude
        assert archivio.istantanea()["si_chiude"]
        assert _codice(lambda: archivio.apri(PAROLA)) == "si_chiude"
        assert aperto.elenco.radici()
        libera.set()
        _finche(lambda: not archivio.si_chiude)
        archivio.apri(PAROLA)
        assert archivio.aperto and casa.aperto is not aperto
        with pytest.raises(sqlite3.ProgrammingError):
            aperto.elenco.radici()
    finally:
        libera.set()
        casa.chiudi()


def test_chiudere_di_nuovo_aspetta_quello_che_non_si_era_fermato(tmp_path):
    dentro, libera = threading.Event(), threading.Event()

    def disco(dove):
        dentro.set()
        libera.wait(ATTESA)
        return LIBERO, LIBERO

    casa = Casa(tmp_path, copia={"disco": disco})
    try:
        casa.metti("A/uno.jpg", _dati(100, 1))
        archivio = casa.archivio
        archivio.crea(PAROLA, costo=LEGGERO)
        aperto = casa.aperto
        archivio.copia_tutto([casa.foto])
        assert dentro.wait(ATTESA)
        assert not archivio.chiudi(0.2)
        assert not archivio.chiudi(0.2)
        libera.set()
        assert archivio.chiudi(ATTESA)
        assert not archivio.si_chiude
        with pytest.raises(sqlite3.ProgrammingError):
            aperto.elenco.radici()
    finally:
        libera.set()
        casa.chiudi()


@pytest.mark.parametrize("fare", [
    lambda archivio: archivio.copia_tutto([]),
    lambda archivio: archivio.metti_le_cartelle([]),
    lambda archivio: archivio.aggiungi("."),
    lambda archivio: archivio.via_libera(["."]),
    lambda archivio: archivio.manda_nel_cestino(["."], "CANCELLA"),
    lambda archivio: archivio.ricontrolla(),
    lambda archivio: archivio.estrai([]),
    lambda archivio: archivio.estrai_la_prova("."),
    lambda archivio: archivio.ho_controllato(),
    lambda archivio: archivio.verifica("."),
    lambda archivio: archivio.ripara([]),
    lambda archivio: archivio.ho_capito("x"),
    lambda archivio: archivio.annulla(),
    lambda archivio: archivio.pausa("copia"),
    lambda archivio: archivio.riprendi("copia"),
    lambda archivio: archivio.controlla_ora(),
    lambda archivio: archivio.aggiungi_password(NUOVA),
    lambda archivio: archivio.tieni_solo(PAROLA),
])
def test_ad_archivio_chiuso_non_si_fa_niente(casa, fare):
    assert _codice(lambda: fare(casa.archivio)) == "archivio_chiuso"
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    assert casa.archivio.chiudi(ATTESA)
    assert _codice(lambda: fare(casa.archivio)) == "archivio_chiuso"


def test_la_fotografia_dell_archivio(casa):
    archivio = casa.archivio
    assert archivio.istantanea() == {"esiste": False, "aperto": False,
                                     "si_chiude": False, "problemi": []}
    archivio.crea(PAROLA, costo=LEGGERO)
    foto = archivio.istantanea()
    assert foto["aperto"] and foto["esiste"] and foto["collaudo"] == DA_FARE
    assert set(foto["tuoi"]) == {"via_libera", "cestino", "ricontrollo", "estrai",
                                 "prova", "verifica", "ripara"}
    for parte in ("custode", "chiavetta", "copia", "controllo", "ronda"):
        assert isinstance(foto[parte], dict)
    assert archivio.chiudi(ATTESA)
    assert archivio.istantanea() == {"esiste": True, "aperto": False,
                                     "si_chiude": False, "problemi": []}


def test_l_archivio_di_adesso_si_tiene_da_una_parte(casa):
    assert modulo.attuale() is None
    modulo.imposta(casa.archivio)
    try:
        assert modulo.attuale() is casa.archivio
    finally:
        modulo.imposta(None)
    assert modulo.attuale() is None


def test_la_pausa_della_copia_passa_al_custode(casa):
    archivio = casa.archivio
    archivio.crea(PAROLA, costo=LEGGERO)
    archivio.pausa("copia")
    assert archivio.istantanea()["custode"]["in_pausa"] == ["copia"]
    archivio.riprendi("copia")
    assert archivio.istantanea()["custode"]["in_pausa"] == []
    with pytest.raises(ValueError):
        archivio.pausa("chiavetta")


def _con_le_foto(casa) -> Path:
    s = casa.metti("s/a.jpg", _dati(100, 1)).parent
    casa.metti("s/b.jpg", _dati(3 * formato.BLOCCO + 7, 2))
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    return s


def test_dal_vero_via_libera_cestino_e_cartella_di_prova(casa):
    s = _con_le_foto(casa)
    archivio, aperto = casa.archivio, casa.aperto
    assert archivio.via_libera([s])
    assert aperto.fresco.aspetta_fine(ATTESA) and aperto.fresco.stato == FINITO
    esame, = aperto.fresco.esaminatore.esami
    assert esame.verde, esame.istantanea()
    assert archivio.manda_nel_cestino([s, s], "CANCELLA")
    assert aperto.mandata.aspetta_fine(ATTESA), aperto.mandata.istantanea()
    risultato, = aperto.mandata.risultati
    assert risultato["esito"] == NEL_CESTINO, risultato
    assert not s.exists() and len(casa.cestino.mosse) == 1
    assert aperto.quaderno.collaudo == DA_GUARDARE
    fuori = casa.base / "fuori"
    assert archivio.estrai_la_prova(fuori)
    assert aperto.prova.aspetta_fine(ATTESA) and aperto.prova.stato == FINITO
    assert aperto.quaderno.collaudo == ESTRATTA
    estratti = sorted(percorso.read_bytes() for percorso in fuori.rglob("*.jpg"))
    assert estratti == sorted([_dati(100, 1), _dati(3 * formato.BLOCCO + 7, 2)])
    archivio.ho_controllato()
    assert aperto.quaderno.collaudo == FATTO


def test_senza_un_controllo_fresco_non_si_manda_niente_nel_cestino(casa):
    s = _con_le_foto(casa)
    archivio = casa.archivio
    assert _codice(lambda: archivio.manda_nel_cestino([s], "CANCELLA")) == (
        "da_ricontrollare")
    assert _codice(lambda: archivio.manda_nel_cestino([], "CANCELLA")) == "niente_scelto"
    assert s.exists() and casa.cestino.mosse == []


def test_con_la_parola_sbagliata_non_si_manda_niente_nel_cestino(casa):
    s = _con_le_foto(casa)
    archivio, aperto = casa.archivio, casa.aperto
    assert archivio.via_libera([s])
    assert aperto.fresco.aspetta_fine(ATTESA)
    for parola in ("cancella", "CANCELLO", ""):
        assert _codice(lambda: archivio.manda_nel_cestino([s], parola)) == (
            "parola_sbagliata")
    assert s.exists() and casa.cestino.mosse == []
    assert archivio.istantanea()["custode"]["turno"] is None


def test_una_cartella_controllata_prima_di_un_altro_controllo_non_vale_piu(casa):
    s = _con_le_foto(casa)
    t = casa.metti("t/c.jpg", _dati(50, 5)).parent
    archivio, aperto = casa.archivio, casa.aperto
    assert archivio.via_libera([s])
    assert aperto.fresco.aspetta_fine(ATTESA)
    assert archivio.via_libera([t])
    assert aperto.fresco.aspetta_fine(ATTESA)
    assert _codice(lambda: archivio.manda_nel_cestino([s], "CANCELLA")) == (
        "da_ricontrollare")
    assert s.exists() and casa.cestino.mosse == []


def test_riparare_prende_la_copia_dalla_chiavetta(tmp_path):
    casa = Casa(tmp_path, ripara={"luoghi": lambda: []})
    try:
        _con_le_foto(casa)
        archivio, aperto = casa.archivio, casa.aperto
        radice, = casa.radici()
        numero = aperto.elenco.attuale(radice["id"], "s/b.jpg").contenuto
        blob = registro.percorso_contenuto(casa.cartella, numero)
        blob.write_bytes(bytes(len(blob.read_bytes())))
        assert archivio.ripara([numero, numero])
        assert aperto.ripara.aspetta_fine(ATTESA) and aperto.ripara.stato == FINITO
        rapporto = aperto.ripara.controllore.rapporto
        assert rapporto.come["copia"] == 1 and rapporto.riparati == [numero]
        with open(blob, "rb") as file:
            dati = formato.Contenuto(file, aperto.chiave,
                                     numero=bytes.fromhex(numero)).tutto()
        assert dati == _dati(3 * formato.BLOCCO + 7, 2)
    finally:
        casa.chiudi()


def test_senza_chiavetta_attaccata_la_riparazione_non_inventa_niente(tmp_path):
    casa = Casa(tmp_path, ripara={"luoghi": lambda: []})
    try:
        _con_le_foto(casa)
        archivio, aperto = casa.archivio, casa.aperto
        os.rename(casa.chiavetta, casa.base / "staccata")
        radice, = casa.radici()
        numero = aperto.elenco.attuale(radice["id"], "s/b.jpg").contenuto
        blob = registro.percorso_contenuto(casa.cartella, numero)
        rotto = bytes(len(blob.read_bytes()))
        blob.write_bytes(rotto)
        assert archivio.ripara([numero])
        assert aperto.ripara.aspetta_fine(ATTESA)
        assert aperto.ripara.controllore.rapporto.riparati == []
        assert blob.read_bytes() == rotto
    finally:
        casa.chiudi()


def test_la_verifica_di_una_cartella_passa_dal_turno(casa):
    s = _con_le_foto(casa)
    archivio, aperto = casa.archivio, casa.aperto
    assert archivio.verifica(s)
    assert aperto.verifica.aspetta_fine(ATTESA) and aperto.verifica.stato == FINITO
    assert aperto.verifica.istantanea()["verde"]


def test_un_tuo_lavoro_alla_volta(casa):
    s = _con_le_foto(casa)
    archivio, aperto = casa.archivio, casa.aperto
    tienila, entrata = threading.Event(), threading.Event()
    vera = aperto.verifica.verificatore.verifica

    def lenta(percorso):
        entrata.set()
        tienila.wait(ATTESA)
        return vera(percorso)

    aperto.verifica.verificatore.verifica = lenta
    assert archivio.via_libera([s])
    assert aperto.fresco.aspetta_fine(ATTESA)
    try:
        assert archivio.verifica(s)
        assert entrata.wait(ATTESA)
        assert _codice(lambda: archivio.via_libera([s])) == "occupato"
        assert _codice(lambda: archivio.manda_nel_cestino([s], "CANCELLA")) == "occupato"
        assert _codice(lambda: archivio.ripara([])) == "occupato"
    finally:
        tienila.set()
    assert aperto.verifica.aspetta_fine(ATTESA)
    assert s.exists() and casa.cestino.mosse == []


def test_annullare_ferma_il_tuo_lavoro(casa):
    s = _con_le_foto(casa)
    archivio, aperto = casa.archivio, casa.aperto
    entrata = threading.Event()

    def ferma_qui(percorso):
        entrata.set()
        while True:
            aperto.verifica._aspetta()
            time.sleep(0.01)

    aperto.verifica.verificatore.verifica = ferma_qui
    assert archivio.verifica(s)
    assert entrata.wait(ATTESA)
    archivio.annulla()
    assert aperto.verifica.aspetta_fine(ATTESA)
    assert aperto.verifica.stato == "fermato"
    _finche(lambda: archivio.istantanea()["custode"]["turno"] is None)
