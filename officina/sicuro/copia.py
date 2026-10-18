from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati
from officina.sicuro.diretto import ALLINEA, Lettore
from officina.sicuro.disco import fissa_cartella, percorso_lungo


TENTATIVI = 3
ATTESE = (1.0, 3.0, 10.0)
LETTURE_PER_SETTORE = 3
PEZZO_DI_LETTURA = 4 * 1024 * 1024
CANDIDATI = 3
FATTI_PER_NOTA = 2000
SECONDI_PER_NOTA = 300.0
VELOCITA = 100 * 1024 * 1024
SPAZIO_IN_PIU = 1.10
DA_SALTARE = frozenset({"$recycle.bin", "system volume information"})
SEGNI_DA_RIFARE = frozenset({"in_uso", "incompleto"})
STATI_BUONI = ("buono", "riparato")
BLOCCATO = (32, 33)
PROVVISORI = (".nuovo", ".tenuto")
ROSSI = frozenset({
    "in_uso", "incompleto", "solo_nel_cloud", "bloccato", "illeggibile",
    "cartella_illeggibile", "radice_mancante", "radice_illeggibile",
    "nome_strano", "cambia_sempre", "flussi_illeggibili", "flusso_strano",
    "radice_nell_archivio"})


class DiscoArchivioGuasto(ErroreOfficina):
    codice = "disco_archivio_guasto"


class Fermato(Exception):
    pass


class _Bloccato(Exception):
    pass


class _NonPiuUnFile(Exception):
    pass


def _bloccato(guasto: OSError) -> bool:
    return getattr(guasto, "winerror", None) in BLOCCATO


def _senza_accesso(metadati_: dict) -> dict:
    return {chiave: valore for chiave, valore in metadati_.items()
            if chiave != "accesso"}


def _sotto(percorso: str, cartelle: set[str]) -> bool:
    if not cartelle:
        return False
    if "" in cartelle or percorso in cartelle:
        return True
    parti = percorso.split("/")
    return any("/".join(parti[:fine]) in cartelle for fine in range(1, len(parti)))


@dataclass
class Giro:
    radice: str
    inizio: float
    fine: float | None = None
    problemi: list[tuple[str, str | None]] = field(default_factory=list)
    contati: dict[str, int] = field(default_factory=dict)

    def problema(self, codice: str, percorso: str | None = None) -> None:
        self.problemi.append((codice, percorso))

    def conta(self, nome: str, quanti: int = 1) -> None:
        self.contati[nome] = self.contati.get(nome, 0) + quanti

    @property
    def rossi(self) -> list[tuple[str, str | None]]:
        return [problema for problema in self.problemi if problema[0] in ROSSI]

    @property
    def verde(self) -> bool:
        return self.fine is not None and not self.rossi

    def fatto(self) -> dict:
        return registro.fatto_giro(self.radice, self.inizio, self.fine,
                                   self.problemi, self.contati)


@dataclass
class Avanzamento:
    radice: str | None = None
    percorso: str | None = None
    file: int = 0
    letti: int = 0
    copiati: int = 0
    doppioni: int = 0
    uguali: int = 0


@dataclass
class Riepilogo:
    cartelle: int = 0
    file: int = 0
    byte: int = 0
    da_copiare: int = 0
    byte_da_copiare: int = 0
    forse_doppioni: int = 0
    nel_cloud: int = 0
    spazio_serve: int = 0
    spazio_libero: int = 0
    secondi: float = 0.0
    problemi: list[tuple[str, str | None]] = field(default_factory=list)
    radici: dict[str, dict] = field(default_factory=dict)

    @property
    def basta_lo_spazio(self) -> bool:
        return self.spazio_libero >= self.spazio_serve


@dataclass
class _Passata:
    esito: str
    scritto: formato.Scritto | None = None
    buchi: tuple[int, ...] = ()
    doppione: str | None = None
    tenuta: bool = False


@dataclass
class _Risultato:
    numero: str | None
    problema: str | None = None
    nuovo: formato.Scritto | None = None
    provvisorio: Path | None = None
    stato: str = "buono"
    segni: frozenset[str] = frozenset()
    info: object = None
    fatto: dict | None = None


