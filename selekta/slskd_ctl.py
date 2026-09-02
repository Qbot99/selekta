"""Sterowanie lokalnym slskd: wykrycie, start, stop, stan połączenia.

selekta nie dystrybuuje slskd ani nie loguje się do Soulseeka — to konto
i hasło użytkownika. Tu tylko uruchamiamy JEGO instalację i pokazujemy,
na czym stoi, żeby nie musiał grzebać w terminalu.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

import requests

from . import config

BINARY_CANDIDATES = (
    "~/slskd/slskd",
    "~/Applications/slskd/slskd",
    "/Applications/slskd/slskd",
    "/usr/local/bin/slskd",
    "/opt/homebrew/bin/slskd",
)
CONFIG_CANDIDATES = (
    "~/Library/Application Support/slskd/slskd.yml",
    "~/.local/share/slskd/slskd.yml",
    "~/.config/slskd/slskd.yml",
)


@dataclass
class Status:
    binary: str = ""            # ścieżka do slskd albo ""
    running: bool = False
    reachable: bool = False     # API odpowiada
    authorized: bool = False    # nasz klucz działa
    logged_in: bool = False     # slskd zalogowany do sieci Soulseek
    username: str = ""
    detail: str = ""


def find_binary() -> str:
    """Ścieżka do slskd — z ustawień, typowych miejsc albo PATH."""
    saved = config.get("slskd_binary")
    if saved and os.path.isfile(os.path.expanduser(saved)):
        return os.path.expanduser(saved)
    for c in BINARY_CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("slskd") or ""


def find_config() -> str:
    for c in CONFIG_CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isfile(p):
            return p
    return ""


def config_write_path() -> str:
    """Dokąd pisać konfigurację slskd: istniejąca albo pierwszy kandydat.

    KAŻDY zapis konfiguracji ma przechodzić tędy. Fallback rozstrzelony po
    endpointach ominął 1.09.2026 stub testu i nadpisał prawdziwy plik
    użytkownika — jedna funkcja daje testom jedno miejsce do podmiany.
    """
    return find_config() or os.path.expanduser(CONFIG_CANDIDATES[0])


def api_key_from_slskd_config() -> str:
    """Wyłuskaj klucz API z konfiguracji slskd (sekcja api_keys).

    Dzięki temu użytkownik nie musi niczego przeklejać — apka sama
    znajduje klucz, który tam jest.
    """
    path = find_config()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    # bierzemy tylko niezakomentowane wpisy 'key: <wartość>'
    best = ""
    in_keys = False
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if re.match(r"^\s{0,6}api_keys:\s*$", line):
            in_keys = True
            continue
        if in_keys:
            if line.strip() and not line.startswith(" "):
                in_keys = False
                continue
            m = re.match(r"^\s+key:\s*(\S+)\s*$", line)
            if m and len(m.group(1)) >= 16:
                best = m.group(1)
    return best


def is_running() -> bool:
    if sys.platform not in ("darwin", "linux"):
        return False
    try:
        return subprocess.run(["pgrep", "-x", "slskd"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def start() -> tuple[bool, str]:
    """Uruchom slskd w tle. Zwraca (sukces, komunikat po polsku)."""
    if is_running():
        return True, "slskd już działa"
    binary = find_binary()
    if not binary:
        return False, ("nie znalazłem slskd — zainstaluj go i wskaż ścieżkę "
                       "w ustawieniach")
    try:
        subprocess.Popen(
            [binary], cwd=os.path.dirname(binary) or None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"nie udało się uruchomić slskd: {exc}"
    return True, "slskd uruchomiony"


def stop() -> tuple[bool, str]:
    if not is_running():
        return True, "slskd nie działa"
    try:
        subprocess.run(["pkill", "-x", "slskd"], capture_output=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"nie udało się zatrzymać: {exc}"
    return True, "slskd zatrzymany"


def status() -> Status:
    """Pełny obraz: proces, API, autoryzacja, logowanie do Soulseeka."""
    st = Status(binary=find_binary(), running=is_running())
    base = (config.get("slskd_url") or "http://localhost:5030").rstrip("/")
    key = config.get("slskd_api_key") or ""
    headers = {"X-API-Key": key} if key else {}

    try:
        r = requests.get(f"{base}/api/v0/session", headers=headers, timeout=4)
        st.reachable = True
        st.authorized = r.ok
        if not r.ok:
            st.detail = ("klucz API nie działa — wygeneruj go ponownie"
                         if key else "brak klucza API")
    except requests.RequestException:
        st.detail = ("slskd nie odpowiada — uruchom go"
                     if st.binary else "slskd nie jest zainstalowany")
        return st

    if st.authorized:
        try:
            srv = requests.get(f"{base}/api/v0/server", headers=headers,
                               timeout=4).json()
            st.logged_in = bool(srv.get("isLoggedIn"))
            st.detail = ("połączony z siecią Soulseek" if st.logged_in
                         else "slskd działa, ale nie jest zalogowany do Soulseeka")
        except (requests.RequestException, ValueError):
            st.detail = "slskd działa; nie udało się odczytać stanu sieci"
    return st
