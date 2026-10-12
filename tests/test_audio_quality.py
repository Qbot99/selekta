"""Testy selekta.quality — detektor fake-lossless (cutoff pasma) i realnej
bitowości.

Wartości odniesienia zmierzone na realnych plikach biblioteki:
- GOOD_FLAC  -> cutoff 22000 Hz, grade "ok" (prawdziwy lossless, 16-bit),
- FAKE_FLAC  -> cutoff 16400 Hz, grade "bad" (źródło ~128k w kontenerze FLAC 24-bit),
- GOOD_MP3   -> cutoff 19600 Hz (typowe pasmo dobrego MP3),
- GOOD_WAV   -> 24-bit nominalnie i realnie (effective_bits == 24).
"""
from __future__ import annotations

import functools
import os

import pytest
from mutagen import File as MutagenFile
from mutagen import MutagenError

from selekta import quality
from tests.conftest import FAKE_FLAC, GOOD_FLAC, GOOD_MP3, GOOD_WAV


@functools.lru_cache(maxsize=None)
def _analyze(path: str) -> quality.QualityReport:
    """Jedna analiza na plik, współdzielona między testami."""
    return quality.analyze(path)


# ---------------------------------------------------------------- analyze()

def test_good_flac_is_true_lossless(sample):
    r = _analyze(sample(GOOD_FLAC))
    assert r.grade == "ok"
    assert r.cutoff_hz > 20500
    assert r.cutoff_hz <= 22050  # nie więcej niż Nyquist dla 44.1 kHz
    assert r.ext == ".flac"
    assert r.sample_rate == 44100
    assert r.nominal_bits == 16
    # dla plików 16-bitowych realna bitowość nie jest liczona
    assert r.effective_bits is None
    assert "lossless" in r.verdict


def test_fake_flac_detected_as_bad(sample):
    r = _analyze(sample(FAKE_FLAC))
    assert r.grade == "bad"
    assert 15000 <= r.cutoff_hz <= 18000
    assert "~16 kHz" in r.verdict
    assert r.ext == ".flac"


def test_good_mp3_cutoff_range(sample):
    r = _analyze(sample(GOOD_MP3))
    assert 19000 <= r.cutoff_hz <= 21000
    assert r.ext == ".mp3"
    # MP3 nie deklaruje bitowości -> oba pola bitowe puste
    assert r.nominal_bits is None
    assert r.effective_bits is None
    # dobre MP3 nie może dostać oceny "bad"
    assert r.grade in ("ok", "warn")


def test_good_wav_real_24bit(sample):
    r = _analyze(sample(GOOD_WAV))
    assert r.nominal_bits == 24
    assert r.effective_bits == 24
    assert r.cutoff_hz > 20500
    assert r.grade == "ok"


# ------------------------------------------------- funkcje pomiarowe wprost

def test_spectral_cutoff_direct_on_wav(sample):
    p = sample(GOOD_WAV)
    info = MutagenFile(p).info
    c = quality.spectral_cutoff(p, info.length, info.sample_rate)
    assert 20500 < c <= info.sample_rate / 2


def test_effective_bits_direct_on_wav(sample):
    p = sample(GOOD_WAV)
    info = MutagenFile(p).info
    assert quality.effective_bits(p, info.length) == 24


def test_spectral_cutoff_nonexistent_returns_zero():
    assert quality.spectral_cutoff("/nie/ma/takiego/pliku.flac", 300.0, 44100) == 0.0


def test_effective_bits_nonexistent_returns_zero():
    assert quality.effective_bits("/nie/ma/takiego/pliku.flac", 300.0) == 0


# ---------------------------------------------------------------- _verdict()

@pytest.mark.parametrize(
    "cutoff, ext, grade",
    [
        (22000.0, ".flac", "ok"),
        (22000.0, ".mp3", "ok"),
        (20000.0, ".mp3", "ok"),      # typowe 320 kbps
        (20000.0, ".flac", "warn"),   # lossless z pasmem MP3 -> transkod?
        (19000.0, ".flac", "warn"),   # ~256 kbps / V0
        (16400.0, ".flac", "bad"),    # ~128-192 kbps
        (10000.0, ".flac", "bad"),    # bardzo wąskie pasmo
    ],
)
def test_verdict_thresholds(cutoff, ext, grade):
    g, verdict = quality._verdict(cutoff, ext)
    assert g == grade
    assert isinstance(verdict, str) and verdict


def test_verdict_transcode_warning_text():
    g, verdict = quality._verdict(20000.0, ".flac")
    assert g == "warn"
    assert "transkod" in verdict


# ---------------------------------------------------------------- błędy IO

def test_analyze_nonexistent_raises_mutagen_error():
    with pytest.raises(MutagenError):
        quality.analyze("/nie/ma/takiego/pliku.flac")


def test_analyze_unrecognized_format_sane_error(tmp_path):
    p = tmp_path / "garbage.dat"
    p.write_bytes(b"\x00\x01to nie jest audio" * 500)
    # oczekiwane: sensowny wyjątek (MutagenError/ValueError), nie crash na None
    with pytest.raises((MutagenError, ValueError)):
        quality.analyze(str(p))


# ---------------------------------------------------------------- transkody o znanej odpowiedzi

import subprocess
import wave

