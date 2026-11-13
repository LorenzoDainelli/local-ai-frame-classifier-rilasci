from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from officina import registro
from officina.errori import ErroreOfficina

COSA = "stampa_veloce"
CARTELLA = "stampa-veloce"
MODULO = "officina.miglioria.stampa_stanza"
LATO = 4096
ORIGINALI = "originali"
VISTE = "viste"
SEEDVR2 = "seedvr2"
VOLTI = "volti"
SCELTE = (ORIGINALI, SEEDVR2, VOLTI)
STATO = "stato.json"
QUALITA_VISTA = 92
ASPETTA_LA_SCHEDA = 5.0
CARTA = "stampa_da_ripartire"
SENZA_SEEDVR2 = ("Per la stampa veloce serve SeedVR2 pronto: preparalo nelle "
                 "Impostazioni del miglioramento.")


class Fermata(Exception):
    pass


def misura_di(larghezza: int, altezza: int, lato: int = LATO) -> tuple[int, int] | None:
    lungo = max(int(larghezza), int(altezza))
    if lungo <= 0 or lungo >= lato:
        return None
    fattore = lato / lungo
    nuova_l = lato if larghezza >= altezza else max(1, round(larghezza * fattore))
    nuova_a = lato if altezza > larghezza else max(1, round(altezza * fattore))
    return nuova_l, nuova_a


def e_due_terzi(larghezza: int, altezza: int) -> bool:
    lungo, corto = max(larghezza, altezza), min(larghezza, altezza)
    return corto > 0 and abs(lungo / corto - 1.5) <= 0.01


def nome_pulito(nome: str) -> str:
    base = Path(str(nome)).name.strip()
    base = re.sub(r"[^\w.\- ()]+", "_", base)
    return base[:120] or "foto"


def _scrivi_json(percorso: Path, dati) -> None:
    provvisorio = percorso.with_name(percorso.name + ".nuovo")
    provvisorio.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(provvisorio, percorso)


def vista_di(sorgente: Path, verso: Path) -> None:
    from officina.miglioria import metadati

    aperta = metadati.apri(sorgente)
    immagine = in_srgb(aperta.immagine, aperta.metadati.icc)
    verso.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = verso.with_name(verso.name + ".nuovo")
    immagine.save(provvisorio, "JPEG", quality=QUALITA_VISTA)
    os.replace(provvisorio, verso)


def in_srgb(immagine, icc: bytes | None):
    if not icc:
        return immagine
    import io

    from PIL import ImageCms

    try:
        da = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        verso = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(immagine, da, verso, outputMode="RGB")
    except Exception as guasto:
        registro.avviso("stampa.colori_non_convertiti", **registro.dove_si_e_rotto(guasto))
        return immagine


