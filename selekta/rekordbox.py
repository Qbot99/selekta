"""Wstawianie playlisty prosto do rekordboxa (macOS).

rekordbox potrafi trzymać w panelu bocznym „zaimportowaną bibliotekę" —
kolekcję z pliku XML wraz z playlistami. Ścieżka do tego pliku siedzi w
ustawieniach pod kluczem `bridgeImportedLibraryFile`. Ustawiając ją raz,
sprawiamy, że po każdym uruchomieniu rekordboxa nasz set po prostu tam
jest — bez ręcznego „File → Import Collection".

Ostrożność, bo dotykamy ustawień cudzej aplikacji:
- plik ustawień jest kopiowany do backupu przed pierwszą zmianą,
- podmieniamy WYŁĄCZNIE jeden klucz (chirurgiczne podstawienie, nie
  przepisywanie całego XML-a — rekordbox jest wrażliwy na format),
- gdy rekordbox działa, odmawiamy: zapisałby swoje ustawienia przy
  wyjściu i nadpisał naszą zmianę.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

# rekordbox 7 nadal używa katalogu "rekordbox6"
SETTINGS_DIRS = (
    "~/Library/Application Support/Pioneer/rekordbox6",
    "~/Library/Application Support/Pioneer/rekordbox7",
)
SETTINGS_NAME = "rekordbox3.settings"
KEY = "bridgeImportedLibraryFile"
BACKUP_SUFFIX = ".selekta-backup"


@dataclass
class InstallResult:
    ok: bool
    message: str            # komunikat po polsku dla użytkownika
    settings_path: str = ""
    previous: str = ""
    backup: str = ""


def settings_path() -> str | None:
    """Ścieżka do pliku ustawień rekordboxa albo None, gdy nie znaleziono."""
    for d in SETTINGS_DIRS:
        p = os.path.join(os.path.expanduser(d), SETTINGS_NAME)
        if os.path.isfile(p):
            return p
    return None


def is_running() -> bool:
    """Czy rekordbox jest uruchomiony (wtedy nadpisałby nasze zmiany)."""
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["pgrep", "-x", "rekordbox"],
                             capture_output=True, timeout=5)
        return out.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read()


def imported_library() -> str | None:
    """Aktualnie podpięty plik XML (pusty string = żaden)."""
    p = settings_path()
    if not p:
        return None
    m = re.search(rf'<VALUE name="{KEY}" val="([^"]*)"', _read(p))
    return m.group(1) if m else None


def _xml_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def install(xml_path: str) -> InstallResult:
    """Podepnij `xml_path` jako zaimportowaną bibliotekę rekordboxa."""
    if sys.platform != "darwin":
        return InstallResult(False, "automatyczne wstawianie działa na razie tylko na macOS")

    settings = settings_path()
    if not settings:
        return InstallResult(False, "nie znalazłem ustawień rekordboxa — czy jest zainstalowany?")

    if is_running():
        return InstallResult(
            False,
            "rekordbox jest uruchomiony — zamknij go i kliknij ponownie "
            "(przy wyjściu nadpisuje własne ustawienia)",
            settings_path=settings,
        )

    if not os.path.isfile(xml_path):
        return InstallResult(False, f"brak pliku playlisty: {xml_path}")

    text = _read(settings)
    pattern = re.compile(rf'(<VALUE name="{KEY}" val=")([^"]*)(")')
    m = pattern.search(text)
    if not m:
        return InstallResult(
            False, "ustawienia rekordboxa nie mają pola importowanej biblioteki "
                   "— wskaż plik ręcznie w Preferencjach",
            settings_path=settings)

    previous = m.group(2)
    if previous == xml_path:
        return InstallResult(True, "playlista była już podpięta — odpal rekordbox",
                             settings_path=settings, previous=previous)

    backup = settings + BACKUP_SUFFIX
    if not os.path.exists(backup):          # backup tylko raz, oryginalny stan
        shutil.copy2(settings, backup)

    new_text = pattern.sub(
        lambda mm: mm.group(1) + _xml_escape(xml_path) + mm.group(3), text, count=1)
    tmp = settings + ".selekta-tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write(new_text)
    os.replace(tmp, settings)

    return InstallResult(
        True,
        "playlista podpięta — odpal rekordbox, będzie w panelu bocznym "
        "pod „rekordbox xml”",
        settings_path=settings, previous=previous, backup=backup,
    )


def restore() -> InstallResult:
    """Przywróć ustawienia rekordboxa sprzed naszej pierwszej zmiany."""
    settings = settings_path()
    if not settings:
        return InstallResult(False, "nie znalazłem ustawień rekordboxa")
    backup = settings + BACKUP_SUFFIX
    if not os.path.isfile(backup):
        return InstallResult(False, "brak kopii zapasowej — nic do przywrócenia")
    if is_running():
        return InstallResult(False, "zamknij rekordbox przed przywracaniem ustawień")
    shutil.copy2(backup, settings)
    return InstallResult(True, "przywrócono poprzednie ustawienia rekordboxa",
                         settings_path=settings, backup=backup)
