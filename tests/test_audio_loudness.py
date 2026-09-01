"""Testy selekta.loudness — LUFS, true peak, ReplayGain 2.0 i tagi.

Wartości odniesienia zmierzone na realnej bibliotece:
- GOOD_FLAC: integrated -7.41 LUFS, true peak +0.51 dBTP, LRA 5.2 LU,
  gain -10.59 dB (sufit -1 dBTP niewiążący),
- GOOD_MP3:  integrated -8.85 LUFS, gain -9.15 dB.
"""
from __future__ import annotations

import functools
import math
import os

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3

from selekta import loudness
from selekta.loudness import Loudness
from tests.conftest import GOOD_FLAC, GOOD_MP3

REF = Loudness(-7.41, 0.51, 5.2, -10.59)


@functools.lru_cache(maxsize=None)
def _analyze(path: str) -> Loudness:
    return loudness.analyze(path)


def _copy(lib_copy: str, name: str) -> str:
    p = os.path.join(lib_copy, name)
    if not os.path.isfile(p):
        pytest.skip(f"brak kopii {name}")
    return p


def _assert_peak_ceiling(l: Loudness) -> None:
    """Po korekcie true peak nie może przekroczyć -1 dBTP."""
    assert l.gain_db <= -1.0 - l.true_peak_dbtp + 1e-6


# ---------------------------------------------------------------- analyze()

@pytest.mark.slow
def test_analyze_good_flac(sample):
    l = _analyze(sample(GOOD_FLAC))
    assert -14.0 <= l.integrated_lufs <= -4.0   # zmierzone -7.41
    assert l.gain_db < 0.0                      # głośny master -> korekta w dół
    _assert_peak_ceiling(l)
    assert 0.0 < l.loudness_range_lu < 20.0     # zmierzone 5.2
    assert -1.0 < l.true_peak_dbtp < 2.0        # zmierzone +0.51
    # sufit -1 dBTP tu nie wiąże, więc gain == -18 - integrated
    assert l.gain_db == pytest.approx(-18.0 - l.integrated_lufs, abs=1e-6)


@pytest.mark.slow
def test_analyze_good_mp3(sample):
    l = _analyze(sample(GOOD_MP3))
    assert -14.0 <= l.integrated_lufs <= -4.0   # zmierzone -8.85
    assert l.gain_db < 0.0
    _assert_peak_ceiling(l)


def test_analyze_nonexistent_returns_nans_and_zero_gain():
    l = loudness.analyze("/nie/ma/takiego/pliku.flac")
    assert math.isnan(l.integrated_lufs)
    assert math.isnan(l.true_peak_dbtp)
    assert math.isnan(l.loudness_range_lu)
    assert l.gain_db == 0.0


# ---------------------------------------------------------------- obliczenia

def test_compute_gain_cases():
    nan = float("nan")
    # nieudany pomiar -> brak korekty
    assert loudness._compute_gain(nan, 0.0) == 0.0
    # utwór dokładnie na referencji, peak nisko -> zero korekty
    assert loudness._compute_gain(-18.0, -5.0) == 0.0
    # cichy utwór, ale wysoki peak -> sufit -1 dBTP wiąże
    assert loudness._compute_gain(-20.0, -0.5) == pytest.approx(-0.5)
    # głośny master (wartości GOOD_FLAC)
    assert loudness._compute_gain(-7.41, 0.51) == pytest.approx(-10.59)
    # NaN w true peak -> korekta bez sufitu
    assert loudness._compute_gain(-30.0, nan) == pytest.approx(12.0)


def test_true_peak_linear():
    assert loudness.true_peak_linear(Loudness(-10.0, 0.0, 5.0, -8.0)) == 1.0
    assert loudness.true_peak_linear(Loudness(-10.0, -6.0206, 5.0, -8.0)) == pytest.approx(0.5, abs=1e-4)
    assert loudness.true_peak_linear(REF) == pytest.approx(1.060474, abs=1e-5)
    nan_l = Loudness(float("nan"), float("nan"), float("nan"), 0.0)
    assert math.isnan(loudness.true_peak_linear(nan_l))


# ---------------------------------------------------------------- write_tags

def test_write_tags_flac_roundtrip_idempotent(lib_copy):
    p = _copy(lib_copy, GOOD_FLAC)
    loudness.write_tags(p, REF)
    loudness.write_tags(p, REF)  # drugi zapis: bez duplikatów
    audio = FLAC(p)
    assert audio["REPLAYGAIN_TRACK_GAIN"] == ["-10.59 dB"]
    assert audio["REPLAYGAIN_TRACK_PEAK"] == ["1.060474"]


def test_write_tags_mp3_roundtrip_idempotent(lib_copy):
    p = _copy(lib_copy, GOOD_MP3)
    title_before = ID3(p).getall("TIT2")
    loudness.write_tags(p, REF)
    loudness.write_tags(p, REF)
    tags = ID3(p)
    gain = tags.getall("TXXX:REPLAYGAIN_TRACK_GAIN")
    peak = tags.getall("TXXX:REPLAYGAIN_TRACK_PEAK")
    assert len(gain) == 1 and gain[0].text == ["-10.59 dB"]
    assert len(peak) == 1 and peak[0].text == ["1.060474"]
    # pozostałe tagi mają zostać nietknięte
    assert [f.text for f in tags.getall("TIT2")] == [f.text for f in title_before]


def test_write_tags_nan_writes_nothing(lib_copy):
    p = _copy(lib_copy, GOOD_MP3)
    nan = float("nan")
    loudness.write_tags(p, Loudness(nan, nan, nan, 0.0))
    tags = ID3(p)
    assert tags.getall("TXXX:REPLAYGAIN_TRACK_GAIN") == []
    assert tags.getall("TXXX:REPLAYGAIN_TRACK_PEAK") == []


@pytest.mark.slow
def test_measure_and_write_full_loop_flac(lib_copy):
    """Pełny obieg: pomiar kopii FLAC -> zapis tagów -> odczyt i porównanie."""
    p = _copy(lib_copy, GOOD_FLAC)
    l = loudness.analyze(p)
    assert not math.isnan(l.integrated_lufs)
    loudness.write_tags(p, l)
    audio = FLAC(p)
    gain_s = audio["REPLAYGAIN_TRACK_GAIN"][0]
    assert gain_s.endswith(" dB")
    assert float(gain_s.split()[0]) == pytest.approx(l.gain_db, abs=0.005)
    peak_s = audio["REPLAYGAIN_TRACK_PEAK"][0]
    assert float(peak_s) == pytest.approx(loudness.true_peak_linear(l), abs=1e-6)


# ---------------------------------------------------------------- raport

def test_format_report_polish_exact():
    assert loudness.format_report(REF) == (
        "głośność -7.4 LUFS | true peak +0.5 dBTP | "
        "zakres 5.2 LU | ReplayGain -10.59 dB"
    )


def test_format_report_positive_gain_sign():
    report = loudness.format_report(Loudness(-20.0, -6.0, 8.0, 2.0))
    assert "głośność -20.0 LUFS" in report
    assert "true peak -6.0 dBTP" in report
    assert "ReplayGain +2.00 dB" in report


def test_format_report_failed_measurement():
    nan = float("nan")
    assert loudness.format_report(Loudness(nan, nan, nan, 0.0)) == (
        "głośność: błąd dekodowania — brak pomiaru"
    )
