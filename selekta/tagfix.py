"""Wykrywanie i naprawa mojibake w tagach audio.

Mojibake powstaje, gdy bajty UTF-8 zostaną błędnie zinterpretowane jako
cp1252 (lub latin-1). Przykład z biblioteki: artysta ``ÅMRTÜM`` zapisany
w tagu jako ``Ã…MRTÃœM``. Litery spoza ASCII rozbijają się wtedy na pary
"śmieciowych" znaków, których pierwszym elementem jest zwykle glif bajtu
wiodącego UTF-8 (``Ã``, ``Â``, ``Ä``, ``Å``, ``â``).

Naprawa polega na odwróceniu procesu:
``tekst.encode('cp1252').decode('utf-8')``. Kluczowa własność: poprawne
diakrytyki (np. ``Öwes``, ``Beyoncé``, ``Zażółć``) po ponownym zakodowaniu
w cp1252 dają bajty, które NIE są prawidłowym UTF-8 i dekodowanie rzuca
wyjątek — dzięki temu takich napisów nie ruszamy.

Moduł jest samodzielny: nie modyfikuje ani nie importuje pozostałych
części pakietu poza stałą ``AUDIO_EXT``.
"""
from __future__ import annotations

import os
import re
import urllib.parse

from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from .matcher import AUDIO_EXT

__all__ = ["looks_mojibake", "repair", "scan", "fix_file", "MOJIBAKE_MARKERS",
           "clean_stem", "name_candidates"]

# Logiczne pola tagów, które naprawiamy.
FIELDS: tuple[str, ...] = ("ARTIST", "TITLE", "ALBUM")

# Mapowania pole logiczne -> klucz zależny od formatu.
_ID3_MAP: dict[str, type] = {"ARTIST": TPE1, "TITLE": TIT2, "ALBUM": TALB}
_ID3_KEYS: dict[str, str] = {"ARTIST": "TPE1", "TITLE": "TIT2", "ALBUM": "TALB"}
_MP4_MAP: dict[str, str] = {"ARTIST": "\xa9ART", "TITLE": "\xa9nam", "ALBUM": "\xa9alb"}

# Rozszerzenia obsługiwane przez konkretne "silniki" tagów.
_VORBIS_EXT = (".flac", ".ogg")
_ID3_EXT = (".mp3", ".wav", ".aiff", ".aif")
_MP4_EXT = (".m4a",)

# Glify bajtów wiodących sekwencji UTF-8 (0xC2-0xC5 oraz 0xE2). W mojibake
# występują sparowane z kolejnym znakiem spoza ASCII — to główny odcisk palca.
# ordy GLIFÓW, na które bajty wiodące UTF-8 (0xC2-0xC5, 0xE2) mapują się
# w cp1252/latin-1 (Â Ã Ä Å â) ORAZ w cp1250 (Â Ă Ä Ĺ â) — polskie tagi
# z lat MP3 to najczęściej właśnie cp1250
_LEAD_BYTES = frozenset({0xC2, 0xC3, 0xC4, 0xC5, 0xE2, 0x102, 0x139})

# Charakterystyczne sekwencje mojibake (dla czytelności i szybkiego testu).
MOJIBAKE_MARKERS: tuple[str, ...] = (
    "Ã", "Â", "â€", "Ã©", "Ã¨", "Ã¼", "Ã¶", "Ã¤", "Ã ", "Ã§", "Ã±",
    "Ã…", "Ãœ", "Ã–", "Ã„", "Ã‰", "Å", "â€™", "â€œ", "â€“", "â‚¬",
    # cp1250 (polskie): ż→ĹĽ, ó→Ăł, ł→Ĺ‚, ś→Ĺ›, ć→Ä‡, ń→Ĺ„, ę→Ä™
    "ĹĽ", "Ăł", "Ĺ‚", "Ĺ›", "Ä‡", "Ĺ„", "Ä™",
)


# Śmieci doklejane przez serwisy z pirackimi mp3 — zostają w nazwie pliku
# i psują wyszukiwanie okładek: „Aquagen Hard To Say I'm Sorry [ ezmp3.cc ]".
_JUNK_BRACKET = re.compile(
    r"[\[\(]\s*[^\]\)]*(?:\.cc|\.com|\.org|\.net|\.ru|\.pl|\.to|kbps|\b320\b"
    r"|mp3|download|rip|promo)[^\]\)]*\s*[\]\)]", re.IGNORECASE)
