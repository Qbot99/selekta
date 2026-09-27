"""Trwały cache wyników analizy audio.

Analizy (BPM/tonacja/fingerprint/jakość/loudness) liczą się od zera przy
każdym uruchomieniu (~0,25 s/plik). Ten moduł zapamiętuje ich wyniki na
dysku, keyując je odciskiem pliku (abspath + mtime + rozmiar), i sam
unieważnia wpis, gdy plik się zmieni.

Magazyn: ``~/.selekta/cache/``. Każdy ``kind`` (namespace, np. "harmonic",
"quality", "fingerprint", "loudness", "cues") trzyma jeden plik JSON:
``<kind>.json`` dla prostych nazw, a ``k_<md5>.json`` dla nazw zawierających
znaki nietypowe dla nazwy pliku. Prawdziwa nazwa ``kind`` zawsze siedzi też
w środku pliku, więc ``stats()`` raportuje ją niezależnie od nazwy pliku.

Każdy zapis jest atomowy (tmp + ``os.replace``), z unikalną nazwą pliku
tymczasowego, więc równoległe zapisy nie uszkodzą pliku (obowiązuje reguła
"ostatni wygrywa" — bez utraty spójności). Ten katalog jest odrębny od
``~/.selekta/wishlist.json`` i ``radar.json`` — cache ich nie dotyka.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime

CACHE_DIR = os.path.expanduser("~/.selekta/cache")

# Nazwy kind, które bez zmian nadają się na nazwę pliku.
_SAFE_KIND = re.compile(r"^[A-Za-z0-9_-]+$")

# Zarezerwowane klucze w wyniku stats() — nie kolidują z realnymi kind,
# bo kind-namespace'y nie zaczynają się od podkreślenia.
_STATS_BYTES = "_total_bytes"
_STATS_ENTRIES = "_total_entries"


# ---------------------------------------------------------------- klucze

def key_for(path: str) -> str:
    """Zwróć odcisk pliku: md5 z abspath + mtime + rozmiaru.

    Odcisk zmienia się, gdy plik zostanie podmieniony lub dotknięty
    (``touch``), więc sam w sobie unieważnia stare wpisy. Rzuca
    ``OSError`` (np. ``FileNotFoundError``), gdy pliku nie da się
    zstatować.
    """
    abspath = os.path.abspath(path)
    st = os.stat(abspath)
    raw = f"{abspath}\x00{st.st_mtime_ns}\x00{st.st_size}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- ścieżki

def _kind_file(kind: str) -> str:
    """Ścieżka pliku JSON dla danego ``kind`` (deterministyczna)."""
    if _SAFE_KIND.match(kind):
        name = f"{kind}.json"
    else:
        digest = hashlib.md5(kind.encode("utf-8")).hexdigest()
        name = f"k_{digest}.json"
    return os.path.join(CACHE_DIR, name)


def _load_store(kind: str) -> dict:
    """Wczytaj kopertę dla ``kind``: {"kind": str, "entries": {...}}.

    Brak pliku lub uszkodzony JSON traktujemy jak pusty magazyn.
    """
    try:
        with open(_kind_file(kind), encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"kind": kind, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"kind": kind, "entries": {}}
    data.setdefault("kind", kind)
    return data


def _save_store(kind: str, store: dict) -> None:
    """Zapisz kopertę atomowo (tmp + ``os.replace``)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    target = _kind_file(kind)
    tmp = f"{target}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    finally:
        # Sprzątamy tmp, gdyby replace się nie powiódł.
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------- API

# Wersja algorytmu dla każdego rodzaju analizy. Podbicie numeru unieważnia
# wyniki policzone starą metodą — bez tego zmiana algorytmu zostawiałaby
# nieaktualne dane na zawsze, bo odcisk zależy tylko od PLIKU, nie od kodu.
# Historia: cues 2 — kotwica beatgridu liczona z fazy prążka tempa zamiast
# z pierwszego napotkanego onsetu (przesunięcie sięgało pół uderzenia).
# Podbicie numeru unieważnia stare wpisy danego rodzaju — po zmianie
# algorytmu użytkownik nie może latami oglądać wyników sprzed poprawki.
# 2.09.2026: harmonic (nowe BPM: gęsta interpolacja + strażnik oktawy),
# tempo (liczone z BPM), quality (dyskryminator transkodu, bitrate),
# energia (naprawiona jasność, gęstość z bramką okresowości).
# cues 3: siatka na stopie (siatka.py) + Battito — stare kotwice były o pół bitu obok
WERSJE = {"cues": 3, "harmonic": 2, "tempo": 2, "quality": 2, "energia": 2}


