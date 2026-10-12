"""Układ biblioteki: które pliki są UTWORAMI, a które tylko kopiami w setach.

Kreator kopiuje utwory setu do osobnego folderu (``playlists.collect``),
żeby set był samodzielny — gotowy na pendrive i do XML-a rekordboxa. Ten
folder leży zwykle w samej bibliotece (``downloads_root`` = folder
biblioteki), więc bez rozróżnienia każdy utwór liczył się tyle razy, w ilu
setach był użyty: biblioteka 277 plików przy ok. 79 utworach, a „Usuń
duplikaty” chciało przenieść do kosza 183 pliki z folderów setów — czyli
rozbić sety i XML-e rekordboxa, które wskazują na te ścieżki.

Zasada:

* folder setu to katalog (poniżej korzenia biblioteki) z plikiem
  ``_selekta.json``; wszystko pod nim to KOPIE, nie osobne utwory;
* jeśli ta sama treść leży też poza setami, utworem jest tamten plik,
  a kopie w setach są jego „użyciami” (``sety_utworu``);
* jeśli utwór istnieje WYŁĄCZNIE w setach, jedna z jego kopii
  reprezentuje go w bibliotece — inaczej zniknąłby z listy.

„Ta sama treść” = identyczny rozmiar i identyczne bajty początku i końca
pliku (kopie z ``cp -c`` są bajt w bajt). Gdy kopia rozjechała się z
oryginałem tylko w tagach (np. ktoś poprawił tag w jednym miejscu), łączy
je ta sama nazwa pliku i ten sam czas trwania co do 50 ms — tagi nie
zmieniają długości dźwięku, a dwa różne nagrania o tej samej nazwie i
identycznej długości praktycznie się nie zdarzają.

Wynik jest zapamiętywany, dopóki nie zmieni się lista plików (nazwy,
rozmiary, czasy modyfikacji, foldery setów) — ``/api/tracks`` woła to
przy każdym odświeżeniu.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field

MANIFEST = "_selekta.json"
KOSZ = "_selekta_kosz"
_PROBKA = 64 * 1024
_KOPIA_NR = re.compile(r"\s\(\d+\)$")

_lock = threading.Lock()
_PAMIEC: dict[str, tuple[tuple, "Uklad"]] = {}
_ODCISKI: dict[tuple, str] = {}
_CZASY: dict[tuple, float | None] = {}


@dataclass
class Uklad:
    root: str
    utwory: list[str]                                   # po jednym pliku na utwór
    wszystkie: list[str]                                # łącznie z kopiami w setach
    kopie: dict[str, list[str]] = field(default_factory=dict)   # utwór -> kopie w setach
    kanon: dict[str, str] = field(default_factory=dict)         # plik -> jego utwór
    set_pliku: dict[str, str] = field(default_factory=dict)     # plik w secie -> folder setu
    podpis: str = ""        # odcisk listy plików (zmienia się z każdą zmianą na dysku)

    def w_secie(self, path: str) -> bool:
        return os.path.abspath(path) in self.set_pliku

    def kanoniczny(self, path: str) -> str:
        p = os.path.abspath(path)
        return self.kanon.get(p, p)

    def sety_utworu(self, path: str) -> list[str]:
        """Nazwy setów, w których ten utwór jest użyty (łącznie z jego własnym)."""
        k = self.kanoniczny(path)
        foldery = {self.set_pliku[p] for p in [k, *self.kopie.get(k, [])]
                   if p in self.set_pliku}
        return sorted((os.path.basename(f) for f in foldery), key=str.lower)

    def kopie_utworu(self, path: str) -> list[str]:
        """Wszystkie pliki tego utworu poza nim samym (kopie w setach)."""
        k = self.kanoniczny(path)
        return [p for p in [k, *self.kopie.get(k, [])] if p != os.path.abspath(path)]


def jest_folderem_setu(folder: str) -> bool:
    return os.path.isfile(os.path.join(folder, MANIFEST))


def _odcisk(path: str, size: int, mtime: int) -> str:
    klucz = (path, size, mtime)
    hit = _ODCISKI.get(klucz)
    if hit is not None:
        return hit
    h = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            h.update(fh.read(_PROBKA))
            if size > 2 * _PROBKA:
                fh.seek(-_PROBKA, os.SEEK_END)
                h.update(fh.read(_PROBKA))
    except OSError:
        h.update(path.encode("utf-8", "replace"))   # nieczytelny = unikalny
    wynik = f"{size}:{h.hexdigest()}"
    _ODCISKI[klucz] = wynik
    return wynik


def odcisk_pliku(path: str) -> str:
    """Odcisk treści pliku (rozmiar + początek + koniec) — „ten sam plik?”."""
    try:
        st = os.stat(path)
    except OSError:
        return path
    return _odcisk(os.path.abspath(path), st.st_size, st.st_mtime_ns)


def _czas(path: str, size: int, mtime: int) -> float | None:
    klucz = (path, size, mtime)
    if klucz not in _CZASY:
        try:
            from mutagen import File as MutagenFile
            a = MutagenFile(path)
            _CZASY[klucz] = float(a.info.length) if a is not None else None
        except Exception:                          # noqa: BLE001
            _CZASY[klucz] = None
    return _CZASY[klucz]


def _nazwa(path: str) -> tuple[str, str]:
    stem, ext = os.path.splitext(os.path.basename(path))
    return _KOPIA_NR.sub("", stem).strip().lower(), ext.lower()


def _przejdz(root: str, audio_ext: tuple[str, ...], skip: set[str]):
    """(plik, size, mtime, folder_setu|None) dla każdego pliku audio."""
    out = []
    set_katalogu: dict[str, str | None] = {root: None}
    for katalog, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in skip)
        rodzic = set_katalogu.get(katalog)
        if rodzic is None and katalog != root and MANIFEST in names:
            rodzic = katalog
        set_katalogu[katalog] = rodzic
        for d in dirs:
            set_katalogu[os.path.join(katalog, d)] = rodzic
        for n in sorted(names):
            if n.startswith(".") or not n.lower().endswith(audio_ext):
                continue
            p = os.path.join(katalog, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((p, st.st_size, st.st_mtime_ns, rodzic))
    return out


def wczytaj(folder: str) -> Uklad:
    """Układ biblioteki w ``folder`` (zapamiętany do zmiany plików)."""
    from .matcher import AUDIO_EXT, SKIP_DIRS
    root = os.path.abspath(folder)
    pliki = _przejdz(root, AUDIO_EXT, set(SKIP_DIRS))
    podpis = tuple(pliki)
    with _lock:
        hit = _PAMIEC.get(root)
        if hit and hit[0] == podpis:
            return hit[1]
        uklad = _zbuduj(root, pliki)
        uklad.podpis = hashlib.md5(repr(podpis).encode("utf-8", "replace")).hexdigest()
        _PAMIEC[root] = (podpis, uklad)
        return uklad


def _zbuduj(root: str, pliki: list[tuple]) -> Uklad:
    info = {p: (s, m) for p, s, m, _ in pliki}
    set_pliku = {p: st for p, _s, _m, st in pliki if st}
    biblioteka = [p for p, _s, _m, st in pliki if not st]
    w_setach = [p for p, _s, _m, st in pliki if st]

    od = lambda p: _odcisk(p, *info[p])          # noqa: E731
    cz = lambda p: _czas(p, *info[p])            # noqa: E731

    po_rozmiarze: dict[int, list[str]] = defaultdict(list)
    po_nazwie: dict[tuple, list[str]] = defaultdict(list)
    for p in biblioteka:
        po_rozmiarze[info[p][0]].append(p)
        po_nazwie[_nazwa(p)].append(p)

    def ten_sam_czas(a: str, b: str) -> bool:
        ca, cb = cz(a), cz(b)
        return ca is not None and cb is not None and abs(ca - cb) <= 0.05

    kanon: dict[str, str] = {p: p for p in biblioteka}
    sieroty: list[str] = []
    for s in w_setach:
        cel = None
        for b in po_rozmiarze.get(info[s][0], []):
            if od(b) == od(s):
                cel = b
                break
        if cel is None:
            for b in po_nazwie.get(_nazwa(s), []):
                if ten_sam_czas(b, s):
                    cel = b
                    break
        if cel is None:
            sieroty.append(s)
        else:
            kanon[s] = cel

    # utwory obecne WYŁĄCZNIE w setach: łączymy kopie i jedną zostawiamy
    rodzic = {p: p for p in sieroty}

    def znajdz(p):
        while rodzic[p] != p:
            rodzic[p] = rodzic[rodzic[p]]
            p = rodzic[p]
        return p

    def polacz(a, b):
        ra, rb = znajdz(a), znajdz(b)
        if ra != rb:
            rodzic[max(ra, rb)] = min(ra, rb)

    grupy: dict[object, list[str]] = defaultdict(list)
    for p in sieroty:
        grupy[("r", info[p][0])].append(p)
        grupy[("n", _nazwa(p))].append(p)
    for (rodzaj, _k), czlonkowie in grupy.items():
        for i, a in enumerate(czlonkowie):
            for b in czlonkowie[i + 1:]:
                if znajdz(a) == znajdz(b):
                    continue
                if rodzaj == "r" and od(a) == od(b):
                    polacz(a, b)
                elif rodzaj == "n" and ten_sam_czas(a, b):
                    polacz(a, b)
    for p in sieroty:
        kanon[p] = znajdz(p)

    kopie: dict[str, list[str]] = defaultdict(list)
    for p, k in kanon.items():
        if p != k:
            kopie[k].append(p)
    utwory = sorted({k for k in kanon.values()})
    return Uklad(root=root, utwory=utwory, wszystkie=sorted(p for p, *_ in pliki),
                 kopie={k: sorted(v) for k, v in kopie.items()},
                 kanon=kanon, set_pliku=set_pliku)


def zapomnij() -> None:
    """Wyczyść pamięć (testy, ręczne odświeżenie)."""
    with _lock:
        _PAMIEC.clear()
        _ODCISKI.clear()
        _CZASY.clear()
