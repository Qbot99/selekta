"""„Sprawdź wszystkie”: brakujący artysta/tytuł z nazwy pliku + okładki z iTunes.

Zasady (te same co przy pojedynczych akcjach, tylko hurtem):

* tagi: uzupełniamy WYŁĄCZNIE puste pola — istniejący artysta czy tytuł
  zostaje, nawet jeśli nazwa pliku mówi co innego. Z nazwy bierzemy tylko
  pewny wzór „Artysta - Tytuł” (z separatorem); nazwy bez separatora
  („Aquagen Hard To Say I'm Sorry”) pokazujemy jako niepewne i nie ruszamy;
* każdy zapis tagów trafia do dziennika, więc całą partię da się cofnąć;
* analizy (BPM, siatka, cue) przechodzą przez zapis (``tagger.zachowaj_analizy``);
* okładka tylko z iTunes i tylko przy zgodnym artyście i tytule
  (``covers.uzupelnij``) — istniejących okładek nie podmieniamy;
* iTunes przyjmuje ok. 20 zapytań na minutę, więc okładki idą powoli, w tle.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from . import config, covers, health, matcher, tagfix, tagger

DZIENNIK = os.path.join(config.STATE_DIR, "porzadek_dziennik.json")
ODSTEP_ITUNES_S = 3.2          # < 20 zapytań/min

_lock = threading.Lock()
_STAN: dict = {"w_toku": False}
_PRZERWIJ = threading.Event()


# „055f8a1ba1 - Artysta - Tytuł.mp3”: kod na początku nazwy (kopie odsłuchowe)
_KOD = re.compile(r"^\s*[0-9a-f]{8,12}\s*-\s*", re.I)
# dopiski z YouTube i wytwórni — nie należą do tytułu (wersja miksu należy)
_SMIECI = re.compile(
    r"\s*[\[(]\s*(?:official\s*)?(?:lyrics?|lyric\s*video|music\s*video|video|audio|"
    r"visuali[sz]er|official|hq|hd|4k|ultra\s*records|house|techno|premiere|"
    r"official\s*(?:lyric\s*)?(?:video|audio))\s*[\])]", re.I)
_YOUTUBE = re.compile(r"ytdown|youtube|\b128k\b|\bmedia\b.*\b\d{3}\b", re.I)


def oczysc_nazwe(stem: str) -> tuple[str, bool]:
    """Nazwa pliku bez kodu na początku i śmieci; drugie pole: czy w ogóle się nadaje."""
    s = _KOD.sub("", stem)
    s = _SMIECI.sub("", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    s = re.sub(r"\s+([)\]])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_")
    return s, not _YOUTUBE.search(s)


def _domkniete(tekst: str) -> bool:
    return tekst.count("(") == tekst.count(")") and tekst.count("[") == tekst.count("]")


def propozycja(path: str) -> dict | None:
    """Co dopisać do tagów pliku — albo None, gdy niczego nie brakuje."""
    artist, title = health.czytaj_tagi(path)
    artist, title = (artist or "").strip(), (title or "").strip()
    if artist and title:
        return None
    stem, nadaje = oczysc_nazwe(os.path.splitext(os.path.basename(path))[0])
    kand = tagfix.name_candidates(stem)
    czysty = tagfix.clean_stem(stem) or stem
    # pewne: dokładnie jeden separator, domknięte nawiasy (nie ucięta nazwa)
    # i prawdziwy utwór, nie efekt dźwiękowy
    czas = matcher._file_tokens(path)[1]
    pewne = (nadaje and bool(kand) and czysty.count(" - ") == 1 and _domkniete(czysty)
             and (czas is None or czas >= 60))
    a_nowy, t_nowy = kand[0] if kand else ("", "")
    # „Artysta - Artysta - Tytuł”: powtórzony artysta nie należy do tytułu
    if a_nowy and t_nowy.lower().startswith(a_nowy.lower()):
        t_nowy = t_nowy[len(a_nowy):].lstrip(" -–—").strip() or t_nowy
    return {"path": path, "artist_teraz": artist, "title_teraz": title,
            "artist": artist or a_nowy, "title": title or t_nowy,
            "pewne": pewne and bool(artist or a_nowy) and bool(title or t_nowy)}


def plan(folder: str) -> dict:
    """Podgląd: czego brakuje w całej bibliotece. Niczego nie zapisuje."""
    folder = os.path.abspath(folder)
    pliki = matcher.audio_files(folder)
    tagi, bez_okladki = [], []
    for p in pliki:
        pr = propozycja(p)
        if pr:
            pr["rel"] = os.path.relpath(p, folder)
            tagi.append(pr)
        try:
            if not covers.embedded_art(p):
                bez_okladki.append(os.path.relpath(p, folder))
        except Exception:                       # noqa: BLE001 — nieczytelny plik
            bez_okladki.append(os.path.relpath(p, folder))
    return {"utworow": len(pliki), "tagi": tagi,
            "tagi_pewne": sum(1 for t in tagi if t["pewne"]),
            "bez_okladki": bez_okladki}


def _dopisz_dziennik(partia: dict) -> None:
    try:
        with open(DZIENNIK, encoding="utf-8") as fh:
            dane = json.load(fh)
        if not isinstance(dane, list):
            dane = []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        dane = []
    dane.append(partia)
    os.makedirs(os.path.dirname(DZIENNIK), exist_ok=True)
    tmp = DZIENNIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane[-20:], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, DZIENNIK)


def uzupelnij_tagi(folder: str, postep=None) -> dict:
    """Dopisz brakujące pola z pewnych nazw plików. Zwraca partię dziennika."""
    folder = os.path.abspath(folder)
    zmiany, bledy = [], []
    pliki = matcher.audio_files(folder)
    for i, p in enumerate(pliki):
        if postep:
            postep("tagi", i + 1, len(pliki))
        pr = propozycja(p)
        if not pr or not pr["pewne"]:
            continue
        nowy_a = pr["artist"] if not pr["artist_teraz"] else None
        nowy_t = pr["title"] if not pr["title_teraz"] else None
        try:
            with tagger.zachowaj_analizy(p):
                tagger._zapisz(p, nowy_a, nowy_t, None)
            zmiany.append({"path": p, "artist": pr["artist_teraz"], "title": pr["title_teraz"],
                           "nowy_artist": pr["artist"], "nowy_title": pr["title"]})
        except Exception as exc:                # noqa: BLE001 — jeden plik nie zatrzymuje reszty
            bledy.append(f"{os.path.basename(p)}: {exc}")
    partia = {"kiedy": time.time(), "zmiany": zmiany}
    if zmiany:
        _dopisz_dziennik(partia)
    return {"zapisane": len(zmiany), "bledy": bledy[:20]}


def cofnij_tagi() -> dict:
    """Przywróć tagi sprzed ostatniej partii (puste pola znów puste)."""
    try:
        with open(DZIENNIK, encoding="utf-8") as fh:
            dane = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        dane = []
    if not dane:
        raise ValueError("nie ma czego cofać")
    partia = dane.pop()
    przywrocone = 0
    for z in partia.get("zmiany", []):
        p = z["path"]
        if not os.path.isfile(p):
            continue
        try:
            with tagger.zachowaj_analizy(p):
                tagger._zapisz(p, z["artist"], z["title"], None)
            przywrocone += 1
        except Exception:                       # noqa: BLE001
            continue
    tmp = DZIENNIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, DZIENNIK)
    return {"przywrocone": przywrocone}


def uzupelnij_okladki(folder: str, postep=None, przerwij=None, kopie=None) -> dict:
    """Okładki z iTunes dla plików bez okładki (po tagach — więc po uzupełnieniu)."""
    folder = os.path.abspath(folder)
    pliki = [p for p in matcher.audio_files(folder) if not covers.embedded_art(p)]
    dodane, brak, bledy = 0, [], []
    for i, p in enumerate(pliki):
        if przerwij is not None and przerwij.is_set():
            break
        if postep:
            postep("okładki", i + 1, len(pliki))
        w = covers.uzupelnij(p, kopie=kopie(p) if kopie else [])
        if w["status"] == "dodano":
            dodane += 1
        elif w["status"] == "brak":
            brak.append(os.path.relpath(p, folder))
        elif w["status"] == "blad":
            bledy.append(f"{os.path.basename(p)}: {w['opis']}")
        if w["status"] in ("dodano", "brak") and i + 1 < len(pliki):
            time.sleep(ODSTEP_ITUNES_S)
    return {"dodane": dodane, "brak": brak[:200], "bez_okladki": len(pliki),
            "bledy": bledy[:20]}


# ------------------------------------------------------------ praca w tle

def stan() -> dict:
    with _lock:
        return dict(_STAN)


def start(folder: str, tagi: bool = True, okladki: bool = True, kopie=None) -> dict:
    with _lock:
        if _STAN.get("w_toku"):
            return dict(_STAN)
        _PRZERWIJ.clear()
        _STAN.clear()
        _STAN.update({"w_toku": True, "etap": "tagi" if tagi else "okładki",
                      "zrobione": 0, "wszystkie": 0, "start": time.time()})

    def postep(etap, z, w):
        with _lock:
            _STAN.update(etap=etap, zrobione=z, wszystkie=w)

    def praca():
        wynik = {}
        try:
            if tagi:
                wynik["tagi"] = uzupelnij_tagi(folder, postep)
            if okladki and not _PRZERWIJ.is_set():
                wynik["okladki"] = uzupelnij_okladki(folder, postep, _PRZERWIJ, kopie)
            with _lock:
                _STAN.update(w_toku=False, wynik=wynik, przerwany=_PRZERWIJ.is_set(),
                             koniec=time.time())
        except Exception as exc:                # noqa: BLE001
            with _lock:
                _STAN.update(w_toku=False, blad=str(exc), wynik=wynik)

    threading.Thread(target=praca, daemon=True, name="porzadek").start()
    return stan()


def przerwij() -> None:
    _PRZERWIJ.set()
