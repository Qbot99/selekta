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

    Obsługuje FLAC (PICTURE), ID3 (APIC — MP3/WAV/AIFF) i MP4/M4A (``covr``).
    Bez tego ostatniego każdy M4A był „bez okładki”, a Zdrowie proponowało
    „Dociągnij”, które kończyło się błędem.

    Wyjątek z mutagen potrafiłby wywalić całe listowanie biblioteki —
    a uszkodzony plik to normalna sytuacja po przerwanym pobieraniu.
    """
    try:
        audio = MutagenFile(path)
    except Exception:                          # noqa: BLE001
        return None
    if audio is None:
        return None
    pictures = getattr(audio, "pictures", None)
    if pictures:
        front = [p for p in pictures if getattr(p, "type", None) == 3]
        return (front or pictures)[0].data
    tags = getattr(audio, "tags", None)
    if not tags:
        return None
    try:
        covr = tags.get("covr") if hasattr(tags, "get") else None
    except Exception:                          # noqa: BLE001
        covr = None
    if covr:
        return bytes(covr[0])
    try:
        klucze = list(tags.keys())
    except Exception:                          # noqa: BLE001
        return None
    for key in klucze:
        if str(key).startswith("APIC"):
            return tags[key].data
    return None


def mime_obrazu(data: bytes) -> str:
    """Typ obrazu z jego pierwszych bajtów (okładki bywają PNG, nie tylko JPEG)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _tokeny(tekst: str) -> set[str]:
    from .matcher import normalize
    return set(normalize(tekst or ""))


def _rdzen(tekst: str) -> set[str]:
    from .matcher import MIX_WORDS
    return {t for t in _tokeny(tekst) if t not in MIX_WORDS}


def _artysta_pasuje(chciany: str, znaleziony: str) -> bool:
    """Ten sam wykonawca: połowa słów artysty z tagu musi być u znalezionego.

    „Maddix, Feles” ↔ „Maddix & Feles” tak; „Linds” ↔ „Natasha Bedingfield” nie.
    """
    a, b = _tokeny(chciany), _tokeny(znaleziony)
    if not a or not b:
        return False
    return len(a & b) / len(a) >= 0.5 or len(a & b) / len(b) >= 0.5


def _tytul_pasuje(chciany: str, znaleziony: str) -> bool:
    """Wszystkie słowa tytułu (bez dopisku wersji) są w tytule z iTunes."""
    a = _rdzen(chciany.split("(")[0]) or _rdzen(chciany)
    b = _tokeny(znaleziony)
    return bool(a) and a <= b


def from_itunes(artist: str, title: str, duration: float | None = None) -> CoverHit | None:
    """Okładka z wyszukiwarki iTunes — tylko przy zgodnym artyście i tytule.

    Wcześniej wystarczała zgodność tytułu: przy pospolitym tytule („Kick It”)
    plik Lindsa dostawał okładkę Natashy Bedingfield. Teraz trafienie musi
    mieć tego samego wykonawcę i wszystkie słowa tytułu; gdy znamy czas
    trwania, wybieramy wersję o najbliższej długości, a wersja różniąca się
    o więcej niż 20 s i 25 % długości przechodzi tylko wtedy, gdy różnicę
    tłumaczy dopisek wersji (Extended/Radio Edit/Remix).
    """
    if not (artist or "").strip() or not (title or "").strip():
        return None
    term = quote_plus(f"{artist} {title.split('(')[0]}")
    try:
        r = requests.get(
            f"https://itunes.apple.com/search?term={term}&entity=song&limit=15",
            headers=UA, timeout=15,
        )
        results = r.json().get("results", [])
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None

    from .matcher import mix_signature, normalize
    pasujace = []
    for item in results:
        if not _artysta_pasuje(artist, item.get("artistName", "")):
            continue
        if not _tytul_pasuje(title, item.get("trackName", "")):
            continue
        ms = item.get("trackTimeMillis")
        roznica = abs(ms / 1000 - duration) if (ms and duration) else None
        # wersja klubowa bywa o minutę dłuższa od singla w iTunes (Linds —
        # Kick It: 258 s w pliku, 225 s w iTunes) — tolerujemy 25 % długości
        if roznica is not None and roznica > max(20.0, 0.25 * (duration or 0)):
            wersje = (mix_signature(normalize(title))
                      | mix_signature(normalize(item.get("trackName", ""))))
            if not wersje:
                continue                     # inny utwór o tym samym tytule
        pasujace.append((roznica if roznica is not None else 0, item))
    pasujace.sort(key=lambda x: x[0])
    for _r, item in pasujace:
        url = item.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        if not url:
            continue
        try:
            img = requests.get(url, headers=UA, timeout=15)
        except requests.RequestException:
            continue
        if img.ok and img.content[:3] == b"\xff\xd8\xff":
            return CoverHit(
                img.content,
                "itunes",
                f"{item['artistName']} — {item['trackName']} ({item.get('collectionName','')})",
            )
    return None


def uzupelnij(path: str, nadpisz: bool = False, kopie: list[str] | None = None) -> dict:
    """Dociągnij okładkę z iTunes dla jednego pliku.

    * artysta i tytuł z TAGÓW pliku; z nazwy pliku tylko wtedy, gdy tagów brak;
    * istniejąca okładka zostaje, chyba że ``nadpisz=True`` (wyraźna prośba);
    * zapisujemy WYŁĄCZNIE okładkę — artysta i tytuł w pliku zostają;
    * ``kopie`` — kopie tego samego utworu w folderach setów: dostają tę samą
      okładkę (jeśli żadnej nie mają), żeby set na pendrivie nie był gorszy.

    Zwraca słownik ``{"status": "dodano"|"jest"|"brak"|"blad", "opis": …,
    "kopii": n}`` — nigdy nie rzuca, więc pętla po wielu plikach nie staje
    na pierwszym trudnym przypadku.
    """
    from . import health, tagger, tagfix
    import os
    if not nadpisz and embedded_art(path):
        return {"status": "jest", "opis": "plik ma już okładkę — zostawiam ją", "kopii": 0}
    artist, title = health.czytaj_tagi(path)
    proby: list[tuple[str, str]] = []
    if artist and title:
        proby.append((artist, title))
    else:
        stem = os.path.splitext(os.path.basename(path))[0]
        proby += [(a, t) for a, t in tagfix.name_candidates(stem) if a and t]
    if not proby:
        return {"status": "brak", "opis": "brak artysty i tytułu — nie wiem, czego szukać",
                "kopii": 0}
    try:
        dur = getattr(MutagenFile(path).info, "length", None)
    except Exception:                          # noqa: BLE001
        dur = None
    hit = None
    for a, t in proby:
        hit = from_itunes(a, t, dur)
        if hit:
            break
    if not hit:
        a, t = proby[0]
        return {"status": "brak",
                "opis": f"iTunes nie ma okładki dla „{a} — {t}” (ten sam artysta i tytuł)",
                "kopii": 0}
    try:
        tagger.zapisz_okladke(path, hit.data)
    except (ValueError, OSError) as exc:
        return {"status": "blad", "opis": f"nie udało się zapisać okładki: {exc}", "kopii": 0}
    if not verify(path, hit.data):
        return {"status": "blad", "opis": "okładka nie zapisała się poprawnie", "kopii": 0}
    n = 0
    for k in kopie or []:
        try:
            if os.path.isfile(k) and not embedded_art(k):
                tagger.zapisz_okladke(k, hit.data)
                n += 1
        except (ValueError, OSError):
            pass
    return {"status": "dodano", "opis": hit.description, "zrodlo": hit.source, "kopii": n}


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
