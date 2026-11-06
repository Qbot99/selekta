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


def test_verify_track_without_preview_returns_none(sample, monkeypatch):
    monkeypatch.setattr(verify_match, "preview_itunes", lambda a, t: None)
    t = Track(id="", artist="a", title="b", preview_url="")
    assert verify_match.verify_track(sample(GOOD_FLAC), t) is None


class _Odpowiedz:
    ok = True
    content = b"x" * 20_000

    def __init__(self, wyniki=None):
        self.wyniki = wyniki

    def json(self):
        return {"results": self.wyniki}


def _itunes(monkeypatch, wyniki):
    """Atrapa iTunes; zwraca listę adresów próbek, które pobrano."""
    pobrane = []

    def get(url, **_kw):
        if "itunes.apple.com/search" in url:
            return _Odpowiedz(wyniki)
        pobrane.append(url)
        return _Odpowiedz()
    monkeypatch.setattr(verify_match.requests, "get", get)
    return pobrane


def _wynik(artysta, tytul, url):
    return {"artistName": artysta, "trackName": tytul, "previewUrl": url}


def test_probka_z_itunes_nie_bierze_cudzego_utworu(monkeypatch):
    """„a" / „b" dostało próbkę „Autumnal Daydream (Key Ab Ver.)", bo tytuł
    był tylko fragmentem nazwy, a wykonawcy nikt nie sprawdzał."""
    pobrane = _itunes(monkeypatch, [
        _wynik("Precious Parade", "Autumnal Daydream (Key Ab Ver.)", "http://cudzy")])
    assert verify_match.preview_itunes("a", "b") is None
    assert pobrane == []


def test_probka_z_itunes_ten_sam_tytul_cudzego_wykonawcy(monkeypatch):
    pobrane = _itunes(monkeypatch, [
        _wynik("Braaheim", "Black Betty (Extended Mix)", "http://cudzy"),
        _wynik("Ram Jam", "Black Betty", "http://wlasciwy")])
    assert verify_match.preview_itunes("Ram Jam", "Black Betty") is not None
    assert pobrane == ["http://wlasciwy"]


def test_probka_z_itunes_ta_sama_wersja_przed_remiksem(monkeypatch):
    pobrane = _itunes(monkeypatch, [
        _wynik("Madonna", "Frozen (Sultan Remix)", "http://remiks"),
        _wynik("Madonna", "Frozen", "http://oryginal")])
    assert verify_match.preview_itunes("Madonna", "Frozen") is not None
    assert pobrane == ["http://oryginal"]


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


class TestDrugieZrodloProbki:
    """Przegląd 0.4.2: Dancing Queen — Spotify 0,25 („odrzuć"), iTunes 0,79."""

    def _ustaw(self, monkeypatch, spotify_wynik, itunes_wynik):
        from selekta import verify_match as vm
        monkeypatch.setattr(vm, "preview_bytes", lambda t: b"spotify" if spotify_wynik else None)
        monkeypatch.setattr(vm, "verify", lambda path, data: spotify_wynik)
        monkeypatch.setattr(vm, "verify_by_name", lambda path, a, t: (
            (itunes_wynik, "ABBA — Dancing Queen") if itunes_wynik else None))
        return vm

    def test_drugie_zrodlo_ratuje_wlasciwy_plik(self, monkeypatch):
        from selekta.spotify import Track
        from selekta.verify_match import MatchResult
        vm = self._ustaw(monkeypatch, MatchResult(0.25, 10, "mismatch"),
                         MatchResult(0.79, 40, "match"))
        r = vm.verify_track("x.flac", Track(id="1", artist="ABBA", title="Dancing Queen",
                                            preview_url="u"))
        assert r.verdict == "match" and r.score == 0.79
        assert "Spotify 0.25" in r.note and "iTunes 0.79" in r.note

    def test_oba_zrodla_niezgodne_to_niezgodnosc(self, monkeypatch):
        from selekta.spotify import Track
        from selekta.verify_match import MatchResult
        vm = self._ustaw(monkeypatch, MatchResult(0.04, 0, "mismatch"),
                         MatchResult(0.05, 0, "mismatch"))
        r = vm.verify_track("x.flac", Track(id="1", artist="A", title="B", preview_url="u"))
        assert r.verdict == "mismatch" and "iTunes też nie potwierdza" in r.note

    def test_zgodnosc_ze_spotify_nie_pyta_itunes(self, monkeypatch):
        from selekta.spotify import Track
        from selekta.verify_match import MatchResult
        vm = self._ustaw(monkeypatch, MatchResult(0.8, 0, "match"), None)
        monkeypatch.setattr(vm, "verify_by_name", lambda *a: pytest.fail("zbędne"))
        assert vm.verify_track("x", Track(id="1", artist="A", title="B", preview_url="u")).verdict == "match"

    def test_bez_probki_spotify_bierze_itunes(self, monkeypatch):
        from selekta.spotify import Track
        from selekta.verify_match import MatchResult
        vm = self._ustaw(monkeypatch, None, MatchResult(0.7, 5, "match"))
        r = vm.verify_track("x", Track(id="1", artist="A", title="B"))
        assert r.verdict == "match" and "iTunes" in r.note
