"""Testy selekta.matcher: normalize, mix_signature, score_file,
best_match, library_index + classify_track."""
from __future__ import annotations

import os

import pytest

from selekta.matcher import (
    AUDIO_EXT,
    Candidate,
    best_match,
    classify_track,
    library_index,
    mix_signature,
    normalize,
    score_file,
)
from selekta.spotify import Track
from tests.conftest import GOOD_FLAC, GOOD_MP3, GOOD_WAV


def track(artist: str, title: str, duration: float | None = None) -> Track:
    return Track(id="t", artist=artist, title=title, duration_s=duration)


# ---------------------------------------------------------------- normalize

class TestNormalize:
    def test_diacritics_folded_and_noise_dropped(self):
        assert normalize("Beyoncé — Déjà Vu (Original Mix) feat. JAY-Z") == \
            ["beyonce", "deja", "vu", "jay", "z"]

    def test_umlaut(self):
        assert normalize("Motörhead") == ["motorhead"]

    def test_noise_only_gives_empty(self):
        assert normalize("The Original Mix feat www com flac") == []

    def test_empty_string(self):
        assert normalize("") == []

    def test_case_and_separators(self):
        assert normalize("ODYMEL_-_Gucci!!!") == ["odymel", "gucci"]

    def test_digits_kept(self):
        assert normalize("Pegassi 227kg") == ["pegassi", "227kg"]


# ------------------------------------------------------------ mix_signature

class TestMixSignature:
    def test_extracts_only_mix_words(self):
        sig = mix_signature(["pegassi", "flashback", "extended", "radio", "edit"])
        assert sig == frozenset({"extended", "radio", "edit"})

    def test_no_mix_words(self):
        assert mix_signature(["odymel", "gucci"]) == frozenset()

    def test_empty(self):
        assert mix_signature([]) == frozenset()


# --------------------------------------------------------------- score_file

class TestScoreFile:
    def test_perfect_match_scores_high(self, sample):
        path = sample(GOOD_FLAC)
        c = score_file(track("Odymel", "Gucci", 274), path)
        # overlap 1.0 + 0.25 (czas) + 0.1 (zgodny brak miksu) = 1.35
        assert c.score == pytest.approx(1.35)
        assert c.duration_delta is not None and c.duration_delta < 1.0
        assert c.reason == "overlap=1.00"

    def test_duration_within_3s_gives_bonus(self, sample):
        path = sample(GOOD_FLAC)
        with_dur = score_file(track("Odymel", "Gucci", 274), path)
        without = score_file(track("Odymel", "Gucci", None), path)
        assert with_dur.score - without.score == pytest.approx(0.25)
        assert without.duration_delta is None

    def test_mix_version_conflict_penalised(self, sample):
        # Chcemy "Radio Edit" (3:30), plik to "Extended Mix" (4:46).
        path = sample("Pegassi - Flashback (Extended Mix).flac")
        conflict = score_file(track("Pegassi", "Flashback (Radio Edit)", 210), path)
        matched = score_file(track("Pegassi", "Flashback (Extended Mix)", 286), path)
        # kara -0.3 (miks) i -0.15 (delta 76 s > 45 s):
        assert conflict.score == pytest.approx(0.05)
        assert conflict.duration_delta == pytest.approx(76.4, abs=0.5)
        assert matched.score == pytest.approx(1.35)
        assert matched.score - conflict.score >= 1.0  # wyraźna różnica

    def test_no_want_tokens_scores_zero(self, sample):
        c = score_file(track("", ""), sample(GOOD_FLAC))
        assert c.score == 0.0
        assert c.duration_delta is None
        assert c.reason == "no tokens"

    def test_unrelated_track_scores_low(self, sample):
        c = score_file(track("Xxqq", "Zzww"), sample(GOOD_FLAC))
        assert c.score <= 0.2

    def test_returns_candidate_dataclass(self, sample):
        c = score_file(track("Odymel", "Gucci"), sample(GOOD_FLAC))
        assert isinstance(c, Candidate)
        assert c.path == sample(GOOD_FLAC)


# --------------------------------------------------------------- best_match

class TestBestMatch:
    def test_finds_gucci_in_real_library(self, real_lib, sample):
        sample(GOOD_FLAC)  # skip, gdy brak pliku referencyjnego
        c = best_match(track("Odymel", "Gucci", 274), real_lib)
        assert c is not None
        assert os.path.basename(c.path) == GOOD_FLAC
        assert c.score >= 1.3

    def test_empty_folder_returns_none(self, tmp_path):
        assert best_match(track("Odymel", "Gucci", 274), str(tmp_path)) is None

    def test_folder_without_audio_returns_none(self, tmp_path):
        (tmp_path / "readme.txt").write_text("nie audio")
        assert best_match(track("Odymel", "Gucci"), str(tmp_path)) is None

    def test_unmatchable_track_returns_none(self, real_lib):
        assert best_match(track("Xxqq", "Zzww"), real_lib) is None

    def test_threshold_respected(self, real_lib, sample):
        path = sample(GOOD_FLAC)
        t = track("Odymel", "Gucci", 274)
        score = score_file(t, path).score
        assert best_match(t, real_lib, threshold=score + 0.1) is None
        assert best_match(t, real_lib, threshold=score) is not None


# --------------------------------------- library_index + classify_track

class TestLibraryIndex:
    def test_index_covers_top_level_audio(self, real_lib):
        idx = library_index(real_lib)
        assert len(idx) > 0
        paths = [p for p, _, _ in idx]
        assert paths == sorted(paths)
        assert all(p.lower().endswith(AUDIO_EXT) for p in paths)
        gucci = [e for e in idx if os.path.basename(e[0]) == GOOD_FLAC]
        assert len(gucci) == 1
        _, tokens, dur = gucci[0]
        assert {"odymel", "gucci"} <= set(tokens)
        assert dur == pytest.approx(273.7, abs=0.5)

    def test_empty_folder_gives_empty_index(self, tmp_path):
        assert library_index(str(tmp_path)) == []

    @pytest.mark.parametrize("artist,title,duration,expected", [
        ("Odymel", "Gucci", 274, GOOD_FLAC),
        ("Pegassi", "MOAA (Extended)", 275, GOOD_WAV),
        ("mischluft, Sachsentrance", "We are Energy", 262, GOOD_MP3),
    ])
    def test_classify_agrees_with_best_match(
        self, real_lib, sample, artist, title, duration, expected
    ):
        sample(expected)
        t = track(artist, title, duration)
        idx = library_index(real_lib)
        via_index = classify_track(t, idx)
        via_scan = best_match(t, real_lib)
        assert via_index is not None and via_scan is not None
        assert via_index.path == via_scan.path
        assert os.path.basename(via_index.path) == expected
        assert via_index.score == pytest.approx(via_scan.score)

    def test_classify_empty_index_returns_none(self):
        assert classify_track(track("Odymel", "Gucci"), []) is None

    def test_classify_no_tokens_returns_none(self, real_lib):
        idx = library_index(real_lib)
        assert classify_track(track("", ""), idx) is None
