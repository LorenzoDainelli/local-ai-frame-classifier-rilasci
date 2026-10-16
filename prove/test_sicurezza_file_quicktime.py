from __future__ import annotations

import struct
import time

import pytest

from officina.importazione import quicktime


def _atomo(nome: bytes, corpo: bytes) -> bytes:
    return struct.pack(">I", 8 + len(corpo)) + nome + corpo


def _mov(per_blocco: int = 1, quanti_stts: int = 1, scarti: int = 1,
         fissa: int = 1, quanti_stsz: int = 1, primo_secondo: int | None = None) -> bytes:
    stsd = _atomo(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + struct.pack(">I", 16) + b"jpeg")
    stsz = _atomo(b"stsz", b"\0" * 4 + struct.pack(">II", fissa, quanti_stsz))
    stco = _atomo(b"stco", b"\0" * 4 + struct.pack(">I", scarti) + struct.pack(">I", 0) * scarti)
    righe = [(1, per_blocco, 1)]
    if primo_secondo is not None:
        righe.append((primo_secondo, per_blocco, 1))
    stsc = _atomo(b"stsc", b"\0" * 4 + struct.pack(">I", len(righe))
                  + b"".join(struct.pack(">III", *riga) for riga in righe))
    stts = _atomo(b"stts", b"\0" * 4 + struct.pack(">I", 1) + struct.pack(">II", quanti_stts, 600))
    stbl = _atomo(b"stbl", stsd + stsz + stco + stsc + stts)
    return _atomo(b"moov", _atomo(b"trak", _atomo(b"mdia", _atomo(b"minf", stbl))))


def _leggi_in_fretta(percorso):
    inizio = time.perf_counter()
    campioni = quicktime.campioni_jpeg(percorso)
    assert time.perf_counter() - inizio < 5
    return campioni


def test_un_blocco_con_quattro_miliardi_di_campioni_non_blocca_niente(tmp_path):
    percorso = tmp_path / "blocco.mov"
    percorso.write_bytes(_mov(per_blocco=0xFFFFFFFF))
    assert len(_leggi_in_fretta(percorso)) == 1


def test_molti_blocchi_enormi_non_bloccano_niente(tmp_path):
    percorso = tmp_path / "blocchi.mov"
    percorso.write_bytes(_mov(per_blocco=0xFFFFFFFF, scarti=30000))
    assert len(_leggi_in_fretta(percorso)) == 1


def test_una_riga_di_blocchi_che_arriva_fino_all_infinito_non_riempie_la_memoria(tmp_path):
    percorso = tmp_path / "infinito.mov"
    percorso.write_bytes(_mov(per_blocco=0xFFFFFFFF, scarti=4, primo_secondo=0xFFFFFFFE))
    assert len(_leggi_in_fretta(percorso)) == 1


def test_i_tempi_di_quattro_miliardi_di_campioni_non_riempiono_la_memoria(tmp_path):
    percorso = tmp_path / "tempi.mov"
    percorso.write_bytes(_mov(quanti_stts=0xFFFFFFFF))
    assert len(_leggi_in_fretta(percorso)) == 1


def test_le_misure_fisse_di_quattro_miliardi_non_riempiono_la_memoria(tmp_path):
    percorso = tmp_path / "misure.mov"
    percorso.write_bytes(_mov(fissa=7, quanti_stsz=0xFFFFFFFF))
    campioni = _leggi_in_fretta(percorso)
    assert len(campioni) <= percorso.stat().st_size


def test_le_misure_variabili_dichiarate_ma_assenti_non_inventano_campioni():
    assert quicktime._misure(b"\0" * 4 + struct.pack(">II", 0, 0xFFFFFFFF)) == []
    assert quicktime._misure(b"\0" * 4 + struct.pack(">II", 0, 3) + struct.pack(">II", 5, 6)) == [5, 6]


def test_un_campione_dichiarato_enorme_si_legge_solo_fin_dove_arriva_il_file(tmp_path):
    percorso = tmp_path / "campione.mov"
    percorso.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    letto = quicktime.leggi_campione(percorso, quicktime.Campione(0, 0xFFFFFFFF, 0))
    assert letto is not None and len(letto) == 103


def test_la_ripartizione_dei_campioni_resta_quella_di_prima():
    stsc = b"\0" * 4 + struct.pack(">I", 2) + struct.pack(">III", 1, 3, 1) + struct.pack(">III", 3, 2, 1)
    assert quicktime._quanti_per_chunk(stsc, 5, 100) == [3, 3, 2, 2, 2]
    assert quicktime._quanti_per_chunk(stsc, 5, 8) == [3, 3, 2]
    assert quicktime._quanti_per_chunk(stsc, 5, 7) == [3, 3, 1]
    assert quicktime._quanti_per_chunk(b"", 4, 3) == [1, 1, 1]


