from __future__ import annotations

import hashlib
import json
import threading
import zlib
from dataclasses import dataclass, field
from typing import Callable

from officina import registro
from officina.apprendimento import classificatore
from officina.apprendimento import pezzi as pezzi_mod
from officina.archivio.database import adesso, tutti, uno
from officina.descrittori import griglia, vettori
from officina.descrittori import apri as apri_descrittore
from officina.descrittori import scheda
from officina.errori import DaRifare, ErroreOfficina
from officina.modello import nodi
from officina.modello import parti as elenco
from officina.ritocco import maschere

CASELLE = griglia.CASELLE_SUL_LATO_LUNGO
MINIMO_SAGOME = 8
MINIMO_SCATTI = 5
OGNI_QUANTI_ALLA_PROVA = 5
COPRE_LA_SAGOMA = 0.5
COPRE_LA_CASELLA = 0.25
NEGATIVE_PER_SAGOMA = 12
SOGLIA_SENZA_PROVA = 0.8
SOGLIA_MINIMA = 0.5
SOGLIA_MASSIMA = 0.97
QUANTILE_DEI_NO = 0.98
INTORNO = 0.25
COINCIDE = 0.6
TROPPO_GRANDE = 4.0
GIA_TROVATA = 0.5
SCATTI_A_TURNO = 8
PICCOLA = 0.02
BUIA = 0.25
MOSSA = 60.0
MODELLO = "imparata"


def _mai() -> bool:
    return False


@dataclass
class Avanzamento:
    fatti: int = 0
    saltati: int = 0
    parti: int = 0
    totale: int = 0
    allenate: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"parti imparate: {self.parti} in {self.fatti} scatti · "
                f"modelli allenati {self.allenate} · saltati {self.saltati}")


def ramo_della_parte(connessione, parte_id: int) -> list[int]:
    riga = uno(connessione, "SELECT nodo_id FROM parti_del_corpo WHERE id = ?", parte_id)
    if riga is None or riga["nodo_id"] is None:
        return []
    return nodi.discendenti(connessione, riga["nodo_id"])


def sagome_della_parte(connessione, parte_id: int) -> list[dict]:
    ramo = ramo_della_parte(connessione, parte_id)
    if not ramo:
        return []
    segnaposto = ",".join(str(int(nodo_id)) for nodo_id in ramo)
    righe = tutti(connessione, pezzi_mod._buone_da_fare_sql(
        f"AND s.nodo_id IN ({segnaposto}) ORDER BY s.id"))
    fuori = []
    for riga in righe:
        voce = dict(riga)
        persa = uno(connessione, "SELECT parte_persa FROM sagome WHERE id = ?", voce["id"])
        voce["persa"] = bool(persa and persa["parte_persa"] == parte_id)
        fuori.append(voce)
    return fuori


def firma_di(sagome: list[dict], descrittore: str, versione: str) -> str:
    impasto = hashlib.sha256(f"{descrittore}|{versione}|{CASELLE}".encode())
    for voce in sagome:
        impasto.update(f"{voce['id']}:{zlib.crc32(voce['maschera'])};".encode())
    return impasto.hexdigest()[:32]


def da_allenare(connessione, descrittore: str, versione: str) -> list[tuple[int, list, str]]:
    fuori = []
    for parte in tutti(connessione,
                       "SELECT id FROM parti_del_corpo WHERE nodo_id IS NOT NULL ORDER BY id"):
        sagome = sagome_della_parte(connessione, parte["id"])
        scatti = {voce["scatto_id"] for voce in sagome}
        tenuta = uno(connessione, "SELECT firma FROM parti_imparate WHERE parte_id = ?",
                     parte["id"])
        if len(sagome) < MINIMO_SAGOME or len(scatti) < MINIMO_SCATTI:
            if tenuta is not None:
                fuori.append((parte["id"], [], ""))
            continue
        firma = firma_di(sagome, descrittore, versione)
        if tenuta is None or tenuta["firma"] != firma:
            fuori.append((parte["id"], sagome, firma))
    return fuori


