from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import pickle
import threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina import schermo
from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.immagini import compatibile, consegna, fotogrammi, lettura
from officina.importazione import miniature, quicktime
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.programma.avvio import Programma
from officina.sicuro import chiavi, dall_archivio, formato, prendi
from officina.sicuro import elenco as registro
from officina.sicuro import servizio as modulo
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SENZA_ARCHIVIO, SI_APRE, TROVATA,
                                           DallArchivio)
from officina.web.strade import comune, scatto, tentativi
from prove import test_sicurezza_strade_accessi as accessi
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_copia import _dati
from prove.test_sicuro_servizio import ATTESA, LEGGERO, PAROLA, Casa, _con_le_foto, _finche

costo_leggero = servizio_di_prova.costo_leggero
porta_finta = accessi.porta_finta
portatile = accessi.portatile

PILLOLA = 'class="pillola minuscolo ft-dall-archivio"'
PERSA = '<div class="dentro-la-lastra ft-non-si-apre ft-persa" id="foto-persa"'
CHIUSA = '<div class="dentro-la-lastra ft-non-si-apre" id="archivio-chiuso">'
SI_STA_APRENDO = '<div class="dentro-la-lastra ft-non-si-apre" id="archivio-si-apre"'
FOTO = '<img id="lastra-principale"'

SENZA_CODIFICATORE = pytest.mark.skipif(not compatibile.si_puo_fare(),
                                        reason="manca il codificatore H.264")


def _impronta(dati: bytes) -> str:
    return hashlib.blake2b(dati, digest_size=formato.IMPRONTA).hexdigest()


def _jpeg(larghezza: int = 96, altezza: int = 64, seme: int = 3) -> bytes:
    tela = Image.new("RGB", (larghezza, altezza), (seme * 20 % 256, 90, 160))
    for x in range(0, larghezza, 8):
        for y in range(altezza):
            tela.putpixel((x, y), (250, 240, (x * seme) % 256))
    fuori = io.BytesIO()
    tela.save(fuori, "JPEG", quality=90)
    return fuori.getvalue()


def _video(codec: str, quanti: int = 12) -> bytes:
    import av
    import numpy

    fuori = io.BytesIO()
    with av.open(fuori, "w", format="mp4") as contenitore:
        traccia = contenitore.add_stream(codec, rate=12)
        traccia.width, traccia.height, traccia.pix_fmt = 64, 48, "yuv420p"
        for quale in range(quanti):
            tela = numpy.full((48, 64, 3), (10, 20 + quale * 9, 200), dtype=numpy.uint8)
            tela[8:24, quale * 3:quale * 3 + 16] = (240, 60, 40)
            fotogramma = av.VideoFrame.from_ndarray(tela, format="rgb24")
            for pacchetto in traccia.encode(fotogramma):
                contenitore.mux(pacchetto)
        for pacchetto in traccia.encode():
            contenitore.mux(pacchetto)
    return fuori.getvalue()


def _numero(casa, relativo: str) -> str:
    radice, = casa.radici()
    return casa.aperto.elenco.attuale(radice["id"], relativo).contenuto


def _blob(casa, relativo: str) -> Path:
    return registro.percorso_contenuto(casa.cartella, _numero(casa, relativo))


def _rovina(casa, relativo: str) -> bytes:
    blob = _blob(casa, relativo)
    rotto = bytes(len(blob.read_bytes()))
    blob.write_bytes(rotto)
    return rotto


def _riparati(aperto) -> list[str]:
    rapporto = aperto.ripara.controllore.rapporto
    return list(rapporto.riparati) if rapporto is not None else []


def _chiaro(casa, relativo: str) -> bytes:
    with open(_blob(casa, relativo), "rb") as file:
        return formato.Contenuto(file, casa.aperto.chiave,
                                 numero=bytes.fromhex(_numero(casa, relativo))).tutto()


def _cerca(casa, dati: bytes, relativo: str = "s/b.jpg", *, intero: bool = True,
           impronta: str | None = None):
    return casa.archivio.cerca(impronta or _impronta(dati), len(dati),
                               [str(casa.foto / relativo)], nome=relativo, intero=intero)


def _stacca(casa) -> None:
    os.rename(casa.chiavetta, casa.base / "staccata")


@pytest.fixture
def casa_che_ripara(tmp_path):
    casa = Casa(tmp_path, ripara={"luoghi": lambda: []}, riparatore={"ogni": 0.05})
    yield casa
    casa.chiudi()


casa = servizio_di_prova.casa


def test_una_foto_si_legge_intera_dall_archivio(casa):
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    ricerca = _cerca(casa, dati)
    assert ricerca.perche == TROVATA and not ricerca.diversa
    trovata = ricerca.trovata
    assert isinstance(trovata, DallArchivio)
    assert trovata.name == "b.jpg" and trovata.suffix == ".jpg" and trovata.stem == "b"
    assert trovata.exists() and trovata.is_file() and trovata.stat().st_size == len(dati)
    assert trovata.blake2b == _impronta(dati) and trovata.dimensione == len(dati)
    assert "dall'Archivio sicuro" in str(trovata)
    letta = trovata.apri()
    assert isinstance(letta, io.BytesIO) and letta.read() == dati
    assert casa.aperto.letti_male == set() and not casa.archivio.persa(trovata.numero)


def test_un_video_si_legge_a_pezzi_e_si_salta_avanti_e_indietro(casa):
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    trovata = _cerca(casa, dati, intero=False).trovata
    with trovata.apri() as flusso:
        assert flusso.seekable() and not isinstance(flusso, io.BytesIO)
        assert flusso.read(10) == dati[:10]
        flusso.seek(formato.BLOCCO - 3)
        assert flusso.read(9) == dati[formato.BLOCCO - 3:formato.BLOCCO + 6]
        flusso.seek(-5, io.SEEK_END)
        assert flusso.read() == dati[-5:]
        assert flusso.read() == b""
        flusso.seek(2 * formato.BLOCCO + 1)
        assert flusso.tell() == 2 * formato.BLOCCO + 1
        flusso.seek(-1, io.SEEK_CUR)
        assert flusso.read(3) == dati[2 * formato.BLOCCO:2 * formato.BLOCCO + 3]
        flusso.seek(0)
        assert flusso.read() == dati
        flusso.seek(len(dati) + 100)
        assert flusso.read(4) == b""
        with pytest.raises((OSError, ValueError)):
            flusso.seek(-1)
        with pytest.raises(ValueError):
            flusso.raw.seek(-1)
        with pytest.raises(ValueError):
            flusso.raw.seek(0, 7)
    assert flusso.closed


