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


# ---------------------------------------------------------------------------
# YAML: zapis wartości i scalanie z sekcjami użytkownika
#
# Wartości wpisywaliśmy kiedyś surowo (`password: {haslo}`). Hasło „abc #def”
# zapisywało się jako „abc” (reszta to komentarz), a „pa: ss”, „@…”, „*…”
# psuły cały plik — slskd nie wstawał, a Soulseek nie ma odzyskiwania konta.
# Teraz KAŻDA wartość idzie w podwójnych cudzysłowach z ucieczką znaków.
#
# Drugi problem: gdy użytkownik miał już własne `soulseek:` czy
# `directories:`, blok selekty doklejał te same klucze najwyższego poziomu
# drugi raz. Teraz nasze wartości wpisujemy DO jego sekcji (bez duplikatów),
# a do bloku selekty trafiają tylko sekcje, których w pliku jeszcze nie ma.
# Bez PyYAML: aplikacja go nie ma, a parser i tak zgubiłby komentarze.
# ---------------------------------------------------------------------------

KOPIA_PIERWOTNA = ".przed-selekta"     # stan sprzed pierwszej zmiany przez apkę
KOPIA_OSTATNIA = ".kopia-selekta"      # stan sprzed ostatniego zapisu


class NietypowyZapis(ValueError):
    """Sekcja w slskd.yml ma zapis, którego nie umiemy bezpiecznie zmienić."""


def _yaml_tekst(wartosc) -> str:
    """Wartość jako skalar YAML w podwójnych cudzysłowach (zawsze tekst)."""
    out = ['"']
    for ch in str(wartosc):
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif 0xD800 <= o <= 0xDFFF:
            raise ValueError("niedozwolony znak w wartości")
        elif o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F or o in (
                0x2028, 0x2029, 0xFEFF, 0xFFFE, 0xFFFF):
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_UCIECZKI = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n",
             "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"',
             "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ",
             "P": " "}


def _rozbij(reszta: str) -> tuple[str, str]:
    """Część po „klucz:” → (wartość jako tekst, komentarz z końca linii).

    Rozumie trzy zapisy skalara: "podwójne" (z ucieczkami), 'pojedyncze'
    ('' = apostrof) i zwykły (komentarz zaczyna się od „ #”).
    """
    s = reszta.strip()
    if s.startswith('"'):
        out, i = [], 1
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s):
                n = s[i + 1]
                dl = {"x": 2, "u": 4, "U": 8}.get(n)
                if dl:
                    try:
                        out.append(chr(int(s[i + 2:i + 2 + dl], 16)))
                    except ValueError:
                        out.append(s[i:i + 2 + dl])
                    i += 2 + dl
                    continue
                out.append(_UCIECZKI.get(n, n))
                i += 2
                continue
            if c == '"':
                return "".join(out), s[i + 1:].strip()
            out.append(c)
            i += 1
        return "".join(out), ""
    if s.startswith("'"):
        out, i = [], 1
        while i < len(s):
            if s[i] == "'":
                if s[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), s[i + 1:].strip()
            out.append(s[i])
            i += 1
        return "".join(out), ""
    m = re.search(r"(^|\s)#", s)
    if m:
        return s[:m.start()].strip(), s[m.start():].strip()
    return s, ""


_KLUCZ_RE = re.compile(r"^( *)([A-Za-z0-9_.-]+):(?:[ \t]+(.*))?$")


def _wciecie(linia: str) -> int:
    return len(linia) - len(linia.lstrip(" "))


def _neutralna(linia: str) -> bool:
    """Pusta albo sam komentarz — nie wpływa na strukturę."""
    s = linia.strip()
    return not s or s.startswith("#")


def _koniec_bloku(linie: list[str], i: int) -> int:
    """Indeks za ostatnią linią treści należącą do klucza z linii `i`."""
    w = _wciecie(linie[i])
    koniec = i + 1
    for j in range(i + 1, len(linie)):
        l = linie[j]
        if _neutralna(l):
            continue
        wj = _wciecie(l)
        # „- element” na tym samym wcięciu to lista należąca do klucza
        if wj > w or (wj == w and l.lstrip().startswith("-")):
            koniec = j + 1
            continue
        break
    return koniec


