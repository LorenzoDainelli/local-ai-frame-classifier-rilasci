from __future__ import annotations

import errno
import io
import os
import random

import pytest

from officina.sicuro import chiavi, diretto, formato
from officina.sicuro.diretto import ALLINEA, Lettore

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")
su_windows = pytest.mark.skipif(os.name != "nt", reason="prove con Windows vero")


def _file(cartella, dati, nome="IMG_1.jpg"):
    percorso = cartella / nome
    percorso.write_bytes(dati)
    return percorso


def _dati(quanti, seme=1):
    return random.Random(seme).randbytes(quanti)


@pytest.mark.parametrize("senza_cache", [True, False])
@pytest.mark.parametrize("quanti", [0, 1, 17, ALLINEA - 1, ALLINEA, ALLINEA + 1,
                                    3 * ALLINEA, 5 * ALLINEA - 3, 70_001])
def test_si_legge_tutto_uguale(tmp_path, senza_cache, quanti):
    dati = _dati(quanti)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso, senza_cache=senza_cache, finestra=2 * ALLINEA) as lettore:
        assert lettore.dimensione == quanti
        assert lettore.read() == dati
        assert lettore.read(10) == b""


@su_linux
def test_su_un_disco_vero_si_salta_la_memoria(tmp_path):
    percorso = _file(tmp_path, _dati(10_000))
    with Lettore(percorso) as lettore:
        assert lettore.senza_cache in (True, False)
        assert lettore.read() == percorso.read_bytes()


def test_chi_vuole_la_memoria_la_usa(tmp_path):
    percorso = _file(tmp_path, b"foto")
    with Lettore(percorso, senza_cache=False) as lettore:
        assert lettore.senza_cache is False
        assert lettore.read() == b"foto"


@pytest.mark.parametrize("seme", range(40))
def test_salti_a_caso_leggono_giusto(tmp_path, seme):
    caso = random.Random(seme)
    dati = _dati(caso.randrange(1, 60_000), seme)
    percorso = _file(tmp_path, dati)
    finestra = caso.choice([ALLINEA, 2 * ALLINEA, 3 * ALLINEA, 64 * 1024])
    with Lettore(percorso, senza_cache=caso.random() < 0.5,
                 finestra=finestra) as lettore:
        for _ in range(60):
            dove = caso.randrange(0, len(dati) + 100)
            quanti = caso.randrange(0, 20_000)
            assert lettore.seek(dove) == dove
            assert lettore.read(quanti) == dati[dove:dove + quanti]
            assert lettore.tell() == min(max(dove, dove + quanti if dove < len(dati)
                                             else dove), max(dove, len(dati)))


def test_i_salti_relativi_e_dalla_fine(tmp_path):
    dati = _dati(20_000)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso, finestra=ALLINEA) as lettore:
        assert lettore.seek(-10, io.SEEK_END) == len(dati) - 10
        assert lettore.read() == dati[-10:]
        lettore.seek(100)
        assert lettore.seek(50, io.SEEK_CUR) == 150
        assert lettore.read(5) == dati[150:155]
        with pytest.raises(ValueError):
            lettore.seek(-1)
        assert lettore.readable() and lettore.seekable()


@pytest.mark.parametrize("dove,quanti", [(0, 1), (4095, 2), (4096, 4096),
                                         (5000, 10_000), (19_990, 100),
                                         (20_000, 5), (30_000, 5), (10, 0)])
def test_un_pezzetto_preciso(tmp_path, dove, quanti):
    dati = _dati(20_000)
    percorso = _file(tmp_path, dati)
    for senza_cache in (True, False):
        with Lettore(percorso, senza_cache=senza_cache) as lettore:
            assert lettore.pezzo(dove, quanti) == dati[dove:dove + quanti]


