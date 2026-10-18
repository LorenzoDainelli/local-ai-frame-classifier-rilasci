from __future__ import annotations

import errno
import os
import random
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, dentro, elenco, formato, metadati, sottofondo
from officina.sicuro.copia import Fermato
from officina.sicuro.dentro import Risposta, Verifica, Verificatore
from prove.test_sicuro_copia import Banco, _dati, _settori_rotti

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")

ATTESA = 20.0


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@contextmanager
def _sveglio():
    yield True


def _verificatore(banco: Banco, **opzioni) -> Verificatore:
    opzioni.setdefault("apri", banco.apri)
    return Verificatore(banco.archivio, banco.elenco, banco.chiave, **opzioni)


def _rovina_blocco(banco: Banco, numero: str, blocchi, tutto=True) -> None:
    blob = banco.blob(numero)
    with open(blob, "rb") as file:
        forma = formato.Contenuto(file, banco.chiave,
                                  numero=bytes.fromhex(numero)).forma
    guasto = bytearray(blob.read_bytes())
    for blocco in blocchi:
        inizio = forma.dove_blocco(blocco)
        fine = inizio + (forma.lunghezza(blocco) + formato.ETICHETTA if tutto else 40)
        for dove in range(inizio, fine):
            guasto[dove] ^= 0x5A
    blob.write_bytes(bytes(guasto))


def _aperti(banco: Banco, percorso) -> int:
    nome = os.fspath(percorso)
    return sum(1 for aperto, _ in banco.apri.aperti if aperto == nome)


def _blob_aperti(banco: Banco) -> list[str]:
    return [Path(nome).stem for nome, _ in banco.apri.aperti if nome.endswith(".ofs")]


def _pieno(banco: Banco) -> dict[str, bytes]:
    fatti = {
        "a.jpg": _dati(70_001, 1),
        "2001/mare/IMG_0001.jpg": _dati(0, 2),
        "2001/mare/IMG_0002.jpg": _dati(1, 3),
        "2001/mare/IMG_0003.JPG": _dati(formato.BLOCCO - 1, 4),
        "2001/montagna/neve.png": _dati(formato.BLOCCO, 5),
        "2002/Natale è qui/video.mov": _dati(3 * formato.BLOCCO + 17, 6),
        "2002/Natale è qui/.nascosto": _dati(12, 7),
        "cartella con spazi/foto ✨.heic": _dati(4096, 8),
    }
    for relativo, dati in fatti.items():
        banco.metti(relativo, dati)
    (banco.sorgente / "vuota").mkdir()
    banco.giro()
    return fatti


def _gemelli(banco: Banco, dati: bytes) -> tuple[str, str]:
    banco.metti("a.jpg", dati)
    banco.giro()
    primo = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(primo, "rovinato")])
    banco.giro()
    secondo = banco.posto("a.jpg").contenuto
    assert secondo != primo
    banco.elenco.registra([elenco.fatto_stato(primo, "riparato")])
    banco.apri.aperti.clear()
    return primo, secondo


def _cloud(monkeypatch, *percorsi) -> None:
    nuvole = {os.lstat(percorso).st_ino for percorso in percorsi}
    monkeypatch.setattr(metadati, "solo_nel_cloud",
                        lambda stato: stato.st_ino in nuvole)


def test_una_cartella_copiata_e_tutta_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde and risposta.finito
    assert risposta.file == risposta.dentro == len(fatti)
    assert risposta.byte == sum(len(dati) for dati in fatti.values())
    assert risposta.byte_mancanti == 0
    assert risposta.rossi == {} and risposta.mancano == 0
    assert risposta.frase() == f"Sì, è tutto dentro: {len(fatti)} file."
    assert risposta.radici == ["r1"]
    assert risposta.cartella == os.path.abspath(banco.sorgente)