def _znajdz(linie: list[str], od: int, do: int, wciecie: int, klucz: str) -> int:
    for j in range(od, do):
        l = linie[j]
        if _neutralna(l) or _wciecie(l) != wciecie:
            continue
        m = _KLUCZ_RE.match(l)
        if m and m.group(2) == klucz:
            return j
    return -1


def _wciecie_dzieci(linie: list[str], i: int, koniec: int) -> int:
    for j in range(i + 1, koniec):
        if not _neutralna(linie[j]):
            return _wciecie(linie[j])
    return _wciecie(linie[i]) + 2


def _pusta_wartosc(reszta: str | None) -> bool:
    """Klucz bez wartości (po nim blok) albo z wartością „pustą”."""
    if reszta is None:
        return True
    wartosc, _kom = _rozbij(reszta)
    return reszta.strip().startswith("#") or wartosc in ("", "~", "null", "{}", "[]")


def _sekcja(linie: list[str], sciezka: list[str], nazwa: str,
            od: int = 0, do: int | None = None, wciecie: int = 0) -> tuple[int, int, int]:
    """Znajdź (albo dopisz) zagnieżdżoną mapę; zwróć (linia klucza, koniec, wcięcie dzieci)."""
    do = len(linie) if do is None else do
    klucz, reszta_sciezki = sciezka[0], sciezka[1:]
    i = _znajdz(linie, od, do, wciecie, klucz)
    if i < 0:
        # dopisz za ostatnią linią treści zakresu (komentarze na końcu zostają na końcu)
        wstaw = do
        while wstaw > od and _neutralna(linie[wstaw - 1]):
            wstaw -= 1
        linie.insert(wstaw, " " * wciecie + f"{klucz}:")
        i = wstaw
    else:
        m = _KLUCZ_RE.match(linie[i])
        if not _pusta_wartosc(m.group(3)):
            raise NietypowyZapis(
                f"sekcja „{nazwa}” w konfiguracji slskd ma nietypowy zapis "
                f"(„{linie[i].strip()}”) — nie zmieniam jej, żeby niczego nie zepsuć; "
                "popraw ją ręcznie albo usuń, a potem spróbuj ponownie")
        if m.group(3) is not None and not m.group(3).strip().startswith("#"):
            linie[i] = " " * wciecie + f"{klucz}:"       # „klucz: {}” → blok
    koniec = _koniec_bloku(linie, i)
    dzieci = _wciecie_dzieci(linie, i, koniec)
    if not reszta_sciezki:
        return i, koniec, dzieci
    return _sekcja(linie, reszta_sciezki, nazwa, i + 1, koniec, dzieci)


def _ustaw(linie: list[str], sciezka: list[str], wartosc: str) -> None:
    """Ustaw skalar pod `sciezka` (np. soulseek.password), tworząc brakujące mapy."""
    nazwa = sciezka[0]
    if len(sciezka) > 1:
        i, koniec, w = _sekcja(linie, sciezka[:-1], nazwa)
        od = i + 1
    else:
        od, koniec, w = 0, len(linie), 0
    klucz = sciezka[-1]
    nowa = " " * w + f"{klucz}: {_yaml_tekst(wartosc)}"
    j = _znajdz(linie, od, koniec, w, klucz)
    if j < 0:
        wstaw = koniec
        while wstaw > od and _neutralna(linie[wstaw - 1]):
            wstaw -= 1
        linie.insert(wstaw, nowa)
        return
    m = _KLUCZ_RE.match(linie[j])
    reszta = m.group(3)
    if _koniec_bloku(linie, j) > j + 1 and _pusta_wartosc(reszta):
        raise NietypowyZapis(f"„{klucz}” w sekcji „{nazwa}” konfiguracji slskd nie jest "
                             "pojedynczą wartością — popraw ją ręcznie")
    _wart, komentarz = _rozbij(reszta or "")
    linie[j] = nowa + (f"  {komentarz}" if komentarz else "")


