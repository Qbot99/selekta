"""Testy selekta.covers: embedded_art, verify, audit, from_itunes."""
from __future__ import annotations

import os

import pytest
import requests

from selekta.covers import CoverHit, audit, embedded_art, from_itunes, verify
from tests.conftest import GOOD_FLAC, GOOD_MP3, GOOD_WAV, MOJIBAKE_MP3

JPEG_MAGIC = b"\xff\xd8\xff"


def _network_available() -> bool:
    try:
        requests.get(
            "https://itunes.apple.com/search?term=test&limit=1", timeout=10
        )
        return True
    except requests.RequestException:
        return False


# ------------------------------------------------------------- embedded_art

class TestEmbeddedArt:
    @pytest.mark.parametrize("name", [GOOD_FLAC, GOOD_MP3, GOOD_WAV])
    def test_reference_files_have_jpeg_cover(self, sample, name):
        data = embedded_art(sample(name))
        assert isinstance(data, bytes)
        assert data[:3] == JPEG_MAGIC
        assert len(data) > 1000  # realna okładka, nie ogryzek

    def test_file_without_cover_returns_none(self, no_cover_mp3):
        # plik z tagami ID3, ale bez ramek APIC (przygotowany w fixture)
        assert embedded_art(no_cover_mp3) is None

    def test_non_audio_file_returns_none(self, tmp_path):
        p = tmp_path / "nie-audio.txt"
        p.write_bytes(b"zwykly tekst")
        assert embedded_art(str(p)) is None


# ------------------------------------------------------------------- verify

class TestVerify:
    def test_matching_cover_true(self, sample):
        path = sample(GOOD_FLAC)
        expected = embedded_art(path)
        assert expected is not None
        assert verify(path, expected) is True

    def test_mismatching_cover_false(self, sample):
        path = sample(GOOD_FLAC)
        other = JPEG_MAGIC + b"\xe0zupelnie-inny-obrazek" * 20
        assert verify(path, other) is False

    def test_file_without_cover_false(self, sample):
        assert verify(sample(MOJIBAKE_MP3), JPEG_MAGIC + b"\xe0cokolwiek") is False

    def test_cover_from_one_file_does_not_verify_another(self, sample):
        flac_art = embedded_art(sample(GOOD_FLAC))
        wav_path = sample(GOOD_WAV)
        assert flac_art is not None
        assert verify(wav_path, flac_art) is False


# -------------------------------------------------------------------- audit

class TestAudit:
    def test_splits_correctly(self, sample, no_cover_mp3):
        with_cover = [sample(GOOD_FLAC), sample(GOOD_MP3), sample(GOOD_WAV)]
        without = [no_cover_mp3]
        have, missing = audit(with_cover + without)
        assert sorted(have) == sorted(with_cover)
        assert missing == without

    def test_empty_input(self):
        assert audit([]) == ([], [])

    def test_all_missing(self, tmp_path):
        p = tmp_path / "pusty.txt"
        p.write_bytes(b"x")
        have, missing = audit([str(p)])
        assert have == []
        assert missing == [str(p)]


# -------------------------------------------------------------- from_itunes

@pytest.mark.network
class TestFromItunes:
    def test_known_track_returns_jpeg_hit(self):
        if not _network_available():
            pytest.skip("brak dostępu do itunes.apple.com")
        hit = from_itunes("Salvatore Ganacci", "Horse")
        if hit is None:
            pytest.skip("iTunes nie zwrócił wyniku (API/limit) — nie oceniamy")
        assert isinstance(hit, CoverHit)
        assert hit.source == "itunes"
        assert hit.data[:3] == JPEG_MAGIC
        assert len(hit.data) > 5000  # 600x600 to dziesiątki KB
        assert "horse" in hit.description.lower()

    def test_known_track_title_match_guard(self):
        # Opis trafienia musi zawierać nazwę utworu — ochrona przed
        # okładką innego kawałka tego samego artysty.
        if not _network_available():
            pytest.skip("brak dostępu do itunes.apple.com")
        hit = from_itunes("Daft Punk", "One More Time")
        if hit is None:
            pytest.skip("iTunes nie zwrócił wyniku (API/limit) — nie oceniamy")
        assert "one more time" in hit.description.lower()
        assert hit.data[:3] == JPEG_MAGIC

    def test_nonsense_query_returns_none(self):
        if not _network_available():
            pytest.skip("brak dostępu do itunes.apple.com")
        assert from_itunes("xqzw", "vvvv") is None