def test_quello_che_non_c_e_non_si_trova(casa):
    _con_le_foto(casa)
    altro = _dati(77, 9)
    assert _cerca(casa, altro, "t/c.jpg").perche == NON_C_E
    dati = _dati(100, 1)
    fuori = [str(casa.base / "altrove" / "a.jpg")]
    assert casa.archivio.cerca("0" * 64, len(dati), fuori, nome="a.jpg",
                               intero=True).perche == NON_C_E
    assert casa.archivio.cerca(_impronta(dati), len(dati) + 1, fuori, nome="a.jpg",
                               intero=True).perche == NON_C_E
    assert casa.archivio.cerca(_impronta(dati), None, fuori, nome="a.jpg",
                               intero=True).trovata.apri().read() == dati


def test_con_l_archivio_chiuso_non_si_legge_niente(casa):
    _con_le_foto(casa)
    dati = _dati(100, 1)
    trovata = _cerca(casa, dati, "s/a.jpg").trovata
    assert trovata.apri().read() == dati
    assert casa.archivio.chiudi(ATTESA)
    assert _cerca(casa, dati, "s/a.jpg").perche == CHIUSO
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    assert not casa.archivio.persa(trovata.numero)


def test_un_flusso_aperto_si_ferma_quando_l_archivio_si_chiude(casa):
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    flusso = _cerca(casa, dati, intero=False).trovata.apri()
    try:
        assert flusso.read(5) == dati[:5]
        assert casa.archivio.chiudi(ATTESA)
        flusso.seek(2 * formato.BLOCCO)
        with pytest.raises(OSError):
            flusso.read(5)
    finally:
        flusso.close()


def test_una_versione_diversa_si_trova_dal_percorso_e_si_dice(casa):
    _con_le_foto(casa)
    dati = _dati(100, 1)
    ricerca = _cerca(casa, b"un'altra versione della stessa foto", "s/a.jpg")
    assert ricerca.perche == TROVATA and ricerca.diversa
    assert ricerca.trovata.diversa and ricerca.trovata.blake2b == _impronta(dati)
    assert ricerca.trovata.apri().read() == dati


def test_una_foto_dall_archivio_non_esce_dal_programma(casa):
    _con_le_foto(casa)
    trovata = _cerca(casa, _dati(100, 1), "s/a.jpg").trovata
    with pytest.raises(TypeError, match="non esce"):
        pickle.dumps(trovata)
    with pytest.raises(TypeError):
        pickle.dumps(dall_archivio.Ricerca(TROVATA, trovata))


def test_una_copia_rovinata_si_legge_lo_stesso_dalla_chiavetta_e_poi_si_ripara(
        casa_che_ripara):
    casa = casa_che_ripara
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    numero = _numero(casa, "s/b.jpg")
    _rovina(casa, "s/b.jpg")
    assert _cerca(casa, dati).trovata.apri().read() == dati
    assert numero in casa.aperto.letti_male and not casa.archivio.persa(numero)
    _finche(lambda: numero in _riparati(casa.aperto))
    assert casa.aperto.ripara.aspetta_fine(ATTESA)
    assert _chiaro(casa, "s/b.jpg") == dati


def test_un_video_rovinato_si_legge_lo_stesso_dalla_chiavetta(casa_che_ripara):
    casa = casa_che_ripara
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    numero = _numero(casa, "s/b.jpg")
    _rovina(casa, "s/b.jpg")
    with _cerca(casa, dati, intero=False).trovata.apri() as flusso:
        flusso.seek(formato.BLOCCO + 1)
        assert flusso.read(formato.BLOCCO) == dati[formato.BLOCCO + 1:2 * formato.BLOCCO + 1]
        flusso.seek(0)
        assert flusso.read() == dati
    assert numero in casa.aperto.letti_male and not casa.archivio.persa(numero)
    _finche(lambda: numero in _riparati(casa.aperto))