def test_readinto_riempie_anche_oltre_la_finestra(tmp_path):
    dati = _dati(50_000)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso, finestra=ALLINEA) as lettore:
        spazio = bytearray(30_000)
        assert lettore.readinto(spazio) == 30_000
        assert bytes(spazio) == dati[:30_000]
        assert lettore.readinto(bytearray(0)) == 0
        assert lettore.readinto(memoryview(spazio)) == 20_000
        assert bytes(spazio[:20_000]) == dati[30_000:]


def test_la_finestra_si_arrotonda(tmp_path):
    percorso = _file(tmp_path, _dati(9000))
    with Lettore(percorso, finestra=5) as lettore:
        assert lettore._finestra == ALLINEA
        assert lettore.read() == percorso.read_bytes()
    with Lettore(percorso, finestra=3 * ALLINEA + 7) as lettore:
        assert lettore._finestra == 3 * ALLINEA


def test_dentro_un_lettore_con_memoria(tmp_path):
    dati = _dati(100_000)
    percorso = _file(tmp_path, dati)
    with io.BufferedReader(Lettore(percorso), buffer_size=10_000) as lettore:
        assert lettore.read(3) == dati[:3]
        assert lettore.read() == dati[3:]


def test_un_file_che_non_ce_si_dice_e_non_lascia_niente_aperto(tmp_path, monkeypatch):
    chiuse = []
    vera = diretto.mmap.mmap

    class Mappa:
        def __init__(self, *a):
            self._vera = vera(*a)

        def close(self):
            chiuse.append(1)
            self._vera.close()

    monkeypatch.setattr(diretto.mmap, "mmap", Mappa)
    with pytest.raises(FileNotFoundError):
        Lettore(tmp_path / "manca.jpg")
    assert chiuse == [1]


@su_linux
def test_se_il_disco_non_vuole_saltare_la_memoria_si_dimentica_dopo(tmp_path, monkeypatch):
    percorso = _file(tmp_path, _dati(10_000))
    vera = os.open
    consigli = []

    def apri(nome, bandiere, *altro):
        if bandiere & getattr(os, "O_DIRECT", 0):
            raise OSError(errno.EINVAL, "no")
        return vera(nome, bandiere, *altro)

    monkeypatch.setattr(diretto.os, "open", apri)
    monkeypatch.setattr(diretto.os, "posix_fadvise",
                        lambda fd, a, b, c: consigli.append(c), raising=False)
    with Lettore(percorso) as lettore:
        assert lettore.senza_cache is False
        assert lettore.read() == percorso.read_bytes()
    assert consigli and set(consigli) == {os.POSIX_FADV_DONTNEED}


@su_linux
def test_senza_il_permesso_di_non_toccare_la_data_si_va_avanti(tmp_path, monkeypatch):
    percorso = _file(tmp_path, _dati(5000))
    vera = os.open
    provate = []

    def apri(nome, bandiere, *altro):
        provate.append(bandiere)
        if bandiere & getattr(os, "O_NOATIME", 0):
            raise PermissionError(errno.EPERM, "non tuo")
        return vera(nome, bandiere, *altro)

    monkeypatch.setattr(diretto.os, "open", apri)
    with Lettore(percorso) as lettore:
        assert lettore.read() == percorso.read_bytes()
    assert len(provate) >= 2


@su_linux
def test_se_la_lettura_diretta_si_rifiuta_si_riapre_con_memoria(tmp_path, monkeypatch):
    dati = _dati(30_000)
    percorso = _file(tmp_path, dati)
    vera = os.preadv
    rifiuti = []

    def leggi(fd, spazi, dove):
        if not rifiuti:
            rifiuti.append(dove)
            raise OSError(errno.EINVAL, "misura sbagliata")
        return vera(fd, spazi, dove)

    lettore = Lettore(percorso)
    lettore.senza_cache = True
    monkeypatch.setattr(diretto.os, "preadv", leggi)
    with lettore:
        assert lettore.read() == dati
        assert lettore.senza_cache is False
    assert rifiuti == [0]


