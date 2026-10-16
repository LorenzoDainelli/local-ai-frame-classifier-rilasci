from __future__ import annotations

import ast
import collections
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GRANDI = frozenset({
    "file_media", "scatti", "percorsi", "etichette", "volti",
    "doppioni_gruppi", "impronte", "scatti_parole", "non_importati",
})

PAGINE = (
    "/", "/api/griglia", "/scatto/1", "/miniatura/1", "/immagine/1",
    "/officina", "/api/officina/1", "/api/persone/cerca?q=a", "/api/ripassi",
    "/api/nodi", "/importazione", "/api/importazione", "/elenchi",
    "/doppioni", "/api/doppioni", "/api/doppioni/gruppi", "/albero",
    "/api/albero/schermata", "/api/albero", "/api/albero/nodo/1",
    "/api/cerca?q=2024", "/persone", "/persone/mazzo", "/persone/cassetto",
    "/luoghi", "/tempo", "/api/tempo/punti", "/api/tempo/zona?zona=-90,-180,90,180",
    "/stato", "/misura/banco", "/api/impronte", "/impostazioni",
    "/blocco", "/api/modelli", "/api/volti", "/api/parole", "/senza-data",
    "/telefono", "/api/telefono", "/sincronia", "/api/sincronia",
    "/benvenuto", "/benvenuto/cartella", "/benvenuto/lavoro",
    "/benvenuto/pronto", "/volti/raddrizzamento", "/miglioramento",
    "/api/miglioramento", "/miglioramento/rivedi", "/miglioramento/sfida",
    "/miglioramento/sfida/com-e-andata",
)


SCHERMATE = tuple(
    dove for dove in PAGINE
    if not dove.startswith(("/api/", "/miniatura/", "/immagine/")))


COMANDI = (
    ("/api/nodi", {"nome": "prova delle letture", "genitore_id": ""}),
    ("/api/nodi", {"nome": "un figlio", "genitore_id": "1"}),
    ("/api/etichetta", {"scatto_id": 3, "nodo_id": 1, "stato": "si"}),
    ("/api/etichetta", {"scatto_id": 4, "nodo_id": 1, "stato": "no"}),
    ("/api/etichetta", {"scatto_id": 4, "nodo_id": 1, "stato": "togli"}),
    ("/api/riaddestra", {}),
    ("/api/cuore", {"scatto_id": 3, "acceso": 1}),
    ("/api/stella", {"scatto_id": 3, "acceso": 1}),
    ("/api/annulla", {}),
    ("/api/ripasso/avanti", {"nodo_id": 1, "scatto_id": 3}),
    ("/api/albero/rinomina", {"nodo_id": 2, "nome": "rinominato"}),
    ("/api/albero/sposta", {"nodo_id": 2, "come": "radice"}),
    ("/api/albero/stato", {"nodo_id": 2, "stato": "congelato"}),
    ("/api/impostazione", {"chiave": "luogo_aiuta", "valore": "1"}),
    ("/scatto/3/nota", {"nota": "una nota"}),
    ("/scatto/3/fuori-archivio", {}),
    ("/luoghi/1/nome", {"nome": "casa"}),
    ("/senza-data/6/imposta", {"giorno": "2024-05-05"}),
    ("/senza-data/8/marca", {}),
    ("/elenchi/riprova-tutti", {}),
)


def come_e_andata(archivio, pagine=PAGINE, comandi=COMANDI) -> list[tuple]:
    from fastapi.testclient import TestClient

    from officina.web.server import app

    connessione = archivio.connessione
    archivio._lettore_a_parte = lambda: None
    cliente = TestClient(app, client=("127.0.0.1", 51000),
                         follow_redirects=False)
    esito = []
    for dove, campi in comandi:
        esito.append(("POST", dove) + _un_giro(
            connessione, lambda d, c=campi: cliente.post(d, data=c), dove))
    for dove in pagine:
        esito.append(("GET", dove) + _un_giro(connessione, cliente.get, dove))
    return esito


def _un_giro(connessione, chiama, dove) -> tuple[int | str, int]:
    viste: list[str] = []
    connessione.set_trace_callback(viste.append)
    try:
        codice = chiama(dove).status_code
    except Exception as errore:
        codice = f"{type(errore).__name__}: {errore}"
    finally:
        connessione.set_trace_callback(None)
    return codice, len(viste)


def guarda(archivio, pagine=PAGINE, comandi=COMANDI) -> dict[str, list[str]]:
    from fastapi.testclient import TestClient

    from officina.web.server import app

    viste: list[str] = []
    connessione = archivio.connessione
    archivio._lettore_a_parte = lambda: None
    connessione.set_trace_callback(viste.append)
    try:
        cliente = TestClient(app, client=("127.0.0.1", 51000),
                             follow_redirects=False)
        for dove, campi in comandi:
            try:
                cliente.post(dove, data=campi)
            except Exception:
                pass
        for dove in pagine:
            cliente.get(dove)
    finally:
        connessione.set_trace_callback(None)

    parziali = _indici_parziali(connessione)
    larghe: dict[str, list[str]] = collections.defaultdict(list)
    for domanda in sorted(set(viste)):
        pulita = " ".join(domanda.split())
        if not pulita.upper().startswith("SELECT"):
            continue
        try:
            piano = [r[3] for r in
                     connessione.execute("EXPLAIN QUERY PLAN " + pulita)]
        except Exception:
            continue
        nomi = soprannomi(pulita)
        for passo in piano:
            tabella = _chi_legge_tutto(passo, parziali, nomi)
            if tabella in GRANDI:
                larghe[tabella].append(pulita)
    return dict(larghe)


