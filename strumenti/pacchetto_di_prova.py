#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import os
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent

PAROLA = "tre parole che ricordi"

DOVE_VA = RADICE / "visore" / "computer" / "src" / "test" / "resources"
IL_PACCHETTO = DOVE_VA / "pacchetto-di-prova.txt"
QUELLO_CHE_CI_LEGGO = DOVE_VA / "pacchetto-di-prova.json"

LARGHEZZA = 76


def costruisci(dove: Path, grosso: bool = False) -> Path:
    dove = Path(dove)
    os.environ["OFFICINA_ARCHIVIO"] = str(dove / "archivio")
    sys.path.insert(0, str(RADICE))

    from officina.archivio import accesso
    from officina.archivio.database import adesso
    from officina.importazione.motore import Motore
    from officina.modello import etichette, nodi, persone, telefoni
    from officina.telefono import costruzione

    foto = _foto_finte(dove / "foto", grosso)

    accesso.chiudi(con_copia=False)
    archivio = accesso.apri("finto")
    motore = Motore(archivio)
    motore.prepara([foto])
    motore.esegui()

    with archivio.scrittura() as connessione:
        cartoline = nodi.crea(connessione, "cartoline")
        francobolli = nodi.crea(connessione, "francobolli", cartoline)
        nodi.crea(connessione, "vecchi", francobolli)
        gite = nodi.crea(connessione, "gite")
        brughiera = nodi.crea(connessione, "brughiera", gite)

        quali = [r["id"] for r in connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "AND sembra_schermata = 0 ORDER BY id")]
        for numero, scatto in enumerate(quali):
            etichette.metti(connessione, scatto,
                            [francobolli, brughiera, gite][numero % 3], "si")

        for nome in ("Ada", "Bruno"):
            persona = persone.crea(connessione, nome)
            for scatto in quali[:3]:
                persone.metti_a_mano(connessione, scatto, persona)

        connessione.execute(
            "INSERT INTO luoghi (nome, centro_lat, centro_lon, raggio_metri, "
            "quanti, nato_il) VALUES ('il molo', 43.7696, 11.2558, "
            "200, 3, ?)", (adesso(),))
        luogo = connessione.execute("SELECT max(id) FROM luoghi").fetchone()[0]
        connessione.execute(
            "UPDATE scatti SET luogo_id = ? WHERE latitudine IS NOT NULL", (luogo,))

        telefono = telefoni.crea(connessione, "iPhone", "ios")

        impronte = [r["impronta"] for r in connessione.execute(
            "SELECT impronta FROM file_media ORDER BY impronta")]
        for impronta in impronte[:2]:
            connessione.execute(
                "INSERT INTO cuori (telefono_id, impronta, messo_il, tornato_il) "
                "VALUES (?, ?, ?, ?)",
                (telefono, impronta, "2021-05-01T10:00:00Z", adesso()))
        connessione.execute(
            "INSERT INTO cuori (telefono_id, impronta, messo_il, tornato_il, "
            "tolto_il) VALUES (?, ?, ?, ?, ?)",
            (telefono, impronte[2], "2021-05-01T10:05:00Z", adesso(), adesso()))
        connessione.execute(
            "INSERT INTO raccolte (telefono_id, numero, nome, creata_il, "
            "tornata_il) VALUES (?, 1, 'quelle da stampare', ?, ?)",
            (telefono, "2021-05-02T09:00:00Z", adesso()))
        raccolta = connessione.execute("SELECT max(id) FROM raccolte").fetchone()[0]
        for impronta in impronte[:2]:
            connessione.execute(
                "INSERT INTO raccolte_scatti (raccolta_id, impronta) VALUES (?, ?)",
                (raccolta, impronta))

    cartella = dove / "Visore-iPhone"
    costruzione.Travaso(archivio, telefono, cartella, PAROLA).esegui()
    accesso.chiudi(con_copia=False)
    return cartella


