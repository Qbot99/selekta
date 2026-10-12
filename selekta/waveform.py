"""Przebieg fali do podglądu i ręcznej korekty siatki beatów.

Po co: DJ musi móc ZOBACZYĆ, czy kotwica beatgridu stoi na uderzeniu.
Algorytm bywa dobry, ale nie zawsze — a werdykt, którego nie da się
sprawdzić ani poprawić, jest gorszy niż brak werdyktu.

Zwracamy dwie obwiednie: szczytową (widać transjenty, czyli uderzenia)
i skuteczną RMS (widać, gdzie utwór ma masę). Rysowane razem dają obraz,
na którym stopa jest wyraźna i łatwo ocenić, czy linie siatki w nią trafiają.
"""
from __future__ import annotations

import subprocess

import numpy as np
from .narzedzia import ffmpeg_path, ffprobe_path

SR = 8000              # do rysowania w zupełności wystarczy
PUNKTY = 1600          # rozdzielczość pozioma wykresu


def _dekoduj(path: str, sr: int = SR) -> np.ndarray:
    """Mono float32 przez ffmpeg; pusta tablica, gdy plik nie da się odczytać."""
    cmd = [ffmpeg_path(), "-v", "error", "-i", path, "-map", "0:a:0",
           "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return np.empty(0, dtype=np.float32)
    if r.returncode != 0 or not r.stdout:
        return np.empty(0, dtype=np.float32)
    return np.frombuffer(r.stdout, dtype=np.float32)


def oblicz(path: str, punkty: int = PUNKTY) -> dict:
    """Obwiednie przebiegu, znormalizowane do 0..1.

    Zwraca słownik gotowy do wysłania w JSON: `szczyt` i `rms` to listy
    tej samej długości, `czas_s` to długość utworu.
    """
    x = _dekoduj(path)
    if x.size == 0:
        return {"szczyt": [], "rms": [], "czas_s": 0.0, "punkty": 0}

    czas = x.size / SR
    punkty = max(16, min(int(punkty), 4000))
    # plik krótszy niż jeden punkt na próbkę (< 0,2 s przy 1600 punktach)
    # rzucał ValueError przy reshape i /api/waveform zwracało 500
    punkty = min(punkty, x.size)
    # przycinamy do pełnej wielokrotności, żeby reshape był bez kopiowania
    na_punkt = max(1, x.size // punkty)
    uzyte = na_punkt * punkty
    kubelki = x[:uzyte].reshape(punkty, na_punkt)

    szczyt = np.abs(kubelki).max(axis=1)
    rms = np.sqrt((kubelki.astype(np.float64) ** 2).mean(axis=1))

    # normalizacja do szczytu całości — cichy utwór ma być widoczny tak samo
    maks = float(szczyt.max()) or 1.0
    szczyt = szczyt / maks
    rms = rms / maks

    return {
        "szczyt": [round(float(v), 4) for v in szczyt],
        "rms": [round(float(v), 4) for v in rms],
        "czas_s": round(czas, 3),
        "punkty": punkty,
    }


# --------------------------------------------------------------------------
# ręczne korekty siatki
# --------------------------------------------------------------------------
#
# Trzymane OSOBNO od pamięci podręcznej analiz, i to celowo. Tamta jest
# kluczowana odciskiem pliku (ścieżka + mtime + rozmiar), a apka zmienia
# tagi i okładki — każda taka zmiana kasowałaby ręczną poprawkę użytkownika.
# Praca człowieka ma przetrwać przetagowanie pliku.

import json
import os

from . import config

PLIK_SIATEK = os.path.join(config.STATE_DIR, "siatki.json")


def _wczytaj_wszystkie() -> dict:
    try:
        with open(PLIK_SIATEK, encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def wczytaj_siatke(path: str) -> dict | None:
    """Ręczna korekta siatki dla pliku albo None."""
    return _wczytaj_wszystkie().get(os.path.abspath(path))


def zapisz_siatke(path: str, first_beat_s: float, bpm: float | None = None,
                  battito: int | None = None) -> dict:
    """Zapamiętaj poprawkę wprowadzoną ręcznie (kotwica, BPM, numer bitu kotwicy)."""
    wpis = {"first_beat_s": round(float(first_beat_s), 4)}
    if bpm:
        wpis["bpm"] = round(float(bpm), 3)
    if battito and 1 <= int(battito) <= 4:
        wpis["battito"] = int(battito)
    dane = _wczytaj_wszystkie()
    dane[os.path.abspath(path)] = wpis
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK_SIATEK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK_SIATEK)
    return wpis


def skasuj_siatke(path: str) -> bool:
    """Wróć do wartości wyliczonej przez apkę."""
    dane = _wczytaj_wszystkie()
    if dane.pop(os.path.abspath(path), None) is None:
        return False
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK_SIATEK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK_SIATEK)
    return True
