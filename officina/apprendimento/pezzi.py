from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageFilter

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.descrittori import apri as apri_descrittore
from officina.descrittori import preparazione, scheda, vettori
from officina.errori import ErroreOfficina
from officina.immagini import fotogrammi as estrattore
from officina.immagini import lettura
from officina.modello import file_media, sagome
from officina.ritocco import maschere
from officina.sicuro import dall_archivio

MARGINE = 0.12
OGNI_FOTOGRAMMI = 5
SICURA = 0.5
SFONDO = (124, 116, 104)
ALLARGA = 5
A_GRUPPI = 16
LATO_DEL_FILE = 2048


def _mai() -> bool:
    return False


def _buone_da_fare_sql(con_quale: str) -> str:
    fatte_dall_utente = ",".join(f"'{come}'" for come in sagome.FATTE_DALL_UTENTE)
    return (
        "SELECT s.id, s.scatto_id, s.file_id, s.fotogramma, s.istante_ms, s.maschera "
        "FROM sagome s "
        "JOIN etichette e ON e.scatto_id = s.scatto_id AND e.nodo_id = s.nodo_id "
        "AND e.stato = 'si' "
        "JOIN nodi n ON n.id = s.nodo_id AND n.stato = 'attivo' "
        "WHERE s.buona = 1 AND ("
        f"s.come IN ({fatte_dall_utente}) OR (s.come = 'seguita' AND s.da_controllare = 0 "
        f"AND coalesce(s.sicurezza, 0) >= {SICURA} AND s.fotogramma % {OGNI_FOTOGRAMMI} = 0)) "
        f"{con_quale}")


def da_fare(connessione, descrittore: str, versione: str, quanti: int | None = None
            ) -> list[dict]:
    righe = tutti(
        connessione,
        _buone_da_fare_sql(
            "AND NOT EXISTS (SELECT 1 FROM impronte_sagome i WHERE i.sagoma_id = s.id "
            "AND i.descrittore = ? AND i.versione = ?) ORDER BY s.id"
            + (" LIMIT ?" if quanti else "")),
        descrittore, versione, *([quanti] if quanti else []))
    return [dict(riga) for riga in righe]


def quanti_da_fare(connessione, descrittore: str, versione: str) -> int:
    return len(da_fare(connessione, descrittore, versione))


def ritaglia(immagine: Image.Image, dati: bytes, lato: int) -> Image.Image | None:
    pezzo = maschere.apri(dati)
    if pezzo is None or not pezzo.maschera.any():
        return None
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    larga, alta = immagine.size
    kx, ky = larga / pezzo.larghezza, alta / pezzo.altezza
    alta_m, larga_m = pezzo.maschera.shape
    x0, y0 = pezzo.x * kx, pezzo.y * ky
    x1, y1 = (pezzo.x + larga_m) * kx, (pezzo.y + alta_m) * ky
    margine = MARGINE * max(x1 - x0, y1 - y0)
    sx0, sy0 = max(0, int(x0 - margine)), max(0, int(y0 - margine))
    sx1, sy1 = min(larga, int(round(x1 + margine))), min(alta, int(round(y1 + margine)))
    if sx1 - sx0 < 2 or sy1 - sy0 < 2:
        return None
    pezzo_img = Image.fromarray((pezzo.maschera * 255).astype("uint8"), "L")
    dentro = Image.new("L", (sx1 - sx0, sy1 - sy0), 0)
    a_misura = pezzo_img.resize((max(1, round(x1 - x0)), max(1, round(y1 - y0))),
                                Image.Resampling.NEAREST)
    dentro.paste(a_misura, (round(x0) - sx0, round(y0) - sy0))
    dentro = dentro.filter(ImageFilter.MaxFilter(ALLARGA))
    ritaglio = immagine.crop((sx0, sy0, sx1, sy1))
    fondo = Image.new("RGB", ritaglio.size, SFONDO)
    return preparazione.in_quadrato(Image.composite(ritaglio, fondo, dentro), lato)


def _immagine_di(connessione, riga) -> Image.Image:
    media = file_media.per_id(connessione, riga["file_id"])
    if media is None:
        raise ErroreOfficina("Il file della sagoma non c'è più.", codice="pezzo_senza_file")
    percorso = file_media.da_guardare(connessione, riga["file_id"])
    if percorso is None:
        raise ErroreOfficina("Il file della sagoma non si trova.", codice="pezzo_senza_file")
    with dall_archivio.attento(percorso):
        if riga["fotogramma"] < 0:
            return lettura.copia_di_lavoro(percorso, LATO_DEL_FILE)
        immagine = estrattore.uno(percorso, riga["fotogramma"], riga["istante_ms"],
                                  LATO_DEL_FILE)
    if immagine is None:
        raise ErroreOfficina("Il fotogramma della sagoma non si legge.",
                             codice="pezzo_senza_fotogramma")
    return immagine


