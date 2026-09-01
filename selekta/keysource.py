"""Oficjalne BPM i tonacja z Beatportu jako źródło rozstrzygające.

Nasz detektor (``selekta.harmonic``) jest dobry, ale przy niskiej pewności
potrafi pomylić durowość z molowością. Beatport publikuje BPM i klucz
podane przez wydawcę — to praktyczny „ground truth". Ten moduł dociąga te
dane i pozwala nimi zweryfikować wynik detektora.

Transport: strona wyszukiwarki Beatportu oraz strony pojedynczych utworów
osadzają cały stan w JSON-ie ``__NEXT_DATA__``. Zwykłe ``requests`` (z
przeglądarkowym User-Agentem) przechodzi — w przeciwieństwie do systemowego
curla, który dostaje ścianę Cloudflare („Just a moment"). Dlatego pobieramy
przez ``requests`` i traktujemy stronę-wyzwanie Cloudflare jak brak danych.

Klucz odczytujemy najpierw ze strony utworu, gdzie Beatport podaje gotowy
kod Camelot (``camelot_number`` + ``camelot_letter``) oraz nazwę muzyczną
(np. „Gb Major"). Gdy strona utworu zawiedzie, degradujemy się do danych
z wyszukiwarki (``key_name`` + ``bpm``) i przeliczamy nazwę na Camelot
sami (:func:`to_camelot`). Każdy błąd sieci/parsowania jest łapany i kończy
się zwróceniem ``None`` — moduł nigdy nie rzuca wyjątkiem w stronę wołającego.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote_plus

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- stałe

UA_STRING = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
UA = {
    "User-Agent": UA_STRING,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 15
MIN_GAP_S = 1.0        # uprzejmy odstęp między żądaniami HTTP
LOW_CONF = 0.5         # poniżej tej pewności detektora ufamy Beatportowi
BPM_TOL = 1.0          # różnica BPM > tej wartości => przyjmij BPM z Beatportu

_last_request = 0.0

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# Pełne koło kwintowe Camelot (te same wartości co w selekta.harmonic).
# Nuty trzymamy w notacji krzyżykowej; bemole normalizujemy niżej.
_CAMELOT_MAJOR = {"B": "1B", "F#": "2B", "C#": "3B", "G#": "4B", "D#": "5B",
                  "A#": "6B", "F": "7B", "C": "8B", "G": "9B", "D": "10B",
                  "A": "11B", "E": "12B"}
_CAMELOT_MINOR = {"G#": "1A", "D#": "2A", "A#": "3A", "F": "4A", "C": "5A",
                  "G": "6A", "D": "7A", "A": "8A", "E": "9A", "B": "10A",
                  "F#": "11A", "C#": "12A"}

# Enharmonia: sprowadzamy każdą nazwę nuty do jednej reprezentacji
# krzyżykowej używanej w tablicach powyżej.
_ENHARMONIC = {
    "DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
    "CB": "B", "FB": "E", "E#": "F", "B#": "C",
    "C#": "C#", "D#": "D#", "F#": "F#", "G#": "G#", "A#": "A#",
    "C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "B",
}


# ---------------------------------------------------------------- pomocnicze

def _norm(s: str | None) -> str:
    """Znormalizuj napis do porównań: pojedyncze spacje, casefold."""
    return " ".join((s or "").split()).casefold()


def _strip_paren(s: str) -> str:
    """Usuń nawiasy (np. '(feat. X)', '(Extended Mix)') dla dopasowania tytułu."""
    return re.sub(r"\([^)]*\)", " ", s or "")


def _slug(name: str) -> str:
    """Zamień nazwę na fragment sluga URL-a (Beatport i tak routuje po ID)."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").casefold()).strip("-")
    return s or "track"


def _challenged(text: str) -> bool:
    """Wykryj stronę-wyzwanie Cloudflare zamiast prawdziwej treści."""
    head = text[:4000].lower()
    return "just a moment" in head or "cf-browser-verification" in head


def _throttle() -> None:
    """Prosty globalny rate-limit między żądaniami."""
    global _last_request
    wait = MIN_GAP_S - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _fetch_next_data(url: str) -> dict | None:
    """Pobierz URL i zwróć sparsowany JSON ``__NEXT_DATA__`` albo ``None``.

    Łapie każdy wyjątek sieciowy, wykrywa ścianę Cloudflare i nieczytelny
    JSON — w każdym z tych przypadków zwraca ``None`` (łagodna degradacja).
    """
    _throttle()
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.warning("keysource: błąd sieci przy %s (%s)", url, exc)
        return None
    if r.status_code != 200:
        log.warning("keysource: %s -> HTTP %s", url, r.status_code)
        return None
    if _challenged(r.text):
        log.warning("keysource: Cloudflare zablokował %s", url)
        return None
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        log.warning("keysource: brak __NEXT_DATA__ w %s", url)
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("keysource: nieczytelny JSON __NEXT_DATA__ w %s", url)
        return None


# ---------------------------------------------------------------- Camelot

