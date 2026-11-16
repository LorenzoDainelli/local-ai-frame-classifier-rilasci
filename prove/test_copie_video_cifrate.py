from __future__ import annotations

from pathlib import Path

import pytest

from officina.immagini import compatibile
from officina.miglioria import da_guardare
from officina.programma import archivio_sicuro
from officina.sicuro import cache_cifrata
from prove.test_miniature_cifrate import casa, cifrate, costo_leggero
from prove.test_sicuro_servizio import ATTESA, PAROLA

__all__ = ["casa", "cifrate", "costo_leggero"]

VIDEO = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40
IMPRONTA = "a" * 64


@pytest.fixture
def finta(monkeypatch):
    fatte = []

    def ricodifica(originale, verso, al_passo=None, *altro):
        fatte.append(Path(verso))
        Path(verso).write_bytes(VIDEO)

    monkeypatch.setattr(compatibile, "si_puo_fare", lambda: True)
    monkeypatch.setattr(compatibile, "_ricodifica", ricodifica)
    monkeypatch.setattr(da_guardare, "ricodifica",
                        lambda sorgente, arrivo, fermati=None, al_passo=None:
                        ricodifica(sorgente, arrivo))
    monkeypatch.setattr(da_guardare, "si_apre", lambda file: False)
    return fatte


def _chiudi(cifrate) -> None:
    assert cifrate.casa.archivio.chiudi(ATTESA)
    archivio_sicuro.butta_le_copie_di_passaggio(cifrate.archivio.dove)


def _in_chiaro(archivio) -> list[Path]:
    passaggio = compatibile.di_passaggio(archivio.dove)
    return [p for p in archivio.dove.miniature.rglob("*")
            if p.is_file() and VIDEO[:64] in p.read_bytes()
            and passaggio not in p.parents]


def test_la_copia_del_video_si_salva_solo_cifrata(cifrate, finta, tmp_path):
    archivio = cifrate.archivio
    originale = tmp_path / "originale.mov"
    originale.write_bytes(b"originale")
    fatta = compatibile.fai(archivio, IMPRONTA, originale)
    assert fatta is not None and fatta.read_bytes() == VIDEO
    assert compatibile.di_passaggio(archivio.dove) in fatta.parents
    persistente = archivio.percorso_copia_video(archivio.nome_copia_video(IMPRONTA))
    assert not persistente.exists()
    assert cache_cifrata.cifrato(persistente).is_file()
    assert _in_chiaro(archivio) == []
    assert finta[0].parent == fatta.parent
    assert compatibile.pronta(archivio, IMPRONTA)
    assert compatibile.gia_fatta(archivio, IMPRONTA) == fatta
    assert compatibile.fai(archivio, IMPRONTA, originale) == fatta
    assert len(finta) == 1


def test_chiuso_l_archivio_la_copia_aperta_sparisce_e_torna(cifrate, finta, tmp_path):
    archivio = cifrate.archivio
    originale = tmp_path / "originale.mov"
    originale.write_bytes(b"originale")
    fatta = compatibile.fai(archivio, IMPRONTA, originale)
    _chiudi(cifrate)
    assert not fatta.exists()
    assert compatibile.gia_fatta(archivio, IMPRONTA) is None
    assert not compatibile.pronta(archivio, IMPRONTA)
    assert compatibile.fai(archivio, "b" * 64, originale) is None
    assert len(finta) == 1
    assert _in_chiaro(archivio) == []
    cifrate.casa.archivio.apri(PAROLA)
    di_nuovo = compatibile.gia_fatta(archivio, IMPRONTA)
    assert di_nuovo is not None and di_nuovo.read_bytes() == VIDEO
    assert len(finta) == 1


def test_una_copia_cifrata_rovinata_non_si_mostra_e_non_si_cancella(cifrate, finta,
                                                                     tmp_path):
    archivio = cifrate.archivio
    originale = tmp_path / "originale.mov"
    originale.write_bytes(b"originale")
    fatta = compatibile.fai(archivio, IMPRONTA, originale)
    fatta.unlink()
    persistente = archivio.percorso_copia_video(archivio.nome_copia_video(IMPRONTA))
    sicuro = cache_cifrata.cifrato(persistente)
    blob = bytearray(sicuro.read_bytes())
    blob[-1] ^= 1
    sicuro.write_bytes(bytes(blob))
    assert compatibile.gia_fatta(archivio, IMPRONTA) is None
    assert sicuro.read_bytes() == bytes(blob)


def test_una_copia_vecchia_in_chiaro_si_cifra_quando_si_guarda(cifrate):
    archivio = cifrate.archivio
    persistente = archivio.percorso_copia_video(archivio.nome_copia_video(IMPRONTA))
    persistente.parent.mkdir(parents=True, exist_ok=True)
    persistente.write_bytes(VIDEO)
    aperta = compatibile.gia_fatta(archivio, IMPRONTA)
    assert aperta.read_bytes() == VIDEO
    assert not persistente.exists() and cache_cifrata.cifrato(persistente).is_file()
    assert _in_chiaro(archivio) == []


