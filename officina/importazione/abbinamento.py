from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

DURATA_MASSIMA_LIVE_MS = 4500

TOLLERANZA_SECONDI = 4


@dataclass(frozen=True)
class Candidato:

    id: int
    nome: str
    istante_utc: str | None
    data_locale: str | None
    identificatore_ios: str | None
    durata_ms: int | None = None
    cartella: str | None = None

    @property
    def radice(self) -> str:
        nome = self.nome.rsplit(".", 1)[0].strip().casefold()
        if nome.endswith(")") and "(" in nome:
            prima = nome[:nome.rfind("(")].strip()
            if prima:
                nome = prima
        return nome

    @property
    def momento(self) -> datetime | None:
        return _leggi(self.istante_utc) or _leggi(self.data_locale)

    @property
    def momento_utc(self) -> datetime | None:
        return _leggi(self.istante_utc)

    @property
    def momento_locale(self) -> datetime | None:
        return _leggi(self.data_locale)


def _leggi(testo: str | None) -> datetime | None:
    if not testo:
        return None
    try:
        return datetime.strptime(testo.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _vicini(uno: datetime | None, altro: datetime | None) -> bool | None:
    if uno is None or altro is None:
        return None
    return abs((uno - altro).total_seconds()) <= TOLLERANZA_SECONDI


@dataclass(frozen=True)
class Indizi:
    nome: bool
    istante: bool
    identificatore: bool
    stessa_cartella: bool = False

    @property
    def quanti(self) -> int:
        return int(self.nome) + int(self.istante) + int(self.identificatore)

    @property
    def certo(self) -> bool:
        return self.quanti >= 2 or (self.nome and self.stessa_cartella)

    def a_parole(self) -> str:
        detti = []
        if self.identificatore:
            detti.append("lo stesso identificatore interno")
        if self.nome:
            detti.append("lo stesso nome nella stessa cartella" if self.stessa_cartella
                         else "lo stesso nome")
        if self.istante:
            detti.append("lo stesso istante di scatto")
        if not detti:
            return "nessun indizio in comune"
        return " e ".join([", ".join(detti[:-1]), detti[-1]] if len(detti) > 1 else detti)


def confronta(video: Candidato, foto: Candidato) -> Indizi:
    stesso_identificatore = bool(
        video.identificatore_ios
        and foto.identificatore_ios
        and video.identificatore_ios == foto.identificatore_ios
    )

    stesso_istante = _vicini(video.momento_utc, foto.momento_utc)
    if stesso_istante is None:
        stesso_istante = _vicini(video.momento_locale, foto.momento_locale)
    if stesso_istante is None:
        stesso_istante = bool(_vicini(video.momento, foto.momento))

    return Indizi(
        nome=video.radice == foto.radice and bool(video.radice),
        istante=stesso_istante,
        identificatore=stesso_identificatore,
        stessa_cartella=bool(video.cartella and foto.cartella
                             and video.cartella.casefold() == foto.cartella.casefold()),
    )


@dataclass(frozen=True)
class Esito:
    foto: Candidato | None
    indizi: Indizi | None

    @property
    def e_live(self) -> bool:
        return self.foto is not None and self.indizi is not None and self.indizi.certo

    @property
    def da_chiedere(self) -> bool:
        return self.foto is not None and self.indizi is not None and self.indizi.quanti == 1


def cerca_gemella(video: Candidato, candidate: list[Candidato]) -> Esito:
    if video.durata_ms is not None and video.durata_ms > DURATA_MASSIMA_LIVE_MS:
        return Esito(None, None)

    migliore: Candidato | None = None
    migliori_indizi: Indizi | None = None

    for foto in candidate:
        indizi = confronta(video, foto)
        if indizi.quanti == 0:
            continue
        if migliori_indizi is None or (indizi.certo, indizi.quanti) > (
                migliori_indizi.certo, migliori_indizi.quanti):
            migliore, migliori_indizi = foto, indizi

    if migliore is None:
        return Esito(None, None)
    return Esito(migliore, migliori_indizi)


def genere_dello_scatto(durata_ms: int | None, ha_gemella: bool,
                        e_un_video: bool | None = None) -> str:
    if e_un_video is None:
        e_un_video = durata_ms is not None
    if not e_un_video:
        return "foto"
    if ha_gemella and (durata_ms is None or durata_ms <= DURATA_MASSIMA_LIVE_MS):
        return "live"
    return "video"