def to_camelot(key_name: str) -> str | None:
    """Przelicz muzyczną nazwę tonacji na kod Camelot.

    Rozumie warianty zapisu: „A minor", „A min", „Am", „F# major",
    „F#maj", „Gb Major", „Bbm", a także same nazwy jak „C" (traktowane
    jako dur). Bemole są sprowadzane enharmonicznie do krzyżyków
    (Gb=F#=2B). Zwraca ``None``, gdy napisu nie da się rozpoznać.
    """
    if not key_name:
        return None
    s = key_name.strip()

    # nuta: litera A-G z opcjonalnym krzyżykiem/bemolem (# ♯ b ♭)
    m = re.match(r"^\s*([A-Ga-g])\s*([#♯b♭]?)", s)
    if not m:
        return None
    letter = m.group(1).upper()
    accidental = m.group(2).replace("♯", "#").replace("♭", "b")
    note = _ENHARMONIC.get((letter + accidental).upper())
    if note is None:
        return None

    # tryb: „min"/„maj" w reszcie; samo „m" => moll; pusta reszta => dur.
    # Niepusta, nierozpoznawalna reszta (np. „garbage") => to nie tonacja.
    rest = s[m.end():].strip().lower()
    if rest == "":
        mode = "major"          # sam symbol tonacji, np. „C" (konwencja tagów)
    elif "min" in rest or rest == "m":
        mode = "minor"
    elif "maj" in rest:
        mode = "major"
    else:
        return None

    table = _CAMELOT_MINOR if mode == "minor" else _CAMELOT_MAJOR
    return table.get(note)


def _camelot_from_key(key: Any) -> tuple[str | None, str | None]:
    """Wyłuskaj (camelot, nazwa_muzyczna) z pola ``key`` obiektu utworu.

    Obsługuje trzy warianty spotykane w danych Beatportu:
    - słownik z gotowym ``camelot_number``/``camelot_letter`` i ``name``,
    - słownik tylko z ``name`` (przeliczamy sami),
    - napis w rodzaju „F Minor".
    """
    if isinstance(key, dict):
        name = key.get("name")
        num = key.get("camelot_number")
        letter = key.get("camelot_letter")
        if num is not None and letter:
            return f"{num}{str(letter).upper()}", name
        if name:
            return to_camelot(name), name
        return None, None
    if isinstance(key, str):
        return to_camelot(key), key
    return None, None


# ---------------------------------------------------------------- wyszukiwarka

def _iter_search_tracks(data: dict) -> list[dict]:
    """Znajdź listę utworów w drzewie ``__NEXT_DATA__`` wyszukiwarki."""
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        return []
    for q in queries:
        d = (q.get("state") or {}).get("data")
        if isinstance(d, dict) and isinstance(d.get("tracks"), dict):
            rows = d["tracks"].get("data")
            if isinstance(rows, list):
                return rows
    return []


def _track_artists(track: dict) -> str:
    names = [a.get("artist_name", "") for a in (track.get("artists") or [])
             if isinstance(a, dict)]
    return _norm(", ".join(names))


def _match_track(tracks: list[dict], artist: str, title: str) -> dict | None:
    """Wybierz utwór najlepiej pasujący do (artist, title).

    Wymaga sygnału zarówno w tytule, jak i w wykonawcy — dzięki temu przy
    zapytaniu „Pegassi Flashback" nie wygrywa cudze „... - Flashback".
    Remisy rozstrzyga kolejność Beatportu (trafność). ``None`` gdy nic
    nie spełnia obu warunków.
    """
    qt = _norm(_strip_paren(title))
    qa_tokens = [_norm(t) for t in re.split(r"[,&/]| x | vs | feat\.? | ft\.? ",
                                            artist) if t.strip()]
    best: tuple[int, int, dict] | None = None
    for idx, t in enumerate(tracks):
        tname = t.get("track_name") or t.get("name") or ""
        tt = _norm(_strip_paren(tname))
        if not tt or not qt:
            continue
        if qt == tt:
            title_score = 3
        elif qt in tt or tt in qt:
            title_score = 2
        else:
            continue  # brak sygnału w tytule
        arts = _track_artists(t)
        if not any(tok and tok in arts for tok in qa_tokens):
            continue  # brak sygnału w wykonawcy
        total = title_score + 3
        if best is None or total > best[0]:
            best = (total, idx, t)
    return best[2] if best else None


# ---------------------------------------------------------------- strona utworu

def _extract_track_node(data: dict, track_id: int | None) -> dict | None:
    """Znajdź na stronie utworu węzeł z ``bpm`` i słownikowym ``key``.

    Preferuje węzeł o zgodnym ``id``/``track_id``; w razie braku bierze
    pierwszy kandydat ze słownikowym kluczem (bogatszym, z Camelotem).
    """
    rich: list[dict] = []
    plain: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "bpm" in node and "key" in node:
                (rich if isinstance(node.get("key"), dict) else plain).append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    if track_id is not None:
        for n in rich:
            if n.get("id") == track_id or n.get("track_id") == track_id:
                return n
    if rich:
        return rich[0]
    if track_id is not None:
        for n in plain:
            if n.get("id") == track_id or n.get("track_id") == track_id:
                return n
    return plain[0] if plain else None


