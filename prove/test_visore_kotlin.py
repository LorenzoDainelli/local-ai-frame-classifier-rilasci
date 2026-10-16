from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
IL_VISORE = RADICE / "visore"

sys.path.insert(0, str(RADICE / "strumenti"))
import pacchetto_di_prova                                    # noqa: E402

PAROLA = pacchetto_di_prova.PAROLA

PAZIENZA = 900

GRADLE = shutil.which("gradle")
SENZA_GRADLE = pytest.mark.skipif(
    GRADLE is None,
    reason="qui non c'è Gradle: il lettore Kotlin non si può compilare")


@pytest.fixture(scope="session")
def comando() -> Path:
    fatto = subprocess.run(
        [GRADLE, "-p", str(IL_VISORE), "-q", ":computer:installDist"],
        capture_output=True, text=True, timeout=PAZIENZA)
    if fatto.returncode != 0:
        pytest.skip("il lettore Kotlin non si compila qui: "
                    + (fatto.stderr or fatto.stdout or "")[-400:])
    nome = "computer.bat" if os.name == "nt" else "computer"
    dove = IL_VISORE / "computer" / "build" / "install" / "computer" / "bin" / nome
    if not dove.exists():
        pytest.skip("il comando del lettore Kotlin non è stato costruito")
    return dove


def _gesti(comando: Path, cartella: Path, password: str,
           cosa: dict) -> tuple[int, dict]:
    fatto = subprocess.run(
        [str(comando), str(cartella), "--gesti"],
        input=password + "\n" + json.dumps(cosa),
        capture_output=True, text=True, timeout=PAZIENZA)
    return fatto.returncode, json.loads(fatto.stdout)


def _chiedi(comando: Path, cartella: Path, password: str,
            *altro: str) -> tuple[int, dict]:
    fatto = subprocess.run(
        [str(comando), str(cartella), *altro],
        input=password + "\n", capture_output=True, text=True, timeout=PAZIENZA)
    return fatto.returncode, json.loads(fatto.stdout)


