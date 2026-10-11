"""Testy selekta.harmonic — BPM, klucz (Camelot), porządkowanie setu, tagi.

Wartości odniesienia zmierzone na realnej bibliotece:
- GOOD_FLAC (Odymel - Gucci): bpm 145.6, key "A minor", camelot "8A".
"""
from __future__ import annotations

import dataclasses
import functools
import os

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3

from selekta import harmonic
from selekta.harmonic import TrackAnalysis
from tests.conftest import GOOD_FLAC, GOOD_MP3


@functools.lru_cache(maxsize=None)
def _analyze(path: str) -> TrackAnalysis:
    return harmonic.analyze(path)


def _copy(lib_copy: str, name: str) -> str:
    p = os.path.join(lib_copy, name)
    if not os.path.isfile(p):
        pytest.skip(f"brak kopii {name}")
    return p


def _ta(bpm: float, key: str, camelot: str) -> TrackAnalysis:
    return TrackAnalysis(bpm, key, camelot, 0.5, 0.9)


# ---------------------------------------------------------------- analyze()

def test_analyze_gucci_bpm_and_key(sample):
    ta = _analyze(sample(GOOD_FLAC))
    assert ta.camelot == "8A"
    assert 145.0 <= ta.bpm <= 147.0
    assert ta.key == "A minor"
    assert 0.0 < ta.confidence_bpm <= 1.0
    assert 0.0 < ta.confidence_key <= 1.0


def test_trackanalysis_has_all_fields():
    names = [f.name for f in dataclasses.fields(TrackAnalysis)]
    assert names == ["bpm", "key", "camelot", "confidence_bpm", "confidence_key"]


def test_analyze_nonexistent_returns_placeholder():
    ta = harmonic.analyze("/nie/ma/takiego/pliku.flac")
    assert ta == TrackAnalysis(0.0, "?", "?", 0.0, 0.0)


# ---------------------------------------------------------------- standard_key

@pytest.mark.parametrize(
    "key, expected",
    [
        ("A minor", "Am"),
        ("F# minor", "F#m"),
        ("C major", "C"),
        ("A# major", "A#"),
    ],
)
def test_standard_key(key, expected):
    assert harmonic.standard_key(_ta(120.0, key, "1A")) == expected


# ---------------------------------------------------------------- order_set

def test_order_set_empty():
    assert harmonic.order_set([]) == []


def test_order_set_single_item():
    ta = _ta(146.0, "A minor", "8A")
    out = harmonic.order_set([("only.flac", ta)])
    assert out == [("only.flac", ta, "start")]


def test_order_set_starts_from_lowest_bpm_and_annotates():
    a = ("a.flac", _ta(146.0, "A minor", "8A"))
    b = ("b.flac", _ta(148.0, "E minor", "9A"))
    c = ("c.flac", _ta(174.0, "C# major", "3B"))
    # wejście celowo przetasowane — start musi wypaść na najniższym BPM
    out = harmonic.order_set([c, b, a])
    assert [row[0] for row in out] == ["a.flac", "b.flac", "c.flac"]
    assert out[0][2] == "start"
    assert out[1][2] == "8A->9A, 146->148"
    assert out[2][2] == "9A->3B, 148->174"


def test_order_set_zero_bpm_never_starts():
    unknown = ("x.flac", _ta(0.0, "?", "?"))
    known = ("a.flac", _ta(146.0, "A minor", "8A"))
    out = harmonic.order_set([unknown, known])
    assert out[0][0] == "a.flac"
    assert out[0][2] == "start"
    assert out[1][0] == "x.flac"
    assert out[1][2] == "8A->?, 146->0"


# --------------------------------------------- koszty przejść (pomocnicze)

