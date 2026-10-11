from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUANTE = 45_000

GIRI = 5

PAGINE = [
    "/", "/?da_fare=1", "/?senza_data=1", "/?schermate=1",
    "/officina", "/albero", "/importazione", "/elenchi", "/impostazioni",
    "/stato", "/senza-data", "/persone", "/persone/mazzo", "/persone/cassetto",
    "/luoghi", "/doppioni", "/telefono", "/misura/banco",
    "/api/griglia", "/api/nodi", "/api/albero", "/api/cerca?frase=cat_1",
    "/api/doppioni", "/scatto/1",
    "/casa", "/lavoro", "/intelligenza", "/api/intelligenza", "/sistemare", "/miglioramento",
    "/novita", "/api/conteggi", "/api/in-corso", "/api/luoghi/albero", "/api/volti",
    "/api/impronte", "/api/periodo", "/api/spazio", "/api/modelli",
]


def costruisci(dove: Path, quante: int = QUANTE, seme: int = 7):
    os.environ["OFFICINA_ARCHIVIO"] = str(dove)
    from officina.archivio import accesso

    accesso.chiudi(con_copia=False)
    archivio = accesso.apri("finto")
    caso = random.Random(seme)
    quando = "2024-01-01T00:00:00Z"

    with archivio.scrittura() as c:
        c.execute("INSERT INTO cartelle_sorgente (percorso, aggiunta_il) "
                  "VALUES ('D:/Foto', ?)", (quando,))
        c.execute("INSERT INTO importazioni (nome, iniziata_il, stato, totale, "
                  "finita_il) VALUES ('Foto', ?, 'finita', ?, ?)",
                  (quando, quante, quando))

        nodi = []
        for ramo in range(12):
            padre = c.execute(
                "INSERT INTO nodi (genitore_id, nome, creato_il) "
                "VALUES (NULL, ?, ?)", (f"cat_{ramo}", quando)).lastrowid
            nodi.append(padre)
            for figlio in range(14):
                nodi.append(c.execute(
                    "INSERT INTO nodi (genitore_id, nome, creato_il) "
                    "VALUES (?, ?, ?)",
                    (padre, f"sub_{ramo}_{figlio}", quando)).lastrowid)

        scatti = []
        for n in range(quante):
            data = (f"{2005 + n % 20:04d}-{1 + n % 12:02d}-{1 + n % 28:02d}"
                    f"T{n % 24:02d}:{n % 60:02d}:00")
            senza_data = n % 900 == 0
            scatti.append((
                "video" if n % 30 == 0 else ("live" if n % 7 == 0 else "foto"),
                None if senza_data else data,
                None if senza_data else 60,
                None if senza_data else data + "Z",
                None if senza_data else data[:10],
                "assente" if senza_data else "exif",
                None if n % 5 == 0 else 43.7 + caso.random(),
                None if n % 5 == 0 else 11.2 + caso.random(),
                4032, 3024, 0,
                1 if n % 40 == 0 else 0,
                1 if n % 200 == 0 else 0,
                None, quando, None,
                1 if n % 25 == 0 else 0,
                1 if n % 60 == 0 else 0,
                1))
        c.executemany(
            "INSERT INTO scatti (genere, data_locale, fuso_minuti, istante_utc,"
            " giorno, origine_data, latitudine, longitudine, larghezza, altezza,"
            " durata_ms, sembra_schermata, fuori_archivio, nota, creato_il,"
            " visto_il, cuore, evidenziato, importazione_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", scatti)

        c.executemany(
            "INSERT INTO file_media (impronta, dimensione, genere, formato,"
            " larghezza, altezza, orientamento, sembra_schermata, miniatura,"
            " scatto_id, ruolo, origine_data, aggiunto_il)"
            " VALUES (?,?,'immagine','JPEG',4032,3024,1,0,?,?,'principale',"
            "'assente',?)",
            [(f"imp{n:08x}" + "0" * 40, 3_500_000 + n, f"min/{n}.webp", n, quando)
             for n in range(1, quante + 1)])
        c.executemany(
            "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, presente,"
            " visto_il) VALUES (?, 1, ?, ?, 1, ?)",
            [(n, f"D:/Foto/{n // 500}/IMG_{n:05d}.JPG", f"IMG_{n:05d}.JPG", quando)
             for n in range(1, quante + 1)])

        viste, etichette = set(), []
        for s in range(1, quante + 1):
            if s % 10 >= 7:
                continue
            for _ in range(1 + s % 3):
                nodo = caso.choice(nodi)
                if (s, nodo) in viste:
                    continue
                viste.add((s, nodo))
                etichette.append((s, nodo, "si" if s % 9 else "no",
                                  "sistema" if s % 3 else "utente", 0.8, quando))
        c.executemany(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine,"
            " sicurezza, creata_il) VALUES (?,?,?,?,?,?)", etichette)

        c.executemany(
            "INSERT INTO persone (nome, stato, nata_il) VALUES (?, 'attiva', ?)",
            [(f"persona_{p}" if p % 3 else None, quando) for p in range(300)])
        c.executemany(
            "INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro, area,"
            " nitidezza, sicurezza, modello, versione, persona_id, deciso_da,"
            " trovato_il) VALUES (?,?,0,'[0.1,0.1,0.2,0.2]',0.04,0.7,0.9,"
            "'m','1',?,'sistema',?)",
            [(s, s, 1 + s % 300, quando) for s in range(1, quante + 1, 3)])
        c.executemany(
            "INSERT INTO luoghi (nome, centro_lat, centro_lon, raggio_metri,"
            " quanti, nato_il) VALUES (?, 43.7, 11.2, 500, 10, ?)",
            [(f"luogo_{l}", quando) for l in range(80)])

        c.executemany(
            "INSERT INTO impronte (scatto_id, file_id, descrittore, versione,"
            " inquadratura, metodo, dimensione, valori, calcolata_il)"
            " VALUES (?, ?, 'clip', '1', 'intera', 'pieno', 32, ?, ?)",
            [(s, s, b"\x00" * 128, quando) for s in range(1, quante // 2)])
        c.executemany(
            "INSERT INTO segnalazioni (tipo, scatto_id, dettaglio, creata_il) VALUES (?, ?, 'x', ?)",
            [(("non_si_apre", "volti_non_letti", "corpi_non_letti")[s % 3], s, quando)
             for s in range(1, quante + 1, 15)])
        c.executemany(
            "INSERT INTO corpi (scatto_id, fotogramma, riquadro, area, sicurezza, maschera, punti,"
            " modello, versione, trovato_il) VALUES (?, 0, '[0.1,0.1,0.3,0.8]', 0.24, 0.9, x'',"
            " x'', 'corpi', '1', ?)",
            [(s, quando) for s in range(1, quante + 1, 4)])

    from officina.archivio import database

    with archivio.scrittura() as c:
        database.impara_com_e_fatto(c)
    return archivio


def misura(dove: Path) -> list[tuple[float, float, int, str]]:
    from fastapi.testclient import TestClient

    from officina.web import in_disparte
    from officina.web.server import app

    in_disparte.A_PARTE = False
    cliente = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51000))
    fuori = []
    for pagina in PAGINE:
        risposta = cliente.get(pagina)
        tempi = []
        for _ in range(GIRI):
            avvio = time.perf_counter()
            risposta = cliente.get(pagina)
            tempi.append((time.perf_counter() - avvio) * 1000)
        tempi.sort()
        fuori.append((tempi[len(tempi) // 2], tempi[0],
                      risposta.status_code, pagina))
    return fuori


def main() -> int:
    quante = int(sys.argv[1]) if len(sys.argv) > 1 else QUANTE
    dove = Path(tempfile.mkdtemp(prefix="officina-cronometro-")) / "archivio"
    os.environ.setdefault("OFFICINA_CASA_PROGRAMMA", str(dove.parent / "casa-programma"))
    print(f"Costruisco {quante} fotografie finte...", flush=True)
    avvio = time.perf_counter()
    costruisci(dove, quante)
    print(f"  fatte in {time.perf_counter() - avvio:.1f} s\n")
    try:
        print(f"{'mediana':>10}  {'minimo':>8}         pagina")
        print("-" * 52)
        for mediana, minimo, codice, pagina in misura(dove):
            segno = " " if codice < 400 else f" [{codice}]"
            print(f"{mediana:9.1f} ms {minimo:8.1f} ms {segno} {pagina}")
    finally:
        from officina.archivio import accesso
        accesso.chiudi(con_copia=False)
        shutil.rmtree(dove.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
