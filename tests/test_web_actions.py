"""Endpointy akcji (mutujące) — wyłącznie na kopiach lib_copy."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from mutagen import File as MutagenFile

from selekta import web
from tests.conftest import GOOD_FLAC, MOJIBAKE_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def test_import_empty_and_garbage(client):
    assert client.post("/api/import", json={"text": ""}).status_code == 400
    r = client.post("/api/import", json={"text": "totalny śmieć bez żadnych linków ani formatu"})
    assert r.status_code == 400
    assert "rozpozna" in r.json()["detail"]


def test_import_text_tracklist_offline(client):
    # tracklista tekstowa nie wymaga sieci; Gucci jest w lib_copy
    r = client.post("/api/import", json={"text": "Odymel - Gucci\nNieistniejący Artysta - Widmo Utworu"})
    assert r.status_code == 200
    d = r.json()
    assert d["counts"]["total"] == 2
    assert d["counts"]["auto"] + d["counts"]["resolve"] >= 1
    assert d["counts"]["missing"] >= 1
    missing = d["missing"][0]
    # kilka sklepów (pop: Qobuz/Apple przodem), „buy" = pierwszy z nich
    assert missing["buy"] == missing["sklepy"][0]["url"]
    assert {s["id"] for s in missing["sklepy"]} >= {"beatport", "qobuz", "apple", "bandcamp"}


@pytest.mark.network
def test_import_spotify_links(client):
    r = client.post("/api/import", json={
        "text": "https://open.spotify.com/track/5jWqlILvwGMwsk3ZKfhxPU"})
    if r.status_code != 200:
        pytest.skip("Spotify niedostępne")
    d = r.json()
    assert d["origin"] == "spotify"
    assert d["counts"]["total"] == 1
    assert d["counts"]["auto"] == 1  # Gucci jest w lib_copy


@pytest.mark.slow
def test_dedupe_plan_and_apply(client, lib_copy):
    plan = client.get("/api/dedupe").json()["actions"]
    assert len(plan) == 1
    assert plan[0]["keep"] == GOOD_FLAC
    assert plan[0]["remove"] == ["Odymel - Gucci.wav"]
    res = client.post("/api/dedupe/apply").json()
    assert res["moved"] == 1 and res["reclaimed_mb"] > 40
    trash = os.path.join(lib_copy, "_selekta_kosz")
    assert os.path.isfile(os.path.join(trash, "Odymel - Gucci.wav"))
    assert os.path.isfile(os.path.join(lib_copy, GOOD_FLAC))  # keep nietknięty


def test_tagfix_scan_and_apply(client, lib_copy):
    hits = client.get("/api/tagfix").json()["hits"]
    assert [h["file"] for h in hits] == [MOJIBAKE_MP3]
    assert hits[0]["suggested"] == "ÅMRTÜM"
    fixed = client.post("/api/tagfix/apply").json()
    assert fixed["fixed"] == 1
    tag = MutagenFile(os.path.join(lib_copy, MOJIBAKE_MP3)).tags
    assert str(tag.get("TPE1")) == "ÅMRTÜM"
    # drugi scan: czysto
    assert client.get("/api/tagfix").json()["hits"] == []


def test_export_targets(client, lib_copy):
    r = client.post("/api/export", json={"target": "m3u8", "name": "testset"})
    assert r.status_code == 200
    d = r.json()
    assert os.path.isfile(d["path"]) and d["path"].endswith("testset.m3u8")
    assert d["count"] == 4  # 4 pliki audio w lib_copy
    bad = client.post("/api/export", json={"target": "winamp"})
    assert bad.status_code == 400
    assert "nieznany cel" in bad.json()["detail"]


def test_export_rekordbox_parses(client, lib_copy):
    import xml.etree.ElementTree as ET
    d = client.post("/api/export", json={"target": "rekordbox", "name": "rbx"}).json()
    root = ET.parse(d["path"]).getroot()
    assert root.tag == "DJ_PLAYLISTS"
    assert len(root.findall(".//COLLECTION/TRACK")) == d["count"]


def test_usb_endpoint(client, tmp_path_factory):
    bad = client.post("/api/usb", json={"dest": ""})
    assert bad.status_code == 400
    # cel POZA biblioteką: lib_copy to samo tmp_path, a folder docelowy
    # w bibliotece jest teraz odrzucany (kopie wracały do niej jako „(2)")
    dest = str(tmp_path_factory.mktemp("usb-cel") / "usb")
    r = client.post("/api/usb", json={"dest": dest, "convert": "keep"})
    assert r.status_code == 200
    d = r.json()
    assert d["copied"] + d["converted"] == 4
    names = os.listdir(dest)
    assert all(n.isascii() for n in names), names


def test_redownload_queues_wishlist(client):
    # wpis z TAGÓW istniejącego pliku (Odymel / Gucci), nie z nazwy pliku;
    # nieistniejący plik to błąd, a nie śmieciowy wpis na liście życzeń
    r = client.post("/api/redownload", json={"file": GOOD_FLAC})
    assert r.status_code == 200
    items = client.get("/api/wishlist").json()["items"]
    assert any(i["artist"] == "Odymel" and i["title"] == "Gucci" for i in items)
    r = client.post("/api/redownload", json={"file": "Artysta X - Zaginiony.flac"})
    assert r.status_code == 404


def test_redownload_bierze_tagi_a_nie_numer_sciezki(client, lib_copy):
    """Przegląd 0.4.2: „01 - Hung Up.flac" → artysta „01"."""
    from tests.conftest import fast_copy
    fast_copy(os.path.join(lib_copy, GOOD_FLAC), os.path.join(lib_copy, "01 - Cokolwiek.flac"))
    r = client.post("/api/redownload", json={"file": "01 - Cokolwiek.flac"})
    assert r.status_code == 200
    assert (r.json()["artist"], r.json()["title"]) == ("Odymel", "Gucci")
    r = client.post("/api/redownload", json={"file": "07 - Zaginiony Utwór.flac"})
    assert r.status_code == 404, "nieistniejący plik — nie tworzymy wpisu bez artysty"
    tytuly = [i["title"] for i in client.get("/api/wishlist").json()["items"]]
    assert tytuly.count("Gucci") == 1


def test_wishlist_api_zapisuje_czas_i_nie_dubluje(client):
    for _ in range(2):
        client.post("/api/wishlist", json={"artist": "Madonna", "title": "Hung Up",
                                           "duration": 337.7})
    items = client.get("/api/wishlist").json()["items"]
    assert len(items) == 1 and items[0]["duration_s"] == 337.7