def _foto_finte(dove: Path, grosso: bool = False) -> Path:
    import io
    from datetime import datetime

    from officina.finto import contenitore_video, generatore, immagini

    dove.mkdir(parents=True, exist_ok=True)
    misura = (320, 240)
    firenze = (43.7696, 11.2558)

    def scrivi(nome: str, tema: str, seme: int, quando, luogo=None,
               identificatore=None) -> None:
        immagine = immagini.disegna(tema, seme, misura)
        appoggio = io.BytesIO()
        exif = (generatore.costruisci_exif(quando, 120, "iPhone 13",
                                           identificatore, luogo)
                if quando is not None else None)
        if exif is None:
            immagine.save(appoggio, "JPEG", quality=70)
        else:
            immagine.save(appoggio, "JPEG", quality=70, exif=exif)
        (dove / nome).write_bytes(appoggio.getvalue())

    scrivi("IMG_2001.JPG", "tema_a", 1, datetime(2021, 3, 14, 10, 30), firenze)
    scrivi("IMG_2002.JPG", "tema_b", 2, datetime(2021, 3, 14, 18, 5))
    scrivi("IMG_2003.JPG", "tema_c", 3, datetime(2021, 4, 2, 9, 15), firenze)

    quando = datetime(2021, 4, 2, 19, 40)
    identificatore = "ABCDEF012345-FINTO-2004"
    scrivi("IMG_2004.JPG", "tema_d", 4, quando, firenze, identificatore)
    fotogrammi = immagini.fotogrammi_video("tema_d", 4, 6, (160, 120))
    contenitore_video.scrivi(dove / "IMG_2004.MOV", fotogrammi, 160, 120, 6,
                             identificatore, quando, 120, "iPhone 13")

    scrivi("IMG_2005.JPG", "tema_e", 5, None)

    if grosso:
        import os

        from PIL import Image

        immagine = Image.frombytes("RGB", (1400, 1000), os.urandom(1400 * 1000 * 3))
        appoggio = io.BytesIO()
        immagine.save(appoggio, "JPEG", quality=92,
                      exif=generatore.costruisci_exif(
                          datetime(2021, 4, 3, 12, 0), 120, "iPhone 13", None, None))
        (dove / "IMG_2006.JPG").write_bytes(appoggio.getvalue())

    return dove


def racconta(cartella: Path, password: str = PAROLA) -> dict:
    sys.path.insert(0, str(RADICE))
    from officina.telefono import lettore

    with lettore.apri(cartella, password) as pacchetto:
        detto = {
            "telefono": pacchetto.carta.telefono,
            "archivio": pacchetto.carta.archivio,
            "completo": pacchetto.completo,
            "versione_formato": pacchetto.carta.versione_formato,
            "quanti": pacchetto.quanti(),
            "giorni": [{"giorno": g["giorno"], "quanti": g["quanti"],
                        "luoghi": g["luoghi"]} for g in pacchetto.giorni()],
            "nodi": [r["nome"] for r in pacchetto.nodi()],
            "persone": [r["nome"] for r in pacchetto.persone()],
            "scatti": [{"id": r["id"], "impronta": r["impronta"],
                        "genere": r["genere"], "giorno": r["giorno"],
                        "posto": r["posto"], "dimensione": r["dimensione"]}
                       for r in pacchetto.scatti(quanti=500)],
            "scorta": _scorta(pacchetto),
            "informazioni": {c: str(v)
                             for c, v in pacchetto.informazioni().items()},
            "dettagli": _dettagli(pacchetto),
            "cerca": _cerca(pacchetto, _parola(pacchetto)),
            "cerca_anno": _cerca(pacchetto, _anno(pacchetto)),
        }
        detto["pezzi"] = _pezzi(pacchetto, detto["scatti"])
        esito = pacchetto.verifica()
        detto["verifica"] = {
            "letti": esito.letti,
            "peso": esito.peso,
            "tutto_a_posto": esito.tutto_a_posto,
            "guasti": [{"posto": g.posto, "perche": g.perche}
                       for g in esito.guasti],
        }
        return detto


def _parola(pacchetto) -> str:
    nodi = pacchetto.nodi()
    return nodi[0]["nome"] if nodi else ""


def _anno(pacchetto) -> str:
    for giorno in pacchetto.giorni():
        if giorno["giorno"]:
            return giorno["giorno"][:4]
    return ""


def _dettagli(pacchetto) -> dict:
    scatti = pacchetto.scatti(quanti=1)
    if not scatti:
        return {}
    dentro = pacchetto.dettagli(scatti[0]["id"])
    return {
        "id": scatti[0]["id"],
        "luogo": dentro["luogo"]["nome"] if dentro["luogo"] else None,
        "nota": dentro["scatto"]["nota"],
        "nodi": [[r["nome"], r["origine"]] for r in dentro["nodi"]],
        "persone": [[r["nome"], r["origine"]] for r in dentro["persone"]],
    }


def _cerca(pacchetto, testo: str) -> dict:
    trovato = pacchetto.cerca(testo)
    return {
        "testo": testo,
        "nodi": [r["nome"] for r in trovato["nodi"]],
        "persone": [r["nome"] for r in trovato["persone"]],
        "luoghi": [r["nome"] for r in trovato["luoghi"]],
        "parole": len(trovato["parole"]),
        "note": [r["nota"] for r in trovato["note"]],
        "date": [[str(r["anno"]), r["quanti"]] for r in trovato["date"]],
    }


