from __future__ import annotations

from pathlib import Path

from officina.corpi.rilevatore import (ALTEZZA_MINIMA, CARTELLA_SAM3, FILE_POSE,
                                       SICUREZZA_MINIMA, VERSIONE, Corpo,
                                       cosa_manca, dove_stanno)
from officina.errori import ErroreOfficina

MEMORIA_PER_TUTTI = 12_000_000_000
RAM_PER_TUTTI = 24_000_000_000
INSIEME_A_TURNO = 32
QUADRI_A_TURNO = 96


class MancanoIModelli(ErroreOfficina):
    codice = "mancano_modelli_corpi"


class Interrotta(Exception):
    pass


class NonSiAccende(Exception):
    pass


def nome_dell_aspetto(versione: str) -> str:
    return f"kpr-{versione}"


VESTITI = "vestiti-siglip2"
SEPARATORE = object()


def c_e_posto_per_tutti(macchina=None) -> bool:
    from officina.descrittori import torcia

    macchina = macchina or torcia.macchina()
    if macchina.dispositivo == "cuda":
        return macchina.memoria_byte >= MEMORIA_PER_TUTTI
    try:
        import psutil
    except ImportError:
        return False
    return psutil.virtual_memory().total >= RAM_PER_TUTTI


class Rilevatore:

    def __init__(self, cartella_modelli: Path, sicurezza_minima: float = SICUREZZA_MINIMA,
                 tutti_accesi: bool | None = None):
        from officina.corpi import kpr, kpr_pesi
        from officina.corpi.rtmw import Pose
        from officina.corpi.sam3 import Separatore
        from officina.descrittori.grandi import Siglip2

        self.cartella_modelli = Path(cartella_modelli)
        casa = dove_stanno(cartella_modelli)
        self.separatore = Separatore(casa / CARTELLA_SAM3, sicurezza_minima)
        self.pose = Pose(casa / FILE_POSE)
        self.aspetti = [kpr.Riconoscitore(kpr_pesi.dove_stanno(cartella_modelli), versione)
                        for versione in kpr.VERSIONI]
        self.vestiti = Siglip2(self.cartella_modelli)
        self._tutti_accesi = tutti_accesi

    @property
    def versione(self) -> str:
        return VERSIONE

    @property
    def tutti_accesi(self) -> bool:
        if self._tutti_accesi is None:
            self._tutti_accesi = c_e_posto_per_tutti()
        return self._tutti_accesi

    @property
    def quanti_insieme(self) -> int:
        return 1 if self.tutti_accesi else INSIEME_A_TURNO

    @property
    def quadri_insieme(self) -> int:
        return 0 if self.tutti_accesi else QUADRI_A_TURNO

    def _turni(self) -> list[object]:
        return [SEPARATORE, *self.aspetti, self.vestiti]

    def accendi(self) -> None:
        manca = cosa_manca(self.cartella_modelli)
        if manca:
            raise MancanoIModelli(manca)
        if self.tutti_accesi:
            for turno in self._turni():
                self._accendi_uno(turno)
        else:
            self._accendi_uno(SEPARATORE)

    def spegni(self) -> None:
        self.separatore.spegni()
        self.pose.spegni()
        for riconoscitore in self.aspetti:
            riconoscitore.spegni()
        self.vestiti.chiudi()

    def _accendi_uno(self, turno) -> None:
        if turno is SEPARATORE:
            self.separatore.accendi()
            self.pose.accendi()
        elif turno is self.vestiti:
            self.vestiti.apri()
        else:
            turno.accendi()

    def _spegni_uno(self, turno) -> None:
        if turno is SEPARATORE:
            self.separatore.spegni()
        elif turno is self.vestiti:
            self.vestiti.chiudi()
        else:
            turno.spegni()

    def _solo(self, turno) -> None:
        if not self.tutti_accesi:
            for altro in self._turni():
                if altro is not turno:
                    self._spegni_uno(altro)
        try:
            self._accendi_uno(turno)
        except ErroreOfficina:
            raise
        except Exception as guasto:
            raise NonSiAccende(str(guasto)) from guasto

    def guarda(self, immagine, intera=None) -> list[Corpo]:
        corpi, preparati = self.trova_e_prepara(immagine, intera)
        guasto = self.completa([(corpi, preparati)])[0]
        if guasto is not None:
            raise guasto
        return corpi

    def trova_e_prepara(self, immagine, intera=None):
        self._solo(SEPARATORE)
        corpi = self._trova(immagine)
        return corpi, self._prepara(intera if intera is not None else immagine, corpi)

    def completa(self, lotti, fermato=None) -> list[BaseException | None]:
        guasti: list[BaseException | None] = [None] * len(lotti)

        def controlla() -> None:
            if fermato is not None and fermato():
                raise Interrotta()

        def da_fare():
            for indice, (corpi, preparati) in enumerate(lotti):
                controlla()
                if corpi and guasti[indice] is None:
                    yield indice, corpi, preparati

        for riconoscitore in self.aspetti:
            self._solo(riconoscitore)
            nome = nome_dell_aspetto(riconoscitore.versione)
            for indice, corpi, (per_kpr, _sagome) in da_fare():
                try:
                    fatti = riconoscitore.guarda_preparati(per_kpr)
                    for corpo, (immersione, visibili) in zip(corpi, fatti, strict=True):
                        corpo.aspetto[nome] = (immersione, visibili)
                except Exception as guasto:
                    guasti[indice] = guasto

        self._solo(self.vestiti)
        for indice, corpi, (_per_kpr, sagome) in da_fare():
            try:
                quali = [i for i, sagoma in enumerate(sagome) if sagoma is not None]
                vettori = self.vestiti.descrivi([sagome[i] for i in quali]) if quali else []
                for i, vettore in zip(quali, vettori, strict=True):
                    corpi[i].vestiti = vettore
            except Exception as guasto:
                guasti[indice] = guasto
        return guasti

    def _trova(self, immagine) -> list[Corpo]:
        from officina.corpi import maschere

        intera = immagine.convert("RGB")
        larga, alta = intera.size
        tenuti = [(riquadro, sicurezza, maschera)
                  for riquadro, sicurezza, maschera in self.separatore.trova(intera)
                  if (riquadro[3] - riquadro[1]) / max(1, alta) >= ALTEZZA_MINIMA]
        punti = self.pose.punti(intera, [riquadro for riquadro, _, _ in tenuti])
        corpi = []
        for (riquadro, sicurezza, maschera), suoi in zip(tenuti, punti, strict=True):
            sinistra, sopra = max(0.0, riquadro[0]), max(0.0, riquadro[1])
            destra, sotto = min(float(larga), riquadro[2]), min(float(alta), riquadro[3])
            corpi.append(Corpo(
                riquadro=(sinistra / larga, sopra / alta,
                          max(0.0, destra - sinistra) / larga,
                          max(0.0, sotto - sopra) / alta),
                sicurezza=sicurezza,
                maschera=maschere.comprimi(maschere.ritaglia(
                    maschera, (sinistra, sopra, destra, sotto))),
                punti=suoi))
        return corpi

    def _prepara(self, immagine, corpi: list[Corpo]):
        from officina.corpi import kpr, vestiti

        intera = immagine.convert("RGB")
        larga, alta = intera.size
        persone = [((c.riquadro[0] * larga, c.riquadro[1] * alta,
                     (c.riquadro[0] + c.riquadro[2]) * larga,
                     (c.riquadro[1] + c.riquadro[3]) * alta), list(c.punti)) for c in corpi]
        lato = self.vestiti.scheda.lato
        sagome = [vestiti.sagoma(intera, c.riquadro, c.maschera, lato_finale=lato)
                  for c in corpi]
        return kpr.prepara(intera, persone), sagome


def apri(archivio, sicurezza_minima: float | None = None) -> Rilevatore:
    return Rilevatore(archivio.dove.modelli,
                      SICUREZZA_MINIMA if sicurezza_minima is None else sicurezza_minima)
