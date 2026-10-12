"""Trwały cache wyników analizy audio.

Analizy (BPM/tonacja/fingerprint/jakość/loudness) liczą się od zera przy
każdym uruchomieniu (~0,25 s/plik). Ten moduł zapamiętuje ich wyniki na
dysku, keyując je odciskiem TREŚCI pliku (rozmiar + skrót początku, końca
i próbek ze środka), i sam unieważnia wpis, gdy treść się zmieni.

Dlaczego treść, a nie ścieżka: kopie utworów w folderach setów i playlist
mają inne ścieżki i daty, a ten sam dźwięk. Przy kluczu ścieżka+mtime każda
kopia liczyła się od nowa (eksport 6 utworów z kreatora: 7 minut).

Magazyn: ``~/.selekta/cache/``. Każdy ``kind`` (namespace, np. "harmonic",
"quality", "fingerprint", "loudness", "cues") trzyma jeden plik JSON:
``<kind>.json`` dla prostych nazw, a ``k_<md5>.json`` dla nazw zawierających
znaki nietypowe dla nazwy pliku. Prawdziwa nazwa ``kind`` zawsze siedzi też
w środku pliku, więc ``stats()`` raportuje ją niezależnie od nazwy pliku.

Każdy zapis jest atomowy (tmp + ``os.replace``), a cały cykl
odczyt–modyfikacja–zapis trzyma blokadę pliku (``fcntl.flock``), więc
równoległe zapisy z wątków i procesów (serwer, obserwator, CLI) nie gubią
sobie nawzajem wpisów — wcześniej ginęła ich połowa. Ten katalog jest odrębny
od ``~/.selekta/wishlist.json`` i ``radar.json`` — cache ich nie dotyka.
"""
from __future__ import annotations

import contextlib
import fcntl
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

# Format magazynu: 2 = klucz z treści pliku. Magazyn w starszym formacie
# (klucz ścieżka+mtime) jest przy pierwszym odczycie przepisywany na nowe
# klucze, żeby po aktualizacji nie liczyć biblioteki od zera.
FORMAT = 2
_BLOK = 64 * 1024            # początek i koniec pliku
_PROBKI = 8                  # dodatkowe 4-kilobajtowe próbki ze środka
_PAMIEC_KLUCZY: dict[tuple, str] = {}


