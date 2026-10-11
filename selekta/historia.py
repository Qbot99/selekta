"""Historia sesji — co naprawdę grałeś, a co leży od dwóch lat.

Rekordbox zapisuje każdą sesję jako playlistę nazwaną datą. Wciągnięcie
tego zamienia zgadywanie w metrykę: które utwory wchodzą zawsze, które
ani razu, i po czym co grasz.

Najważniejsze, co z tego wychodzi, to MARTWY BALAST — utwory, które masz
na dysku i których nigdy nie zagrałeś. Bez historii to tylko przeczucie.

Czytamy z XML-a, nie z bazy: ``~/Library/Pioneer/rekordbox/`` to
zaszyfrowane DeviceSQL, które psuje się przy aktualizacjach programu.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from . import config, matcher

PLIK = os.path.join(config.STATE_DIR, "historia.json")

# nazwy sesji w rekordboksie: 2026-08-31, 2026_08_31, 31-08-2026, "2026-08-31 (2)"
_DATA = re.compile(r"(20\d{2})[-_./](\d{1,2})[-_./](\d{1,2})"
                   r"|(\d{1,2})[-_./](\d{1,2})[-_./](20\d{2})")


@dataclass
class Sesja:
    """Jedno granie: kiedy i co poszło, w kolejności."""
    nazwa: str
    data: str = ""
    sciezki: list[str] = field(default_factory=list)
    nieodnalezione: int = 0


def _sciezka_z_location(value: str) -> str:
    # ta sama funkcja co przy wymianie z rekordboxem — bez obcinania na „#"
    from .rbimport import _sciezka_z_location as z_rekordboxa
    return z_rekordboxa(value)


def rozpoznaj_date(nazwa: str) -> str:
    """Wyłuskaj datę z nazwy playlisty; pusty string, gdy jej nie ma."""
    m = _DATA.search(nazwa or "")
    if not m:
        return ""
    if m.group(1):
        rok, mies, dzien = m.group(1), m.group(2), m.group(3)
    else:
        dzien, mies, rok = m.group(4), m.group(5), m.group(6)
    try:
        if not (1 <= int(mies) <= 12 and 1 <= int(dzien) <= 31):
            return ""
    except ValueError:
        return ""
    return f"{rok}-{int(mies):02d}-{int(dzien):02d}"


def _kolekcja(root: ET.Element) -> dict[str, str]:
    """TrackID → ścieżka pliku."""
    mapa = {}
    for t in root.iter("TRACK"):
        tid, loc = t.get("TrackID"), t.get("Location")
        if tid and loc:
            mapa[tid] = _sciezka_z_location(loc)
    return mapa


def _playlisty(root: ET.Element) -> list[tuple[list[str], str, list[str]]]:
    """Wszystkie playlisty jako (ścieżka folderów, nazwa, [TrackID])."""
    wynik = []

    def zejdz(node: ET.Element, przodkowie: list[str]) -> None:
        for dziecko in node.findall("NODE"):
            nazwa = dziecko.get("Name", "") or ""
            if dziecko.get("Type") == "1":          # playlista
                klucze = [t.get("Key") for t in dziecko.findall("TRACK")
                          if t.get("Key")]
                wynik.append((przodkowie, nazwa, klucze))
            else:                                    # folder
                zejdz(dziecko, przodkowie + [nazwa])

    korzen = root.find("PLAYLISTS")
    if korzen is not None:
        zejdz(korzen, [])
    return wynik


def wczytaj_sesje(sciezka_xml: str, folder: str,
                  wszystkie_playlisty: bool = False) -> list[Sesja]:
    """Wyciągnij sesje z XML-a rekordboxa.

    Za sesję uznajemy playlistę, której nazwa zawiera datę, albo leżącą
    w folderze „History"/„Historia". Z opcją `wszystkie_playlisty`
    bierzemy każdą — przydatne, gdy ktoś nazywa sesje po klubie.
    """
    root = ET.parse(sciezka_xml).getroot()
    mapa = _kolekcja(root)
    sesje = []
    for przodkowie, nazwa, klucze in _playlisty(root):
        data = rozpoznaj_date(nazwa)
        w_historii = any(p.lower() in ("history", "historia", "historie")
                         for p in przodkowie)
        if not (data or w_historii or wszystkie_playlisty):
            continue
        if not data:
            data = rozpoznaj_date(" ".join(przodkowie))
        sciezki, brak = [], 0
        for k in klucze:
            surowa = mapa.get(k, "")
            trafiony = None
            if surowa and os.path.isfile(surowa):
                trafiony = os.path.abspath(surowa)
            elif surowa:
                znaleziony = matcher.resolve_in_library(
                    folder, os.path.basename(surowa))
                trafiony = os.path.abspath(znaleziony) if znaleziony else None
            if trafiony:
                sciezki.append(trafiony)
            else:
                brak += 1
        if sciezki:
            sesje.append(Sesja(nazwa=nazwa, data=data, sciezki=sciezki,
                               nieodnalezione=brak))
    sesje.sort(key=lambda s: (s.data or "0000", s.nazwa))
    return sesje


# --------------------------------------------------------------------------
# magazyn
# --------------------------------------------------------------------------

def _wczytaj() -> list[dict]:
    try:
        with open(PLIK, encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _zapisz(dane: list[dict]) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK)


def sesje() -> list[dict]:
    return _wczytaj()


def dopisz(nowe: list[Sesja]) -> dict:
    """Dołóż sesje, pomijając te już zapamiętane (po nazwie i dacie)."""
    stare = _wczytaj()
    znane = {(s.get("nazwa"), s.get("data")) for s in stare}
    dodane = [asdict(s) for s in nowe if (s.nazwa, s.data) not in znane]
    if dodane:
        _zapisz(stare + dodane)
    return {"wczytane": len(nowe), "nowe": len(dodane),
            "juz_znane": len(nowe) - len(dodane), "razem": len(stare) + len(dodane)}


def wyczysc() -> int:
    ile = len(_wczytaj())
    _zapisz([])
    return ile


# --------------------------------------------------------------------------
# metryki
# --------------------------------------------------------------------------

def podsumowanie(folder: str) -> dict:
    """Co grasz, czego nie grasz i co po czym idzie."""
    zapisane = _wczytaj()
    licznik: Counter = Counter()
    ostatnio: dict[str, str] = {}
    przejscia: Counter = Counter()

    for s in zapisane:
        sciezki = s.get("sciezki") or []
        for p in sciezki:
            licznik[p] += 1
            data = s.get("data") or ""
            if data > ostatnio.get(p, ""):
                ostatnio[p] = data
        for a, b in zip(sciezki, sciezki[1:]):
            przejscia[(a, b)] += 1

    w_bibliotece = matcher.audio_files(folder)
    grane = {p for p in licznik if os.path.isfile(p)}
    martwe = [p for p in w_bibliotece if p not in grane]

    def opis(p: str) -> dict:
        return {"file": os.path.basename(p), "path": p,
                "zagran": licznik.get(p, 0), "ostatnio": ostatnio.get(p, "")}

    return {
        "sesji": len(zapisane),
        "utworow_granych": len(grane),
        "w_bibliotece": len(w_bibliotece),
        "martwy_balast": len(martwe),
        "procent_martwych": (round(100 * len(martwe) / len(w_bibliotece))
                             if w_bibliotece else 0),
        "najczestsze": [opis(p) for p, _n in licznik.most_common(15)
                        if os.path.isfile(p)],
        "martwe": [opis(p) for p in martwe[:40]],
        "ulubione_przejscia": [
            {"z": os.path.basename(a), "na": os.path.basename(b), "razy": n}
            for (a, b), n in przejscia.most_common(10) if n > 1],
        "zakres_dat": [s.get("data") for s in zapisane if s.get("data")][:1]
                      + [s.get("data") for s in reversed(zapisane) if s.get("data")][:1],
    }
