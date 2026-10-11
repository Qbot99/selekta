"""Cover art: fetch, embed, and — crucially — verify.

Two sources: Spotify (exact, when the track came from a playlist) and
iTunes Search (fallback for anything not on the playlist, e.g. bootlegs
and older rips).

The verify step exists because a wrong cover is worse than none: it is
invisible in a tag editor and only shows up on the CDJ screen mid-set.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests
from mutagen import File as MutagenFile

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


@dataclass
class CoverHit:
    data: bytes
    source: str
    description: str


def embedded_art(path: str) -> bytes | None:
    """Okładka wbudowana w plik; None także przy pliku uszkodzonym.

    Wyjątek z mutagen potrafiłby wywalić całe listowanie biblioteki —
    a uszkodzony plik to normalna sytuacja po przerwanym pobieraniu.
    """
    try:
        audio = MutagenFile(path)
    except Exception:                          # noqa: BLE001
        return None
    if audio is None:
        return None
    if path.lower().endswith(".flac"):
        return audio.pictures[0].data if audio.pictures else None
    tags = getattr(audio, "tags", None)
    if tags:
        # M4A/MP4: okładka w atomie 'covr' (bez tego każdy M4A miał „brak okładki")
        if "covr" in tags and tags["covr"]:
            return bytes(tags["covr"][0])
        for key in tags.keys():
            if key.startswith("APIC"):
                return tags[key].data
    return None


def from_itunes(artist: str, title: str) -> CoverHit | None:
    """Fallback lookup; matches on track name to avoid grabbing a
    same-artist-different-song cover."""
    term = quote_plus(f"{artist} {title}")
    try:
        r = requests.get(
            f"https://itunes.apple.com/search?term={term}&entity=song&limit=5",
            headers=UA, timeout=15,
        )
        results = r.json().get("results", [])
    except (requests.RequestException, json.JSONDecodeError):
        return None

    key = title.lower().split("(")[0].strip()
    for item in results:
        if key and key not in item.get("trackName", "").lower():
            continue
        url = item.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        if not url:
            continue
        img = requests.get(url, headers=UA, timeout=15)
        if img.ok and img.content[:3] == b"\xff\xd8\xff":
            return CoverHit(
                img.content,
                "itunes",
                f"{item['artistName']} — {item['trackName']} ({item.get('collectionName','')})",
            )
    return None


def verify(path: str, expected: bytes) -> bool:
    """True when the file carries exactly the expected image."""
    got = embedded_art(path)
    if got is None:
        return False
    return hashlib.md5(got).digest() == hashlib.md5(expected).digest()


def audit(paths: list[str]) -> tuple[list[str], list[str]]:
    """Split files into (with_cover, without_cover)."""
    have, missing = [], []
    for p in paths:
        (have if embedded_art(p) else missing).append(p)
    return have, missing