def test_un_guasto_qualsiasi_nelle_tabelle_non_rompe_la_lettura(tmp_path, monkeypatch):
    percorso = tmp_path / "guasto.mov"
    percorso.write_bytes(_mov())

    def esplode(*_):
        raise MemoryError()

    monkeypatch.setattr(quicktime, "_componi_campioni", esplode)
    assert quicktime.campioni_jpeg(percorso) == []


@pytest.mark.parametrize("fisso", [1, 5])
def test_un_filmato_normale_si_legge_ancora(tmp_path, fisso):
    percorso = tmp_path / "normale.mov"
    percorso.write_bytes(_mov(fissa=fisso))
    campioni = quicktime.campioni_jpeg(percorso)
    assert len(campioni) == 1
    assert campioni[0].misura == fisso


def _annidato(nome: bytes, livelli: int) -> bytes:
    dentro = b""
    for _ in range(livelli):
        dentro = _atomo(nome, dentro)
    return dentro


@pytest.mark.parametrize("nome", [b"meta", b"trak", b"udta"])
def test_un_filmato_con_atomi_annidati_all_infinito_non_rompe_la_lettura(tmp_path, nome):
    percorso = tmp_path / "annidato.mov"
    percorso.write_bytes(_atomo(b"ftyp", b"qt  \0\0\0\0") + _atomo(b"moov", _annidato(nome, 3000)))
    assert quicktime.leggi(percorso).durata_ms is None
    assert quicktime.chiavi_apple(percorso) == {}
    assert quicktime.codec_video(percorso) is None
    assert quicktime.primo_fotogramma_jpeg(percorso) is None
    assert quicktime.campioni_jpeg(percorso) == []


class _FileCheConta:

    def __init__(self, vero):
        self.vero = vero
        self.massimo = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.vero.close()

    def seek(self, *a):
        return self.vero.seek(*a)

    def read(self, quanto=-1):
        letto = self.vero.read(quanto)
        self.massimo = max(self.massimo, len(letto))
        return letto


def _con_misura_estesa_troppo_corta(nome: bytes) -> bytes:
    return struct.pack(">I", 1) + nome + struct.pack(">Q", 8)


@pytest.mark.parametrize("strada", [(b"mvhd",), (b"trak", b"tkhd"), (b"udta", b"\xa9day"),
                                    (b"meta", b"keys"), (b"trak", b"mdia", b"minf", b"stbl",
                                                         b"stsd")])
def test_un_atomo_con_la_misura_estesa_troppo_corta_non_fa_leggere_tutto_il_filmato(
        tmp_path, monkeypatch, strada):
    percorso = tmp_path / "estesa.mov"
    dentro = _con_misura_estesa_troppo_corta(strada[-1]) + b"\0" * (4 * quicktime.FOGLIA_MASSIMA)
    for contenitore in reversed(strada[:-1]):
        dentro = _atomo(contenitore, dentro)
    percorso.write_bytes(_atomo(b"moov", dentro))
    aperti = []

    def apri(*a, **k):
        aperti.append(_FileCheConta(open(*a, **k)))
        return aperti[-1]

    with monkeypatch.context() as cambio:
        cambio.setattr(quicktime, "open", apri, raising=False)
        cambio.setattr(quicktime, "PEZZO_DA_FRUGARE", 1024)
        quicktime.leggi(percorso)
        quicktime.chiavi_apple(percorso)
        quicktime.codec_video(percorso)
        quicktime.primo_fotogramma_jpeg(percorso)
        quicktime.campioni_jpeg(percorso)
    assert aperti
    assert max(f.massimo for f in aperti) <= quicktime.FOGLIA_MASSIMA


def test_un_atomo_con_la_misura_estesa_giusta_si_legge_ancora(tmp_path):
    corpo = b"\0" * 4 + struct.pack(">IIII", 0, 0, 1000, 5000) + b"\0" * 80
    mvhd = struct.pack(">I", 1) + b"mvhd" + struct.pack(">Q", 16 + len(corpo)) + corpo
    percorso = tmp_path / "estesa_giusta.mov"
    percorso.write_bytes(_atomo(b"moov", mvhd))
    assert quicktime.leggi(percorso).durata_ms == 5000