import numpy as np

_SR = 44100


def _ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True, capture_output=True)


@pytest.fixture(scope="module")
def glosny_master(tmp_path_factory):
    """Głośny „utwór” stereo: szum różowy w rytmie 128 BPM + ton, szczyt −0,1 dBFS.

    Taki master to typowe źródło fałszywych FLAC-ów: dekoder MP3 oddaje
    szczyty powyżej 0 dBFS i zapis do 16 bit je przycina.
    """
    d = tmp_path_factory.mktemp("jakosc")
    n = _SR * 30
    t = np.arange(n) / _SR

    def kanal(ziarno):
        rng = np.random.default_rng(ziarno)
        w = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / _SR)
        w[1:] /= np.sqrt(f[1:] / 100)
        w[0] = 0
        szum = np.fft.irfft(w, n)
        obw = 0.3 + 0.7 * np.exp(-((t * 128 / 60) % 1) * 6)
        return szum / np.abs(szum).max() * obw + 0.3 * np.sin(2 * np.pi * 110 * t)

    x = np.stack([kanal(5), kanal(6)], 1)
    x = x / np.abs(x).max() * 0.99
    src = str(d / "master.wav")
    with wave.open(src, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(_SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return d, src


def _transkod(d, src, kbps, nazwa, *wyj):
    mp3 = str(d / f"{nazwa}.mp3")
    _ff("-i", src, "-b:a", f"{kbps}k", mp3)
    out = str(d / nazwa)
    _ff("-i", mp3, *wyj, out)
    return out


@pytest.mark.parametrize("kbps", [128, 192])
def test_przesterowany_transkod_mp3_to_bad(glosny_master, kbps):
    """Przegląd 0.4.2: MP3 128 → FLAC przeszedł jako „prawdziwy lossless”,
    a transkody 192–320 z głośnych masterów dostawały tylko „warn”."""
    d, src = glosny_master
    p = _transkod(d, src, kbps, f"t{kbps}.flac", "-sample_fmt", "s16")
    r = quality.analyze(p)
    assert r.cechy["przyciete_ramki"] > 0          # dekoder MP3 przesterował przy zapisie
    assert r.grade == "bad", r.verdict
    assert "transkod" in r.verdict


def test_transkod_w_kontenerze_24bit_nie_lagodnieje(glosny_master):
    """quality.py:158-159 zamieniało wykryte „bad” na „warn”, gdy plik 24-bit
    miał realnie 16 bitów — fałszywy FLAC 24-bit zawsze przechodził bramkę."""
    d, src = glosny_master
    p16 = _transkod(d, src, 128, "t24_16.flac", "-sample_fmt", "s16")
    p24 = str(d / "t24.flac")
    _ff("-i", p16, "-sample_fmt", "s32", p24)
    r = quality.analyze(p24)
    assert r.grade == "bad"
    assert "realnie 16-bit" in r.verdict


def test_alac_jest_oceniany_jak_bezstratny(glosny_master):
    """.m4a z ALAC omijał test transkodu (traktowany jak stratny)."""
    d, src = glosny_master
    prawdziwy = str(d / "prawdziwy.m4a")
    _ff("-i", src, "-c:a", "alac", prawdziwy)
    r = quality.analyze(prawdziwy)
    assert r.grade == "ok" and "lossless" in r.verdict and r.bitrate_kbps is None
    fałszywy = _transkod(d, src, 128, "falszywy.m4a", "-c:a", "alac")
    assert quality.analyze(fałszywy).grade == "bad"


def test_falszywe_hi_res_to_ostrzezenie(glosny_master):
    d, src = glosny_master
    p = str(d / "hires.flac")
    _ff("-i", src, "-af", "aresample=96000", "-sample_fmt", "s32", p)
    r = quality.analyze(p)
    assert r.grade == "warn"
    assert "przepróbkowane" in r.verdict


def test_prawdziwy_master_ok(glosny_master):
    d, src = glosny_master
    p = str(d / "prawdziwy.flac")
    _ff("-i", src, p)
    assert quality.analyze(p).grade == "ok"


def test_mono_128_nie_udaje_320(tmp_path):
    """MP3 128 kbps mono ma pasmo jak 320 (LAME nie tnie), ale werdykt ma
    mówić prawdę z nagłówka, a nie „typowe pasmo dla 320 kbps”."""
    from tests import probka
    wav = probka.pelne_pasmo(str(tmp_path / "m.wav"), sekund=20)
    mp3 = str(tmp_path / "m.mp3")
    _ff("-i", wav, "-ac", "1", "-b:a", "128k", mp3)
    r = quality.analyze(mp3)
    assert "128 kbps mono" in r.verdict
    assert "320" not in r.verdict
    assert r.grade == "warn"


def test_master_ze_sciana_bez_sladow_kodeka_nie_jest_bad(tmp_path):
    """Ostra ściana z ciszą nad nią bez śladów kodeka (konwersja 48→44,1 kHz
    przy masteringu) nie może oblać bramki."""
    from tests import probka
    wav = probka.obciete_pasmo(str(tmp_path / "s.wav"), 20.3, sekund=30)
    r = quality.analyze(probka.do_flac(wav, str(tmp_path / "s.flac")))
    assert r.grade != "bad", r.verdict
