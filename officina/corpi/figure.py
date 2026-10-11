from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import istruzioni, registro
from officina.archivio.database import adesso, tutti, uno
from officina.corpi import Interrotta, corpo3d, maschere, obiettivo
from officina.corpi import rilevatore as rilevatore_mod
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.importazione import gruppi
from officina.modello import file_media, segnalazioni

ASPETTO = "corpo3d-1"
VERSIONE_OBIETTIVO = "1-puffin-caption"
LATO_DELLE_FIGURE = 2048
SCATTI_A_TURNO = 16
PERSONE_A_TURNO = 8
DIAGONALE_35MM = math.hypot(36.0, 24.0)
RAPPORTI_INTERI = (4 / 3, 3 / 2, 16 / 9, 1.0)
IFD_EXIF = 0x8769
FUOCO_35MM = 0xA405
PARTI = (("forma", 45), ("scala", 28), ("parametri", 204), ("spostamento", 3), ("fuoco", 1),
         ("punti_3d", 210), ("punti_2d", 140))
NUMERI = sum(quanti for _, quanti in PARTI)
EXIF, PUFFIN, BASE = "exif", "puffin", "base"


@dataclass
class Avanzamento:
    fatti: int = 0
    saltati: int = 0
    figure: int = 0
    dall_exif: int = 0
    da_puffin: int = 0
    totale: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"figure in 3D: {self.figure} in {self.fatti} scatti · saltati {self.saltati} · "
                f"obiettivo dai dati della foto {self.dall_exif}, stimato da Puffin {self.da_puffin}")


@dataclass
class Lente:
    fonte: str
    campo_verticale: float
    rollio: float | None = None
    beccheggio: float | None = None
    distorsione: float | None = None

    def fuoco(self, alta: int) -> float:
        return alta / (2.0 * math.tan(self.campo_verticale / 2.0))


def campo_dall_exif(percorso: Path, larga: int, alta: int) -> float | None:
    from PIL import Image

    try:
        with Image.open(percorso) as aperta:
            esteso = aperta.getexif().get_ifd(IFD_EXIF) or {}
    except Exception:
        return None
    try:
        f35 = float(esteso.get(FUOCO_35MM) or 0)
    except (TypeError, ValueError):
        return None
    if f35 <= 0 or min(larga, alta) <= 0:
        return None
    rapporto = max(larga, alta) / min(larga, alta)
    if not any(abs(rapporto - giusto) / giusto < 0.01 for giusto in RAPPORTI_INTERI):
        return None
    fuoco = f35 * math.hypot(larga, alta) / DIAGONALE_35MM
    return 2.0 * math.atan(alta / (2.0 * fuoco))


def campo_di_base(larga: int, alta: int) -> float:
    return 2.0 * math.atan(alta / (2.0 * corpo3d.fuoco_di_base(larga, alta)))


def figura_a_numeri(figura, larga: int, alta: int) -> list[float]:
    punti_2d = [v for x, y in figura.punti_2d for v in (x / larga, y / alta)]
    return [*figura.forma, *figura.scala, *figura.parametri, *figura.spostamento, figura.fuoco / alta,
            *[v for terna in figura.punti_3d for v in terna], *punti_2d]


def numeri_a_figura(numeri) -> dict:
    numeri = [float(v) for v in numeri]
    if len(numeri) != NUMERI:
        raise ValueError(f"una figura ha {NUMERI} numeri, non {len(numeri)}")
    parti, posto = {}, 0
    for nome, quanti in PARTI:
        parti[nome] = numeri[posto:posto + quanti]
        posto += quanti
    parti["fuoco"] = parti["fuoco"][0]
    parti["punti_3d"] = [parti["punti_3d"][i:i + 3] for i in range(0, 210, 3)]
    parti["punti_2d"] = [parti["punti_2d"][i:i + 2] for i in range(0, 140, 2)]
    return parti


def maschera_intera(dati: bytes | None, riquadro, larga: int, alta: int):
    import numpy
    from PIL import Image

    piena = numpy.zeros((alta, larga), dtype=numpy.uint8)
    sinistra, sopra = int(round(riquadro[0] * larga)), int(round(riquadro[1] * alta))
    destra = min(larga, max(sinistra + 1, int(round((riquadro[0] + riquadro[2]) * larga))))
    sotto = min(alta, max(sopra + 1, int(round((riquadro[1] + riquadro[3]) * alta))))
    sinistra, sopra = max(0, min(sinistra, larga - 1)), max(0, min(sopra, alta - 1))
    pezzo = maschere.apri(dati or b"")
    if not pezzo.size or not pezzo.any():
        piena[sopra:sotto, sinistra:destra] = 1
        return piena
    grande = Image.fromarray(pezzo.astype(numpy.uint8) * 255, "L").resize(
        (destra - sinistra, sotto - sopra), Image.BILINEAR)
    piena[sopra:sotto, sinistra:destra] = numpy.asarray(grande) >= 128
    return piena


