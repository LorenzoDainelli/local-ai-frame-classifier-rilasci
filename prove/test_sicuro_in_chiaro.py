from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from officina import registro
from officina.archivio import riserva
from officina.archivio.database import adesso
from officina.sicuro import in_chiaro
from officina.sicuro.in_chiaro import CopiaInChiaro, e_una_copia, leggi, misura, trova

QUANDO = "2024-03-05T06:07:08Z"
MOMENTO = datetime(2024, 3, 5, 6, 7, 8, tzinfo=timezone.utc).timestamp()


def _nessun_disco():
    return []


def _casa(base: Path, nome: str = "archivio_finto") -> Path:
    casa = riserva.dove_va(base, nome)
    casa.mkdir(parents=True)
    return casa


def _scrivi(percorso: Path, dati: bytes | str = b"finto") -> Path:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(dati, str):
        percorso.write_text(dati, "utf-8")
    else:
        percorso.write_bytes(dati)
    return percorso


def _copia_finta(base: Path, nome: str = "archivio_finto", quando: str = QUANDO,
                 database: bool = True) -> Path:
    casa = _casa(base, nome)
    _scrivi(casa / riserva.ELENCO, json.dumps({"radice/foto/uno.jpg": {"dimensione": 3}}))
    _scrivi(casa / riserva.ULTIMA, json.dumps({"quando": quando, "copiati": 2}))
    fine = ".sqlite" if database else ".forziere"
    _scrivi(casa / "archivio" / f"{nome}{fine}", b"d" * 50)
    _scrivi(casa / "foto" / "radice" / "foto" / "uno.jpg", b"abc")
    _scrivi(casa / "foto" / "radice" / "foto" / "sotto" / "due.png", b"x" * 1000)
    return casa


def _fotografia(cartella: Path) -> dict:
    tutto = {}
    for percorso in sorted(cartella.rglob("*")):
        informazioni = os.lstat(percorso)
        dati = percorso.read_bytes() if percorso.is_file() and not percorso.is_symlink() else None
        tutto[str(percorso)] = (informazioni.st_mode, informazioni.st_size,
                                informazioni.st_mtime_ns, dati)
    return tutto


def _collega(da: Path, verso: Path, cartella: bool = False) -> None:
    try:
        os.symlink(verso, da, target_is_directory=cartella)
    except (OSError, NotImplementedError):
        pytest.skip("questo sistema non fa collegamenti")


def test_i_nomi_sono_quelli_della_copia_vecchia():
    assert in_chiaro.CARTELLA == riserva.CARTELLA
    assert in_chiaro.ELENCO == riserva.ELENCO
    assert in_chiaro.ULTIMA == riserva.ULTIMA
    assert in_chiaro.DATABASE == (".sqlite", ".sqlite" + riserva.IN_ARRIVO)
    assert in_chiaro.CHIUSO == (".forziere", ".forziere" + riserva.IN_ARRIVO)
    assert riserva.dove_va(Path("disco"), "x").parent.name == in_chiaro.CARTELLA


