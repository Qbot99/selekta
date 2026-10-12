"""Tonacja w muzyce klubowej — wzorce o znanej odpowiedzi.

Przegląd 0.4.2 (październik 2026): na prawdziwej muzyce selekta podawała
tonację DUROWĄ dla utworów w MOLL (20 z 21 pomyłek „równoległych” wobec
rekordboxa i Mixed In Key), a pewność tego nie sygnalizowała. Mechanizm:
bas techno gra prymę i kwintę bez tercji, a profile Krumhansla przy samej
prymie i kwincie wolą dur.

Wzorce poniżej są zbudowane jak utwór klubowy (piłokształtny bas na tonice,
stopa nastrojona na tonikę, pad, hi-haty), żeby sprawdzać zachowanie na
materiale podobnym do prawdziwego, a nie tylko na czystych akordach
(te pilnuje tests/test_regresja_dsp.py::TestTonacja).

Zasada przy braku tercji: tryb jest umowny. Przyjmujemy moll (konwencja
muzyki klubowej, tak samo robią rekordbox i Mixed In Key), ale pewność
MUSI spaść poniżej progu „sprawdź uchem” — DJ ma wiedzieć, że dur/moll
nie wynika z nagrania.
"""
from __future__ import annotations

import os
import struct
import wave

import numpy as np
import pytest

from selekta import harmonic, uchem

SR = 22050
NUTY = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _ton(f: float, n: int, alikwoty: int = 6) -> np.ndarray:
    t = np.arange(n) / SR
    x = np.zeros(n)
    for k in range(1, alikwoty + 1):
        if f * k < SR / 2:
            x += np.sin(2 * np.pi * f * k * t) / k
    return x


def _stopa(n: int, bpm: float, f_kon: float) -> np.ndarray:
    """Stopa z tonem opadającym do f_kon (w techno strojona na tonikę)."""
    okres = int(SR * 60 / bpm)
    t = np.arange(int(0.25 * SR)) / SR
    f = f_kon + 120 * np.exp(-t * 30)
    uderzenie = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    x = np.zeros(n)
    for a in range(0, n - len(uderzenie), okres):
        x[a:a + len(uderzenie)] += uderzenie
    return x


def _hihat(n: int, bpm: float) -> np.ndarray:
    rng = np.random.default_rng(20261011)
    okres = int(SR * 60 / bpm)
    d = int(0.04 * SR)
    h = np.diff(np.concatenate([[0.0], rng.standard_normal(d) * np.exp(-np.arange(d) / (0.01 * SR))]))
    x = np.zeros(n)
    for a in range(okres // 2, n - d, okres):
        x[a:a + d] += h
    return x


def _zapisz(x: np.ndarray, path: str) -> str:
    x = np.clip(x / max(1e-9, np.abs(x).max()) * 0.8, -1, 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(struct.pack("<%dh" % len(x), *(x * 32000).astype(int)))
    return path


def utwor_klubowy(path: str, tonika: str, tercja: str | None = None,
                  sekund: float = 30.0, rozstrojenie_ct: float = 0.0,
                  pad: tuple[int, ...] | None = None, bpm: float = 145.0) -> str:
    """Bas piłokształtny na tonice (41-78 Hz), stopa na tonice, pad, hi-hat.

    tercja: None (sama pryma i kwinta), "mol" albo "dur".
    pad: własne interwały padu względem toniki (zamiast prymy/kwinty/tercji).
    rozstrojenie_ct: cały utwór przestrojony o tyle centów (A != 440 Hz).
    """
    n = int(SR * sekund)
    r = 28 + (NUTY.index(tonika) - 4) % 12 + rozstrojenie_ct / 100.0
    x = 0.6 * _ton(_hz(r), n, alikwoty=8)
    if pad is None:
        pad = (24, 31) + ({"mol": (27,), "dur": (28,)}.get(tercja, ()))
    p = np.zeros(n)
    for interwal in pad:
        p += _ton(_hz(r + interwal), n, alikwoty=4) * (0.5 if interwal in (27, 28) else 1.0)
    x += 0.4 * p
    x += 0.9 * _stopa(n, bpm, _hz(r))
    x += 0.15 * _hihat(n, bpm)
    return _zapisz(x, path)


def _camelot(tonika: str, tryb: str) -> str:
    tab = harmonic._CAMELOT_MINOR if tryb == "minor" else harmonic._CAMELOT_MAJOR
    return tab[tonika]


class TestBrakTercji:
    """Sama pryma i kwinta — typowy bas hard techno."""

    @pytest.mark.parametrize("tonika", ["A", "C", "F#"])
    def test_pryma_i_kwinta_to_moll(self, tmp_path, tonika):
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "b.wav"), tonika))
        assert a.key == f"{tonika} minor", a
        assert a.camelot == _camelot(tonika, "minor")

    @pytest.mark.parametrize("tonika", ["A", "F#"])
    def test_brak_tercji_obniza_pewnosc(self, tmp_path, tonika):
        """Tryb bez tercji jest umowny — pewność poniżej progu „sprawdź uchem”."""
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "b.wav"), tonika))
        assert a.confidence_key < uchem.PROG_TONACJI, a
        # podpowiedź: równoległa durowa jest drugą możliwością
        assert a.key_alt == _camelot(tonika, "major"), a


