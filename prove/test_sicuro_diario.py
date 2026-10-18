from __future__ import annotations

import random

import pytest

from officina.sicuro import chiavi, diario
from officina.sicuro.diario import Diario, DiarioRovinato


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture
def posti(tmp_path):
    return tmp_path / "diario.ofd", tmp_path / "diario.riserva.ofd"


def _fatti(quanti: int, seme: int = 0) -> list[dict]:
    caso = random.Random(seme)
    return [{"fatto": "prova", "numero": i, "testo": f"IMG_{caso.randrange(10 ** 6)}.jpg",
             "pieno": "x" * caso.randrange(0, 300)} for i in range(quanti)]


def _scrivi(posti, chiave, fatti, a_gruppi: int = 7, generazione: int = 3) -> None:
    nuovo = Diario.nuovo(*posti, chiave, generazione)
    for inizio in range(0, len(fatti), a_gruppi):
        nuovo.aggiungi(fatti[inizio:inizio + a_gruppi])


def _riapri(posti, chiave, generazione: int = 3):
    return Diario.apri(*posti, chiave, generazione)


def _confini(dati: bytes) -> list[tuple[int, int]]:
    righe = []
    dove = diario.TESTA.size
    while dove < len(dati):
        lungo, _ = diario.RIGA.unpack_from(dati, dove)
        righe.append((dove, dove + diario.RIGA.size + lungo))
        dove += diario.RIGA.size + lungo
    return righe


@pytest.mark.parametrize("quanti", [0, 1, 2, 13, 100])
@pytest.mark.parametrize("a_gruppi", [1, 5, 1000])
def test_quello_che_si_scrive_si_rilegge_in_ordine(posti, chiave, quanti, a_gruppi):
    fatti = _fatti(quanti)
    _scrivi(posti, chiave, fatti, a_gruppi)
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti
    assert riaperto.righe == quanti
    assert not riaperto.riparato and not riaperto.buchi and not riaperto.rotto
    assert posti[0].read_bytes() == posti[1].read_bytes()


def test_si_riapre_e_si_continua_tante_volte(posti, chiave):
    tutti = []
    Diario.nuovo(*posti, chiave, 3)
    for giro in range(8):
        aperto, letti = _riapri(posti, chiave)
        assert letti == tutti
        nuovi = _fatti(giro + 1, giro)
        aperto.aggiungi(nuovi)
        tutti += nuovi
    assert _riapri(posti, chiave)[1] == tutti


def test_lettere_strane_e_righe_lunghe(posti, chiave):
    fatti = [{"nome": "perché così 🐶 €.heic"}, {"lungo": "y" * 1_000_000},
             {"vuoto": {}}, {"lista": [None, True, 1.5, "\x00"]}]
    _scrivi(posti, chiave, fatti)
    assert _riapri(posti, chiave)[1] == fatti


def test_nomi_con_lettere_rotte_tornano_uguali(posti, chiave):
    fatti = [{"nome": "Mare\udc80/IMG_\ud800 1.jpg"}, {"\udfff": "\udcff"}]
    _scrivi(posti, chiave, fatti)
    assert _riapri(posti, chiave)[1] == fatti


def test_una_riga_troppo_lunga_non_rovina_il_diario(posti, chiave, monkeypatch):
    monkeypatch.setattr(diario, "MASSIMO", 1000)
    aperto = Diario.nuovo(*posti, chiave, 3)
    aperto.aggiungi([{"a": 1}])
    prima = posti[0].read_bytes()
    with pytest.raises(Exception):
        aperto.aggiungi([{"b": 2}, {"lungo": "z" * 5000}])
    assert posti[0].read_bytes() == prima
    aperto.aggiungi([{"c": 3}])
    assert _riapri(posti, chiave)[1] == [{"a": 1}, {"c": 3}]


def test_da_fuori_non_si_legge_niente(posti, chiave):
    _scrivi(posti, chiave, [{"nome": "Vacanze_Sardegna_segreto.jpg"}])
    for percorso in posti:
        dati = percorso.read_bytes()
        assert b"Sardegna" not in dati and b"nome" not in dati


def test_ogni_riga_ha_il_suo_nonce(posti, chiave):
    _scrivi(posti, chiave, [{"stesso": 1}] * 200)
    dati = posti[0].read_bytes()
    nonce = {dati[inizio + diario.RIGA.size:inizio + diario.RIGA.size + diario.NONCE]
             for inizio, _ in _confini(dati)}
    assert len(nonce) == 200


