"""Wykrywanie zmiennego tempa.

Testy jadą na sygnałach o ZNANYM tempie, bo tylko wtedy wiadomo, czy
detektor ma rację. Na prawdziwej muzyce da się sprawdzić wiarygodność,
ale nie prawdę — nie znamy jej z góry.

Rozdzielamy dwa przypadki, które łatwo pomylić: nietrafione BPM przy
stałym tempie (naprawia jedna liczba) i tempo naprawdę falujące
(nie naprawi go żadna).
"""
from __future__ import annotations

import os
import struct
import wave

import numpy as np
import pytest

from selekta import tempo

SR = 22050


def _sciezka_klikow(path: str, sekund: float, bpm_a: float, bpm_b: float,
                    falowanie: float = 0.0) -> str:
    """Metronom o zadanym tempie: liniowa rampa i/lub falowanie."""
    n = int(SR * sekund)
    x = np.zeros(n, dtype=np.float32)
    t = 0.0
    while t < sekund:
        frakcja = t / sekund
        bpm = bpm_a + (bpm_b - bpm_a) * frakcja
        if falowanie:
            bpm *= 1 + falowanie * np.sin(2 * np.pi * frakcja * 3)
        i = int(t * SR)
        if i < n - 400:
            env = np.exp(-np.arange(400) / 40.0)
            x[i:i + 400] += (env * np.sin(2 * np.pi * 90 * np.arange(400) / SR)
                             ).astype(np.float32)
        t += 60.0 / bpm
    x = x / max(1e-9, float(np.abs(x).max()))
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(struct.pack("<%dh" % len(x),
                                  *(np.clip(x, -1, 1) * 32000).astype(int)))
    return path


class TestTempoStale:
    def test_rowny_metronom_jest_stabilny(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "a.wav"), 200, 150, 150)
        s = tempo.zbadaj(p, 150.0)
        assert s.stabilne is True and s.bpm_nietrafione is False
        assert s.wahanie_bitu < 0.02

    def test_inne_tempo_tez_dziala(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "b.wav"), 200, 128, 128)
        assert tempo.zbadaj(p, 128.0).stabilne is True


class TestBpmNietrafione:
    def test_wykrywa_lekko_zle_bpm(self, tmp_path):
        """Tempo stałe 150, ale podajemy 149 — to nie jest zmienne tempo."""
        p = _sciezka_klikow(str(tmp_path / "c.wav"), 200, 150, 150)
        s = tempo.zbadaj(p, 149.0)
        assert s.stabilne is True, "stałe tempo nie może być zgłoszone jako zmienne"
        assert s.bpm_nietrafione is True

    def test_proponowane_bpm_jest_trafne(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "d.wav"), 200, 150, 150)
        s = tempo.zbadaj(p, 149.0)
        assert abs(s.bpm_poprawione - 150.0) < 0.3, s.bpm_poprawione

    def test_dziala_w_obie_strony(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "e.wav"), 200, 150, 150)
        s = tempo.zbadaj(p, 151.0)
        assert s.bpm_nietrafione and abs(s.bpm_poprawione - 150.0) < 0.3


class TestTempoZmienne:
    def test_wykrywa_rampe_tempa(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "f.wav"), 200, 150, 153)
        s = tempo.zbadaj(p, 150.0)
        assert s.stabilne is False
        assert "faluje" in s.opis

    def test_wykrywa_falowanie(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "g.wav"), 200, 150, 150,
                            falowanie=0.015)
        assert tempo.zbadaj(p, 150.0).stabilne is False

    def test_przy_zmiennym_nie_proponujemy_bpm(self, tmp_path):
        """Żadna pojedyncza liczba tego nie naprawi — nie udajemy, że tak."""
        p = _sciezka_klikow(str(tmp_path / "h.wav"), 200, 150, 153)
        assert tempo.zbadaj(p, 150.0).bpm_poprawione is None


class TestPrzypadkiBrzegowe:
    def test_bez_bpm_nie_zgaduje(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "i.wav"), 60, 150, 150)
        s = tempo.zbadaj(p, None)
        assert s.stabilne is True and "bez BPM" in s.opis

    def test_krotki_utwor_nie_jest_oceniany(self, tmp_path):
        p = _sciezka_klikow(str(tmp_path / "j.wav"), 25, 150, 150)
        s = tempo.zbadaj(p, 150.0)
        assert s.stabilne is True
        assert "za krótki" in s.opis or "za mało" in s.opis

    def test_cisza_nie_wywala(self, tmp_path):
        p = str(tmp_path / "k.wav")
        with wave.open(p, "w") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(struct.pack("<%dh" % (SR * 60), *([0] * (SR * 60))))
        s = tempo.zbadaj(p, 150.0)
        assert s.stabilne is True, "cisza to nie jest dowód zmiennego tempa"

    def test_nieczytelny_plik_nie_wywala(self, tmp_path):
        zly = tmp_path / "zly.wav"
        zly.write_bytes(b"to nie jest dzwiek")
        assert tempo.zbadaj(str(zly), 150.0).stabilne is True