def test_senza_nessuna_copia_buona_non_si_inventa_niente_e_non_si_cancella_niente(
        casa_che_ripara):
    casa = casa_che_ripara
    _con_le_foto(casa)
    _stacca(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    numero = _numero(casa, "s/b.jpg")
    rotto = _rovina(casa, "s/b.jpg")
    trovata = _cerca(casa, dati).trovata
    with pytest.raises(prendi.Persa) as preso:
        trovata.apri()
    assert preso.value.codice == "persa_nell_archivio"
    assert casa.archivio.persa(numero) and numero in casa.aperto.letti_male
    with _cerca(casa, dati, intero=False).trovata.apri() as flusso:
        with pytest.raises(OSError):
            flusso.read()
    assert _blob(casa, "s/b.jpg").read_bytes() == rotto
    assert casa.aperto.elenco.contenuto(numero) is not None
    assert casa.archivio.istantanea()["persi"] == [numero]


def test_una_foto_tornata_buona_non_e_piu_persa(casa_che_ripara):
    casa = casa_che_ripara
    _con_le_foto(casa)
    dati = _dati(3 * formato.BLOCCO + 7, 2)
    numero = _numero(casa, "s/b.jpg")
    blob = _blob(casa, "s/b.jpg")
    buono = blob.read_bytes()
    _stacca(casa)
    _rovina(casa, "s/b.jpg")
    with pytest.raises(prendi.Persa):
        _cerca(casa, dati).trovata.apri()
    assert casa.archivio.persa(numero)
    blob.write_bytes(buono)
    assert _cerca(casa, dati).trovata.apri().read() == dati
    assert not casa.archivio.persa(numero)


def test_di_una_foto_cambiata_si_prende_l_ultima_versione(casa):
    _con_le_foto(casa)
    prima = _numero(casa, "s/a.jpg")
    nuova = _dati(150, 5)
    casa.metti("s/a.jpg", nuova)
    casa.archivio.copia_tutto([casa.foto])
    _finche(lambda: _numero(casa, "s/a.jpg") != prima and casa.copiato())
    ricerca = _cerca(casa, b"quella importata prima di tutte", "s/a.jpg")
    assert ricerca.perche == TROVATA and ricerca.diversa
    assert ricerca.trovata.blake2b == _impronta(nuova)
    assert ricerca.trovata.apri().read() == nuova
    vecchia = _cerca(casa, _dati(100, 1), "s/a.jpg")
    assert not vecchia.diversa and vecchia.trovata.apri().read() == _dati(100, 1)


class _ElencoFinto:

    def __init__(self, radice: Path, contenuti: dict, posti: list):
        self.radice = radice
        self.contenuti = contenuti
        self.posti = posti

    def con_impronta(self, impronta, dimensione):
        return []

    def contenuto(self, numero):
        return self.contenuti.get(numero)

    def radici(self):
        return [{"id": "r1", "percorso": str(self.radice)}]

    def storia(self, radice, resto):
        if not isinstance(self.posti, list):
            raise self.posti
        return self.posti


@pytest.mark.parametrize("ultima", [
    {"stato": "incompleto", "perche": "buchi"},
    {"stato": "buono", "perche": registro.SALVATO + "ab" * 16},
    None])
def test_dal_percorso_si_prende_l_ultima_copia_intera(tmp_path, ultima):
    buona = {"stato": "buono", "perche": None}
    posti = [SimpleNamespace(tipo="file", contenuto="vecchia"),
             SimpleNamespace(tipo="file", contenuto="nuova"),
             SimpleNamespace(tipo="tolto", contenuto=None)]
    contenuti = {"vecchia": buona, **({} if ultima is None else {"nuova": ultima})}
    elenco = _ElencoFinto(tmp_path, contenuti, posti)
    dove = [str(tmp_path / "s" / "a.jpg")]
    assert prendi.trova(elenco, "0" * 64, 10, dove) == ("vecchia", buona, True)
    elenco.contenuti.pop("vecchia")
    assert prendi.trova(elenco, "0" * 64, 10, dove) is None
    elenco.posti = ValueError("percorso strano")
    assert prendi.trova(elenco, "0" * 64, 10, dove) is None


def test_dall_impronta_si_prende_prima_la_copia_buona_e_mai_un_pezzo_salvato(tmp_path):
    chiave = chiavi.Chiave(bytes(range(32)))
    elenco = registro.Elenco.apri(tmp_path / "archivio", chiave)
    try:
        def scritto():
            return formato.scrivi_byte(io.BytesIO(), chiave, b"la foto", {"nome": "x"})

        rotta, salvata, incompleta, buona = scritto(), scritto(), scritto(), scritto()
        elenco.registra([
            registro.fatto_contenuto(rotta, "rovinato", "non_riparato", quando=1.0),
            registro.fatto_contenuto(salvata, "buono", registro.SALVATO + rotta.numero,
                                     quando=2.0),
            registro.fatto_contenuto(incompleta, "incompleto", "buchi", quando=3.0),
            registro.fatto_contenuto(buona, "riparato", "pezzi", quando=4.0),
        ])
        in_ordine = [buona.numero, incompleta.numero, rotta.numero]
        assert elenco.con_impronta(rotta.blake2b) == in_ordine
        assert elenco.con_impronta(rotta.blake2b, len(b"la foto")) == in_ordine
        assert elenco.con_impronta(rotta.blake2b, 3) == []
    finally:
        elenco.chiudi()


def test_una_copia_con_un_altra_misura_non_si_usa(tmp_path):
    chiave = chiavi.Chiave(bytes(range(32)))
    numero = formato.nuovo_numero()
    dati = _dati(3 * formato.BLOCCO + 7, 2)

    def scrivi(nome: str, contenuto: bytes):
        percorso = tmp_path / nome
        with open(percorso, "wb") as fuori:
            return percorso, formato.scrivi_byte(fuori, chiave, contenuto, {}, numero)

    giusta, scritta = scrivi("giusta", dati)
    altra, _ = scrivi("altra", _dati(2 * formato.BLOCCO + 1, 4))
    with ExitStack() as pila:
        fonti = prendi.Fonti(numero.hex(), {"testa": scritta.testa}, chiave, pila)
        fonti.aggiungi(tmp_path / "non-c-e", numero.hex(), scritta.testa)
        fonti.aggiungi(altra, numero.hex(), None)
        assert fonti.blocco(0) is None and fonti.persa
        fonti.aggiungi(giusta, numero.hex(), scritta.testa)
        assert fonti.blocco(0) == dati[:formato.BLOCCO]


def test_mentre_l_archivio_si_spegne_la_ricerca_dice_chiuso(casa, monkeypatch):
    _con_le_foto(casa)
    aperto = casa.aperto
    aperto._spento = True
    try:
        assert _cerca(casa, _dati(100, 1), "s/a.jpg").perche == CHIUSO
    finally:
        aperto._spento = False

    def guasto(*argomenti):
        raise ErroreOfficina("un altro guaio", codice="altro")

    monkeypatch.setattr(aperto, "cerca", guasto)
    with pytest.raises(ErroreOfficina, match="un altro guaio"):
        _cerca(casa, _dati(100, 1), "s/a.jpg")


def test_un_contenuto_sparito_dall_elenco_e_persa_e_non_un_guasto(casa):
    _con_le_foto(casa)
    trovata = _cerca(casa, _dati(100, 1), "s/a.jpg").trovata
    with pytest.raises(prendi.Persa):
        dataclasses.replace(trovata, numero="00" * 16).apri()


def test_mentre_l_archivio_si_apre_lo_dice(casa, monkeypatch):
    _con_le_foto(casa)
    assert casa.archivio.chiudi(ATTESA)
    visti = []
    vera = modulo.chiavi.apri

    def apri_e_guarda(*argomenti, **opzioni):
        visti.append(casa.archivio.si_apre)
        return vera(*argomenti, **opzioni)

    monkeypatch.setattr(modulo.chiavi, "apri", apri_e_guarda)
    assert not casa.archivio.si_apre
    with pytest.raises(PasswordSbagliata):
        casa.archivio.apri("sbagliata")
    assert not casa.archivio.si_apre
    casa.archivio.apri(PAROLA)
    assert visti == [True, True] and not casa.archivio.si_apre and casa.archivio.aperto


def test_il_codec_di_un_video_che_non_si_legge_piu_e_nessuno(monkeypatch):
    def chiuso(trovata):
        raise ErroreOfficina("chiuso", codice="archivio_chiuso")

    trovata = DallArchivio("00" * 16, "v.mp4", 10, "ab" * 32, False, False, chiuso)
    assert scatto._codec_di(None) is None
    assert scatto._codec_di(trovata) is None

    def guasto(percorso):
        raise ErroreOfficina("guasto")

    monkeypatch.setattr(quicktime, "codec_video", guasto)
    with pytest.raises(ErroreOfficina, match="guasto"):
        scatto._codec_di(Path("v.mp4"))


def test_se_i_pezzi_non_tornano_con_l_impronta_la_foto_e_persa():
    dati = b"abab"
    guardate = []
    fonti = SimpleNamespace(forma=SimpleNamespace(blocchi=2), blocco=lambda numero: b"ab",
                            guarda=guardate.append)
    giuste = {"dimensione": len(dati), "blake2b": _impronta(dati),
              "sha256": hashlib.sha256(dati).hexdigest()}
    assert prendi.tutto(fonti, giuste).read() == dati and guardate == []
    for sbagliata in ({"dimensione": 5}, {"blake2b": "0" * 64}, {"sha256": "0" * 64}):
        with pytest.raises(prendi.Persa):
            prendi.tutto(fonti, {**giuste, **sbagliata})
    assert guardate == [True, True, True]
    chiesti = []
    fonti.blocco = chiesti.append
    with pytest.raises(prendi.Persa):
        prendi.tutto(fonti, giuste)
    assert chiesti == [0] and guardate == [True, True, True]


def test_una_copia_che_non_va_al_suo_posto_non_lascia_niente(archivio, monkeypatch):
    monkeypatch.setattr(compatibile, "si_puo_fare", lambda: True)
    impronta = "ab" * 32
    dove = compatibile.di_passaggio(archivio.dove) / archivio.nome_copia_video(impronta)

    def e_poi_ci_si_mette_in_mezzo(originale, verso, al_passo=None):
        verso.write_bytes(b"mezza copia")
        dove.mkdir(parents=True)
        (dove / "dentro").write_bytes(b"x")

    monkeypatch.setattr(compatibile, "_ricodifica", e_poi_ci_si_mette_in_mezzo)
    assert compatibile.fai(archivio, impronta, Path("finto.mov"), passaggio=True) is None
    assert not dove.with_suffix(".parziale.mp4").exists()


def test_la_foto_si_apre_come_immagine_anche_dall_archivio(casa):
    foto = _jpeg()
    casa.metti("s/foto.jpg", foto)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    trovata = _cerca(casa, foto, "s/foto.jpg").trovata
    immagine = lettura.copia_di_lavoro(trovata, 32)
    assert max(immagine.size) == 32
    assert lettura.intestazione(trovata).size == (96, 64)


def test_una_foto_persa_non_diventa_un_file_non_leggibile(casa_che_ripara):
    casa = casa_che_ripara
    foto = _jpeg()
    casa.metti("s/foto.jpg", foto)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    _rovina(casa, "s/foto.jpg")
    with pytest.raises(prendi.Persa):
        lettura.intestazione(_cerca(casa, foto, "s/foto.jpg").trovata)


@SENZA_CODIFICATORE
def test_un_video_dall_archivio_si_legge_col_decodificatore(casa):
    filmato = _video("libx264")
    casa.metti("v/giro.mp4", filmato)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    trovata = _cerca(casa, filmato, "v/giro.mp4", intero=False).trovata
    assert quicktime.codec_video(trovata) == "avc1"
    assert fotogrammi.misure_dal_decodificatore(trovata) == (64, 48)


def test_le_foto_arrivano_dall_archivio_solo_da_quello_vero_e_aperto(monkeypatch, tmp_path):
    from officina.archivio import accesso
    from officina.impostazioni import FINTO, REALE

    aperto = SimpleNamespace(dove=SimpleNamespace(nome=FINTO))
    monkeypatch.setattr(accesso, "aperto", lambda: aperto)
    acceso = SimpleNamespace(aperto=True, si_apre=False)
    monkeypatch.setattr(modulo, "attuale", lambda: acceso)
    assert archivio_sicuro.per_le_foto() == (SENZA_ARCHIVIO, None)

    def nessuno():
        raise ErroreOfficina("nessun archivio aperto")

    monkeypatch.setattr(accesso, "aperto", nessuno)
    assert archivio_sicuro.per_le_foto() == (SENZA_ARCHIVIO, None)
    aperto.dove.nome = REALE
    monkeypatch.setattr(accesso, "aperto", lambda: aperto)
    servizio = SimpleNamespace(aperto=True, si_apre=False)
    monkeypatch.setattr(modulo, "attuale", lambda: servizio)
    assert archivio_sicuro.per_le_foto() == (TROVATA, servizio)
    servizio.aperto, servizio.si_apre = False, True
    assert archivio_sicuro.per_le_foto() == (SI_APRE, None)
    servizio.si_apre = False
    monkeypatch.setattr(archivio_sicuro, "c_e", lambda posizione: True)
    assert archivio_sicuro.per_le_foto() == (CHIUSO, None)
    monkeypatch.setattr(modulo, "attuale", lambda: None)
    assert archivio_sicuro.per_le_foto() == (CHIUSO, None)
    monkeypatch.setattr(archivio_sicuro, "c_e", lambda posizione: False)
    assert archivio_sicuro.per_le_foto() == (SENZA_ARCHIVIO, None)

    def rotto(posizione):
        raise OSError("il disco non risponde")

    monkeypatch.setattr(archivio_sicuro, "c_e", rotto)
    assert archivio_sicuro.per_le_foto() == (CHIUSO, None)


def test_le_copie_di_passaggio_si_buttano_e_il_resto_resta(tmp_path):
    dove = SimpleNamespace(miniature=tmp_path / "miniature")
    cartella = compatibile.di_passaggio(dove)
    (cartella / "ab").mkdir(parents=True)
    (cartella / "ab" / "uno.mp4").write_bytes(b"1")
    (cartella / "ab" / "uno.parziale.mp4").write_bytes(b"2")
    (cartella / "cd").mkdir()
    (cartella / "cd" / "due.mp4").write_bytes(b"3")
    (cartella / "cd" / "appunti.txt").write_bytes(b"resta")
    fuori = tmp_path / "fuori.mp4"
    fuori.write_bytes(b"non e' di passaggio")
    (cartella / "cd" / "collegato.mp4").symlink_to(fuori)
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    (altrove / "tiene.mp4").write_bytes(b"non si tocca")
    (cartella / "gh").symlink_to(altrove, target_is_directory=True)
    vicino = tmp_path / "miniature" / "ef"
    vicino.mkdir()
    (vicino / "normale.mp4").write_bytes(b"cache vera")
    assert compatibile.butta_quelle_di_passaggio(dove) == 3
    assert not (cartella / "ab").exists()
    assert sorted(voce.name for voce in (cartella / "cd").iterdir()) == [
        "appunti.txt", "collegato.mp4"]
    assert fuori.read_bytes() == b"non e' di passaggio"
    assert (altrove / "tiene.mp4").read_bytes() == b"non si tocca"
    assert (vicino / "normale.mp4").read_bytes() == b"cache vera"
    assert compatibile.butta_quelle_di_passaggio(SimpleNamespace(
        miniature=tmp_path / "non-c-e")) == 0


def test_buttare_le_copie_non_ferma_mai_l_archivio(monkeypatch, tmp_path):
    dove = SimpleNamespace(miniature=tmp_path)
    (compatibile.di_passaggio(dove) / "ab").mkdir(parents=True)
    (compatibile.di_passaggio(dove) / "ab" / "uno.mp4").write_bytes(b"1")
    assert archivio_sicuro.butta_le_copie_di_passaggio(dove) == 1

    def guasto(dove):
        raise RuntimeError("si è rotto qualcosa")

    monkeypatch.setattr(compatibile, "butta_quelle_di_passaggio", guasto)
    assert archivio_sicuro.butta_le_copie_di_passaggio(dove) == 0


def test_chiudere_l_archivio_e_aprirlo_butta_le_copie_di_passaggio(monkeypatch, tmp_path):
    buttate = []
    monkeypatch.setattr(archivio_sicuro, "butta_le_copie_di_passaggio", buttate.append)
    posizione = SimpleNamespace(radice=tmp_path / "vero", nome="vero",
                                miniature=tmp_path / "vero" / "miniature")
    collegamento = archivio_sicuro.Collegamento(posizione)
    assert collegamento.chiudi(ATTESA)
    assert buttate == [posizione]
    servizio = SimpleNamespace(aperto=False, si_apre=False, si_chiude=False,
                               ha_qualcosa=False,
                               chiudi=lambda aspetta: buttate.append("chiuso") or True)
    collegamento = archivio_sicuro.Collegamento(posizione)
    collegamento._servizio = servizio
    monkeypatch.setattr(modulo, "attuale", lambda: servizio)
    tolto = []
    monkeypatch.setattr(modulo, "imposta", tolto.append)
    assert collegamento.chiudi(ATTESA)
    assert buttate == [posizione, "chiuso", posizione] and tolto == [None]
    del buttate[1:]
    programma = SimpleNamespace(_il_sicuro=lambda: SimpleNamespace(
        posizione=posizione, apri_in_sottofondo=lambda password: buttate.append(password)))
    Programma._apri_l_archivio_sicuro_in_sottofondo(programma, "parola")
    assert buttate == [posizione, posizione, "parola"]


class _SicuroFinto:

    def __init__(self, giusta: str, aperto: bool = False):
        self.giusta = giusta
        self.aperto = aperto
        self.provate: list = []
        self.servizio = SimpleNamespace(problemi=["un problema di prima"])

    def guarda(self) -> str:
        return archivio_sicuro.APERTO if self.aperto else archivio_sicuro.CHIUSO

    def apri_con_la_password(self, password, del_forziere):
        self.provate.append((password, del_forziere))
        if password != self.giusta:
            raise PasswordSbagliata("La password non è giusta.")
        self.aperto = True
        return ["forziere_corta"]


def _programma(sicuro):
    return SimpleNamespace(_il_sicuro=lambda: sicuro,
                           _parola_del_forziere=lambda: "del forziere")


@pytest.fixture
def freno_pulito():
    tentativi.freno.dimentica_tutti()
    yield
    tentativi.freno.dimentica_tutti()


def test_la_password_giusta_apre_e_racconta_i_problemi(freno_pulito):
    sicuro = _SicuroFinto(PAROLA)
    assert Programma.apri_l_archivio_sicuro(_programma(sicuro), PAROLA) == {
        "aperto": True, "problemi": ["forziere_corta"]}
    assert sicuro.provate == [(PAROLA, "del forziere")]


def test_dopo_troppe_password_sbagliate_si_aspetta(freno_pulito):
    sicuro = _SicuroFinto(PAROLA)
    programma = _programma(sicuro)
    for _ in range(tentativi.LIBERI):
        with pytest.raises(PasswordSbagliata):
            Programma.apri_l_archivio_sicuro(programma, "sbagliata")
    with pytest.raises(ErroreOfficina) as preso:
        Programma.apri_l_archivio_sicuro(programma, PAROLA)
    assert preso.value.codice == "troppi_tentativi"
    assert len(sicuro.provate) == tentativi.LIBERI and not sicuro.aperto


def test_il_portatile_ha_il_suo_freno(freno_pulito):
    sicuro = _SicuroFinto(PAROLA)
    programma = _programma(sicuro)
    segno = schermo.segna_dal_portatile(True)
    try:
        for _ in range(tentativi.LIBERI):
            with pytest.raises(PasswordSbagliata):
                Programma.apri_l_archivio_sicuro(programma, "sbagliata")
        assert tentativi.freno.da_aspettare("portatile") > 0
    finally:
        schermo.smetti(segno)
    assert tentativi.freno.da_aspettare("qui") == 0
    assert Programma.apri_l_archivio_sicuro(programma, PAROLA)["aperto"]


def test_mentre_si_controlla_un_altra_password_si_dice_di_aspettare(freno_pulito):
    sicuro = _SicuroFinto(PAROLA)
    assert tentativi.freno._una_alla_volta.acquire(blocking=False)
    try:
        with pytest.raises(ErroreOfficina) as preso:
            Programma.apri_l_archivio_sicuro(_programma(sicuro), PAROLA)
    finally:
        tentativi.freno._una_alla_volta.release()
    assert preso.value.codice == "occupato" and sicuro.provate == []


def test_se_e_gia_aperto_non_si_tocca_il_freno(freno_pulito):
    for _ in range(tentativi.LIBERI - 1):
        tentativi.freno.prova("qui", lambda: False)
    sicuro = _SicuroFinto(PAROLA, aperto=True)
    assert Programma.apri_l_archivio_sicuro(_programma(sicuro), "qualsiasi") == {
        "aperto": True, "problemi": ["un problema di prima"]}
    assert sicuro.provate == []
    tentativi.freno.prova("qui", lambda: False)
    assert tentativi.freno.da_aspettare("qui") > 0


@pytest.mark.parametrize("strana", [None, 123, ["una", "lista"], {"a": 1}])
def test_una_password_che_non_e_testo_vale_come_vuota(freno_pulito, strana):
    sicuro = _SicuroFinto(PAROLA)
    with pytest.raises(PasswordSbagliata):
        Programma.apri_l_archivio_sicuro(_programma(sicuro), strana)
    assert sicuro.provate == [("", "del forziere")]


def test_il_ponte_trasforma_la_password_sbagliata_in_un_messaggio(freno_pulito):
    from officina.programma.ponti import PontePrincipale

    sicuro = _SicuroFinto(PAROLA)
    programma = SimpleNamespace(_lucchetto=threading.RLock(), apri_l_archivio_sicuro=(
        lambda password: Programma.apri_l_archivio_sicuro(_programma(sicuro), password)))
    programma.fai = lambda azione: Programma.fai(programma, azione)
    ponte = PontePrincipale(programma)
    assert ponte.apri_l_archivio_sicuro("sbagliata") == {
        "errore": "La password non è giusta."}
    assert ponte.apri_l_archivio_sicuro(PAROLA) == {"aperto": True,
                                                    "problemi": ["forziere_corta"]}


def test_dal_portatile_la_password_arriva_al_programma_del_fisso(portatile, monkeypatch):
    ricevute = []

    class Finto:
        def apri_l_archivio_sicuro(self, password):
            ricevute.append((password, schermo.dal_portatile()))
            return {"aperto": True, "problemi": []}

    monkeypatch.setattr(comune, "programma_di_qui", Finto())
    assert portatile.post("/api/programma/apri_l_archivio_sicuro",
                          json=[PAROLA]).json() == {"aperto": True, "problemi": []}
    assert ricevute == [(PAROLA, True)]
    assert portatile.post("/api/programma/apri_l_archivio_sicuro",
                          json=[]).status_code == 400
    assert ricevute == [(PAROLA, True)]


def test_il_pezzo_chiesto_si_legge_come_dice_la_regola():
    pezzo = scatto.il_pezzo_chiesto
    assert pezzo(None, 100) is None
    assert pezzo("", 100) is None
    assert pezzo("bytes=0-9", 100) == (0, 9)
    assert pezzo("BYTES=10-", 100) == (10, 99)
    assert pezzo(" bytes=10-500 ", 100) == (10, 99)
    assert pezzo("bytes=-30", 100) == (70, 99)
    assert pezzo("bytes=-300", 100) == (0, 99)
    assert pezzo("bytes=99-99", 100) == (99, 99)
    assert pezzo("bytes=100-", 100) is False
    assert pezzo("bytes=-0", 100) is False
    assert pezzo("bytes=0-", 0) is False
    assert pezzo("bytes=-5", 0) is False
    assert pezzo("bytes=5-3", 100) is None
    assert pezzo("bytes=-", 100) is None
    assert pezzo("bytes=0-1,5-6", 100) is None
    assert pezzo("righe=0-1", 100) is None
    assert pezzo("bytes=a-b", 100) is None
    assert pezzo("bytes=" + "9" * 30 + "-", 100) is None
    assert pezzo("bytes=0-" + "9" * 4400, 100) is None
    assert pezzo("bytes=١-٢", 100) is None


def test_i_pezzi_si_fermano_se_la_lettura_si_rompe():
    class Rotto(io.BytesIO):
        def read(self, quanti=-1):
            if self.tell() >= 4:
                raise OSError(5, "rovinato")
            return super().read(min(quanti, 4))

    lettore = Rotto(b"0123456789")
    assert list(scatto._a_pezzi(lettore, 0, 10)) == [b"0123"]
    assert lettore.closed
    lettore = io.BytesIO(b"0123456789")
    assert b"".join(scatto._a_pezzi(lettore, 3, 4)) == b"3456"
    assert lettore.closed
    lettore = io.BytesIO(b"012")
    assert b"".join(scatto._a_pezzi(lettore, 1, 50)) == b"12"


class _Situazione:

    def __init__(self, casa):
        self.casa = casa
        self.forzata: str | None = None

    def per_le_foto(self):
        if self.forzata is not None:
            return self.forzata, None
        if self.casa.archivio.aperto:
            return TROVATA, self.casa.archivio
        return CHIUSO, None


def _metti_nel_database(archivio, genere: str, dati: bytes, percorso: Path,
                        formato_file: str) -> tuple[int, int]:
    with archivio.scrittura() as connessione:
        riga = connessione.execute(
            "SELECT id, scatto_id FROM file_media WHERE genere = 'immagine' "
            "AND ruolo = 'principale' AND scatto_id IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()
        connessione.execute(
            "UPDATE file_media SET impronta = ?, dimensione = ?, genere = ?, formato = ?, "
            "miniatura = NULL WHERE id = ?",
            (_impronta(dati), len(dati), genere, formato_file, riga["id"]))
        connessione.execute("UPDATE scatti SET genere = ? WHERE id = ?",
                            ("video" if genere == "video" else "foto", riga["scatto_id"]))
        connessione.execute("DELETE FROM percorsi WHERE file_id = ?", (riga["id"],))
        connessione.execute(
            "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
            "VALUES (?, ?, ?, 0, '2026-01-01T00:00:00')",
            (riga["id"], str(percorso), percorso.name))
    return riga["id"], riga["scatto_id"]


def _prepara(tmp_path, archivio_pieno, monkeypatch, relativo: str, dati: bytes,
             genere: str, formato_file: str, **cambi):
    base = tmp_path / "casa"
    base.mkdir()
    casa = Casa(base, **cambi)
    originale = casa.metti(relativo, dati)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    originale.unlink()
    file_id, scatto_id = _metti_nel_database(archivio_pieno, genere, dati, originale,
                                             formato_file)
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    monkeypatch.setattr(modulo, "attuale", lambda: casa.archivio)
    from officina.web.server import app

    return SimpleNamespace(casa=casa, situazione=situazione, file_id=file_id,
                           scatto_id=scatto_id, dati=dati, originale=originale,
                           relativo=relativo, archivio=archivio_pieno,
                           cliente=TestClient(app, client=("127.0.0.1", 51000)))


@pytest.fixture
def foto_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "s/foto.jpg", _jpeg(),
                      "immagine", "jpeg", ripara={"luoghi": lambda: []},
                      riparatore={"ogni": 0.05})
    yield pronta
    pronta.casa.chiudi()


def _pagina(pronta) -> str:
    risposta = pronta.cliente.get(f"/scatto/{pronta.scatto_id}",
                                  headers={"accept": "text/html"})
    assert risposta.status_code == 200
    return risposta.text


def _stato(pronta) -> dict:
    return pronta.cliente.get(f"/api/dall-archivio/{pronta.file_id}").json()


def test_la_foto_aperta_arriva_dall_archivio_e_non_si_tiene(foto_nell_archivio):
    pronta = foto_nell_archivio
    risposta = pronta.cliente.get(f"/immagine/{pronta.file_id}")
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store"
    assert "etag" not in risposta.headers
    assert Image.open(io.BytesIO(risposta.content)).size == (96, 64)
    piccola = pronta.cliente.get(f"/immagine/{pronta.file_id}?lato=48")
    assert max(Image.open(io.BytesIO(piccola.content)).size) == 48
    assert piccola.headers["cache-control"] == "no-store"
    assert not pronta.originale.exists()


def test_l_originale_dall_archivio_arriva_intero_e_a_pezzi(foto_nell_archivio):
    pronta = foto_nell_archivio
    dati, dove = pronta.dati, f"/originale/{pronta.file_id}"
    intero = pronta.cliente.get(dove)
    assert intero.status_code == 200 and intero.content == dati
    assert intero.headers["cache-control"] == "no-store"
    assert intero.headers["accept-ranges"] == "bytes"
    assert intero.headers["content-length"] == str(len(dati))
    assert "etag" not in intero.headers
    pezzo = pronta.cliente.get(dove, headers={"range": "bytes=10-99"})
    assert pezzo.status_code == 206 and pezzo.content == dati[10:100]
    assert pezzo.headers["content-range"] == f"bytes 10-99/{len(dati)}"
    assert pezzo.headers["content-length"] == "90"
    coda = pronta.cliente.get(dove, headers={"range": "bytes=-50"})
    assert coda.status_code == 206 and coda.content == dati[-50:]
    oltre = pronta.cliente.get(dove, headers={"range": f"bytes={len(dati)}-"})
    assert oltre.status_code == 416 and oltre.content == b""
    assert oltre.headers["content-range"] == f"bytes */{len(dati)}"
    for strano in ("bytes=0-1,5-6", "bytes=5-3", "bytes=" + "9" * 30 + "-"):
        tutto = pronta.cliente.get(dove, headers={"range": strano})
        assert tutto.status_code == 200 and tutto.content == dati
    sotto = pronta.cliente.get(dove + "?sotto=1")
    assert sotto.status_code == 200 and sotto.content == dati


def test_la_pagina_dice_che_la_foto_arriva_dall_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    assert _stato(pronta) == {"perche": TROVATA, "diversa": False, "persa": False}
    pagina = _pagina(pronta)
    assert FOTO in pagina
    assert PILLOLA in pagina and "Dall'Archivio sicuro</span>" in pagina
    assert f'data-dall-archivio="{pronta.file_id}"' in pagina
    assert 'id="foto-persa" role="alert" hidden>' in pagina
    assert "dall'Archivio sicuro</span>" in pagina
    assert "versione diversa" not in pagina
    assert CHIUSA not in pagina and SI_STA_APRENDO not in pagina


def test_con_l_originale_sul_disco_la_pagina_non_parla_dell_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    pronta.originale.write_bytes(pronta.dati)
    assert _stato(pronta) == {"perche": None, "diversa": False, "persa": False}
    pagina = _pagina(pronta)
    assert PILLOLA not in pagina and "data-dall-archivio=" not in pagina
    assert PERSA not in pagina
    risposta = pronta.cliente.get(f"/immagine/{pronta.file_id}")
    assert risposta.status_code == 200 and "etag" in risposta.headers


def test_con_l_archivio_chiuso_si_chiede_la_password(foto_nell_archivio):
    pronta = foto_nell_archivio
    assert pronta.casa.archivio.chiudi(ATTESA)
    assert _stato(pronta) == {"perche": CHIUSO, "diversa": False, "persa": False}
    pagina = _pagina(pronta)
    assert CHIUSA in pagina
    assert "scrivi la password per vederla" in pagina
    modulo_html = pagina.split('<form id="modulo-archivio-sicuro"', 1)[1].split("</form>")[0]
    assert 'method="post"' in modulo_html and "data-solo-nel-programma hidden" in modulo_html
    assert 'type="password"' in modulo_html
    assert 'autocomplete="current-password"' in modulo_html
    assert FOTO not in pagina and PILLOLA not in pagina
    assert pronta.cliente.get(f"/immagine/{pronta.file_id}").status_code == 404
    assert pronta.cliente.get(f"/originale/{pronta.file_id}").status_code == 404
    assert pronta.cliente.get(f"/miniatura/{pronta.file_id}").status_code == 404


def test_mentre_l_archivio_si_apre_la_pagina_aspetta(foto_nell_archivio):
    pronta = foto_nell_archivio
    pronta.situazione.forzata = SI_APRE
    assert _stato(pronta)["perche"] == SI_APRE
    pagina = _pagina(pronta)
    assert SI_STA_APRENDO in pagina and f'data-file="{pronta.file_id}"' in pagina
    assert '<form id="modulo-archivio-sicuro"' not in pagina
    assert FOTO not in pagina


def test_senza_archivio_sicuro_la_pagina_resta_com_era(foto_nell_archivio):
    pronta = foto_nell_archivio
    pronta.situazione.forzata = SENZA_ARCHIVIO
    assert _stato(pronta)["perche"] == SENZA_ARCHIVIO
    pagina = _pagina(pronta)
    assert CHIUSA not in pagina and SI_STA_APRENDO not in pagina
    assert PERSA not in pagina and PILLOLA not in pagina


def test_una_versione_diversa_si_mostra_e_si_dice(foto_nell_archivio):
    pronta = foto_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (_impronta(b"la versione importata"), pronta.file_id))
    assert _stato(pronta) == {"perche": TROVATA, "diversa": True, "persa": False}
    pagina = _pagina(pronta)
    assert "È una versione diversa da quella importata: l'IA non la usa." in pagina
    assert pronta.cliente.get(f"/immagine/{pronta.file_id}").status_code == 200
    with pronta.archivio.lettura() as connessione:
        riga = file_media.per_id(connessione, pronta.file_id)
    assert miniature.per_file(pronta.archivio, riga, anche_dall_archivio=True) is None


