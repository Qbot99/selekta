"""Natywne okno wyboru folderu/pliku (macOS: Finder, Windows: okno systemowe).

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
    return sys.platform in ("darwin", "win32")


def _run_windows(skrypt: str) -> str:
    """Okno Windows Forms przez PowerShell; ścieżka na stdout (UTF-8)."""
    pelny = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
             "Add-Type -AssemblyName System.Windows.Forms; " + skrypt)
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", pelny],
                             capture_output=True, timeout=TIMEOUT_S,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise PickCancelled("okno wyboru było otwarte za długo")
    except OSError as exc:
        raise PickUnavailable(f"nie udało się otworzyć okna wyboru: {exc}")
    out = res.stdout.decode("utf-8", "replace").strip()
    if res.returncode != 0:
        raise PickUnavailable(res.stderr.decode("utf-8", "replace").strip()
                              or "nie udało się otworzyć okna wyboru")
    if not out:
        raise PickCancelled("nie wybrano")
    return out


def _ps(tekst: str) -> str:
    return tekst.replace("'", "''")


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
    if sys.platform == "win32":
        return _run_windows(
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$d.Description = '{_ps(prompt)}'; $d.ShowNewFolderButton = $false; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
    safe = prompt.replace('"', "'")
    return _run(
        'tell application "System Events" to activate\n'
        f'set f to choose folder with prompt "{safe}"\n'
        "return POSIX path of f"
    )


def choose_file(prompt: str = "Wskaż plik playlisty") -> str:
    """Ścieżka pliku wybranego przez użytkownika."""
    if sys.platform == "win32":
        return _run_windows(
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            f"$d.Title = '{_ps(prompt)}'; "
            "if ($d.ShowDialog() -eq 'OK') { $d.FileName }")
    safe = prompt.replace('"', "'")
    return _run(
        'tell application "System Events" to activate\n'
        f'set f to choose file with prompt "{safe}"\n'
        "return POSIX path of f"
    )
