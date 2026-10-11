from __future__ import annotations

import os
import socket

INTERRUTTORI = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE",
                "DIFFUSERS_OFFLINE")


class RetePortaChiusa(OSError):
    pass


def _vietato(*_argomenti, **_nomi):
    raise RetePortaChiusa("la rete è chiusa nella stanza del miglioramento")


def chiudi() -> None:
    for interruttore in INTERRUTTORI:
        os.environ[interruttore] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    socket.socket.connect = _vietato
    socket.socket.connect_ex = _vietato
    socket.socket.sendto = _vietato
    socket.create_connection = _vietato
    socket.getaddrinfo = _vietato