def coperture(dati: bytes, caselle: list[griglia.Casella]) -> list[tuple[float, float]]:
    pezzo = maschere.apri(dati)
    if pezzo is None or not pezzo.maschera.any():
        return []
    totale = float(pezzo.maschera.sum())
    alta_m, larga_m = pezzo.maschera.shape
    fuori = []
    for casella in caselle:
        x, y, larga, alta = casella.riquadro
        x0, y0 = x * pezzo.larghezza, y * pezzo.altezza
        x1, y1 = (x + larga) * pezzo.larghezza, (y + alta) * pezzo.altezza
        c0 = max(0, int(round(x0)) - pezzo.x)
        r0 = max(0, int(round(y0)) - pezzo.y)
        c1 = min(larga_m, int(round(x1)) - pezzo.x)
        r1 = min(alta_m, int(round(y1)) - pezzo.y)
        dentro = float(pezzo.maschera[r0:r1, c0:c1].sum()) if c1 > c0 and r1 > r0 else 0.0
        area = max(1.0, (x1 - x0) * (y1 - y0))
        fuori.append((dentro / totale, dentro / area))
    return fuori


def risposta(copre_sagoma: float, copre_casella: float) -> int | None:
    if copre_sagoma >= COPRE_LA_SAGOMA or copre_casella >= COPRE_LA_CASELLA:
        return 1
    if copre_sagoma == 0.0:
        return 0
    return None


def com_e_fatta(immagine, sagoma: dict) -> dict[str, bool]:
    numpy = vettori.numpy_o_spiega()
    grigia = numpy.asarray(immagine.convert("L").resize((256, 256)), dtype=numpy.float64)
    luce = float(grigia.mean()) / 255.0
    bordi = (grigia[1:-1, 1:-1] * 4 - grigia[:-2, 1:-1] - grigia[2:, 1:-1]
             - grigia[1:-1, :-2] - grigia[1:-1, 2:])
    pezzo = maschere.apri(sagoma["maschera"])
    area = (float(pezzo.maschera.sum()) / float(pezzo.larghezza * pezzo.altezza)
            if pezzo is not None and pezzo.larghezza and pezzo.altezza else 0.0)
    return {"piccola": area < PICCOLA, "buia": luce < BUIA,
            "mossa": float(bordi.var()) < MOSSA, "video": sagoma["fotogramma"] >= 0,
            "persa": bool(sagoma.get("persa"))}


@dataclass
class Esempio:
    sagoma_id: int
    scatto_id: int
    impronte: object
    risposte: list
    come: dict


def esempio_da(descrittore, carta, immagine, sagoma: dict) -> Esempio | None:
    larga, alta = immagine.size
    caselle = griglia.caselle(larga, alta, CASELLE)
    coperte = coperture(sagoma["maschera"], caselle)
    if not coperte:
        return None
    risposte = [risposta(*voce) for voce in coperte]
    if 1 not in risposte:
        return None
    ritagli = griglia.ritagli(immagine, carta.lato, CASELLE)
    numpy = vettori.numpy_o_spiega()
    impronte = numpy.asarray(descrittore.descrivi([r.immagine for r in ritagli]),
                             dtype=numpy.float32)
    return Esempio(sagoma["id"], sagoma["scatto_id"], impronte, risposte,
                   com_e_fatta(immagine, sagoma))


def _tabella(esempi: list[Esempio]):
    numpy = vettori.numpy_o_spiega()
    righe, risposte = [], []
    for esempio in esempi:
        no = [i for i, r in enumerate(esempio.risposte) if r == 0]
        if len(no) > NEGATIVE_PER_SAGOMA:
            passo = len(no) / NEGATIVE_PER_SAGOMA
            no = [no[int(i * passo)] for i in range(NEGATIVE_PER_SAGOMA)]
        si = [i for i, r in enumerate(esempio.risposte) if r == 1]
        for indice in si:
            righe.append(esempio.impronte[indice])
            risposte.append(1)
        for indice in no:
            righe.append(esempio.impronte[indice])
            risposte.append(0)
    return numpy.asarray(righe), risposte


def alla_prova(scatto_id: int) -> bool:
    return scatto_id % OGNI_QUANTI_ALLA_PROVA == 0


