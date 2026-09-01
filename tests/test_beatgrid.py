"""Kotwica beatgridu musi leżeć NA uderzeniu.

Realny objaw, od którego się zaczęło: wskaźnik pierwszego beatu bywał
przesunięty nawet o pół uderzenia, bo brany był pierwszy napotkany onset
— a tym bywa fade-in, sweep albo oddech wokalisty. Teraz fazę siatki
liczymy z całego utworu.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from selekta import cache, cues


def _obwiednia_z_uderzeniami(bpm: float, faza: float, sekundy: float = 30.0):
    """Sztuczna obwiednia onsetów: impulsy dokładnie co 60/bpm od `faza`."""
    n = int(sekundy * cues.FPS)
    flux = np.zeros(n, dtype=float)
    okres = 60.0 / bpm
    t = faza
    while t < sekundy:
        i = int(round(t * cues.FPS))
        if 0 <= i < n:
            flux[i] = 1.0
        t += okres
    return flux


class TestFazaSiatki:
    @pytest.mark.parametrize("bpm", [128.0, 140.0, 150.0, 174.0])
    @pytest.mark.parametrize("faza_ms", [0, 90, 200, 310])
    def test_odtwarza_zadana_faze(self, bpm, faza_ms):
        okres = 60.0 / bpm
        faza = (faza_ms / 1000.0) % okres
        flux = _obwiednia_z_uderzeniami(bpm, faza)
        wynik = cues.faza_siatki(flux, bpm)
        # błąd liczony cyklicznie: 0 i okres to ta sama faza
        blad = abs(wynik - faza)
        blad = min(blad, okres - blad)
        assert blad < 0.030, f"pomyłka {blad*1000:.0f} ms przy {bpm} BPM"

    def test_bez_bpm_zwraca_zero(self):
        assert cues.faza_siatki(np.ones(100), None) == 0.0
        assert cues.faza_siatki(np.ones(100), 0) == 0.0

    def test_cisza_nie_wywala(self):
        assert cues.faza_siatki(np.zeros(200), 140.0) == 0.0

    def test_krotka_obwiednia_nie_wywala(self):
        assert cues.faza_siatki(np.ones(3), 140.0) == 0.0


class TestKotwicaNaSiatce:
    @pytest.mark.parametrize("bpm,faza_ms", [(150.0, 120), (128.0, 40), (174.0, 250)])
    def test_kotwica_lezy_na_uderzeniu(self, bpm, faza_ms):
        """Kotwica ma wypadać na jednym z impulsów, nie pomiędzy nimi.

        Podajemy tu SZTUCZNĄ obwiednię, w której nie ma okna STFT — a
        `_first_beat` oddaje jego opóźnienie, bo w produkcji obwiednia
        zawsze z niego pochodzi. Dlatego odejmujemy tę znaną stałą; na
        prawdziwym dźwięku sprawdza to test regresyjny z modułu
        test_regresja_dsp.
        """
        okres = 60.0 / bpm
        faza = (faza_ms / 1000.0) % okres
        flux = _obwiednia_z_uderzeniami(bpm, faza)
        total = np.ones_like(flux)                  # muzyka gra od początku
        kotwica = cues._first_beat(total, flux, bpm) - cues.OPOZNIENIE_OKNA_S
        reszta = (kotwica - faza) % okres
        odchylka = min(reszta, okres - reszta)
        assert odchylka < 0.030, f"kotwica obok siatki o {odchylka*1000:.0f} ms"

    def test_kotwica_nie_jest_ujemna(self):
        flux = _obwiednia_z_uderzeniami(150.0, 0.2)
        assert cues._first_beat(np.ones_like(flux), flux, 150.0) >= 0.0

    def test_kotwica_nie_wyprzedza_poczatku_muzyki(self):
        """Anchor nie może wypaść w ciszy przed pierwszym dźwiękiem."""
        bpm, faza = 150.0, 0.1
        flux = _obwiednia_z_uderzeniami(bpm, faza, sekundy=30)
        total = np.zeros_like(flux)
        cisza_do = int(5.0 * cues.FPS)
        total[cisza_do:] = 1.0                      # muzyka startuje w 5. sekundzie
        kotwica = cues._first_beat(total, flux, bpm)
        assert kotwica >= 5.0 - 60.0 / bpm

    def test_bez_bpm_nadal_daje_sensowna_wartosc(self):
        flux = _obwiednia_z_uderzeniami(150.0, 0.2)
        kotwica = cues._first_beat(np.ones_like(flux), flux, None)
        assert isinstance(kotwica, float) and kotwica >= 0.0


class TestWersjonowaniePamieci:
    """Zmiana algorytmu musi unieważniać stare wyniki."""

    def test_stara_wersja_jest_pomijana(self, tmp_path, monkeypatch, lib_copy):
        import os
        from tests.conftest import GOOD_MP3
        plik = os.path.join(lib_copy, GOOD_MP3)
        monkeypatch.setitem(cache.WERSJE, "cues", 1)
        cache.put(plik, "cues", {"first_beat_s": 0.111})
        assert cache.get(plik, "cues") == {"first_beat_s": 0.111}
        monkeypatch.setitem(cache.WERSJE, "cues", 2)
        assert cache.get(plik, "cues") is None, "wynik starej wersji ma odpaść"

    def test_inne_rodzaje_nie_sa_ruszane(self, lib_copy, monkeypatch):
        import os
        from tests.conftest import GOOD_MP3
        plik = os.path.join(lib_copy, GOOD_MP3)
        cache.put(plik, "harmonic", {"bpm": 128.0})
        monkeypatch.setitem(cache.WERSJE, "cues", 99)
        assert cache.get(plik, "harmonic") == {"bpm": 128.0}
