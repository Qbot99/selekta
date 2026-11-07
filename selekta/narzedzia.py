"""Gdzie są ffmpeg i ffprobe.

W wersji do pobrania (pakiet .app) ffmpeg jedzie w środku — użytkownik nie
ma instalować Homebrew. Kolejność: kopia obok pakietu (``SELEKTA_FFMPEG_DIR``
albo katalog zasobów PyInstallera), potem PATH. Każde miejsce w kodzie,
które woła ffmpeg, ma brać ścieżkę stąd, nie z gołej nazwy.
"""
from __future__ import annotations

import os
import shutil
import sys


def _katalog_pakietu() -> str | None:
    d = os.environ.get("SELEKTA_FFMPEG_DIR")
    if d:
        return d
    # PyInstaller rozpakowuje zasoby do sys._MEIPASS (onefile) albo obok
    # binarki (onedir / .app: Contents/MacOS)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return None


def _znajdz(nazwa: str) -> str:
    from .system import exe
    nazwa = exe(nazwa)                       # na Windows ffmpeg.exe
    d = _katalog_pakietu()
    if d:
        # PyInstaller 6 w pakiecie .app kładzie binarki w Contents/Frameworks
        # (Contents/MacOS ma tylko plik wykonywalny apki)
        for kandydat in (os.path.join(d, nazwa), os.path.join(d, "bin", nazwa),
                         os.path.join(d, "..", "Frameworks", nazwa),
                         os.path.join(d, "..", "Resources", nazwa)):
            if os.path.isfile(kandydat) and os.access(kandydat, os.X_OK):
                return os.path.normpath(kandydat)
    return shutil.which(nazwa) or nazwa


def ffmpeg_path() -> str:
    return _znajdz("ffmpeg")


def ffprobe_path() -> str:
    return _znajdz("ffprobe")
