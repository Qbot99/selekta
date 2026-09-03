"""Doktor — kontrola integracji. Bez sieci: sondy podmieniamy na atrapy.

Sprawdzamy mechanikę: izolację błędów (jedna sonda nie zabija reszty),
limit czasu, zapis i odczyt ostatniego wyniku, kody wyjścia w CLI.
"""
from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from selekta import config, doktor, web


@pytest.fixture(autouse=True)
def _izolowany_wynik(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(doktor, "PLIK_WYNIKU", str(tmp_path / "doktor.json"))


def _ok(nazwa):
    return lambda: doktor.Sonda(nazwa, True, "działa")


def _pada(nazwa, krytyczna=True):
    return lambda: doktor.Sonda(nazwa, False, "milczy", krytyczna=krytyczna)


def _wyjatek():
    raise ConnectionError("sieć padła")


def _wisi():
    time.sleep(60)


class TestMechanika:
    def test_wyjatek_w_sondzie_to_czysty_wynik(self, monkeypatch):
        monkeypatch.setattr(doktor, "SONDY", [("Spotify", _wyjatek), ("ffmpeg", _ok("ffmpeg"))])
        r = doktor.zbadaj()
        spotify = next(w for w in r["wyniki"] if w["nazwa"] == "Spotify")
        assert spotify["ok"] is False and "ConnectionError" in spotify["opis"]
        assert next(w for w in r["wyniki"] if w["nazwa"] == "ffmpeg")["ok"] is True

    def test_zawieszona_sonda_nie_blokuje_reszty(self, monkeypatch):
        monkeypatch.setattr(doktor, "LIMIT_S", 0.3)
        monkeypatch.setattr(doktor, "SONDY", [("YouTube", _wisi), ("ffmpeg", _ok("ffmpeg"))])
        start = time.time()
        r = doktor.zbadaj()
        assert time.time() - start < 5
        yt = next(w for w in r["wyniki"] if w["nazwa"] == "YouTube")
        assert yt["ok"] is False and "brak odpowiedzi" in yt["opis"]

    def test_krytyczne_ok_odroznia_rdzen_od_dodatkow(self, monkeypatch):
        monkeypatch.setattr(doktor, "SONDY", [("ffmpeg", _ok("ffmpeg")),
                                              ("Beatport", _pada("Beatport", krytyczna=False))])
        r = doktor.zbadaj()
        assert r["wszystko_ok"] is False and r["krytyczne_ok"] is True

    def test_wynik_zapisany_i_odczytany(self, monkeypatch):
        monkeypatch.setattr(doktor, "SONDY", [("ffmpeg", _ok("ffmpeg"))])
        r = doktor.zbadaj()
        assert os.path.exists(doktor.PLIK_WYNIKU)
        assert doktor.ostatni()["kiedy"] == r["kiedy"]

    def test_brak_wyniku_to_none(self):
        assert doktor.ostatni() is None

    def test_tylko_lokalne_pomija_siec(self, monkeypatch):
        wywolane = []
        monkeypatch.setattr(doktor, "SONDY", [
            ("ffmpeg", lambda: (wywolane.append("ffmpeg"), doktor.Sonda("ffmpeg", True, ""))[1]),
            ("Spotify", lambda: (wywolane.append("Spotify"), doktor.Sonda("Spotify", True, ""))[1])])
        doktor.zbadaj(tylko_lokalne=True)
        assert wywolane == ["ffmpeg"]

    def test_raport_tekstowy(self, monkeypatch):
        monkeypatch.setattr(doktor, "SONDY", [("ffmpeg", _ok("ffmpeg")),
                                              ("Spotify", _pada("Spotify"))])
        t = doktor.format_report(doktor.zbadaj())
        assert "✅ ffmpeg" in t and "❌ Spotify" in t
        assert "brakuje czegoś" in t


class TestPrawdziweSondyLokalne:
    def test_ffmpeg_na_tej_maszynie(self):
        s = doktor._ffmpeg()
        assert s.ok, s.opis
        assert "ffmpeg version" in s.opis


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    return TestClient(web.app)


class TestEndpoint:
    def test_get_bez_wyniku(self, client):
        d = client.get("/api/doktor").json()
        assert d["kiedy"] is None and d["wyniki"] == []

    def test_post_odpala_i_get_pamieta(self, client, monkeypatch):
        monkeypatch.setattr(doktor, "SONDY", [("ffmpeg", _ok("ffmpeg"))])
        r = client.post("/api/doktor", json={"tylko_lokalne": True}).json()
        assert r["wszystko_ok"] is True
        assert client.get("/api/doktor").json()["kiedy"] == r["kiedy"]
        with open(doktor.PLIK_WYNIKU, encoding="utf-8") as fh:
            assert json.load(fh)["kiedy"] == r["kiedy"]
