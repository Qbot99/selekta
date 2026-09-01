"""Export a track list to DJ software: rekordbox XML, M3U8, Serato crate.

Works on plain track dicts so every writer shares one input shape:

    {"path": str, "artist": str, "title": str, "duration_s": float,
     "bpm": float | None, "key": str | None}   # bpm/key optional

`collect(folder)` builds that list from an audio folder, preferring
mutagen tags (TITLE/ARTIST or TIT2/TPE1) and falling back to the
"Artist - Title" filename convention used across the library.

Formats
-------
rekordbox: DJ_PLAYLISTS 1.0.0 XML (File > Import Collection) — a
COLLECTION of TRACK entries plus a PLAYLISTS/NODE tree whose playlist
references tracks by TrackID, preserving input order.

M3U8: extended M3U, UTF-8, absolute paths.

Serato: binary .crate — big-endian chunks '<4s tag><uint32 len><payload>'
with UTF-16-BE strings. Header chunk 'vrsn' ("1.0/Serato ScratchLive
Crate"); one 'otrk' per track wrapping a 'ptrk' whose payload is the
track path relative to its volume root, without a leading slash.
"""
from __future__ import annotations

import os
import struct
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote

from mutagen import File as MutagenFile
from mutagen.id3 import ID3

from .matcher import AUDIO_EXT
from .tagger import FORBIDDEN

CRATE_VERSION = "1.0/Serato ScratchLive Crate"

KIND = {
    ".mp3": "MP3 File",
    ".flac": "FLAC File",
    ".wav": "WAV File",
    ".aiff": "AIFF File",
    ".aif": "AIFF File",
    ".m4a": "M4A File",
    ".ogg": "OGG File",
}


# --------------------------------------------------------------------------- #
# building track dicts from a folder
# --------------------------------------------------------------------------- #

def _tag_text(audio, id3_frames: tuple[str, ...], vorbis_names: tuple[str, ...]) -> str | None:
    """First non-empty value among ID3 frames / Vorbis comment names."""
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None
    if isinstance(tags, ID3):
        for name in id3_frames:
            frame = tags.get(name)
            if frame is not None and getattr(frame, "text", None):
                val = str(frame.text[0]).strip()
                if val:
                    return val
        return None
    for name in vorbis_names:  # VCommentDict lookups are case-insensitive
        try:
            val = tags.get(name)
        except Exception:
            val = None
        if val:
            val = str(val[0] if isinstance(val, list) else val).strip()
            if val:
                return val
    return None


def _float_or_none(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        val = float(str(raw).replace(",", "."))
    except ValueError:
        return None
    return val if val > 0 else None


def track_from_file(path: str) -> dict:
    """One track dict for `path`; tags first, filename parse as fallback."""
    path = os.path.abspath(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    fn_artist, sep, fn_title = stem.partition(" - ")
    track = {
        "path": path,
        "artist": fn_artist.strip() if sep else "",
        "title": fn_title.strip() if sep else stem,
        "duration_s": 0.0,
        "bpm": None,
        "key": None,
    }
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    if audio is None:
        return track
    length = getattr(audio.info, "length", None)
    if length:
        track["duration_s"] = float(length)
    title = _tag_text(audio, ("TIT2",), ("TITLE",))
    artist = _tag_text(audio, ("TPE1",), ("ARTIST",))
    if title:
        track["title"] = title
    if artist:
        track["artist"] = artist
    track["bpm"] = _float_or_none(_tag_text(audio, ("TBPM",), ("BPM", "TEMPO")))
    track["key"] = _tag_text(audio, ("TKEY",), ("KEY", "INITIALKEY", "INITIAL_KEY"))
    _fill_from_cache(path, track)
    return track


def _fill_from_cache(path: str, track: dict) -> None:
    """Uzupełnij BPM/tonację z policzonej analizy, gdy plik nie ma tagów.

    Bez tego eksport gubi klucze policzone przez `analyze` (siedzą w cache,
    nie w pliku) i rekordbox dostaje niepełną kolekcję.
    """
    if track["bpm"] and track["key"]:
        return
    try:
        from . import cache

        data = cache.get(path, "harmonic")
    except Exception:  # noqa: BLE001 — brak cache nie może psuć eksportu
        return
    if not data:
        return
    if not track["bpm"] and data.get("bpm"):
        track["bpm"] = float(data["bpm"])
    if not track["key"] and data.get("camelot"):
        track["key"] = data["camelot"]


def collect(folder: str) -> list[dict]:
    """Track dicts for every audio file directly inside `folder`, sorted by name."""
    out: list[dict] = []
    for name in sorted(os.listdir(folder), key=str.lower):
        if name.startswith("."):
            continue
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.lower().endswith(AUDIO_EXT):
            out.append(track_from_file(path))
    return out


# --------------------------------------------------------------------------- #
# rekordbox XML
# --------------------------------------------------------------------------- #

def _location_url(path: str) -> str:
    """rekordbox-style file URL: file://localhost/<percent-encoded abs path>."""
    return "file://localhost" + quote(os.path.abspath(path), safe="/")


def to_rekordbox_xml(tracks: list[dict], playlist_name: str, out_path: str) -> str:
    """Write a rekordbox DJ_PLAYLISTS 1.0.0 XML with one playlist; return out_path.

    Track order in COLLECTION and in the playlist NODE follows `tracks`.
    AverageBpm/Tonality are emitted only when the dict provides bpm/key.
    """
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="6.0.0", Company="AlphaTheta")

    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks)))
    for i, track in enumerate(tracks, start=1):
        path = track["path"]
        attrs = {
            "TrackID": str(i),
            "Name": str(track.get("title") or ""),
            "Artist": str(track.get("artist") or ""),
            "Kind": KIND.get(os.path.splitext(path)[1].lower(), "Unknown File"),
            "TotalTime": str(int(round(float(track.get("duration_s") or 0)))),
            "Location": _location_url(path),
        }
        if os.path.exists(path):
            attrs["Size"] = str(os.path.getsize(path))
        bpm = _float_or_none(track.get("bpm"))
        if bpm:
            attrs["AverageBpm"] = f"{bpm:.2f}"
        if track.get("key"):
            attrs["Tonality"] = str(track["key"])
        ET.SubElement(collection, "TRACK", attrs)

    playlists = ET.SubElement(root, "PLAYLISTS")
    node_root = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(
        node_root, "NODE",
        Name=playlist_name, Type="1", KeyType="0", Entries=str(len(tracks)),
    )
    for i in range(1, len(tracks) + 1):  # playlist order == input order
        ET.SubElement(node, "TRACK", Key=str(i))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return out_path


