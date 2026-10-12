"""Pola, które dashboard pokazywał jako „—", bo backend ich nie oddawał
(3.09.2026): średnia głośność, metryki sesji, prędkość użytkownika
Soulseeka, pamięć radaru, cache analiz, pełne „Przelicz analizę"."""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from selekta import cache, historia, radar, web
from selekta.slskd_client import SearchHit, SlskdClient, _fmt_speed
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    return TestClient(web.app)


def _plik(lib_copy, wzor):
    return os.path.join(lib_copy, os.path.basename(wzor))


class TestStatystykiGlosnosc:
    def test_srednia_lufs_z_cache(self, client, lib_copy):
        a, b = _plik(lib_copy, GOOD_MP3), _plik(lib_copy, GOOD_FLAC)
        for p in (a, b):
            cache.put(p, "harmonic", {"bpm": 128.0, "camelot": "8A", "key": "A minor",
                                      "confidence_bpm": .5, "confidence_key": .9})
        cache.put(a, "loudness", {"integrated_lufs": -6.0, "true_peak_dbtp": 0.1,
                                  "loudness_range_lu": 5.0, "gain_db": -12.0})
        cache.put(b, "loudness", {"integrated_lufs": -9.0, "true_peak_dbtp": -0.5,
                                  "loudness_range_lu": 6.0, "gain_db": -9.0})
        d = client.get("/api/statystyki").json()
        assert d["srednia_lufs"] == -7.5 and d["lufs_min"] == -9.0 and d["lufs_max"] == -6.0
        assert d["z_glosnoscia"] == 2
        z = client.post("/api/statystyki", json={"files": [os.path.basename(a)]}).json()
        assert z["srednia_lufs"] == -6.0 and z["z_glosnoscia"] == 1

    def test_bez_glosnosci_zwraca_none(self, client):
        d = client.get("/api/statystyki").json()
        assert d["srednia_lufs"] is None and d["z_glosnoscia"] == 0


class TestHistoriaMetryki:
    def test_sesja_ma_sciezki_i_metryki(self, client, lib_copy):
        a, b = _plik(lib_copy, GOOD_MP3), _plik(lib_copy, GOOD_FLAC)
        cache.put(a, "harmonic", {"bpm": 126.0, "camelot": "7A", "key": "D minor",
                                  "confidence_bpm": .5, "confidence_key": .9})
        cache.put(b, "harmonic", {"bpm": 130.0, "camelot": "9A", "key": "E minor",
                                  "confidence_bpm": .5, "confidence_key": .9})
        historia.dopisz([historia.Sesja(nazwa="2026-09-02 Smolna", data="2026-09-02",
                                        sciezki=[a, b])])
        sesje = client.get("/api/historia").json()["lista_sesji"]
        assert len(sesje) == 1, "stan historii ma być odizolowany od użytkownika i innych testów"
        s = sesje[0]
        assert s["sciezki"] == [a, b] and s["utworow"] == 2
        assert s["czas_s"] > 0
        assert s["bpm_mediana"] == 128.0      # prawdziwa mediana [126, 130]
        assert s["tonacje"] == ["7A", "9A"] and s["tonacje_opis"] == "7A → 9A"


class TestSoulseekPredkosc:
    def test_describe_oddaje_predkosc_i_kolejke(self):
        c = SlskdClient(base_url="http://localhost:9", api_key="x")
        h = SearchHit("u", "Artist - Tytul.flac", 30_000_000, None, 200, True, True,
                      upload_speed=2_400_000, queue_length=3)
        d = c.describe(h, "Artist", "Tytul", 200)
        assert d["speed"] == "2,4 MB/s" and d["speed_kbs"] == 2400 and d["queue"] == 3

    def test_fmt_speed(self):
        assert _fmt_speed(None) == "" and _fmt_speed(610_000) == "610 kB/s"
        assert _fmt_speed(1_260_000) == "1,3 MB/s"

    def test_predkosc_rozstrzyga_remis_ale_nie_jakosc(self):
        """Szybszy użytkownik wygrywa tylko przy równych plikach — 128 kbps
        od szybkiego nie może wyprzedzić 320 od wolnego."""
        c = SlskdClient(base_url="http://localhost:9", api_key="x")
        wolny320 = SearchHit("w", "A - T.mp3", 9_000_000, 320, 200, False, True, upload_speed=100_000)
        szybki128 = SearchHit("s", "A - T.mp3", 4_000_000, 128, 200, False, True, upload_speed=5_000_000)
        assert c.rank([szybki128, wolny320], 200, "A", "T")[0].bitrate == 320
        a = SearchHit("a", "A - T.flac", 30_000_000, None, 200, True, True, upload_speed=100_000)
        b = SearchHit("b", "A - T.flac", 30_000_000, None, 200, True, True, upload_speed=3_000_000)
        assert c.rank([a, b], 200, "A", "T")[0].username == "b"

    def test_stary_konstruktor_dalej_dziala(self):
        h = SearchHit("u", "x.flac", 1, None, 200, True, True)
        assert h.upload_speed is None and h.queue_length is None


