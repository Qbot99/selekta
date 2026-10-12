"""Radar — regresje z przeglądu 0.4.2 (sieć podstawiona atrapą).

Przed naprawą: dla artysty bez dokładnego trafienia Bandcamp brał pierwszy
wynik wyszukiwarki („best guess”) i meldował cudzą dyskografię; tytuły
„/track/intro” szły na listę życzeń; karty nie miały okładek ani wytwórni;
„Sprawdź teraz” pytało w kółko o tych samych 10 artystów; limit „abc” → 500.
"""
from __future__ import annotations

import json

import pytest

from selekta import radar


@pytest.fixture(autouse=True)
def _izoluj(tmp_path, monkeypatch):
    monkeypatch.setattr(radar, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(radar, "STATE_PATH", str(tmp_path / "radar.json"))
    monkeypatch.setattr(radar, "WYNIKI_PATH", str(tmp_path / "radar-wyniki.json"))


SZUKAJ_ABBA = """
<div class="itemurl"><a href="https://abba.bandcamp.com/?from=search">x</a></div>
<div class="heading"><a href="#">abba</a></div>
"""


def test_bandcamp_bez_dokladnego_trafienia_nie_zgaduje(monkeypatch):
    monkeypatch.setattr(radar, "_get", lambda url: SZUKAJ_ABBA.replace("abba</a>", "ham and cheese</a>"))
    monkeypatch.setattr(radar, "_post_json", lambda url, p: {"auto": {"results": [
        {"type": "b", "name": "Nantzin Anastacia", "item_url_root": "https://x.bandcamp.com"}]}})
    assert radar._bandcamp_artist_page("ABBA") is None
    assert radar._bandcamp_artist_page("Anastacia") is None


def test_bandcamp_dokladne_trafienie_dziala(monkeypatch):
    monkeypatch.setattr(radar, "_get", lambda url: SZUKAJ_ABBA)
    assert radar._bandcamp_artist_page("ABBA") == "https://abba.bandcamp.com"


def test_bandcamp_tytul_ze_sciezki_i_okladka(monkeypatch):
    strona = ('<li><a href="/track/body-beat">x</a>'
              '<img class="art" src="https://f4.bcbits.com/img/a123_2.jpg"></li>')
    monkeypatch.setattr(radar, "_bandcamp_artist_page", lambda a: "https://alt8.bandcamp.com")
    monkeypatch.setattr(radar, "_get", lambda url: strona)
    (it,) = radar.fetch_bandcamp("Alt8")              # pełny katalog, bez pamięci radaru
    assert it["title"] == "Body Beat"
    assert it["cover"] == "https://f4.bcbits.com/img/a123_2.jpg"


def test_beatport_okladka_i_wytwornia(monkeypatch):
    dane = {"props": {"releases": [{
        "release_id": 7, "release_name": "Break", "release_date": "2026-10-01",
        "artists": [{"artist_name": "Afem Syko"}],
        "label": {"label_name": "Speedmaster Records"},
        "release_image_uri": "https://geo-media.beatport.com/image_size/500x500/x.jpg"}]}}
    strona = ('<script id="__NEXT_DATA__" type="application/json">'
              + json.dumps(dane) + "</script>")
    monkeypatch.setattr(radar, "_get", lambda url: strona)
    (it,) = radar.check_beatport("Afem Syko")
    assert it["label"] == "Speedmaster Records"
    assert it["cover"].startswith("https://geo-media.beatport.com/")


def test_sprawdz_teraz_idzie_dalej_po_artystach(monkeypatch):
    from fastapi.testclient import TestClient
    from selekta import web
    monkeypatch.setattr(radar, "artists_from_library", lambda f: {f"A{i:02d}" for i in range(25)})
    pytani = []
    monkeypatch.setattr(radar, "check_bandcamp", lambda a: pytani.append(a) or [])
    monkeypatch.setattr(radar, "check_beatport", lambda a: [])
    c = TestClient(web.app)
    c.post("/api/radar/sprawdz", json={"limit": 10})
    c.post("/api/radar/sprawdz", json={"limit": 10})
    assert pytani[:10] != pytani[10:20]
    assert pytani[10] == "A10"
    assert c.post("/api/radar/sprawdz", json={"limit": "abc"}).status_code == 400