def wersja(kind: str) -> int:
    return WERSJE.get(kind, 1)


def get(path: str, kind: str) -> dict | None:
    """Zwróć zapisane dane dla (plik, kind) albo ``None``.

    ``None`` gdy: brak wpisu, plik zniknął, albo plik się zmienił —
    tzn. bieżące mtime/rozmiar różnią się od zapisanych.
    """
    try:
        st = os.stat(os.path.abspath(path))
    except OSError:
        return None
    fingerprint = key_for(path)
    store = _load_store(kind)
    entry = store["entries"].get(fingerprint)
    if entry is None:
        return None
    # Dodatkowy strażnik na wypadek kolizji md5 / ręcznej edycji pliku.
    if entry.get("mtime_ns") != st.st_mtime_ns or entry.get("size") != st.st_size:
        return None
    if entry.get("wersja", 1) != wersja(kind):
        return None                    # policzone starszą wersją algorytmu
    data = entry.get("data")
    return data if isinstance(data, dict) else None


def put(path: str, kind: str, data: dict) -> None:
    """Zapisz ``data`` dla (plik, kind); nadpisz starszy wpis dla tego pliku.

    Stare odciski tej samej ścieżki (sprzed zmiany pliku) są usuwane, więc
    magazyn nie puchnie od nieaktualnych wpisów. Rzuca ``OSError``, gdy
    pliku nie da się zstatować, oraz ``TypeError``/``ValueError``, gdy
    ``data`` nie jest serializowalne do JSON.
    """
    abspath = os.path.abspath(path)
    st = os.stat(abspath)
    fingerprint = key_for(path)
    entry = {
        "path": abspath,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "wersja": wersja(kind),
        "data": data,
    }
    store = _load_store(kind)
    entries = store["entries"]
    # Usuń nieaktualne odciski tej samej ścieżki.
    for k in [k for k, e in entries.items()
              if isinstance(e, dict) and e.get("path") == abspath and k != fingerprint]:
        del entries[k]
    entries[fingerprint] = entry
    store["kind"] = kind
    _save_store(kind, store)


def clear(kind: str | None = None) -> int:
    """Wyczyść cały cache albo jeden ``kind``; zwróć liczbę usuniętych wpisów.

    Usuwa wyłącznie pliki JSON z ``~/.selekta/cache/`` — nic poza tym
    katalogiem (wishlist.json/radar.json są bezpieczne).
    """
    if not os.path.isdir(CACHE_DIR):
        return 0
    if kind is not None:
        path = _kind_file(kind)
        if not os.path.exists(path):
            return 0
        count = len(_load_store(kind)["entries"])
        os.remove(path)
        return count
    removed = 0
    for name in os.listdir(CACHE_DIR):
        if not name.endswith(".json"):
            continue
        full = os.path.join(CACHE_DIR, name)
        try:
            with open(full, encoding="utf-8") as fh:
                data = json.load(fh)
            removed += len(data.get("entries", {}))
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass
        os.remove(full)
    return removed


def stats() -> dict:
    """Statystyki cache'u: {kind: liczba_wpisów, ...} + rozmiary.

    Oprócz liczników per-kind zwraca zarezerwowane klucze
    ``_total_entries`` (suma wpisów) i ``_total_bytes`` (łączny rozmiar
    plików cache na dysku).
    """
    result: dict = {}
    total_entries = 0
    total_bytes = 0
    if not os.path.isdir(CACHE_DIR):
        result[_STATS_ENTRIES] = 0
        result[_STATS_BYTES] = 0
        return result
    for name in os.listdir(CACHE_DIR):
        if not name.endswith(".json"):
            continue
        full = os.path.join(CACHE_DIR, name)
        try:
            total_bytes += os.path.getsize(full)
        except OSError:
            pass
        try:
            with open(full, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        entries = data.get("entries", {})
        n = len(entries) if isinstance(entries, dict) else 0
        kind = data.get("kind") or os.path.splitext(name)[0]
        result[kind] = result.get(kind, 0) + n
        total_entries += n
    result[_STATS_ENTRIES] = total_entries
    result[_STATS_BYTES] = total_bytes
    return result