@pytest.fixture
def pacchetto_grosso(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    return pacchetto_di_prova.costruisci(tmp_path, grosso=True)


@pytest.fixture
def pacchetto(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    return pacchetto_di_prova.costruisci(tmp_path)


@pytest.fixture
def archivio_del_pacchetto(pacchetto):
    from officina.archivio import accesso

    aperto = accesso.apri("finto")
    yield aperto
    accesso.chiudi(con_copia=False)


def _telefono_e_impronte(archivio, cartella) -> tuple[int, list[str], object]:
    from officina.modello import telefoni
    from officina.telefono import lettore

    with archivio.lettura() as connessione:
        telefono = telefoni.elenco(connessione)[0]["id"]
    with lettore.apri(cartella, PAROLA) as dentro:
        impronte = [r["impronta"] for r in dentro.scatti()]
        return telefono, impronte, dentro.chiave


@SENZA_GRADLE
def test_il_kotlin_legge_quello_che_ci_legge_il_python(comando, pacchetto_grosso):
    atteso = pacchetto_di_prova.racconta(pacchetto_grosso)
    uscita, detto = _chiedi(comando, pacchetto_grosso, PAROLA, "--verifica")

    assert uscita == 0
    assert detto["verifica"]["tutto_a_posto"], detto["verifica"]["guasti"]
    assert detto == atteso


@SENZA_GRADLE
def test_una_foto_da_piu_blocchi_si_legge_a_salti(comando, pacchetto_grosso):
    from officina.telefono import cifratura

    uscita, detto = _chiedi(comando, pacchetto_grosso, PAROLA)
    assert uscita == 0

    grosse = [s for s in detto["scatti"] if s["dimensione"] > cifratura.BLOCCO]
    assert grosse, "questo pacchetto doveva avere una foto da più di un blocco"

    a_cavallo = [p for p in detto["pezzi"] if p["da"] == cifratura.BLOCCO - 50]
    assert a_cavallo and a_cavallo[0]["lungo"] == 100
    assert detto["pezzi"] == pacchetto_di_prova.racconta(pacchetto_grosso)["pezzi"]


@SENZA_GRADLE
def test_la_password_sbagliata_lo_dice_col_suo_codice(comando, pacchetto_grosso):
    uscita, detto = _chiedi(comando, pacchetto_grosso, "una password qualunque")

    assert uscita == 2
    assert detto["errore"] == "password_sbagliata"
    assert PAROLA not in json.dumps(detto)
    assert "qualunque" not in json.dumps(detto)


@SENZA_GRADLE
def test_le_prove_del_lettore_kotlin_passano(comando):
    fatto = subprocess.run([GRADLE, "-p", str(IL_VISORE), "-q", "test"],
                           capture_output=True, text=True, timeout=PAZIENZA)
    assert fatto.returncode == 0, (fatto.stdout or "") + (fatto.stderr or "")


def test_il_pacchetto_di_prova_e_ancora_quello_che_dice(tmp_path):
    dove = tmp_path / "Visore-iPhone"
    pacchetto_di_prova.spacchetta(
        pacchetto_di_prova.IL_PACCHETTO.read_text(encoding="utf-8"), dove)

    atteso = json.loads(
        pacchetto_di_prova.QUELLO_CHE_CI_LEGGO.read_text(encoding="utf-8"))
    assert pacchetto_di_prova.racconta(dove) == atteso


@SENZA_GRADLE
def test_quello_che_scrive_il_kotlin_il_pc_lo_rilegge(comando, pacchetto,
                                                     archivio_del_pacchetto,
                                                     tmp_path):
    from officina.telefono import ritorno as il_ritorno

    telefono, impronte, chiave = _telefono_e_impronte(archivio_del_pacchetto,
                                                      pacchetto)

    uscita, detto = _gesti(comando, pacchetto, PAROLA, {
        "cuori": impronte[:2],
        "raccolte": [{"nome": "quelle da guardare", "impronte": impronte[:3]}],
        "diario": [{"aperto_il": "2026-08-30T21:14:02Z", "durata_s": 1980,
                    "latitudine": 44.4939, "longitudine": 11.3427,
                    "quante_foto": 128}],
    })
    assert uscita == 0, detto
    assert detto["guaio"] is None
    assert set(impronte[:2]) <= {c["impronta"] for c in detto["cuori"]}

    arrivato = il_ritorno.apri(pacchetto, chiave)
    with archivio_del_pacchetto.scrittura() as connessione:
        tornato = il_ritorno.leggi(connessione, telefono, arrivato)

    assert tornato.c_era
    assert not tornato.guai
    assert tornato.cuori_nuovi >= 1
    assert tornato.giornate_di_diario == 1
    assert tornato.raccolte == 2
    assert tornato.foto_nelle_raccolte == 5
    assert tornato.cuori_tolti_applicati == 1

    with archivio_del_pacchetto.lettura() as connessione:
        cuori = {r["impronta"] for r in connessione.execute(
            "SELECT impronta FROM cuori WHERE telefono_id = ? AND tolto_il IS NULL",
            (telefono,))}
        riga = connessione.execute(
            "SELECT durata_s, latitudine, quante_foto FROM diario_visore "
            "WHERE telefono_id = ? AND aperto_il = ?",
            (telefono, "2026-08-30T21:14:02Z")).fetchone()

    assert set(impronte[:2]) <= cuori
    assert riga["durata_s"] == 1980 and riga["quante_foto"] == 128
    assert abs(riga["latitudine"] - 44.4939) < 1e-9


@SENZA_GRADLE
def test_il_giro_si_chiude(comando, pacchetto, archivio_del_pacchetto, tmp_path):
    from officina.telefono import costruzione, ritorno as il_ritorno

    telefono, impronte, chiave = _telefono_e_impronte(archivio_del_pacchetto,
                                                      pacchetto)
    _gesti(comando, pacchetto, PAROLA, {
        "cuori": impronte[:2],
        "raccolte": [{"nome": "quelle da guardare", "impronte": impronte[:2]}],
    })
    arrivato = il_ritorno.apri(pacchetto, chiave)
    with archivio_del_pacchetto.scrittura() as connessione:
        il_ritorno.leggi(connessione, telefono, arrivato)

    costruzione.Travaso(archivio_del_pacchetto, telefono, pacchetto,
                        PAROLA).esegui()

    uscita, detto = _chiedi(comando, pacchetto, PAROLA)
    assert uscita == 0
    assert set(impronte[:2]) <= {c["impronta"] for c in detto["scorta"]["cuori"]}
    nomi = [r["nome"] for r in detto["scorta"]["raccolte"]]
    assert "quelle da guardare" in nomi
    fatta = next(r for r in detto["scorta"]["raccolte"]
                 if r["nome"] == "quelle da guardare")
    assert set(impronte[:2]) <= set(fatta["impronte"])