def misura(modello: classificatore.Modello, prova: list[Esempio]) -> dict:
    gruppi = {"tutte": [0, 0], "difficili": [0, 0], "piccola": [0, 0], "buia": [0, 0],
              "mossa": [0, 0], "video": [0, 0], "persa": [0, 0]}
    no_punteggi = []
    for esempio in prova:
        punteggi = modello.punteggi(esempio.impronte)
        migliore = int(punteggi.argmax())
        giusta = esempio.risposte[migliore] == 1
        no_punteggi.extend(float(punteggi[i]) for i, r in enumerate(esempio.risposte) if r == 0)
        difficile = any(esempio.come[k] for k in ("piccola", "buia", "mossa"))
        for nome in ("tutte",) + (("difficili",) if difficile else ()) + tuple(
                k for k in ("piccola", "buia", "mossa", "video", "persa") if esempio.come[k]):
            gruppi[nome][0] += int(giusta)
            gruppi[nome][1] += 1
    return {"gruppi": {k: {"giuste": v[0], "su": v[1]} for k, v in gruppi.items()},
            "no": no_punteggi}


def soglia_da(no_punteggi: list[float]) -> float:
    if not no_punteggi:
        return SOGLIA_SENZA_PROVA
    numpy = vettori.numpy_o_spiega()
    valore = float(numpy.quantile(numpy.asarray(no_punteggi), QUANTILE_DEI_NO))
    return round(min(SOGLIA_MASSIMA, max(SOGLIA_MINIMA, valore)), 4)


def allena(esempi: list[Esempio]) -> tuple[classificatore.Modello, dict] | None:
    allenamento = [e for e in esempi if not alla_prova(e.scatto_id)]
    prova = [e for e in esempi if alla_prova(e.scatto_id)]
    misurata = None
    if prova and allenamento:
        tabella, risposte = _tabella(allenamento)
        if any(risposte) and not all(risposte):
            misurata = misura(classificatore.addestra(tabella, risposte), prova)
    tabella, risposte = _tabella(esempi)
    if not any(risposte) or all(risposte):
        return None
    modello = classificatore.addestra(tabella, risposte)
    resoconto = {"soglia": soglia_da(misurata["no"] if misurata else []),
                 "gruppi": misurata["gruppi"] if misurata else {},
                 "sagome": len(esempi), "alla_prova": len(prova)}
    return modello, resoconto


def in_byte(modello: classificatore.Modello) -> bytes:
    numpy = vettori.numpy_o_spiega()
    return numpy.asarray(list(modello.pesi) + [modello.scarto], dtype="<f8").tobytes()


def da_byte(dati: bytes) -> classificatore.Modello:
    numpy = vettori.numpy_o_spiega()
    valori = numpy.frombuffer(dati, dtype="<f8")
    return classificatore.Modello(pesi=valori[:-1].copy(), scarto=float(valori[-1]),
                                  esempi_si=0, esempi_no=0)


def salva_il_modello(connessione, parte_id: int, descrittore: str, versione: str,
                     modello: classificatore.Modello, resoconto: dict, firma: str) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO parti_imparate (parte_id, descrittore, versione, pesi, "
        "esempi, firma, misura, allenata_il) VALUES (?,?,?,?,?,?,?,?)",
        (parte_id, descrittore, versione, in_byte(modello), resoconto["sagome"], firma,
         json.dumps(resoconto), adesso()))


def dimentica_il_modello(connessione, parte_id: int) -> None:
    connessione.execute("DELETE FROM parti_imparate WHERE parte_id = ?", (parte_id,))
    connessione.execute("DELETE FROM parti_imparate_guardate WHERE parte_id = ?", (parte_id,))
    connessione.execute(
        "DELETE FROM parti_trovate WHERE parte_id = ? AND come = 'imparata'", (parte_id,))


@dataclass
class Imparata:
    parte_id: int
    modello: classificatore.Modello
    soglia: float
    firma: str


def imparate(connessione, descrittore: str, versione: str) -> list[Imparata]:
    fuori = []
    for riga in tutti(connessione,
                      "SELECT parte_id, pesi, firma, misura FROM parti_imparate "
                      "WHERE descrittore = ? AND versione = ? ORDER BY parte_id",
                      descrittore, versione):
        resoconto = json.loads(riga["misura"] or "{}")
        fuori.append(Imparata(riga["parte_id"], da_byte(riga["pesi"]),
                              float(resoconto.get("soglia", SOGLIA_SENZA_PROVA)),
                              riga["firma"]))
    return fuori


