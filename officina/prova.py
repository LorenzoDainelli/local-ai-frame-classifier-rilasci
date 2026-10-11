from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from officina import istruzioni


SERVONO = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("jinja2", "jinja2"),
    ("multipart", "python-multipart"),
    ("numpy", "numpy"),
)

IN_PIU = (
    ("torch", "le reti neurali", "requirements-modelli.txt"),
    ("transformers", "i due descrittori grandi", "requirements-modelli.txt"),
    ("torchvision", "prepara l'immagine per il modello", "requirements-modelli.txt"),
    ("av", "i fotogrammi dei video veri", "requirements-modelli.txt"),
    ("cv2", "i due modelli dei volti (regola 339)", "requirements-modelli.txt"),
    ("pynvml", "la temperatura della scheda (regola 181)", "requirements-modelli.txt"),
)


@dataclass
class Riga:

    nome: str
    va: bool | None
    detto: str
    cosa_fare: str = ""


@dataclass
class Prova:
    gruppi: list[tuple[str, list[Riga]]] = field(default_factory=list)

    @property
    def righe(self) -> list[Riga]:
        return [riga for _, righe in self.gruppi for riga in righe]

    @property
    def quante_rosse(self) -> int:
        return sum(1 for riga in self.righe if riga.va is False)

    @property
    def tutto_bene(self) -> bool:
        return self.quante_rosse == 0


def _le_librerie() -> list[Riga]:
    righe = []
    for modulo, pacchetto in SERVONO:
        c_e = importlib.util.find_spec(modulo) is not None
        righe.append(Riga(
            nome=modulo,
            va=c_e,
            detto="c'è" if c_e else "non c'è",
            cosa_fare="" if c_e else istruzioni.cosa_fare_per(pacchetto),
        ))
    return righe


def _le_librerie_in_piu() -> list[Riga]:
    righe = []
    for modulo, a_cosa_serve, dove in IN_PIU:
        c_e = importlib.util.find_spec(modulo) is not None
        righe.append(Riga(
            nome=modulo,
            va=True if c_e else None,
            detto=(a_cosa_serve if c_e
                   else f"non c'è: senza, {a_cosa_serve} non funziona"),
            cosa_fare="" if c_e else istruzioni.cosa_fare_per_i_motori(dove),
        ))
    return righe


def _cosa_sa_fare_con_le_immagini() -> list[Riga]:
    from officina.immagini import consegna

    puo = consegna.capacita()
    return [
        Riga("Legge gli HEIC", puo["heic"],
             "le foto dell'iPhone si aprono" if puo["heic"]
             else "le foto dell'iPhone non si aprono",
             "" if puo["heic"] else istruzioni.cosa_fare_per("pillow-heif")),
        Riga("Scrive gli AVIF", True if puo["avif"] else None,
             "le foto arrivano al browser leggere" if puo["avif"]
             else "le foto arriveranno al browser in JPEG: si vede uguale, pesa di più",
             "" if puo["avif"] else istruzioni.cosa_fare_per("pillow-avif-plugin")),
        Riga("Scrive i WebP", True if puo["webp"] else None,
             "c'è anche la riserva" if puo["webp"] else "non c'è la riserva"),
    ]


def _l_archivio(archivio) -> list[Riga]:
    righe = []

    try:
        with archivio.lettura() as connessione:
            quanti = connessione.execute(
                "SELECT count(*) FROM scatti").fetchone()[0]
        righe.append(Riga("L'archivio si apre", True,
                          f"{quanti} scatti dentro"))
    except Exception:
        righe.append(Riga("L'archivio si apre", False,
                          "non si apre",
                          "guarda che la cartella dell'archivio esista e sia leggibile"))
        return righe

    prova_file = Path(archivio.dove.radice) / ".prova-scrittura"
    try:
        prova_file.write_bytes(b"prova")
        riletto = prova_file.read_bytes()
        prova_file.unlink()
        righe.append(Riga("L'archivio si scrive", riletto == b"prova",
                          "scritto e riletto"))
    except OSError:
        righe.append(Riga(
            "L'archivio si scrive", False, "non si riesce a scrivere",
            "la cartella è di sola lettura, oppure il disco è pieno o scollegato"))

    try:
        libero = shutil.disk_usage(archivio.dove.radice).free
        basta = libero > 2_000_000_000
        righe.append(Riga(
            "Spazio sul disco", basta if basta else None,
            f"{libero / 1e9:.1f} GB liberi",
            "" if basta else "sotto i due giga conviene fare spazio prima di importare"))
    except OSError:
        righe.append(Riga("Spazio sul disco", None, "non si riesce a chiederlo"))

    return righe