def _dopisz_do_listy(linie: list[str], sciezka: list[str], elementy: list[str]) -> None:
    """Upewnij się, że lista pod `sciezka` zawiera `elementy` (cudze zostają)."""
    i, koniec, w = _sekcja(linie, sciezka, sciezka[0])
    obecne = set()
    ostatni = i
    wciecie_listy = None
    for j in range(i + 1, koniec):
        l = linie[j]
        if _neutralna(l):
            continue
        s = l.lstrip()
        if not s.startswith("-"):
            raise NietypowyZapis(f"„{sciezka[-1]}” w sekcji „{sciezka[0]}” konfiguracji "
                                 "slskd nie jest listą — popraw ją ręcznie")
        wciecie_listy = _wciecie(l)
        obecne.add(_rozbij(s[1:])[0])
        ostatni = j
    if wciecie_listy is None:
        wciecie_listy = _wciecie(linie[i]) + 2
    nowe = [" " * wciecie_listy + f"- {_yaml_tekst(e)}" for e in elementy if e not in obecne]
    linie[ostatni + 1:ostatni + 1] = nowe


def _klucze_glowne(tresc: str) -> set[str]:
    return {m.group(2) for l in tresc.splitlines()
            if not _neutralna(l) and (m := _KLUCZ_RE.match(l)) and not m.group(1)}