class Stampa:

    def __init__(self, archivio, cartella: Path | None = None,
                 lancia: Callable[[dict, Callable], dict] | None = None, turno=None,
                 pronta: Callable[[], bool] | None = None, volti=None, sosta=None):
        from officina.web.lavori import Lavoro

        self.archivio = archivio
        self.cartella = Path(cartella or Path(archivio.dove.modelli) / CARTELLA)
        self._lancia = lancia or self._lancia_la_stanza
        self._turno = turno
        self._pronta = pronta or self._seedvr2_pronto
        self._volti = volti
        self._sosta = sosta
        self.lavoro = Lavoro(COSA, scheda=True)
        self._fermati = threading.Event()
        self._serratura = threading.RLock()
        self._processo: subprocess.Popen | None = None

    @property
    def turno(self):
        if self._turno is None:
            from officina.web import lavori

            return lavori.turno
        return self._turno

    def _stato(self) -> dict:
        try:
            dati = json.loads((self.cartella / STATO).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dati = {}
        foto = dati.get("foto") if isinstance(dati, dict) else None
        return {"foto": foto if isinstance(foto, list) else [],
                "prossimo": int(dati.get("prossimo") or 1) if isinstance(dati, dict) else 1}

    def _salva(self, stato: dict) -> None:
        self.cartella.mkdir(parents=True, exist_ok=True)
        _scrivi_json(self.cartella / STATO, stato)

    def file_di(self, foto: dict, quale: str) -> Path:
        if quale == ORIGINALI:
            return self.cartella / ORIGINALI / foto["file"]
        return self.cartella / quale / f"{foto['id']}.png"

    def vista(self, foto_id: int, quale: str) -> Path | None:
        if quale not in SCELTE:
            return None
        uno = self._una(foto_id)
        if uno is None:
            return None
        posto = self.cartella / VISTE / f"{uno['id']}-{quale}.jpg"
        if posto.is_file():
            return posto
        sorgente = self.file_di(uno, quale)
        if not sorgente.is_file():
            return None
        vista_di(sorgente, posto)
        return posto

    def _una(self, foto_id: int) -> dict | None:
        for uno in self._stato()["foto"]:
            if int(uno["id"]) == int(foto_id):
                return uno
        return None

    def aggiungi(self, nome: str, contenuto) -> dict:
        from officina.miglioria import metadati

        with self._serratura:
            stato = self._stato()
            numero = stato["prossimo"]
            pulito = nome_pulito(nome)
            file = f"{numero}-{pulito}"
            dove = self.cartella / ORIGINALI / file
            dove.parent.mkdir(parents=True, exist_ok=True)
            provvisorio = dove.with_name(dove.name + ".in-corso")
            with open(provvisorio, "wb") as fuori:
                shutil.copyfileobj(contenuto, fuori, 2 ** 20)
            try:
                aperta = metadati.apri(provvisorio)
            except Exception as guasto:
                provvisorio.unlink(missing_ok=True)
                raise ErroreOfficina(f"«{pulito}» non si apre come foto.",
                                     codice="stampa_non_foto") from guasto
            os.replace(provvisorio, dove)
            larghezza, altezza = aperta.immagine.size
            arrivo = misura_di(larghezza, altezza)
            uno = {"id": numero, "nome": pulito, "file": file,
                   "larghezza": larghezza, "altezza": altezza,
                   "arrivo": list(arrivo) if arrivo else None,
                   "due_terzi": e_due_terzi(larghezza, altezza),
                   "fatte": [], "scelta": None}
            stato["foto"].append(uno)
            stato["prossimo"] = numero + 1
            self._salva(stato)
            return uno

    def scegli(self, foto_id: int, quale: str | None) -> None:
        if quale is not None and quale not in SCELTE:
            raise ErroreOfficina("Scelta sconosciuta.", codice="stampa_scelta")
        with self._serratura:
            stato = self._stato()
            for uno in stato["foto"]:
                if int(uno["id"]) == int(foto_id):
                    pronta = quale in (None, ORIGINALI) or quale in uno["fatte"]
                    if not pronta:
                        raise ErroreOfficina("Questa versione non è ancora pronta.",
                                             codice="stampa_non_pronta")
                    uno["scelta"] = quale
                    self._salva(stato)
                    return
        raise ErroreOfficina("Foto non trovata.", codice="stampa_non_trovata")

    def togli(self, foto_id: int) -> None:
        if self.lavoro.sta_lavorando:
            raise ErroreOfficina("Aspetta che il lavoro finisca o fermalo.",
                                 codice="stampa_al_lavoro")
        with self._serratura:
            stato = self._stato()
            restano = []
            for uno in stato["foto"]:
                if int(uno["id"]) == int(foto_id):
                    for quale in SCELTE:
                        self.file_di(uno, quale).unlink(missing_ok=True)
                        (self.cartella / VISTE / f"{uno['id']}-{quale}.jpg").unlink(
                            missing_ok=True)
                else:
                    restano.append(uno)
            stato["foto"] = restano
            self._salva(stato)

    def svuota(self) -> None:
        if self.lavoro.sta_lavorando:
            raise ErroreOfficina("Aspetta che il lavoro finisca o fermalo.",
                                 codice="stampa_al_lavoro")
        with self._serratura:
            shutil.rmtree(self.cartella, ignore_errors=True)

    def come_va(self) -> dict:
        stato = self.lavoro.come_va()
        foto = self._stato()["foto"]
        stato["foto"] = foto
        stato["volti"] = self._motore_dei_volti()
        stato["pronta"] = bool(self._pronta())
        stato["approvate"] = sum(1 for uno in foto if uno.get("scelta"))
        return stato

    def zip(self, verso) -> int:
        from officina.miglioria import metadati

        quante = 0
        usati: set[str] = set()
        with zipfile.ZipFile(verso, "w", zipfile.ZIP_STORED) as archivio_zip:
            for uno in self._stato()["foto"]:
                quale = uno.get("scelta")
                if not quale:
                    continue
                sorgente = self.file_di(uno, quale)
                if not sorgente.is_file():
                    continue
                radice = Path(uno["nome"]).stem
                if quale == ORIGINALI:
                    nome = uno["nome"]
                else:
                    nome = f"{radice}.jpg"
                while nome in usati:
                    nome = f"{uno['id']}-{nome}"
                usati.add(nome)
                if quale == ORIGINALI:
                    archivio_zip.write(sorgente, nome)
                else:
                    archivio_zip.writestr(nome, self._jpeg(uno, sorgente, metadati))
                quante += 1
        return quante

    def _jpeg(self, uno: dict, sorgente: Path, metadati) -> bytes:
        import io

        from PIL import Image

        originale = metadati.apri(self.file_di(uno, ORIGINALI))
        with Image.open(sorgente) as aperta:
            immagine = aperta.convert("RGB")
        immagine = in_srgb(immagine, originale.metadati.icc)
        larghezza, altezza = immagine.size
        exif = metadati.exif_raddrizzato(originale.metadati.exif, larghezza, altezza)
        fuori = io.BytesIO()
        opzioni = {"quality": 100, "subsampling": 0, "dpi": (300, 300)}
        if exif:
            opzioni["exif"] = exif
        immagine.save(fuori, "JPEG", **opzioni)
        return fuori.getvalue()

    def parti(self) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        if not self._pronta():
            raise ErroreOfficina(SENZA_SEEDVR2, codice="stampa_senza_seedvr2")
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome=COSA)

    def ferma(self, aspetta: float = 0.0) -> None:
        self._fermati.set()
        processo = self._processo
        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
            except OSError:
                pass
        if aspetta:
            self.lavoro.aspetta_che_finisca(aspetta)

    def _ricorda(self, processo: subprocess.Popen) -> None:
        self._processo = processo
        if self._fermati.is_set():
            try:
                processo.terminate()
            except OSError:
                pass

    def _lancia_la_stanza(self, lavoro: dict, al_passo: Callable[[int, int], None]) -> dict:
        from officina.miglioria.lavoro import lancia_la_stanza

        return lancia_la_stanza(lavoro, al_passo, self._ricorda, MODULO)

    def _seedvr2_pronto(self) -> bool:
        from officina.miglioria import preparazione

        return bool(preparazione.e_pronto(self.archivio.dove.modelli))

    def _motore_dei_volti(self) -> str | None:
        if self._volti is not None:
            return self._volti()
        from officina.miglioria import motori
        from officina.miglioria.lavoro import volti_da_soli

        modelli = Path(self.archivio.dove.modelli)
        return motori.CODEFORMER if volti_da_soli(modelli, senza_faceme=True) else None

    def _la_sosta(self):
        if self._sosta is not None:
            return self._sosta
        from officina.programma import carta
        from officina.web import sosta

        return sosta.Sosta(leggi=lambda: carta.leggi().get(CARTA),
                           scrivi=lambda valore: carta.aggiorna(**{CARTA: valore}))

    def _gira(self) -> None:
        sosta = self._la_sosta()
        self._finito = False
        sosta.guarda(lambda: not self._finito)
        try:
            self._corri(sosta)
        except Fermata:
            self.lavoro.di("fermato: riparte da dove era")
        finally:
            self._finito = True
            self._processo = None
            self.turno.lascia(self.lavoro)
            self.lavoro.senza_numeri()
            try:
                sosta.giro()
            finally:
                sosta.smetti(0.5)
            self.lavoro.di("gli altri lavori ripartono")

    _finito = True

    def _corri(self, sosta) -> None:
        stato = self._stato()
        volti = self._motore_dei_volti()
        da_fare = []
        for uno in stato["foto"]:
            if not uno.get("arrivo"):
                continue
            mancano = [q for q in (SEEDVR2, VOLTI) if q not in uno["fatte"]]
            if volti is None and VOLTI in mancano:
                mancano.remove(VOLTI)
            if not mancano:
                continue
            da_fare.append({"id": uno["id"], "originale": str(self.file_di(uno, ORIGINALI)),
                            "seedvr2": str(self.file_di(uno, SEEDVR2)),
                            "volti": str(self.file_di(uno, VOLTI)),
                            "larghezza": uno["arrivo"][0], "altezza": uno["arrivo"][1]})
        if not da_fare:
            self.lavoro.di("niente da fare: sono già tutte pronte")
            return
        self.lavoro.di("metto in pausa gli altri lavori dell'IA")
        sosta.subito()
        self._prendi_la_scheda()
        from officina.miglioria.lavoro import RAM_POCA, a_parole, percorsi_della_stanza

        lavoro = {"foto": da_fare, "volti": volti,
                  "intensita": int(self.archivio.impostazione("intensita_scheda") or 100),
                  "opzioni": {"cartella_modelli": str(self.archivio.dove.modelli)},
                  "percorsi": percorsi_della_stanza()}
        self.lavoro.di(f"SeedVR2 si carica una volta e fa {len(da_fare)} foto"
                       + (f", poi {volti} i volti" if volti else
                          "; i volti non si ritoccano: il motore non è pronto"))
        self.lavoro.fasi(lavoro=1)
        self.lavoro.fase("lavoro")
        partito = time.monotonic()
        esito = self._lancia(lavoro, self._al_passo)
        if esito.get("guasto") == RAM_POCA and not self._fermati.is_set():
            self.lavoro.di("la RAM non basta: riparto con una parte dei pesi sul disco")
            lavoro["opzioni"]["disco"] = True
            esito = self._lancia(lavoro, self._al_passo)
        self._segna_le_fatte()
        if self._fermati.is_set():
            raise Fermata()
        if "guasto" in esito:
            detto = str(esito.get("spiegazione") or "") or a_parole(str(esito["guasto"]))
            raise ErroreOfficina(detto or "Il lavoro si è fermato per un guasto.",
                                 codice=str(esito["guasto"]))
        minuti = (time.monotonic() - partito) / 60
        self.lavoro.di(f"finito in {minuti:.0f} minuti: ora scegli e scarica")

    def _segna_le_fatte(self) -> None:
        with self._serratura:
            stato = self._stato()
            for uno in stato["foto"]:
                fatte = [q for q in (SEEDVR2, VOLTI) if self.file_di(uno, q).is_file()]
                uno["fatte"] = fatte
            self._salva(stato)

    def _al_passo(self, fatti: int, totale: int) -> None:
        if self._fermati.is_set():
            return
        self.lavoro.a_che_punto_a_pezzi(fatti, totale)
        self._segna_le_fatte()

    def _prendi_la_scheda(self) -> None:
        detto = False
        try:
            while not self.turno.prendi_se_libera(self.lavoro):
                if self.turno.chi is self.lavoro:
                    return
                if not detto:
                    self.lavoro.di("aspetto che la scheda si liberi")
                    self.lavoro.in_pausa(True)
                    detto = True
                if self._fermati.wait(ASPETTA_LA_SCHEDA):
                    raise Fermata()
        finally:
            self.lavoro.in_pausa(False)


__all__ = ["COSA", "Fermata", "LATO", "Stampa", "e_due_terzi", "misura_di", "nome_pulito"]
