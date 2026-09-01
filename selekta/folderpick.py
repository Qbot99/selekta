"""Natywne okno wyboru folderu/pliku (macOS).

Przeglądarka z zasady nie zdradza, gdzie na dysku leży wybrany plik —
dostajemy samą zawartość. Dla folderu z muzyką to bez sensu: nie chcemy
przesyłać gigabajtów, chcemy ŚCIEŻKĘ, żeby analizować i naprawiać pliki
w miejscu. Selekta działa lokalnie, więc może po prostu poprosić system
o pokazanie zwykłego okna Findera.
"""
from __future__ import annotations

import subprocess
import sys

TIMEOUT_S = 180          # tyle czasu ma użytkownik na wybór


class PickCancelled(Exception):
    """Użytkownik zamknął okno bez wyboru."""


class PickUnavailable(Exception):
    """Na tym systemie nie ma jak pokazać natywnego okna."""


def available() -> bool:
    return sys.platform == "darwin"


def _run(script: str) -> str:
    if not available():
        raise PickUnavailable("natywne okno wyboru działa na razie tylko na macOS")
    try:
        res = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise PickCancelled("okno wyboru było otwarte za długo")
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode != 0 or not out:
        if "User canceled" in err or "-128" in err:
            raise PickCancelled("nie wybrano folderu")
        raise PickUnavailable(err or "nie udało się otworzyć okna wyboru")
    return out


def choose_folder(prompt: str = "Wskaż folder z muzyką") -> str:
    """Ścieżka folderu wybranego przez użytkownika."""
    safe = prompt.replace('"', "'")
    return _run(
        'tell application "System Events" to activate\n'
        f'set f to choose folder with prompt "{safe}"\n'
        "return POSIX path of f"
    )


def choose_file(prompt: str = "Wskaż plik playlisty") -> str:
    """Ścieżka pliku wybranego przez użytkownika."""
    safe = prompt.replace('"', "'")
    return _run(
        'tell application "System Events" to activate\n'
        f'set f to choose file with prompt "{safe}"\n'
        "return POSIX path of f"
    )