def _zapisz_bezpiecznie(sciezka: str, tresc: str) -> None:
    """Zapis atomowy; plik tymczasowy od początku ma prawa 0600 (jest w nim hasło)."""
    import tempfile
    katalog = os.path.dirname(sciezka) or "."
    fd, tmp = tempfile.mkstemp(dir=katalog, prefix=".slskd.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(tresc)
        os.chmod(tmp, 0o600)
        os.replace(tmp, sciezka)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(sciezka, 0o600)      # w środku jest hasło do Soulseeka
    except OSError:
        pass


def zapisz_konfiguracje(sciezka_yml: str, *, klucz_api: str,
                        katalog_pobran: str, katalog_niepelnych: str = "",
                        login: str | None = None,
                        haslo: str | None = None,
                        udostepniane: list[str] | None = None) -> None:
    """Zapisz konfigurację slskd: nasze wartości, reszta pliku nietknięta.

    Sekcje, których w pliku nie ma, trafiają do jednego zarządzanego bloku
    (ograniczonego znacznikami i przy każdym zapisie podmienianego w całości).
    Sekcje, które użytkownik już ma, uzupełniamy na miejscu — bez dublowania
    kluczy najwyższego poziomu. Przed zapisem robimy kopię zapasową.

    `login` i `haslo` pochodzą od użytkownika. Jeśli są puste, zostawiamy
    to, co już jest w pliku — żeby przypadkowy zapis nie wylogował go
    z Soulseeka.

    Rzuca `NietypowyZapis` (ValueError), gdy sekcja użytkownika ma zapis,
    którego nie da się bezpiecznie uzupełnić — plik zostaje wtedy nietknięty.
    """
    stara = ""
    if os.path.isfile(sciezka_yml):
        with open(sciezka_yml, encoding="utf-8") as fh:
            stara = fh.read()

    if not (login and haslo):
        login = login or _wyczytaj(stara, "username")
        haslo = haslo or _wyczytaj(stara, "password")

    # (ścieżka, wartość) — kolejność = kolejność w pliku
    skalary = [
        (["web", "authentication", "api_keys", "selekta", "key"], klucz_api),
        (["web", "authentication", "api_keys", "selekta", "role"], "readwrite"),
        (["web", "authentication", "api_keys", "selekta", "cidr"], "127.0.0.1/32,::1/128"),
        (["directories", "downloads"], katalog_pobran),
    ]
    if katalog_niepelnych:
        skalary.append((["directories", "incomplete"], katalog_niepelnych))
    if login and haslo:
        skalary += [(["soulseek", "username"], login), (["soulseek", "password"], haslo)]
    listy = [(["shares", "directories"], list(udostepniane))] if udostepniane else []

    uzytkownika = _bez_bloku_selekta(stara)
    jego = _klucze_glowne(uzytkownika)

    # 1) sekcje, które użytkownik już ma — uzupełniamy na miejscu
    linie = uzytkownika.rstrip("\n").split("\n") if uzytkownika.strip() else []
    for sciezka, wartosc in skalary:
        if sciezka[0] in jego:
            _ustaw(linie, sciezka, wartosc)
    for sciezka, elementy in listy:
        if sciezka[0] in jego:
            _dopisz_do_listy(linie, sciezka, elementy)

    # 2) pozostałe — w zarządzanym bloku, z komentarzami jak dotąd
    blok: list[str] = []
    opisy = {
        "web": ["# Klucz API — tym selekta rozmawia z slskd. To NIE jest hasło do",
                "# Soulseeka i nie wychodzi poza ten komputer."],
        "directories": ["# Pobrania lądują wprost w bibliotece, żeby apka widziała je od razu",
                        "# i nie ściągała drugi raz tego samego utworu."],
        "shares": ["# Soulseek to sieć wzajemności — udostępnianie własnych",
                   "# plików wyraźnie poprawia szybkość pobierania."],
        "soulseek": ["# Konto Soulseek — podane przez użytkownika."],
    }
    for sekcja in ("web", "directories", "shares", "soulseek"):
        if sekcja in jego:
            continue
        czesc: list[str] = []
        for sciezka, wartosc in skalary:
            if sciezka[0] == sekcja:
                _ustaw(czesc, sciezka, wartosc)
        for sciezka, elementy in listy:
            if sciezka[0] == sekcja:
                _dopisz_do_listy(czesc, sciezka, elementy)
        if czesc:
            blok += [""] + opisy[sekcja] + czesc
    tresc = "\n".join(linie).rstrip() + "\n" if linie else ""
    if blok:
        tresc += "\n" + "\n".join([POCZATEK, *blok, "", KONIEC, ""])

    os.makedirs(os.path.dirname(sciezka_yml) or ".", exist_ok=True)
    if stara and tresc != stara:
        pierwotna = sciezka_yml + KOPIA_PIERWOTNA
        if not os.path.exists(pierwotna):
            _zapisz_bezpiecznie(pierwotna, stara)
        _zapisz_bezpiecznie(sciezka_yml + KOPIA_OSTATNIA, stara)
    _zapisz_bezpiecznie(sciezka_yml, tresc)


def _wyczytaj(tresc: str, klucz: str) -> str:
    """Wartość z sekcji soulseek: (username/password) — dokładnie taka, jaką zapisano."""
    linie = tresc.splitlines()
    i = _znajdz(linie, 0, len(linie), 0, "soulseek")
    if i < 0:
        return ""
    koniec = _koniec_bloku(linie, i)
    w = _wciecie_dzieci(linie, i, koniec)
    j = _znajdz(linie, i + 1, koniec, w, klucz)
    if j < 0:
        return ""
    reszta = _KLUCZ_RE.match(linie[j]).group(3) or ""
    surowa = reszta.strip()
    wartosc, _kom = _rozbij(reszta)
    # bez cudzysłowów „~”/„null” w YAML znaczą „brak wartości”
    if not surowa.startswith(("'", '"')) and wartosc in ("", "~", "null", "Null", "NULL"):
        return ""
    return wartosc


def konto_ustawione(sciezka_yml: str) -> bool:
    """Czy w konfiguracji jest komplet danych logowania (bez ich czytania)."""
    if not os.path.isfile(sciezka_yml):
        return False
    with open(sciezka_yml, encoding="utf-8") as fh:
        tresc = fh.read()
    return bool(_wyczytaj(tresc, "username") and _wyczytaj(tresc, "password"))
