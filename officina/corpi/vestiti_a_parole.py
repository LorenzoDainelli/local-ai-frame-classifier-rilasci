from __future__ import annotations

import sqlite3

from officina.archivio.database import tutti
from officina.corpi import VESTITI
from officina.descrittori import vettori

SOPRA = (
    ("felpa", "f", "s", "hoodie"),
    ("maglietta", "f", "s", "t-shirt"),
    ("camicia", "f", "s", "button-up shirt"),
    ("polo", "f", "s", "polo shirt"),
    ("maglione", "m", "s", "sweater"),
    ("giacca", "f", "s", "jacket"),
    ("cappotto", "m", "s", "long coat"),
    ("piumino", "m", "s", "puffer jacket"),
    ("canottiera", "f", "s", "tank top"),
    ("vestito", "m", "s", "dress"),
    ("tuta", "f", "s", "tracksuit"),
    ("costume da bagno", "m", "s", "swimsuit"),
    ("gilet", "m", "s", "vest"),
)
SOTTO = (
    ("jeans", "m", "p", "jeans"),
    ("pantaloni", "m", "p", "trousers"),
    ("pantaloncini", "m", "p", "shorts"),
    ("gonna", "f", "s", "skirt"),
    ("leggings", "m", "p", "leggings"),
)
COLORI = (
    ("black", "nero", "nera", "neri", "nere"),
    ("white", "bianco", "bianca", "bianchi", "bianche"),
    ("gray", "grigio", "grigia", "grigi", "grigie"),
    ("red", "rosso", "rossa", "rossi", "rosse"),
    ("dark blue", "blu", "blu", "blu", "blu"),
    ("light blue", "azzurro", "azzurra", "azzurri", "azzurre"),
    ("green", "verde", "verde", "verdi", "verdi"),
    ("yellow", "giallo", "gialla", "gialli", "gialle"),
    ("orange", "arancione", "arancione", "arancioni", "arancioni"),
    ("pink", "rosa", "rosa", "rosa", "rosa"),
    ("purple", "viola", "viola", "viola", "viola"),
    ("brown", "marrone", "marrone", "marroni", "marroni"),
    ("beige", "beige", "beige", "beige", "beige"),
)
INTERO = ("vestito ", "tuta ", "costume da bagno ")
MARGINE = 0.005
SI_CAPISCE = 0.05


def _colore(colore: tuple, genere: str, numero: str) -> str:
    return colore[1 + (genere == "f") + 2 * (numero == "p")]


def frasi() -> list[tuple[str, str]]:
    fuori = []
    for dove, capi in (("sopra", SOPRA), ("sotto", SOTTO)):
        for nome, genere, numero, inglese in capi:
            for colore in COLORI:
                fuori.append((f"{dove}|{nome} {_colore(colore, genere, numero)}",
                              f"a photo of a person wearing a {colore[0]} {inglese}"))
    return fuori


def pronte(connessione: sqlite3.Connection) -> int:
    return connessione.execute(
        "SELECT count(*) FROM parole_dei_vestiti WHERE modello = ?", (VESTITI,)).fetchone()[0]


def prepara(archivio, siglip=None) -> int:
    with archivio.lettura() as connessione:
        if pronte(connessione) == len(frasi()):
            return 0
    if siglip is None:
        from officina.descrittori.grandi import Siglip2

        siglip = Siglip2(archivio.dove.modelli)
    elenco = frasi()
    numeri = siglip.descrivi_parole([inglese for _, inglese in elenco])
    chiudi = getattr(siglip, "chiudi", None)
    if callable(chiudi):
        chiudi()
    from officina.modello import corpi as corpi_mod

    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM parole_dei_vestiti WHERE modello = ?", (VESTITI,))
        connessione.executemany(
            "INSERT INTO parole_dei_vestiti (modello, frase, vettore) VALUES (?, ?, ?)",
            [(VESTITI, chiave, corpi_mod.vettore_a_byte(vettore))
             for (chiave, _), vettore in zip(elenco, numeri, strict=True)])
    return len(elenco)


def parole(connessione: sqlite3.Connection):
    numpy = vettori.numpy_o_spiega()
    righe = tutti(connessione, "SELECT frase, vettore FROM parole_dei_vestiti WHERE modello = ? "
                  "ORDER BY frase", VESTITI)
    if not righe:
        return [], numpy.zeros((0, 1), dtype=numpy.float32)
    matrice = numpy.stack([numpy.frombuffer(riga["vettore"], dtype="<f4") for riga in righe])
    matrice = matrice / numpy.maximum(numpy.linalg.norm(matrice, axis=1, keepdims=True), 1e-8)
    return [riga["frase"] for riga in righe], matrice


def parti_di_tanti(numeri, chiavi: list[str], matrice) -> list[tuple[str, ...]]:
    numpy = vettori.numpy_o_spiega()
    numeri = numpy.asarray(numeri, dtype=numpy.float32)
    if numeri.ndim != 2 or not len(numeri):
        return []
    if not chiavi or matrice.shape[1] != numeri.shape[1]:
        return [() for _ in range(len(numeri))]
    norme = numpy.maximum(numpy.linalg.norm(numeri, axis=1, keepdims=True), 1e-8)
    voti = (numeri / norme) @ matrice.T
    righe = numpy.arange(len(numeri))
    scelte = {}
    for dove in ("sopra", "sotto"):
        indici = numpy.array([i for i, chiave in enumerate(chiavi) if chiave.startswith(dove + "|")],
                             dtype=numpy.int64)
        if not indici.size:
            continue
        loro = voti[:, indici]
        ordine = numpy.argsort(-loro, axis=1)
        primo = loro[righe, ordine[:, 0]]
        buoni = primo >= SI_CAPISCE
        if dove == "sotto" and indici.size > 1:
            buoni &= primo - loro[righe, ordine[:, 1]] >= MARGINE
        scelte[dove] = (indici[ordine[:, 0]], buoni)
    fuori = []
    for riga in range(len(numeri)):
        detti: list[str] = []
        for dove in ("sopra", "sotto"):
            if dove not in scelte or not scelte[dove][1][riga]:
                continue
            detti.append(chiavi[int(scelte[dove][0][riga])].split("|", 1)[1])
            if detti[-1].startswith(INTERO):
                break
        fuori.append(tuple(detti))
    return fuori


def a_parole(parti: tuple[str, ...]) -> str | None:
    if not parti:
        return None
    testo = ", ".join(parti)
    return testo[0].upper() + testo[1:]


def nomina(vettore, chiavi: list[str], matrice) -> str | None:
    numpy = vettori.numpy_o_spiega()
    if vettore is None or not len(vettore) or float(numpy.linalg.norm(vettore)) <= 0:
        return None
    return a_parole(parti_di_tanti([vettore], chiavi, matrice)[0])


def _genere_e_numero(parte: str) -> tuple[str, str]:
    for nome, genere, numero, _ in sorted((*SOPRA, *SOTTO), key=lambda capo: -len(capo[0])):
        if parte == nome or parte.startswith(nome + " "):
            return genere, numero
    return "m", "s"


def visti(parti: tuple[str, ...], volte: int) -> str:
    genere, numero = ("m", "p") if len(parti) != 1 else _genere_e_numero(parti[0])
    fine = {("m", "s"): "o", ("f", "s"): "a", ("m", "p"): "i", ("f", "p"): "e"}[(genere, numero)]
    return f"vist{fine} {volte} {'volta' if volte == 1 else 'volte'}"
