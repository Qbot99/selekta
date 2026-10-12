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
import unicodedata
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
    battito: int = 1                 # numer bitu w takcie dla kotwicy (TEMPO Battito)
    kolor: str = ""
    ocena: int | None = None
    odtworzen: int | None = None
    komentarz: str = ""
    znaczniki: list[Znacznik] = field(default_factory=list)
    # wszystkie znaczniki TEMPO (zmienne tempo); first_beat_s/bpm to pierwszy
    tempa: list[dict] = field(default_factory=list)
    # skąd XML: „rekordbox" albo „selekta" (nasz własny eksport wczytany z powrotem)
    zrodlo: str = "rekordbox"
    pominiete_cue_selekty: int = 0

    @property
    def ma_reczna_prace(self) -> bool:
        """Czy jest tu cokolwiek, czego algorytm nie umie odtworzyć."""
        return bool(self.znaczniki or self.kolor or self.ocena
                    or self.odtworzen or self.komentarz)


def _sciezka_z_location(value: str) -> str:
    """'file://localhost/Users/a%20b.flac' → '/Users/a b.flac'.

    Bez urlparse: niezakodowany „#" albo „?" w nazwie pliku (zdarza się
    w XML-ach z innych programów) urlparse brał za początek fragmentu
    i obcinał ścieżkę — utwór „#1" przepadał po cichu.
    """
    if not value:
        return ""
    if value.startswith("file://localhost/"):
        value = value[len("file://localhost"):]
    elif value.startswith("file:///"):
        value = value[len("file://"):]
    elif value.startswith("file:"):
        return urllib.parse.unquote(urllib.parse.urlparse(value).path)
    return urllib.parse.unquote(value)


def _klucz(path: str) -> str:
    """Klucz stanu: ścieżka bezwzględna w NFC.

    macOS potrafi trzymać nazwę pliku w NFD („a" + kreska), a rekordbox
    zapisuje Location w NFC. Bez normalizacji stan zapisany pod NFC nie
    trafiał przy eksporcie pliku o nazwie NFD — ręczne cue i ocena
    przepadały po cichu.
    """
    return unicodedata.normalize("NFC", os.path.abspath(path))


# Własne cue selekty: nazwa i numer hot cue, które nadaje eksport
# (dj_export.to_rekordbox_xml). Po wczytaniu NASZEGO XML-a z powrotem nie
# są ręczną pracą — inaczej zamrażały starą analizę na zawsze.
CUE_SELEKTY = {"intro": 0, "drop": 1, "outro": 2}
TOLERANCJA_CUE_S = 0.02


def _plik_selekty(root: ET.Element) -> bool:
    """Czy XML wyprodukowała selekta (nowy podpis albo stary 0.4.x)."""
    prod = root.find("PRODUCT")
    if prod is None:
        return False
    if (prod.get("Name") or "").lower() == "selekta":
        return True
    # do 0.4.2 selekta podpisywała się jako rekordbox 6.0.0 / AlphaTheta;
    # prawdziwy rekordbox 6.0 pisał Company „Pioneer DJ"
    return (prod.get("Name") == "rekordbox" and prod.get("Version") == "6.0.0"
            and prod.get("Company") == "AlphaTheta")


def _wartosci_selekty(path: str) -> dict[str, list[float]]:
    """Czasy intro/drop/outro, które selekta policzyła albo wysłała."""
    wynik: dict[str, list[float]] = {n: [] for n in CUE_SELEKTY}
    try:
        from . import cache
        c = cache.get(path, "cues") or {}
    except Exception:  # noqa: BLE001
        c = {}
    for nazwa, pole in (("intro", "intro_end_s"), ("drop", "drop_s"),
                        ("outro", "outro_start_s")):
        if isinstance(c.get(pole), (int, float)):
            wynik[nazwa].append(float(c[pole]))
    for nazwa, czasy in wyslane_cue(path).items():
        wynik.setdefault(nazwa, []).extend(czasy)
    return wynik