def cosa_manca(cartella_modelli: Path) -> str:
    mancano = [nome for nome, c_e in (("SAM 3D Body", corpo3d.ci_sono(cartella_modelli)),
                                      ("Puffin", obiettivo.ci_sono(cartella_modelli))) if not c_e]
    if not mancano:
        return ""
    return (f"Per la figura in 3D delle persone manca {' e '.join(mancano)}. Si scarica\n\n"
            f"{istruzioni.modello('corpi')}\n\n"
            "SAM 3D Body chiede di accettare la sua licenza su Hugging Face.")


class Figure:

    def __init__(self, cartella_modelli: Path):
        self.cartella_modelli = Path(cartella_modelli)
        self._lente = None
        self._corpo = None

    def accendi_la_lente(self) -> None:
        self._spegni_il_corpo()
        if self._lente is None:
            from officina.descrittori import torcia

            self._lente = obiettivo.costruisci(obiettivo.dove_stanno(self.cartella_modelli),
                                               torcia.macchina().dispositivo)

    def accendi_il_corpo(self) -> None:
        self._spegni_la_lente()
        if self._corpo is None:
            from officina.descrittori import torcia

            self._corpo = corpo3d.costruisci(corpo3d.dove_stanno(self.cartella_modelli),
                                             torcia.macchina().dispositivo)

    def _spegni_la_lente(self) -> None:
        if self._lente is not None:
            from officina.descrittori import torcia

            self._lente = None
            torcia.libera()

    def _spegni_il_corpo(self) -> None:
        if self._corpo is not None:
            from officina.descrittori import torcia

            self._corpo = None
            torcia.libera()

    def spegni(self) -> None:
        self._spegni_la_lente()
        self._spegni_il_corpo()

    def stima(self, immagine) -> Lente | None:
        rete, tokenizzatore = self._lente
        stimato = obiettivo.stima(rete, tokenizzatore, immagine)
        if stimato is None or not 0.0 < stimato.campo_verticale < math.pi:
            return None
        return Lente(PUFFIN, stimato.campo_verticale, stimato.rollio, stimato.beccheggio,
                     stimato.distorsione)

    def ricostruisci(self, pixel, riquadri, maschere_intere, fuoco: float):
        alta, larga = pixel.shape[:2]
        posa = corpo3d.ricostruisci(self._corpo, pixel, riquadri, maschere_intere,
                                    corpo3d.camera(larga, alta, fuoco))
        return corpo3d.in_figure(posa), posa["mani_valide"].tolist()


@dataclass
class Quadro:
    fotogramma: int
    immagine: object
    corpi: list


@dataclass
class Letto:
    scatto_id: int
    percorso: Path
    genere: str
    larga: int
    alta: int
    quadri: list[Quadro]
    lente: Lente | None = None