class TestTercjaRozstrzyga:
    @pytest.mark.parametrize("tonika", ["A", "D#", "G"])
    def test_tercja_mala_to_moll(self, tmp_path, tonika):
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "m.wav"), tonika, "mol"))
        assert a.key == f"{tonika} minor", a

    @pytest.mark.parametrize("tonika", ["A", "D#", "G"])
    def test_tercja_wielka_to_dur(self, tmp_path, tonika):
        """Piłokształtny bas ma piątą harmoniczną w tercji WIELKIEJ — mimo to
        moll bez tercji w padzie nie może się stać durem, a dur z tercją
        w padzie musi zostać durem."""
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "d.wav"), tonika, "dur"))
        assert a.key == f"{tonika} major", a

    def test_tercja_w_nagraniu_daje_pewnosc(self, tmp_path):
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "m.wav"), "A", "mol"))
        assert a.confidence_key >= uchem.PROG_TONACJI, a


class TestTonikaZBasu:
    def test_bas_na_tonice_mollowej_a_pad_w_relatywnym_durze(self, tmp_path):
        """C#m7: bas na C#, pad gra E-G#-B (trójdźwięk E-dur) + C#.

        Sam środek pasma wskazuje E-dur (relatywna, 12B); bas rozstrzyga
        o C# minor (12A). Tak wyglądały pomyłki „relatywne” z przeglądu.
        """
        a = harmonic.analyze(utwor_klubowy(
            str(tmp_path / "r.wav"), "C#", pad=(24, 27, 31, 34)))
        assert a.camelot == "12A", a


class TestStrojenie:
    @pytest.mark.parametrize("ct", [-45.0, -30.0, 35.0])
    def test_rozstrojony_utwor(self, tmp_path, ct):
        """Bootlegi i stare płyty bywają przestrojone (w korpusie do 45 ct).

        Przy 45 ct nuty leżą prawie w połowie między półtonami — bez
        estymacji stroju chroma rozlewa się na dwa sąsiednie półtony."""
        a = harmonic.analyze(utwor_klubowy(
            str(tmp_path / "s.wav"), "E", "mol", rozstrojenie_ct=ct))
        assert a.key == "E minor", (ct, a)

    def test_estymacja_stroju(self):
        n = SR * 10
        t = np.arange(n) / SR
        for ct in (-40.0, 0.0, 25.0):
            x = sum(np.sin(2 * np.pi * _hz(57 + k + ct / 100) * t) for k in (0, 3, 7, 12))
            dev = harmonic._strojenie_sygnalu(x.astype(np.float32), SR)
            assert abs(dev * 100 - ct) < 3.0, (ct, dev)


class TestPewnosc:
    def test_pewnosc_niska_gdy_dwie_tonacje(self, tmp_path):
        """Pół utworu w A-moll, pół w E-moll (modulacja) — tonika niepewna."""
        a = utwor_klubowy(str(tmp_path / "a.wav"), "A", "mol", sekund=20)
        e = utwor_klubowy(str(tmp_path / "e.wav"), "E", "mol", sekund=20)
        xs = []
        for p in (a, e):
            with wave.open(p) as w:
                xs.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32000.0)
        sklejony = _zapisz(np.concatenate(xs), str(tmp_path / "ae.wav"))
        wynik = harmonic.analyze(sklejony)
        assert wynik.camelot in ("8A", "9A"), wynik
        assert wynik.confidence_key < uchem.PROG_TONACJI, wynik

    def test_alternatywa_jest_kodem_camelota(self, tmp_path):
        a = harmonic.analyze(utwor_klubowy(str(tmp_path / "m.wav"), "A", "mol"))
        assert a.key_alt and a.key_alt != a.camelot
        assert a.key_alt[:-1].isdigit() and a.key_alt[-1] in "AB"
