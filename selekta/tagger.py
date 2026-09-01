"""Write clean tags, embed cover art, rename to 'Artist - Title.ext'."""
from __future__ import annotations

import os
import re

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2, TPE1
from mutagen.wave import WAVE

FORBIDDEN = re.compile(r'[/\\:?"<>|*]')  # FAT32-safe for CDJ USB exports


def safe_name(artist: str, title: str) -> str:
    # rstrip('. ') zdejmuje też przeplot "b. ." — końcowa spacja/kropka
    # jest niedozwolona na FAT32/Windows
    return FORBIDDEN.sub("", f"{artist} - {title}").strip().rstrip(". ")


def _tag_id3(tags, artist: str, title: str, cover: bytes | None) -> None:
    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))


def tag_file(path: str, artist: str, title: str, cover: bytes | None) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        audio = FLAC(path)
        audio["TITLE"] = title
        audio["ARTIST"] = artist
        if cover:
            audio.clear_pictures()
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, "image/jpeg", "Cover"
            pic.data = cover
            audio.add_picture(pic)
        audio.save()
    elif ext == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        _tag_id3(tags, artist, title, cover)
        tags.save(path)
    elif ext == ".wav":
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        _tag_id3(audio.tags, artist, title, cover)
        audio.save()
    else:
        raise ValueError(f"unsupported format: {ext}")


def rename_file(path: str, artist: str, title: str) -> str:
    folder, old = os.path.split(path)
    ext = os.path.splitext(old)[1]
    new = safe_name(artist, title) + ext
    dst = os.path.join(folder, new)
    if os.path.abspath(dst) == os.path.abspath(path):
        return path
    if os.path.exists(dst) and old.lower() != new.lower():
        raise FileExistsError(dst)
    if old.lower() == new.lower() and old != new:  # case-only rename (APFS)
        tmp = os.path.join(folder, new + ".renaming")
        os.rename(path, tmp)
        os.rename(tmp, dst)
    else:
        os.rename(path, dst)
    return dst
