"""Różnice między systemami w jednym miejscu: macOS, Windows, Linux.

Selekta powstała na Macu (Finder, ``pgrep``, ``~/Library``). Wersja na
Windows potrzebuje tych samych czynności innymi narzędziami — reszta kodu
woła tylko te funkcje i nie sprawdza ``sys.platform`` sama.
"""
from __future__ import annotations

import os
import string
import subprocess
import sys

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"


def exe(nazwa: str) -> str:
    """Nazwa pliku wykonywalnego: ``ffmpeg`` → ``ffmpeg.exe`` na Windows."""
    return nazwa + ".exe" if WINDOWS and not nazwa.lower().endswith(".exe") else nazwa


def bez_okna() -> dict:
    """Argumenty subprocess, żeby na Windows nie mrugało okno konsoli."""
    if WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def odlaczony() -> dict:
    """Argumenty Popen dla procesu, który ma żyć niezależnie od selekty."""
    if WINDOWS:
        flagi = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        return {"creationflags": flagi}
    return {"start_new_session": True}


def procesy(nazwa: str) -> list[tuple[int, str]]:
    """(pid, ścieżka programu) każdego procesu o tej nazwie (bez .exe)."""
    try:
        if WINDOWS:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"Get-Process -Name '{nazwa}' -ErrorAction SilentlyContinue | "
                 "ForEach-Object { \"$($_.Id)|$($_.Path)\" }"],
                capture_output=True, text=True, timeout=15, **bez_okna())
            out = []
            for linia in r.stdout.splitlines():
                pid, _, sciezka = linia.strip().partition("|")
                if pid.isdigit():
                    out.append((int(pid), sciezka))
            return out
        r = subprocess.run(["pgrep", "-x", nazwa], capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 — brak narzędzia = nie wiemy, więc „nie działa”
        return []
    out = []
    for pid in (int(p) for p in r.stdout.split() if p.isdigit()):
        sciezka = ""
        try:
            if sys.platform.startswith("linux"):
                sciezka = os.readlink(f"/proc/{pid}/exe")
            else:
                sciezka = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                                         capture_output=True, text=True,
                                         timeout=5).stdout.strip()
        except Exception:  # noqa: BLE001
            pass
        out.append((pid, sciezka))
    return out


def dziala(nazwa: str) -> bool:
    return bool(procesy(nazwa))


def pokaz_w_menedzerze(sciezka: str) -> tuple[bool, str]:
    """Pokaż plik zaznaczony w Finderze / Eksploratorze. (sukces, komunikat)."""
    try:
        if MAC:
            subprocess.run(["open", "-R", sciezka], check=True, capture_output=True)
        elif WINDOWS:
            # explorer zwraca 1 nawet przy sukcesie — nie sprawdzamy kodu wyjścia
            subprocess.run(["explorer", f"/select,{os.path.normpath(sciezka)}"])
        else:
            subprocess.run(["xdg-open", os.path.dirname(sciezka)], check=True,
                           capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, f"nie udało się otworzyć folderu: {exc}"
    return True, ""


def nazwa_menedzera() -> str:
    return "Finderze" if MAC else ("Eksploratorze" if WINDOWS else "menedżerze plików")


def dyski_windows() -> list[str]:
    """Litery dysków z wyjątkiem systemowego, np. ['D:\\\\', 'E:\\\\']."""
    if not WINDOWS:
        return []
    systemowy = (os.environ.get("SystemDrive") or "C:").upper()
    out = []
    for litera in string.ascii_uppercase:
        d = f"{litera}:"
        if d == systemowy:
            continue
        if os.path.isdir(d + "\\"):
            out.append(d + "\\")
    return out
