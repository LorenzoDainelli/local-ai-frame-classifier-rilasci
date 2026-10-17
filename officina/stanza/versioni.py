from __future__ import annotations

from dataclasses import dataclass, field

CUBO = 0.04
SCARTO_MINIMO = 0.06
SCARTO_IN_PROPORZIONE = 0.05
VICINO_MINIMO = 0.1
QUOTA_DI_VUOTI = 0.25
VICINI_MINIMI = 3
VISTI_INSIEME_MINIMI = 15
ACCORDO_MINIMO = 0.75
CUBI_PROPRI_MINIMI = 25
VERSIONI_MASSIME = 8
SPOSTA = 1 << 20
BIT = 21


def chiavi(punti, lato: float = CUBO):
    import numpy as np

    interi = np.floor(np.asarray(punti, dtype=np.float64) / lato).astype(np.int64) + SPOSTA
    return (interi[:, 0] << (2 * BIT)) | (interi[:, 1] << BIT) | interi[:, 2]


def centri(chiavi_dei_cubi, lato: float = CUBO):
    import numpy as np

    maschera = (1 << BIT) - 1
    x = (chiavi_dei_cubi >> (2 * BIT)) & maschera
    y = (chiavi_dei_cubi >> BIT) & maschera
    z = chiavi_dei_cubi & maschera
    return (np.stack([x, y, z], axis=1).astype(np.float64) - SPOSTA + 0.5) * lato


@dataclass
class Vista:
    profondita: object
    matrice: object
    estrinseci: object
    buoni: object
    quando: str | None = None


@dataclass
class Esito:
    gruppo_della_foto: list[int]
    cambiano: object
    versioni: list[dict] = field(default_factory=list)

    @property
    def ci_sono(self) -> bool:
        return len(self.versioni) > 1


def _stati(cubi, viste: list[Vista], sistemazione, occupati: list):
    import numpy as np

    punti = centri(cubi)
    nella_corsa = ((punti - sistemazione.spostamento) @ sistemazione.rotazione) / sistemazione.metri
    stati = np.zeros((len(viste), len(cubi)), dtype=np.int8)
    for numero, vista in enumerate(viste):
        estrinseci = np.asarray(vista.estrinseci, dtype=np.float64)
        camera = nella_corsa @ estrinseci[:3, :3].T + estrinseci[:3, 3]
        z = camera[:, 2] * sistemazione.metri
        matrice = np.asarray(vista.matrice, dtype=np.float64)
        profondita = np.asarray(vista.profondita, dtype=np.float64)
        alta, larga = profondita.shape
        davanti = camera[:, 2] > 1e-6
        u = np.full(len(cubi), -1, dtype=np.int64)
        v = np.full(len(cubi), -1, dtype=np.int64)
        u[davanti] = np.floor(matrice[0, 0] * camera[davanti, 0] / camera[davanti, 2] + matrice[0, 2]).astype(np.int64)
        v[davanti] = np.floor(matrice[1, 1] * camera[davanti, 1] / camera[davanti, 2] + matrice[1, 2]).astype(np.int64)
        dentro = davanti & (z > VICINO_MINIMO) & (u >= 0) & (u < larga) & (v >= 0) & (v < alta)
        indici = np.nonzero(dentro)[0]
        if len(indici):
            d = profondita[v[indici], u[indici]] * sistemazione.metri
            valida = np.asarray(vista.buoni)[v[indici], u[indici]] & np.isfinite(d) & (d > 0)
            scarto = np.maximum(SCARTO_MINIMO, SCARTO_IN_PROPORZIONE * z[indici])
            pieno = valida & (np.abs(z[indici] - d) <= scarto)
            vuoto = valida & (d > z[indici] + scarto)
            stati[numero, indici[pieno]] = 1
            stati[numero, indici[vuoto]] = -1
        stati[numero, np.isin(cubi, occupati[numero])] = 1
    return stati


def _con_vicini(cubi, scelti):
    import numpy as np

    if not len(scelti):
        return scelti
    insieme = np.sort(scelti)
    conti = np.zeros(len(scelti), dtype=np.int32)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == dy == dz == 0:
                    continue
                spostati = scelti + (dx << (2 * BIT)) + (dy << BIT) + dz
                posto = np.searchsorted(insieme, spostati)
                posto = np.minimum(posto, len(insieme) - 1)
                conti += insieme[posto] == spostati
    return scelti[conti >= VICINI_MINIMI]


def _accordo(firma, somma) -> tuple[float, int]:
    import numpy as np

    insieme = (firma != 0) & (somma != 0)
    quanti = int(insieme.sum())
    if not quanti:
        return 0.0, 0
    return float(np.mean(np.sign(somma[insieme]) == firma[insieme])), quanti