def quanti_da_guardare(connessione, descrittore: str, versione: str) -> int:
    riga = uno(connessione,
               "SELECT count(DISTINCT s.id) AS q FROM scatti s "
               "JOIN corpi_guardati c ON c.scatto_id = s.id AND c.da_riguardare = 0 "
               "JOIN parti_imparate p LEFT JOIN parti_imparate_guardate g "
               "ON g.scatto_id = s.id AND g.parte_id = p.parte_id "
               "WHERE p.descrittore = ? AND p.versione = ? AND s.fuori_archivio = 0 "
               "AND (g.scatto_id IS NULL OR g.firma != p.firma "
               "OR g.guardata_il < c.guardato_il)",
               descrittore, versione)
    return int(riga["q"]) if riga else 0


def da_guardare(connessione, descrittore: str, versione: str, quanti: int,
                tranne=()) -> list[tuple[int, list[int]]]:
    saltati = {int(v) for v in tranne}
    fuori: dict[int, list[int]] = {}
    for riga in tutti(connessione,
                      "SELECT s.id AS scatto_id, p.parte_id FROM scatti s "
                      "JOIN corpi_guardati c ON c.scatto_id = s.id AND c.da_riguardare = 0 "
                      "JOIN parti_imparate p LEFT JOIN parti_imparate_guardate g "
                      "ON g.scatto_id = s.id AND g.parte_id = p.parte_id "
                      "WHERE p.descrittore = ? AND p.versione = ? AND s.fuori_archivio = 0 "
                      "AND (g.scatto_id IS NULL OR g.firma != p.firma "
                      "OR g.guardata_il < c.guardato_il) ORDER BY s.id DESC, p.parte_id",
                      descrittore, versione):
        if riga["scatto_id"] in saltati:
            continue
        if riga["scatto_id"] not in fuori and len(fuori) >= quanti:
            break
        parti_dello_scatto = fuori.setdefault(riga["scatto_id"], [])
        if riga["parte_id"] not in parti_dello_scatto:
            parti_dello_scatto.append(riga["parte_id"])
    return list(fuori.items())


def quanti_mancano(connessione) -> int:
    from officina.apprendimento import proposte

    nome, _ = proposte.scegli_descrittore(connessione)
    if not nome:
        return 0
    versione = scheda(nome).versione
    return (len(da_allenare(connessione, nome, versione))
            + quanti_da_guardare(connessione, nome, versione))


def zona(punteggi, caselle: list[griglia.Casella], soglia: float):
    migliore = int(punteggi.argmax())
    if float(punteggi[migliore]) < soglia:
        return None
    bx, by, bw, bh = caselle[migliore].riquadro
    scelte = []
    for indice, casella in enumerate(caselle):
        x, y, w, h = casella.riquadro
        tocca = x < bx + bw and bx < x + w and y < by + bh and by < y + h
        if tocca and float(punteggi[indice]) >= soglia:
            scelte.append((indice, float(punteggi[indice])))
    peso = sum(p for _, p in scelte)
    cx = sum((caselle[i].riquadro[0] + caselle[i].riquadro[2] / 2) * p for i, p in scelte) / peso
    cy = sum((caselle[i].riquadro[1] + caselle[i].riquadro[3] / 2) * p for i, p in scelte) / peso
    x0 = min(caselle[i].riquadro[0] for i, _ in scelte)
    y0 = min(caselle[i].riquadro[1] for i, _ in scelte)
    x1 = max(caselle[i].riquadro[0] + caselle[i].riquadro[2] for i, _ in scelte)
    y1 = max(caselle[i].riquadro[1] + caselle[i].riquadro[3] for i, _ in scelte)
    return (cx, cy), (x0, y0, x1 - x0, y1 - y0), float(punteggi[migliore])


