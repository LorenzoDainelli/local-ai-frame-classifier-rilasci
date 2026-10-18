from __future__ import annotations

import re
from pathlib import PurePosixPath


SEGNI_DI_COPIA = re.compile(
    r"(\s\(\d+\)$"
    r"|\s-\s(copia|copy)(\s\(\d+\))?$"
    r"|^(copia|copy)\s(di|of)\s"
    r"|[\s_-](copia|copy)(\s?\d+)?$)",
    re.IGNORECASE)

NOMI_DI_FOTOCAMERA = re.compile(
    r"^(IMG|VID|PXL|DSC|DSCN|DSCF|_DSC|_MG|MVI|MOV|GOPR|GH\d\d|GX\d\d|DJI|SAM"
    r"|WP|PANO|HPIM|CIMG|DSCI|SDC|KIF|IMAG|PICT|MAH|PIC|PHOTO|VIDEO|MAX|LRV"
    r"|Screenshot)[_\- ]?\d"
    r"|^P\d{7}$"
    r"|^C\d{4}$"
    r"|^\d{8}_\d{6}",
    re.IGNORECASE)


def _radice_del_nome(nome: str) -> str:
    return PurePosixPath(nome).stem


def nome_pulito(nome: str) -> bool:
    return not SEGNI_DI_COPIA.search(_radice_del_nome(nome))


def nome_di_fotocamera(nome: str) -> bool:
    return bool(NOMI_DI_FOTOCAMERA.search(_radice_del_nome(nome)))


def _modifica(posto) -> float | None:
    valore = (posto.metadati or {}).get("modifica")
    if type(valore) is int:
        return valore / 1e9
    if type(valore) is float:
        return valore
    return None


def scegli(posti: list, data_scatto: float | None = None):
    if not posti:
        return None
    date = {_modifica(posto) for posto in posti}

    def ordine(posto):
        nome = PurePosixPath(posto.percorso).name
        modifica = _modifica(posto)
        if len(date) < 2:
            data = 0.0
        elif modifica is None:
            data = float("inf")
        elif data_scatto is not None:
            data = abs(modifica - data_scatto)
        else:
            data = modifica
        return (not nome_pulito(nome), data, not nome_di_fotocamera(nome),
                nome.casefold(), nome, posto.percorso.casefold(),
                posto.percorso, posto.radice, posto.chiave)

    return min(posti, key=ordine)
