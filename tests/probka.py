"""Stała próbka sygnałów o ZNANYCH właściwościach.

Po co osobny moduł: testy zachowania sprawdzają, czy kod nie rzuca
wyjątkiem i czy przepływ ma sens. Nie sprawdzają LICZB. Przestawienie
progu w detekcji fałszywego lossless albo zmiana okna w liczeniu BPM
przechodzi przez wszystkie testy zachowania, a wyniki cicho się
przesuwają — i dowiadujesz się o tym, gdy zaufasz złemu numerowi w klubie.

Sygnały generujemy KODEM, deterministycznie, zamiast wrzucać pliki audio
do repozytorium. Trzy powody: identyczne na każdej maszynie, żadnych
cudzych nagrań w repo, a właściwości znamy z góry — więc wiadomo, jaka
odpowiedź jest poprawna, a nie tylko „taka jak ostatnio".
"""
from __future__ import annotations

import os
import struct
import subprocess
import wave

import numpy as np

SR = 44100
ZIARNO = 20260901          # stałe ziarno: ten sam szum przy każdym uruchomieniu


def _zapisz_wav(x: np.ndarray, path: str, sr: int = SR) -> str:
    x = np.clip(x, -1.0, 1.0)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack("<%dh" % len(x), *(x * 32000).astype(int)))
    return path


def metronom(path: str, bpm: float, sekund: float = 90.0,
             faza: float = 0.0) -> str:
    """Kliki dokładnie co 60/bpm — wzorzec dla detekcji tempa i kotwicy."""
    n = int(SR * sekund)
    x = np.zeros(n, dtype=np.float64)
    dlugosc = 900
    obwiednia = np.exp(-np.arange(dlugosc) / 90.0)
    klik = obwiednia * np.sin(2 * np.pi * 80 * np.arange(dlugosc) / SR)
    t = faza
    while t < sekund:
        i = int(t * SR)
        if i < n - dlugosc:
            x[i:i + dlugosc] += klik
        t += 60.0 / bpm
    return _zapisz_wav(x / max(1e-9, np.abs(x).max()), path)


def pelne_pasmo(path: str, sekund: float = 20.0) -> str:
    """Szum o pełnym paśmie — tak wygląda prawdziwy lossless."""
    rng = np.random.default_rng(ZIARNO)
    x = rng.standard_normal(int(SR * sekund)) * 0.25
    return _zapisz_wav(x, path)


def obciete_pasmo(path: str, khz: float = 16.0, sekund: float = 20.0) -> str:
    """Szum z pasmem uciętym na `khz` — tak wygląda MP3 przebrany za FLAC.

    Odcięcie robimy w dziedzinie widma, żeby nie zależeć od filtrów ffmpeg
    i mieć DOKŁADNIE tę granicę, o której mówimy w teście.
    """
    rng = np.random.default_rng(ZIARNO + 1)
    n = int(SR * sekund)
    x = rng.standard_normal(n) * 0.25
    widmo = np.fft.rfft(x)
    czest = np.fft.rfftfreq(n, 1 / SR)
    widmo[czest > khz * 1000] = 0
    return _zapisz_wav(np.fft.irfft(widmo, n), path)


def ton(path: str, hz: float = 1000.0, sekund: float = 10.0,
        amplituda: float = 0.5) -> str:
    """Czysty ton — wzorzec dla pomiaru głośności."""
    t = np.arange(int(SR * sekund)) / SR
    return _zapisz_wav(amplituda * np.sin(2 * np.pi * hz * t), path)


def akord(path: str, czestotliwosci: list[float], sekund: float = 30.0) -> str:
    """Utrzymany akord — wzorzec dla detekcji tonacji."""
    t = np.arange(int(SR * sekund)) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in czestotliwosci)
    # lekkie pulsowanie, żeby analiza miała onsety i nie liczyła ciszy
    x = x * (0.6 + 0.4 * (np.sin(2 * np.pi * 2 * t) > 0))
    return _zapisz_wav(x / max(1e-9, np.abs(x).max()) * 0.8, path)


def do_flac(wav: str, flac: str) -> str:
    """Przepakuj do FLAC-a — bezstratnie, więc widmo zostaje nietknięte."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, flac], check=True)
    return flac


def do_mp3(wav: str, mp3: str, kbps: int = 128) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav,
                    "-b:a", f"{kbps}k", mp3], check=True)
    return mp3