def _cue_selekty(z: "Znacznik", plik_selekty: bool, wartosci: dict | None) -> bool:
    """Czy ten znacznik to automatyczne cue selekty, a nie ręczna praca."""
    if CUE_SELEKTY.get(z.nazwa) != z.num or z.typ != "0" or z.koniec_s is not None:
        return False
    if plik_selekty:
        return True
    # XML z rekordboxa, do którego trafiły kiedyś nasze cue: uznajemy je za
    # nasze tylko, gdy stoją DOKŁADNIE tam, gdzie je postawiliśmy. Przesunięte
    # przez DJ-a są już jego pracą.
    return any(abs(z.start_s - t) <= TOLERANCJA_CUE_S
               for t in (wartosci or {}).get(z.nazwa, []))


def _plik_wyslanych() -> str:
    return os.path.join(config.STATE_DIR, "rekordbox-wyslane.json")


def wyslane_cue(path: str) -> dict[str, list[float]]:
    """Czasy cue, które selekta zapisała w eksportach dla tego pliku."""
    try:
        with open(_plik_wyslanych(), encoding="utf-8") as fh:
            dane = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    wpis = dane.get(_klucz(path)) if isinstance(dane, dict) else None
    return wpis if isinstance(wpis, dict) else {}


def zapamietaj_wyslane(cue_na_plik: dict[str, dict[str, float]]) -> None:
    """Zapisz, jakie cue właśnie wysłaliśmy (ścieżka → {nazwa: czas}).

    To „znacznik źródła": po powrocie XML-a z rekordboxa wiemy, które
    intro/drop/outro postawiła selekta, nawet gdy analiza się od tego
    czasu zmieniła. Trzymamy kilka ostatnich wartości na cue.
    """
    if not cue_na_plik:
        return
    try:
        with open(_plik_wyslanych(), encoding="utf-8") as fh:
            dane = json.load(fh)
        if not isinstance(dane, dict):
            dane = {}
    except (OSError, json.JSONDecodeError):
        dane = {}
    for path, cue in cue_na_plik.items():
        wpis = dane.setdefault(_klucz(path), {})
        for nazwa, czas in cue.items():
            lista = [t for t in wpis.get(nazwa, []) if abs(t - czas) > 1e-6]
            wpis[nazwa] = (lista + [round(float(czas), 3)])[-5:]
    try:
        os.makedirs(config.STATE_DIR, exist_ok=True)
        tmp = _plik_wyslanych() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dane, fh, ensure_ascii=False)
        os.replace(tmp, _plik_wyslanych())
    except OSError:
        pass                                   # brak zapisu nie psuje eksportu


def _liczba(value, calkowita=False):
    if value in (None, "", "0.000000"):
        return None if not calkowita else None
    try:
        return int(float(value)) if calkowita else float(value)
    except (TypeError, ValueError):
        return None


def wczytaj_xml(sciezka: str) -> list[WpisRekordbox]:
    """Rozbierz XML wyeksportowany z rekordboxa.

    Automatyczne cue selekty (intro/drop/outro) i jej własna siatka nie
    są ręczną pracą — odsiewamy je, żeby nie zamroziły starej analizy.
    """
    root = ET.parse(sciezka).getroot()
    plik_selekty = _plik_selekty(root)
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
        w.zrodlo = "selekta" if plik_selekty else "rekordbox"
        # siatkę z NASZEGO pliku pomijamy: to stara analiza selekty, nie
        # ręczna korekta w rekordboksie
        tempo = t.find("TEMPO") if not plik_selekty else None
        if tempo is not None:
            w.first_beat_s = _czas(tempo.get("Inizio"))
            if w.bpm is None:
                w.bpm = _liczba(tempo.get("Bpm"))
            b = _liczba(tempo.get("Battito"), calkowita=True)
            w.battito = b if b is not None and 1 <= b <= 4 else 1
            w.tempa = [{"inizio_s": _czas(x.get("Inizio")), "bpm": _liczba(x.get("Bpm")),
                        "metro": x.get("Metro") or "4/4",
                        "battito": _liczba(x.get("Battito"), calkowita=True) or 1}
                       for x in t.findall("TEMPO")]
        wartosci = None
        for m in t.findall("POSITION_MARK"):
            start = _czas(m.get("Start"))
            if start is None:
                continue
            z = Znacznik(
                start_s=start,
                num=_liczba(m.get("Num"), calkowita=True) if m.get("Num") else -1,
                typ=m.get("Type", "0") or "0",
                nazwa=m.get("Name", "") or "",
                koniec_s=_liczba(m.get("End")),
                kolor=_kolor_znacznika(m),
            )
            if CUE_SELEKTY.get(z.nazwa) == z.num and not plik_selekty and wartosci is None:
                wartosci = _wartosci_selekty(w.location) if w.location else {}
            if _cue_selekty(z, plik_selekty, wartosci):
                w.pominiete_cue_selekty += 1
                continue
            w.znaczniki.append(z)
        w.znaczniki.sort(key=lambda z: z.start_s)
        wpisy.append(w)
    return wpisy


