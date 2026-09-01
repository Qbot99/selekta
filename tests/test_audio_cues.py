"""Testy selekta.cues — struktura utworu (intro/outro/drop/pierwsze uderzenie).

Wartości odniesienia zmierzone na realnej bibliotece:
- GOOD_FLAC:    duration 273.699 s, first_beat 9.009, intro_end 81.688,
                outro_start 272.091, drop 193.933,
- CORRUPT_FLAC: 4 błędy dekodowania na końcu pliku — analiza nie może się
                wywalić, a punkty muszą zachować porządek.
"""
from __future__ import annotations

import functools
import subprocess

import pytest

from selekta import cues
from selekta.cues import Cues
from tests.conftest import CORRUPT_FLAC, GOOD_FLAC


@functools.lru_cache(maxsize=None)
def _analyze(path: str, bpm: float | None = None) -> Cues:
    return cues.analyze(path, bpm=bpm)


def _assert_ordering(c: Cues) -> None:
    """Inwariant modułu: 0 <= first_beat < intro_end < outro_start <= duration."""
    assert 0.0 <= c.first_beat_s < c.intro_end_s < c.outro_start_s <= c.duration_s
    if c.drop_s is not None:
        assert c.intro_end_s < c.drop_s < c.outro_start_s


# ---------------------------------------------------------------- analyze()

def test_good_flac_cue_points(sample):
    c = _analyze(sample(GOOD_FLAC))
    _assert_ordering(c)
    assert 270.0 < c.duration_s < 277.0
    assert 7.0 < c.first_beat_s < 11.0     # zmierzone 9.009
    assert 75.0 < c.intro_end_s < 90.0     # zmierzone 81.688
    assert c.outro_start_s > 260.0         # zmierzone 272.091
    assert c.drop_s is not None            # zmierzone 193.933
    assert 180.0 < c.drop_s < 210.0


def test_corrupt_flac_does_not_crash_and_keeps_order(sample):
    c = _analyze(sample(CORRUPT_FLAC))
    _assert_ordering(c)
    assert 200.0 < c.duration_s < 220.0    # zmierzone 210.0


def test_bpm_hint_keeps_first_beat_close(sample):
    p = sample(GOOD_FLAC)
    base = _analyze(p)
    hinted = cues.analyze(p, bpm=146.0)
    _assert_ordering(hinted)
    # dociągnięcie do bitu może przesunąć punkt najwyżej o ~pół bitu
    assert abs(hinted.first_beat_s - base.first_beat_s) <= 0.5


def test_nonexistent_file_returns_zero_cues():
    c = cues.analyze("/nie/ma/takiego/pliku.flac")
    assert c == Cues(0.0, 0.0, 0.0, 0.0, None)


def test_empty_file_returns_zero_cues(tmp_path):
    p = tmp_path / "pusty.wav"
    p.write_bytes(b"")
    c = cues.analyze(str(p))
    assert c == Cues(0.0, 0.0, 0.0, 0.0, None)


def test_too_short_material_returns_sane_zeros(tmp_path):
    """2-sekundowy sinus < MIN_LEN_S -> zera z prawdziwą długością, bez wyjątku."""
    p = tmp_path / "krotki.wav"
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2", str(p)],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    c = cues.analyze(str(p))
    assert 1.9 <= c.duration_s <= 2.1
    assert c.first_beat_s == 0.0
    assert c.intro_end_s == 0.0
    assert c.outro_start_s == pytest.approx(c.duration_s, abs=0.01)
    assert c.drop_s is None


# ---------------------------------------------------------------- raport

def test_format_report_exact_mmss():
    c = Cues(273.699, 9.009, 81.688, 272.091, 193.933)
    assert cues.format_report(c) == (
        "Czas 4:34 | pierwsze uderzenie 0:09 | koniec intra 1:22 | "
        "początek outra 4:32 | drop 3:14"
    )


def test_format_report_without_drop():
    c = Cues(10.0, 0.0, 1.0, 9.0, None)
    report = cues.format_report(c)
    assert "drop brak" in report
    assert "Czas 0:10" in report


def test_format_report_contains_mmss_for_real_file(sample):
    import re
    report = cues.format_report(_analyze(sample(GOOD_FLAC)))
    assert re.search(r"\b\d+:\d{2}\b", report)
    assert "Czas 4:34" in report
    assert "pierwsze uderzenie 0:09" in report


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.0, "0:00"),
        (59.6, "1:00"),   # zaokrąglanie w górę
        (61.0, "1:01"),
        (-5.0, "0:00"),   # ujemne obcinane do zera
        (600.0, "10:00"),
    ],
)
def test_mmss(seconds, expected):
    assert cues._mmss(seconds) == expected