def key_for(path: str) -> str:
    """Zwróć odcisk TREŚCI pliku: md5 z rozmiaru, początku, końca i próbek
    ze środka.

    Ten sam plik pod inną ścieżką (kopia w folderze setu) ma ten sam
    odcisk; zmiana treści — nowy. Sama zmiana daty (``touch``) nie zmienia
    wyniku analizy, więc nie unieważnia wpisu. Rzuca ``OSError`` (np.
    ``FileNotFoundError``), gdy pliku nie da się odczytać.
    """
    abspath = os.path.abspath(path)
    st = os.stat(abspath)
    # ctime zmienia się przy KAŻDYM zapisie i przy utime, więc pamięć
    # w procesie nie poda starego klucza po podmianie treści
    memo = (abspath, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
    klucz = _PAMIEC_KLUCZY.get(memo)
    if klucz is not None:
        return klucz
    h = hashlib.md5(f"{st.st_size}\x00".encode())
    with open(abspath, "rb") as fh:
        h.update(fh.read(_BLOK))
        if st.st_size > 2 * _BLOK:
            for i in range(1, _PROBKI + 1):
                fh.seek(st.st_size * i // (_PROBKI + 1))
                h.update(fh.read(4096))
            fh.seek(st.st_size - _BLOK)
            h.update(fh.read(_BLOK))
    klucz = h.hexdigest()
    if len(_PAMIEC_KLUCZY) > 50_000:
        _PAMIEC_KLUCZY.clear()
    _PAMIEC_KLUCZY[memo] = klucz
    return klucz


# ---------------------------------------------------------------- ścieżki

def _kind_file(kind: str) -> str:
    """Ścieżka pliku JSON dla danego ``kind`` (deterministyczna)."""
    if _SAFE_KIND.match(kind):
        name = f"{kind}.json"
    else:
        digest = hashlib.md5(kind.encode("utf-8")).hexdigest()
        name = f"k_{digest}.json"
    return os.path.join(CACHE_DIR, name)


@contextlib.contextmanager
def _blokada(kind: str):
    """Wyłączny dostęp do magazynu (także między procesami).

    Blokujemy sam katalog cache — bez dodatkowych plików-zamków obok
    magazynów. Jedna blokada na wszystkie rodzaje wystarcza: cykl
    odczyt–modyfikacja–zapis trwa milisekundy.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd = os.open(CACHE_DIR, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                     # zamknięcie zwalnia blokadę


def _read_store(kind: str) -> dict:
    try:
        with open(_kind_file(kind), encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"kind": kind, "format": FORMAT, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"kind": kind, "format": FORMAT, "entries": {}}
    data.setdefault("kind", kind)
    return data


def _migruj(store: dict) -> dict:
    """Przepisz wpisy ze starego klucza (ścieżka+mtime) na klucz treści.

    Przenosimy tylko wpisy, których plik nadal leży pod tą samą ścieżką
    z tą samą datą i rozmiarem — tylko wtedy wiadomo, że wynik dotyczy
    obecnej treści. Reszta przepada (i tak byłaby nieaktualna).
    """
    nowe: dict = {}
    for entry in store.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        p = entry.get("path")
        try:
            st = os.stat(p)
        except (OSError, TypeError):
            continue
        if st.st_mtime_ns != entry.get("mtime_ns") or st.st_size != entry.get("size"):
            continue
        try:
            nowe[key_for(p)] = {**entry, "paths": [p]}
        except OSError:
            continue
    store["entries"] = nowe
    store["format"] = FORMAT
    return store


def _load_store(kind: str) -> dict:
    """Wczytaj kopertę dla ``kind``: {"kind", "format", "entries": {...}}.

    Brak pliku lub uszkodzony JSON traktujemy jak pusty magazyn. Magazyn
    w starym formacie jest raz migrowany i zapisywany (pod blokadą).
    """
    data = _read_store(kind)
    if data.get("format", 1) >= FORMAT:
        return data
    with _blokada(kind):
        data = _read_store(kind)          # ktoś mógł zmigrować w międzyczasie
        if data.get("format", 1) < FORMAT:
            data = _migruj(data)
            if os.path.exists(_kind_file(kind)):
                _save_store(kind, data)
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
# 11.10.2026: integrity 2 — porównanie z długością z nagłówka (stare „ok”
# przepuszczało ucięte MP3); energia 3 — energia bezwzględna (porównywalna
# między utworami), frazy liczone przy odczycie z aktualnej siatki;
# cues 4 — koniec intra i początek outra na granicach fraz; quality 3 —
# widmo z ramek bez przesteru, ślady kodeka, ALAC jako bezstratny
WERSJE = {"cues": 4, "harmonic": 2, "tempo": 2, "quality": 3, "energia": 3,
          "integrity": 2}


def wersja(kind: str) -> int:
    return WERSJE.get(kind, 1)


def get(path: str, kind: str) -> dict | None:
    """Zwróć zapisane dane dla (treść pliku, kind) albo ``None``.

    ``None`` gdy: brak wpisu, plik zniknął, treść się zmieniła albo wynik
    policzono starszą wersją algorytmu.
    """
    try:
        st = os.stat(os.path.abspath(path))
        fingerprint = key_for(path)
    except OSError:
        return None
    store = _load_store(kind)
    entry = store["entries"].get(fingerprint)
    if entry is None:
        return None
    # Dodatkowy strażnik na wypadek kolizji md5 / ręcznej edycji magazynu.
    if entry.get("size") != st.st_size:
        return None
    if entry.get("wersja", 1) != wersja(kind):
        return None                    # policzone starszą wersją algorytmu
    data = entry.get("data")
    return data if isinstance(data, dict) else None


def put(path: str, kind: str, data: dict) -> None:
    """Zapisz ``data`` dla (treść pliku, kind); nadpisz starszy wpis.

    Wpis pamięta ścieżki, z których go zapisano. Gdy plik pod daną ścieżką
    zmieni treść, ta ścieżka znika ze starego wpisu, a wpis bez żadnej
    ścieżki jest usuwany — magazyn nie puchnie od nieaktualnych wyników.
    Rzuca ``OSError``, gdy pliku nie da się odczytać, oraz
    ``TypeError``/``ValueError``, gdy ``data`` nie jest serializowalne do JSON.
    """
    abspath = os.path.abspath(path)
    st = os.stat(abspath)
    fingerprint = key_for(path)
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dumps(data)                   # błąd serializacji PRZED blokadą i zapisem
    with _blokada(kind):
        store = _load_store_locked(kind)
        entries = store["entries"]
        for k in [k for k, e in entries.items()
                  if k != fingerprint and isinstance(e, dict)
                  and abspath in (e.get("paths") or [e.get("path")])]:
            sciezki = [p for p in (entries[k].get("paths") or [entries[k].get("path")])
                       if p != abspath]
            if sciezki:
                entries[k]["paths"] = sciezki
                entries[k]["path"] = sciezki[-1]
            else:
                del entries[k]
        stary = entries.get(fingerprint) or {}
        sciezki = [p for p in (stary.get("paths") or []) if p != abspath and os.path.exists(p)]
        entries[fingerprint] = {
            "path": abspath,
            "paths": (sciezki + [abspath])[-20:],
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "wersja": wersja(kind),
            "data": data,
        }
        store["kind"] = kind
        store["format"] = FORMAT
        _save_store(kind, store)


def _load_store_locked(kind: str) -> dict:
    """Jak _load_store, ale wołane już POD blokadą (bez ponownego jej brania)."""
    data = _read_store(kind)
    if data.get("format", 1) < FORMAT:
        data = _migruj(data)
    return data


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
        with _blokada(kind):
            count = len(_read_store(kind)["entries"])
            try:
                os.remove(path)
            except FileNotFoundError:
                return 0
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