def test_la_miniatura_si_fa_anche_dall_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    piccola = pronta.cliente.get(f"/miniatura/{pronta.file_id}")
    assert piccola.status_code == 200 and Image.open(io.BytesIO(piccola.content)).size
    with pronta.archivio.lettura() as connessione:
        riga = file_media.per_id(connessione, pronta.file_id)
    assert miniature.per_file(pronta.archivio, riga) is None
    assert miniature.per_file(pronta.archivio, riga, anche_dall_archivio=True)
    with pronta.archivio.lettura() as connessione:
        trovata = file_media.percorso_migliore(connessione, pronta.file_id,
                                               anche_dall_archivio=True)
        assert file_media.percorso_migliore(connessione, pronta.file_id) is None
    assert isinstance(trovata, DallArchivio) and trovata.intero


def test_una_foto_persa_mostra_l_allarme_rosso_e_non_cancella_niente(foto_nell_archivio):
    pronta = foto_nell_archivio
    casa = pronta.casa
    _stacca(casa)
    rotto = _rovina(casa, pronta.relativo)
    numero = _numero(casa, pronta.relativo)
    assert pronta.cliente.get(f"/immagine/{pronta.file_id}").status_code == 400
    assert pronta.cliente.get(f"/miniatura/{pronta.file_id}").status_code == 404
    assert _stato(pronta) == {"perche": TROVATA, "diversa": False, "persa": True}
    pagina = _pagina(pronta)
    assert 'id="foto-persa" role="alert" >' in pagina
    assert "Questa foto, nell'Archivio sicuro, è rovinata." in pagina
    assert FOTO not in pagina and PILLOLA not in pagina
    assert _blob(casa, pronta.relativo).read_bytes() == rotto
    assert casa.aperto.elenco.contenuto(numero) is not None
    assert numero in casa.archivio.istantanea()["persi"]


