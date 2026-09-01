"""Folder obserwowany — nowe pliki analizują się same."""
from __future__ import annotations

import os
import shutil
import time

import pytest

from selekta import cache, obserwator
from tests.conftest import GOOD_MP3


@pytest.fixture
def obs(tmp_path, lib_copy, monkeypatch):
    o = obserwator.Obserwator()
    o._folder = lib_copy
    return o


class TestWykrywanieNowych:
    def test_znajduje_pliki_bez_analiz(self, obs, lib_copy):
        czekaja = obs._do_zrobienia()
        assert any(GOOD_MP3 in p for p in czekaja)

    def test_przeanalizowany_plik_znika_z_kolejki(self, obs, lib_copy):
        plik = os.path.join(lib_copy, GOOD_MP3)
        assert obs.przeanalizuj(plik) is True
        assert plik not in obs._do_zrobienia()

    def test_analiza_zapisuje_wszystkie_rodzaje(self, obs, lib_copy):
        plik = os.path.join(lib_copy, GOOD_MP3)
        obs.przeanalizuj(plik)
        for rodzaj in ("harmonic", "quality", "cues"):
            assert cache.get(plik, rodzaj) is not None, f"brak {rodzaj}"

    def test_uszkodzony_plik_nie_zabija_watku(self, obs, lib_copy):
        zly = os.path.join(lib_copy, "ogryzek.flac")
        with open(zly, "wb") as fh:
            fh.write(b"fLaC" + b"\x00" * 20)
        assert obs.przeanalizuj(zly) is False      # zwraca False, nie rzuca


class TestPlikWTrakciePobierania:
    """Rosnący plik przeanalizowany w połowie dałby bzdurny wynik."""

    def test_nowy_plik_nie_jest_od_razu_gotowy(self, obs, tmp_path):
        plik = tmp_path / "pobierany.flac"
        plik.write_bytes(b"x" * 100)
        assert obs._ustabilizowany(str(plik)) is False, "pierwszy raz — czekamy"

    def test_rosnacy_plik_nie_jest_gotowy(self, obs, tmp_path):
        plik = tmp_path / "rosnie.flac"
        plik.write_bytes(b"x" * 100)
        obs._ustabilizowany(str(plik))
        plik.write_bytes(b"x" * 200)
        assert obs._ustabilizowany(str(plik)) is False

    def test_spokojny_plik_jest_gotowy(self, obs, tmp_path, monkeypatch):
        plik = tmp_path / "gotowy.flac"
        plik.write_bytes(b"x" * 100)
        obs._ustabilizowany(str(plik))
        # udajemy, że minął czas spokoju
        rozmiar, _kiedy = obs._rozmiary[str(plik)]
        obs._rozmiary[str(plik)] = (rozmiar, time.time() - obserwator.SPOKOJ_S - 1)
        assert obs._ustabilizowany(str(plik)) is True

    def test_znikniety_plik_nie_wywala(self, obs, tmp_path):
        assert obs._ustabilizowany(str(tmp_path / "nie-ma.flac")) is False

    def test_produkcyjny_rytm_skanowania_odblokowuje_plik(self, obs, tmp_path,
                                                          monkeypatch):
        """Symulacja prawdziwej pętli: skan co ODSTEP_S, plik się nie zmienia.

        Regresja z 1.09.2026: _ustabilizowany nadpisywał znacznik czasu przy
        KAŻDYM skanie, a spokój wymaga SPOKOJ_S (20 s) między dwoma kolejnymi
        pomiarami — pomiary były co ODSTEP_S (12 s), więc warunek nie zachodził
        nigdy i obserwator nie przetworzył żadnego pliku od początku istnienia.
        Starszy test tego nie łapał, bo antydatował znacznik ręcznie zamiast
        odtworzyć rytm produkcyjny.
        """
        plik = tmp_path / "sciagniety.flac"
        plik.write_bytes(b"x" * 100)
        zegar = [1000.0]
        monkeypatch.setattr(obserwator.time, "time", lambda: zegar[0])

        wyniki = []
        for _ in range(6):                       # ~minuta prawdziwej pętli
            wyniki.append(obs._ustabilizowany(str(plik)))
            zegar[0] += obserwator.ODSTEP_S
        assert any(wyniki), (
            "plik o stałym rozmiarze nigdy nie został uznany za stabilny "
            "przy produkcyjnym rytmie skanowania")
        # dokładnie: pierwszy skan zapamiętuje, gotowość gdy od tego pomiaru
        # minie SPOKOJ_S — przy 12 s odstępu ma to być trzeci skan (24 s)
        assert wyniki.index(True) == 2

    def test_wzrost_rozmiaru_zeruje_odliczanie(self, obs, tmp_path, monkeypatch):
        plik = tmp_path / "jeszcze-rosnie.flac"
        plik.write_bytes(b"x" * 100)
        zegar = [1000.0]
        monkeypatch.setattr(obserwator.time, "time", lambda: zegar[0])
        obs._ustabilizowany(str(plik))
        zegar[0] += obserwator.SPOKOJ_S + 5      # długa przerwa…
        plik.write_bytes(b"x" * 900)             # …ale plik urósł
        assert obs._ustabilizowany(str(plik)) is False
        zegar[0] += obserwator.ODSTEP_S
        assert obs._ustabilizowany(str(plik)) is False, (
            "po zmianie rozmiaru odliczanie spokoju ma ruszyć od zera")
        zegar[0] += obserwator.SPOKOJ_S
        assert obs._ustabilizowany(str(plik)) is True


class TestSterowanie:
    def test_stan_opisuje_co_sie_dzieje(self, obs):
        s = obs.stan()
        assert set(s) >= {"wlaczony", "dziala", "folder", "przeanalizowane"}

    def test_wylaczony_obserwator_nie_analizuje(self, obs, lib_copy):
        obs.wlaczony = False
        obs._stop.set()
        obs._petla()                                # nie powinno nic zrobić
        assert obs.przeanalizowane == 0