def test_una_copia_vera_della_versione_vecchia_si_trova(archivio, tmp_path):
    originali = tmp_path / "originali"
    originali.mkdir()
    with archivio.scrittura() as c:
        for i in range(4):
            dati = f"finto-{i}".encode() * (i + 7)
            percorso = originali / f"foto_{i}.jpg"
            percorso.write_bytes(dati)
            numero = c.execute(
                "INSERT INTO file_media (impronta, dimensione, genere, aggiunto_il) "
                "VALUES (?, ?, 'immagine', ?)",
                (hashlib.blake2b(dati, digest_size=32).hexdigest(), len(dati),
                 adesso())).lastrowid
            c.execute("INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
                      "VALUES (?, ?, ?, ?)", (numero, str(percorso), percorso.name, adesso()))
    disco = tmp_path / "disco"
    disco.mkdir()
    esito = riserva.parti(archivio, disco, in_sottofondo=False)
    assert esito["fase"] == "fatto"
    prima = _fotografia(disco)
    trovate = trova(cartelle=[disco], dischi=_nessun_disco)
    assert _fotografia(disco) == prima
    assert len(trovate) == 1
    copia = trovate[0]
    casa = riserva.dove_va(disco, archivio.dove.nome)
    assert copia.percorso == casa
    vere = [p for p in casa.rglob("*") if p.is_file()]
    assert copia.file == len(vere) and copia.byte == sum(p.stat().st_size for p in vere)
    assert copia.database and copia.finita
    scritto = riserva.ultima(disco, archivio.dove.nome)["quando"]
    atteso = datetime.strptime(scritto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert copia.quando == atteso.timestamp()


@pytest.mark.parametrize("segno", [
    riserva.ELENCO, riserva.ULTIMA, "archivio/a.sqlite", "archivio/a.sqlite.in-arrivo",
    "archivio/a.forziere", "archivio/a.forziere.in-arrivo", "archivio/A.SQLITE",
    "archivio/nome con spazi è.Forziere"])
def test_ogni_segno_basta_da_solo(tmp_path, segno):
    casa = _casa(tmp_path)
    _scrivi(casa / segno, b"{}")
    assert e_una_copia(casa)
    trovate = trova(cartelle=[tmp_path], dischi=_nessun_disco)
    assert [copia.percorso for copia in trovate] == [casa]
    assert trovate[0].database == (segno.lower().startswith("archivio/")
                                   and ".sqlite" in segno.lower())
    assert trovate[0].finita == (segno == riserva.ULTIMA)


@pytest.mark.parametrize("prepara", [
    lambda casa: None,
    lambda casa: _scrivi(casa / "foto" / "x.jpg"),
    lambda casa: (casa / riserva.ELENCO).mkdir(),
    lambda casa: (casa / riserva.ULTIMA).mkdir(),
    lambda casa: (casa / "archivio" / "a.sqlite").mkdir(parents=True),
    lambda casa: _scrivi(casa / "archivio" / "a.sqlite.vecchio"),
    lambda casa: _scrivi(casa / "archivio" / "a.txt"),
    lambda casa: _scrivi(casa / "archivio"),
    lambda casa: _scrivi(casa / "elenco.json.in-arrivo"),
    lambda casa: _scrivi(casa / "sotto" / riserva.ELENCO),
    lambda casa: _scrivi(casa / "sotto" / "archivio" / "a.sqlite"),
])
def test_le_cartelle_che_non_sono_copie_non_si_toccano(tmp_path, prepara):
    casa = _casa(tmp_path)
    prepara(casa)
    prima = _fotografia(tmp_path)
    assert not e_una_copia(casa)
    assert trova(cartelle=[tmp_path], dischi=_nessun_disco) == []
    assert _fotografia(tmp_path) == prima


def test_un_file_al_posto_della_cartella_non_e_una_copia(tmp_path):
    _scrivi(tmp_path / riserva.CARTELLA, b"non sono una cartella")
    assert trova(cartelle=[tmp_path], dischi=_nessun_disco) == []
    altro = tmp_path / "altro"
    _scrivi(altro / riserva.CARTELLA / "file_sciolto.sqlite")
    assert trova(cartelle=[altro], dischi=_nessun_disco) == []
    assert not e_una_copia(tmp_path / "non c'è")
    assert not e_una_copia(altro / riserva.CARTELLA / "file_sciolto.sqlite")


def test_misura_conta_tutti_i_file_anche_in_fondo(tmp_path):
    casa = _copia_finta(tmp_path)
    _scrivi(casa / "foto" / "a" / "b" / "c" / "d" / "e" / "profondo.bin", b"p" * 4321)
    _scrivi(casa / "foto" / "vuoto.bin", b"")
    (casa / "foto" / "cartella vuota").mkdir()
    vere = [p for p in casa.rglob("*") if p.is_file()]
    assert misura(casa) == (len(vere), sum(p.stat().st_size for p in vere))
    assert misura(tmp_path / "non c'è") == (0, 0)


def test_misura_non_segue_i_collegamenti(tmp_path):
    casa = _copia_finta(tmp_path / "copia")
    fuori = tmp_path / "fuori"
    _scrivi(fuori / "grosso.bin", b"g" * 100_000)
    prima = misura(casa)
    _collega(casa / "foto" / "a_un_file.bin", fuori / "grosso.bin")
    _collega(casa / "foto" / "a_una_cartella", fuori, cartella=True)
    _collega(casa / "foto" / "a_se_stessa", casa, cartella=True)
    assert misura(casa) == prima
    assert (fuori / "grosso.bin").stat().st_size == 100_000


def test_una_copia_dietro_un_collegamento_non_si_segue(tmp_path):
    vera = tmp_path / "vera"
    _copia_finta(vera)
    base = tmp_path / "base"
    (base / riserva.CARTELLA).mkdir(parents=True)
    _collega(base / riserva.CARTELLA / "finta", riserva.dove_va(vera, "archivio_finto"),
             cartella=True)
    assert trova(cartelle=[base], dischi=_nessun_disco) == []
    altra = tmp_path / "altra"
    altra.mkdir()
    _collega(altra / riserva.CARTELLA, vera / riserva.CARTELLA, cartella=True)
    assert trova(cartelle=[altra], dischi=_nessun_disco) == []


def test_il_momento_viene_da_ultima(tmp_path):
    casa = _copia_finta(tmp_path)
    os.utime(casa / riserva.ULTIMA, (1, 1))
    copia = leggi(casa)
    assert copia.quando == MOMENTO and copia.finita


@pytest.mark.parametrize("contenuto", [
    b"", b"{", b"[]", b"\"testo\"", b"\xff\xfe\x00", b"{\"quando\": 5}",
    b"{\"quando\": \"ieri\"}", b"{\"quando\": \"2024-13-40T99:99:99Z\"}",
    b"{\"quando\": null}", b"{}", ("[" * 100_000 + "]" * 100_000).encode()[:60_000],
    b"[" * 50_000 + b"]" * 50_000])
def test_un_ultima_strano_non_rompe_niente(tmp_path, contenuto):
    casa = _copia_finta(tmp_path)
    _scrivi(casa / riserva.ULTIMA, contenuto)
    for nome, momento in ((riserva.ELENCO, 1_500_000_000), (riserva.ULTIMA, 1_400_000_000),
                          ("archivio/archivio_finto.sqlite", 1_600_000_000)):
        os.utime(casa / nome, (momento, momento))
    copia = leggi(casa)
    letto = None
    try:
        letto = json.loads(contenuto.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        pass
    assert copia.finita == isinstance(letto, dict)
    assert copia.quando == 1_600_000_000
    assert copia.file == 5


def test_un_ultima_troppo_grande_non_si_legge(tmp_path):
    casa = _copia_finta(tmp_path)
    grande = json.dumps({"quando": QUANDO, "riempi": "x" * in_chiaro.ULTIMA_MASSIMA})
    _scrivi(casa / riserva.ULTIMA, grande)
    os.utime(casa / riserva.ULTIMA, (1_234_567_890, 1_234_567_890))
    for nome in (riserva.ELENCO, "archivio/archivio_finto.sqlite"):
        os.utime(casa / nome, (1_000_000_000, 1_000_000_000))
    copia = leggi(casa)
    assert not copia.finita and copia.quando == 1_234_567_890
    giusto = json.dumps({"quando": QUANDO})
    _scrivi(casa / riserva.ULTIMA, giusto + " " * (in_chiaro.ULTIMA_MASSIMA - len(giusto)))
    assert leggi(casa).finita and leggi(casa).quando == MOMENTO


def test_senza_ultima_il_momento_e_l_ultima_modifica(tmp_path):
    casa = _casa(tmp_path)
    _scrivi(casa / "archivio" / "a.sqlite.in-arrivo", b"a" * 10)
    _scrivi(casa / "archivio" / "b.forziere", b"b" * 10)
    os.utime(casa / "archivio" / "a.sqlite.in-arrivo", (100, 1_700_000_000))
    os.utime(casa / "archivio" / "b.forziere", (100, 1_650_000_000))
    copia = leggi(casa)
    assert copia.quando == 1_700_000_000 and copia.database and not copia.finita
    vuota = _casa(tmp_path / "altra")
    assert leggi(vuota).quando is None


def test_solo_forziere_non_e_un_database_in_chiaro(tmp_path):
    copia = leggi(_copia_finta(tmp_path, database=False))
    assert not copia.database and copia.finita


def test_si_trovano_sul_disco_e_nelle_sue_cartelle(tmp_path):
    disco_d = tmp_path / "D"
    disco_e = tmp_path / "E"
    prima = _copia_finta(disco_d)
    seconda = _copia_finta(disco_d / "Copie", nome="secondo")
    terza = _copia_finta(disco_e / "Backup", nome="terzo")
    _copia_finta(disco_e / "Backup" / "troppo" / "in fondo", nome="no")
    trovate = trova(dischi=lambda: [disco_d, disco_e])
    assert sorted(copia.percorso for copia in trovate) == sorted([prima, seconda, terza])


def test_la_stessa_copia_si_conta_una_volta(tmp_path):
    disco = tmp_path / "D"
    casa = _copia_finta(disco)
    trovate = trova(cartelle=[disco, str(disco), disco / ".", disco / "x" / ".."],
                    dischi=lambda: [disco, disco])
    assert [copia.percorso for copia in trovate] == [casa]


def test_piu_copie_nella_stessa_cartella(tmp_path):
    case = [_copia_finta(tmp_path, nome=nome) for nome in ("uno", "due", "tre è")]
    trovate = trova(cartelle=[tmp_path], dischi=_nessun_disco)
    assert [copia.percorso for copia in trovate] == sorted(case)


@pytest.mark.parametrize("cartelle", [[""], [None], [], ["/questa/non/esiste/proprio"]])
def test_cartelle_vuote_o_sbagliate(cartelle):
    assert trova(cartelle=cartelle, dischi=_nessun_disco) == []


def test_un_disco_che_non_risponde(tmp_path):
    casa = _copia_finta(tmp_path)

    def rotto():
        raise OSError("il disco non risponde")

    assert [c.percorso for c in trova(cartelle=[tmp_path], dischi=rotto)] == [casa]
    assert trova(dischi=lambda: [tmp_path / "staccato"]) == []


def test_senza_dischi_usa_tutti_quelli_del_computer(tmp_path, monkeypatch):
    casa = _copia_finta(tmp_path / "F")
    monkeypatch.setattr(in_chiaro, "tutti_i_dischi", lambda: [tmp_path / "F"])
    assert [copia.percorso for copia in trova()] == [casa]


def test_senza_misurare(tmp_path):
    _copia_finta(tmp_path)
    copia, = trova(cartelle=[tmp_path], dischi=_nessun_disco, misurale=False)
    assert (copia.file, copia.byte) == (0, 0) and copia.finita


def test_a_parole_si_scrive_in_json(tmp_path):
    copia, = trova(cartelle=[_copia_finta(tmp_path).parent.parent], dischi=_nessun_disco)
    parole = copia.a_parole()
    assert json.loads(json.dumps(parole)) == parole
    assert set(parole) == {"percorso", "file", "byte", "quando", "database", "finita"}
    assert parole["percorso"] == str(copia.percorso)
    assert isinstance(copia, CopiaInChiaro)


def test_non_cancella_niente_e_non_scrive_niente(tmp_path, monkeypatch):
    for nome in ("uno", "due"):
        _copia_finta(tmp_path, nome=nome)
    _casa(tmp_path, "non è una copia")
    _scrivi(tmp_path / "sciolto.txt", "x")
    prima = _fotografia(tmp_path)
    vietati = []
    for nome in ("unlink", "remove", "rmdir", "rename", "replace"):
        monkeypatch.setattr(os, nome, lambda *a, _n=nome, **k: vietati.append(_n))
    vero_open = open

    def solo_lettura(file, modo="r", *a, **k):
        if any(lettera in modo for lettera in "wax+"):
            vietati.append(("open", file))
        return vero_open(file, modo, *a, **k)

    monkeypatch.setattr("builtins.open", solo_lettura)
    assert len(trova(cartelle=[tmp_path], dischi=_nessun_disco)) == 2
    monkeypatch.undo()
    assert vietati == []
    assert _fotografia(tmp_path) == prima


def test_nel_registro_non_finiscono_nomi(tmp_path, monkeypatch):
    scritti = []
    for nome in ("evento", "errore", "avviso"):
        if hasattr(registro, nome):
            monkeypatch.setattr(registro, nome, lambda *a, **k: scritti.append((a, k)))
    _copia_finta(tmp_path, nome="nome segreto")
    trova(cartelle=[tmp_path], dischi=_nessun_disco)
    assert scritti == []


@pytest.mark.skipif(sys.platform == "win32", reason="nomi non validi su Windows")
def test_nomi_strani_sul_disco(tmp_path):
    base = Path(os.fsdecode(bytes(tmp_path) + b"/strano \xff"))
    casa = _copia_finta(base, nome="x")
    strana = casa.parent / os.fsdecode(b"\xfe\xfd")
    _scrivi(strana / riserva.ULTIMA, json.dumps({"quando": QUANDO}))
    _scrivi(casa / "foto" / os.fsdecode(b"\x80.jpg"), b"12345")
    trovate = trova(cartelle=[base], dischi=_nessun_disco)
    assert sorted(copia.percorso for copia in trovate) == sorted([casa, strana])
    assert all(json.dumps(copia.a_parole()) for copia in trovate)


def test_il_rimando_di_windows_non_si_segue(tmp_path, monkeypatch):
    casa = _copia_finta(tmp_path / "uno")
    prima = misura(casa)
    lontana = casa / "foto" / "unita_di_rete"
    _scrivi(lontana / "lontano.bin", b"l" * 9999)
    altra = _copia_finta(tmp_path / "due", nome="altra")
    contenitore = tmp_path / "tre" / riserva.CARTELLA
    _copia_finta(tmp_path / "tre", nome="dietro")
    segno = 1_111_111_111
    for percorso in (lontana, altra, contenitore):
        os.utime(percorso, (segno, segno))
    monkeypatch.setattr(in_chiaro, "_rimando",
                        lambda informazioni: int(informazioni.st_mtime) == segno)
    assert misura(casa) == prima
    basi = [tmp_path / "uno", tmp_path / "due", tmp_path / "tre"]
    assert [copia.percorso for copia in trova(cartelle=basi, dischi=_nessun_disco)] == [casa]
    assert in_chiaro.RIMANDO == 0x400
    assert not in_chiaro._rimando(os.lstat(casa))
