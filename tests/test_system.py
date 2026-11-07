"""Różnice między systemami (selekta.system) — gałęzie Windows sprawdzane atrapami."""
from __future__ import annotations

import os
import subprocess

from selekta import skaner, system


def test_exe_tylko_na_windows(monkeypatch):
    monkeypatch.setattr(system, "WINDOWS", False)
    assert system.exe("ffmpeg") == "ffmpeg"
    monkeypatch.setattr(system, "WINDOWS", True)
    assert system.exe("ffmpeg") == "ffmpeg.exe" and system.exe("slskd.exe") == "slskd.exe"


def test_procesy_windows_z_powershella(monkeypatch):
    monkeypatch.setattr(system, "WINDOWS", True)
    wolane = []

    def run(cmd, **kw):
        wolane.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="4242|C:\\slskd\\slskd.exe\n\n", stderr="")
    monkeypatch.setattr(system.subprocess, "run", run)
    assert system.procesy("slskd") == [(4242, "C:\\slskd\\slskd.exe")]
    assert wolane[0][0] == "powershell" and "slskd" in wolane[0][-1]


def test_brak_narzedzia_to_nie_dziala(monkeypatch):
    def run(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(system.subprocess, "run", run)
    assert system.procesy("rekordbox") == [] and system.dziala("rekordbox") is False


def test_odlaczony_proces(monkeypatch):
    monkeypatch.setattr(system, "WINDOWS", False)
    assert system.odlaczony() == {"start_new_session": True}
    monkeypatch.setattr(system, "WINDOWS", True)
    assert "creationflags" in system.odlaczony()


def test_pokaz_w_eksploratorze(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "MAC", False)
    monkeypatch.setattr(system, "WINDOWS", True)
    wolane = []
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **kw: wolane.append(cmd))
    p = str(tmp_path / "a.mp3")
    assert system.pokaz_w_menedzerze(p) == (True, "")
    assert wolane == [["explorer", f"/select,{os.path.normpath(p)}"]]


def test_skaner_na_windows_dom_muzyka_publiczna_i_dyski(monkeypatch, tmp_path):
    dom = tmp_path / "Users" / "ja"
    dom.mkdir(parents=True)
    (tmp_path / "Users" / "Public" / "Music").mkdir(parents=True)
    monkeypatch.setattr(system, "WINDOWS", True)
    monkeypatch.setattr(system, "dyski_windows", lambda: ["D:\\", "E:\\"])
    assert skaner.korzenie(str(dom)) == [str(dom), str(tmp_path / "Users" / "Public" / "Music"),
                                         "D:\\", "E:\\"]


def test_skaner_pomija_appdata_i_katalogi_systemu_windows():
    dom = "/u/ja"
    assert skaner._pomin_katalog("AppData", dom, dom)
    for nazwa in ("$Recycle.Bin", "System Volume Information", "Program Files", "Windows"):
        assert skaner._pomin_katalog(nazwa, "D:\\", dom)
    assert not skaner._pomin_katalog("Muzyka", "D:\\", dom)