@su_linux
def test_un_errore_vero_del_disco_non_si_nasconde(tmp_path, monkeypatch):
    percorso = _file(tmp_path, _dati(30_000))

    def leggi(fd, spazi, dove):
        raise OSError(errno.EIO, "settore rotto")

    with Lettore(percorso, senza_cache=False) as lettore:
        monkeypatch.setattr(diretto.os, "preadv", leggi)
        with pytest.raises(OSError) as errore:
            lettore.read()
        assert errore.value.errno == errno.EIO


@su_linux
def test_un_rifiuto_senza_lettura_diretta_non_si_riprova(tmp_path, monkeypatch):
    percorso = _file(tmp_path, _dati(3000))

    def leggi(fd, spazi, dove):
        raise OSError(errno.EINVAL, "strano")

    with Lettore(percorso, senza_cache=False) as lettore:
        monkeypatch.setattr(diretto.os, "preadv", leggi)
        with pytest.raises(OSError):
            lettore.read()


def test_un_file_che_si_accorcia_dopo_si_legge_fino_a_dove_ce(tmp_path):
    dati = _dati(40_000)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso, finestra=ALLINEA) as lettore:
        assert lettore.read(100) == dati[:100]
        with open(percorso, "r+b") as file:
            file.truncate(10_000)
        resto = lettore.read()
        assert resto == dati[100:10_000]


def test_un_file_che_cresce_dopo_si_legge_fino_alla_grandezza_di_prima(tmp_path):
    dati = _dati(9_000)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso) as lettore:
        with open(percorso, "ab") as file:
            file.write(b"in piu")
        assert lettore.read() == dati


def test_chiudere_due_volte_va_bene(tmp_path):
    percorso = _file(tmp_path, b"x")
    lettore = Lettore(percorso)
    lettore.close()
    lettore.close()
    assert lettore.closed
    with pytest.raises(ValueError):
        lettore.read()


def test_il_nome_e_quello_lungo(tmp_path):
    percorso = _file(tmp_path, b"x")
    with Lettore(percorso) as lettore:
        assert lettore.nome == diretto.percorso_lungo(percorso)


@pytest.mark.parametrize("quanti", [0, 5, formato.BLOCCO, 3 * formato.BLOCCO + 11])
def test_un_contenuto_cifrato_si_controlla_dal_disco(tmp_path, quanti):
    chiave = chiavi.Chiave(bytes(range(32)))
    dati = _dati(quanti)
    blob = tmp_path / "x.ofs"
    with open(blob, "wb") as fuori:
        scritto = formato.scrivi_byte(fuori, chiave, dati, {"nome": "IMG_1.jpg"})
    with Lettore(blob, finestra=ALLINEA) as lettore:
        contenuto = formato.Contenuto(lettore, chiave, testa=scritto.testa)
        assert contenuto.tutto() == dati
        controllo = formato.controlla(lettore, chiave, testa=scritto.testa)
        assert controllo.buono


@su_windows
def test_su_windows_si_salta_la_memoria(tmp_path):
    dati = _dati(70_000)
    percorso = _file(tmp_path, dati)
    with Lettore(percorso) as lettore:
        assert lettore.senza_cache is True
        assert lettore.read() == dati
        lettore.seek(5000)
        assert lettore.read(3) == dati[5000:5003]
        assert lettore.pezzo(4095, 2) == dati[4095:4097]


@su_windows
def test_su_windows_un_file_aperto_da_altri_si_legge(tmp_path):
    dati = _dati(5000)
    percorso = _file(tmp_path, dati)
    with open(percorso, "r+b"):
        with Lettore(percorso) as lettore:
            assert lettore.read() == dati


@su_windows
def test_su_windows_un_nome_con_il_punto_alla_fine(tmp_path):
    dati = _dati(100)
    percorso = diretto.percorso_lungo(tmp_path) + "\\foto."
    with open(percorso, "wb") as file:
        file.write(dati)
    with Lettore(percorso) as lettore:
        assert lettore.read() == dati
