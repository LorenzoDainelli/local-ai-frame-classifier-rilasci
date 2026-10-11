from __future__ import annotations

import io
import pickle
import zipfile
from collections import OrderedDict
from pathlib import Path

TIPI = {
    "FloatStorage": "float32", "DoubleStorage": "float64", "HalfStorage": "float16",
    "BFloat16Storage": "bfloat16", "LongStorage": "int64", "IntStorage": "int32",
    "UInt32Storage": "uint32", "ShortStorage": "int16", "CharStorage": "int8",
    "ByteStorage": "uint8", "BoolStorage": "bool",
}


class FileNonValido(Exception):
    pass


class _Tipo:

    def __init__(self, nome: str):
        self.nome = nome


class Oggetto:

    def __init__(self, *argomenti, **chiavi):
        self.argomenti = argomenti
        self.stato: dict = {}

    def __setstate__(self, stato) -> None:
        self.stato = dict(stato) if isinstance(stato, dict) else {"valore": stato}

    def __getitem__(self, chiave):
        return self.stato[chiave]

    def __setitem__(self, chiave, valore):
        self.stato[chiave] = valore

    def append(self, valore):
        self.stato.setdefault("elenco", []).append(valore)

    def extend(self, valori):
        self.stato.setdefault("elenco", []).extend(valori)


def _uguale(valore, *_resto):
    return valore


def _lista(valore):
    return list(valore)


class _Lettore(pickle.Unpickler):

    def __init__(self, dati: bytes, archivio: zipfile.ZipFile, radice: str,
                 classi: dict[str, set[str]] | None):
        super().__init__(io.BytesIO(dati))
        self.archivio = archivio
        self.radice = radice
        self.classi = classi
        self.memorie: dict[str, object] = {}

    def find_class(self, modulo: str, nome: str):
        if modulo == "torch" and nome in TIPI:
            return _Tipo(nome)
        if modulo == "torch._utils" and nome == "_rebuild_tensor_v2":
            return self._tensore
        if modulo == "torch._utils" and nome == "_rebuild_parameter":
            return _uguale
        if modulo == "torch.jit._pickle" and nome == "restore_type_tag":
            return _uguale
        if modulo == "torch.jit._pickle" and nome in {"build_intlist", "build_doublelist",
                                                      "build_boollist", "build_tensorlist"}:
            return _lista
        if modulo == "collections" and nome == "OrderedDict":
            return OrderedDict
        if self.classi is None or nome in self.classi.get(modulo, set()):
            return type(nome, (Oggetto,), {})
        raise FileNonValido(f"il file chiede {modulo}.{nome}, che non è un numero")

    def persistent_load(self, identita):
        import torch

        if not (isinstance(identita, tuple) and len(identita) == 5 and identita[0] == "storage"):
            raise FileNonValido("pezzo di dati sconosciuto")
        _, tipo, chiave, _dove, quanti = identita
        if not isinstance(tipo, _Tipo):
            raise FileNonValido("tipo di dati sconosciuto")
        if chiave not in self.memorie:
            grezzi = bytearray(self.archivio.read(f"{self.radice}/data/{chiave}"))
            dtype = getattr(torch, TIPI[tipo.nome])
            piatto = torch.frombuffer(grezzi, dtype=dtype) if grezzi else torch.empty(0, dtype=dtype)
            if piatto.numel() != int(quanti):
                raise FileNonValido("pezzo di dati della misura sbagliata")
            self.memorie[chiave] = piatto.clone()
        return self.memorie[chiave]

    @staticmethod
    def _tensore(memoria, inizio, misura, passi, *_resto):
        return memoria.as_strided(tuple(misura), tuple(passi), int(inizio)).clone()


def leggi(percorso: Path, classi: dict[str, set[str]] | None = None):
    with zipfile.ZipFile(percorso) as archivio:
        nomi = archivio.namelist()
        dati = [n for n in nomi if n.endswith("/data.pkl") and n.count("/") == 1]
        if not dati:
            raise FileNonValido("manca data.pkl")
        radice = dati[0].split("/")[0]
        return _Lettore(archivio.read(dati[0]), archivio, radice, classi).load()


def pesi(percorso: Path) -> dict:
    import torch

    letto = leggi(percorso)
    if isinstance(letto, dict) and "state_dict" in letto:
        letto = letto["state_dict"]
    if not isinstance(letto, dict):
        raise FileNonValido("nel file non ci sono i pesi")
    return {k: v for k, v in letto.items() if isinstance(v, torch.Tensor)}