def coincide(dati: bytes, regione) -> bool:
    pezzo = maschere.apri(dati) if dati else None
    if pezzo is None or not pezzo.maschera.any():
        return False
    x, y, w, h = regione
    margine_x, margine_y = w * INTORNO, h * INTORNO
    totale = float(pezzo.maschera.sum())
    area_regione = w * h * pezzo.larghezza * pezzo.altezza
    if totale > TROPPO_GRANDE * area_regione:
        return False
    casella = griglia.Casella(0, 0, (x - margine_x, y - margine_y, w + 2 * margine_x,
                                     h + 2 * margine_y))
    dentro = coperture(dati, [casella])
    return bool(dentro) and dentro[0][0] >= COINCIDE


def riquadro_di(dati: bytes):
    pezzo = maschere.apri(dati)
    alta, larga = pezzo.maschera.shape
    return (pezzo.x / pezzo.larghezza, pezzo.y / pezzo.altezza,
            larga / pezzo.larghezza, alta / pezzo.altezza)


def gia_trovata(connessione, scatto_id: int, parte_id: int, fotogramma: int,
                riquadro) -> bool:
    for riga in tutti(connessione,
                      "SELECT riquadro FROM parti_trovate WHERE scatto_id = ? AND parte_id = ? "
                      "AND fotogramma = ? AND come = 'parola'",
                      scatto_id, parte_id, fotogramma):
        if _sovrapposizione(json.loads(riga["riquadro"]), riquadro) >= GIA_TROVATA:
            return True
    return False


def _sovrapposizione(a, b) -> float:
    sinistra, sopra = max(a[0], b[0]), max(a[1], b[1])
    destra, sotto = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    comune = max(0.0, destra - sinistra) * max(0.0, sotto - sopra)
    piccola = min(a[2] * a[3], b[2] * b[3])
    return comune / piccola if piccola > 0 else 0.0


def apri_lo_sceglitore(cartella_modelli):
    from officina.corpi import rilevatore as rilevatore_mod
    from officina.ritocco.scelta import Sceglitore

    cartella = rilevatore_mod.dove_stanno(cartella_modelli) / rilevatore_mod.CARTELLA_SAM3
    if not (cartella / rilevatore_mod.PROVA_SAM3).is_file():
        return None
    return Sceglitore(cartella)


