"""Przygotowanie USB pod CDJ — build a CDJ-ready USB folder.

Copies every audio file from a source folder (non-recursive) into a flat
destination folder with FAT32-safe, ASCII-only names (some CDJ firmwares
garble non-ASCII on the browse screen: Öwes -> Owes, Más -> Mas).

WAV files get special treatment: CDJs read WAV audio fine, but WAV
tags/artwork support is poor, so by default WAV is converted to AIFF
with ffmpeg (pcm_s16be / pcm_s24be, matching the source bit depth) and
re-tagged via mutagen.aiff — AIFF carries full ID3 (TIT2/TPE1/APIC), so
title, artist and the cover survive onto the player screen.
convert_wav="flac" converts to FLAC (compression level 5) instead;
convert_wav=None copies WAV as-is.

FLAC/MP3 (and AIFF/M4A/OGG) are copied byte-identical — content only
(shutil.copyfile), so no resource forks; '._*', '.DS_Store' and other
dotfiles never reach the stick. Name collisions get ' (2)', ' (3)', ...

Requires ffmpeg on PATH for WAV conversion.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from mutagen import File as MutagenFile
from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, TIT2, TPE1
from mutagen.wave import WAVE

from .covers import embedded_art
from .matcher import AUDIO_EXT
from .tagger import FORBIDDEN, safe_name
from .narzedzia import ffmpeg_path, ffprobe_path

MAX_NAME = 120  # full filename budget (stem + extension), CDJ-friendly

# Characters NFKD cannot decompose to ASCII — folded by hand.
_FOLD = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ı": "i",
})


def ascii_fold(text: str) -> str:
    """Diacritics -> plain ASCII (Öwes -> Owes, Más -> Mas, łza -> lza)."""
    text = text.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.encode("ascii", "ignore").decode("ascii")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

@dataclass
class UsbReport:
    """Result of prepare(): what landed on the stick and what did not."""
    copied: list[str] = field(default_factory=list)       # dest paths, copied 1:1
    converted: list[str] = field(default_factory=list)    # dest paths, WAV->AIFF/FLAC
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (source name, reason)
    total_bytes: int = 0

    def format_report(self) -> str:
        """Polish, human-readable summary."""
        mb = self.total_bytes / (1024 * 1024)
        lines = [
            "Przygotowanie USB pod CDJ zakończone:",
            f"  skopiowane pliki: {len(self.copied)}",
            f"  skonwertowane z WAV: {len(self.converted)}",
            f"  pominięte: {len(self.skipped)}",
            f"  łącznie zapisano: {mb:.1f} MB ({self.total_bytes} B)",
        ]
        for name, reason in self.skipped:
            lines.append(f"    - {name}: {reason}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #

def _artist_title(path: str) -> tuple[str, str]:
    """(artist, title) from tags, falling back to the 'Artist - Title' filename."""
    stem = os.path.splitext(os.path.basename(path))[0]
    fn_artist, sep, fn_title = stem.partition(" - ")
    artist = fn_artist.strip() if sep else ""
    title = fn_title.strip() if sep else stem
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    tags = getattr(audio, "tags", None)
    if tags is not None:
        if hasattr(tags, "getall"):  # ID3 (MP3/WAV/AIFF)
            t = tags.get("TIT2")
            a = tags.get("TPE1")
            if t is not None and getattr(t, "text", None) and str(t.text[0]).strip():
                title = str(t.text[0]).strip()
            if a is not None and getattr(a, "text", None) and str(a.text[0]).strip():
                artist = str(a.text[0]).strip()
        else:  # Vorbis comments (FLAC/OGG)
            if tags.get("TITLE"):
                title = str(tags["TITLE"][0]).strip() or title
            if tags.get("ARTIST"):
                artist = str(tags["ARTIST"][0]).strip() or artist
    return artist, title


def _dest_stem(path: str, ext: str) -> str:
    """FAT32-safe, ASCII, length-capped stem for the destination file."""
    artist, title = _artist_title(path)
    if artist:
        stem = safe_name(artist, title)
    else:
        stem = FORBIDDEN.sub("", title).strip().rstrip(".")
    stem = ascii_fold(stem)
    stem = " ".join(stem.split())  # collapse whitespace left by folding
    stem = stem.strip().rstrip(".")
    if not stem:
        stem = "utwor"
    budget = MAX_NAME - len(ext) - 6  # leave room for ' (99)' dedupe suffix
    return stem[:budget].rstrip(" .")


def _unique_dest(dest_folder: str, stem: str, ext: str, taken: set[str]) -> str:
    """Collision-free path in dest_folder; FAT32 is case-insensitive."""
    name = stem + ext
    n = 2
    while name.lower() in taken or os.path.exists(os.path.join(dest_folder, name)):
        name = f"{stem} ({n}){ext}"
        n += 1
    taken.add(name.lower())
    return os.path.join(dest_folder, name)


# --------------------------------------------------------------------------- #
# WAV conversion
# --------------------------------------------------------------------------- #

def _convert_wav(src: str, dst: str) -> None:
    """ffmpeg WAV -> AIFF/FLAC, matching bit depth; tags handled separately."""
    ext = os.path.splitext(dst)[1].lower()
    try:
        bits = WAVE(src).info.bits_per_sample or 16
    except Exception:
        bits = 16
    cmd = [ffmpeg_path(), "-v", "error", "-y", "-i", src, "-vn", "-map_metadata", "-1"]
    if ext == ".aiff":
        cmd += ["-c:a", "pcm_s16be" if bits <= 16 else "pcm_s24be"]
    else:  # .flac
        cmd += ["-c:a", "flac", "-compression_level", "5"]
    proc = subprocess.run(cmd + [dst], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffmpeg zakończył się kodem {proc.returncode}")


def _retag_converted(src_wav: str, dst: str, artist: str, title: str) -> None:
    """Carry TIT2/TPE1 and the embedded cover from the WAV into dst."""
    cover = None
    try:
        cover = embedded_art(src_wav)
    except Exception:
        pass
    ext = os.path.splitext(dst)[1].lower()
    if ext == ".aiff":
        audio = AIFF(dst)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.delall("TIT2")
        audio.tags.delall("TPE1")
        audio.tags.add(TIT2(encoding=3, text=title))
        if artist:
            audio.tags.add(TPE1(encoding=3, text=artist))
        if cover:
            audio.tags.delall("APIC")
            audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3,
                                desc="Cover", data=cover))
        audio.save()
    elif ext == ".flac":
        audio = FLAC(dst)
        audio["TITLE"] = title
        if artist:
            audio["ARTIST"] = artist
        if cover:
            audio.clear_pictures()
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, "image/jpeg", "Cover"
            pic.data = cover
            audio.add_picture(pic)
        audio.save()


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #

def prepare(
    src_folder: str,
    dest_folder: str,
    convert_wav: str | None = "aiff",
    on_progress: Callable[[int, int, str], None] | None = None,
) -> UsbReport:
    """Copy/convert audio from src_folder into a flat, CDJ-ready dest_folder.

    convert_wav: "aiff" (default) or "flac" — target for WAV files;
    None copies WAV unchanged. on_progress, when given, is called after
    each source file as on_progress(done, total, source_name).
    Only regular files directly inside src_folder are considered;
    dotfiles ('._*', '.DS_Store', ...) are ignored entirely.
    """
    if convert_wav is not None:
        convert_wav = convert_wav.lower().lstrip(".")
        if convert_wav not in ("aiff", "flac"):
            raise ValueError(
                f"convert_wav musi być 'aiff', 'flac' albo None, nie {convert_wav!r}"
            )

    os.makedirs(dest_folder, exist_ok=True)
    report = UsbReport()
    taken: set[str] = set()

    entries = [
        name for name in sorted(os.listdir(src_folder), key=str.lower)
        if not name.startswith(".")  # no ._ forks, no .DS_Store
        and os.path.isfile(os.path.join(src_folder, name))
    ]

    for done, name in enumerate(entries, start=1):
        src = os.path.join(src_folder, name)
        ext = os.path.splitext(name)[1].lower()
        try:
            if ext not in AUDIO_EXT:
                report.skipped.append((name, "to nie plik audio"))
                continue

            stem = _dest_stem(src, ext)
            if ext == ".wav" and convert_wav is not None:
                dst = _unique_dest(dest_folder, stem, "." + convert_wav, taken)
                artist, title = _artist_title(src)
                try:
                    _convert_wav(src, dst)
                    _retag_converted(src, dst, artist, title)
                except (RuntimeError, OSError) as exc:
                    report.skipped.append((name, f"konwersja nieudana: {exc}"))
                    if os.path.exists(dst):
                        os.remove(dst)
                    continue
                report.converted.append(dst)
            else:
                dst = _unique_dest(dest_folder, stem, ext, taken)
                try:
                    # copyfile = data fork only; copy2 could drag metadata along
                    shutil.copyfile(src, dst)
                except OSError as exc:
                    report.skipped.append((name, f"kopiowanie nieudane: {exc}"))
                    if os.path.exists(dst):
                        os.remove(dst)
                    continue
                report.copied.append(dst)
            report.total_bytes += os.path.getsize(dst)
        finally:
            if on_progress is not None:
                on_progress(done, len(entries), name)

    return report


# --------------------------------------------------------------------------- #
# weryfikacja po skopiowaniu
# --------------------------------------------------------------------------- #

def _suma(path: str, blok: int = 1024 * 1024) -> str:
    """SHA-1 zawartości pliku. Szybsze niż SHA-256, a do wykrycia
    przekłamanego kopiowania w zupełności wystarczy."""
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            kawalek = fh.read(blok)
            if not kawalek:
                break
            h.update(kawalek)
    return h.hexdigest()


def zweryfikuj(pary: list[tuple[str, str]],
               on_progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Sprawdź, czy pliki na pendrive są identyczne ze źródłem.

    Pendrive'y potrafią zapisać plik po cichu uszkodzony — zwłaszcza gdy
    wyjmie się go bez odmontowania. Ucięty albo przekłamany plik na CDJ-u
    kończy się przerwaniem odtwarzania w środku setu, więc lepiej
    dowiedzieć się o tym w domu.

    `pary` to lista (źródło, cel). Kopie WAV→AIFF pomijamy: mają inną
    zawartość z założenia, więc porównujemy tylko rozmiar celu > 0.
    """
    zgodne, rozne, brakujace = [], [], []
    for i, (src, dst) in enumerate(pary, start=1):
        if on_progress:
            on_progress(i, len(pary), os.path.basename(dst))
        if not os.path.isfile(dst):
            brakujace.append(dst)
            continue
        try:
            if os.path.splitext(src)[1].lower() != os.path.splitext(dst)[1].lower():
                # plik przekonwertowany — porównanie bajt w bajt nie ma sensu
                (zgodne if os.path.getsize(dst) > 0 else rozne).append(dst)
                continue
            if os.path.getsize(src) != os.path.getsize(dst):
                rozne.append(dst)
                continue
            (zgodne if _suma(src) == _suma(dst) else rozne).append(dst)
        except OSError:
            rozne.append(dst)
    return {"sprawdzonych": len(pary), "zgodne": len(zgodne),
            "rozne": rozne, "brakujace": brakujace,
            "ok": not rozne and not brakujace}