def test_una_foto_rovinata_si_vede_lo_stesso_grazie_alla_chiavetta(foto_nell_archivio):
    pronta = foto_nell_archivio
    casa = pronta.casa
    numero = _numero(casa, pronta.relativo)
    _rovina(casa, pronta.relativo)
    risposta = pronta.cliente.get(f"/immagine/{pronta.file_id}")
    assert risposta.status_code == 200
    assert _stato(pronta)["persa"] is False
    assert numero in casa.aperto.letti_male
    _finche(lambda: numero in _riparati(casa.aperto))
    assert casa.aperto.ripara.aspetta_fine(ATTESA)
    assert _chiaro(casa, pronta.relativo) == pronta.dati


def test_una_foto_senza_impronta_non_si_cerca_nell_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = '' WHERE id = ?",
                            (pronta.file_id,))
    assert _stato(pronta)["perche"] == NON_C_E


def test_un_ritocco_che_manca_non_fa_vedere_l_archivio(foto_nell_archivio):
    pronta = foto_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, impronta_copia, "
            "percorso_base, impronta_base, base_e) VALUES (?, 'fatta', ?, ?, ?, ?, "
            "'originale')",
            (pronta.file_id, str(pronta.casa.base / "non-c-e.jpg"), "cd" * 32,
             str(pronta.originale), _impronta(pronta.dati)))
    assert _stato(pronta)["perche"] is None
    pronta.originale.write_bytes(pronta.dati)
    assert pronta.casa.archivio.chiudi(ATTESA)
    assert _stato(pronta)["perche"] is None
    assert CHIUSA not in _pagina(pronta)


