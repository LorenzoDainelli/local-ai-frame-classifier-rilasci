from __future__ import annotations

import json
import threading
import time

import pytest

from prove.conftest import tutto_pronto_per_il_telefono

from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.telefono import cavo, costruzione, formato, lettore, ritorno
from officina.web import telefono as pagina

PAROLA = "tre parole che ricordi"


@pytest.fixture
def telefono(archivio_pieno):
    tutto_pronto_per_il_telefono(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        return telefoni.crea(connessione, "iPhone", "ios")


@pytest.fixture
def pronto(archivio_pieno, telefono, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    esito = costruzione.Travaso(archivio_pieno, telefono, dove, PAROLA).esegui()
    assert esito.completo
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    return dove, radice


def _lassu(radice):
    return radice / cavo.PACCHETTO


def _uguali(dove, radice) -> None:
    for file in dove.rglob("*"):
        if not file.is_file():
            continue
        posto = file.relative_to(dove).as_posix()
        if posto in (formato.RITORNO, cavo.LOCALE):
            continue
        copia = _lassu(radice) / posto
        assert copia.is_file(), posto
        assert copia.read_bytes() == file.read_bytes(), posto


def test_la_prima_copia_porta_tutto_e_il_visore_si_apre(pronto):
    dove, radice = pronto
    finto = cavo.FintoTelefono(radice)

    esito = cavo.manda(finto, dove)

    assert esito.completo
    assert esito.mandati > 2
    assert esito.uguali == 0
    _uguali(dove, radice)
    assert finto.caricati[-1] == f"{cavo.PACCHETTO}/{formato.CARTA}.parziale"
    assert finto.caricati[-2] == f"{cavo.PACCHETTO}/{formato.DATI}.parziale"
    assert not list(_lassu(radice).rglob("*.parziale"))
    with lettore.apri(_lassu(radice), PAROLA) as pacchetto:
        assert pacchetto.completo
        assert pacchetto.verifica().tutto_a_posto


def test_la_seconda_copia_non_porta_niente(pronto):
    dove, radice = pronto
    primo = cavo.manda(cavo.FintoTelefono(radice), dove)

    finto = cavo.FintoTelefono(radice)
    esito = cavo.manda(finto, dove)

    assert esito.completo
    assert esito.mandati == 0
    assert esito.uguali == primo.mandati
    assert finto.caricati == []
    assert "già tutto uguale" in esito.a_parole()


def test_il_ritorno_non_va_mai_sull_iphone(pronto):
    dove, radice = pronto
    (dove / formato.RITORNO).write_bytes(b"ritorno")

    cavo.manda(cavo.FintoTelefono(radice), dove)

    assert not (_lassu(radice) / formato.RITORNO).exists()


def test_senza_la_cartella_del_visore_non_copia(pronto):
    dove, radice = pronto
    _lassu(radice).rmdir()

    with pytest.raises(ErroreOfficina) as preso:
        cavo.manda(cavo.FintoTelefono(radice), dove)
    assert preso.value.codice == "cavo_aprilo"
    assert not _lassu(radice).exists()


def test_un_pacchetto_non_finito_non_parte(pronto):
    dove, radice = pronto
    carta = formato.Carta.leggi(dove)
    carta.stato = formato.INTERROTTO
    carta.scrivi(dove)

    with pytest.raises(ErroreOfficina) as preso:
        cavo.manda(cavo.FintoTelefono(radice), dove)
    assert preso.value.codice == "cavo_non_finito"
    assert not any(_lassu(radice).iterdir())


def test_un_file_che_arriva_diverso_tiene_chiuso_il_visore(pronto):
    dove, radice = pronto

    esito = cavo.manda(cavo.FintoTelefono(radice, rovina={"foto"}), dove)

    assert not esito.completo
    assert esito.guasti
    assert "NON finita" in esito.a_parole()
    assert not (_lassu(radice) / formato.CARTA).exists()
    assert not list(_lassu(radice).rglob("*.parziale"))

    esito = cavo.manda(cavo.FintoTelefono(radice), dove)
    assert esito.completo
    _uguali(dove, radice)


def test_se_si_stacca_il_visore_resta_chiuso_e_poi_riprende(pronto):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    mini = sorted((dove / formato.MINI).rglob("*"))
    cambiati = [m for m in mini if m.is_file()][:2]
    for file in cambiati:
        file.write_bytes(file.read_bytes() + b"-nuovo")

    with pytest.raises(ErroreOfficina) as preso:
        cavo.manda(cavo.FintoTelefono(radice, stacca_dopo=1), dove)
    assert preso.value.codice == "cavo_staccato"
    lassu = json.loads((_lassu(radice) / formato.CARTA).read_text(encoding="utf-8"))
    assert lassu["stato"] == formato.INTERROTTO

    finto = cavo.FintoTelefono(radice)
    esito = cavo.manda(finto, dove)
    assert esito.completo
    assert esito.mandati == 2
    assert finto.caricati[-1] == f"{cavo.PACCHETTO}/{formato.CARTA}.parziale"
    _uguali(dove, radice)
    lassu = json.loads((_lassu(radice) / formato.CARTA).read_text(encoding="utf-8"))
    assert lassu["stato"] == formato.COMPLETO


def test_fermato_a_meta_lo_dice(pronto):
    dove, radice = pronto
    fermati = threading.Event()
    fermati.set()

    esito = cavo.manda(cavo.FintoTelefono(radice), dove, fermati=fermati)

    assert esito.interrotto
    assert not (_lassu(radice) / formato.CARTA).exists()


def test_i_file_vecchi_si_tolgono_e_gli_estranei_restano(pronto):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    vecchio = _lassu(radice) / "foto" / "ab" / ("0" * 32)
    vecchio.parent.mkdir(parents=True, exist_ok=True)
    vecchio.write_bytes(b"vecchio")
    avanzo = _lassu(radice) / "dati.db.parziale"
    avanzo.write_bytes(b"avanzo")
    estraneo = _lassu(radice) / "appunti.txt"
    estraneo.write_bytes(b"non mio")

    esito = cavo.manda(cavo.FintoTelefono(radice), dove)

    assert esito.completo
    assert esito.tolti == 2
    assert not vecchio.exists()
    assert not avanzo.exists()
    assert estraneo.read_bytes() == b"non mio"


def test_un_manifesto_bugiardo_non_inganna(pronto):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    una = next(p for p in (_lassu(radice) / formato.MINI).rglob("*") if p.is_file())
    una.write_bytes(b"corta")

    finto = cavo.FintoTelefono(radice)
    esito = cavo.manda(finto, dove)

    assert esito.mandati == 2
    assert finto.caricati[-1] == f"{cavo.PACCHETTO}/{formato.CARTA}.parziale"
    _uguali(dove, radice)


def test_il_pacchetto_di_un_altro_archivio_non_si_tocca(pronto):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    carta = _lassu(radice) / formato.CARTA
    altra = json.loads(carta.read_text(encoding="utf-8"))
    altra["archivio"] = "un-altro"
    carta.write_text(json.dumps(altra), encoding="utf-8")
    prima = sorted(p.as_posix() for p in _lassu(radice).rglob("*"))

    with pytest.raises(ErroreOfficina) as preso:
        cavo.manda(cavo.FintoTelefono(radice), dove)
    assert preso.value.codice == "cavo_altro_archivio"
    assert sorted(p.as_posix() for p in _lassu(radice).rglob("*")) == prima


def _ritorno_sul_telefono(dove, radice, tmp_path) -> bytes:
    chiave = formato.Carta.leggi(dove).chiave(PAROLA)
    grezzo = tmp_path / "ritorno-finto.sqlite"
    ritorno.scrivi_ritorno_finto(grezzo, diario=[("2026-08-10T09:00:00", 620, 43.8,
                                                  11.29, 47)])
    lassu = radice / cavo.RITORNO_SUL_TELEFONO
    lassu.parent.mkdir(parents=True, exist_ok=True)
    chiave.cifra_file(grezzo, lassu, formato.RITORNO)
    grezzo.unlink()
    return lassu.read_bytes()


def test_il_ritorno_arriva_dall_iphone(pronto, tmp_path):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    atteso = _ritorno_sul_telefono(dove, radice, tmp_path)

    assert cavo.prendi_il_ritorno(cavo.FintoTelefono(radice), dove) == "preso"
    assert (dove / formato.RITORNO).read_bytes() == atteso
    assert not (dove / (formato.RITORNO + cavo.PARZIALE)).exists()


def test_senza_ritorno_o_con_un_altra_chiave_non_si_prende(pronto, tmp_path):
    dove, radice = pronto
    finto = cavo.FintoTelefono(radice)
    assert cavo.prendi_il_ritorno(finto, dove) == "nessuno"
    _ritorno_sul_telefono(dove, radice, tmp_path)
    assert cavo.prendi_il_ritorno(finto, dove) == "senza_pacchetto"

    cavo.manda(finto, dove)
    carta = _lassu(radice) / formato.CARTA
    altra = json.loads(carta.read_text(encoding="utf-8"))
    altra["sale"] = "00" * 16
    carta.write_text(json.dumps(altra), encoding="utf-8")
    assert cavo.prendi_il_ritorno(finto, dove) == "altra_chiave"
    assert not (dove / formato.RITORNO).exists()


def test_dalla_pagina_col_cavo_porta_il_ritorno_e_copia(archivio_pieno, telefono,
                                                        tmp_path, monkeypatch):
    dove = tmp_path / "Visore-iPhone"
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    finti: list[cavo.FintoTelefono] = []

    def collega():
        finti.append(cavo.FintoTelefono(radice))
        return finti[-1]

    monkeypatch.setattr(cavo, "collega", collega)
    in_corso = pagina.InCorso()

    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert detto["col_cavo"] and detto["cavo_completo"]
    assert finti[-1].chiuso
    _uguali(dove, radice)

    _ritorno_sul_telefono(dove, radice, tmp_path)
    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert in_corso.esito.tornato.giornate_di_diario == 1
    assert detto["cavo_completo"]
    assert finti[-1].chiuso


def test_dalla_pagina_senza_iphone_lo_dice(archivio_pieno, telefono, tmp_path,
                                           monkeypatch):
    def collega():
        raise ErroreOfficina(cavo.NESSUNO, codice="cavo_nessuno")

    monkeypatch.setattr(cavo, "collega", collega)
    in_corso = pagina.InCorso()

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == cavo.NESSUNO
    assert not (tmp_path / "Visore-iPhone").exists()


def _aspetta_la_fase(in_corso, inizio, secondi=60.0):
    fino = time.monotonic() + secondi
    while time.monotonic() < fino:
        if str(in_corso.fase).startswith(inizio):
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def riprende_presto(monkeypatch):
    monkeypatch.setattr(pagina, "PAUSA_TRA_LE_PROVE", 0.05)


def test_dalla_pagina_se_si_stacca_aspetta_e_riprende_da_solo(
        archivio_pieno, telefono, tmp_path, monkeypatch, riprende_presto):
    dove = tmp_path / "Visore-iPhone"
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    in_corso = pagina.InCorso()
    prove = []
    finti: list[cavo.FintoTelefono] = []

    def collega():
        if str(in_corso.fase).startswith("aspetto"):
            prove.append(1)
            if len(prove) < 3:
                raise ErroreOfficina(cavo.NESSUNO, codice="cavo_nessuno")
            finti.append(cavo.FintoTelefono(radice))
        else:
            finti.append(cavo.FintoTelefono(radice, stacca_dopo=3))
        return finti[-1]

    monkeypatch.setattr(cavo, "collega", collega)

    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert detto["cavo_completo"]
    assert len(prove) >= 3
    assert any(riga.startswith("L'iPhone si è staccato") for riga in detto["righe"])
    assert any("Aspetto ancora" in riga for riga in detto["righe"])
    assert any(riga.startswith("Ricollegato") for riga in detto["righe"])
    assert all(finto.chiuso for finto in finti)
    _uguali(dove, radice)
    lassu = json.loads((_lassu(radice) / formato.CARTA).read_text(encoding="utf-8"))
    assert lassu["stato"] == formato.COMPLETO
    dettagli = detto["dettagli_per_claude"]
    assert "caduto durante la copia · cavo_staccato" in dettagli
    assert "riprovo a collegarmi · cavo_nessuno" in dettagli
    assert "ricollegato, ripresa numero 1" in dettagli
    assert "copia finita" in dettagli
    assert str(dove) not in dettagli and str(radice) not in dettagli
    assert cavo.STACCATO not in dettagli and cavo.NESSUNO not in dettagli
    for file in dove.rglob("*"):
        if len(file.name) >= 8:
            assert file.name not in dettagli


def test_i_dettagli_per_claude_non_dicono_niente_di_privato():
    class AfcFinto(Exception):
        pass

    class Stato:
        name = "OBJECT_NOT_FOUND"

    guaio = AfcFinto("/Documents/Pacchetto/segreto/nome.jpg")
    guaio.status = Stato()
    assert cavo.causa_tecnica(guaio) == "AfcFinto OBJECT_NOT_FOUND"
    rotto = OSError(5, "nome-segreto.jpg")
    assert cavo.causa_tecnica(rotto) == "OSError errno 5"
    assert cavo.causa_tecnica(cavo.GuastoDelCavo("/una/cartella/foto.jpg")) == (
        "GuastoDelCavo cavo_staccato")


def test_senza_guai_i_dettagli_restano_nascosti(archivio_pieno, telefono, tmp_path,
                                                 monkeypatch):
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    monkeypatch.setattr(cavo, "collega", lambda: cavo.FintoTelefono(radice))
    in_corso = pagina.InCorso()
    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.come_va()["cavo_completo"]
    assert in_corso.come_va()["dettagli_per_claude"] == ""


def test_dalla_pagina_fermato_mentre_aspetta_lo_dice(
        archivio_pieno, telefono, tmp_path, monkeypatch, riprende_presto):
    dove = tmp_path / "Visore-iPhone"
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    in_corso = pagina.InCorso()

    def collega():
        if str(in_corso.fase).startswith("aspetto"):
            raise ErroreOfficina(cavo.NESSUNO, codice="cavo_nessuno")
        return cavo.FintoTelefono(radice, stacca_dopo=3)

    monkeypatch.setattr(cavo, "collega", collega)

    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True)
    assert _aspetta_la_fase(in_corso, "aspetto")
    in_corso.ferma()
    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == pagina.FERMATO_MENTRE_ASPETTAVO
    carta = _lassu(radice) / formato.CARTA
    if carta.exists():
        assert json.loads(carta.read_text(encoding="utf-8"))["stato"] != formato.COMPLETO


def test_dalla_pagina_dopo_l_attesa_massima_si_arrende(
        archivio_pieno, telefono, tmp_path, monkeypatch, riprende_presto):
    monkeypatch.setattr(pagina, "ASPETTO_AL_MASSIMO", 0.5)
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    in_corso = pagina.InCorso()

    def collega():
        if str(in_corso.fase).startswith("aspetto"):
            raise ErroreOfficina(cavo.NESSUNO, codice="cavo_nessuno")
        return cavo.FintoTelefono(radice, stacca_dopo=3)

    monkeypatch.setattr(cavo, "collega", collega)

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == cavo.STACCATO
    assert not in_corso.come_va()["cavo_completo"]


def test_dalla_pagina_un_guaio_che_non_passa_non_si_aspetta(
        archivio_pieno, telefono, tmp_path, monkeypatch, riprende_presto):
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    in_corso = pagina.InCorso()

    def collega():
        if str(in_corso.fase).startswith("aspetto"):
            raise ErroreOfficina(cavo.SENZA_APP, codice="cavo_senza_app")
        return cavo.FintoTelefono(radice, stacca_dopo=3)

    monkeypatch.setattr(cavo, "collega", collega)

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == cavo.SENZA_APP


class _Lento(cavo.FintoTelefono):

    def carica(self, sorgente, posto):
        time.sleep(0.02)
        super().carica(sorgente, posto)


def test_con_due_strade_si_copia_in_parallelo_e_tutto_torna(pronto):
    dove, radice = pronto
    primo = _Lento(radice)
    aiuti: list[cavo.FintoTelefono] = []

    def aiuto():
        aiuti.append(_Lento(radice, nome="seconda strada"))
        return aiuti[-1]

    esito = cavo.manda(primo, dove, aiuto=aiuto)

    assert esito.completo
    assert len(aiuti) == 1 and aiuti[0].chiuso
    assert primo.caricati and aiuti[0].caricati
    assert esito.mandati == len(primo.caricati) + len(aiuti[0].caricati)
    assert primo.caricati[-1] == f"{cavo.PACCHETTO}/{formato.CARTA}.parziale"
    assert primo.caricati[-2] == f"{cavo.PACCHETTO}/{formato.DATI}.parziale"
    assert not any(formato.DATI in p or formato.CARTA in p for p in aiuti[0].caricati)
    assert not list(_lassu(radice).rglob("*.parziale"))
    _uguali(dove, radice)
    with lettore.apri(_lassu(radice), PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto


def test_se_la_seconda_strada_si_rompe_finisce_la_prima(pronto):
    dove, radice = pronto
    aiuti: list[cavo.FintoTelefono] = []

    def aiuto():
        aiuti.append(_Lento(radice, stacca_dopo=1))
        return aiuti[-1]

    esito = cavo.manda(_Lento(radice), dove, aiuto=aiuto)

    assert esito.completo
    assert aiuti[0].chiuso
    _uguali(dove, radice)
    lassu = json.loads((_lassu(radice) / formato.CARTA).read_text(encoding="utf-8"))
    assert lassu["stato"] == formato.COMPLETO


def test_se_la_seconda_strada_non_si_apre_basta_la_prima(pronto):
    dove, radice = pronto

    def aiuto():
        raise ErroreOfficina(cavo.NESSUNO, codice="cavo_nessuno")

    esito = cavo.manda(cavo.FintoTelefono(radice), dove, aiuto=aiuto)

    assert esito.completo
    _uguali(dove, radice)


def test_un_file_rovinato_dalla_seconda_strada_tiene_chiuso_il_visore(pronto):
    dove, radice = pronto

    def aiuto():
        return _Lento(radice, rovina={formato.MINI, formato.FOTO})

    esito = cavo.manda(_Lento(radice), dove, aiuto=aiuto)

    assert not esito.completo
    assert esito.guasti
    assert not (_lassu(radice) / formato.CARTA).exists()
    assert not list(_lassu(radice).rglob("*.parziale"))


def test_fermato_mentre_vanno_due_strade_lo_dice(pronto):
    dove, radice = pronto
    fermati = threading.Event()

    class Ferma(_Lento):
        def carica(self, sorgente, posto):
            super().carica(sorgente, posto)
            fermati.set()

    esito = cavo.manda(Ferma(radice), dove, fermati=fermati,
                       aiuto=lambda: Ferma(radice))

    assert esito.interrotto
    assert not (_lassu(radice) / formato.CARTA).exists()


class _CadeSenzaSalvare(cavo.FintoTelefono):

    def __init__(self, radice, quanti):
        super().__init__(radice)
        self.quanti = quanti
        self.caduto = False

    def carica(self, da, posto):
        if len(self.caricati) >= self.quanti:
            self.caduto = True
            raise cavo.GuastoDelCavo(posto)
        super().carica(da, posto)

    def scrivi(self, posto, dati):
        if self.caduto:
            raise cavo.GuastoDelCavo(posto)
        super().scrivi(posto, dati)


def test_ripartendo_dopo_una_caduta_non_rimanda_quello_che_e_gia_arrivato(pronto):
    dove, radice = pronto
    with pytest.raises(ErroreOfficina):
        cavo.manda(_CadeSenzaSalvare(radice, 3), dove)
    assert not (_lassu(radice) / cavo.MANIFESTO).exists()

    finto = cavo.FintoTelefono(radice)
    esito = cavo.manda(finto, dove)

    assert esito.completo
    assert esito.ritrovati == 3
    assert "rimasti dalla copia interrotta" in esito.a_parole()
    _uguali(dove, radice)


def test_un_file_lassu_della_stessa_misura_ma_diverso_si_rimanda(pronto):
    dove, radice = pronto
    cavo.manda(cavo.FintoTelefono(radice), dove)
    (_lassu(radice) / cavo.MANIFESTO).unlink()
    foto = next(f for f in _lassu(radice).rglob("*")
                if f.is_file() and f.relative_to(_lassu(radice)).parts[0] == formato.FOTO)
    grezzo = bytearray(foto.read_bytes())
    grezzo[-1] ^= 0xFF
    foto.write_bytes(bytes(grezzo))

    finto = cavo.FintoTelefono(radice)
    esito = cavo.manda(finto, dove)

    assert esito.completo
    posto = foto.relative_to(_lassu(radice)).as_posix()
    assert f"{cavo.PACCHETTO}/{posto}{cavo.PARZIALE}" in finto.caricati
    _uguali(dove, radice)
