"""Krótkie syntetyczne utwory z tagami — do testów porządków biblioteki.

Każdy plik to kilka sekund sinusa o zadanej częstotliwości (różna
częstotliwość = różna treść), zapisany ffmpeg-iem w żądanym formacie,
z tagami artysta/tytuł i opcjonalną okładką. Nic z prawdziwej biblioteki.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from selekta.narzedzia import ffmpeg_path

_OBRAZY: dict[str, bytes] = {}


def obraz(fmt: str = "jpg", kolor: str = "red") -> bytes:
    """Mały prawdziwy obraz (8×8) wygenerowany ffmpeg-iem — „okładka” do testów."""
    klucz = f"{fmt}:{kolor}"
    if klucz not in _OBRAZY:
        proc = subprocess.run(
            [ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", f"color=c={kolor}:s=8x8",
             "-frames:v", "1", "-f", "image2pipe",
             "-c:v", "mjpeg" if fmt == "jpg" else "png", "-"],
            check=True, capture_output=True)
        _OBRAZY[klucz] = proc.stdout
    return _OBRAZY[klucz]


def utwor(path: str, artist: str | None = "Artysta", title: str | None = "Tytuł",
          sekund: float = 6.0, hz: float = 440.0, okladka: bytes | None = None,
          kbps: int = 192) -> str:
    """Utwórz plik audio (format z rozszerzenia) z tagami; zwróć ścieżkę."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    cmd = [ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi",
           "-i", f"sine=frequency={hz}:sample_rate=44100:duration={sekund}",
           "-ac", "2"]
    if ext == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-write_xing", "1"]
    elif ext == ".m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{kbps}k"]
    elif ext == ".flac":
        cmd += ["-c:a", "flac"]
    elif ext in (".wav", ".aiff", ".aif"):
        cmd += ["-c:a", "pcm_s16le" if ext == ".wav" else "pcm_s16be"]
    subprocess.run(cmd + [path], check=True, capture_output=True)
    taguj(path, artist, title, okladka)
    return path


def taguj(path: str, artist: str | None, title: str | None,
          okladka: bytes | None = None) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        from mutagen.flac import FLAC, Picture
        a = FLAC(path)
        if artist is not None:
            a["ARTIST"] = artist
        if title is not None:
            a["TITLE"] = title
        if okladka:
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, "image/jpeg", okladka
            a.add_picture(pic)
        a.save()
    elif ext == ".m4a":
        from mutagen.mp4 import MP4, MP4Cover
        a = MP4(path)
        if artist is not None:
            a["\xa9ART"] = [artist]
        if title is not None:
            a["\xa9nam"] = [title]
        if okladka:
            fmt = MP4Cover.FORMAT_PNG if okladka[:4] == b"\x89PNG" else MP4Cover.FORMAT_JPEG
            a["covr"] = [MP4Cover(okladka, imageformat=fmt)]
        a.save()
    else:
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2, TPE1
        if ext in (".wav", ".aiff", ".aif"):
            from mutagen.aiff import AIFF
            from mutagen.wave import WAVE
            kont = WAVE(path) if ext == ".wav" else AIFF(path)
            if kont.tags is None:
                kont.add_tags()
            tags = kont.tags
        else:
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            kont = None
        if artist is not None:
            tags.add(TPE1(encoding=3, text=artist))
        if title is not None:
            tags.add(TIT2(encoding=3, text=title))
        if okladka:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover",
                          data=okladka))
        if kont is not None:
            kont.save()
        else:
            tags.save(path)


def kopia(src: str, dst: str) -> str:
    """Kopia jak w playlists.collect: klon APFS (cp -c), inaczej zwykła kopia."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if sys.platform == "darwin" and subprocess.run(
            ["cp", "-c", src, dst], capture_output=True).returncode == 0:
        return dst
    shutil.copy2(src, dst)
    return dst


def set_z(folder: str, nazwa: str, pliki: list[str]) -> list[str]:
    """Folder setu tak, jak robi go kreator: kopie + _selekta.json."""
    katalog = os.path.join(folder, nazwa)
    os.makedirs(katalog, exist_ok=True)
    kopie = [kopia(p, os.path.join(katalog, os.path.basename(p))) for p in pliki]
    with open(os.path.join(katalog, "_selekta.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": nazwa, "files": kopie}, fh, ensure_ascii=False)
    return kopie


def utnij(path: str, ile: float) -> str:
    """Zostaw tylko ułamek ``ile`` bajtów pliku (jak przerwane pobieranie)."""
    rozmiar = os.path.getsize(path)
    with open(path, "r+b") as fh:
        fh.truncate(int(rozmiar * ile))
    return path


_BITRATY = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_PROBKOWANIE = [44100, 48000, 32000, 0]


def utnij_mp3_na_ramce(path: str, ile: float) -> str:
    """Utnij MP3 (MPEG-1 Layer III) DOKŁADNIE na granicy ramki.

    Tak wygląda plik po przerwanym pobieraniu, którego ffmpeg nie zgłasza
    żadnym błędem: dekoduje się „czysto”, tylko krócej, a nagłówek Xing nadal
    obiecuje pełną długość.
    """
    from mutagen.mp3 import MP3
    off = MP3(path).info.frame_offset
    with open(path, "rb") as fh:
        dane = fh.read()
    cel = int(len(dane) * ile)
    while off + 4 <= len(dane) and off < cel:
        b1, b2 = dane[off + 1], dane[off + 2]
        if dane[off] != 0xFF or (b1 & 0xE0) != 0xE0:
            break
        br = _BITRATY[b2 >> 4] * 1000
        sr = _PROBKOWANIE[(b2 >> 2) & 3]
        if not br or not sr:
            break
        off += 144 * br // sr + ((b2 >> 1) & 1)
    with open(path, "r+b") as fh:
        fh.truncate(off)
    return path