@pytest.fixture
def video_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "v/giro.mp4",
                      _video("libx265"), "video", "mp4")
    yield pronta
    pronta.casa.chiudi()


@SENZA_CODIFICATORE
def test_un_video_dall_archivio_ha_il_fotogramma_e_la_copia_di_passaggio(
        video_nell_archivio, monkeypatch):
    pronta = video_nell_archivio
    poster = pronta.cliente.get(f"/immagine/{pronta.file_id}")
    assert poster.status_code == 200 and poster.headers["cache-control"] == "no-store"
    assert "etag" not in poster.headers
    assert not any(_impronta(pronta.dati) in chiave for chiave in consegna.gia_pronte._dati)
    atteso = scatto.segno("fotogramma", _impronta(pronta.dati), 0, 0,
                          consegna.lato_per_guardare(None))
    di_nuovo = pronta.cliente.get(f"/immagine/{pronta.file_id}",
                                  headers={"if-none-match": atteso})
    assert di_nuovo.status_code == 200 and di_nuovo.content == poster.content
    pagina = _pagina(pronta)
    assert 'id="live-non-si-legge"' in pagina
    assert "Si butta da sola quando chiudi il programma." in pagina
    pezzo = pronta.cliente.get(f"/originale/{pronta.file_id}",
                               headers={"range": "bytes=0-99"})
    assert pezzo.status_code == 206 and pezzo.content == pronta.dati[:100]
    monkeypatch.setattr(comune.lavoro_copia_video, "parti",
                        lambda fare, nome: fare())
    risposta = pronta.cliente.post(f"/scatto/copia-video/{pronta.file_id}",
                                   follow_redirects=False)
    assert risposta.status_code == 303
    dove = pronta.archivio.dove
    fatta = compatibile.gia_fatta(pronta.archivio, _impronta(pronta.dati), passaggio=True)
    assert fatta is not None and fatta.is_relative_to(compatibile.di_passaggio(dove))
    assert compatibile.gia_fatta(pronta.archivio, _impronta(pronta.dati)) is None
    copia = pronta.cliente.get(f"/originale/{pronta.file_id}")
    assert copia.status_code == 200 and copia.headers["cache-control"] == "no-store"
    assert copia.content == fatta.read_bytes()
    assert quicktime.il_browser_lo_apre(quicktime.codec_video(fatta))
    assert pronta.casa.archivio.chiudi(ATTESA)
    archivio_sicuro.butta_le_copie_di_passaggio(dove)
    assert not fatta.exists()


