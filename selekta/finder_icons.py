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


def apply(paths: list[str]) -> tuple[int, list[str]]:
    """Set each file's Finder icon from its embedded cover."""
    NSImage, NSWorkspace = _load_appkit()
    ws = NSWorkspace.sharedWorkspace()
    done, skipped = 0, []
    for p in paths:
        if not p.lower().endswith(FINDER_BLIND):
            continue                     # Finder already shows these
        data = embedded_art(p)
        if not data:
            skipped.append(p)
            continue
        img = NSImage.alloc().initWithData_(data)
        if img and ws.setIcon_forFile_options_(img, p, 0):
            done += 1
        else:
            skipped.append(p)
    return done, skipped


def clear(paths: list[str]) -> int:
    """Remove custom icons (and the resource forks they live in)."""
    n = 0
    for p in paths:
        subprocess.run(["xattr", "-d", "com.apple.ResourceFork", p],
                       capture_output=True)
        subprocess.run(["xattr", "-d", "com.apple.FinderInfo", p],
                       capture_output=True)
        n += 1
    return n
