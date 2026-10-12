"""Testy selekta.pipeline — bramki weryfikacji pobranego pliku.

Wszystko offline: integralność (ffmpeg), tożsamość (pominięta bez utworu
odniesienia), jakość (analiza widmowa) oraz orkiestracja verify_download
i wybór następnego źródła (next_source).
"""
from __future__ import annotations

import pytest

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


def test_czysty_transkod_320_z_szumu_dostaje_ostrzezenie(tmp_path):
    """Szum przekodowany przez MP3 320 bez przesteru: ściana 20 kHz i cisza
    nad nią, ale bez dziur kodeka — tego samego śladu nie da się odróżnić od
    konwersji 48→44,1 kHz przy masteringu. Zmiana z 11.10.2026: zamiast
    „bad” (które oblewało też prawdziwe mastery po konwersji: w zestawie
    kontrolnym 16/22) jest „warn” z nazwą podejrzenia — bramka przepuszcza,
    lista „sprawdź uchem” pokazuje."""
    import subprocess
    from tests import probka
    wav = probka.pelne_pasmo(str(tmp_path / "a.wav"), sekund=70)
    mp3 = probka.do_mp3(wav, str(tmp_path / "a.mp3"), 320)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", mp3,
                    str(tmp_path / "dekod.wav")], check=True)
    flac = probka.do_flac(str(tmp_path / "dekod.wav"),
                          str(tmp_path / "transkod.flac"))
    wynik = pipeline.sound_quality(flac)
    assert "MP3 320" in wynik.detail


@pytest.mark.slow
@pytest.mark.parametrize("wyjscie", [["-sample_fmt", "s16"], []])
def test_transkod_320_prawdziwej_muzyki_oblewa_bramke(sample, tmp_path, wyjscie):
    """Przegląd 0.4.2: 15/15 typowych transkodów MP3 192–320 → FLAC z głośnych
    masterów przechodziło bramkę (przester przy zapisie zalewał pasmo nad
    cięciem). Tu: Odymel – Gucci, 30 s ze środka, MP3 320 → FLAC 16 bit
    i domyślny FLAC ffmpeg (24 bit)."""
    import subprocess
    src = sample(GOOD_FLAC)
    wycinek = str(tmp_path / "w.flac")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "90", "-t", "30", "-i", src,
                    wycinek], check=True)
    mp3 = str(tmp_path / "w.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wycinek, "-b:a", "320k", mp3], check=True)
    flac = str(tmp_path / "t.flac")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, *wyjscie, flac], check=True)
    wynik = pipeline.sound_quality(flac)
    assert wynik.passed is False, wynik.detail
    assert "transkod" in wynik.detail
    # ten sam wycinek bez transkodu przechodzi
    assert pipeline.sound_quality(wycinek).passed is True


def test_master_z_lowpassem_przechodzi_check(tmp_path):
    """Druga strona dyskryminatora: 1/5 legalnych plików w bibliotece to
    mastery z lowpassem ~20.1-20.8 kHz — mają energię nad cięciem
    (zmierzone -45..-60 dB) i NIE mogą oblewać weryfikacji pobrań."""
    from tests import probka
    wav = probka.obciete_pasmo(str(tmp_path / "m.wav"), 20.3, sekund=70)
    flac = probka.do_flac(wav, str(tmp_path / "master.flac"))
    wynik = pipeline.sound_quality(flac)
    assert wynik.passed is True, wynik.detail


def test_mp3_256_dalej_przechodzi_check(tmp_path):
    """Warn dla stratnych to niższa półka, nie fałszerstwo — przechodzi."""
    from tests import probka
    wav = probka.obciete_pasmo(str(tmp_path / "t.wav"), 19.0)
    mp3 = probka.do_mp3(wav, str(tmp_path / "srednie.mp3"), 256)
    wynik = pipeline.sound_quality(mp3)
    assert wynik.passed is True, wynik.detail