@pytest.mark.parametrize(
    "c1, c2, dist",
    [
        ("8A", "8A", 0.0),
        ("8A", "9A", 1.0),   # sąsiedni numer, ta sama litera
        ("8A", "8B", 1.0),   # ten sam numer, inna litera
        ("1A", "12A", 1.0),  # koło Camelota się zawija
        ("8A", "2B", 7.0),   # 6 numerów + zmiana litery
        ("?", "8A", 3.0),    # klucz nieznany -> neutralna kara
    ],
)
def test_camelot_distance(c1, c2, dist):
    assert harmonic._camelot_distance(c1, c2) == dist


def test_bpm_cost_shape():
    assert harmonic._bpm_cost(146.0, 146.0) == 0.0
    # w obrębie +-6 % koszt < 1
    assert 0.9 < harmonic._bpm_cost(100.0, 106.0) < 1.0
    # daleko poza zakresem pitch — koszt stromo rośnie
    assert harmonic._bpm_cost(100.0, 130.0) > 10.0
    # nieznane BPM -> stała kara
    assert harmonic._bpm_cost(0.0, 120.0) == 3.0
    assert harmonic._bpm_cost(120.0, 0.0) == 3.0


# ---------------------------------------------------------------- write_tags

def test_write_tags_flac_roundtrip(lib_copy):
    p = _copy(lib_copy, GOOD_FLAC)
    harmonic.write_tags(p, TrackAnalysis(145.6, "A minor", "8A", 0.42, 1.0))
    audio = FLAC(p)
    assert audio["BPM"] == ["145.6"]
    assert audio["INITIALKEY"] == ["Am"]
    assert audio["COMMENT"] == ["8A"]


def test_write_tags_flac_keeps_user_comment(lib_copy):
    """Przegląd 0.4.2: komentarz „Kupione na Beatport — zagrać po 2 w nocy”
    został zastąpiony przez „8A”."""
    p = _copy(lib_copy, GOOD_FLAC)
    audio = FLAC(p)
    audio["COMMENT"] = "Kupione na Beatport — zagrać po 2 w nocy"
    audio.save()
    harmonic.write_tags(p, TrackAnalysis(145.6, "A minor", "8A", 0.42, 1.0))
    harmonic.write_tags(p, TrackAnalysis(145.6, "A minor", "8A", 0.42, 1.0))
    audio = FLAC(p)
    assert audio["COMMENT"] == ["Kupione na Beatport — zagrać po 2 w nocy"]
    assert audio["CAMELOT"] == ["8A"]
    assert audio["INITIALKEY"] == ["Am"]


def test_write_tags_flac_integer_bpm_formatting(lib_copy):
    p = _copy(lib_copy, GOOD_FLAC)
    harmonic.write_tags(p, TrackAnalysis(146.0, "F# minor", "11A", 0.5, 0.9))
    audio = FLAC(p)
    assert audio["BPM"] == ["146"]  # %g: bez zbędnego ".0"
    assert audio["INITIALKEY"] == ["F#m"]
    assert audio["COMMENT"] == ["11A"]


def test_write_tags_mp3_roundtrip_idempotent(lib_copy):
    p = _copy(lib_copy, GOOD_MP3)
    ta = TrackAnalysis(145.6, "A minor", "8A", 0.42, 1.0)
    harmonic.write_tags(p, ta)
    harmonic.write_tags(p, ta)  # drugi zapis nie może mnożyć ramek
    tags = ID3(p)
    tbpm = tags.getall("TBPM")
    tkey = tags.getall("TKEY")
    camelot = tags.getall("TXXX:CAMELOT")
    assert len(tbpm) == 1 and tbpm[0].text == ["145.6"]
    assert len(tkey) == 1 and tkey[0].text == ["Am"]
    assert len(camelot) == 1 and camelot[0].text == ["8A"]


def test_analyze_then_write_tags_full_loop(sample, lib_copy):
    ta = _analyze(sample(GOOD_FLAC))
    p = _copy(lib_copy, GOOD_FLAC)
    harmonic.write_tags(p, ta)
    audio = FLAC(p)
    assert audio["INITIALKEY"] == ["Am"]
    assert audio["COMMENT"] == ["8A"]
    assert 145.0 <= float(audio["BPM"][0]) <= 147.0
