"""Audio quality verification — the fake-FLAC detector.

Lossy codecs low-pass the signal: ~16 kHz for 128 kbps, ~19 kHz for
~256 kbps/V0, ~20.5 kHz for 320 kbps. Genuine lossless keeps energy up
to Nyquist. We measure the spectral cutoff on a 60 s window from the
middle of the track, and separately verify that nominal 24-bit files
carry real 24-bit data (not 16 bits padded with zeros).

Requires ffmpeg on PATH.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import numpy as np

from .narzedzia import ffmpeg_path, ffprobe_path
from mutagen import File as MutagenFile


@dataclass
class QualityReport:
    path: str
    ext: str
    sample_rate: int
    nominal_bits: int | None
    effective_bits: int | None
    cutoff_hz: float
    grade: str          # "ok" | "warn" | "bad"
    verdict: str
    bitrate_kbps: int | None = None   # z nagłówka; None dla lossless


def _decode(path: str, ss: float, dur: float, fmt: str, extra: list[str]) -> bytes:
    cmd = [ffmpeg_path(), "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", path,
           *extra, "-f", fmt, "-"]
    return subprocess.run(cmd, capture_output=True).stdout


def _widmo_pasmowe(path: str, length: float, sr: int):
    """Uśrednione widmo w pasmach 100 Hz: (poziomy dB, środki pasm, poziom
    odniesienia 5-14 kHz) albo None dla za krótkiego materiału."""
    ss = max(0.0, length / 2 - 30)
    raw = _decode(path, ss, 60, "f32le", ["-ac", "1", "-ar", str(sr)])
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < sr * 10:
        return None
    n = 8192
    win = np.hanning(n)
    hop = n // 2
    nseg = (len(x) - n) // hop
    acc = np.zeros(n // 2 + 1)
    for i in range(nseg):
        seg = x[i * hop : i * hop + n] * win
        acc += np.abs(np.fft.rfft(seg)) ** 2
    spec = 10 * np.log10(acc / max(nseg, 1) + 1e-20)
    freqs = np.fft.rfftfreq(n, 1 / sr)

    band = 100
    nb = int(freqs[-1] // band)
    levels = np.array(
        [spec[(freqs >= i * band) & (freqs < (i + 1) * band)].mean() for i in range(nb)]
    )
    centers = (np.arange(nb) + 0.5) * band
    ref = levels[(centers >= 5000) & (centers <= 14000)].mean()
    return levels, centers, ref


def _cutoff_z_widma(levels, centers, ref) -> float:
    for i in range(len(levels) - 1, -1, -1):
        if levels[i] > ref - 42:
            return float(centers[i] + 50)
    return 0.0


def _cisza_nad_cieciem(levels, centers, ref, cutoff: float) -> float | None:
    """Średni poziom (dB względem 5-14 kHz) powyżej cięcia + 300 Hz.

    To rozstrzyga „transkod czy master z lowpassem": transkod z MP3 ma nad
    cięciem ścianę i CYFROWĄ CISZĘ (zmierzone ~-66..-70 dB), master
    z lowpassem łagodne zbocze z resztą energii (~-37..-59 dB). Sam cutoff
    tego nie odróżnia — stąd 19.8% fałszywych alarmów na prawdziwej
    bibliotece przy bramce ostrzejszej tylko o próg cutoffu.
    """
    nad = (centers > cutoff + 300) & (centers < centers[-1] - 100)
    if not nad.any():
        return None
    return float(levels[nad].mean() - ref)


def spectral_cutoff(path: str, length: float, sr: int) -> float:
    w = _widmo_pasmowe(path, length, sr)
    if w is None:
        return 0.0
    return _cutoff_z_widma(*w)


def effective_bits(path: str, length: float) -> int:
    ss = max(0.0, length / 2 - 15)
    raw = _decode(path, ss, 30, "s32le", [])
    x = np.frombuffer(raw, dtype=np.int32)
    x = x[x != 0]
    if len(x) == 0:
        return 0
    combined = int(np.bitwise_or.reduce(x))
    tz = 0
    while tz < 32 and not (combined >> tz) & 1:
        tz += 1
    return 32 - tz


def _verdict(cutoff: float, ext: str) -> tuple[str, str]:
    lossless = ext in (".flac", ".wav", ".aiff")
    if cutoff >= 20900:
        return "ok", "pełne pasmo — prawdziwy lossless" if lossless else "pełne pasmo — bardzo dobre 320"
    if cutoff >= 19800:
        if not lossless:
            return "ok", "typowe pasmo dla 320 kbps"
        return "warn", "pasmo ~20,5 kHz — możliwy transkod z MP3 320 (albo master z lowpassem)"
    if cutoff >= 18300:
        return "warn", "pasmo ~19 kHz — wygląda na źródło ~256 kbps / V0"
    if cutoff >= 15300:
        return "bad", "pasmo ~16 kHz — źródło ~128–192 kbps"
    return "bad", "bardzo wąskie pasmo — kiepskie źródło"


# poniżej tego poziomu (dB względem 5-14 kHz) pasmo nad cięciem uznajemy
# za cyfrową ciszę transkodu; zmierzone: transkod MP3 320 = -67.1 dB,
# prawdziwe mastery z lowpassem z biblioteki = -45.6..-59.7 dB
TRANSKOD_CISZA_DB = -63.0


def analyze(path: str) -> QualityReport:
    audio = MutagenFile(path)
    if audio is None:
        raise ValueError(f"nierozpoznany format audio: {path}")
    sr = audio.info.sample_rate
    length = audio.info.length
    ext = os.path.splitext(path)[1].lower()
    bits = getattr(audio.info, "bits_per_sample", None)

    widmo = _widmo_pasmowe(path, length, sr)
    cutoff = _cutoff_z_widma(*widmo) if widmo else 0.0
    eff = effective_bits(path, length) if bits and bits > 16 else None
    grade, verdict = _verdict(cutoff, ext)
    lossless = ext in (".flac", ".wav", ".aiff")
    if widmo and lossless and grade == "warn" and cutoff >= 18300:
        rel = _cisza_nad_cieciem(*widmo, cutoff)
        if rel is not None and rel < TRANSKOD_CISZA_DB:
            grade = "bad"
            verdict = (f"pasmo {cutoff/1000:.1f} kHz i cyfrowa cisza nad "
                       f"cięciem ({rel:.0f} dB) — transkod z MP3")
        elif rel is not None:
            verdict += (f"; nad cięciem zostaje energia ({rel:.0f} dB) "
                        f"— wygląda na master z lowpassem")
    if bits and bits > 16 and eff and eff <= 16:
        grade = "warn"
        verdict += f"; deklarowane {bits}-bit, realnie {eff}-bit"
    # bitrate z nagłówka: pasmo nie odróżnia MP3 mono 128 od 320 (LAME
    # przy 128 mono nie tnie pasma), a liczba z nagłówka — tak
    br = None
    if ext not in (".flac", ".wav", ".aiff"):
        surowy = getattr(audio.info, "bitrate", 0) or 0
        br = round(surowy / 1000) or None
    return QualityReport(path, ext, sr, bits, eff, cutoff, grade, verdict, br)
