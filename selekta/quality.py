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


def _decode(path: str, ss: float, dur: float, fmt: str, extra: list[str]) -> bytes:
    cmd = ["ffmpeg", "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", path,
           *extra, "-f", fmt, "-"]
    return subprocess.run(cmd, capture_output=True).stdout


def spectral_cutoff(path: str, length: float, sr: int) -> float:
    ss = max(0.0, length / 2 - 30)
    raw = _decode(path, ss, 60, "f32le", ["-ac", "1", "-ar", str(sr)])
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < sr * 10:
        return 0.0
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
    for i in range(nb - 1, -1, -1):
        if levels[i] > ref - 42:
            return float(centers[i] + 50)
    return 0.0


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


def analyze(path: str) -> QualityReport:
    audio = MutagenFile(path)
    if audio is None:
        raise ValueError(f"nierozpoznany format audio: {path}")
    sr = audio.info.sample_rate
    length = audio.info.length
    ext = os.path.splitext(path)[1].lower()
    bits = getattr(audio.info, "bits_per_sample", None)

    cutoff = spectral_cutoff(path, length, sr)
    eff = effective_bits(path, length) if bits and bits > 16 else None
    grade, verdict = _verdict(cutoff, ext)
    if bits and bits > 16 and eff and eff <= 16:
        grade = "warn"
        verdict += f"; deklarowane {bits}-bit, realnie {eff}-bit"
    return QualityReport(path, ext, sr, bits, eff, cutoff, grade, verdict)