class Passata:

    def __init__(self, archivio, descrittore=None, sceglitore=None,
                 fermato: Callable[[], bool] | None = None, sulla_scheda: bool = True):
        self.archivio = archivio
        self.avanzamento = Avanzamento()
        self._descrittore = descrittore
        self._sceglitore = sceglitore
        self._fermati = threading.Event()
        self._fuori = fermato
        self._saltati: set[int] = set()
        self._sulla_scheda = sulla_scheda
        self.nome: str | None = None
        self.carta = None

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set() or bool(self._fuori and self._fuori())

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return quanti_mancano(connessione)

    def _scegli(self) -> bool:
        from officina.apprendimento import proposte

        with self.archivio.lettura() as connessione:
            nome, _ = proposte.scegli_descrittore(connessione)
        if not nome:
            return False
        self.nome, self.carta = nome, scheda(nome)
        return True

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None) -> Avanzamento:
        if not self._scegli() or not self.quanti_mancano():
            return self.avanzamento
        mio = self._descrittore is None
        if mio:
            self._descrittore = apri_descrittore(self.nome, self.archivio.dove.modelli)
        try:
            self._descrittore.apri()
            self._allena_tutte()
            if not self.fermata:
                self._guarda_tutti(al_passo)
        finally:
            if mio:
                self._descrittore.chiudi()
            if self._sceglitore is not None:
                self._sceglitore.spegni()
        registro.evento("imparate.passata", fatti=self.avanzamento.fatti,
                        parti=self.avanzamento.parti, allenate=self.avanzamento.allenate,
                        saltati=self.avanzamento.saltati)
        return self.avanzamento

    def _allena_tutte(self) -> None:
        with self.archivio.lettura() as connessione:
            lavori = da_allenare(connessione, self.carta.nome, self.carta.versione)
        for parte_id, sagome, firma in lavori:
            if self.fermata:
                return
            if not sagome:
                with self.archivio.scrittura() as connessione:
                    dimentica_il_modello(connessione, parte_id)
                continue
            esempi = []
            for sagoma in sagome:
                if self.fermata:
                    return
                try:
                    with self.archivio.lettura() as connessione:
                        immagine = pezzi_mod._immagine_di(connessione, sagoma)
                    esempio = esempio_da(self._descrittore, self.carta, immagine, sagoma)
                except Exception as errore:          # noqa: BLE001
                    registro.avviso("imparate.sagoma_saltata", sagoma=sagoma["id"],
                                    motivo=registro.Parola(type(errore).__name__))
                    esempio = None
                if esempio is not None:
                    esempi.append(esempio)
            fatto = allena(esempi) if len(esempi) >= MINIMO_SAGOME else None
            with self.archivio.scrittura() as connessione:
                if elenco.una(connessione, parte_id) is None:
                    continue
                if fatto is None:
                    dimentica_il_modello(connessione, parte_id)
                    continue
                modello, resoconto = fatto
                salva_il_modello(connessione, parte_id, self.carta.nome, self.carta.versione,
                                 modello, resoconto, firma)
            self.avanzamento.allenate += 1

    def _guarda_tutti(self, al_passo) -> None:
        from officina.corpi.parti import quadri_di

        with self.archivio.lettura() as connessione:
            self.avanzamento.totale = quanti_da_guardare(connessione, self.carta.nome,
                                                         self.carta.versione)
            modelli = {m.parte_id: m for m in imparate(connessione, self.carta.nome,
                                                       self.carta.versione)}
        if not modelli:
            return
        if self._sceglitore is None:
            self._sceglitore = apri_lo_sceglitore(self.archivio.dove.modelli)
        while not self.fermata:
            with self.archivio.lettura() as connessione:
                gruppo = da_guardare(connessione, self.carta.nome, self.carta.versione,
                                     SCATTI_A_TURNO, tranne=self._saltati)
            if not gruppo:
                break
            for scatto_id, parti_ids in gruppo:
                if self.fermata:
                    break
                try:
                    file_id, quadri = quadri_di(self.archivio, scatto_id)
                    trovate = self._cerca([modelli[p] for p in parti_ids if p in modelli],
                                          scatto_id, quadri)
                except DaRifare as errore:
                    self._salta(scatto_id, errore.codice or "fermato")
                    continue
                except ErroreOfficina as errore:
                    self._salta(scatto_id, errore.codice or "non_letto")
                    self._segna(scatto_id, parti_ids, modelli, None, {})
                    continue
                except Exception as guasto:          # noqa: BLE001
                    registro.errore("imparate.non_cercate", scatto=scatto_id,
                                    **registro.dove_si_e_rotto(guasto))
                    self._salta(scatto_id, "non_letto")
                    continue
                self._segna(scatto_id, parti_ids, modelli, file_id, trovate)
                self.avanzamento.fatti += 1
            if al_passo:
                al_passo(self.avanzamento)

    def _cerca(self, modelli: list[Imparata], scatto_id: int, quadri) -> dict[int, list]:
        from officina.ritocco.scelta import Punto

        trovate: dict[int, list] = {m.parte_id: [] for m in modelli}
        for numero, immagine in quadri:
            if self.fermata:
                raise DaRifare("Fermato a metà.", codice="fermato")
            larga, alta = immagine.size
            caselle = griglia.caselle(larga, alta, CASELLE)
            ritagli = griglia.ritagli(immagine, self.carta.lato, CASELLE)
            numpy = vettori.numpy_o_spiega()
            impronte = numpy.asarray(
                self._descrittore.descrivi([r.immagine for r in ritagli]), dtype=numpy.float64)
            for imparata in modelli:
                trovata = zona(imparata.modello.punteggi(impronte), caselle, imparata.soglia)
                if trovata is None:
                    continue
                (cx, cy), regione, sicurezza = trovata
                maschera = None
                if self._sceglitore is not None:
                    try:
                        scelta = self._sceglitore.scegli_su(
                            f"{scatto_id}#{numero}", immagine, [Punto(cx, cy, True)], None,
                            self._sulla_scheda)
                        maschera = scelta.maschera or None
                    except Exception as errore:          # noqa: BLE001
                        registro.avviso("imparate.sam_non_risponde",
                                        motivo=registro.Parola(type(errore).__name__))
                if maschera is not None and coincide(maschera, regione):
                    trovate[imparata.parte_id].append(
                        (numero, riquadro_di(maschera), sicurezza, maschera, False))
                else:
                    trovate[imparata.parte_id].append((numero, regione, sicurezza, None, True))
        return trovate

    def _segna(self, scatto_id: int, parti_ids: list[int], modelli: dict,
               file_id: int | None, trovate: dict) -> None:
        with self.archivio.scrittura() as connessione:
            for parte_id in parti_ids:
                if parte_id not in modelli or elenco.una(connessione, parte_id) is None:
                    continue
                tenute = [voce for voce in trovate.get(parte_id, [])
                          if not gia_trovata(connessione, scatto_id, parte_id, voce[0], voce[1])]
                quante = elenco.salva_imparate(connessione, scatto_id, file_id, parte_id,
                                               tenute)
                connessione.execute(
                    "INSERT OR REPLACE INTO parti_imparate_guardate (scatto_id, parte_id, "
                    "firma, quante, guardata_il) VALUES (?,?,?,?,?)",
                    (scatto_id, parte_id, modelli[parte_id].firma, quante, adesso()))
                self.avanzamento.parti += quante

    def _salta(self, scatto_id: int, codice: str) -> None:
        self._saltati.add(scatto_id)
        self.avanzamento.saltati += 1
        self.avanzamento.motivi[codice] = self.avanzamento.motivi.get(codice, 0) + 1


