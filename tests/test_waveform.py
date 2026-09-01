"""Przebieg fali i ręczna korekta siatki beatów.

Najważniejsza własność: poprawka wprowadzona ręcznie przeżywa
przetagowanie pliku. Apka sama zmienia tagi i okładki, a każda taka
zmiana zmienia sygnaturę pliku — gdyby korekty trzymać w zwykłej pamięci
podręcznej, praca użytkownika znikałaby bez ostrzeżenia.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import waveform, web
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy, tmp_path, monkeypatch):
    monkeypatch.setattr(waveform, "PLIK_SIATEK", str(tmp_path / "siatki.json"))
    monkeypatch.setattr(waveform.config, "STATE_DIR", str(tmp_path))
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


class TestObliczanie:
    def test_zwraca_obie_obwiednie(self, lib_copy):
        d = waveform.oblicz(os.path.join(lib_copy, GOOD_MP3), punkty=200)
        assert d["punkty"] == 200
        assert len(d["szczyt"]) == len(d["rms"]) == 200
        assert d["czas_s"] > 0

    def test_wartosci_sa_znormalizowane(self, lib_copy):
        d = waveform.oblicz(os.path.join(lib_copy, GOOD_FLAC), punkty=100)
        assert 0.99 <= max(d["szczyt"]) <= 1.0
        assert all(0.0 <= v <= 1.0 for v in d["szczyt"])
        assert all(0.0 <= v <= 1.0 for v in d["rms"])

    def test_szczyt_nie_jest_mniejszy_od_rms(self, lib_copy):
        d = waveform.oblicz(os.path.join(lib_copy, GOOD_FLAC), punkty=100)
        assert all(s >= r - 1e-9 for s, r in zip(d["szczyt"], d["rms"]))

    def test_nieczytelny_plik_nie_wywala(self, tmp_path):
        zly = tmp_path / "nie-audio.flac"
        zly.write_bytes(b"to nie jest dzwiek")
        d = waveform.oblicz(str(zly))
        assert d["punkty"] == 0 and d["szczyt"] == []

    def test_liczba_punktow_ma_rozsadne_granice(self, lib_copy):
        maly = waveform.oblicz(os.path.join(lib_copy, GOOD_MP3), punkty=1)
        duzy = waveform.oblicz(os.path.join(lib_copy, GOOD_MP3), punkty=99999)
        assert maly["punkty"] >= 16 and duzy["punkty"] <= 4000


class TestKorektaPrzezywaPrzetagowanie:
    def test_zapis_i_odczyt(self, lib_copy, tmp_path, monkeypatch):
        monkeypatch.setattr(waveform, "PLIK_SIATEK", str(tmp_path / "s.json"))
        monkeypatch.setattr(waveform.config, "STATE_DIR", str(tmp_path))
        plik = os.path.join(lib_copy, GOOD_MP3)
        waveform.zapisz_siatke(plik, 1.2345, 145.0)
        assert waveform.wczytaj_siatke(plik) == {"first_beat_s": 1.2345, "bpm": 145.0}

    def test_dotkniecie_pliku_nie_kasuje_korekty(self, lib_copy, tmp_path,
                                                 monkeypatch):
        """Zapis tagów zmienia mtime — korekta ma przetrwać."""
        monkeypatch.setattr(waveform, "PLIK_SIATEK", str(tmp_path / "s.json"))
        monkeypatch.setattr(waveform.config, "STATE_DIR", str(tmp_path))
        plik = os.path.join(lib_copy, GOOD_MP3)
        waveform.zapisz_siatke(plik, 0.5)
        os.utime(plik, None)
        assert waveform.wczytaj_siatke(plik) == {"first_beat_s": 0.5}

    def test_kasowanie_wraca_do_wyliczonej(self, lib_copy, tmp_path, monkeypatch):
        monkeypatch.setattr(waveform, "PLIK_SIATEK", str(tmp_path / "s.json"))
        monkeypatch.setattr(waveform.config, "STATE_DIR", str(tmp_path))
        plik = os.path.join(lib_copy, GOOD_MP3)
        waveform.zapisz_siatke(plik, 0.5)
        assert waveform.skasuj_siatke(plik) is True
        assert waveform.wczytaj_siatke(plik) is None
        assert waveform.skasuj_siatke(plik) is False


class TestEndpointy:
    def test_waveform_zwraca_siatke_i_cue(self, client):
        d = client.get(f"/api/waveform?file={GOOD_MP3}").json()
        assert d["punkty"] > 0
        assert "first_beat_s" in d and "bpm" in d
        assert set(d["cues"]) == {"intro", "drop", "outro"}
        assert d["reczna_korekta"] is False

    def test_zapis_korekty_zmienia_kotwice(self, client, lib_copy):
        r = client.post("/api/siatka",
                        json={"file": GOOD_MP3, "first_beat_s": 2.5, "bpm": 140})
        assert r.status_code == 200 and r.json()["reczna_korekta"] is True
        d = client.get(f"/api/waveform?file={GOOD_MP3}").json()
        assert d["first_beat_s"] == 2.5
        assert d["reczna_korekta"] is True
        assert d["wyliczony_first_beat_s"] != 2.5, "wyliczona zostaje do porównania"

    def test_reset_wraca_do_wyliczonej(self, client):
        client.post("/api/siatka", json={"file": GOOD_MP3, "first_beat_s": 2.5})
        r = client.post("/api/siatka", json={"file": GOOD_MP3, "reset": True})
        assert r.status_code == 200 and r.json()["reczna_korekta"] is False
        assert client.get(f"/api/waveform?file={GOOD_MP3}").json()[
            "reczna_korekta"] is False

    def test_bezsensowne_wartosci_odrzucone(self, client):
        assert client.post("/api/siatka",
                           json={"file": GOOD_MP3, "first_beat_s": -1}).status_code == 400
        assert client.post("/api/siatka",
                           json={"file": GOOD_MP3, "first_beat_s": 99999}).status_code == 400
        assert client.post("/api/siatka",
                           json={"file": GOOD_MP3, "first_beat_s": "abc"}).status_code == 400
        assert client.post("/api/siatka",
                           json={"file": GOOD_MP3, "first_beat_s": 1,
                                 "bpm": 999}).status_code == 400

    def test_nie_wypuszcza_plikow_spoza_biblioteki(self, client):
        assert client.get("/api/waveform?file=../../etc/hosts").status_code == 400
        assert client.post("/api/siatka",
                           json={"file": "../../etc/hosts",
                                 "first_beat_s": 1}).status_code == 400
