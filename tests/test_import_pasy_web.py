"""/api/import i /api/playlist/collect: cudzy plik nigdy nie trafia do setu.

Przed naprawą pas „do rozstrzygnięcia" przyjmował wynik ≥ 0,5 albo
identity ≥ 0,75 — np. „Michael Jackson — Beat It" → „Linds - Kick It.wav".
Kreator wkładał ten pas do kolumny „masz", a collect uznawał utwór za
obecny, więc brakujący utwór po cichu znikał z setu.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from selekta import importers, matcher, web
from selekta.spotify import Track
from tests.conftest import GOOD_FLAC

DANE = json.load(open(os.path.join(os.path.dirname(__file__),
                                   "dane_dopasowania.json"), encoding="utf-8"))


def _indeks():
    out = []
    for rel, artist, title, dur in DANE["biblioteka"]:
        stem = os.path.splitext(os.path.basename(rel))[0]
        tok = matcher.normalize(stem) + matcher.normalize(title) + matcher.normalize(artist)
        out.append(matcher.IndexEntry("/biblioteka/" + rel, tok, dur or None,
                                      {"title": title, "artist": artist}))
    return out


@pytest.fixture()
def klient(monkeypatch, tmp_path):
    web.set_folder(str(tmp_path))
    monkeypatch.setattr(web.matcher, "library_index", lambda folder: _indeks())
    return TestClient(web.app)


def _importuj(klient, monkeypatch, utwory):
    tracks = [Track(id="", artist=a, title=t, duration_s=d) for a, t, d in utwory]
    monkeypatch.setattr(importers, "resolve_any", lambda text: (tracks, "spotify"))
    r = klient.post("/api/import", json={"text": "https://open.spotify.com/playlist/x"})
    assert r.status_code == 200, r.text
    return r.json()


def test_playlista_100lecie_pasy(klient, monkeypatch):
    utwory = [(a, t, d) for _e, a, t, d, _f in DANE["playlista_100lecie"]]
    d = _importuj(klient, monkeypatch, utwory)
    assert d["counts"] == {"auto": 22, "resolve": 3, "missing": 5, "total": 30, "zrodlo": 30}
    assert d["uwagi"] == []
    # pas „resolve" to wyłącznie INNA WERSJA tego samego utworu
    assert all(r["other_version"] for r in d["resolve"])
    assert {r["title"] for r in d["resolve"]} == {
        "Mas Que Nada - Radio Edit", "To the Moon & Back", "Makina Time"}
    assert "Sultans Of Swing" in {r["title"] for r in d["missing"]}
    to_the_moon = next(r for r in d["resolve"] if r["title"] == "To the Moon & Back")
    assert to_the_moon["file_duration"] == 280 and to_the_moon["duration"] == 339


def test_utwory_spoza_biblioteki_ida_do_sciagniecia(klient, monkeypatch):
    d = _importuj(klient, monkeypatch, [
        ("Michael Jackson", "Beat It", 258), ("Madonna", "Let It Will Be", 260.9),
        ("Madonna", "Jump", 238.6), ("a-ha", "Take on Me", 225),
        ("Madonna", "Hung Up", 337.7)])
    assert d["counts"]["missing"] == 4 and d["counts"]["resolve"] == 0
    assert [r["title"] for r in d["auto"]] == ["Hung Up"]
    for r in d["missing"]:
        assert "file" not in r
        # zakup: kilka sklepów, nie tylko Beatport (dla popu Beatport jest pusty)
        assert len(r["sklepy"]) >= 4 and r["buy"] == r["sklepy"][0]["url"]


def test_collect_nie_dobiera_cudzego_pliku(lib_copy):
    """Gucci Gang ani „Ktoś Inny — Gucci" to nie „Odymel — Gucci"."""
    web.set_folder(lib_copy)
    c = TestClient(web.app)
    cudze = [{"artist": "Odymel", "title": "Gucci Gang", "duration": 274},
             {"artist": "Ktoś Inny", "title": "Gucci", "duration": 274}]
    r = c.post("/api/playlist/collect", json={
        "name": "bez-cudzych", "files": [], "tracks": cudze})
    # przed naprawą: 200 i „Odymel - Gucci.flac" w secie zamiast Gucci Gang
    assert r.status_code == 400, r.text
    r = c.post("/api/playlist/collect", json={
        "name": "bez-cudzych", "files": [],
        "tracks": cudze + [{"artist": "Odymel", "title": "Gucci", "duration": 274}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["late"] == [GOOD_FLAC]
    assert d["count"] == 1


def test_collect_bez_wlasciwej_wersji_nie_bierze_innej(lib_copy):
    """Inna wersja trafia do setu tylko wtedy, gdy użytkownik sam ją wybrał
    (przychodzi w `files`); dociąganie po nazwie bierze tylko tę samą."""
    web.set_folder(lib_copy)
    c = TestClient(web.app)
    r = c.post("/api/playlist/collect", json={
        "name": "inna-wersja", "files": [],
        "tracks": [{"artist": "Odymel", "title": "Gucci (Techno Remix)", "duration": 274}],
    })
    assert r.status_code == 400
    r = c.post("/api/playlist/collect", json={
        "name": "inna-wersja", "files": [GOOD_FLAC],
        "tracks": [{"artist": "Odymel", "title": "Gucci (Techno Remix)", "duration": 274}],
    })
    assert r.status_code == 200 and r.json()["count"] == 1