def test_si_contano_anche_le_cartelle(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.cartelle == 7


def test_una_cartella_vuota_ha_la_sua_frase(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (tmp_path / "nulla").mkdir()
    risposta = _verificatore(banco).verifica(tmp_path / "nulla")
    assert risposta.verde
    assert risposta.frase() == "Sì: in questa cartella non ci sono file."


def test_un_file_arrivato_dopo_la_copia_manca(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("2003/nuova.jpg", _dati(5555, 99))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert not risposta.verde
    assert risposta.rossi == {"manca": 1}
    assert risposta.esempi["manca"] == ["2003/nuova.jpg"]
    assert risposta.byte_mancanti == 5555
    assert risposta.frase() == "No, manca 1 file su 9."


def test_piu_file_mancanti_si_dicono_al_plurale(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("n1.jpg", _dati(10, 91))
    banco.metti("n2.jpg", _dati(11, 92))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.frase() == "No, mancano 2 file su 10."


def test_un_file_cambiato_dopo_la_copia_manca(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    banco.metti("a.jpg", _dati(9000, 2))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"manca": 1}
    assert risposta.esempi["manca"] == ["a.jpg"]


def test_un_solo_byte_diverso_basta_a_dire_che_manca(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 5, 1)
    banco.metti("a.jpg", dati)
    banco.giro()
    cambiato = bytearray(dati)
    cambiato[-1] ^= 1
    banco.metti("a.jpg", bytes(cambiato))
    assert _verificatore(banco).verifica(banco.sorgente).rossi == {"manca": 1}


def test_un_file_cambiato_ma_uguale_a_un_altro_e_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.metti("b.jpg", _dati(9000, 2))
    banco.giro()
    banco.metti("a.jpg", _dati(9000, 2))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde and risposta.dentro == 2


def test_una_cartella_qualsiasi_con_copie_rinominate_e_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    altrove = tmp_path / "chiavetta vecchia"
    for indice, dati in enumerate(fatti.values()):
        (altrove / f"sotto{indice % 3}").mkdir(parents=True, exist_ok=True)
        (altrove / f"sotto{indice % 3}" / f"copia {indice}.bin").write_bytes(dati)
    risposta = _verificatore(banco).verifica(altrove)
    assert risposta.verde and risposta.dentro == len(fatti)
    assert risposta.radici == []


def test_in_una_cartella_qualsiasi_si_dice_solo_quello_che_manca(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    (altrove / "vecchia.jpg").write_bytes(fatti["a.jpg"])
    (altrove / "nuova.jpg").write_bytes(_dati(70_001, 77))
    (altrove / "piccola.jpg").write_bytes(_dati(3, 78))
    risposta = _verificatore(banco).verifica(altrove)
    assert risposta.dentro == 1
    assert sorted(risposta.esempi["manca"]) == ["nuova.jpg", "piccola.jpg"]


def test_un_file_di_una_misura_mai_vista_non_si_legge_nemmeno(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    nuova = banco.metti("nuova.jpg", _dati(123_457, 5))
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.esempi["manca"] == ["nuova.jpg"]
    assert _aperti(banco, nuova) == 0


def test_un_file_gia_copiato_si_legge_una_volta_sola(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(5 * formato.BLOCCO, 1))
    banco.giro()
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde
    assert _aperti(banco, banco.sorgente / "a.jpg") == 1
    assert _blob_aperti(banco) == [banco.posto("a.jpg").contenuto]


def test_una_copia_altrove_si_apre_una_volta_e_si_confronta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(5 * formato.BLOCCO, 1)
    banco.metti("a.jpg", dati)
    banco.giro()
    (tmp_path / "altrove").mkdir()
    copia = tmp_path / "altrove" / "b.jpg"
    copia.write_bytes(dati)
    banco.apri.aperti.clear()
    assert _verificatore(banco).verifica(tmp_path / "altrove").verde
    assert _aperti(banco, copia) == 1
    assert _blob_aperti(banco) == [banco.posto("a.jpg").contenuto]


def test_un_file_cambiato_nella_radice_apre_il_vecchio_solo_una_volta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    banco.metti("a.jpg", _dati(9000, 2))
    banco.apri.aperti.clear()
    _verificatore(banco).verifica(banco.sorgente)
    assert _blob_aperti(banco) == [banco.posto("a.jpg").contenuto]


def test_una_sottocartella_della_radice_si_controlla_coi_suoi_posti(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente / "2001")
    assert risposta.verde and risposta.dentro == 4
    assert risposta.radici == ["r1"]
    assert len(_blob_aperti(banco)) == 4


def test_una_cartella_sopra_la_radice_trova_i_posti_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    (tmp_path / "sciolta.jpg").write_bytes(_dati(31, 31))
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(tmp_path)
    assert risposta.dentro == len(fatti)
    assert risposta.esempi["manca"] == ["sciolta.jpg"]
    assert risposta.radici == []
    assert len(_blob_aperti(banco)) == len(fatti)


def test_la_cartella_dell_archivio_dentro_quella_scelta_si_salta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    risposta = _verificatore(banco).verifica(tmp_path)
    assert risposta.verde
    assert risposta.saltate == 1
    assert risposta.file == len(fatti)


def test_il_cestino_di_windows_non_si_guarda(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("$RECYCLE.BIN/buttata.jpg", _dati(77, 1))
    banco.metti("System Volume Information/x", _dati(78, 1))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde


def test_una_cartella_tolta_dall_archivio_ha_ancora_i_suoi_byte(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    banco.elenco.registra([elenco.fatto_radice("r1", str(banco.sorgente),
                                               tolta=True, quando=5000.0)])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde and risposta.dentro == len(fatti)
    assert risposta.radici == []


def test_un_contenuto_segnato_rovinato_non_conta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "rovinato")])
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"manca": 1}
    assert _blob_aperti(banco) == []


def test_un_contenuto_incompleto_non_conta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "incompleto")])
    assert _verificatore(banco).verifica(banco.sorgente).rossi == {"manca": 1}


def test_un_contenuto_riparato_conta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "riparato")])
    assert _verificatore(banco).verifica(banco.sorgente).verde