_JUNK_TAIL = re.compile(r"\s*\+?\s*(?:FREE\s*)?DOWNLOAD\s*$", re.IGNORECASE)
# adres serwisu doklejony bez nawiasu: „(Maras Bootleg)cmp3.eu"
_JUNK_DOMAIN = re.compile(
    r"\s*[a-z0-9-]{2,}\.(?:cc|com|eu|net|org|ru|pl|to|me|biz)\b\.?", re.IGNORECASE)
# ogony bez znaczenia dla wyszukiwania okładki
# Ogon bywa z numerem wersji: „... Bootleg) Master 2".
_NOISE_TAIL = re.compile(
    r"\s*\b(?:master(?:ed)?|hq|hd|official\s*video|audio|full|version|remaster(?:ed)?)"
    r"\b\s*\d{0,4}\s*$", re.IGNORECASE)
# słowa oznaczające przeróbkę — bez nich trafiamy na okładkę ORYGINAŁU,
# a to dla DJ-a i tak lepsze niż pusty kwadrat
_REMIX_WORD = re.compile(
    r"\b(?:bootleg|remix|rmx|edit|mix|mashup|flip|rework|refix|vip)\b", re.IGNORECASE)
_TRACK_NO = re.compile(r"^\s*\d{1,3}\s*[.)\-_]\s+")


def clean_stem(name: str) -> str:
    """Nazwa pliku bez śmieci: adresów serwisów, „+ DOWNLOAD", numerów ścieżek.

    Nie zgadujemy tu artysty ani tytułu — tylko usuwamy to, co na pewno
    nie jest częścią nazwy utworu, żeby wyszukiwanie okładki miało szansę.
    """
    text = name
    if "%" in text and re.search(r"%[0-9A-Fa-f]{2}", text):
        try:
            text = urllib.parse.unquote(text)
        except (UnicodeDecodeError, ValueError):
            pass
    text = _JUNK_BRACKET.sub(" ", text)
    text = _JUNK_DOMAIN.sub(" ", text)
    text = _JUNK_TAIL.sub("", text)
    text = _TRACK_NO.sub("", text)
    text = re.sub(r"[\[\(]\s*[\]\)]", " ", text)      # puste nawiasy po czyszczeniu
    text = _JUNK_TAIL.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip(" -_")


def _bare_title(title: str) -> str:
    """Tytuł bez nawiasów, ogonów i słów o przeróbce — do szukania oryginału."""
    text = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", " ", title)
    text = _REMIX_WORD.sub(" ", text)
    prev = None
    while prev != text:                    # „... Bootleg Master" ma dwa ogony
        prev = text
        text = _NOISE_TAIL.sub("", text.strip())
    return re.sub(r"\s{2,}", " ", text).strip(" -_")


def name_candidates(stem: str) -> list[tuple[str, str]]:
    """Możliwe pary (artysta, tytuł) dla nazwy pliku, od najpewniejszej.

    Przy „Artysta - Tytuł" sprawa jest prosta. Gdy separatora brak
    („Aquagen Hard To Say I'm Sorry"), próbujemy kolejno traktować
    pierwsze 1–2 słowa jako artystę — tak wygląda większość takich nazw.
    """
    clean = clean_stem(stem)
    if not clean:
        return []
    out: list[tuple[str, str]] = []
    if " - " in clean:
        artist, _, title = clean.partition(" - ")
        artist, title = artist.strip(), title.strip()
        if artist and title:
            out.append((artist, title))
            goly = _bare_title(title)
            if goly and goly != title:
                out.append((artist, goly))
        return out
    words = clean.split()
    for n in (1, 2):
        if len(words) > n + 1:
            artist, title = " ".join(words[:n]), " ".join(words[n:])
            out.append((artist, _bare_title(title) or title))
    return out