def _czas(value) -> float | None:
    """Czas w sekundach — ZERO jest poprawne (cue/kotwica na samym początku)."""
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


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
        if not isinstance(dane, dict):
            return {}
        # stan sprzed normalizacji mógł mieć klucze w NFD
        return {_klucz(k): v for k, v in dane.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _zapisz_stan(dane: dict) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK)


def dla_pliku(path: str) -> dict | None:
    """Dane z rekordboxa zapamiętane dla tego pliku.

    Wpisy zapisane przed rozróżnianiem cue selekty (bez pola „zrodlo")
    czyścimy w locie z naszych intro/drop/outro stojących dokładnie tam,
    gdzie je postawiliśmy.
    """
    return _odfiltruj(path, _wczytaj_stan().get(_klucz(path)))


def wszystkie() -> dict:
    """Cały zapamiętany stan, z odsianymi cue selekty (jak w dla_pliku)."""
    return {k: _odfiltruj(k, v) for k, v in _wczytaj_stan().items()}


def _odfiltruj(path: str, dane: dict | None) -> dict | None:
    if dane and "zrodlo" not in dane and dane.get("znaczniki"):
        wartosci = _wartosci_selekty(path)
        zostaja = []
        for z in dane["znaczniki"]:
            try:
                zn = Znacznik(**{k: z.get(k) for k in ("start_s", "num", "typ",
                                                       "nazwa", "koniec_s", "kolor")
                                 if z.get(k) is not None})
            except TypeError:
                zostaja.append(z)
                continue
            if not _cue_selekty(zn, False, wartosci):
                zostaja.append(z)
        dane = {**dane, "znaczniki": zostaja}
    return dane


def scal(sciezka_xml: str, folder: str) -> dict:
    """Wciągnij XML z rekordboxa i zapamiętaj ręczną pracę użytkownika.

    Nic nie nadpisuje plików ani analiz — zapisuje osobno to, co rekordbox
    wie, żeby EKSPORT mógł to oddać z powrotem zamiast zastąpić własnym
    wyliczeniem.
    """
    wpisy = wczytaj_xml(sciezka_xml)
    stan = _wczytaj_stan()
    dopasowane, nieznane, z_praca, pominiete = 0, [], 0, 0
    for w in wpisy:
        path = dopasuj(w, folder)
        if not path:
            nieznane.append(f"{w.artist} — {w.title}".strip(" —") or w.location)
            continue
        dopasowane += 1
        if w.ma_reczna_prace:
            z_praca += 1
        pominiete += w.pominiete_cue_selekty
        stan[_klucz(path)] = {
            **{k: v for k, v in asdict(w).items()
               if k not in ("znaczniki", "pominiete_cue_selekty")},
            "znaczniki": [asdict(z) for z in w.znaczniki],
        }
    _zapisz_stan(stan)
    return {
        "w_xml": len(wpisy),
        "dopasowane": dopasowane,
        "z_reczna_praca": z_praca,
        "cue_selekty_pominiete": pominiete,
        "plik_selekty": bool(wpisy) and all(w.zrodlo == "selekta" for w in wpisy),
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
    if stan.pop(_klucz(path), None) is None:
        return 0
    _zapisz_stan(stan)
    return 1
