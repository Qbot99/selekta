"""Endpointy odczytowe dashboardu — TestClient in-process (bez localhost:8756)."""
from __future__ import annotations

import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from selekta import web
from tests.conftest import CORRUPT_FLAC, GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3, real_path


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def _audio_count(folder: str) -> int:
    from selekta.matcher import AUDIO_EXT
    return sum(1 for f in os.listdir(folder) if f.lower().endswith(AUDIO_EXT))


def test_tracks_lists_all_audio(client, lib_copy):
    r = client.get("/api/tracks")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == _audio_count(lib_copy) == len(d["tracks"])
    row = next(t for t in d["tracks"] if t["file"] == GOOD_FLAC)
    assert row["ext"] == "flac" and row["duration"] > 60
    assert row["has_cover"] is True
    assert set(row) >= {"file", "artist", "title", "ext", "sr", "duration", "size_mb"}


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    # ekrany buduje JS (static/ekrany), w HTML jest tylko powłoka
    assert "selekta" in r.text and "/static/ekrany/_powloka.js" in r.text


def test_cover_present_and_missing(client):
    ok = client.get("/api/cover", params={"file": GOOD_FLAC})
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"
    assert ok.content[:3] == b"\xff\xd8\xff"
    # mojibake mp3 nie ma okładki
    missing = client.get("/api/cover", params={"file": MOJIBAKE_MP3})
    assert missing.status_code == 404


def test_analyze_fills_bpm_and_key(client):
    r = client.post("/api/analyze", params={"file": GOOD_FLAC})
    assert r.status_code == 200
    d = r.json()
    assert d["camelot"] == "8A"
    assert 144 <= d["bpm"] <= 148
    assert d["analyzed"] is True


@pytest.mark.slow
def test_track_detail_full_and_strict_json(client):
    r = client.get("/api/track", params={"file": GOOD_FLAC})
    assert r.status_code == 200
    # strict: NaN/Infinity nie przechodzą przez json.loads z parse_constant
    def _no_const(name):  # pragma: no cover - wywołanie oznacza błąd
        raise AssertionError(f"stała {name} w JSON")
    d = json.loads(r.text, parse_constant=_no_const)
    assert set(d) >= {"harmonic", "quality_full", "loudness", "cues", "integrity"}
    assert d["integrity"]["ok"] is True
    assert d["quality_full"]["grade"] == "ok"
    assert -14 < d["loudness"]["integrated_lufs"] < -4
    c = d["cues"]
    assert 0 <= c["first_beat_s"] < c["intro_end_s"] < c["outro_start_s"] <= c["duration_s"]


@pytest.mark.slow
def test_track_detail_corrupt_integrity(tmp_path):
    shutil.copy(real_path(CORRUPT_FLAC), tmp_path / CORRUPT_FLAC)
    web.set_folder(str(tmp_path))
    web._HEALTH_CACHE.update(sig=None, report=None)
    c = TestClient(web.app)
    d = c.get("/api/track", params={"file": CORRUPT_FLAC}).json()
    assert d["integrity"]["ok"] is False
    assert "pobierz ponownie" in d["integrity"]["detail"]


@pytest.mark.slow
def test_health_caches_by_folder_signature(client, lib_copy):
    first = client.get("/api/health").json()
    assert first["cached"] is False
    assert first["files"] == _audio_count(lib_copy)
    second = client.get("/api/health").json()
    assert second["cached"] is True
    assert second["problems"] == first["problems"]
    # zmiana zawartości folderu unieważnia cache
    shutil.copy(real_path(GOOD_MP3), os.path.join(lib_copy, "nowy plik.mp3"))
    third = client.get("/api/health").json()
    assert third["cached"] is False
    assert third["files"] == first["files"] + 1


def test_order_after_analyze(client):
    client.post("/api/analyze", params={"file": GOOD_FLAC})
    d = client.get("/api/order").json()
    files = [o["file"] for o in d["order"]]
    assert GOOD_FLAC in files
    positions = [o["pos"] for o in d["order"]]
    assert positions == sorted(positions)
    assert d["order"][0]["note"] == "start"


def test_slskd_status_and_wishlist_roundtrip(client):
    assert client.get("/api/slskd").json() == {"available": False}
    assert client.get("/api/wishlist").json()["items"] == []
    r = client.post("/api/wishlist", json={"artist": "Test", "title": "Utwór"})
    items = r.json()["items"]
    assert any(i["artist"] == "Test" and i["title"] == "Utwór" for i in items)


def test_download_without_slskd_is_503(client):
    r = client.post("/api/download", json={"artist": "A", "title": "B"})
    assert r.status_code == 503
    assert "slskd" in r.json()["detail"]