class Passata:

    def __init__(self, archivio, figure=None, fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self.figure = figure if figure is not None else Figure(archivio.dove.modelli)
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()
        self._fuori = fermato

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set() or bool(self._fuori and self._fuori())

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return quanti_mancano_senza_aprire(connessione)

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti: int | None = None) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            da_fare = [riga["id"] for riga in tutti(connessione, _da_fare(connessione, "s.id"),
                                                    rilevatore_mod.NOME, ASPETTO)]
        if quanti:
            da_fare = da_fare[:quanti]
        self.avanzamento.totale = len(da_fare)
        try:
            for inizio in range(0, len(da_fare), SCATTI_A_TURNO):
                if self.fermata:
                    break
                try:
                    self._fai_il_gruppo(da_fare[inizio:inizio + SCATTI_A_TURNO])
                except Interrotta:
                    break
                if al_passo:
                    al_passo(self.avanzamento)
        finally:
            self.figure.spegni()
        registro.evento("figure.passata", fatti=self.avanzamento.fatti, figure=self.avanzamento.figure)
        return self.avanzamento

    def _fai_il_gruppo(self, gruppo: list[int]) -> None:
        letti = []
        for scatto_id in gruppo:
            if self.fermata:
                raise Interrotta()
            try:
                letto = self._leggi(scatto_id)
            except ErroreOfficina as errore:
                self._segnala(scatto_id, errore)
                continue
            except Exception:                    # noqa: BLE001
                self._segnala(scatto_id, ErroreOfficina("Questo scatto non si è lasciato guardare."))
                continue
            if letto is not None:
                letti.append(letto)
        self._trova_le_lenti(letti)
        self._fai_le_figure(letti)

    def _leggi(self, scatto_id: int) -> Letto | None:
        from officina.immagini import lettura

        with self.archivio.lettura() as connessione:
            righe = file_media.di_scatto(connessione, scatto_id)
            principale = next((f for f in righe if f["ruolo"] == "principale"), None)
            if principale is None:
                raise ErroreOfficina("Questo scatto non ha un file principale.")
            percorso = file_media.percorso_migliore(connessione, principale["id"])
            corpi = tutti(connessione,
                          "SELECT c.id, c.fotogramma, c.riquadro, c.maschera FROM corpi c "
                          "WHERE c.scatto_id = ? AND c.modello = ? AND NOT EXISTS ("
                          "SELECT 1 FROM aspetti a WHERE a.corpo_id = c.id AND a.modello = ?) "
                          "ORDER BY c.fotogramma, c.id", scatto_id, rilevatore_mod.NOME, ASPETTO)
            istanti = {riga["fotogramma"]: riga["istante_ms"] for riga in tutti(
                connessione,
                "SELECT fotogramma, min(istante_ms) AS istante_ms FROM impronte "
                "WHERE scatto_id = ? AND inquadratura = 'intera' GROUP BY fotogramma", scatto_id)}
            gia = uno(connessione, "SELECT * FROM obiettivi WHERE scatto_id = ?", scatto_id)
        if percorso is None:
            raise ErroreOfficina("Il file non si trova sul disco.")
        if not corpi:
            return None
        per_quadro: dict[int, list] = {}
        for corpo in corpi:
            per_quadro.setdefault(int(corpo["fotogramma"]), []).append(corpo)
        quadri, larga, alta = [], 0, 0
        for numero, suoi in sorted(per_quadro.items()):
            if principale["genere"] == "immagine":
                intera = lettura.copia_di_lavoro(Path(percorso))
            else:
                from officina.immagini import fotogrammi as estrattore

                intera = estrattore.uno(Path(percorso), numero, istanti.get(numero))
            if intera is None:
                continue
            larga, alta = intera.size
            quadri.append(Quadro(numero, _ridotta(intera.convert("RGB")), list(suoi)))
        if not quadri:
            raise FileNonLeggibile("Non riesco a leggere i fotogrammi di questo scatto.",
                                   codice="non_letto")
        lente = None
        if gia is not None:
            lente = Lente(gia["fonte"], gia["campo_verticale"], gia["rollio"], gia["beccheggio"],
                          gia["distorsione"])
        return Letto(scatto_id, Path(percorso), principale["genere"], larga, alta, quadri, lente)

    def _trova_le_lenti(self, letti: list[Letto]) -> None:
        senza = []
        for letto in letti:
            if letto.lente is not None:
                continue
            campo = (campo_dall_exif(letto.percorso, letto.larga, letto.alta)
                     if letto.genere == "immagine" else None)
            if campo is not None:
                letto.lente = Lente(EXIF, campo)
                self._salva_la_lente(letto)
                self.avanzamento.dall_exif += 1
            else:
                senza.append(letto)
        if not senza:
            return
        self.figure.accendi_la_lente()
        for letto in senza:
            if self.fermata:
                raise Interrotta()
            stimata = self.figure.stima(letto.quadri[0].immagine)
            if stimata is None:
                larga, alta = letto.quadri[0].immagine.size
                stimata = Lente(BASE, campo_di_base(larga, alta))
            else:
                self.avanzamento.da_puffin += 1
            letto.lente = stimata
            self._salva_la_lente(letto)

    def _fai_le_figure(self, letti: list[Letto]) -> None:
        import numpy

        if not letti:
            return
        self.figure.accendi_il_corpo()
        for letto in letti:
            fatte: list[tuple[int, list[float], list[bool]]] = []
            try:
                for quadro in letto.quadri:
                    if self.fermata:
                        raise Interrotta()
                    larga, alta = quadro.immagine.size
                    pixel = numpy.asarray(quadro.immagine)
                    for primo in range(0, len(quadro.corpi), PERSONE_A_TURNO):
                        if self.fermata:
                            raise Interrotta()
                        corpi = quadro.corpi[primo:primo + PERSONE_A_TURNO]
                        riquadri_norm = [json.loads(c["riquadro"]) for c in corpi]
                        riquadri = numpy.array([[r[0] * larga, r[1] * alta, (r[0] + r[2]) * larga,
                                                 (r[1] + r[3]) * alta] for r in riquadri_norm],
                                               dtype=numpy.float64)
                        intere = numpy.stack([maschera_intera(c["maschera"], r, larga, alta)
                                              for c, r in zip(corpi, riquadri_norm, strict=True)])
                        figure, mani = self.figure.ricostruisci(pixel, riquadri, intere,
                                                               letto.lente.fuoco(alta))
                        for corpo, figura, sue in zip(corpi, figure, mani, strict=True):
                            fatte.append((corpo["id"], figura_a_numeri(figura, larga, alta), sue))
            except Interrotta:
                raise
            except ErroreOfficina as errore:
                self._segnala(letto.scatto_id, errore)
                continue
            except Exception:                    # noqa: BLE001
                self._segnala(letto.scatto_id, ErroreOfficina(
                    "La figura in 3D di questo scatto non si è lasciata fare."))
                continue
            self._salva_le_figure(fatte)
            self.avanzamento.fatti += 1
            self.avanzamento.figure += len(fatte)

    def _salva_la_lente(self, letto: Letto) -> None:
        lente = letto.lente
        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "INSERT OR REPLACE INTO obiettivi (scatto_id, fonte, campo_verticale, rollio, "
                "beccheggio, distorsione, versione, guardato_il) VALUES (?,?,?,?,?,?,?,?)",
                (letto.scatto_id, lente.fonte, lente.campo_verticale, lente.rollio, lente.beccheggio,
                 lente.distorsione, VERSIONE_OBIETTIVO, adesso()))

    def _salva_le_figure(self, fatte) -> None:
        from officina.modello import corpi as corpi_mod

        with self.archivio.scrittura() as connessione:
            for corpo_id, numeri, mani in fatte:
                connessione.execute(
                    "INSERT OR REPLACE INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
                    "SELECT id, ?, 1, ?, ? FROM corpi WHERE id = ?",
                    (ASPETTO, corpi_mod.vettore_a_byte(numeri), bytes(int(bool(m)) for m in mani),
                     corpo_id))

    def _segnala(self, scatto_id: int, errore: ErroreOfficina) -> None:
        self.avanzamento.saltati += 1
        codice = errore.codice or "non_letto"
        self.avanzamento.motivi[codice] = self.avanzamento.motivi.get(codice, 0) + 1
        quale = (segnalazioni.NON_SI_APRE if isinstance(errore, FileNonLeggibile)
                 else segnalazioni.FIGURE_NON_FATTE)
        with self.archivio.scrittura() as connessione:
            segnalazioni.segna(connessione, quale, scatto_id,
                               dettaglio=codice if quale == segnalazioni.NON_SI_APRE else errore.messaggio,
                               file_id=getattr(errore, "file_id", None))