class TestRadarPamiec:
    @pytest.fixture(autouse=True)
    def _izoluj(self, tmp_path, monkeypatch):
        monkeypatch.setattr(radar, "STATE_DIR", str(tmp_path))
        monkeypatch.setattr(radar, "STATE_PATH", str(tmp_path / "radar.json"))
        monkeypatch.setattr(radar, "WYNIKI_PATH", str(tmp_path / "radar-wyniki.json"))

    def test_get_bez_sieci_pusto(self, client):
        d = client.get("/api/radar").json()
        assert d["items"] == [] and d["checked_at"] is None and "total_artists" in d

    def test_sprawdz_oba_sklepy_i_pamiec(self, client, monkeypatch):
        wywolane = []
        monkeypatch.setattr(radar, "artists_from_library", lambda folder: {"Zeta", "Alfa", "Beta"})
        monkeypatch.setattr(radar, "check_bandcamp", lambda a: (wywolane.append(("bc", a)),
            [{"id": f"bc:{a}", "title": f"{a} EP", "url": f"https://bandcamp/{a}", "source": "bandcamp"}])[1])
        monkeypatch.setattr(radar, "check_beatport", lambda a: (wywolane.append(("bp", a)),
            [{"id": f"bp:{a}", "title": f"{a} Remixes", "url": f"https://beatport/{a}",
              "date": "2026-09-01", "source": "beatport"}])[1])
        r = client.post("/api/radar/sprawdz", json={"limit": 2, "offset": 0}).json()
        assert r["checked"] == 2 and r["total_artists"] == 3 and r["next_offset"] == 2
        assert {w[1] for w in wywolane} == {"Alfa", "Beta"}          # alfabetycznie, porcja 2
        assert {x["store"] for x in r["new"]} == {"bandcamp", "beatport"}
        d = client.get("/api/radar").json()
        assert len(d["items"]) == 4 and d["checked_at"] and d["last"]["new"] == 4
        assert all(it["artist"] in ("Alfa", "Beta") and it["znalezione"] for it in d["items"])
        # kolejna porcja dopisuje, bez duplikatów
        r2 = client.post("/api/radar/sprawdz", json={"limit": 2, "offset": 2}).json()
        assert r2["checked"] == 1 and r2["next_offset"] is None
        assert len(client.get("/api/radar").json()["items"]) == 6
        client.post("/api/radar/sprawdz", json={"limit": 5, "offset": 0})
        assert len(client.get("/api/radar").json()["items"]) == 6

    def test_blad_sklepu_to_502_nie_traceback(self, client, monkeypatch):
        monkeypatch.setattr(radar, "artists_from_library", lambda folder: {"X"})
        def pada(a): raise RuntimeError("Bandcamp padł")
        monkeypatch.setattr(radar, "check_bandcamp", pada)
        assert client.post("/api/radar/sprawdz", json={}).status_code == 502


class TestCacheEndpoint:
    def test_stats_i_wyczysc(self, client, lib_copy):
        a = _plik(lib_copy, GOOD_MP3)
        cache.put(a, "harmonic", {"bpm": 128.0, "camelot": "8A", "key": "A minor",
                                  "confidence_bpm": .5, "confidence_key": .9})
        s = client.get("/api/cache").json()
        assert s["_total_entries"] >= 1 and s.get("harmonic", 0) >= 1
        r = client.post("/api/cache/wyczysc", json={"kind": "harmonic"}).json()
        assert r["removed"] >= 1 and r.get("harmonic", 0) == 0
        assert client.post("/api/cache/wyczysc", json={"kind": "../etc"}).status_code == 400
        r = client.post("/api/cache/wyczysc", json={}).json()
        assert r["_total_entries"] == 0


class TestPrzeliczAnalize:
    def test_analyze_liczy_komplet(self, client, lib_copy):
        a = _plik(lib_copy, GOOD_MP3)
        row = client.post(f"/api/analyze?file={os.path.basename(a)}").json()
        assert row["analyzed"] and row["bpm"]
        assert cache.get(a, "loudness") is not None, "głośność ma być przeliczona"
        assert cache.get(a, "cues") is not None, "cue mają być przeliczone"
        q = cache.get(a, "quality")
        assert "bitrate_kbps" in q and row.get("bitrate_kbps") == q["bitrate_kbps"]
