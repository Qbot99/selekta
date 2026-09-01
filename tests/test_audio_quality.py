"""Testy selekta.quality — detektor fake-lossless (cutoff pasma) i realnej
bitowości.

Wartości odniesienia zmierzone na realnych plikach biblioteki:
- GOOD_FLAC  -> cutoff 22000 Hz, grade "ok" (prawdziwy lossless, 16-bit),
- FAKE_FLAC  -> cutoff 16400 Hz, grade "bad" (źródło ~128k w kontenerze FLAC 24-bit),
- GOOD_MP3   -> cutoff 19600 Hz (typowe pasmo dobrego MP3),
- GOOD_WAV   -> 24-bit nominalnie i realnie (effective_bits == 24).
"""
from __future__ import annotations

import functools
import os

import pytest
from mutagen import File as MutagenFile
from mutagen import MutagenError

from selekta import quality
from tests.conftest import FAKE_FLAC, GOOD_FLAC, GOOD_MP3, GOOD_WAV


@functools.lru_cache(maxsize=None)
def _analyze(path: str) -> quality.QualityReport:
    """Jedna analiza na plik, współdzielona między testami."""
    return quality.analyze(path)


# ---------------------------------------------------------------- analyze()

def test_good_flac_is_true_lossless(sample):
    r = _analyze(sample(GOOD_FLAC))
    assert r.grade == "ok"
    assert r.cutoff_hz > 20500
    assert r.cutoff_hz <= 22050  # nie więcej niż Nyquist dla 44.1 kHz
    assert r.ext == ".flac"
    assert r.sample_rate == 44100
    assert r.nominal_bits == 16
    # dla plików 16-bitowych realna bitowość nie jest liczona
    assert r.effective_bits is None
    assert "lossless" in r.verdict


def test_fake_flac_detected_as_bad(sample):
    r = _analyze(sample(FAKE_FLAC))
    assert r.grade == "bad"
    assert 15000 <= r.cutoff_hz <= 18000
    assert "~16 kHz" in r.verdict
    assert r.ext == ".flac"


def test_good_mp3_cutoff_range(sample):
    r = _analyze(sample(GOOD_MP3))
    assert 19000 <= r.cutoff_hz <= 21000
    assert r.ext == ".mp3"
    # MP3 nie deklaruje bitowości -> oba pola bitowe puste
    assert r.nominal_bits is None
    assert r.effective_bits is None
    # dobre MP3 nie może dostać oceny "bad"
    assert r.grade in ("ok", "warn")


def test_good_wav_real_24bit(sample):
    r = _analyze(sample(GOOD_WAV))
    assert r.nominal_bits == 24
    assert r.effective_bits == 24
    assert r.cutoff_hz > 20500
    assert r.grade == "ok"


# ------------------------------------------------- funkcje pomiarowe wprost

def test_spectral_cutoff_direct_on_wav(sample):
    p = sample(GOOD_WAV)
    info = MutagenFile(p).info
    c = quality.spectral_cutoff(p, info.length, info.sample_rate)
    assert 20500 < c <= info.sample_rate / 2


def test_effective_bits_direct_on_wav(sample):
    p = sample(GOOD_WAV)
    info = MutagenFile(p).info
    assert quality.effective_bits(p, info.length) == 24


def test_spectral_cutoff_nonexistent_returns_zero():
    assert quality.spectral_cutoff("/nie/ma/takiego/pliku.flac", 300.0, 44100) == 0.0


def test_effective_bits_nonexistent_returns_zero():
    assert quality.effective_bits("/nie/ma/takiego/pliku.flac", 300.0) == 0


# ---------------------------------------------------------------- _verdict()

@pytest.mark.parametrize(
    "cutoff, ext, grade",
    [
        (22000.0, ".flac", "ok"),
        (22000.0, ".mp3", "ok"),
        (20000.0, ".mp3", "ok"),      # typowe 320 kbps
        (20000.0, ".flac", "warn"),   # lossless z pasmem MP3 -> transkod?
        (19000.0, ".flac", "warn"),   # ~256 kbps / V0
        (16400.0, ".flac", "bad"),    # ~128-192 kbps
        (10000.0, ".flac", "bad"),    # bardzo wąskie pasmo
    ],
)
def test_verdict_thresholds(cutoff, ext, grade):
    g, verdict = quality._verdict(cutoff, ext)
    assert g == grade
    assert isinstance(verdict, str) and verdict


def test_verdict_transcode_warning_text():
    g, verdict = quality._verdict(20000.0, ".flac")
    assert g == "warn"
    assert "transkod" in verdict


# ---------------------------------------------------------------- błędy IO

def test_analyze_nonexistent_raises_mutagen_error():
    with pytest.raises(MutagenError):
        quality.analyze("/nie/ma/takiego/pliku.flac")


def test_analyze_unrecognized_format_sane_error(tmp_path):
    p = tmp_path / "garbage.dat"
    p.write_bytes(b"\x00\x01to nie jest audio" * 500)
    # oczekiwane: sensowny wyjątek (MutagenError/ValueError), nie crash na None
    with pytest.raises((MutagenError, ValueError)):
        quality.analyze(str(p))
