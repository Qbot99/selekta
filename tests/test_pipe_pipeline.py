"""Testy selekta.pipeline — bramki weryfikacji pobranego pliku.

Wszystko offline: integralność (ffmpeg), tożsamość (pominięta bez utworu
odniesienia), jakość (analiza widmowa) oraz orkiestracja verify_download
i wybór następnego źródła (next_source).
"""
from __future__ import annotations

from selekta import pipeline
from selekta.pipeline import Check, VerifyResult
from selekta.slskd_client import SearchHit
from selekta.spotify import Track
from tests.conftest import CORRUPT_FLAC, FAKE_FLAC, GOOD_FLAC, real_path


# ---------------------------------------------------------------- integrity

def test_integrity_good_flac_passes(sample):
    c = pipeline.integrity(sample(GOOD_FLAC))
    assert c.passed is True
    assert c.critical is True
    assert c.name == "integralność"
    assert "bez błędów" in c.detail


def test_integrity_corrupt_flac_fails_at_end(sample):
    c = pipeline.integrity(sample(CORRUPT_FLAC))
    assert c.passed is False
    assert c.critical is True
    # uszkodzenie zlokalizowane przy końcu pliku (sygnatura uciętego transferu)
    assert "końc" in c.detail
    assert "ucięty" in c.detail
    assert "4" in c.detail  # znane 4 błędy dekodowania tego pliku


def test_integrity_nonexistent_file_fails():
    c = pipeline.integrity("/nie/ma/takiego/pliku.flac")
    assert c.passed is False
    assert c.critical is True


# ---------------------------------------------------------------- identity

def test_identity_skipped_without_track(sample):
    c = pipeline.identity(sample(GOOD_FLAC), None)
    assert c.passed is True
    assert c.critical is False
    assert "pominięto" in c.detail


def test_identity_skipped_for_empty_track(sample):
    t = Track(id="", artist="a", title="b", preview_url="")
    c = pipeline.identity(sample(GOOD_FLAC), t)
    assert c.passed is True
    assert c.critical is False
    assert "pominięto" in c.detail


# ---------------------------------------------------------------- quality

def test_sound_quality_fake_flac_critical_fail(sample):
    c = pipeline.sound_quality(sample(FAKE_FLAC))
    assert c.passed is False
    assert c.critical is True          # grade "bad" => bramka krytyczna
    assert c.name == "jakość"
    assert "16.4 kHz" in c.detail      # znane ucięcie pasma ~16.4 kHz


def test_sound_quality_good_flac_passes(sample):
    c = pipeline.sound_quality(sample(GOOD_FLAC))
    assert c.passed is True
    assert c.critical is False


# ---------------------------------------------------------------- orkiestracja

def test_verify_download_good_no_track_ok(sample):
    res = pipeline.verify_download(sample(GOOD_FLAC), None)
    assert res.ok is True
    assert [c.name for c in res.checks] == ["integralność", "tożsamość", "jakość"]
    ident = res.checks[1]
    assert ident.passed is True and ident.critical is False  # pominięta, nie krytyczna
    assert res.reasons == []
    assert res.format().startswith("✅")


def test_verify_download_corrupt_fails_with_cross(sample):
    res = pipeline.verify_download(sample(CORRUPT_FLAC))
    assert res.ok is False
    txt = res.format()
    assert "✗" in txt and "❌" in txt
    assert len(res.reasons) == 1
    assert res.reasons[0].startswith("integralność:")


def test_verifyresult_noncritical_fail_still_ok():
    res = VerifyResult("x.flac", [
        Check("integralność", True, True, "ok"),
        Check("jakość", False, False, "słabe pasmo"),
    ])
    assert res.ok is True                       # krytyczne przeszły
    assert res.reasons == ["jakość: słabe pasmo"]
    assert "⚠" in res.format()                  # niekrytyczna porażka = ostrzeżenie


def test_verifyresult_empty_checks_ok():
    assert VerifyResult("x.flac").ok is True


# ---------------------------------------------------------------- next_source

def _hit(username, lossless=True, free=True, length=360, bitrate=None, size=10):
    return SearchHit(username=username, filename="f.flac" if lossless else "f.mp3",
                     size=size, bitrate=bitrate, length_s=length,
                     is_lossless=lossless, free_slot=free)


def test_next_source_skips_tried_users():
    hits = [_hit("best"), _hit("second", free=False), _hit("mp3guy", lossless=False, bitrate=320)]
    assert pipeline.next_source(hits, set(), 360).username == "best"
    assert pipeline.next_source(hits, {"best"}, 360).username == "second"
    assert pipeline.next_source(hits, {"best", "second"}, 360).username == "mp3guy"


def test_next_source_all_tried_returns_none():
    hits = [_hit("a"), _hit("b")]
    assert pipeline.next_source(hits, {"a", "b"}, 360) is None


def test_next_source_empty_hits_returns_none():
    assert pipeline.next_source([], set(), None) is None


def test_transkod_z_320_oblewa_pelna_weryfikacje(tmp_path):
    """Regresja z 1.09.2026: FLAC z pasmem MP3 320 przechodził `check`
    jako „warn" — ostrzeżenie łatwe do przeoczenia. PRAWDZIWY transkod
    (ściana + cyfrowa cisza nad cięciem) ma OBLAĆ bramkę."""
    import subprocess
    import sys
    sys.path.insert(0, "/Users/hubert/claude/selekta/tests")
    import probka
    wav = probka.pelne_pasmo(str(tmp_path / "a.wav"), sekund=70)
    mp3 = probka.do_mp3(wav, str(tmp_path / "a.mp3"), 320)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", mp3,
                    str(tmp_path / "dekod.wav")], check=True)
    flac = probka.do_flac(str(tmp_path / "dekod.wav"),
                          str(tmp_path / "transkod.flac"))
    wynik = pipeline.sound_quality(flac)
    assert wynik.passed is False, wynik.detail
    assert "transkod" in wynik.detail


def test_master_z_lowpassem_przechodzi_check(tmp_path):
    """Druga strona dyskryminatora: 1/5 legalnych plików w bibliotece to
    mastery z lowpassem ~20.1-20.8 kHz — mają energię nad cięciem
    (zmierzone -45..-60 dB) i NIE mogą oblewać weryfikacji pobrań."""
    import sys
    sys.path.insert(0, "/Users/hubert/claude/selekta/tests")
    import probka
    wav = probka.obciete_pasmo(str(tmp_path / "m.wav"), 20.3, sekund=70)
    flac = probka.do_flac(wav, str(tmp_path / "master.flac"))
    wynik = pipeline.sound_quality(flac)
    assert wynik.passed is True, wynik.detail


def test_mp3_256_dalej_przechodzi_check(tmp_path):
    """Warn dla stratnych to niższa półka, nie fałszerstwo — przechodzi."""
    import sys
    sys.path.insert(0, "/Users/hubert/claude/selekta/tests")
    import probka
    wav = probka.obciete_pasmo(str(tmp_path / "t.wav"), 19.0)
    mp3 = probka.do_mp3(wav, str(tmp_path / "srednie.mp3"), 256)
    wynik = pipeline.sound_quality(mp3)
    assert wynik.passed is True, wynik.detail
