from __future__ import annotations

import os
from pathlib import Path

import pytest

from officina.modello import impronte as magazzino_impronte
from officina.modello import scatti
from officina.modello.scatti import Filtro

ALBERO = "USE TEMP B-TREE FOR ORDER BY"

QUANTE = 4000


@pytest.fixture(scope="module")
def archivio_grande(tmp_path_factory):
    from officina.archivio import accesso

    dove = tmp_path_factory.mktemp("archivio-piani")
    vecchio = os.environ.get("OFFICINA_ARCHIVIO")
    os.environ["OFFICINA_ARCHIVIO"] = str(dove)
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    try:
        with aperto.scrittura() as connessione:
            quando = "2024-01-01T00:00:00Z"
            connessione.execute(
                "INSERT INTO nodi (nome, creato_il) VALUES ('un nodo', ?)", (quando,))
            righe = []
            for n in range(QUANTE):
                data = (f"{2005 + n % 20:04d}-{1 + n % 12:02d}-"
                        f"{1 + n % 28:02d}T{n % 24:02d}:{n % 60:02d}:00")
                senza_data = n % 300 == 0
                righe.append((
                    "video" if n % 30 == 0 else "foto",
                    None if senza_data else data,
                    None if senza_data else data + "Z",
                    None if senza_data else data[:10],
                    1 if n % 40 == 0 else 0,
                    1 if n % 200 == 0 else 0,
                    1 if n % 25 == 0 else 0,
                    1 if n % 60 == 0 else 0,
                    None,
                    quando))
            connessione.executemany(
                "INSERT INTO scatti (genere, data_locale, istante_utc, giorno,"
                " sembra_schermata, fuori_archivio, cuore, evidenziato, luogo_id,"
                " creato_il) VALUES (?,?,?,?,?,?,?,?,?,?)", righe)
            connessione.executemany(
                "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il)"
                " VALUES (?, 1, 'si', 'sistema', ?)",
                [(s, quando) for s in range(1, QUANTE, 3)])
            connessione.execute("ANALYZE")
        yield aperto
    finally:
        accesso.chiudi(con_copia=False)
        if vecchio is None:
            os.environ.pop("OFFICINA_ARCHIVIO", None)
        else:
            os.environ["OFFICINA_ARCHIVIO"] = vecchio


ACCETTATE = {
    "SELECT e.scatto_id, e.origine, n.id AS nodo_id, n.nome":
        "le etichette delle centoventi fotografie che si stanno mostrando, "
        "in ordine di nome. Non cresce con l'archivio: cresce con quanto è "
        "alta la finestra.",
    "SELECT id FROM scatti WHERE cuore = 1 UNION":
        "il filtro «preferiti». I due posti in cui un cuore può stare — la "
        "colonna e la tavola che arriva dal telefono (regole 424, 380) — si "
        "mettono insieme, e mettere insieme due elenchi vuol dire riordinarli. "
        "Gira su quanti cuori hai messo, non su quante fotografie hai: su un "
        "archivio finto da 45.000 con 1.575 cuori sono 2,9 millesimi, contro "
        "i 59 della forma con l'«oppure» che c'era prima.",
}


def domande_di(archivio, fai) -> list[str]:
    raccolte: list[str] = []
    connessione = archivio.connessione
    connessione.set_trace_callback(raccolte.append)
    try:
        fai(connessione)
    finally:
        connessione.set_trace_callback(None)
    return [d for d in raccolte if "ORDER BY" in d.upper()]


def chi_riordina(archivio, fai) -> list[str]:
    connessione = archivio.connessione
    colpevoli = []
    for domanda in domande_di(archivio, fai):
        try:
            come = " | ".join(riga["detail"] for riga in
                              connessione.execute("EXPLAIN QUERY PLAN " + domanda))
        except Exception:
            continue
        if ALBERO not in come:
            continue
        piatta = " ".join(domanda.split())
        if any(pezzo in piatta for pezzo in ACCETTATE):
            continue
        colpevoli.append(f"{piatta[:110]}\n     {come}")
    return colpevoli


FILTRI = [
    ("tutto", Filtro()),
    ("dal più vecchio", Filtro(ordine="data_su")),
    ("senza etichetta", Filtro(senza_etichetta=True)),
    ("la coda dell'etichettatura", Filtro(senza_evidenziati=True)),
    ("un genere", Filtro(genere="foto")),
    ("senza data", Filtro(senza_data=True)),
    ("schermate", Filtro(solo_schermate=True)),
    ("senza schermate", Filtro(escludi_schermate=True)),
    ("fuori archivio", Filtro(fuori_archivio=True)),
    ("col cuore", Filtro(col_cuore=True)),
    ("messi da parte", Filtro(evidenziati=True)),
    ("un nodo", Filtro(nodi_e=[1])),
]


@pytest.mark.parametrize("nome, filtro", FILTRI, ids=[n for n, _ in FILTRI])
def test_la_prima_schermata_della_galleria_non_riordina_niente(
        archivio_grande, nome, filtro):
    colpevoli = chi_riordina(
        archivio_grande, lambda c: scatti.pagina(c, filtro, 0, 120))
    assert not colpevoli, (
        f"«{nome}» ordina l'archivio da capo per mostrarne centoventi:\n  "
        + "\n  ".join(colpevoli))