@SENZA_CODIFICATORE
def test_se_l_archivio_si_chiude_durante_la_copia_la_copia_si_butta(video_nell_archivio,
                                                                     monkeypatch):
    pronta = video_nell_archivio
    with pronta.archivio.lettura() as connessione:
        percorso, _ = file_media.da_mostrare(connessione, pronta.file_id,
                                             anche_dall_archivio=True)
    assert isinstance(percorso, DallArchivio) and not percorso.intero
    vera = compatibile.fai

    def e_poi_si_chiude(*argomenti, **opzioni):
        fatta = vera(*argomenti, **opzioni)
        pronta.situazione.forzata = CHIUSO
        return fatta

    monkeypatch.setattr(compatibile, "fai", e_poi_si_chiude)
    with pytest.raises(ErroreOfficina, match="si è chiuso"):
        scatto._fai_la_copia(pronta.archivio, percorso.blake2b, percorso, 1000, True)
    assert compatibile.gia_fatta(pronta.archivio, percorso.blake2b, passaggio=True) is None


@SENZA_CODIFICATORE
def test_la_copia_di_una_versione_diversa_prende_il_nome_dalla_sua_impronta(
        video_nell_archivio, monkeypatch):
    pronta = video_nell_archivio
    importata = _impronta(b"il video importato")
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (importata, pronta.file_id))
    assert _stato(pronta)["diversa"]
    monkeypatch.setattr(comune.lavoro_copia_video, "parti",
                        lambda fare, nome: fare())
    risposta = pronta.cliente.post(f"/scatto/copia-video/{pronta.file_id}",
                                   follow_redirects=False)
    assert risposta.status_code == 303
    assert compatibile.gia_fatta(pronta.archivio, _impronta(pronta.dati), passaggio=True)
    assert compatibile.gia_fatta(pronta.archivio, importata, passaggio=True) is None