class _Confronto:

    def __init__(self, copiatore: Copiatore, originale):
        self._copiatore = copiatore
        self._originale = originale
        self.dove = 0
        self.diverso = False
        self.buchi: set[int] = set()
        self.blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        self.sha = hashlib.sha256()

    def __call__(self, chiaro: bytes) -> None:
        letto, buchi = self._copiatore._leggi_pezzo(self._originale, self.dove,
                                                     len(chiaro))
        self.buchi.update(buchi)
        if letto != chiaro:
            self.diverso = True
        self.blake.update(letto)
        self.sha.update(letto)
        self.dove += len(letto)
        self._copiatore.avanzamento.letti += len(letto)

    def impronte(self) -> dict:
        return {"blake2b": self.blake.hexdigest(), "sha256": self.sha.hexdigest()}


class Copiatore:

    def __init__(self, cartella: Path, elenco: registro.Elenco, chiave, *,
                 tentativi: int = TENTATIVI, attese=ATTESE, dormi=time.sleep,
                 adesso=time.time, apri=Lettore, atteso=None, aspetta=None,
                 spazio=None, settore: int = ALLINEA, salta=()):
        self.cartella = Path(cartella)
        self._salta = (self.cartella, *salta)
        self.elenco = elenco
        self._chiave = chiave
        self._tentativi = max(1, tentativi)
        self._attese = tuple(attese) or (0.0,)
        self._dormi = dormi
        self._adesso = adesso
        self._apri = apri
        self._atteso = atteso
        self._aspetta = aspetta
        self._spazio = spazio
        self._settore = settore
        self.avanzamento = Avanzamento()
        self._per_nota: list[dict] = []
        self._ultima_nota = time.monotonic()

    def _ferma_se_serve(self) -> None:
        if self._aspetta is not None:
            self._aspetta()

    def pulisci_provvisori(self) -> int:
        tolti = 0
        try:
            sotto = [voce.path for voce in os.scandir(self.cartella / registro.CONTENUTI)
                     if voce.is_dir(follow_symlinks=False)]
        except FileNotFoundError:
            return 0
        for dove in sotto:
            with os.scandir(dove) as voci:
                vecchi = [voce.path for voce in voci
                          if voce.name.endswith(PROVVISORI)
                          and voce.is_file(follow_symlinks=False)]
            for percorso in vecchi:
                os.unlink(percorso)
                tolti += 1
        return tolti

    @staticmethod
    def _assoluto(radice: str, relativo: str) -> str:
        return os.path.join(radice, *relativo.split("/")) if relativo else radice

    @staticmethod
    def _nome_buono(nome: str, relativo: str) -> bool:
        if any(segno in nome for segno in "\\/\x00"):
            return False
        try:
            return registro.percorso_pulito(relativo) == relativo
        except ValueError:
            return False

    @staticmethod
    def _radice_c_e(percorso: str) -> bool:
        try:
            return stat.S_ISDIR(os.stat(percorso_lungo(percorso)).st_mode)
        except (OSError, ValueError):
            return False

    def _da_saltare(self) -> tuple[set[tuple[int, int]], set[str]]:
        identita: set[tuple[int, int]] = set()
        percorsi: set[str] = set()
        for cartella in self._salta:
            percorsi.add(os.path.normcase(os.path.abspath(cartella)))
            try:
                stato = os.stat(percorso_lungo(cartella))
            except (OSError, ValueError):
                continue
            if stato.st_ino:
                identita.add((stato.st_dev, stato.st_ino))
        return identita, percorsi

    @staticmethod
    def _saltata(assoluto: str, stato, saltare) -> bool:
        identita, percorsi = saltare
        if stato.st_ino and (stato.st_dev, stato.st_ino) in identita:
            return True
        return os.path.normcase(os.path.abspath(assoluto)) in percorsi

    def cammina(self, radice: str, giro: Giro, illeggibili: set[str]):
        saltare = self._da_saltare()
        try:
            if self._saltata(radice, os.stat(percorso_lungo(radice)), saltare):
                giro.problema("radice_nell_archivio")
                illeggibili.add("")
                return
        except (OSError, ValueError):
            pass
        pila = [""]
        while pila:
            relativo = pila.pop()
            try:
                with os.scandir(percorso_lungo(self._assoluto(radice, relativo))) as voci:
                    nomi = sorted(voce.name for voce in voci)
            except OSError:
                giro.problema("radice_illeggibile" if relativo == ""
                              else "cartella_illeggibile", relativo or None)
                illeggibili.add(relativo)
                continue
            figli = []
            for nome in nomi:
                if nome.casefold() in DA_SALTARE:
                    continue
                figlio = f"{relativo}/{nome}" if relativo else nome
                if not self._nome_buono(nome, figlio):
                    giro.problema("nome_strano", f"{relativo}/{nome}" if relativo
                                  else nome)
                    continue
                assoluto = self._assoluto(radice, figlio)
                try:
                    stato = os.lstat(percorso_lungo(assoluto))
                except FileNotFoundError:
                    continue
                except OSError:
                    giro.problema("illeggibile", figlio)
                    illeggibili.add(figlio)
                    continue
                cartella = metadati.tipo_di(stato) == metadati.CARTELLA
                if cartella and self._saltata(assoluto, stato, saltare):
                    giro.conta("saltate")
                    continue
                yield figlio, stato
                if cartella:
                    figli.append(figlio)
            pila.extend(reversed(figli))

    def copia_radice(self, radice: dict) -> Giro:
        giro = Giro(radice["id"], self._adesso())
        self.avanzamento.radice = radice["id"]
        self._per_nota.append(self._fatto_radice(radice))
        self._registra([giro.fatto()])
        illeggibili: set[str] = set()
        visti: set[str] = set()
        try:
            if not self._radice_c_e(radice["percorso"]):
                giro.problema("radice_mancante")
            else:
                for relativo, stato in self.cammina(radice["percorso"], giro,
                                                    illeggibili):
                    self._ferma_se_serve()
                    visti.add(relativo)
                    self._uno(radice, relativo, stato, giro, visti, illeggibili)
                self._spariti(radice["id"], visti, illeggibili, giro)
            giro.fine = self._adesso()
        finally:
            self.avanzamento.percorso = None
            self._registra([giro.fatto()])
            self._scrivi_nota()
        return giro

    @staticmethod
    def _fatto_radice(radice: dict) -> dict:
        return registro.fatto_radice(
            radice["id"], radice["percorso"], bool(radice.get("tolta")),
            quando=radice.get("cambiata") or radice["aggiunta"])

    def _spariti(self, radice: str, visti: set[str], illeggibili: set[str],
                 giro: Giro) -> None:
        if "" in illeggibili:
            return
        fatti = [registro.fatto_sparito(posto.chiave, self._adesso())
                 for posto in self.elenco.dentro(radice)
                 if posto.percorso not in visti
                 and not _sotto(posto.percorso, illeggibili)]
        if fatti:
            giro.conta("spariti", len(fatti))
            self._registra(fatti)

    def _uno(self, radice: dict, relativo: str, stato, giro: Giro,
             visti: set[str], illeggibili: set[str]) -> None:
        self.avanzamento.percorso = relativo
        assoluto = self._assoluto(radice["percorso"], relativo)
        try:
            letto = metadati.leggi(assoluto, stato)
        except FileNotFoundError:
            visti.discard(relativo)
            return
        except OSError:
            giro.problema("illeggibile", relativo)
            illeggibili.add(relativo)
            return
        for avviso in letto.avvisi:
            if avviso != "solo_nel_cloud":
                giro.problema(avviso, relativo)
        if letto.tipo == metadati.SPECIALE:
            return
        attuale = self.elenco.attuale(radice["id"], relativo)
        if letto.tipo != metadati.FILE:
            self._senza_byte(radice, relativo, letto, attuale, giro)
            return
        giro.conta("file")
        giro.conta("byte", letto.dimensione)
        self.avanzamento.file += 1
        if attuale is not None and self._ancora_uguale(attuale, letto):
            self.avanzamento.uguali += 1
            if not letto.cloud and (_senza_accesso(attuale.metadati)
                                    != _senza_accesso(letto.metadati)):
                self._solo_metadati(radice, relativo, letto, attuale)
            return
        if letto.cloud:
            giro.problema("solo_nel_cloud", relativo)
            return
        risultato = self._copia_file(radice, relativo, assoluto, letto, attuale,
                                     giro)
        if risultato == "sparito":
            visti.discard(relativo)

    def _senza_byte(self, radice: dict, relativo: str, letto, attuale,
                    giro: Giro) -> None:
        giro.conta("cartelle" if letto.tipo == metadati.CARTELLA
                   else "collegamenti")
        if (attuale is not None and attuale.tipo == letto.tipo
                and _senza_accesso(attuale.metadati)
                == _senza_accesso(letto.metadati)):
            return
        fatti = [registro.fatto_posto(radice["id"], relativo, letto.tipo, None,
                                      letto.metadati, quando=self._adesso())]
        if attuale is not None:
            fatti.append(registro.fatto_sparito(attuale.chiave, self._adesso()))
        self._registra(fatti)

    def _ancora_uguale(self, attuale: registro.Posto, letto) -> bool:
        if (attuale.tipo != metadati.FILE or attuale.contenuto is None
                or SEGNI_DA_RIFARE & set(attuale.segni)):
            return False
        informazioni = self.elenco.contenuto(attuale.contenuto)
        if (informazioni is None or informazioni["stato"] not in STATI_BUONI
                or informazioni["dimensione"] != letto.dimensione):
            return False
        if any(attuale.metadati.get(chiave) != letto.metadati.get(chiave)
               for chiave in ("modifica", "creazione")):
            return False
        if letto.cloud or "flussi_illeggibili" in letto.avvisi:
            return True
        salvati = {nome for nome, _ in self.elenco.flussi_di(attuale.chiave)}
        return salvati == {nome for nome, _ in letto.flussi
                           if metadati.nome_di_flusso_buono(nome)}

    def _solo_metadati(self, radice: dict, relativo: str, letto,
                       attuale: registro.Posto) -> None:
        nuovo = registro.fatto_posto(radice["id"], relativo, metadati.FILE,
                                     attuale.contenuto, letto.metadati,
                                     attuale.segni, quando=self._adesso())
        fatti = [nuovo]
        fatti += [registro.fatto_flusso(nuovo["chiave"], nome, numero)
                  for nome, numero in self.elenco.flussi_di(attuale.chiave)]
        fatti.append(registro.fatto_sparito(attuale.chiave, self._adesso()))
        self._registra(fatti)

    def _copia_file(self, radice: dict, relativo: str, assoluto: str, letto,
                    attuale, giro: Giro) -> str | None:
        chiave_posto = registro.nuova_chiave()
        fatto_radice = self._fatto_radice(radice)

        def segno_ora():
            return metadati.segno_di(os.lstat(percorso_lungo(assoluto)))

        def prepara(tentativo: int, numero: str):
            info = letto if tentativo == 0 else metadati.leggi(assoluto)
            if info.tipo != metadati.FILE or info.cloud:
                raise _NonPiuUnFile
            posto = registro.fatto_posto(radice["id"], relativo, metadati.FILE,
                                         numero, info.metadati,
                                         chiave=chiave_posto,
                                         quando=self._adesso())
            return info, info.segno, [fatto_radice, posto], posto

        if self._spazio is not None:
            self._spazio(formato.peso_previsto(letto.dimensione))
        principale = self._porta(assoluto, prepara, segno_ora)
        provvisori = [principale.provvisorio]
        try:
            if principale.numero is None:
                if principale.problema != "sparito":
                    giro.problema(principale.problema, relativo)
                return principale.problema
            flussi = []
            for nome, _ in principale.info.flussi:
                portato = self._porta_flusso(assoluto, nome, chiave_posto,
                                             segno_ora, giro, relativo)
                if portato is not None:
                    provvisori.append(portato.provvisorio)
                    flussi.append((nome, portato))
            segni = set(principale.segni)
            for _, portato in flussi:
                segni |= portato.segni
            if principale.problema:
                giro.problema(principale.problema, relativo)
            if self._diverso_da_prima(radice["id"], relativo, principale):
                segni.add("diverso_da_prima")
                giro.problema("diverso_da_prima", relativo)
            if self._stesso_posto(attuale, principale, segni, flussi):
                return None
            fatti = []
            if principale.nuovo is not None:
                self._fissa(principale)
                fatti += self._fatti_contenuto(principale)
            fatti.append(dict(principale.fatto, contenuto=principale.numero,
                              segni=sorted(segni)))
            for nome, portato in flussi:
                if portato.nuovo is not None:
                    self._fissa(portato)
                    fatti += self._fatti_contenuto(portato)
                fatti.append(registro.fatto_flusso(chiave_posto, nome,
                                                   portato.numero))
            if attuale is not None:
                fatti.append(registro.fatto_sparito(attuale.chiave, self._adesso()))
            self._registra(fatti)
            return None
        finally:
            for provvisorio in provvisori:
                if provvisorio is not None:
                    provvisorio.unlink(missing_ok=True)

    def _fatti_contenuto(self, risultato: _Risultato) -> list[dict]:
        fatti = [registro.fatto_contenuto(risultato.nuovo, risultato.stato,
                                          quando=self._adesso())]
        if risultato.stato != "buono":
            fatti.append(registro.fatto_stato(risultato.numero, risultato.stato,
                                              quando=self._adesso()))
        return fatti

    def _stesso_posto(self, attuale, principale: _Risultato, segni: set[str],
                      flussi: list) -> bool:
        if (attuale is None or principale.nuovo is not None
                or any(portato.nuovo is not None for _, portato in flussi)
                or attuale.contenuto != principale.numero
                or set(attuale.segni) != segni):
            return False
        if (_senza_accesso(attuale.metadati)
                != _senza_accesso(principale.fatto["metadati"])):
            return False
        return dict(self.elenco.flussi_di(attuale.chiave)) == {
            nome: portato.numero for nome, portato in flussi}

    def _porta_flusso(self, assoluto: str, nome: str, chiave_posto: str,
                      segno_ora, giro: Giro, relativo: str) -> _Risultato | None:
        try:
            dove = metadati.percorso_del_flusso(assoluto, nome)
        except ErroreOfficina:
            giro.problema("flusso_strano", relativo)
            return None

        def prepara(tentativo: int, numero: str):
            fatto = registro.fatto_flusso(chiave_posto, nome, numero)
            return None, segno_ora(), [fatto], fatto

        portato = self._porta(dove, prepara, segno_ora)
        if portato.numero is None:
            if portato.problema != "sparito":
                giro.problema(portato.problema, relativo)
            return None
        if portato.problema:
            giro.problema(portato.problema, relativo)
        return portato

    def _fissa(self, risultato: _Risultato) -> None:
        finale = registro.percorso_contenuto(self.cartella, risultato.numero)
        os.replace(risultato.provvisorio, finale)
        fissa_cartella(finale.parent)
        self.avanzamento.copiati += 1

    def _diverso_da_prima(self, radice: str, relativo: str,
                          risultato: _Risultato) -> bool:
        if self._atteso is None:
            return False
        try:
            atteso = self._atteso(radice, relativo)
        except Exception:
            return False
        if not atteso:
            return False
        if risultato.nuovo is not None:
            valori = {"dimensione": risultato.nuovo.dimensione,
                      "blake2b": risultato.nuovo.blake2b,
                      "sha256": risultato.nuovo.sha256}
        else:
            valori = self.elenco.contenuto(risultato.numero) or {}
        return any(chiave in atteso and atteso[chiave] != valori.get(chiave)
                   for chiave in ("dimensione", "blake2b", "sha256"))

    def _porta(self, percorso: str, prepara, segno_ora) -> _Risultato:
        numero = formato.nuovo_numero()
        finale = registro.percorso_contenuto(self.cartella, numero.hex())
        finale.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = finale.with_name(finale.name + ".nuovo")
        tenuto = finale.with_name(finale.name + ".tenuto")
        migliore: tuple[_Passata, object, dict] | None = None
        ultimo = "illeggibile"
        sbagliati = 0
        riuscito = False
        try:
            for tentativo in range(self._tentativi):
                if tentativo:
                    self._dormi(self._attese[min(tentativo - 1, len(self._attese) - 1)])
                    self._ferma_se_serve()
                try:
                    info, segno, fatti_meta, fatto = prepara(tentativo, numero.hex())
                except FileNotFoundError:
                    return _Risultato(None, "sparito")
                except _NonPiuUnFile:
                    ultimo = "cambiato"
                    continue
                except OSError:
                    ultimo = "illeggibile"
                    continue
                passata = self._passata(percorso, numero, provvisorio, fatti_meta,
                                        segno, segno_ora)
                ultimo = passata.esito
                if passata.esito == "sparito":
                    return _Risultato(None, "sparito")
                if passata.esito == "sbagliato":
                    sbagliati += 1
                    if sbagliati >= 2:
                        raise DiscoArchivioGuasto(
                            "Il disco dell'archivio ha scritto male due volte di "
                            "fila lo stesso file: mi fermo per non rovinare "
                            "niente.")
                    continue
                if passata.esito == "doppione":
                    riuscito = True
                    self.avanzamento.doppioni += 1
                    return _Risultato(passata.doppione, info=info, fatto=fatto)
                if passata.esito == "fatto":
                    riuscito = True
                    return _Risultato(numero.hex(), nuovo=passata.scritto,
                                      provvisorio=provvisorio, info=info,
                                      fatto=fatto)
                if passata.tenuta and self._meglio(passata, migliore):
                    os.replace(provvisorio, tenuto)
                    migliore = (passata, info, fatto)
                else:
                    provvisorio.unlink(missing_ok=True)
            if migliore is not None:
                passata, info, fatto = migliore
                os.replace(tenuto, provvisorio)
                if passata.esito == "buchi":
                    stesso = self._incompleto_uguale(provvisorio, numero,
                                                     passata.scritto)
                    if stesso is not None:
                        self.avanzamento.doppioni += 1
                        return _Risultato(stesso, "incompleto",
                                          segni=frozenset({"incompleto"}),
                                          info=info, fatto=fatto)
                    riuscito = True
                    return _Risultato(numero.hex(), "incompleto",
                                      nuovo=passata.scritto,
                                      provvisorio=provvisorio,
                                      stato="incompleto",
                                      segni=frozenset({"incompleto"}),
                                      info=info, fatto=fatto)
                if self._blob_sano(provvisorio, numero, passata.scritto):
                    riuscito = True
                    return _Risultato(numero.hex(), "in_uso",
                                      nuovo=passata.scritto,
                                      provvisorio=provvisorio,
                                      segni=frozenset({"in_uso"}), info=info,
                                      fatto=fatto)
            return _Risultato(None, {"bloccato": "bloccato",
                                     "cambiato": "cambia_sempre"}.get(
                                         ultimo, "illeggibile"))
        finally:
            tenuto.unlink(missing_ok=True)
            if not riuscito:
                provvisorio.unlink(missing_ok=True)

    @staticmethod
    def _meglio(passata: _Passata, migliore) -> bool:
        if migliore is None:
            return True
        vecchia = migliore[0]
        if passata.esito == "buchi":
            return vecchia.esito != "buchi" or len(passata.buchi) < len(vecchia.buchi)
        return vecchia.esito != "buchi"

    def _incompleto_uguale(self, blob: Path, numero: bytes,
                           scritto: formato.Scritto) -> str | None:
        for candidato, testa in self._candidati(scritto, ("incompleto",)):
            if self._stessi_byte(blob, numero, scritto, candidato, testa):
                return candidato
        return None

    def _stessi_byte(self, blob: Path, numero: bytes, scritto: formato.Scritto,
                     candidato: str, testa: bytes) -> bool:
        impronte = {"blake2b": scritto.blake2b, "sha256": scritto.sha256}
        diversi = []
        try:
            with self._apri(blob, True) as nostro, self._apri(
                    registro.percorso_contenuto(self.cartella, candidato),
                    True) as altro:
                nuovo = formato.Contenuto(nostro, self._chiave, numero=numero,
                                          testa=scritto.testa)
                fila = iter(range(nuovo.forma.blocchi))

                def confronta(pezzo: bytes) -> None:
                    if pezzo != nuovo.blocco(next(fila)):
                        diversi.append(1)

                controllo = formato.controlla(
                    altro, self._chiave, numero=bytes.fromhex(candidato),
                    testa=testa, impronte=impronte, ogni_pezzo=confronta)
                finiti = next(fila, None) is None
        except (ErroreOfficina, OSError, StopIteration):
            return False
        return controllo.buono and finiti and not diversi

    def _blob_sano(self, blob: Path, numero: bytes, scritto: formato.Scritto) -> bool:
        try:
            with self._apri(blob, True) as copia:
                return formato.controlla(
                    copia, self._chiave, numero=numero, testa=scritto.testa,
                    impronte={"blake2b": scritto.blake2b,
                              "sha256": scritto.sha256}).buono
        except (ErroreOfficina, OSError):
            return False

    def _passata(self, percorso: str, numero: bytes, provvisorio: Path,
                 fatti_meta: list[dict], segno_prima, segno_ora) -> _Passata:
        try:
            lettore = self._apri(percorso, False)
        except FileNotFoundError:
            return _Passata("sparito")
        except OSError as guasto:
            return _Passata("bloccato" if isinstance(guasto, PermissionError)
                            or _bloccato(guasto) else "illeggibile")
        try:
            dimensione = lettore.dimensione
            with open(provvisorio, "wb") as fuori:
                scrittore = formato.Scrittore(
                    fuori, self._chiave, dimensione,
                    {"fatti": fatti_meta, "scritto": self._adesso()}, numero)
                buchi = self._leggi_tutto(lettore, scrittore)
                scritto = scrittore.finisci()
                fuori.flush()
                os.fsync(fuori.fileno())
        except formato.FileCambiato:
            provvisorio.unlink(missing_ok=True)
            return _Passata("cambiato")
        except _Bloccato:
            provvisorio.unlink(missing_ok=True)
            return _Passata("bloccato")
        except BaseException:
            provvisorio.unlink(missing_ok=True)
            raise
        finally:
            lettore.close()
        if buchi and len(buchi) >= -(-dimensione // self._settore):
            provvisorio.unlink(missing_ok=True)
            return _Passata("illeggibile")
        cambiato = _Passata("cambiato", scritto, buchi, tenuta=not buchi)
        try:
            if segno_ora() != segno_prima:
                return cambiato
        except FileNotFoundError:
            return _Passata("sparito")
        except OSError:
            return cambiato
        impronte = {"blake2b": scritto.blake2b, "sha256": scritto.sha256}
        if not buchi:
            for candidato, testa in self._candidati(scritto):
                esito = self._confronta(
                    percorso, dimensione,
                    registro.percorso_contenuto(self.cartella, candidato),
                    bytes.fromhex(candidato), testa, impronte, ())
                if esito == "cambiato":
                    return cambiato
                if esito == "uguale":
                    if self._ancora_lui(segno_ora, segno_prima):
                        provvisorio.unlink(missing_ok=True)
                        return _Passata("doppione", scritto, doppione=candidato)
                    return cambiato
        esito = self._confronta(percorso, dimensione, provvisorio, numero,
                                scritto.testa, impronte, buchi)
        if esito == "sbagliata":
            provvisorio.unlink(missing_ok=True)
            return _Passata("sbagliato")
        if esito == "cambiato" or not self._ancora_lui(segno_ora, segno_prima):
            return cambiato
        if buchi:
            return _Passata("buchi", scritto, buchi, tenuta=True)
        return _Passata("fatto", scritto)

    @staticmethod
    def _ancora_lui(segno_ora, segno_prima) -> bool:
        try:
            return segno_ora() == segno_prima
        except OSError:
            return False

    def _candidati(self, scritto: formato.Scritto, stati=STATI_BUONI):
        trovati = 0
        for numero in self.elenco.uguali(scritto.dimensione, scritto.blake2b,
                                         scritto.sha256):
            informazioni = self.elenco.contenuto(numero)
            if informazioni is None or informazioni["stato"] not in stati:
                continue
            yield numero, informazioni["testa"]
            trovati += 1
            if trovati >= CANDIDATI:
                return

    def _confronta(self, percorso: str, dimensione: int, blob: Path,
                   numero: bytes, testa: bytes, impronte: dict,
                   buchi) -> str:
        try:
            originale = self._apri(percorso, True)
        except OSError:
            return "cambiato"
        with originale:
            if originale.dimensione != dimensione:
                return "cambiato"
            try:
                copia = self._apri(blob, True)
            except OSError:
                return "sbagliata"
            with copia:
                confronto = _Confronto(self, originale)
                try:
                    controllo = formato.controlla(
                        copia, self._chiave, numero=numero, testa=testa,
                        impronte=impronte, ogni_pezzo=confronto)
                except _Bloccato:
                    return "cambiato"
                except ErroreOfficina:
                    return "sbagliata"
        if not controllo.buono:
            return "sbagliata"
        if (confronto.diverso or confronto.dove != dimensione
                or confronto.buchi != set(buchi)
                or confronto.impronte() != impronte):
            return "cambiato"
        return "uguale"

    def _leggi_tutto(self, lettore, scrittore: formato.Scrittore) -> tuple[int, ...]:
        buchi: set[int] = set()
        dove = 0
        while dove < lettore.dimensione:
            self._ferma_se_serve()
            dati, nuovi = self._leggi_pezzo(
                lettore, dove, min(PEZZO_DI_LETTURA, lettore.dimensione - dove))
            buchi.update(nuovi)
            if not dati:
                break
            scrittore.write(dati)
            dove += len(dati)
            self.avanzamento.letti += len(dati)
        return tuple(sorted(buchi))

    def _leggi_pezzo(self, lettore, dove: int, quanti: int) -> tuple[bytes, list[int]]:
        try:
            lettore.seek(dove)
            return lettore.read(quanti), []
        except OSError as guasto:
            if _bloccato(guasto):
                raise _Bloccato from guasto
        return self._salva(lettore, dove, quanti)

    def _salva(self, lettore, dove: int, quanti: int) -> tuple[bytes, list[int]]:
        pezzi: list[bytes] = []
        buchi: list[int] = []
        fine = min(dove + quanti, lettore.dimensione)
        inizio = dove
        while inizio < fine:
            passo = min(self._settore - inizio % self._settore, fine - inizio)
            for _ in range(LETTURE_PER_SETTORE):
                try:
                    dati = lettore.pezzo(inizio, passo)
                    break
                except OSError as guasto:
                    if _bloccato(guasto):
                        raise _Bloccato from guasto
            else:
                dati = bytes(passo)
                buchi.append(inizio // self._settore * self._settore)
            pezzi.append(dati)
            if len(dati) < passo:
                break
            inizio += passo
        return b"".join(pezzi), buchi

    def _registra(self, fatti: list[dict]) -> None:
        self.elenco.registra(fatti)
        self._per_nota += [fatto for fatto in fatti if fatto["fatto"] != "contenuto"]
        if (len(self._per_nota) >= FATTI_PER_NOTA
                or time.monotonic() - self._ultima_nota >= SECONDI_PER_NOTA):
            self._scrivi_nota()

    def _scrivi_nota(self) -> None:
        fatti, self._per_nota = self._per_nota, []
        try:
            if fatti:
                self.elenco.scrivi_nota(fatti)
        except BaseException:
            self._per_nota = fatti + self._per_nota
            raise
        self._ultima_nota = time.monotonic()

    def _sembra_uguale(self, attuale: registro.Posto, stato) -> bool:
        if (attuale.tipo != metadati.FILE or attuale.contenuto is None
                or SEGNI_DA_RIFARE & set(attuale.segni)):
            return False
        informazioni = self.elenco.contenuto(attuale.contenuto)
        if (informazioni is None or informazioni["stato"] not in STATI_BUONI
                or informazioni["dimensione"] != stato.st_size):
            return False
        date = metadati.date_di(stato)
        return all(attuale.metadati.get(chiave) == date.get(chiave)
                   for chiave in ("modifica", "creazione"))

    def riepiloga(self, radici: list[dict] | None = None,
                  velocita: float = VELOCITA) -> Riepilogo:
        if radici is None:
            radici = [radice for radice in self.elenco.radici() if not radice["tolta"]]
        riepilogo = Riepilogo()
        grandezze: Counter[int] = Counter()
        peso = 0
        for radice in radici:
            parte = {"file": 0, "byte": 0, "byte_da_copiare": 0}
            riepilogo.radici[radice["id"]] = parte
            giro = Giro(radice["id"], 0.0)
            if not self._radice_c_e(radice["percorso"]):
                riepilogo.problemi.append(("radice_mancante", radice["id"]))
                continue
            for relativo, stato in self.cammina(radice["percorso"], giro, set()):
                tipo = metadati.tipo_di(stato)
                if tipo == metadati.CARTELLA:
                    riepilogo.cartelle += 1
                    continue
                if tipo != metadati.FILE:
                    continue
                riepilogo.file += 1
                riepilogo.byte += stato.st_size
                parte["file"] += 1
                parte["byte"] += stato.st_size
                attuale = self.elenco.attuale(radice["id"], relativo)
                if attuale is not None and self._sembra_uguale(attuale, stato):
                    continue
                if metadati.solo_nel_cloud(stato):
                    riepilogo.nel_cloud += 1
                    continue
                riepilogo.da_copiare += 1
                riepilogo.byte_da_copiare += stato.st_size
                parte["byte_da_copiare"] += stato.st_size
                grandezze[stato.st_size] += 1
                peso += formato.peso_previsto(stato.st_size)
            riepilogo.problemi += giro.problemi
        esistenti = self.elenco.dimensioni()
        riepilogo.forse_doppioni = sum(
            quanti if grandezza in esistenti else quanti - 1
            for grandezza, quanti in grandezze.items())
        riepilogo.spazio_serve = int(peso * SPAZIO_IN_PIU)
        riepilogo.spazio_libero = spazio_libero(self.cartella)
        riepilogo.secondi = 2 * riepilogo.byte_da_copiare / velocita
        return riepilogo


def cartella_esistente(cartella: Path) -> Path:
    dove = Path(cartella)
    while not dove.exists() and dove != dove.parent:
        dove = dove.parent
    return dove


def spazio_libero(cartella: Path) -> int:
    return shutil.disk_usage(cartella_esistente(cartella)).free
