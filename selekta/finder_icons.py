"""macOS-only: show embedded artwork as the file's Finder icon.

Finder renders embedded art for MP3/M4A/AIFF but not for FLAC or WAV,
so a lossless library looks empty in icon view even when every file is
correctly tagged. Copying the art into the file's custom-icon resource
fixes the display without touching the audio stream.

Cost: this writes a resource fork, which turns into a stray ._ file when
the track is copied to a FAT32/exFAT USB stick. Undo with `clear()`.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .covers import embedded_art

FINDER_BLIND = (".flac", ".wav")   # formats Finder will not thumbnail itself


def available() -> bool:
    return sys.platform == "darwin"


def _load_appkit():
    try:
        from AppKit import NSImage, NSWorkspace  # noqa: PLC0415
    except ImportError as exc:                    # pyobjc not installed
        raise RuntimeError("wymaga: pip install pyobjc-framework-Cocoa") from exc
    return NSImage, NSWorkspace


MARKER = "pl.selekta.ikona"          # „tę ikonę postawiła selekta”
_FINDER_INFO = "com.apple.FinderInfo"
_RESOURCE_FORK = "com.apple.ResourceFork"
_CUSTOM_ICON = 0x0400                  # kHasCustomIcon we flagach Findera


def _xattr(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["xattr", *args], capture_output=True, text=True)


def _finder_info(path: str) -> bytes | None:
    r = _xattr("-px", _FINDER_INFO, path)
    if r.returncode != 0:
        return None
    try:
        return bytes.fromhex("".join(r.stdout.split()))
    except ValueError:
        return None


def _ma_wlasna_ikone(path: str) -> bool:
    fi = _finder_info(path)
    return bool(fi and len(fi) >= 10 and int.from_bytes(fi[8:10], "big") & _CUSTOM_ICON)


def nasza(path: str) -> bool:
    """Czy ikonę tego pliku ustawiła selekta (znacznik w atrybucie)."""
    return _xattr("-p", MARKER, path).returncode == 0


def apply(paths: list[str]) -> tuple[int, list[str]]:
    """Set each file's Finder icon from its embedded cover.

    Pliki, które mają już WŁASNĄ ikonę postawioną przez kogoś innego, zostają
    nietknięte. Postawione przez nas dostają znacznik, żeby ``clear`` mógł
    zdjąć tylko je.
    """
    NSImage, NSWorkspace = _load_appkit()
    ws = NSWorkspace.sharedWorkspace()
    done, skipped = 0, []
    for p in paths:
        if not p.lower().endswith(FINDER_BLIND):
            continue                     # Finder already shows these
        if _ma_wlasna_ikone(p) and not nasza(p):
            skipped.append(p)            # cudza ikona — nie ruszamy
            continue
        data = embedded_art(p)
        if not data:
            skipped.append(p)
            continue
        img = NSImage.alloc().initWithData_(data)
        if img and ws.setIcon_forFile_options_(img, p, 0):
            _xattr("-w", MARKER, "1", p)
            done += 1
        else:
            skipped.append(p)
    return done, skipped


def clear(paths: list[str]) -> int:
    """Zdejmij ikony postawione przez selektę — i tylko je.

    Wcześniej kasowaliśmy cały ``com.apple.FinderInfo`` każdego pliku: znikały
    też cudze ikony i KOLOROWE ETYKIETY Findera (siedzą w tym samym atrybucie).
    Teraz: tylko pliki ze znacznikiem selekty, a w FinderInfo gasimy wyłącznie
    bit „własna ikona”.
    """
    n = 0
    for p in paths:
        if not nasza(p):
            continue
        fi = _finder_info(p)
        if fi and len(fi) >= 10:
            flagi = int.from_bytes(fi[8:10], "big") & ~_CUSTOM_ICON
            fi = fi[:8] + flagi.to_bytes(2, "big") + fi[10:]
            if any(fi):
                _xattr("-wx", _FINDER_INFO, fi.hex(), p)
            else:
                _xattr("-d", _FINDER_INFO, p)
        _xattr("-d", _RESOURCE_FORK, p)
        _xattr("-d", MARKER, p)
        n += 1
    return n