def test_una_copia_rovinata_si_dice_rovinata(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3 * formato.BLOCCO + 17, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    _rovina_blocco(banco, numero, [1])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"rovinato": 1}
    assert risposta.esempi["rovinato"] == ["a.jpg"]
    assert risposta.rovinati == {numero}
    assert risposta.frase() == "No, manca 1 file su 1."


def test_una_copia_rovinata_si_dice_anche_da_una_cartella_qualsiasi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17, 1)
    banco.metti("a.jpg", dati)
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    _rovina_blocco(banco, numero, [0])
    (tmp_path / "altrove").mkdir()
    (tmp_path / "altrove" / "x.jpg").write_bytes(dati)
    risposta = _verificatore(banco).verifica(tmp_path / "altrove")
    assert risposta.rossi == {"rovinato": 1}
    assert risposta.rovinati == {numero}


def test_un_danno_piccolo_si_ripara_e_si_segna_da_sistemare(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(40 * formato.BLOCCO, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    _rovina_blocco(banco, numero, [7], tutto=False)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde
    assert risposta.da_riparare == {numero}
    assert risposta.rovinati == set()


def test_con_un_gemello_sano_il_file_e_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    primo, secondo = _gemelli(banco, _dati(3 * formato.BLOCCO + 17, 1))
    _rovina_blocco(banco, secondo, [2])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde
    assert risposta.rovinati == {secondo}
    assert _blob_aperti(banco) == [secondo, primo]


def test_due_gemelli_rovinati_dicono_rovinato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    primo, secondo = _gemelli(banco, _dati(3 * formato.BLOCCO + 17, 1))
    _rovina_blocco(banco, primo, [1])
    _rovina_blocco(banco, secondo, [2])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"rovinato": 1}
    assert risposta.rovinati == {primo, secondo}


def test_un_file_cifrato_sparito_si_dice_rovinato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    banco.blob(numero).unlink()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"rovinato": 1}
    assert risposta.rovinati == {numero}


def test_un_file_cifrato_scambiato_si_dice_rovinato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.metti("b.jpg", _dati(9000, 2))
    banco.giro()
    uno = banco.posto("a.jpg").contenuto
    due = banco.posto("b.jpg").contenuto
    dati_uno = banco.blob(uno).read_bytes()
    banco.blob(uno).write_bytes(banco.blob(due).read_bytes())
    banco.blob(due).write_bytes(dati_uno)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.conti["rovinato"] == 2
    assert risposta.rovinati == {uno, due}


def test_se_sparisce_il_disco_dell_archivio_ci_si_ferma(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    shutil.rmtree(banco.archivio / elenco.CONTENUTI)
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).verifica(banco.sorgente)
    assert errore.value.codice == "archivio_sparito"


def test_un_file_solo_nel_cloud_con_le_date_giuste_e_dentro(tmp_path, chiave,
                                                             monkeypatch):
    banco = Banco(tmp_path, chiave)
    nuvola = banco.metti("nuvola.jpg", _dati(9000, 1))
    banco.giro()
    _cloud(monkeypatch, nuvola)
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde
    assert risposta.dalle_date == 1 and risposta.dentro == 1
    assert banco.apri.aperti == []


def test_un_file_solo_nel_cloud_cambiato_non_si_sa(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    nuvola = banco.metti("nuvola.jpg", _dati(9000, 1))
    banco.giro()
    os.utime(nuvola, ns=(10 ** 18, 10 ** 18))
    _cloud(monkeypatch, nuvola)
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"solo_nel_cloud": 1}
    assert risposta.esempi["solo_nel_cloud"] == ["nuvola.jpg"]
    assert banco.apri.aperti == []


def test_un_file_solo_nel_cloud_fuori_dalle_radici_non_si_sa(tmp_path, chiave,
                                                             monkeypatch):
    banco = Banco(tmp_path, chiave)
    dati = _dati(9000, 1)
    banco.metti("a.jpg", dati)
    banco.giro()
    (tmp_path / "altrove").mkdir()
    nuvola = tmp_path / "altrove" / "a.jpg"
    nuvola.write_bytes(dati)
    _cloud(monkeypatch, nuvola)
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(tmp_path / "altrove")
    assert risposta.rossi == {"solo_nel_cloud": 1}
    assert banco.apri.aperti == []


def test_un_file_solo_nel_cloud_con_copia_rovinata_non_si_fida(tmp_path, chiave,
                                                               monkeypatch):
    banco = Banco(tmp_path, chiave)
    nuvola = banco.metti("nuvola.jpg", _dati(9000, 1))
    banco.giro()
    numero = banco.posto("nuvola.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "rovinato")])
    _cloud(monkeypatch, nuvola)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"solo_nel_cloud": 1}


def test_un_file_che_non_si_legge_si_dice_illeggibile(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    _settori_rotti(banco, "a.jpg", [4096])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"illeggibile": 1}
    assert risposta.esempi["illeggibile"] == ["a.jpg"]


