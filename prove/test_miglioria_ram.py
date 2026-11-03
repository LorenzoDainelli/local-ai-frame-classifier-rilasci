from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace

from officina.miglioria import ram


def _senza_psutil(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)


def test_con_psutil_la_dice_lui(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=5.0 * 2 ** 30)))
    quanta = ram.libera()
    assert quanta == 5 * 2 ** 30 and type(quanta) is int


def test_su_linux_la_legge_da_meminfo(monkeypatch, tmp_path):
    _senza_psutil(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       32000000 kB\nMemFree:  100 kB\n"
                       "MemAvailable:   20000000 kB\n", encoding="ascii")
    monkeypatch.setattr(ram, "MEMINFO", meminfo)
    assert ram.libera() == 20000000 * 1024


def test_su_linux_senza_la_riga_giusta_non_si_sa(monkeypatch, tmp_path):
    _senza_psutil(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    meminfo = tmp_path / "meminfo"
    monkeypatch.setattr(ram, "MEMINFO", meminfo)
    assert ram.libera() is None
    meminfo.write_text("MemFree: 100 kB\nMemAvailable: tanti kB\nMemAvailable:\n",
                       encoding="ascii")
    assert ram.libera() is None
    meminfo.write_bytes(b"\xff\xfe")
    assert ram.libera() is None


def test_su_un_altro_sistema_la_legge_come_su_linux(monkeypatch, tmp_path):
    _senza_psutil(monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 3 kB\n", encoding="ascii")
    monkeypatch.setattr(ram, "MEMINFO", meminfo)
    assert ram.libera() == 3 * 1024


def _windows(monkeypatch, riesce: bool, libera: int) -> list:
    chiamate = []

    def stato(puntatore):
        chiamate.append(puntatore.contents.dwLength)
        puntatore.contents.ullAvailPhys = libera
        return 1 if riesce else 0

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
        kernel32=SimpleNamespace(GlobalMemoryStatusEx=stato)), raising=False)
    return chiamate


def test_su_windows_la_chiede_al_sistema(monkeypatch):
    _senza_psutil(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    chiamate = _windows(monkeypatch, True, 9 * 2 ** 30)
    assert ram.libera() == 9 * 2 ** 30
    assert chiamate == [ctypes.sizeof(ram._StatoDellaMemoria)] == [64]


def test_su_windows_se_il_sistema_non_risponde_non_si_sa(monkeypatch):
    _senza_psutil(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    _windows(monkeypatch, False, 9 * 2 ** 30)
    assert ram.libera() is None
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert ram.libera() is None