@pytest.mark.parametrize("taglio", range(1, 60, 3))
def test_una_scrittura_interrotta_nella_prima_copia(posti, chiave, taglio):
    fatti = _fatti(10)
    _scrivi(posti, chiave, fatti[:9])
    aperto, _ = _riapri(posti, chiave)
    aperto.aggiungi(fatti[9:])
    dati = posti[0].read_bytes()
    ultima = _confini(dati)[-1]
    posti[0].write_bytes(dati[:min(ultima[1] - 1, ultima[0] + taglio)])
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti and riaperto.riparato
    assert posti[0].read_bytes() == posti[1].read_bytes() == dati


@pytest.mark.parametrize("taglio", range(1, 60, 3))
def test_una_scrittura_interrotta_nella_seconda_copia(posti, chiave, taglio):
    fatti = _fatti(10)
    _scrivi(posti, chiave, fatti)
    dati = posti[1].read_bytes()
    ultima = _confini(dati)[-1]
    posti[1].write_bytes(dati[:min(ultima[1] - 1, ultima[0] + taglio)])
    assert _riapri(posti, chiave)[1] == fatti


@pytest.mark.parametrize("taglio", range(0, 40, 4))
def test_corrente_staccata_mentre_si_scrive_la_prima(posti, chiave, taglio):
    fatti = _fatti(6)
    _scrivi(posti, chiave, fatti[:5])
    dati = posti[0].read_bytes()
    aperto, _ = _riapri(posti, chiave)
    aperto.aggiungi(fatti[5:])
    nuovo = posti[0].read_bytes()
    posti[0].write_bytes(nuovo[:len(dati) + taglio])
    posti[1].write_bytes(dati)
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti[:5]
    riaperto.aggiungi([{"dopo": True}])
    assert _riapri(posti, chiave)[1] == [*fatti[:5], {"dopo": True}]


@pytest.mark.parametrize("seme", range(40))
def test_un_byte_rovinato_in_una_copia_si_ripara(posti, chiave, seme):
    fatti = _fatti(20, seme)
    _scrivi(posti, chiave, fatti)
    caso = random.Random(seme)
    quale = posti[caso.randrange(2)]
    dati = bytearray(quale.read_bytes())
    dati[caso.randrange(len(dati))] ^= 1 << caso.randrange(8)
    quale.write_bytes(bytes(dati))
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti and riaperto.riparato and not riaperto.rotto
    assert posti[0].read_bytes() == posti[1].read_bytes()


@pytest.mark.parametrize("seme", range(20))
def test_danni_in_tutte_e_due_le_copie_in_righe_diverse(posti, chiave, seme):
    fatti = _fatti(30, seme)
    _scrivi(posti, chiave, fatti)
    righe = _confini(posti[0].read_bytes())
    caso = random.Random(seme)
    prima, seconda = caso.sample(range(len(righe)), 2)
    for percorso, riga in ((posti[0], righe[prima]), (posti[1], righe[seconda])):
        dati = bytearray(percorso.read_bytes())
        dati[caso.randrange(riga[0] + diario.RIGA.size, riga[1])] ^= 0xFF
        percorso.write_bytes(bytes(dati))
    assert _riapri(posti, chiave)[1] == fatti


@pytest.mark.parametrize("riga", [0, 5, 18])
def test_la_stessa_riga_rovinata_in_tutte_e_due_e_un_buco(posti, chiave, riga):
    fatti = _fatti(20)
    _scrivi(posti, chiave, fatti)
    confine = _confini(posti[0].read_bytes())[riga]
    for percorso in posti:
        dati = bytearray(percorso.read_bytes())
        dati[confine[1] - 3] ^= 0x55
        percorso.write_bytes(bytes(dati))
    prima = [percorso.read_bytes() for percorso in posti]
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti[:riga] + fatti[riga + 1:]
    assert riaperto.buchi == 1 and riaperto.rotto
    assert [percorso.read_bytes() for percorso in posti] == prima
    with pytest.raises(DiarioRovinato):
        riaperto.aggiungi([{"no": 1}])


def test_l_ultima_riga_rovinata_in_tutte_e_due_si_toglie(posti, chiave):
    fatti = _fatti(5)
    _scrivi(posti, chiave, fatti)
    for percorso in posti:
        dati = bytearray(percorso.read_bytes())
        dati[-2] ^= 1
        percorso.write_bytes(bytes(dati))
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti[:4] and not riaperto.rotto
    riaperto.aggiungi([{"nuovo": 1}])
    assert _riapri(posti, chiave)[1] == [*fatti[:4], {"nuovo": 1}]