def misure_delle_parti(connessione) -> dict[int, dict]:
    fuori = {}
    for riga in tutti(connessione,
                      "SELECT parte_id, esempi, misura, allenata_il FROM parti_imparate"):
        resoconto = json.loads(riga["misura"] or "{}")
        fuori[riga["parte_id"]] = {"sagome": riga["esempi"],
                                   "allenata_il": riga["allenata_il"], **resoconto}
    return fuori


PERSE_DA_AVVISARE = 3
GRUPPI_DA_MOSTRARE = (("tutte", "in tutto"), ("difficili", "sui difficili"),
                      ("piccola", "piccole"), ("buia", "al buio"), ("mossa", "mosse o sfocate"),
                      ("video", "nei video"), ("persa", "che la parola non trova"))


def stato_delle_parti(connessione) -> list[dict]:
    from officina.modello import sagome as sagome_mod

    misure = misure_delle_parti(connessione)
    perse = sagome_mod.perse_per_parte(connessione)
    fuori = []
    for parte in tutti(connessione,
                       "SELECT id, nome, parola, nodo_id FROM parti_del_corpo "
                       "ORDER BY nome COLLATE NOCASE, id"):
        sagome = sagome_della_parte(connessione, parte["id"]) if parte["nodo_id"] else []
        misura = misure.get(parte["id"])
        gruppi = []
        for chiave, nome in GRUPPI_DA_MOSTRARE:
            gruppo = (misura or {}).get("gruppi", {}).get(chiave)
            if gruppo and gruppo["su"]:
                gruppi.append({"nome": nome, "giuste": gruppo["giuste"], "su": gruppo["su"],
                               "per_cento": round(100 * gruppo["giuste"] / gruppo["su"])})
        trovate = uno(connessione,
                      "SELECT count(DISTINCT scatto_id) AS q, sum(da_controllare) AS d "
                      "FROM parti_trovate WHERE parte_id = ? AND come = 'imparata'",
                      parte["id"])
        fuori.append({
            "id": parte["id"], "nome": parte["nome"], "parola": parte["parola"],
            "con_nodo": parte["nodo_id"] is not None,
            "sagome": len(sagome),
            "mancano": max(0, MINIMO_SAGOME - len(sagome)),
            "imparata": misura is not None,
            "gruppi": gruppi,
            "trovate": int(trovate["q"] or 0),
            "da_controllare": int(trovate["d"] or 0),
            "perse": perse.get(parte["id"], 0),
            "spesso_persa": perse.get(parte["id"], 0) >= PERSE_DA_AVVISARE,
        })
    return fuori
