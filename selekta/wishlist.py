"""Wishlist hunter — keeps looking for tracks you could not find yet.

Entries live in ~/.selekta/wishlist.json. Each check() pass searches the
user's own slskd daemon for every entry not yet found; daemon() wraps
that in a sleep loop and raises a macOS notification when something new
turns up. No slskd means no crash — we simply wait for the next cycle.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime

import requests

from .slskd_client import SlskdClient, SoulseekOffline

STATE_DIR = os.path.expanduser("~/.selekta")
STATE_PATH = os.path.join(STATE_DIR, "wishlist.json")


# ---------------------------------------------------------------- state

def _load() -> list[dict]:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def items() -> list[dict]:
    """Return all wishlist entries (oldest first)."""
    return _load()


def _klucz(artist: str, title: str) -> tuple[str, str]:
    return (" ".join((artist or "").lower().split()),
            " ".join((title or "").lower().split()))


def add(artist: str, title: str, duration_s: float | None = None) -> dict:
    """Dodaj utwór do listy życzeń i zwróć jego wpis.

    Ten sam utwór drugi raz NIE tworzy duplikatu (dawniej każde kliknięcie
    „Dodaj do życzeń" dopisywało kolejny wpis): zwracamy istniejący,
    uzupełniamy brakujący czas, a wpis już „znaleziony" wraca do szukania —
    skoro ktoś dodaje go znowu, poprzednie znalezisko nie pomogło.
    """
    entries = _load()
    klucz = _klucz(artist, title)
    for e in entries:
        if _klucz(e.get("artist", ""), e.get("title", "")) == klucz:
            zmiana = False
            if duration_s and not e.get("duration_s"):
                e["duration_s"] = duration_s
                zmiana = True
            if e.get("found"):
                e["found"] = False
                e.pop("found_hit", None)
                e.pop("found_at", None)
                zmiana = True
            if zmiana:
                _save(entries)
            return e
    entry = {
        "id": uuid.uuid4().hex[:8],
        "artist": artist.strip(),
        "title": title.strip(),
        "duration_s": duration_s,
        "added_at": datetime.now().isoformat(timespec="seconds"),
        "found": False,
    }
    entries.append(entry)
    _save(entries)
    return entry


def remove(id_or_index: str | int) -> dict | None:
    """Remove an entry by its id, or by 0-based index when given a number.

    Returns the removed entry, or None when nothing matched.
    """
    entries = _load()
    idx = None
    for i, e in enumerate(entries):
        if e.get("id") == str(id_or_index):
            idx = i
            break
    if idx is None:
        try:
            i = int(id_or_index)
            entries[i]          # IndexError for out-of-range
            idx = i if i >= 0 else len(entries) + i
        except (ValueError, IndexError):
            return None
    removed = entries.pop(idx)
    _save(entries)
    return removed


# ---------------------------------------------------------------- hunting

def check(client: SlskdClient) -> tuple[list[dict], int]:
    """Search slskd for every entry not yet found; return (finds, failures).

    A find marks the entry found=True and records the best-ranked hit.
    Network errors on a single entry are skipped, not fatal — but COUNTED:
    „0 znalezisk, 12 błędów sieci" i „0 znalezisk, wszystko sprawdzone"
    to dwie różne wiadomości, a zlewanie ich w jedną pozwalało miesiącami
    nie zauważyć, że slskd w ogóle nie działa.
    """
    entries = _load()
    finds: list[dict] = []
    nieudane = 0
    for entry in entries:
        if entry.get("found"):
            continue
        artist, title = entry.get("artist", ""), entry.get("title", "")
        dur = entry.get("duration_s")
        try:
            # ta sama drabina zapytań i ten sam ranking co w aplikacji
            hits = client.search_track(artist, title, dur)
        except (requests.RequestException, KeyError, ValueError, SoulseekOffline):
            nieudane += 1
            continue  # slskd padł w trakcie — spróbujemy w następnym cyklu
        # Dawniej rank(hits, czas) bez artysty i tytułu: trafność = 0 dla
        # wszystkich, wygrywał największy FLAC — „Znaleziono" z plikiem Ricka
        # Astleya, a wpis już nigdy nie był szukany. Teraz tylko wynik, który
        # JEST tym utworem w tej wersji.
        best = client.pewny_wynik(hits, artist, title, dur) if hits else None
        if best is None:
            continue
        entry["found"] = True
        entry["found_at"] = datetime.now().isoformat(timespec="seconds")
        entry["found_hit"] = {
            "username": best.username,
            "filename": best.filename,
            "size": best.size,
            "bitrate": best.bitrate,
            "length_s": best.length_s,
            "is_lossless": best.is_lossless,
        }
        finds.append(entry)
    if finds:
        _save(entries)
    return finds, nieudane


# ---------------------------------------------------------------- notify

def notify(text: str, title: str = "selekta") -> bool:
    """Raise a macOS notification via osascript; True when it went out."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{esc(text)}" with title "{esc(title)}"'
    try:
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=10
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------- daemon

def daemon(interval_s: int = 3600, client: SlskdClient | None = None) -> None:
    """Loop forever: check the wishlist, notify on finds, sleep.

    When slskd is unreachable we just wait for the next cycle.
    Stop with Ctrl+C.
    """
    client = client or SlskdClient()
    print(f"wishlist: nasłuchuję co {interval_s} s (Ctrl+C aby przerwać)")
    try:
        while True:
            if client.available():
                finds, _nieudane = check(client)
                for entry in finds:
                    name = os.path.basename(entry["found_hit"]["filename"])
                    print(f"✓ znaleziono: {entry['artist']} — {entry['title']} ({name})")
                    notify(f"Znaleziono: {entry['artist']} — {entry['title']}")
                if not finds:
                    pending = sum(1 for e in items() if not e.get("found"))
                    print(f"— nic nowego ({pending} wciąż na liście)")
            else:
                print("— slskd niedostępny, czekam do następnego cyklu")
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\nwishlist: koniec nasłuchu")