@pytest.mark.parametrize("nome, filtro", FILTRI, ids=[n for n, _ in FILTRI])
def test_chi_viene_prima_e_chi_dopo_non_riordina_niente(
        archivio_grande, nome, filtro):
    colpevoli = chi_riordina(
        archivio_grande, lambda c: scatti.vicini(c, filtro, QUANTE // 2))
    assert not colpevoli, f"«{nome}»:\n  " + "\n  ".join(colpevoli)


def test_anche_sul_primo_sull_ultimo_e_su_uno_senza_data(archivio_grande):
    with archivio_grande.lettura() as connessione:
        senza = connessione.execute(
            "SELECT id FROM scatti WHERE istante_utc IS NULL ORDER BY id LIMIT 1").fetchone()
    for quale in (1, QUANTE, senza["id"]):
        colpevoli = chi_riordina(
            archivio_grande, lambda c: scatti.vicini(c, Filtro(), quale))
        assert not colpevoli, f"scatto {quale}:\n  " + "\n  ".join(colpevoli)


def test_la_coda_dei_modelli_non_riordina_niente(archivio_grande):
    colpevoli = chi_riordina(
        archivio_grande,
        lambda c: magazzino_impronte.scatti_da_fare(c, "disegnato", "1", 64))
    assert not colpevoli, "\n  ".join(colpevoli)


def test_la_prova_saprebbe_accorgersene(archivio_grande):
    colpevoli = chi_riordina(archivio_grande, lambda c: c.execute(
        "SELECT s.id FROM scatti s WHERE s.fuori_archivio = 0 "
        "ORDER BY s.istante_utc IS NULL, s.istante_utc DESC, s.id DESC "
        "LIMIT 120").fetchall())
    assert colpevoli


def test_ogni_riordino_accettato_esiste_ancora(archivio_grande):
    viste = []
    for filtro in [f for _, f in FILTRI]:
        viste += domande_di(archivio_grande,
                            lambda c, f=filtro: scatti.pagina(c, f, 0, 120))
    tutte = " ".join(" ".join(d.split()) for d in viste)
    morte = [pezzo for pezzo in ACCETTATE if pezzo not in tutte]
    assert not morte, f"ACCETTATE spiega domande che non esistono più: {morte}"


def test_le_domande_che_si_guardano_esistono_davvero(archivio_grande):
    assert domande_di(archivio_grande,
                      lambda c: scatti.pagina(c, Filtro(), 0, 120))
    assert domande_di(archivio_grande,
                      lambda c: scatti.vicini(c, Filtro(), QUANTE // 2))


def test_nessuna_prova_chiede_le_prime_n_senza_dire_in_che_ordine():
    import re

    cartella = Path(__file__).resolve().parent
    senza_ordine = re.compile(
        r"""(["'])(SELECT [^"']*? FROM scatti(?: s)?(?: WHERE [^"']*?)?) LIMIT \d+\1""")
    colpevoli = []
    for foglio in sorted(cartella.glob("test_*.py")):
        testo = foglio.read_text(encoding="utf-8")
        for numero, riga in enumerate(testo.splitlines(), 1):
            for incontro in senza_ordine.finditer(riga):
                if "ORDER BY" in incontro.group(2).upper():
                    continue
                colpevoli.append(f"{foglio.name}:{numero}: {incontro.group(0)[:80]}")
    assert not colpevoli, (
        "queste prove chiedono le prime n righe senza dire in che ordine, e "
        "quale sia «la prima» lo decide l'indice che c'è quel giorno:\n  "
        + "\n  ".join(colpevoli))


def test_ogni_indice_parziale_sa_anche_dire_in_che_ordine(archivio_grande):
    with archivio_grande.lettura() as connessione:
        righe = connessione.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'scatti' AND sql IS NOT NULL"
        ).fetchall()
    monchi = []
    for riga in righe:
        testo = " ".join(riga["sql"].split())
        if " WHERE " not in testo.upper():
            continue
        colonne = [c.strip() for c in
                   testo[testo.index("(") + 1:testo.index(")")].split(",")]
        if colonne[:1] == ["fuori_archivio"] and colonne[1:2] != ["istante_utc"]:
            monchi.append(f"{riga['name']}: ({', '.join(colonne)})")
    assert not monchi, (
        "questi indici parziali sanno dire quali, ma non in che ordine, e la "
        "galleria per metterli in ordine li lascia perdere:\n  "
        + "\n  ".join(monchi))


def test_due_indici_non_cominciano_per_la_stessa_colonna_sugli_scatti(archivio_grande):
    with archivio_grande.lettura() as connessione:
        righe = connessione.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'scatti' AND sql IS NOT NULL"
        ).fetchall()
    per_prima_colonna: dict[str, list[str]] = {}
    for riga in righe:
        testo = " ".join(riga["sql"].split())
        if " WHERE " in testo.upper():
            continue
        dentro = testo[testo.index("(") + 1:testo.rindex(")")]
        per_prima_colonna.setdefault(
            dentro.split(",")[0].strip(), []).append(riga["name"])
    doppioni = {colonna: quali for colonna, quali in per_prima_colonna.items()
                if len(quali) > 1}
    assert not doppioni, (
        "questi indici cominciano per la stessa colonna e si contendono le "
        f"stesse domande: {doppioni}")
