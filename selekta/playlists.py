"""Playlisty jako osobne foldery — jedna playlista, jeden katalog.

Układ na dysku:

    ~/Music/selekta/                 <- wspólny katalog pobierania
        set piatek/                  <- jedna playlista = jeden folder
        wesele 2026/

Dzięki temu ostatni krok kreatora eksportuje DOKŁADNIE tę playlistę,
a nie całą bibliotekę użytkownika. Utwory, które użytkownik już ma,
zostają na swoim miejscu — playlista trzyma tylko ścieżki, więc nic
się nie duplikuje; do folderu playlisty trafiają wyłącznie NOWE
pobrania.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import config

FORBIDDEN = re.compile(r'[/\\:?"<>|*]')
MANIFEST = "_selekta.json"
SLSKD_DOWNLOADS = (
    "~/Library/Application Support/slskd/downloads",
    "~/.local/share/slskd/downloads",
)


def root() -> str:
    """Wspólny katalog na pobrania selekty."""
    r = config.get("downloads_root") or "~/Music/selekta"
    path = os.path.abspath(os.path.expanduser(r))
    os.makedirs(path, exist_ok=True)
    return path


def safe_name(name: str) -> str:
    cleaned = FORBIDDEN.sub("", (name or "").strip()).strip(". ")
    return cleaned or f"set {time.strftime('%Y-%m-%d')}"


def folder_for(name: str, create: bool = True) -> str:
    path = os.path.join(root(), safe_name(name))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def rename(old_name: str, new_name: str) -> str:
    """Zmień nazwę folderu playlisty (gdy użytkownik nazwie ją później)."""
    src, dst = folder_for(old_name, create=False), folder_for(new_name, create=False)
    if src != dst and os.path.isdir(src) and not os.path.exists(dst):
        os.rename(src, dst)
        return dst
    return folder_for(new_name)


def slskd_downloads_dir() -> str:
    for c in SLSKD_DOWNLOADS:
        p = os.path.expanduser(c)
        if os.path.isdir(p):
            return p
    return ""


def _all_files(folder: str) -> list[str]:
    out = []
    for base, _dirs, files in os.walk(folder):
        for f in files:
            if not f.startswith("."):
                out.append(os.path.join(base, f))
    return out


def fast_copy(src: str, dst: str) -> None:
    """Kopia pliku, najtaniej jak się da.

    Na APFS (macOS) robimy klon copy-on-write: kopia jest natychmiastowa
    i zajmuje ~0 bajtów, dopóki któraś ze stron się nie zmieni. Dzięki
    temu folder playlisty może być samodzielny (gotowy na pendrive) bez
    mnożenia gigabajtów na dysku.
    """
    if sys.platform == "darwin":
        if subprocess.run(["cp", "-c", src, dst],
                          capture_output=True).returncode == 0:
            return
    shutil.copy2(src, dst)


def przenies_analizy(src: str, dst: str) -> int:
    """Skopiuj policzone analizy (BPM, tonacja, siatka, głośność, cue…) na kopię.

    Pamięć analiz jest kluczowana ścieżką pliku, więc kopia w folderze setu
    zaczynała od zera: eksport 6 utworów liczył wszystko od nowa (424 s).
    Kopia z ``cp -c`` ma ten sam dźwięk co oryginał — wyniki są te same.
    Ręczna korekta siatki też idzie za utworem.
    """
    from . import cache
    from .tagger import _rodzaje_cache
    n = 0
    for kind in _rodzaje_cache():
        try:
            if cache.get(dst, kind) is not None:
                continue
            d = cache.get(src, kind)
            if d is not None:
                cache.put(dst, kind, d)
                n += 1
        except (OSError, TypeError, ValueError):
            continue
    try:
        from . import waveform
        w = waveform.wczytaj_siatke(src)
        if w and w.get("first_beat_s") is not None and not waveform.wczytaj_siatke(dst):
            waveform.zapisz_siatke(dst, w["first_beat_s"], w.get("bpm"), w.get("battito"))
    except Exception:                          # noqa: BLE001
        pass
    return n


def collect(name: str, files: list[str]) -> dict:
    """Skopiuj utwory playlisty do jej folderu (samodzielna kopia setu).

    Pobrania trafiają dziś prosto do biblioteki, więc apka widzi je od razu
    i nie ściąga drugi raz tego samego. Tutaj tworzymy z nich osobny,
    kompletny folder playlisty — bez ruszania oryginałów.
    """
    dest = folder_for(name)
    copied, missing, reused = [], [], []
    for src in files:
        if not src or not os.path.isfile(src):
            missing.append(src)
            continue
        target = os.path.join(dest, os.path.basename(src))
        if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(src):
            reused.append(target)          # już skopiowany wcześniej
            przenies_analizy(src, target)
            continue
        stem, ext = os.path.splitext(target)
        n = 2
        while os.path.exists(target):
            target = f"{stem} ({n}){ext}"
            n += 1
        try:
            fast_copy(src, target)
            copied.append(target)
        except OSError:
            missing.append(src)
            continue
        przenies_analizy(src, target)
    return {"copied": copied, "reused": reused, "missing": missing,
            "files": copied + reused, "folder": dest}


def save_manifest(name: str, files: list[str]) -> str:
    """Zapisz skład playlisty (ścieżki bezwzględne) obok jej folderu."""
    dest = folder_for(name)
    path = os.path.join(dest, MANIFEST)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"name": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "files": files}, fh, ensure_ascii=False, indent=2)
    return path


def load_manifest(name: str) -> list[str]:
    path = os.path.join(folder_for(name, create=False), MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            return [f for f in json.load(fh).get("files", []) if os.path.isfile(f)]
    except (OSError, json.JSONDecodeError):
        return []


def audio_in(name: str) -> list[str]:
    """Pliki audio faktycznie leżące w folderze playlisty."""
    from .matcher import AUDIO_EXT
    folder = folder_for(name, create=False)
    if not os.path.isdir(folder):
        return []
    return sorted(p for p in _all_files(folder) if p.lower().endswith(AUDIO_EXT))


def wszystkie() -> list[dict]:
    """Playlisty utworzone w apce — nazwa, liczba utworów, katalog."""
    korzen = root()
    if not os.path.isdir(korzen):
        return []
    out = []
    for nazwa in sorted(os.listdir(korzen), key=str.lower):
        folder = os.path.join(korzen, nazwa)
        if not os.path.isdir(folder) or nazwa.startswith("."):
            continue
        pliki = [f for f in load_manifest(nazwa) if os.path.isfile(f)]
        if not pliki:
            pliki = audio_in(nazwa)
        out.append({"name": nazwa, "utworow": len(pliki), "folder": folder})
    return out
