"""Wymiana danych z rekordboxem w obie strony, przez XML.

Do tej pory apka była rurą jednokierunkową: wypluwała XML i traciła
wszystko, co dopiszesz po stronie rekordboxa — hot cue postawione ręcznie
na CDJ-u, kolory, oceny, licznik odtworzeń, komentarze.

Zasada scalania jest jedna i twarda: **ręczna praca użytkownika wygrywa**.
Analiza selekty uzupełnia wyłącznie puste miejsca. Ręczne cue DJ stawia
świadomie, pod konkretny miks; algorytm zgaduje, a nadpisanie cudzej
pracy widać dopiero na parkiecie.

Świadomie przez XML, nie przez bazę: ``~/Library/Pioneer/rekordbox/``
to zaszyfrowane pliki DeviceSQL, których czytanie psuje się przy każdej
aktualizacji programu. XML jest brzydszy i stabilny.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

from . import config, matcher

PLIK = os.path.join(config.STATE_DIR, "rekordbox.json")

# Type w POSITION_MARK: 0=cue, 1=fade-in, 2=fade-out, 3=load, 4=loop
NAZWY_TYPOW = {"0": "cue", "1": "fade-in", "2": "fade-out", "3": "load", "4": "pętla"}


@dataclass
class Znacznik:
    """Punkt cue z rekordboxa. `num` -1 to memory cue, 0-7 to hot cue A-H."""
    start_s: float
    num: int = -1
    typ: str = "0"
    nazwa: str = ""
    koniec_s: float | None = None      # tylko dla pętli
    kolor: str = ""

    @property
    def hot(self) -> bool:
        return self.num >= 0

    @property
    def etykieta(self) -> str:
        if self.hot:
            return f"hot cue {chr(ord('A') + self.num)}"
        return NAZWY_TYPOW.get(self.typ, "cue")


@dataclass
class WpisRekordbox:
    """Co rekordbox wie o jednym utworze."""
    location: str = ""
    artist: str = ""
    title: str = ""
    bpm: float | None = None
    tonality: str = ""
    first_beat_s: float | None = None
    kolor: str = ""
    ocena: int | None = None
    odtworzen: int | None = None
    komentarz: str = ""
    znaczniki: list[Znacznik] = field(default_factory=list)

    @property
    def ma_reczna_prace(self) -> bool:
        """Czy jest tu cokolwiek, czego algorytm nie umie odtworzyć."""
        return bool(self.znaczniki or self.kolor or self.ocena
                    or self.odtworzen or self.komentarz)


def _sciezka_z_location(value: str) -> str:
    """'file://localhost/Users/a%20b.flac' → '/Users/a b.flac'."""
    if not value:
        return ""
    if value.startswith("file:"):
        return urllib.parse.unquote(urllib.parse.urlparse(value).path)
    return urllib.parse.unquote(value)


def _liczba(value, calkowita=False):
    if value in (None, "", "0.000000"):
        return None if not calkowita else None
    try:
        return int(float(value)) if calkowita else float(value)
    except (TypeError, ValueError):
        return None


def wczytaj_xml(sciezka: str) -> list[WpisRekordbox]:
    """Rozbierz XML wyeksportowany z rekordboxa."""
    root = ET.parse(sciezka).getroot()
    wpisy: list[WpisRekordbox] = []
    for t in root.iter("TRACK"):
        loc = t.get("Location")
        if loc is None:
            continue                       # wpis playlisty, nie definicja utworu
        w = WpisRekordbox(
            location=_sciezka_z_location(loc),
            artist=t.get("Artist", "") or "",
            title=t.get("Name", "") or "",
            bpm=_liczba(t.get("AverageBpm")),
            tonality=t.get("Tonality", "") or "",
            kolor=t.get("Colour", "") or "",
            ocena=_liczba(t.get("Rating"), calkowita=True),
            odtworzen=_liczba(t.get("PlayCount"), calkowita=True),
            komentarz=t.get("Comments", "") or "",
        )
        tempo = t.find("TEMPO")
        if tempo is not None:
            w.first_beat_s = _liczba(tempo.get("Inizio"))
            if w.bpm is None:
                w.bpm = _liczba(tempo.get("Bpm"))
        for m in t.findall("POSITION_MARK"):
            start = _liczba(m.get("Start"))
            if start is None:
                continue
            w.znaczniki.append(Znacznik(
                start_s=start,
                num=_liczba(m.get("Num"), calkowita=True) if m.get("Num") else -1,
                typ=m.get("Type", "0") or "0",
                nazwa=m.get("Name", "") or "",
                koniec_s=_liczba(m.get("End")),
                kolor=_kolor_znacznika(m),
            ))
        w.znaczniki.sort(key=lambda z: z.start_s)
        wpisy.append(w)
    return wpisy


def _kolor_znacznika(m: ET.Element) -> str:
    r, g, b = m.get("Red"), m.get("Green"), m.get("Blue")
    if r is None or g is None or b is None:
        return ""
    try:
        return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))
    except (TypeError, ValueError):
        return ""


# --------------------------------------------------------------------------
# dopasowanie do biblioteki i zapis
# --------------------------------------------------------------------------

def dopasuj(wpis: WpisRekordbox, folder: str) -> str | None:
    """Znajdź plik w bibliotece odpowiadający wpisowi z rekordboxa.

    Najpierw po ścieżce z XML-a — jest dokładna, gdy nic się nie
    przenosiło. Dopiero potem po nazwie pliku, bo biblioteka mogła
    zmienić miejsce.
    """
    if wpis.location and os.path.isfile(wpis.location):
        return os.path.abspath(wpis.location)
    if wpis.location:
        znaleziony = matcher.resolve_in_library(
            folder, os.path.basename(wpis.location))
        if znaleziony:
            return os.path.abspath(znaleziony)
    return None


def _wczytaj_stan() -> dict:
    try:
        with open(PLIK, encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _zapisz_stan(dane: dict) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK)


def dla_pliku(path: str) -> dict | None:
    """Dane z rekordboxa zapamiętane dla tego pliku."""
    return _wczytaj_stan().get(os.path.abspath(path))


def scal(sciezka_xml: str, folder: str) -> dict:
    """Wciągnij XML z rekordboxa i zapamiętaj ręczną pracę użytkownika.

    Nic nie nadpisuje plików ani analiz — zapisuje osobno to, co rekordbox
    wie, żeby EKSPORT mógł to oddać z powrotem zamiast zastąpić własnym
    wyliczeniem.
    """
    wpisy = wczytaj_xml(sciezka_xml)
    stan = _wczytaj_stan()
    dopasowane, nieznane, z_praca = 0, [], 0
    for w in wpisy:
        path = dopasuj(w, folder)
        if not path:
            nieznane.append(f"{w.artist} — {w.title}".strip(" —") or w.location)
            continue
        dopasowane += 1
        if w.ma_reczna_prace:
            z_praca += 1
        stan[path] = {
            **{k: v for k, v in asdict(w).items() if k != "znaczniki"},
            "znaczniki": [asdict(z) for z in w.znaczniki],
        }
    _zapisz_stan(stan)
    return {
        "w_xml": len(wpisy),
        "dopasowane": dopasowane,
        "z_reczna_praca": z_praca,
        "nieodnalezione": nieznane[:20],
        "nieodnalezionych": len(nieznane),
    }


def wyczysc(path: str | None = None) -> int:
    """Zapomnij dane z rekordboxa — dla jednego pliku albo dla wszystkich."""
    stan = _wczytaj_stan()
    if path is None:
        ile = len(stan)
        _zapisz_stan({})
        return ile
    if stan.pop(os.path.abspath(path), None) is None:
        return 0
    _zapisz_stan(stan)
    return 1