def scrivi(connessione, sagoma_id: int, descrittore: str, versione: str, valori) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO impronte_sagome (sagoma_id, descrittore, versione, valori, "
        "calcolata_il) VALUES (?, ?, ?, ?, ?)",
        (sagoma_id, descrittore, versione, vettori.a_byte(valori), adesso()))


class Pezzi:

    def __init__(self, archivio, nome: str):
        self.archivio = archivio
        self.carta = scheda(nome)
        self.fatti = 0
        self.saltati = 0
        self._fermati = threading.Event()

    def ferma(self) -> None:
        self._fermati.set()

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return quanti_da_fare(connessione, self.carta.nome, self.carta.versione)

    def esegui(self, fermati: Callable[[], bool] = _mai) -> int:
        if not self.quanti_mancano():
            return 0
        descrittore = apri_descrittore(self.carta.nome, self.archivio.dove.modelli)
        saltate: set[int] = set()
        try:
            descrittore.apri()
            while not (fermati() or self._fermati.is_set()):
                with self.archivio.lettura() as connessione:
                    righe = [r for r in da_fare(connessione, self.carta.nome,
                                                self.carta.versione, A_GRUPPI + len(saltate))
                             if r["id"] not in saltate][:A_GRUPPI]
                if not righe:
                    break
                pronti = []
                for riga in righe:
                    try:
                        with self.archivio.lettura() as connessione:
                            immagine = _immagine_di(connessione, riga)
                        ritaglio = ritaglia(immagine, riga["maschera"], self.carta.lato)
                    except Exception as errore:
                        registro.avviso("pezzi.sagoma_saltata", sagoma=riga["id"],
                                        motivo=registro.Parola(type(errore).__name__))
                        ritaglio = None
                    if ritaglio is None:
                        saltate.add(riga["id"])
                        self.saltati += 1
                    else:
                        pronti.append((riga["id"], ritaglio))
                if not pronti:
                    continue
                valori = descrittore.descrivi([ritaglio for _, ritaglio in pronti])
                with self.archivio.scrittura() as connessione:
                    for (sagoma_id, _), impronta in zip(pronti, valori, strict=True):
                        if uno(connessione, "SELECT 1 FROM sagome WHERE id = ?",
                               sagoma_id) is not None:
                            scrivi(connessione, sagoma_id, self.carta.nome,
                                   self.carta.versione, impronta)
                            self.fatti += 1
        finally:
            descrittore.chiudi()
        registro.evento("pezzi.fatti", fatti=self.fatti, saltati=self.saltati)
        return self.fatti


def del_nodo(connessione, nodi: list[int], scatti_si: set[int], descrittore: str,
             versione: str) -> list[tuple[int, bytes]]:
    if not nodi or not scatti_si:
        return []
    segnaposto = ",".join("?" * len(nodi))
    righe = tutti(
        connessione,
        "SELECT s.id, s.scatto_id, i.valori FROM sagome s JOIN impronte_sagome i "
        "ON i.sagoma_id = s.id AND i.descrittore = ? AND i.versione = ? "
        f"WHERE s.buona = 1 AND s.nodo_id IN ({segnaposto}) ORDER BY s.id",
        descrittore, versione, *nodi)
    return [(riga["id"], riga["valori"]) for riga in righe if riga["scatto_id"] in scatti_si]


def contrari(connessione, lontani: set[int], scatti_no: set[int], descrittore: str,
             versione: str) -> list[tuple[int, bytes]]:
    righe = tutti(
        connessione,
        "SELECT s.id, s.scatto_id, s.nodo_id, i.valori FROM sagome s JOIN impronte_sagome i "
        "ON i.sagoma_id = s.id AND i.descrittore = ? AND i.versione = ? "
        "WHERE s.buona = 1 ORDER BY s.id",
        descrittore, versione)
    return [(riga["id"], riga["valori"]) for riga in righe
            if riga["nodo_id"] not in lontani and riga["scatto_id"] not in scatti_no]


def firma(connessione, descrittore: str | None, versione: str | None) -> tuple:
    if not descrittore or not versione:
        return (0, None, 0)
    riga = uno(connessione,
               "SELECT count(*) AS quante, max(calcolata_il) AS quando FROM impronte_sagome "
               "WHERE descrittore = ? AND versione = ?", descrittore, versione)
    buone = uno(connessione,
                "SELECT count(*) AS q, max(cambiata_il) AS c, total(buona) AS b, "
                "total(id * buona) AS i, total(id * nodo_id) AS n FROM sagome")
    return ((riga["quante"], riga["quando"], buone["q"], buone["c"], buone["b"],
             buone["i"], buone["n"]) if riga else (0, None, 0))