def _raggruppa(firme, ordine: list[int]) -> list[int]:
    import numpy as np

    gruppi: list[list[int]] = []
    somme: list = []
    di_chi = [-1] * len(firme)
    for numero in ordine:
        migliore, accordo_migliore = -1, -1.0
        for indice, somma in enumerate(somme):
            accordo, insieme = _accordo(firme[numero], somma)
            if insieme >= VISTI_INSIEME_MINIMI and accordo > accordo_migliore:
                migliore, accordo_migliore = indice, accordo
        if migliore >= 0 and accordo_migliore >= ACCORDO_MINIMO:
            gruppi[migliore].append(numero)
            somme[migliore] = somme[migliore] + firme[numero]
            di_chi[numero] = migliore
        elif not np.count_nonzero(firme[numero]):
            continue
        else:
            gruppi.append([numero])
            somme.append(firme[numero].astype(np.int32))
            di_chi[numero] = len(gruppi) - 1
    if not gruppi:
        return [0] * len(firme)
    piu_grande = max(range(len(gruppi)), key=lambda i: len(gruppi[i]))
    return [piu_grande if g < 0 else g for g in di_chi]


def _unisci_i_piccoli(di_chi: list[int], stati_cambiano):
    import numpy as np

    while True:
        nomi = sorted(set(di_chi))
        if len(nomi) <= 1:
            return di_chi
        somme = {g: stati_cambiano[[i for i, x in enumerate(di_chi) if x == g]].sum(axis=0) for g in nomi}
        propri = {}
        for g in nomi:
            altri_vuoti = np.zeros(stati_cambiano.shape[1], dtype=bool)
            altri_pieni = np.zeros(stati_cambiano.shape[1], dtype=bool)
            for h in nomi:
                if h != g:
                    altri_vuoti |= somme[h] < 0
                    altri_pieni |= somme[h] > 0
            propri[g] = int((((somme[g] > 0) & altri_vuoti) | ((somme[g] < 0) & altri_pieni)).sum())
        conti = {g: di_chi.count(g) for g in nomi}
        debole = min(nomi, key=lambda g: (propri[g], conti[g]))
        if propri[debole] >= CUBI_PROPRI_MINIMI and len(nomi) <= VERSIONI_MASSIME:
            return di_chi
        verso = max((g for g in nomi if g != debole),
                    key=lambda g: (_accordo(np.sign(somme[debole]).astype(np.int8), somme[g])[0], conti[g]))
        di_chi = [verso if x == debole else x for x in di_chi]


def trova(nuvole: list, viste: list[Vista], sistemazione) -> Esito:
    import numpy as np

    quante = len(viste)
    occupati = [np.unique(chiavi(p)) if len(p) else np.zeros(0, dtype=np.int64) for p in nuvole]
    if quante < 2 or not any(len(o) for o in occupati):
        return Esito([0] * quante, np.zeros(0, dtype=np.int64))
    cubi = np.unique(np.concatenate(occupati))
    stati = _stati(cubi, viste, sistemazione, occupati)
    pieni = (stati > 0).sum(axis=0)
    vuoti = (stati < 0).sum(axis=0)
    dubbi = (pieni >= 1) & (vuoti >= 1) & (vuoti >= QUOTA_DI_VUOTI * (pieni + vuoti))
    cambiano = _con_vicini(cubi, cubi[dubbi])
    if not len(cambiano):
        return Esito([0] * quante, cambiano)
    colonne = np.isin(cubi, cambiano)
    firme = [stati[i, colonne] for i in range(quante)]
    ordine = sorted(range(quante), key=lambda i: (viste[i].quando or "9999", i))
    di_chi = _unisci_i_piccoli(_raggruppa(firme, ordine), stati[:, colonne])
    nomi = sorted(set(di_chi), key=lambda g: min((viste[i].quando or "9999", i) for i, x in enumerate(di_chi) if x == g))
    if len(nomi) <= 1:
        return Esito([0] * quante, np.zeros(0, dtype=np.int64))
    numero_di = {g: n + 1 for n, g in enumerate(nomi)}
    gruppo_della_foto = [numero_di[g] for g in di_chi]
    somme = {numero_di[g]: stati[[i for i, x in enumerate(di_chi) if x == g]][:, colonne].sum(axis=0) for g in nomi}
    davvero = np.zeros(int(colonne.sum()), dtype=bool)
    for a in somme.values():
        for b in somme.values():
            davvero |= (a > 0) & (b < 0)
    cambiano = cubi[colonne][davvero]
    versioni = []
    for numero in range(1, len(nomi) + 1):
        dentro = [i for i, g in enumerate(gruppo_della_foto) if g == numero]
        date = sorted(viste[i].quando[:10] for i in dentro if viste[i].quando)
        versioni.append({"numero": numero, "foto": dentro, "dal": date[0] if date else None,
                         "al": date[-1] if date else None})
    return Esito(gruppo_della_foto, cambiano, versioni)


def gruppi_dei_punti(punti, gruppo: int, esito: Esito):
    import numpy as np

    if not esito.ci_sono or not len(punti) or gruppo <= 0:
        return np.zeros(len(punti), dtype=np.uint8)
    dentro = np.isin(chiavi(punti), esito.cambiano)
    return np.where(dentro, gruppo, 0).astype(np.uint8)