def test_le_copie_da_guardare_del_miglioramento_sono_cifrate(cifrate, finta, tmp_path):
    archivio = cifrate.archivio
    dopo = tmp_path / "dopo.mov"
    dopo.write_bytes(b"dopo")
    lati = {da_guardare.DOPO: dopo}
    assert da_guardare.mancano(archivio.dove, 7, lati) == [da_guardare.DOPO]
    assert da_guardare.fai(archivio.dove, 7, lati) == [da_guardare.DOPO]
    persistente = da_guardare.percorso(archivio.dove, 7, da_guardare.DOPO)
    assert not persistente.exists() and cache_cifrata.cifrato(persistente).is_file()
    assert _in_chiaro(archivio) == []
    assert da_guardare.mancano(archivio.dove, 7, lati) == []
    mostrata = da_guardare.da_mostrare(archivio.dove, 7, da_guardare.DOPO, dopo)
    assert mostrata.read_bytes() == VIDEO
    _chiudi(cifrate)
    assert not cache_cifrata.copia_aperta_in(archivio.dove, persistente).exists()
    assert da_guardare.da_mostrare(archivio.dove, 7, da_guardare.DOPO, dopo) is None
    with pytest.raises(Exception):
        da_guardare.fai(archivio.dove, 8, lati)
    assert len(finta) == 1
    cifrate.casa.archivio.apri(PAROLA)
    assert da_guardare.da_mostrare(archivio.dove, 7, da_guardare.DOPO,
                                   dopo).read_bytes() == VIDEO
    assert da_guardare.togli(archivio.dove, 7) >= 2
    assert not cache_cifrata.cifrato(persistente).exists()
    assert not cache_cifrata.copia_aperta_in(archivio.dove, persistente).exists()


def test_le_copie_vecchie_dei_video_si_cifrano_in_sottofondo(cifrate, monkeypatch):
    archivio = cifrate.archivio
    vecchie = [archivio.dove.miniature / "revisione" / "3-prima.mp4",
               archivio.dove.miniature / "revisione-ritocco" / "1-1-2-dopo.mp4",
               archivio.percorso_copia_video(archivio.nome_copia_video(IMPRONTA))]
    parziale = archivio.dove.miniature / "revisione" / "4-dopo.parziale.mp4"
    for percorso in [*vecchie, parziale]:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(VIDEO)
    monkeypatch.setattr(cache_cifrata, "RIPOSO", 0)
    cache_cifrata.in_sottofondo(archivio).join(30)
    for percorso in vecchie:
        assert not percorso.exists() and cache_cifrata.cifrato(percorso).is_file()
        aperta = cache_cifrata.copia_da_guardare(archivio.dove, percorso)
        assert aperta.read_bytes() == VIDEO
    assert parziale.exists()


def test_le_copie_da_guardare_del_ritocco_sono_cifrate(cifrate, finta, tmp_path):
    from officina.web import rivedi_ritocco

    archivio = cifrate.archivio
    lavoro = {"id": 5, "versione": 2}
    sorgente = tmp_path / "prima.mov"
    sorgente.write_bytes(b"prima")
    copia = rivedi_ritocco._copia(archivio, lavoro, 9, rivedi_ritocco.PRIMA)
    assert not rivedi_ritocco._c_e(archivio, lavoro, 9, rivedi_ritocco.PRIMA, sorgente)
    fatta = cache_cifrata.copia_da_fare(archivio.dove, copia)
    fatta.parent.mkdir(parents=True, exist_ok=True)
    fatta.write_bytes(VIDEO)
    cache_cifrata.copia_salva(archivio.dove, copia, fatta)
    assert not copia.exists() and cache_cifrata.cifrato(copia).is_file()
    assert _in_chiaro(archivio) == []
    assert rivedi_ritocco._c_e(archivio, lavoro, 9, rivedi_ritocco.PRIMA, sorgente)
    vista = rivedi_ritocco._da_vedere(archivio, lavoro, 9, rivedi_ritocco.PRIMA, sorgente)
    assert vista.read_bytes() == VIDEO
    _chiudi(cifrate)
    assert rivedi_ritocco._da_vedere(archivio, lavoro, 9, rivedi_ritocco.PRIMA,
                                     sorgente) is None
    cifrate.casa.archivio.apri(PAROLA)
    assert rivedi_ritocco._da_vedere(archivio, lavoro, 9, rivedi_ritocco.PRIMA,
                                     sorgente).read_bytes() == VIDEO
    assert rivedi_ritocco.togli_le_copie(archivio, 5) == 1
    assert not cache_cifrata.cifrato(copia).exists()
    assert not cache_cifrata.copia_aperta_in(archivio.dove, copia).exists()


def test_due_richieste_insieme_decifrano_la_copia_una_volta_sola(cifrate, monkeypatch):
    import threading

    archivio = cifrate.archivio
    persistente = archivio.percorso_copia_video(archivio.nome_copia_video(IMPRONTA))
    fatta = cache_cifrata.copia_da_fare(archivio.dove, persistente)
    fatta.parent.mkdir(parents=True, exist_ok=True)
    fatta.write_bytes(VIDEO)
    cache_cifrata.copia_salva(archivio.dove, persistente, fatta)
    cache_cifrata.copia_aperta_in(archivio.dove, persistente).unlink()
    letture = []
    vera = cache_cifrata.leggi

    def contata(*argomenti, **opzioni):
        letture.append(1)
        return vera(*argomenti, **opzioni)

    monkeypatch.setattr(cache_cifrata, "leggi", contata)
    viste = []
    fili = [threading.Thread(target=lambda: viste.append(
        cache_cifrata.copia_da_guardare(archivio.dove, persistente))) for _ in range(4)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join(30)
    assert len(viste) == 4 and all(v.read_bytes() == VIDEO for v in viste)
    assert letture == [1]