@pytest.mark.parametrize("dove", [0, 9, 20, 40, 60, 63])
def test_l_inizio_rovinato_di_una_copia(posti, chiave, dove):
    fatti = _fatti(4)
    _scrivi(posti, chiave, fatti)
    dati = bytearray(posti[0].read_bytes())
    dati[dove] ^= 0x10
    posti[0].write_bytes(bytes(dati))
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti and riaperto.riparato


def test_l_inizio_rovinato_in_tutte_e_due(posti, chiave):
    _scrivi(posti, chiave, _fatti(4))
    for percorso in posti:
        dati = bytearray(percorso.read_bytes())
        dati[3] ^= 1
        percorso.write_bytes(bytes(dati))
    with pytest.raises(DiarioRovinato):
        _riapri(posti, chiave)


def test_una_copia_sparita(posti, chiave):
    fatti = _fatti(4)
    _scrivi(posti, chiave, fatti)
    posti[1].unlink()
    riaperto, letti = _riapri(posti, chiave)
    assert letti == fatti and riaperto.riparato
    assert posti[1].read_bytes() == posti[0].read_bytes()


def test_con_un_altra_chiave_non_si_tocca_niente(posti, chiave):
    _scrivi(posti, chiave, _fatti(4))
    prima = [percorso.read_bytes() for percorso in posti]
    with pytest.raises(DiarioRovinato):
        _riapri(posti, chiavi.Chiave(bytes(32)))
    assert [percorso.read_bytes() for percorso in posti] == prima


def test_un_altra_generazione_non_si_scambia(posti, chiave):
    _scrivi(posti, chiave, _fatti(4), generazione=3)
    with pytest.raises(DiarioRovinato):
        _riapri(posti, chiave, generazione=4)


def test_righe_scambiate_di_posto_non_passano(posti, chiave):
    fatti = _fatti(6)
    _scrivi(posti, chiave, fatti)
    for percorso in posti:
        dati = percorso.read_bytes()
        righe = _confini(dati)
        pezzi = [dati[inizio:fine] for inizio, fine in righe]
        pezzi[1], pezzi[2] = pezzi[2], pezzi[1]
        percorso.write_bytes(dati[:diario.TESTA.size] + b"".join(pezzi))
    riaperto, letti = _riapri(posti, chiave)
    assert letti == [fatti[0], *fatti[3:]] and riaperto.buchi == 2


def test_una_riga_di_un_altro_diario_non_passa(tmp_path, chiave):
    primo = (tmp_path / "a.ofd", tmp_path / "a.r.ofd")
    secondo = (tmp_path / "b.ofd", tmp_path / "b.r.ofd")
    _scrivi(primo, chiave, [{"a": 1}, {"a": 2}])
    _scrivi(secondo, chiave, [{"b": 1}, {"b": 2}])
    estranea = secondo[0].read_bytes()[diario.TESTA.size:]
    for percorso in primo:
        percorso.write_bytes(percorso.read_bytes() + estranea)
    assert _riapri(primo, chiave)[1] == [{"a": 1}, {"a": 2}]


def test_non_si_crea_sopra_un_diario_che_c_e(posti, chiave):
    Diario.nuovo(*posti, chiave, 3)
    with pytest.raises(Exception):
        Diario.nuovo(*posti, chiave, 3)


def test_se_la_seconda_copia_non_si_scrive_il_diario_si_ferma(posti, chiave):
    aperto = Diario.nuovo(*posti, chiave, 3)
    posti[1].unlink()
    posti[1].mkdir()
    with pytest.raises(OSError):
        aperto.aggiungi([{"a": 1}])
    assert aperto.rotto
    with pytest.raises(DiarioRovinato):
        aperto.aggiungi([{"a": 2}])


@pytest.mark.parametrize("seme", range(150))
def test_danni_a_caso_non_inventano_mai_fatti(posti, chiave, seme):
    fatti = _fatti(25, seme)
    _scrivi(posti, chiave, fatti, a_gruppi=4)
    caso = random.Random(seme)
    for _ in range(caso.randint(1, 6)):
        percorso = posti[caso.randrange(2)]
        dati = bytearray(percorso.read_bytes())
        if not dati:
            continue
        come = caso.randrange(4)
        dove = caso.randrange(len(dati))
        if come == 0:
            dati[dove] ^= 1 << caso.randrange(8)
        elif come == 1:
            del dati[dove:]
        elif come == 2:
            dati[dove:dove + 50] = caso.randbytes(min(50, len(dati) - dove))
        else:
            dati[dove:dove] = caso.randbytes(caso.randrange(1, 30))
        percorso.write_bytes(bytes(dati))
    try:
        _, letti = _riapri(posti, chiave)
    except DiarioRovinato:
        return
    rimasti = iter(fatti)
    for fatto in letti:
        assert any(fatto == atteso for atteso in rimasti)
