"""Testy selekta.verify_match — akustyczna weryfikacja tożsamości pliku.

Część czysta (bez sieci): _decode, _band_envelopes, _ncc_curve, verify na
śmieciowym preview. Część @network: prawdziwy preview Spotify utworu ACID
(Hardwell, Maddix, Luciana) vs realny plik FLAC — pozytyw i negatyw.
"""
from __future__ import annotations

import numpy as np
import pytest
import requests

from selekta import spotify, verify_match
from selekta.spotify import Track
from selekta.verify_match import MatchResult
from tests.conftest import GOOD_FLAC, real_path

ACID_ID = "6JkQb1qCCJDBV7kW5vJUAH"
ACID_FLAC = "Hardwell, Maddix, Luciana - ACID (Extended Mix).flac"


# ---------------------------------------------------------------- czyste

def test_decode_returns_float32_mono(sample):
    x = verify_match._decode(sample(GOOD_FLAC), max_s=5.0)
    assert x.dtype == np.float32
    # 5 s przy 11025 Hz: ffmpeg tnie na granicy ramki, stąd luźna tolerancja
    assert 4.5 * verify_match.SR <= len(x) <= 5.5 * verify_match.SR
    assert float(np.abs(x).max()) <= 1.5  # próbki w sensownym zakresie


def test_decode_nonexistent_file_empty():
    x = verify_match._decode("/nie/ma/takiego/pliku.flac")
    assert isinstance(x, np.ndarray)
    assert len(x) == 0


def test_band_envelopes_too_short_input():
    env = verify_match._band_envelopes(np.zeros(10, dtype=np.float32))
    assert env.shape == (0, verify_match.N_BANDS)


def test_band_envelopes_shape_on_noise():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(verify_match.SR * 3).astype(np.float32)
    env = verify_match._band_envelopes(x)
    n_frames = (len(x) - verify_match.N_FFT) // verify_match.HOP
    assert env.shape == (n_frames - 1, verify_match.N_BANDS)  # diff zjada 1 ramkę
    assert np.all(env >= 0)  # flux jest nieujemny


def test_ncc_curve_preview_too_short():
    track_b = np.ones((500, verify_match.N_BANDS))
    prev_b = np.ones((10, verify_match.N_BANDS))  # < ~1 s ramek
    assert len(verify_match._ncc_curve(track_b, prev_b)) == 0


def test_ncc_curve_track_shorter_than_preview():
    track_b = np.ones((50, verify_match.N_BANDS))
    prev_b = np.ones((100, verify_match.N_BANDS))
    assert len(verify_match._ncc_curve(track_b, prev_b)) == 0


def test_verify_garbage_preview_is_mismatch(sample):
    res = verify_match.verify(sample(GOOD_FLAC), b"to nie jest audio")
    assert isinstance(res, MatchResult)
    assert res.verdict == "mismatch"
    assert res.score == 0.0


def test_preview_bytes_no_url_returns_none():
    t = Track(id="x", artist="a", title="b", preview_url="")
    assert verify_match.preview_bytes(t) is None


def test_verify_track_without_preview_returns_none(sample):
    t = Track(id="", artist="a", title="b", preview_url="")
    assert verify_match.verify_track(sample(GOOD_FLAC), t) is None


def test_matchresult_defaults():
    r = MatchResult(0.7, 12.5, "match")
    assert (r.score, r.offset_s, r.verdict, r.note) == (0.7, 12.5, "match", "")


# ---------------------------------------------------------------- sieć

@pytest.fixture(scope="module")
def acid_track():
    try:
        t = spotify.track(ACID_ID)
    except (requests.RequestException, RuntimeError) as exc:
        pytest.skip(f"Spotify niedostępne: {exc}")
    if not t.preview_url:
        pytest.skip("Spotify nie udostępnia preview dla ACID")
    return t


@pytest.fixture(scope="module")
def acid_preview(acid_track):
    try:
        data = verify_match.preview_bytes(acid_track)
    except requests.RequestException as exc:
        pytest.skip(f"nie udało się pobrać preview: {exc}")
    if not data:
        pytest.skip("preview puste / za małe")
    return data


@pytest.mark.network
def test_spotify_track_metadata(acid_track):
    assert "Hardwell" in acid_track.artist
    assert acid_track.title == "ACID"
    assert acid_track.duration_s and 150 < acid_track.duration_s < 240


@pytest.mark.network
def test_acid_preview_matches_real_file(acid_preview):
    res = verify_match.verify(real_path(ACID_FLAC), acid_preview)
    assert res.verdict == "match"
    assert 0.5 < res.score <= 1.2
    assert 0.0 <= res.offset_s < 600.0


@pytest.mark.network
def test_verify_track_wrapper_match(acid_track):
    res = verify_match.verify_track(real_path(ACID_FLAC), acid_track)
    assert res is not None
    assert res.verdict == "match"
    assert res.score > 0.5


@pytest.mark.network
def test_acid_preview_vs_other_track_mismatch(acid_preview):
    """Negatyw: preview ACID przyłożony do zupełnie innego utworu (Gucci)."""
    res = verify_match.verify(real_path(GOOD_FLAC), acid_preview)
    assert res.verdict == "mismatch"
    assert res.score < 0.3