# --------------------------------------------------------------------------- #
# M3U8
# --------------------------------------------------------------------------- #

def to_m3u8(tracks: list[dict], out_path: str) -> str:
    """Write an extended M3U8 (UTF-8, absolute paths); return out_path."""
    lines = ["#EXTM3U"]
    for track in tracks:
        seconds = int(round(float(track.get("duration_s") or 0)))
        artist = str(track.get("artist") or "").strip()
        title = str(track.get("title") or "").strip()
        label = f"{artist} - {title}" if artist else title
        lines.append(f"#EXTINF:{seconds},{label}")
        lines.append(os.path.abspath(track["path"]))
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path


# --------------------------------------------------------------------------- #
# Serato crate
# --------------------------------------------------------------------------- #

def _chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack(">I", len(payload)) + payload


def _volume_relative(path: str) -> str:
    """Path relative to its volume root, forward slashes, no leading slash.

    Serato resolves 'ptrk' against the root of the volume that holds the
    _Serato_ folder: '/Volumes/USB/Music/a.mp3' -> 'Music/a.mp3'; files on
    the boot volume keep their full path minus the leading '/'.
    """
    p = os.path.abspath(path)
    if sys.platform == "darwin" and p.startswith("/Volumes/"):
        parts = p.split("/", 3)  # ['', 'Volumes', '<name>', '<rest>']
        return parts[3] if len(parts) > 3 else ""
    return p.replace(os.sep, "/").lstrip("/")


def to_serato_crate(tracks: list[dict], crate_path: str) -> str:
    """Write a Serato .crate for `tracks` at crate_path; return crate_path.

    Layout: 'vrsn' header chunk (UTF-16-BE version string), then one
    'otrk' chunk per track wrapping a 'ptrk' chunk whose payload is the
    volume-relative path in UTF-16-BE. Input order is preserved.
    """
    blob = _chunk(b"vrsn", CRATE_VERSION.encode("utf-16-be"))
    for track in tracks:
        ptrk = _chunk(b"ptrk", _volume_relative(track["path"]).encode("utf-16-be"))
        blob += _chunk(b"otrk", ptrk)
    parent = os.path.dirname(os.path.abspath(crate_path))
    os.makedirs(parent, exist_ok=True)
    with open(crate_path, "wb") as fh:
        fh.write(blob)
    return crate_path


def install_serato_crate(tracks: list[dict], library_root: str,
                         crate_name: str = "selekta") -> str:
    """Write <library_root>/_Serato_/Subcrates/<crate_name>.crate; return its path."""
    safe = FORBIDDEN.sub("", crate_name).strip().rstrip(".") or "crate"
    crate_path = os.path.join(library_root, "_Serato_", "Subcrates", safe + ".crate")
    return to_serato_crate(tracks, crate_path)