def _mojibake_score(text: str) -> int:
    """Policz "podejrzane" wzorce w napisie.

    Liczymy: (a) glif bajtu wiodącego UTF-8 tuż przed kolejnym znakiem
    spoza ASCII oraz (b) znaki zastępcze U+FFFD. Im wyższy wynik, tym
    bardziej napis wygląda na uszkodzony.
    """
    score = text.count("�")
    for i in range(len(text) - 1):
        if ord(text[i]) in _LEAD_BYTES and ord(text[i + 1]) >= 0x80:
            # rumuńska pułapka: Ă i Â to zwykłe rumuńskie litery, a Ş (stara
            # cedilla, standard w tagach z ery cp1250) ma w cp1250 bajt
            # KONTYNUACJI UTF-8 — więc zdrowe „MĂŞTI" czy „CÂŞTIG" wygląda
            # bajtowo jak poprawne UTF-8 i bezpiecznik enkodowania go nie
            # łapie. Ceną jest przepuszczenie mojibake francuskiego ê/ª
            # czytanego jako cp1250 — rzadszego niż rumuńskie wersaliki.
            if text[i] in "ĂÂ" and text[i + 1] in "ŞşȘș":
                continue
            score += 1
    return score


def _decode_once(text: str) -> str | None:
    """Jedna próba odwrócenia mojibake.

    Próbuje kolejno cp1252, cp1250 i latin-1; zwraca najlepszy wariant, który jest
    poprawnym UTF-8 i obniża wynik ``_mojibake_score`` względem wejścia.
    Zwraca ``None``, gdy żaden wariant nie poprawia napisu.
    """
    base = _mojibake_score(text)
    best: str | None = None
    best_score = base
    for enc in ("cp1252", "cp1250", "latin-1"):
        try:
            candidate = text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if "�" in candidate:
            continue
        cand_score = _mojibake_score(candidate)
        if cand_score < best_score:
            best, best_score = candidate, cand_score
    return best


def _decode_repair(text: str) -> str | None:
    """Odwróć mojibake, obsługując też podwójne zakodowanie.

    Iteruje ``_decode_once`` dopóki napis się poprawia (maks. 3 kroki, więc
    zawsze się zatrzymuje). Zwraca naprawiony napis albo ``None``, jeśli nic
    nie dało się poprawić.
    """
    current = text
    for _ in range(3):
        nxt = _decode_once(current)
        if nxt is None:
            break
        current = nxt
    return current if current != text else None


def looks_mojibake(text: str) -> bool:
    """Czy ``text`` wygląda na uszkodzony przez błędne dekodowanie UTF-8.

    Wymaga jednocześnie: obecności charakterystycznego wzorca/sekwencji
    ORAZ tego, że odwrócenie kodowania daje "czystszy" wynik (niższy
    ``_mojibake_score``). Poprawne diakrytyki nie spełniają obu warunków,
    więc nie są flagowane.
    """
    if not text:
        return False
    has_marker = _mojibake_score(text) > 0 or any(m in text for m in MOJIBAKE_MARKERS)
    if not has_marker:
        return False
    repaired = _decode_repair(text)
    return repaired is not None and _mojibake_score(repaired) < _mojibake_score(text)


def repair(text: str) -> str:
    """Zwróć naprawioną wersję napisu lub oryginał, jeśli nie ma mojibake.

    Bezpieczne dla poprawnych napisów: ``repair("Öwes") == "Öwes"``,
    ``repair("Beyoncé") == "Beyoncé"``. Uszkodzone napisy są odwracane,
    np. ``repair("Ã…MRTÃœM") == "ÅMRTÜM"``.
    """
    if not text or not looks_mojibake(text):
        return text
    repaired = _decode_repair(text)
    return repaired if repaired is not None else text


def _read_fields(path: str) -> dict[str, str]:
    """Odczytaj ARTIST/TITLE/ALBUM niezależnie od formatu pliku.

    Zwraca słownik {pole: wartość} tylko dla obecnych, niepustych pól.
    Błędy odczytu tagów są ignorowane (zwracany pusty słownik).
    """
    ext = os.path.splitext(path)[1].lower()
    values: dict[str, str] = {}
    try:
        if ext in _VORBIS_EXT:
            audio = FLAC(path) if ext == ".flac" else OggVorbis(path)
            for field in FIELDS:
                val = audio.get(field) or audio.get(field.lower())
                if val:
                    values[field] = str(val[0])
        elif ext in _MP4_EXT:
            audio = MP4(path)
            for field, key in _MP4_MAP.items():
                val = audio.get(key)
                if val:
                    values[field] = str(val[0])
        elif ext in _ID3_EXT:
            tags = _load_id3(path, ext)
            if tags is not None:
                for field, key in _ID3_KEYS.items():
                    frame = tags.get(key)
                    if frame is not None and getattr(frame, "text", None):
                        values[field] = str(frame.text[0])
    except Exception:
        return {}
    return values