def test_un_file_illeggibile_fuori_dalle_radici(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    banco.metti("b.jpg", _dati(9000, 2))
    _settori_rotti(banco, "b.jpg", [0])
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"illeggibile": 1}
    assert risposta.esempi["illeggibile"] == ["b.jpg"]


def _in_uso():
    guasto = OSError(errno.EACCES, "in uso")
    guasto.winerror = 32
    return guasto


def test_un_file_tenuto_da_un_altro_programma_si_dice_in_uso(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    _settori_rotti(banco, "a.jpg", [0], errore=_in_uso)
    assert _verificatore(banco).verifica(banco.sorgente).rossi == {"in_uso": 1}


def test_un_file_che_non_si_apre_perche_in_uso(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    bersaglio = os.fspath(banco.sorgente / "a.jpg")

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            raise _in_uso()
        return lettore

    banco.apri.regole.append(regola)
    assert _verificatore(banco).verifica(banco.sorgente).rossi == {"in_uso": 1}


def test_un_file_che_cambia_mentre_si_controlla(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    bersaglio = banco.sorgente / "a.jpg"

    def regola(percorso, senza_cache, volta, lettore):
        if percorso.endswith(".ofs"):
            with open(bersaglio, "ab") as file:
                file.write(b"di piu")
        return lettore

    banco.apri.regole.append(regola)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"cambiato": 1}


def test_un_file_piu_corto_quando_si_apre_e_cambiato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    bersaglio = os.fspath(banco.sorgente / "a.jpg")

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            lettore.dimensione -= 1
        return lettore

    banco.apri.regole.append(regola)
    assert _verificatore(banco).verifica(banco.sorgente).rossi == {"cambiato": 1}


def test_un_file_sparito_mentre_si_controlla_non_si_conta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.metti("b.jpg", _dati(9000, 2))
    banco.giro()
    bersaglio = os.fspath(banco.sorgente / "a.jpg")

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            lettore.close()
            os.unlink(bersaglio)
            raise FileNotFoundError(bersaglio)
        return lettore

    banco.apri.regole.append(regola)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde and risposta.file == 1


@su_linux
def test_i_collegamenti_e_i_file_speciali_si_contano_e_basta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    os.symlink("a.jpg", banco.sorgente / "scorciatoia")
    os.symlink("/non/esiste", banco.sorgente / "rotta")
    os.mkfifo(banco.sorgente / "tubo")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde
    assert risposta.collegamenti == 2 and risposta.speciali == 1


@su_linux
def test_un_collegamento_a_una_cartella_non_si_segue(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    (tmp_path / "fuori").mkdir()
    (tmp_path / "fuori" / "nuova.jpg").write_bytes(_dati(50, 50))
    os.symlink(tmp_path / "fuori", banco.sorgente / "porta")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.verde and risposta.collegamenti == 1


@su_linux
def test_una_cartella_scelta_attraverso_un_collegamento_si_segue(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    os.symlink(banco.sorgente, tmp_path / "scorciatoia")
    banco.apri.aperti.clear()
    risposta = _verificatore(banco).verifica(tmp_path / "scorciatoia")
    assert risposta.verde and risposta.dentro == len(fatti)
    assert risposta.radici == ["r1"]
    assert len(_blob_aperti(banco)) == len(fatti)


@su_linux
def test_un_nome_strano_non_puo_essere_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    (banco.sorgente / "a\\b.jpg").write_bytes(b"x")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.rossi == {"nome_strano": 1}
    assert risposta.frase() == "No, manca 1 file su 9."


def _scandir_rotto(monkeypatch, cartella: Path) -> None:
    vero = os.scandir
    rotta = os.fspath(cartella)

    def finto(dove="."):
        if os.fspath(dove) == rotta:
            raise PermissionError(errno.EACCES, "vietato", rotta)
        return vero(dove)

    monkeypatch.setattr(os, "scandir", finto)


def test_una_sottocartella_che_non_si_legge_lascia_il_dubbio(tmp_path, chiave,
                                                             monkeypatch):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    _scandir_rotto(monkeypatch, banco.sorgente / "2001")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert not risposta.verde
    assert risposta.rossi == {"cartella_illeggibile": 1}
    assert risposta.esempi["cartella_illeggibile"] == ["2001"]
    assert risposta.frase() == "Non lo so: 1 cartella non si legge."


def test_la_cartella_scelta_che_non_si_legge_lascia_il_dubbio(tmp_path, chiave,
                                                              monkeypatch):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    _scandir_rotto(monkeypatch, banco.sorgente)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert not risposta.verde
    assert risposta.rossi == {"radice_illeggibile": 1}
    assert risposta.frase() == "Non lo so: questa cartella non si legge."


def test_un_file_e_un_dubbio_insieme_si_dice_il_file(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("nuova.jpg", _dati(5, 5))
    _scandir_rotto(monkeypatch, banco.sorgente / "2002")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.frase().startswith("No, manca 1 file su")


@pytest.mark.parametrize("dove", ["archivio", "archivio/contenuti",
                                  "archivio/elenco"])
def test_dentro_l_archivio_non_si_chiede(tmp_path, chiave, dove):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    (tmp_path / dove).mkdir(parents=True, exist_ok=True)
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).verifica(tmp_path / dove)
    assert errore.value.codice == "nell_archivio"


@su_linux
def test_dentro_l_archivio_non_si_chiede_neanche_con_un_collegamento(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    os.symlink(banco.archivio, tmp_path / "porta")
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).verifica(tmp_path / "porta")
    assert errore.value.codice == "nell_archivio"


def test_un_file_al_posto_della_cartella(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"x")
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).verifica(banco.sorgente / "a.jpg")
    assert errore.value.codice == "non_una_cartella"


def test_una_cartella_che_non_c_e(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).verifica(tmp_path / "non c'è")
    assert errore.value.codice == "cartella_sparita"


def test_i_file_vuoti(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(10, 1))
    banco.giro()
    banco.metti("vuoto.txt", b"")
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.esempi["manca"] == ["vuoto.txt"]
    banco.giro()
    assert _verificatore(banco).verifica(banco.sorgente).verde
    (tmp_path / "altrove").mkdir()
    (tmp_path / "altrove" / "anche.txt").write_bytes(b"")
    assert _verificatore(banco).verifica(tmp_path / "altrove").verde


def test_gli_esempi_si_fermano_ma_il_conto_no(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(dentro, "ESEMPI", 3)
    banco = Banco(tmp_path, chiave)
    for indice in range(7):
        banco.metti(f"n{indice}.jpg", _dati(10 + indice, indice))
    risposta = _verificatore(banco).verifica(banco.sorgente)
    assert risposta.conti["manca"] == 7
    assert len(risposta.esempi["manca"]) == 3
    assert risposta.frase() == "No, mancano 7 file su 7."


def test_ci_si_puo_fermare_a_meta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    colpi = []

    def aspetta():
        colpi.append(1)
        if len(colpi) > 4:
            raise Fermato

    verificatore = _verificatore(banco, aspetta=aspetta)
    with pytest.raises(Fermato):
        verificatore.verifica(banco.sorgente)
    assert verificatore.risposta is not None
    assert not verificatore.risposta.finito and not verificatore.risposta.verde
    assert verificatore.risposta.frase().startswith("Il controllo non è finito")


def test_ci_si_ferma_anche_dentro_un_file_grande(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(dentro, "OGNI_QUANTI_PEZZI", 1)
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(6 * formato.BLOCCO, 1))
    banco.giro()
    colpi = []

    def aspetta():
        colpi.append(1)
        if len(colpi) == 4:
            raise Fermato

    with pytest.raises(Fermato):
        _verificatore(banco, aspetta=aspetta).verifica(banco.sorgente)
    assert len(colpi) == 4


def test_mentre_si_controlla_non_si_scrive_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("nuova.jpg", _dati(5, 5))
    prima = {percorso: percorso.read_bytes()
             for percorso in banco.archivio.rglob("*") if percorso.is_file()}
    conto = banco.elenco.conta()
    _verificatore(banco).verifica(tmp_path)
    dopo = {percorso: percorso.read_bytes()
            for percorso in banco.archivio.rglob("*") if percorso.is_file()}
    assert dopo == prima
    assert banco.elenco.conta() == conto


def test_l_avanzamento_conta_file_e_byte_letti(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fatti = _pieno(banco)
    verificatore = _verificatore(banco)
    verificatore.verifica(banco.sorgente)
    assert verificatore.avanzamento.file == len(fatti)
    assert verificatore.avanzamento.letti == sum(len(dati) for dati in fatti.values())
    assert verificatore.avanzamento.percorso is None


def test_aggiungere_una_cartella_gia_seguita_non_ne_crea_un_altra(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    verificatore = _verificatore(banco)
    for dove in (banco.sorgente, banco.sorgente / "2001" / "mare"):
        assert verificatore.aggiungi(dove) == {
            "radice": "r1", "percorso": str(banco.sorgente), "nuova": False}
    assert len(banco.elenco.radici()) == 1


def test_aggiungere_una_cartella_nuova_la_segna_e_resta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    (tmp_path / "altrove").mkdir()
    (tmp_path / "altrove" / "nuova.jpg").write_bytes(_dati(5, 5))
    aggiunta = _verificatore(banco, adesso=lambda: 7777.0).aggiungi(tmp_path / "altrove")
    assert aggiunta["nuova"] is True
    assert aggiunta["percorso"] == os.path.abspath(tmp_path / "altrove")
    banco = banco.riapri()
    radice = banco.radice(aggiunta["radice"])
    assert radice["percorso"] == aggiunta["percorso"]
    assert radice["aggiunta"] == 7777.0 and not radice["tolta"]


def test_dopo_l_aggiunta_e_la_copia_e_tutto_dentro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    altrove = tmp_path / "altrove"
    (altrove / "sotto").mkdir(parents=True)
    (altrove / "nuova.jpg").write_bytes(_dati(5, 5))
    (altrove / "sotto" / "anche.jpg").write_bytes(_dati(50, 6))
    verificatore = _verificatore(banco)
    assert verificatore.verifica(altrove).mancano == 2
    aggiunta = verificatore.aggiungi(altrove)
    banco.giro(aggiunta["radice"])
    risposta = verificatore.verifica(altrove)
    assert risposta.verde and risposta.radici == [aggiunta["radice"]]


def test_il_programma_sceglie_il_nome_della_cartella_nuova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (tmp_path / "altrove").mkdir()
    chiesti = []

    def nuova_radice(percorso):
        chiesti.append(percorso)
        return "cartella-7"

    verificatore = _verificatore(banco, nuova_radice=nuova_radice)
    aggiunta = verificatore.aggiungi(tmp_path / "altrove")
    assert aggiunta["radice"] == "cartella-7"
    assert chiesti == [os.path.abspath(tmp_path / "altrove")]
    assert banco.radice("cartella-7")["percorso"] == chiesti[0]


def test_un_nome_gia_usato_dal_programma_si_rifiuta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (tmp_path / "altrove").mkdir()
    verificatore = _verificatore(banco, nuova_radice=lambda percorso: "r1")
    with pytest.raises(ErroreOfficina) as errore:
        verificatore.aggiungi(tmp_path / "altrove")
    assert errore.value.codice == "radice_gia_usata"
    assert banco.radice("r1")["percorso"] == str(banco.sorgente)


def test_se_il_programma_non_riesce_non_si_segna_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (tmp_path / "altrove").mkdir()

    def nuova_radice(percorso):
        raise ErroreOfficina("no", codice="programma_occupato")

    with pytest.raises(ErroreOfficina):
        _verificatore(banco, nuova_radice=nuova_radice).aggiungi(tmp_path / "altrove")
    assert [radice["id"] for radice in banco.elenco.radici()] == ["r1"]


def test_una_cartella_dentro_una_tolta_diventa_nuova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.elenco.registra([elenco.fatto_radice("r1", str(banco.sorgente),
                                               tolta=True, quando=5000.0)])
    aggiunta = _verificatore(banco).aggiungi(banco.sorgente / "2001")
    assert aggiunta["nuova"] is True and aggiunta["radice"] != "r1"


def test_una_cartella_sopra_una_radice_diventa_nuova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    (tmp_path / "x").mkdir()
    aggiunta = _verificatore(banco).aggiungi(tmp_path / "x")
    assert aggiunta["nuova"] is True


@pytest.mark.parametrize("dove", ["archivio", "archivio/contenuti"])
def test_non_si_aggiunge_l_archivio(tmp_path, chiave, dove):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).aggiungi(tmp_path / dove)
    assert errore.value.codice == "nell_archivio"
    assert len(banco.elenco.radici()) == 1


def test_non_si_aggiunge_un_file(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"x")
    with pytest.raises(ErroreOfficina) as errore:
        _verificatore(banco).aggiungi(banco.sorgente / "a.jpg")
    assert errore.value.codice == "non_una_cartella"


def _aspetta_fine(lavoro) -> None:
    assert lavoro.aspetta_fine(ATTESA)


def _verifica(banco: Banco, **opzioni) -> Verifica:
    opzioni.setdefault("apri", banco.apri)
    return Verifica(banco.archivio, banco.elenco, banco.chiave, sveglio=_sveglio,
                    **opzioni)


def test_il_controllo_in_sottofondo_risponde(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    banco.metti("nuova.jpg", _dati(5, 5))
    lavoro = _verifica(banco)
    assert lavoro.avvia(banco.sorgente)
    _aspetta_fine(lavoro)
    foto = lavoro.istantanea()
    assert foto["stato"] == sottofondo.FINITO
    assert foto["finito"] is True and foto["verde"] is False
    assert foto["frase"] == "No, manca 1 file su 9."
    assert foto["rossi"] == {"manca": 1}
    assert foto["esempi"] == {"manca": ["nuova.jpg"]}
    assert foto["file"] == 9 and foto["dentro"] == 8 and foto["mancano"] == 1
    assert foto["byte_mancanti"] == 5
    assert foto["da_controllare"] == []
    assert foto["errore"] is None and foto["codice"] is None


def test_il_controllo_in_sottofondo_dice_cosa_va_controllato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3 * formato.BLOCCO + 17, 1))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    _rovina_blocco(banco, numero, [1])
    lavoro = _verifica(banco)
    lavoro.avvia(banco.sorgente)
    _aspetta_fine(lavoro)
    assert lavoro.istantanea()["da_controllare"] == [numero]


def test_prima_di_partire_l_istantanea_e_vuota(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    foto = _verifica(banco).istantanea()
    assert foto["stato"] == sottofondo.FERMO
    assert foto["cartella"] is None and foto["frase"] is None
    assert foto["verde"] is False and foto["rossi"] == {}


def test_una_cartella_sbagliata_in_sottofondo_e_un_errore(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    lavoro = _verifica(banco)
    lavoro.avvia(tmp_path / "non c'è")
    _aspetta_fine(lavoro)
    foto = lavoro.istantanea()
    assert foto["stato"] == sottofondo.ERRORE
    assert foto["codice"] == "cartella_sparita"


def test_il_controllo_in_sottofondo_si_mette_in_pausa_e_si_ferma(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    lavoro = _verifica(banco)
    lavoro.pausa()
    lavoro.avvia(banco.sorgente)
    lavoro.pausa()
    assert lavoro.stato == sottofondo.IN_PAUSA
    assert not lavoro.aspetta_fine(0.2)
    lavoro.ferma(ATTESA)
    foto = lavoro.istantanea()
    assert foto["stato"] == sottofondo.FERMATO
    assert foto["finito"] is False


def test_il_controllo_in_sottofondo_riprende_dopo_la_pausa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    lavoro = _verifica(banco)
    lavoro.avvia(banco.sorgente)
    lavoro.pausa()
    lavoro.riprendi()
    _aspetta_fine(lavoro)
    assert lavoro.istantanea()["verde"] is True


def test_il_controllo_in_sottofondo_si_rifa_da_capo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _pieno(banco)
    lavoro = _verifica(banco)
    lavoro.avvia(banco.sorgente)
    _aspetta_fine(lavoro)
    banco.metti("nuova.jpg", _dati(5, 5))
    lavoro.avvia(banco.sorgente)
    _aspetta_fine(lavoro)
    assert lavoro.istantanea()["mancano"] == 1


def test_il_disco_dell_archivio_sparito_in_sottofondo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(9000, 1))
    banco.giro()
    shutil.rmtree(banco.archivio / elenco.CONTENUTI)
    lavoro = _verifica(banco)
    lavoro.avvia(banco.sorgente)
    _aspetta_fine(lavoro)
    foto = lavoro.istantanea()
    assert foto["stato"] == sottofondo.ERRORE
    assert foto["codice"] == "archivio_sparito"
    assert foto["finito"] is False


@pytest.mark.parametrize("file, dentro_, conti, attesa", [
    (0, 0, {}, "Sì: in questa cartella non ci sono file."),
    (1, 1, {}, "Sì, è tutto dentro: 1 file."),
    (1234, 1234, {}, "Sì, è tutto dentro: 1.234 file."),
    (1234567, 1234567, {}, "Sì, è tutto dentro: 1.234.567 file."),
    (2, 1, {"manca": 1}, "No, manca 1 file su 2."),
    (5000, 3000, {"manca": 1500, "solo_nel_cloud": 500},
     "No, mancano 2.000 file su 5.000."),
    (3, 2, {"in_uso": 1}, "No, manca 1 file su 3."),
    (3, 3, {"cartella_illeggibile": 2}, "Non lo so: 2 cartelle non si leggono."),
    (0, 0, {"radice_illeggibile": 1}, "Non lo so: questa cartella non si legge."),
])
def test_la_frase(file, dentro_, conti, attesa):
    risposta = Risposta(cartella="C:\\Foto", file=file, dentro=dentro_, finito=True)
    risposta.conti.update(conti)
    assert risposta.frase() == attesa


@pytest.mark.parametrize("sopra, sotto, attesa", [
    ("/a/b", "/a/b", ""),
    ("/a/b", "/a/b/c", "c"),
    ("/a/b", "/a/b/c/d", "c/d"),
    ("/a/b", "/a/bc", None),
    ("/a/b", "/a", None),
    ("/a/b/", "/a/b/c", "c"),
    ("/", "/a", "a"),
    ("/a/b", "/x/a/b", None),
])
def test_quello_che_resta_di_un_percorso(sopra, sotto, attesa):
    assert dentro._resto(sopra, sotto) == attesa


@pytest.mark.parametrize("sistema, relativo, cima, attesa", [
    ("posix", "a/b/c", "a", "b/c"),
    ("posix", "a/b/c", "a/b", "c"),
    ("posix", "a/b", "a/b", ""),
    ("posix", "ab/c", "a", None),
    ("posix", "A/b", "a", None),
    ("nt", "A/b", "a", "b"),
    ("nt", "FOTO", "foto", ""),
    ("nt", "Foto2/x", "foto", None),
])
def test_quello_che_sta_sotto_una_cima(monkeypatch, sistema, relativo, cima, attesa):
    monkeypatch.setattr(dentro.os, "name", sistema)
    assert dentro._sotto_di(relativo, cima) == attesa


MISURE = (0, 1, 12, 4095, 4096, formato.BLOCCO - 1, formato.BLOCCO,
          formato.BLOCCO + 1, 2 * formato.BLOCCO + 3)


def _albero_a_caso(caso: random.Random, banco: Banco) -> dict[str, bytes]:
    fatti = {}
    for indice in range(caso.randint(1, 14)):
        profondita = caso.randint(0, 3)
        parti = [f"c{caso.randint(0, 3)}" for _ in range(profondita)]
        relativo = "/".join([*parti, f"f{indice}.bin"])
        dati = _dati(caso.choice(MISURE), caso.randint(0, 6))
        fatti[relativo] = dati
        banco.metti(relativo, dati)
    return fatti


def _contenuti_buoni(banco: Banco) -> set[bytes]:
    buoni = set()
    for numero in banco.elenco.numeri():
        if banco.elenco.contenuto(numero)["stato"] in ("buono", "riparato"):
            buoni.add(banco.dati(numero))
    return buoni


def _attese(cartella: Path, buoni: set[bytes]) -> tuple[int, set[str]]:
    dentro_, mancano = 0, set()
    for percorso in cartella.rglob("*"):
        if percorso.is_file() and not percorso.is_symlink():
            relativo = percorso.relative_to(cartella).as_posix()
            if percorso.read_bytes() in buoni:
                dentro_ += 1
            else:
                mancano.add(relativo)
    return dentro_, mancano


@pytest.mark.parametrize("seme", range(40))
def test_a_caso_la_risposta_e_sempre_giusta(tmp_path, chiave, seme):
    caso = random.Random(seme)
    banco = Banco(tmp_path, chiave)
    fatti = _albero_a_caso(caso, banco)
    banco.giro()
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    for relativo, dati in fatti.items():
        scelta = caso.random()
        if scelta < 0.2:
            banco.metti(relativo, _dati(len(dati), 100 + caso.randint(0, 3)))
        elif scelta < 0.3:
            (banco.sorgente / relativo).unlink()
        if caso.random() < 0.4:
            (altrove / f"copia di {relativo.replace('/', '_')}").write_bytes(dati)
    for indice in range(caso.randint(0, 4)):
        banco.metti(f"n/n{indice}.bin", _dati(caso.choice(MISURE), 200 + indice))
        (altrove / f"x{indice}.bin").write_bytes(_dati(caso.choice(MISURE), 300 + indice))
    buoni = _contenuti_buoni(banco)
    verificatore = _verificatore(banco)
    for cartella in (banco.sorgente, altrove):
        risposta = verificatore.verifica(cartella)
        attesi, mancano = _attese(cartella, buoni)
        assert risposta.dentro == attesi
        assert set(risposta.esempi.get("manca", [])) == mancano
        assert risposta.verde == (not mancano)
        assert set(risposta.rossi) <= {"manca"}


@pytest.mark.parametrize("seme", range(25))
def test_a_caso_con_copie_rovinate_non_si_sbaglia_mai(tmp_path, chiave, seme):
    caso = random.Random(1000 + seme)
    banco = Banco(tmp_path, chiave)
    fatti = _albero_a_caso(caso, banco)
    banco.giro()
    chiari = {numero: banco.dati(numero) for numero in banco.elenco.numeri()}
    sani: set[bytes] = set()
    rotti: set[bytes] = set()
    for numero, dati in chiari.items():
        with open(banco.blob(numero), "rb") as file:
            blocchi = formato.Contenuto(file, banco.chiave,
                                        numero=bytes.fromhex(numero)).forma.blocchi
        if blocchi and caso.random() < 0.5:
            _rovina_blocco(banco, numero, [caso.randrange(blocchi)],
                           tutto=caso.random() < 0.7)
        with open(banco.blob(numero), "rb") as file:
            controllo = formato.controlla(
                file, banco.chiave, numero=bytes.fromhex(numero),
                testa=banco.elenco.contenuto(numero)["testa"])
        (sani if controllo.leggibile else rotti).add(dati)
    risposta = _verificatore(banco).verifica(banco.sorgente)
    attesi_dentro = sum(1 for dati in fatti.values() if dati in sani)
    attesi_rotti = {relativo for relativo, dati in fatti.items()
                    if dati in rotti and dati not in sani}
    assert risposta.dentro == attesi_dentro
    assert set(risposta.esempi.get("rovinato", [])) == attesi_rotti
    assert risposta.verde == (not attesi_rotti)


@pytest.mark.parametrize("seme", range(20))
def test_a_caso_fermarsi_non_dice_mai_verde(tmp_path, chiave, seme):
    caso = random.Random(2000 + seme)
    banco = Banco(tmp_path, chiave)
    _albero_a_caso(caso, banco)
    banco.giro()
    limite = caso.randint(1, 12)
    colpi = []

    def aspetta():
        colpi.append(1)
        if len(colpi) >= limite:
            raise Fermato

    verificatore = _verificatore(banco, aspetta=aspetta)
    try:
        risposta = verificatore.verifica(banco.sorgente)
    except Fermato:
        assert not verificatore.risposta.verde
        assert not verificatore.risposta.finito
    else:
        assert risposta.verde and risposta.finito