def _le_miniature(archivio) -> list[Riga]:
    try:
        from PIL import Image

        from officina.immagini import consegna

        disegno = Image.new("RGB", (900, 600), (32, 32, 34))
        for x in range(0, 900, 60):
            for y in range(0, 600, 60):
                if (x // 60 + y // 60) % 2 == 0:
                    disegno.paste((208, 208, 205), (x, y, x + 60, y + 60))
        disegno.thumbnail((320, 320))
        dati, _ = consegna.da_immagine(disegno)

        nome = "prova-della-macchina"
        archivio.scrivi_miniatura(nome, dati)
        riletta = archivio.leggi_miniatura(nome)
        archivio.percorso_miniatura(nome).unlink(missing_ok=True)

        va = bool(riletta) and riletta == dati
        return [Riga("Le miniature si fanno", va,
                     f"fatta, scritta e riletta ({len(dati) / 1000:.0f} kB)" if va
                     else "fatta ma riletta diversa",
                     "" if va else "il disco non sta scrivendo quello che gli si dà")]
    except Exception as guasto:
        return [Riga("Le miniature si fanno", False,
                     f"si è fermato su {type(guasto).__name__}",
                     istruzioni.cosa_fare_per("pillow") + ", e guarda la riga «pillow» qui sopra")]


def _le_copie(archivio) -> list[Riga]:
    from officina.archivio import copie

    esistenti = archivio.copie_esistenti()
    if not esistenti:
        return [Riga("Le copie del database", None,
                     "non ce n'è ancora nessuna: la prima si fa alla prima chiusura")]
    ultima = esistenti[0]
    try:
        copie.verifica(ultima.percorso)
        return [Riga("Le copie del database", True,
                     f"l'ultima si riapre ed è intera ({ultima.quando})")]
    except Exception:
        return [Riga("Le copie del database", False,
                     "l'ultima copia non si riapre",
                     "fanne una nuova da Stato, e guarda lo spazio sul disco")]


def _il_calcolo() -> list[Riga]:
    try:
        from officina.descrittori import torcia

        macchina = torcia.macchina()
        con_scheda = macchina.e_scheda_video
        return [Riga("Il calcolo", True if con_scheda else None,
                     macchina.a_parole(),
                     "" if con_scheda else
                     "senza scheda video i modelli grandi vanno, ma molto più piano")]
    except Exception:
        return [Riga("Il calcolo", None,
                     "non si sa: manca torch, quindi i modelli grandi non girano",
                     istruzioni.cosa_fare_per_i_motori())]


def _i_modelli(dove: Path) -> list[Riga]:
    from officina.descrittori import SCHEDE, scaricamento

    righe = []
    for nome, carta in SCHEDE.items():
        if not carta.va_scaricato:
            continue
        esito = scaricamento.stato(carta, dove)
        righe.append(Riga(
            f"Modello «{nome}»",
            True if esito["in_casa"] else None,
            "in casa" if esito["in_casa"] else "non ancora scaricato",
            "" if esito["in_casa"] else "premi «Scarica quello che manca»"))

    from officina.volti import scaricamento as scarica_volti

    c_e = scarica_volti.gia_in_casa(dove)
    righe.append(Riga(
        "Modelli dei volti", True if c_e else None,
        "in casa" if c_e else "non ancora scaricati",
        "" if c_e else "premi «Scarica quello che manca»"))

    from officina.corpi import scaricamento as scarica_corpi

    c_e = scarica_corpi.gia_in_casa(dove)
    righe.append(Riga(
        "Modelli del corpo", True if c_e else None,
        "in casa" if c_e else "non ancora scaricati",
        "" if c_e else "premi «Scarica quello che manca»"))
    return righe


def _le_prove_di_sviluppo() -> list[Riga]:
    c_e = importlib.util.find_spec("pytest") is not None
    cartella = Path(__file__).resolve().parent.parent / "prove"
    if not cartella.is_dir():
        return [Riga("Le prove di sviluppo", None,
                     "non ci sono: questa è una copia da usare, non da modificare")]
    if not c_e:
        return [Riga("Le prove di sviluppo", None,
                     "ci sono, ma manca pytest per farle girare",
                     "pip install -r requirements-sviluppo.txt")]
    quante = len(list(cartella.glob("test_*.py")))
    return [Riga("Le prove di sviluppo", True,
                 f"{quante} file di prove, e pytest c'è: si possono far girare",
                 "python -m pytest prove")]


def controlla(archivio) -> Prova:
    prova = Prova()
    prova.gruppi.append(("Il programma", [
        Riga("Python", True, f"{sys.version.split()[0]} su {sys.platform}"),
        *_le_librerie(),
    ]))
    prova.gruppi.append(("Questo computer", [
        *_l_archivio(archivio),
        *_le_miniature(archivio),
        *_le_copie(archivio),
    ]))
    prova.gruppi.append(("Le immagini", _cosa_sa_fare_con_le_immagini()))
    prova.gruppi.append(("Per i modelli grandi", [
        *_il_calcolo(),
        *_le_librerie_in_piu(),
    ]))
    prova.gruppi.append(("I modelli", _i_modelli(archivio.dove.modelli)))
    prova.gruppi.append(("Per chi modifica il programma", _le_prove_di_sviluppo()))
    return prova