def _indici_parziali(connessione) -> frozenset[str]:
    return frozenset(
        nome for nome, sql in connessione.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index'")
        if sql and " WHERE " in sql.upper())


UN_SOPRANNOME = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)(?:\s+AS)?\s+([A-Za-z_]\w*)", re.I)

NON_SONO_SOPRANNOMI = frozenset({
    "on", "where", "group", "order", "limit", "join", "left", "inner",
    "cross", "natural", "outer", "using", "set", "values", "as", "and",
    "or", "union", "having", "returning", "window",
})


def soprannomi(domanda: str) -> dict[str, str]:
    mappa: dict[str, str] = {}
    for tabella, nome in UN_SOPRANNOME.findall(domanda):
        if nome.lower() in NON_SONO_SOPRANNOMI:
            continue
        mappa[nome] = tabella
    return mappa


def _chi_legge_tutto(passo: str, parziali: frozenset[str],
                     come_si_chiama: dict[str, str] | None = None) -> str | None:
    def vero(nome: str) -> str:
        return (come_si_chiama or {}).get(nome, nome)

    nuda = re.fullmatch(r"SCAN (\w+)", passo)
    if nuda:
        return vero(nuda.group(1))
    con_soprannome = re.fullmatch(r"SCAN (\w+) AS (\w+)", passo)
    if con_soprannome:
        return con_soprannome.group(1)
    con_indice = re.fullmatch(r"SCAN (\w+) USING INDEX (\w+)", passo)
    if con_indice and con_indice.group(2) not in parziali:
        return vero(con_indice.group(1))
    con_due = re.fullmatch(r"SCAN (\w+) AS (\w+) USING INDEX (\w+)", passo)
    if con_due and con_due.group(3) not in parziali:
        return con_due.group(1)
    return None


COMINCIA_UNA_DOMANDA = re.compile(r"\s*(SELECT|UPDATE|DELETE)\b", re.I)


def _ogni_domanda_scritta(radice: Path) -> dict[str, list[str]]:
    def testo(nodo):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            return nodo.value
        if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
            sinistra, destra = testo(nodo.left), testo(nodo.right)
            if sinistra is not None and destra is not None:
                return sinistra + destra
        return None

    trovate: dict[str, list[str]] = collections.defaultdict(list)
    for file in sorted(radice.rglob("*.py")):
        for nodo in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            scritto = testo(nodo)
            if scritto and COMINCIA_UNA_DOMANDA.match(scritto):
                trovate[" ".join(scritto.split())].append(
                    f"{file.relative_to(radice.parent)}:{nodo.lineno}")
    return dict(trovate)


def raccogli(radice: Path | None = None) -> tuple[list[tuple], list[tuple]]:
    radice = radice or Path(__file__).resolve().parent.parent / "officina"
    from officina.archivio import migrazioni

    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    migrazioni.aggiorna(connessione)
    parziali = _indici_parziali(connessione)

    larghe, illeggibili = [], []
    for domanda, dove in sorted(_ogni_domanda_scritta(radice).items()):
        try:
            piano = [riga["detail"] for riga in connessione.execute(
                "EXPLAIN QUERY PLAN " + domanda, ("1",) * domanda.count("?"))]
        except sqlite3.Error as guaio:
            illeggibili.append((dove[0], type(guaio).__name__, domanda))
            continue
        nomi = soprannomi(domanda)
        for passo in piano:
            tabella = _chi_legge_tutto(passo, parziali, nomi)
            if tabella in GRANDI:
                larghe.append((tabella, dove[0], domanda))
                break
    return larghe, illeggibili


def main() -> int:
    os.environ.setdefault("OFFICINA_ARCHIVIO",
                          "/tmp/officina-prova-doppioni/archivio")
    from officina.archivio import accesso

    archivio = accesso.apri("finto")

    raccolte, illeggibili = raccogli()
    print(f"--- {len(raccolte)} letture larghe fra le domande scritte "
          f"({len(illeggibili)} non si leggono da ferme)")
    for tabella, dove, domanda in sorted(raccolte):
        print(f"  [{tabella}] {dove}\n      {domanda[:130]}")

    print("\n--- e adesso aprendo le schermate e facendo i comandi")
    larghe = guarda(archivio)
    if not larghe:
        print("Nessuna domanda legge una tabella grande da capo a fondo.")
        return 0
    for tabella, domande in sorted(larghe.items()):
        print(f"* SCAN {tabella}: {len(domande)} "
              + ("domanda" if len(domande) == 1 else "domande"))
        for domanda in domande:
            print("    ", domanda[:140])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
