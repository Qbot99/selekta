"""Automatyczna instalacja i konfiguracja slskd.

Cel: użytkownik pobiera selektę, klika i ma działającą apkę. Bez terminala,
bez Homebrew, bez ręcznego dłubania w YAML-u.

Czego ten moduł świadomie NIE robi: nie zakłada konta w Soulseeku i nie
wymyśla haseł. Login i hasło podaje użytkownik — my je tylko zapisujemy
do konfiguracji slskd, z prawami 0600, i nigdy nie zwracamy ani nie
logujemy.
"""
from __future__ import annotations

import io
import os
import platform
import re
import secrets
import shutil
import stat
import zipfile

import requests

WYDANIA = "https://api.github.com/repos/slskd/slskd/releases/latest"
KATALOG_DOMYSLNY = os.path.expanduser("~/.selekta/slskd")

POCZATEK = "# === zarządzane przez selekta — nie edytuj ręcznie ==="
KONIEC = "# === koniec bloku selekta ==="


def platforma() -> str | None:
    """Końcówka nazwy pliku wydania dla tego systemu, np. 'osx-arm64'."""
    system = platform.system()
    maszyna = platform.machine().lower()
    arm = maszyna in ("arm64", "aarch64")
    if system == "Darwin":
        return "osx-arm64" if arm else "osx-x64"
    if system == "Linux":
        return "linux-arm64" if arm else "linux-x64"
    if system == "Windows":
        return "win-arm64" if arm else "win-x64"
    return None