# ---------------------------------------------------------------- API publiczne

def lookup(artist: str, title: str) -> dict | None:
    """Pobierz oficjalne BPM i tonację utworu z Beatportu.

    Kroki: wyszukaj frazę „artist title", dopasuj pierwszy pasujący utwór,
    wejdź na jego stronę i odczytaj BPM oraz tonację z osadzonego JSON-a
    (Beatport podaje gotowy Camelot i nazwę muzyczną). Gdy strona utworu
    zawiedzie, użyj danych z wyszukiwarki.

    Zwraca słownik::

        {"bpm": int|None, "key_camelot": str|None, "key_name": str|None,
         "url": str, "source": "beatport"}

    albo ``None``, gdy nie ma trafienia lub wystąpił błąd sieci.
    """
    query = f"{artist} {title}".strip()
    data = _fetch_next_data(
        f"https://www.beatport.com/search?q={quote_plus(query)}"
    )
    if data is None:
        return None
    tracks = _iter_search_tracks(data)
    if not tracks:
        log.warning("keysource: brak wyników wyszukiwania dla '%s'", query)
        return None

    track = _match_track(tracks, artist, title)
    if track is None:
        log.warning("keysource: brak dopasowania dla '%s - %s'", artist, title)
        return None

    track_id = track.get("track_id") or track.get("id")
    name = track.get("track_name") or track.get("name") or title
    url = f"https://www.beatport.com/track/{_slug(name)}/{track_id}"

    # dane zapasowe prosto z wyszukiwarki (na wypadek blokady strony utworu)
    bpm = track.get("bpm")
    key_camelot = to_camelot(track.get("key_name")) if track.get("key_name") else None
    key_name = track.get("key_name")

    # źródło rozstrzygające: strona utworu (gotowy Camelot z Beatportu)
    page = _fetch_next_data(url) if track_id else None
    if page is not None:
        node = _extract_track_node(page, track_id)
        if node is not None:
            if node.get("bpm") is not None:
                bpm = node.get("bpm")
            cam, kname = _camelot_from_key(node.get("key"))
            if cam is not None:
                key_camelot = cam
            if kname:
                key_name = kname

    try:
        bpm_int = int(round(float(bpm))) if bpm is not None else None
    except (TypeError, ValueError):
        bpm_int = None

    return {
        "bpm": bpm_int,
        "key_camelot": key_camelot,
        "key_name": key_name,
        "url": url,
        "source": "beatport",
    }


def reconcile(
    detected_camelot: str,
    detected_bpm: float,
    detected_conf: float,
    official: dict | None,
) -> tuple[str, float, str]:
    """Uzgodnij wynik detektora z oficjalnymi danymi Beatportu.

    Reguła:

    - Gdy brak ``official`` — zwróć wykryte wartości z notatką „tylko detektor".
    - Gdy ``official`` istnieje i (pewność detektora jest niska LUB Camelot
      detektora różni się od oficjalnego) — przyjmij tonację z Beatportu
      i zaznacz to w notatce („z Beatport").
    - BPM bierzemy z Beatportu, gdy różni się od wykrytego o więcej niż 1.

    Zwraca ``(camelot, bpm, note_po_polsku)``.
    """
    det_cam = (detected_camelot or "").upper()

    if not official:
        return det_cam or "?", float(detected_bpm), "tylko detektor (brak danych z Beatport)"

    off_cam = (official.get("key_camelot") or "").upper() or None
    off_bpm = official.get("bpm")

    # --- tonacja ---
    note_parts: list[str] = []
    if off_cam is None:
        camelot = det_cam or "?"
        note_parts.append(f"tonacja z detektora {camelot} (Beatport bez tonacji)")
    elif detected_conf < LOW_CONF or det_cam != off_cam:
        camelot = off_cam
        if det_cam and det_cam != off_cam:
            note_parts.append(
                f"tonacja z Beatport: {off_cam} (detektor sugerował {det_cam})"
            )
        else:
            # zgodne, ale niska pewność -> potwierdzenie z Beatportu
            note_parts.append(f"tonacja z Beatport: {off_cam} (potwierdzona)")
    else:
        camelot = det_cam
        note_parts.append(f"tonacja {det_cam} zgodna z Beatport")

    # --- BPM ---
    if off_bpm is not None and abs(float(off_bpm) - float(detected_bpm)) > BPM_TOL:
        bpm = float(off_bpm)
        note_parts.append(
            f"BPM z Beatport: {off_bpm:g} (detektor {float(detected_bpm):g})"
        )
    else:
        bpm = float(detected_bpm)
        if off_bpm is not None:
            note_parts.append(f"BPM {bpm:g} zgodny z Beatport")

    return camelot, bpm, "; ".join(note_parts)