def _scorta(pacchetto) -> dict:
    def righe(domanda: str) -> list:
        try:
            return [dict(r) for r in pacchetto.dentro.execute(domanda)]
        except Exception:            # noqa: BLE001 — una tabella che non c'e'
            return []

    raccolte = righe("SELECT id, nome, creata_il FROM raccolte ORDER BY id")
    for raccolta in raccolte:
        raccolta["impronte"] = [
            r["impronta"] for r in pacchetto.dentro.execute(
                "SELECT impronta FROM raccolte_scatti WHERE raccolta_id = ? "
                "ORDER BY impronta", (raccolta["id"],))]
    return {
        "cuori": righe("SELECT impronta, messo_il FROM cuori ORDER BY impronta"),
        "tolti": righe("SELECT impronta, tolto_il FROM cuori_tolti "
                       "ORDER BY impronta"),
        "raccolte": raccolte,
    }


def _pezzi(pacchetto, scatti: list[dict]) -> list[dict]:
    from officina.telefono import cifratura

    if not scatti:
        return []
    piu_grosso = max(scatti, key=lambda s: (s["dimensione"], -s["id"]))
    dimensione = piu_grosso["dimensione"]
    dove = [(0, 100),
            (max(0, cifratura.BLOCCO - 50), 100),
            (max(0, dimensione - 100), 100)]
    import hashlib
    fuori = []
    for da, quanti in dove:
        pezzo = pacchetto.pezzo(piu_grosso["id"], da, quanti)
        fuori.append({
            "id": piu_grosso["id"], "da": da, "quanti": quanti,
            "lungo": len(pezzo),
            "impronta": hashlib.blake2b(pezzo, digest_size=32).hexdigest(),
        })
    return fuori


def impacchetta(cartella: Path) -> str:
    cartella = Path(cartella)
    righe = [
        "# Un pacchetto del Visore, piccolo e finto (regola 114).",
        "#",
        "# Lo rifà: python strumenti/pacchetto_di_prova.py --rifai",
        f"# La password è: {PAROLA}",
        "#",
        "# Ogni file comincia con una riga «nome quanti-byte», poi i suoi byte",
        "# in base64. Il contenuto è cifrato: qui si vedono solo i nomi.",
        "",
    ]
    for dove in sorted(p for p in cartella.rglob("*") if p.is_file()):
        dati = dove.read_bytes()
        nome = dove.relative_to(cartella).as_posix()
        righe.append(f"{nome} {len(dati)}")
        scritto = base64.b64encode(dati).decode("ascii")
        for inizio in range(0, len(scritto), LARGHEZZA):
            righe.append(scritto[inizio:inizio + LARGHEZZA])
        righe.append("")
    return "\n".join(righe) + "\n"


def spacchetta(testo: str, dove: Path) -> Path:
    dove = Path(dove)
    nome = None
    quanti = 0
    pezzi: list[str] = []

    def chiudi() -> None:
        if nome is None:
            return
        dati = base64.b64decode("".join(pezzi))
        if len(dati) != quanti:
            raise ValueError(f"«{nome}» doveva essere di {quanti} byte, "
                             f"ne sono usciti {len(dati)}")
        fuori = dove.joinpath(*nome.split("/"))
        fuori.parent.mkdir(parents=True, exist_ok=True)
        fuori.write_bytes(dati)

    for riga in testo.splitlines():
        if riga.startswith("#"):
            continue
        if not riga.strip():
            chiudi()
            nome, pezzi = None, []
            continue
        if nome is None:
            pezzo, _, misura = riga.rpartition(" ")
            nome, quanti, pezzi = pezzo, int(misura), []
        else:
            pezzi.append(riga.strip())
    chiudi()
    return dove


def rifai() -> None:
    import json
    import shutil

    stanza = Path(tempfile.mkdtemp(prefix="pacchetto-di-prova-"))
    try:
        cartella = costruisci(stanza)
        detto = racconta(cartella)
        DOVE_VA.mkdir(parents=True, exist_ok=True)
        IL_PACCHETTO.write_text(impacchetta(cartella), encoding="utf-8")
        QUELLO_CHE_CI_LEGGO.write_text(
            json.dumps(detto, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(stanza, ignore_errors=True)

    peso = IL_PACCHETTO.stat().st_size
    print(f"{IL_PACCHETTO.relative_to(RADICE)} — {peso // 1024} kB, "
          f"{detto['quanti']} scatti, {detto['verifica']['letti']} file riletti")
    print(f"{QUELLO_CHE_CI_LEGGO.relative_to(RADICE)} — quello che ci legge il "
          "telefono finto")


def main() -> int:
    discorso = argparse.ArgumentParser(description="Il pacchetto di prova.")
    discorso.add_argument("--rifai", action="store_true",
                          help="ricostruisce il pacchetto di prova")
    detto = discorso.parse_args()
    if not detto.rifai:
        discorso.print_help()
        return 0
    rifai()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