def najnowsze_wydanie() -> tuple[str, str] | None:
    """(wersja, adres pliku) dla tej platformy — albo None."""
    cel = platforma()
    if not cel:
        return None
    try:
        r = requests.get(WYDANIA, timeout=20,
                         headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        dane = r.json()
    except (requests.RequestException, ValueError):
        return None
    for a in dane.get("assets", []):
        nazwa = a.get("name", "")
        if nazwa.endswith(f"-{cel}.zip"):
            return dane.get("tag_name", "?"), a.get("browser_download_url", "")
    return None


def zainstaluj(katalog: str = KATALOG_DOMYSLNY,
               postep=None) -> tuple[bool, str, str]:
    """Pobierz i rozpakuj slskd. Zwraca (udane, komunikat, ścieżka)."""
    wydanie = najnowsze_wydanie()
    if not wydanie:
        return False, ("nie znalazłem wersji slskd dla tego systemu "
                       f"({platform.system()} {platform.machine()})"), ""
    wersja, url = wydanie
    if postep:
        postep(f"pobieram slskd {wersja}…")
    try:
        r = requests.get(url, timeout=300, stream=True)
        r.raise_for_status()
        bufor = io.BytesIO()
        pobrano = 0
        for kawalek in r.iter_content(chunk_size=1024 * 256):
            bufor.write(kawalek)
            pobrano += len(kawalek)
            if postep and pobrano % (1024 * 1024 * 8) < 1024 * 256:
                postep(f"pobieram slskd {wersja}… {pobrano // 1024 // 1024} MB")
    except requests.RequestException as exc:
        return False, f"nie udało się pobrać: {exc}", ""

    if postep:
        postep("rozpakowuję…")
    os.makedirs(katalog, exist_ok=True)
    try:
        with zipfile.ZipFile(bufor) as z:
            for wpis in z.namelist():
                # zip slip: wpis w archiwum nie może wyjść poza katalog docelowy
                cel = os.path.abspath(os.path.join(katalog, wpis))
                if os.path.commonpath([cel, os.path.abspath(katalog)]) != \
                        os.path.abspath(katalog):
                    return False, f"archiwum próbuje pisać poza katalogiem: {wpis}", ""
            z.extractall(katalog)
    except (zipfile.BadZipFile, OSError) as exc:
        return False, f"nie udało się rozpakować: {exc}", ""

    nazwa = "slskd.exe" if platform.system() == "Windows" else "slskd"
    sciezka = ""
    for korzen, _katalogi, pliki in os.walk(katalog):
        if nazwa in pliki:
            sciezka = os.path.join(korzen, nazwa)
            break
    if not sciezka:
        return False, "w archiwum nie ma pliku slskd", ""
    if platform.system() != "Windows":
        st = os.stat(sciezka)
        os.chmod(sciezka, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # macOS oznacza pobrane pliki kwarantanną i odmawia uruchomienia
        _zdejmij_kwarantanne(sciezka)
    return True, f"zainstalowano slskd {wersja}", sciezka


def _zdejmij_kwarantanne(sciezka: str) -> None:
    """Usuń atrybut com.apple.quarantine z pobranego pliku wykonywalnego."""
    if platform.system() != "Darwin":
        return
    import subprocess
    try:
        subprocess.run(["xattr", "-d", "com.apple.quarantine", sciezka],
                       capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def wygeneruj_klucz() -> str:
    """Losowy klucz API do rozmowy selekta ↔ slskd (nie jest hasłem)."""
    return secrets.token_hex(24)


def _bez_bloku_selekta(tresc: str) -> str:
    """Usuń poprzedni blok selekty razem ze starymi, doklejanymi sekcjami."""
    tresc = re.sub(re.escape(POCZATEK) + r".*?" + re.escape(KONIEC),
                   "", tresc, flags=re.DOTALL)
    # sprzątamy też bloki z wcześniejszych wersji apki, dopisywane luzem
    tresc = re.sub(r"\n# --- (dopisane|katalogi|konto)[^\n]*\n"
                   r"(?:(?:[ \t#][^\n]*|\w[^\n]*:[^\n]*|\n)*)", "\n", tresc)
    return tresc.rstrip() + "\n"


def zapisz_konfiguracje(sciezka_yml: str, *, klucz_api: str,
                        katalog_pobran: str, katalog_niepelnych: str = "",
                        login: str | None = None,
                        haslo: str | None = None,
                        udostepniane: list[str] | None = None) -> None:
    """Zapisz konfigurację slskd w jednym, zarządzanym bloku.

    Blok jest ograniczony znacznikami i przy każdym zapisie podmieniany
    w całości — dzięki temu konfiguracja nie puchnie od doklejanych sekcji
    i zawsze wiadomo, co należy do apki, a co użytkownik dopisał sam.

    `login` i `haslo` pochodzą od użytkownika. Jeśli są puste, zostawiamy
    to, co już jest w pliku — żeby przypadkowy zapis nie wylogował go
    z Soulseeka.
    """
    stara = ""
    if os.path.isfile(sciezka_yml):
        with open(sciezka_yml, encoding="utf-8") as fh:
            stara = fh.read()

    if not (login and haslo):
        login = login or _wyczytaj(stara, "username")
        haslo = haslo or _wyczytaj(stara, "password")

    linie = [
        POCZATEK,
        "",
        "# Klucz API — tym selekta rozmawia z slskd. To NIE jest hasło do",
        "# Soulseeka i nie wychodzi poza ten komputer.",
        "web:",
        "  authentication:",
        "    api_keys:",
        "      selekta:",
        f"        key: {klucz_api}",
        "        role: readwrite",
        "        cidr: 127.0.0.1/32,::1/128",
        "",
        "# Pobrania lądują wprost w bibliotece, żeby apka widziała je od razu",
        "# i nie ściągała drugi raz tego samego utworu.",
        "directories:",
        f"  downloads: {katalog_pobran}",
    ]
    if katalog_niepelnych:
        linie.append(f"  incomplete: {katalog_niepelnych}")
    if udostepniane:
        linie += ["", "# Soulseek to sieć wzajemności — udostępnianie własnych",
                  "# plików wyraźnie poprawia szybkość pobierania.", "shares:",
                  "  directories:"]
        linie += [f"    - {k}" for k in udostepniane]
    if login and haslo:
        linie += ["", "# Konto Soulseek — podane przez użytkownika.",
                  "soulseek:", f"  username: {login}", f"  password: {haslo}"]
    linie += ["", KONIEC, ""]

    nowa = _bez_bloku_selekta(stara) + "\n" + "\n".join(linie)
    os.makedirs(os.path.dirname(sciezka_yml), exist_ok=True)
    tmp = sciezka_yml + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(nowa)
    os.replace(tmp, sciezka_yml)
    try:
        os.chmod(sciezka_yml, 0o600)      # w środku jest hasło do Soulseeka
    except OSError:
        pass


def _wyczytaj(tresc: str, klucz: str) -> str:
    """Wyłuskaj wartość z sekcji soulseek: (username/password)."""
    m = re.search(r"^soulseek:\s*$((?:\n[ \t]+[^\n]*)*)", tresc,
                  flags=re.MULTILINE)
    if not m:
        return ""
    m2 = re.search(rf"^\s+{klucz}:\s*(.+)$", m.group(1), flags=re.MULTILINE)
    if not m2:
        return ""
    wartosc = m2.group(1).strip().strip('"\'')
    return "" if wartosc in ("~", "null") else wartosc


def konto_ustawione(sciezka_yml: str) -> bool:
    """Czy w konfiguracji jest komplet danych logowania (bez ich czytania)."""
    if not os.path.isfile(sciezka_yml):
        return False
    with open(sciezka_yml, encoding="utf-8") as fh:
        tresc = fh.read()
    return bool(_wyczytaj(tresc, "username") and _wyczytaj(tresc, "password"))