def _load_id3(path: str, ext: str) -> ID3 | None:
    """Zwróć obiekt ID3 dla plików MP3/WAV/AIFF (albo ``None``)."""
    try:
        if ext == ".wav":
            return WAVE(path).tags
        if ext in (".aiff", ".aif"):
            return AIFF(path).tags
        return MP3(path).tags  # .mp3
    except (ID3NoHeaderError, Exception):
        return None


def _iter_audio(folder: str) -> list[str]:
    """Ścieżki plików audio w folderze i podfolderach jednego poziomu."""
    paths: list[str] = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name)
    except OSError:
        return paths
    subdirs: list[str] = []
    for entry in entries:
        if entry.is_file() and entry.name.lower().endswith(AUDIO_EXT):
            paths.append(entry.path)
        elif entry.is_dir():
            subdirs.append(entry.path)
    for sub in subdirs:
        try:
            for entry in sorted(os.scandir(sub), key=lambda e: e.name):
                if entry.is_file() and entry.name.lower().endswith(AUDIO_EXT):
                    paths.append(entry.path)
        except OSError:
            continue
    return paths


def scan(folder: str) -> list[tuple[str, str, str, str]]:
    """Przeskanuj bibliotekę pod kątem mojibake w tagach.

    Przechodzi pliki audio w ``folder`` i podfolderach jednego poziomu.
    Zwraca listę krotek ``(ścieżka, pole, obecna_wartość, sugerowana_wartość)``
    dla pól ARTIST/TITLE/ALBUM, w których wykryto mojibake.
    """
    hits: list[tuple[str, str, str, str]] = []
    for path in _iter_audio(folder):
        fields = _read_fields(path)
        for field in FIELDS:
            value = fields.get(field)
            if value and looks_mojibake(value):
                fixed = repair(value)
                if fixed != value:
                    hits.append((path, field, value, fixed))
    return hits


def _write_fields(path: str, ext: str, fixes: dict[str, str]) -> None:
    """Zapisz naprawione pola do pliku (format wybierany po rozszerzeniu)."""
    if ext in _VORBIS_EXT:
        audio = FLAC(path) if ext == ".flac" else OggVorbis(path)
        for field, new in fixes.items():
            audio[field] = new
        audio.save()
    elif ext in _MP4_EXT:
        audio = MP4(path)
        for field, new in fixes.items():
            audio[_MP4_MAP[field]] = [new]
        audio.save()
    elif ext in _ID3_EXT:
        if ext == ".wav":
            container = WAVE(path)
            if container.tags is None:
                container.add_tags()
            tags = container.tags
        elif ext in (".aiff", ".aif"):
            container = AIFF(path)
            if container.tags is None:
                container.add_tags()
            tags = container.tags
        else:  # .mp3
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            container = tags
        for field, new in fixes.items():
            frame_cls = _ID3_MAP[field]
            tags.setall(_ID3_KEYS[field], [frame_cls(encoding=3, text=[new])])
        container.save(path)


def fix_file(path: str, dry_run: bool = True) -> list[tuple[str, str, str]]:
    """Napraw mojibake w polach ARTIST/TITLE/ALBUM jednego pliku.

    Obsługuje FLAC/OGG (Vorbis), MP3/WAV/AIFF (ID3: TPE1/TIT2/TALB) oraz
    M4A (MP4). Przy ``dry_run=True`` nic nie zapisuje — zwraca listę zmian
    ``(pole, stare, nowe)``. Przy ``dry_run=False`` dodatkowo zapisuje je.
    """
    ext = os.path.splitext(path)[1].lower()
    fields = _read_fields(path)
    changes: list[tuple[str, str, str]] = []
    fixes: dict[str, str] = {}
    for field in FIELDS:
        value = fields.get(field)
        if not value:
            continue
        fixed = repair(value)
        if fixed != value:
            changes.append((field, value, fixed))
            fixes[field] = fixed
    if fixes and not dry_run:
        _write_fields(path, ext, fixes)
    return changes
