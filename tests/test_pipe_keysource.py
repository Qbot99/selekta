"""Testy selekta.keysource — przeliczanie tonacji na Camelot i uzgadnianie
wyniku detektora z oficjalnymi danymi Beatportu. Całość offline.
"""
from __future__ import annotations

import pytest

from selekta.keysource import LOW_CONF, _camelot_from_key, reconcile, to_camelot


# ---------------------------------------------------------------- to_camelot

@pytest.mark.parametrize(
    "name,expected",
    [
        ("A minor", "8A"),
        ("Am", "8A"),
        ("A min", "8A"),
        ("am", "8A"),              # małe litery
        ("C maj", "8B"),
        ("C", "8B"),               # sama nuta => dur (konwencja tagów)
        ("F# major", "2B"),
        ("F#maj", "2B"),           # bez spacji
        ("Gb Major", "2B"),        # enharmonia: Gb == F#
        ("B♭m", "3A"),             # unicode bemol
        ("Eb minor", "2A"),
        ("Db major", "3B"),
        ("E# major", "7B"),        # enharmonia: E# == F
        ("Cb major", "1B"),        # enharmonia: Cb == B
        ("B#m", "5A"),             # enharmonia: B# == C
        ("G Minor", "6A"),
        ("A", "11B"),
        ("bzdura", None),          # zaczyna się od litery b, ale to nie tonacja
        ("garbage", None),
        ("12A", None),             # kod Camelot to nie nazwa muzyczna
        ("Xyz", None),
        ("", None),
    ],
)
def test_to_camelot(name, expected):
    assert to_camelot(name) == expected


def test_to_camelot_none_input():
    assert to_camelot(None) is None


# ---------------------------------------------------------------- _camelot_from_key

def test_camelot_from_key_dict_with_ready_camelot():
    key = {"camelot_number": 8, "camelot_letter": "a", "name": "A Minor"}
    assert _camelot_from_key(key) == ("8A", "A Minor")


def test_camelot_from_key_dict_name_only():
    assert _camelot_from_key({"name": "F Minor"}) == ("4A", "F Minor")


def test_camelot_from_key_plain_string():
    assert _camelot_from_key("Gb Major") == ("2B", "Gb Major")


def test_camelot_from_key_garbage_types():
    assert _camelot_from_key(None) == (None, None)
    assert _camelot_from_key(42) == (None, None)
    assert _camelot_from_key({}) == (None, None)


# ---------------------------------------------------------------- reconcile

def test_reconcile_no_official_keeps_detector():
    cam, bpm, note = reconcile("8a", 146.0, 0.9, None)
    assert cam == "8A"              # normalizacja do wielkich liter
    assert bpm == 146.0
    assert "tylko detektor" in note


def test_reconcile_no_official_empty_detection():
    cam, bpm, note = reconcile("", 120.0, 0.1, None)
    assert cam == "?"
    assert bpm == 120.0
    assert "tylko detektor" in note


def test_reconcile_low_confidence_disagreement_takes_beatport():
    cam, bpm, note = reconcile("8A", 146.0, 0.3, {"key_camelot": "8B", "bpm": 146})
    assert cam == "8B"
    assert "z Beatport" in note and "8A" in note   # notka wymienia sugestię detektora
    assert bpm == 146.0


def test_reconcile_high_confidence_disagreement_still_takes_beatport():
    cam, _, note = reconcile("5A", 130.0, 0.95, {"key_camelot": "12B", "bpm": None})
    assert cam == "12B"
    assert "detektor sugerował 5A" in note


def test_reconcile_agreement_keeps_detector():
    cam, bpm, note = reconcile("8A", 146.0, 0.9, {"key_camelot": "8A", "bpm": 146})
    assert cam == "8A"
    assert "zgodna z Beatport" in note
    assert bpm == 146.0


def test_reconcile_agreement_low_confidence_confirmed_by_beatport():
    cam, _, note = reconcile("8A", 146.0, LOW_CONF - 0.1,
                             {"key_camelot": "8A", "bpm": 146})
    assert cam == "8A"
    assert "potwierdzona" in note


def test_reconcile_bpm_differs_over_tolerance_takes_official():
    cam, bpm, note = reconcile("8A", 146.0, 0.9, {"key_camelot": "8A", "bpm": 148})
    assert bpm == 148.0
    assert "BPM z Beatport: 148" in note


def test_reconcile_bpm_within_tolerance_keeps_detected():
    _, bpm, note = reconcile("8A", 146.4, 0.9, {"key_camelot": "8A", "bpm": 146})
    assert bpm == 146.4             # różnica 0.4 <= 1.0 => zostaje detektor
    assert "zgodny z Beatport" in note


def test_reconcile_official_without_key_keeps_detector_key():
    cam, bpm, note = reconcile("8A", 146.0, 0.9, {"key_camelot": None, "bpm": None})
    assert cam == "8A"
    assert "Beatport bez tonacji" in note
    assert bpm == 146.0


def test_reconcile_case_insensitive_camelot_compare():
    cam, _, note = reconcile("8a", 146.0, 0.9, {"key_camelot": "8a", "bpm": None})
    assert cam == "8A"
    assert "zgodna" in note