def _ridotta(immagine):
    from PIL import Image

    if max(immagine.size) <= LATO_DELLE_FIGURE:
        return immagine
    copia = immagine.copy()
    copia.thumbnail((LATO_DELLE_FIGURE, LATO_DELLE_FIGURE), Image.Resampling.LANCZOS)
    return copia


def figura_di(connessione, corpo_id: int) -> dict | None:
    from officina.modello import corpi as corpi_mod

    riga = uno(connessione, "SELECT vettore, visibili FROM aspetti WHERE corpo_id = ? AND modello = ?",
               corpo_id, ASPETTO)
    if riga is None:
        return None
    figura = numeri_a_figura(corpi_mod.vettore_da_byte(riga["vettore"], 1).tolist())
    figura["mani"] = [bool(v) for v in (riga["visibili"] or b"")]
    return figura


def _da_fare(connessione, cosa: str) -> str:
    return f"""
        SELECT {cosa} FROM scatti s
        WHERE s.fuori_archivio = 0{gruppi.clausola(connessione, "intelligenza")}
          AND EXISTS (
              SELECT 1 FROM corpi c WHERE c.scatto_id = s.id AND c.modello = ?
                AND NOT EXISTS (SELECT 1 FROM aspetti a WHERE a.corpo_id = c.id AND a.modello = ?))
          {segnalazioni.clausola(segnalazioni.FIGURE_NON_FATTE)}
          {segnalazioni.clausola(segnalazioni.NON_SI_APRE)}
        ORDER BY s.id
    """


def quanti_mancano_senza_aprire(connessione) -> int:
    riga = uno(connessione, _da_fare(connessione, "count(*) AS q"), rilevatore_mod.NOME, ASPETTO)
    return int(riga["q"]) if riga else 0
