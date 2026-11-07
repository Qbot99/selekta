"""Szukanie muzyki na całym komputerze.

Biblioteka to jeden folder (zwykle ``~/Music``), a utwory DJ-a leżą też
w Pobranych, na Biurku, w starych folderach i na dyskach zewnętrznych.
Skaner przechodzi folder domowy, ``/Users/Shared`` i podłączone dyski.
Pomija system, programy, dane aplikacji (``~/Library``), pakiety projektów,
sample i krótkie dźwięki oraz pliki, które biblioteka już ma (ta sama
zawartość, choćby pod inną nazwą).

Skan niczego nie zmienia. Dodanie do biblioteki to KOPIA do
``<biblioteka>/Z komputera/…`` z zachowaną ścieżką źródła, więc dwa
foldery „Nowe" z różnych miejsc się nie mieszają. Na tym samym dysku APFS
kopia jest klonem (``cp -c``) i zajmuje ~0 bajtów; z innego dysku to
pełna kopia, dlatego przed nią sprawdzamy wolne miejsce. Oryginały zostają
tam, gdzie były — inne programy (rekordbox, Serato, Muzyka) dalej je widzą.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time

from . import matcher

MIN_S = 60.0                 # krótsze: sample, dzwonki, notatki głosowe
MIN_BAJTOW = 400_000         # szybkie sito przed czytaniem nagłówka
FOLDER_DOCELOWY = "Z komputera"
ZAPAS_BAJTOW = 1_000_000_000  # tyle zostawiamy wolnego przy pełnej kopii
# Plik trzymany tylko w iCloud (Biurko i Dokumenty bywają synchronizowane).
# Samo czytanie nagłówka zmusiłoby macOS do pobrania całego pliku, więc
# takich plików nie otwieramy — liczymy je osobno.
SF_DATALESS = 0x40000000

# katalogi, do których nie wchodzimy nigdzie
POMIJANE_NAZWY = {
    "node_modules", "site-packages", "dist-packages", "venv", "__pycache__",
    "_selekta_kosz", "Caches", "DerivedData", "Backups.backupdb",
    # Windows: system i programy na dodatkowych dyskach
    "$Recycle.Bin", "System Volume Information", "Windows", "Program Files",
    "Program Files (x86)", "ProgramData", "WindowsApps", "$WinREAgent",
}
# znaki projektu z kodem (strona, aplikacja, skrypty): pliki audio w środku to
# zasoby i sygnały testowe, nie utwory — cały taki katalog pomijamy
ZNACZNIKI_PROJEKTU = {
    ".git", ".hg", ".svn", "venv", ".venv", "node_modules", "__pycache__", "pyproject.toml",
    "setup.py", "package.json", "Cargo.toml", "go.mod", "composer.json",
    "wp-config.php", "pubspec.yaml", "Podfile", "Package.swift", "Gemfile",
}
# katalogi pomijane tylko bezpośrednio w folderze domowym
POMIJANE_W_DOMU = {"Library", "Applications", "AppData"}
# pakiety (macOS pokazuje je jako jeden plik) — w środku są dźwięki programów
# i ścieżki projektów, nie utwory
PAKIETY = (
    ".app", ".bundle", ".framework", ".plugin", ".component", ".vst", ".vst3",
    ".aaxplugin", ".logicx", ".band", ".photoslibrary", ".musiclibrary",
    ".tvlibrary", ".imovielibrary", ".fcpbundle", ".xcodeproj", ".xcassets",
    ".lproj", ".rtfd", ".backup", ".inprogress",
)

_lock = threading.Lock()
_STAN: dict = {"etap": "", "w_toku": False}
_PRZERWIJ = threading.Event()


# ------------------------------------------------------------------ gdzie

def korzenie(dom: str | None = None, wolumeny: str = "/Volumes") -> list[str]:
    """Miejsca do przeszukania: dom, /Users/Shared i podłączone dyski."""
    dom = os.path.abspath(os.path.expanduser(dom or "~"))
    out = [dom]
    from .system import WINDOWS, dyski_windows
    if WINDOWS:
        publiczny = os.path.join(os.path.dirname(dom), "Public", "Music")
        if os.path.isdir(publiczny):
            out.append(publiczny)
        return out + dyski_windows()            # D:\, E:\ … (bez dysku systemowego)
    wspolne = os.path.join(os.path.dirname(dom), "Shared")
    if os.path.isdir(wspolne):
        out.append(wspolne)
    try:
        nazwy = sorted(os.listdir(wolumeny))
    except OSError:
        nazwy = []
    for n in nazwy:
        p = os.path.join(wolumeny, n)
        # dysk systemowy jest pod /Volumes jako dowiązanie do „/"
        if n.startswith(".") or os.path.realpath(p) == "/" or not os.path.isdir(p):
            continue
        out.append(p)
    return out


def _w(sciezka: str, folder: str) -> bool:
    try:
        return os.path.commonpath([sciezka, folder]) == folder
    except ValueError:
        return False


def _pomin_katalog(nazwa: str, rodzic: str, dom: str) -> bool:
    if nazwa.startswith(".") or nazwa in POMIJANE_NAZWY:
        return True
    if rodzic == dom and nazwa in POMIJANE_W_DOMU:
        return True
    return nazwa.lower().endswith(PAKIETY)


# --------------------------------------------------------- ta sama zawartość

def odcisk(sciezka: str, rozmiar: int | None = None) -> str:
    """Szybki odcisk zawartości: rozmiar + początek + koniec pliku.

    Wystarcza, żeby rozpoznać kopię tego samego pliku pod inną nazwą —
    całości nie czytamy, bo na dysku zewnętrznym trwałoby to minutami.
    """
    rozmiar = os.path.getsize(sciezka) if rozmiar is None else rozmiar
    h = hashlib.blake2b(str(rozmiar).encode(), digest_size=16)
    kawalek = 128 * 1024
    with open(sciezka, "rb") as fh:
        h.update(fh.read(kawalek))
        if rozmiar > 2 * kawalek:
            fh.seek(-kawalek, os.SEEK_END)
            h.update(fh.read(kawalek))
    return h.hexdigest()


class _Znane:
    """Pliki biblioteki: odcisk liczony tylko przy zgodnym rozmiarze."""

    def __init__(self, pliki: list[str]):
        self.po_rozmiarze: dict[int, list[str]] = {}
        self.nazwy: set[tuple[str, int]] = set()     # (nazwa, rozmiar) — dla plików z iCloud
        for p in pliki:
            try:
                r = os.path.getsize(p)
            except OSError:
                continue
            self.po_rozmiarze.setdefault(r, []).append(p)
            self.nazwy.add((os.path.basename(p).lower(), r))
        self._odciski: dict[str, str] = {}

    def ma(self, rozmiar: int, odc: str) -> bool:
        for p in self.po_rozmiarze.get(rozmiar, ()):
            if p not in self._odciski:
                try:
                    self._odciski[p] = odcisk(p, rozmiar)
                except OSError:
                    self._odciski[p] = ""
            if self._odciski[p] == odc:
                return True
        return False


# ------------------------------------------------------------------ skan

def _czas_i_tagi(sciezka: str) -> tuple[float | None, dict]:
    _tokeny, czas, info = matcher._file_info(sciezka)
    return czas, info


def skanuj(biblioteka: str, miejsca: list[str] | None = None,
           postep=None, przerwij: threading.Event | None = None,
           dom: str | None = None) -> dict:
    """Znajdź utwory spoza biblioteki. Niczego nie zmienia na dysku.

    Zwraca ``{"foldery": [...], "juz_w_bibliotece": n, "kopie": n,
    "krotkie": n, "brak_dostepu": [...], "miejsca": [...]}``; każdy folder
    to ``{"folder", "pliki": [...], "rozmiar", "ten_sam_dysk"}``.
    """
    biblioteka = os.path.abspath(os.path.expanduser(biblioteka))
    dom = os.path.abspath(os.path.expanduser(dom or "~"))
    miejsca = [os.path.abspath(m) for m in (miejsca or korzenie(dom))]
    try:
        znane = _Znane(matcher.audio_files(biblioteka, kopie_w_setach=True))
    except FileNotFoundError:
        znane = _Znane([])
    try:
        dysk_biblioteki = os.stat(biblioteka).st_dev
    except OSError:
        dysk_biblioteki = None

    wynik = {"juz_w_bibliotece": 0, "kopie": 0, "krotkie": 0, "w_chmurze": 0,
             "projekty": 0,
             "brak_dostepu": [], "miejsca": miejsca, "przerwany": False}
    znalezione: dict[str, dict] = {}            # odcisk → plik
    licznik = {"foldery": 0, "pliki": 0}

    def blad(exc: OSError) -> None:
        if isinstance(exc, PermissionError) and len(wynik["brak_dostepu"]) < 30:
            wynik["brak_dostepu"].append(getattr(exc, "filename", "") or str(exc))

    for korzen in miejsca:
        for katalog, dirs, names in os.walk(korzen, onerror=blad):
            if przerwij is not None and przerwij.is_set():
                wynik["przerwany"] = True
                break
            # biblioteka już jest w bibliotece; jej podfoldery też
            if _w(katalog, biblioteka):
                dirs[:] = []
                continue
            # korzenia (domu, dysku) nie wykluczamy, nawet gdy ma np. .git
            if katalog != korzen and ZNACZNIKI_PROJEKTU & (set(names) | set(dirs)):
                wynik["projekty"] += 1
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if not _pomin_katalog(d, katalog, dom)
                             and not _w(os.path.join(katalog, d), biblioteka))
            licznik["foldery"] += 1
            if postep is not None and licznik["foldery"] % 50 == 0:
                postep(katalog, licznik["foldery"], len(znalezione))
            for n in sorted(names):
                if n.startswith(".") or not n.lower().endswith(matcher.AUDIO_EXT):
                    continue
                p = os.path.join(katalog, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_size < MIN_BAJTOW:
                    wynik["krotkie"] += 1
                    continue
                if getattr(st, "st_flags", 0) & SF_DATALESS:
                    # nie otwieramy (pobrałoby się z iCloud); bez odcisku
                    # i czasu — rozpoznajemy po nazwie i rozmiarze
                    if (n.lower(), st.st_size) in znane.nazwy:
                        wynik["juz_w_bibliotece"] += 1
                        continue
                    wynik["w_chmurze"] += 1
                    licznik["pliki"] += 1
                    znalezione[f"icloud:{p}"] = {
                        "path": p, "name": n, "size": st.st_size, "duration": None,
                        "artist": "", "title": "", "w_chmurze": True,
                        "ten_sam_dysk": False}           # pobranie zajmie miejsce
                    continue
                czas, info = _czas_i_tagi(p)
                if czas is not None and czas < MIN_S:
                    wynik["krotkie"] += 1
                    continue
                try:
                    odc = odcisk(p, st.st_size)
                except OSError:
                    continue
                if znane.ma(st.st_size, odc):
                    wynik["juz_w_bibliotece"] += 1
                    continue
                licznik["pliki"] += 1
                plik = {"path": p, "name": n, "size": st.st_size,
                        "duration": round(czas, 1) if czas else None,
                        "artist": info.get("artist", ""), "title": info.get("title", ""),
                        "ten_sam_dysk": st.st_dev == dysk_biblioteki}
                poprzedni = znalezione.get(odc)
                if poprzedni is None:
                    znalezione[odc] = plik
                    continue
                wynik["kopie"] += 1
                # ta sama zawartość w dwóch miejscach: zostaje krótsza ścieżka,
                # zwykle to oryginał, a dłuższa — kopia zapasowa
                if (len(p), p) < (len(poprzedni["path"]), poprzedni["path"]):
                    znalezione[odc] = plik
        if wynik["przerwany"]:
            break

    foldery: dict[str, dict] = {}
    for plik in znalezione.values():
        f = os.path.dirname(plik["path"])
        g = foldery.setdefault(f, {"folder": f, "pliki": [], "rozmiar": 0,
                                   "ten_sam_dysk": True, "w_chmurze": 0})
        g["pliki"].append(plik)
        g["rozmiar"] += plik["size"]
        g["ten_sam_dysk"] = g["ten_sam_dysk"] and plik["ten_sam_dysk"]
        g["w_chmurze"] += 1 if plik.get("w_chmurze") else 0
    for g in foldery.values():
        g["pliki"].sort(key=lambda x: x["name"].lower())
    wynik["foldery"] = sorted(foldery.values(),
                              key=lambda g: (-len(g["pliki"]), g["folder"].lower()))
    wynik["utworow"] = len(znalezione)
    return wynik


# ------------------------------------------------------------------ dodanie

def cel_dla(zrodlo: str, biblioteka: str, dom: str | None = None,
            wolumeny: str = "/Volumes") -> str:
    """Gdzie w bibliotece wyląduje kopia — ścieżka źródła zachowana."""
    dom = os.path.abspath(os.path.expanduser(dom or "~"))
    zrodlo = os.path.abspath(zrodlo)
    baza = os.path.join(biblioteka, FOLDER_DOCELOWY)
    dysk, reszta = os.path.splitdrive(zrodlo)
    if _w(zrodlo, dom):
        rel = os.path.relpath(zrodlo, dom)
    elif _w(zrodlo, wolumeny):
        rel = os.path.relpath(zrodlo, wolumeny)          # „<dysk>/…"
    elif dysk:                                           # Windows: „D/Muzyka/…”
        rel = os.path.join(dysk.rstrip(":"), reszta.lstrip("\\/"))
    else:
        rel = zrodlo.lstrip(os.sep)
    return os.path.join(baza, rel)


def sprawdz_miejsce(pliki: list[dict], biblioteka: str) -> None:
    """ValueError, gdy pełne kopie (z innych dysków) nie zmieszczą się."""
    pelne = sum(p["size"] for p in pliki if not p.get("ten_sam_dysk"))
    if not pelne:
        return                                     # klony APFS nie zajmują miejsca
    wolne = shutil.disk_usage(biblioteka).free
    if pelne + ZAPAS_BAJTOW > wolne:
        raise ValueError(
            f"za mało miejsca: pliki z innych dysków zajmą {pelne / 1e9:.1f} GB, "
            f"wolne {wolne / 1e9:.1f} GB (zostawiam 1 GB zapasu) — "
            "odznacz część folderów z innych dysków")


def dodaj(pliki: list[dict], biblioteka: str, postep=None,
          dom: str | None = None, wolumeny: str = "/Volumes") -> dict:
    """Skopiuj wskazane pliki ze skanu do ``Z komputera/…`` w bibliotece."""
    from .playlists import fast_copy

    biblioteka = os.path.abspath(os.path.expanduser(biblioteka))
    sprawdz_miejsce(pliki, biblioteka)
    dodane, pominiete, bledy = [], 0, []
    for i, p in enumerate(pliki):
        src = p["path"]
        cel = cel_dla(src, biblioteka, dom=dom, wolumeny=wolumeny)
        try:
            rozmiar = os.path.getsize(src)
            if os.path.exists(cel):
                if os.path.getsize(cel) == rozmiar and odcisk(cel) == odcisk(src):
                    pominiete += 1                 # już dodany wcześniej
                    continue
                stem, ext = os.path.splitext(cel)
                n = 2
                while os.path.exists(f"{stem} ({n}){ext}"):
                    n += 1
                cel = f"{stem} ({n}){ext}"
            os.makedirs(os.path.dirname(cel), exist_ok=True)
            fast_copy(src, cel)
            dodane.append(cel)
        except OSError as exc:
            bledy.append(f"{os.path.basename(src)}: {exc.strerror or exc}")
        if postep is not None:
            postep(i + 1, len(pliki))
    return {"dodane": len(dodane), "pominiete": pominiete, "bledy": bledy[:20],
            "folder": os.path.join(biblioteka, FOLDER_DOCELOWY)}


# ------------------------------------------------------------ praca w tle

def stan() -> dict:
    with _lock:
        return dict(_STAN)


def _ustaw(**kw) -> None:
    with _lock:
        _STAN.update(kw)


def start_skanu(biblioteka: str, miejsca: list[str] | None = None) -> dict:
    """Uruchom skan w tle (jeden naraz). Postęp i wynik: ``stan()``."""
    with _lock:
        if _STAN.get("w_toku"):
            return dict(_STAN)
        _PRZERWIJ.clear()
        _STAN.clear()
        _STAN.update({"etap": "szukam", "w_toku": True, "start": time.time(),
                      "folderow": 0, "znalezione": 0, "biezacy": ""})

    def postep(katalog, folderow, znalezione):
        _ustaw(biezacy=katalog, folderow=folderow, znalezione=znalezione)

    def praca():
        try:
            w = skanuj(biblioteka, miejsca, postep=postep, przerwij=_PRZERWIJ)
            _ustaw(w_toku=False, wynik=w, koniec=time.time(), znalezione=w["utworow"])
        except Exception as exc:  # noqa: BLE001 — błąd ma trafić do UI, nie w próżnię
            _ustaw(w_toku=False, blad=str(exc), koniec=time.time())

    threading.Thread(target=praca, daemon=True, name="skaner").start()
    return stan()


def przerwij() -> None:
    _PRZERWIJ.set()


def start_dodawania(foldery: list[str], biblioteka: str,
                    pominiete_pliki: list[str] | None = None) -> dict:
    """Dodaj w tle wybrane foldery z OSTATNIEGO skanu.

    Przyjmujemy tylko ścieżki, które skan znalazł — endpoint nie może
    służyć do kopiowania dowolnych plików z dysku.
    """
    with _lock:
        if _STAN.get("w_toku"):
            raise RuntimeError("skaner jeszcze pracuje — poczekaj na koniec")
        wynik = _STAN.get("wynik")
        if not wynik:
            raise RuntimeError("najpierw przeszukaj komputer")
        wybrane = set(foldery)
        bez = set(pominiete_pliki or ())
        pliki = [p for g in wynik["foldery"] if g["folder"] in wybrane
                 for p in g["pliki"] if p["path"] not in bez]
        if not pliki:
            raise RuntimeError("nie wybrano żadnych utworów ze skanu")
        sprawdz_miejsce(pliki, biblioteka)
        _STAN.update({"etap": "dodaję", "w_toku": True, "zrobione": 0,
                      "wszystkie": len(pliki), "dodawanie": None, "blad": None})

    def postep(z, w):
        _ustaw(zrobione=z, wszystkie=w)

    def praca():
        try:
            d = dodaj(pliki, biblioteka, postep=postep)
            _ustaw(w_toku=False, dodawanie=d)
        except Exception as exc:  # noqa: BLE001
            _ustaw(w_toku=False, blad=str(exc))

    threading.Thread(target=praca, daemon=True, name="skaner-dodaj").start()
    return stan()
