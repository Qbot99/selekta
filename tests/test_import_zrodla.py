"""Importery źródeł — bez sieci (strony i odpowiedzi API podmienione).

Pozycje z przeglądu 0.4.2: ucinanie list bez słowa (Spotify 150→100,
YouTube 186→100, SoundCloud 5/335), link do filmu YouTube = polecane filmy,
link do utworu Apple Music = cały album, Tidal nie działał wcale, URI
„spotify:track:", pominięte po cichu linie i martwe linki.
"""
from __future__ import annotations

import json

import pytest
import requests

from selekta import importers, spotify
from selekta.importers import from_text, resolve_any, split_artist_title


class _Odp:
    def __init__(self, data=None, text="", status=200):
        self._data, self.text, self.status_code = data, text, status
        self.ok = status < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code}", response=self)


# ------------------------------------------------------------------ tekst

@pytest.mark.parametrize("linia,oczekiwane", [
    ("Madonna-Hung Up", ("Madonna", "Hung Up")),
    ("Hung Up by Madonna", ("Madonna", "Hung Up")),
    ("Madonna\tHung Up", ("Madonna", "Hung Up")),
    ("Killed by Death by Motörhead", ("Motörhead", "Killed by Death")),
    ("Stand by Me", None),
    ("Blink-182", None),
])
def test_tekst_nowe_formaty(linia, oczekiwane):
    assert split_artist_title(linia) == oczekiwane


def test_tekst_pominiete_linie_sa_zgloszone():
    t = from_text("Madonna - Hung Up\nbzdura bez separatora\nABBA - SOS\n# komentarz\n")
    assert [x.title for x in t] == ["Hung Up", "SOS"]
    assert len(t.uwagi) == 1 and "bzdura bez separatora" in t.uwagi[0]


# ------------------------------------------------------------------ Spotify

def _embed_tracks(n):
    return [{"uri": f"spotify:track:id{i}", "title": f"T{i}", "subtitle": "A",
             "duration": 200_000} for i in range(n)]


def test_spotify_uri_z_aplikacji(monkeypatch):
    assert spotify.parse_input("spotify:track:3850dYVgOFIXJh5U4BFEWH") == [
        ("track", "3850dYVgOFIXJh5U4BFEWH")]
    monkeypatch.setattr(importers, "spotify_resolve",
                        lambda text: [spotify.Track(id="x", artist="Madonna", title="Hung Up")])
    tracks, origin = resolve_any("spotify:track:3850dYVgOFIXJh5U4BFEWH")
    assert origin == "spotify" and len(tracks) == 1


def test_spotify_ucieta_playlista_mowi_ile_brakuje(monkeypatch):
    monkeypatch.setattr(spotify, "_entity", lambda kind, sid: {"trackList": _embed_tracks(100)})
    monkeypatch.setattr(spotify, "_song_count", lambda kind, sid: 150)
    t = spotify.playlist_tracks("x")
    assert len(t) == 100 and t.zrodlo_total == 150
    assert "100 z 150" in t.uwagi[0]


def test_spotify_krotka_playlista_bez_uwag(monkeypatch):
    monkeypatch.setattr(spotify, "_entity", lambda kind, sid: {"trackList": _embed_tracks(30)})
    monkeypatch.setattr(spotify, "_song_count", lambda kind, sid: pytest.fail("zbędne zapytanie"))
    assert spotify.playlist_tracks("x").uwagi == []


def test_spotify_bez_powtorzen_wykonawcow(monkeypatch):
    sub = "Dimitri Vegas & Like Mike, Marlon Hoffstadt, Dj Konik, Dimitri Vegas, Like Mike"
    monkeypatch.setattr(spotify, "_entity", lambda kind, sid: {"trackList": [
        {"uri": "spotify:track:a", "title": "Makina Time", "subtitle": sub, "duration": 130_000}]})
    t = spotify.playlist_tracks("x")[0]
    assert t.artist == "Dimitri Vegas & Like Mike, Marlon Hoffstadt, Dj Konik"


def test_spotify_martwy_link_jest_zgloszony(monkeypatch):
    def track(sid):
        if sid == "dobry":
            return spotify.Track(id=sid, artist="A", title="B")
        raise RuntimeError("nierozpoznany utwór")
    monkeypatch.setattr(spotify, "track", track)
    t = spotify.resolve("https://open.spotify.com/track/dobry https://open.spotify.com/track/martwy")
    assert len(t) == 1 and "Pominięto 1 z 2" in t.uwagi[0]
    with pytest.raises(ImportError, match="usunięte"):
        spotify.resolve("https://open.spotify.com/track/martwy")


def test_spotify_blad_sieci_to_nie_brak_utworow(monkeypatch):
    def track(sid):
        raise requests.ConnectionError("brak sieci")
    monkeypatch.setattr(spotify, "track", track)
    with pytest.raises(ImportError, match="połączyć ze Spotify"):
        spotify.resolve("https://open.spotify.com/track/abc")


# ------------------------------------------------------------------ YouTube

def _lockup(title, channel="Kanał", czas="3:45"):
    return {"lockupViewModel": {
        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
        "contentImage": {"thumbnailViewModel": {"overlays": [{"text": czas}]}},
        "metadata": {"lockupMetadataViewModel": {
            "title": {"content": title},
            "metadata": {"contentMetadataViewModel": {"metadataRows": [
                {"metadataParts": [{"text": {"content": channel}}]}]}}}}}}


def _cont(token):
    return {"continuationItemViewModel": {"continuationCommand": {"innertubeCommand": {
        "continuationCommand": {"token": token}}}}}


def _yt_page(dane, player=None):
    s = ('<script>var ytcfg={"INNERTUBE_API_KEY":"KLUCZ","INNERTUBE_CLIENT_VERSION":"2.0"};'
         f"var ytInitialData = {json.dumps(dane)};</script>")
    if player is not None:
        s += f"<script>var ytInitialPlayerResponse = {json.dumps(player)};</script>"
    return s


def test_youtube_pojedynczy_film_to_jeden_utwor(monkeypatch):
    """Dawniej: 19–20 polecanych filmów (kabaret, „Świat według Kiepskich")."""
    polecane = {"contents": [_lockup("Kiepski prezydent — CAŁY ODCINEK", "TV", "30:58"),
                             _lockup("Kabaret Moralnego Niepokoju", "TV", "2:49:31")]}
    player = {"videoDetails": {"title": "a-ha - Take On Me (Official Video) [4K]",
                               "author": "a-ha", "lengthSeconds": "244"}}
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: _yt_page(polecane, player))
    for url in ("https://www.youtube.com/watch?v=djV11Xbc914", "https://youtu.be/djV11Xbc914",
                "https://music.youtube.com/watch?v=djV11Xbc914"):
        t, origin = resolve_any(url)
        assert origin == "youtube"
        assert [(x.artist, x.title) for x in t] == [("a-ha", "Take On Me")]
        assert t[0].duration_s is None        # czas teledysku ≠ czas utworu


def test_youtube_playlista_ponad_100_kontynuacja(monkeypatch):
    strona = {"header": {"stats": [{"runs": [{"text": "4"}, {"text": " filmy"}]}]},
              "contents": [_lockup("A - Jeden"), _lockup("B - Dwa (Official 4K Video)"), _cont("T1")]}
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: _yt_page(strona))
    zapytania = []

    def post(url, json=None, headers=None, timeout=None):
        zapytania.append(json["continuation"])
        assert "key=KLUCZ" in url
        return _Odp({"onResponseReceivedActions": [{"appendContinuationItemsAction": {
            "continuationItems": [_lockup("C - Trzy"), _lockup("D - Cztery [HD Remaster]")]}}]})

    monkeypatch.setattr(importers.requests, "post", post)
    t, _ = resolve_any("https://www.youtube.com/playlist?list=PLx")
    assert [x.title for x in t] == ["Jeden", "Dwa", "Trzy", "Cztery"]
    assert zapytania == ["T1"] and t.zrodlo_total == 4 and t.uwagi == []
    assert t[1].duration_s is None and t[0].duration_s == 225


def test_youtube_przerwana_kontynuacja_jest_zgloszona(monkeypatch):
    strona = {"header": {"stats": [{"runs": [{"text": "186"}, {"text": " filmów"}]}]},
              "contents": [_lockup("A - Jeden"), _cont("T1")]}
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: _yt_page(strona))

    def post(*a, **kw):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(importers.requests, "post", post)
    t, _ = resolve_any("https://www.youtube.com/playlist?list=PLx")
    assert len(t) == 1 and "1 z 186" in t.uwagi[0]


@pytest.mark.parametrize("tytul,czysty", [
    ("Toto - Africa (Official HD Video)", "Toto - Africa"),
    ("Madonna - Hung Up (Official 4K Video)", "Madonna - Hung Up"),
    ("Queen - Bohemian Rhapsody [HD Remaster]", "Queen - Bohemian Rhapsody"),
    ("Dire Straits - Walk Of Life (Remastered 2009)", "Dire Straits - Walk Of Life (Remastered 2009)"),
    ("Tom Santa - Rainfall (Praise You)", "Tom Santa - Rainfall (Praise You)"),
])
def test_youtube_szum_w_tytule(tytul, czysty):
    assert importers._oczysc_tytul_yt(tytul)[0] == czysty


# ------------------------------------------------------------------ SoundCloud

def _sc_strona(tracks, total):
    hyd = [{"hydratable": "playlist", "data": {"track_count": total, "tracks": tracks}}]
    return f"<script>window.__sc_hydration = {json.dumps(hyd)};</script>"


def test_soundcloud_doczytuje_reszte_i_poprawia_wykonawce(monkeypatch):
    pelne = [{"id": 1, "title": "Stan Christ - Lucid Dreams", "duration": 180036,
              "publisher_metadata": {"artist": "Revised Records"}, "user": {"username": "Revised"}},
             {"id": 2, "title": "Remon Verhoeve - I Wanna Feel", "duration": 318093,
              "publisher_metadata": {"artist": "Remon Verhoeve"}}]
    stuby = [{"id": 3}, {"id": 4}]
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: _sc_strona(pelne + stuby, 4))
    monkeypatch.setattr(importers, "_sc_client_id", lambda page: "CID")

    def get(url, params=None, headers=None, timeout=None):
        assert params["client_id"] == "CID" and params["ids"] == "3,4"
        return _Odp([{"id": 4, "title": "Track Four", "duration": 200000,
                      "publisher_metadata": {"artist": "HOEHENANGST"}},
                     {"id": 3, "title": "Song - Extended Mix", "duration": 300000,
                      "user": {"username": "Producent"}}])
    monkeypatch.setattr(importers.requests, "get", get)
    t, _ = resolve_any("https://soundcloud.com/revisedrecords/sets/hard-techno-playlist")
    assert [(x.artist, x.title) for x in t] == [
        ("Stan Christ", "Lucid Dreams"), ("Remon Verhoeve", "I Wanna Feel"),
        ("Producent", "Song - Extended Mix"), ("HOEHENANGST", "Track Four")]
    assert t.uwagi == [] and t.zrodlo_total == 4


def test_soundcloud_bez_doczytania_mowi_ile_brakuje(monkeypatch):
    pelne = [{"id": 1, "title": "A - B", "duration": 1000}]
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: _sc_strona(pelne + [{"id": 2}], 335))
    monkeypatch.setattr(importers, "_sc_client_id", lambda page: None)
    t, _ = resolve_any("https://soundcloud.com/x/sets/y")
    assert len(t) == 1 and "1 z 335" in t.uwagi[0]


# ------------------------------------------------------------------ Apple Music

def test_apple_link_do_utworu_to_jeden_utwor(monkeypatch):
    zapytania = []

    def get(url, params=None, headers=None, timeout=None):
        zapytania.append(params)
        return _Odp({"results": [{"wrapperType": "track", "trackId": int(params["id"]),
                                  "trackName": "Mam Cudownych Rodziców",
                                  "artistName": "Urszula Sipinska", "trackTimeMillis": 259787}]})
    monkeypatch.setattr(importers.requests, "get", get)
    monkeypatch.setattr(importers, "_fetch", lambda *a, **k: pytest.fail("album nie powinien być pobierany"))
    for url in ("https://music.apple.com/pl/album/mam-cudownych-rodzicow/1160875454?i=1160877478",
                "https://music.apple.com/pl/song/mam-cudownych-rodzicow/1160877478"):
        t, origin = resolve_any(url)
        assert origin == "apple-music" and len(t) == 1
        assert (t[0].artist, t[0].title, t[0].duration_s) == (
            "Urszula Sipinska", "Mam Cudownych Rodziców", 259.787)
    assert all(z == {"id": "1160877478", "country": "pl"} for z in zapytania)


# ------------------------------------------------------------------ Tidal

_TIDAL_LI = ('<list-item product-id="{i}" product-type="track"><span slot="index">{i}</span>'
             '<span slot="title">{t}</span><span slot="artist"><a href="x">{a}</a>'
             '<a href="y">The 80&#39;s Band</a></span><time slot="duration">3:46</time></list-item>')


def test_tidal_z_publicznego_odtwarzacza(monkeypatch):
    def fetch(url, h=None):
        if url.startswith("https://embed.tidal.com/playlists/"):
            return "".join(_TIDAL_LI.format(i=i, t=f"Utwór {i}", a="Biia") for i in range(50))
        if url.startswith("https://tidal.com/playlist/"):
            return '<meta name="description" content="Playlist - Dub Techno Sessions - 155 items">'
        pytest.fail(url)
    monkeypatch.setattr(importers, "_fetch", fetch)
    t, origin = resolve_any("https://listen.tidal.com/playlist/5c5f3cda-1123-40e6-a866-e66390731d83")
    assert origin == "tidal" and len(t) == 50 and t.zrodlo_total == 155
    assert (t[0].artist, t[0].title, t[0].duration_s) == ("Biia, The 80's Band", "Utwór 0", 226.0)
    assert "50 z 155" in t.uwagi[0]


def test_tidal_album_i_utwor(monkeypatch):
    def fetch(url, h=None):
        if "/albums/" in url:
            return _TIDAL_LI.format(i=1, t="Physical", a="80s Greatest Hits")
        if "/tracks/" in url:
            return ('<h1 class="media-title" title="Track: Physical">Physical</h1>'
                    '<span class="media-artist"><a>80s Greatest Hits</a></span>')
        pytest.fail(url)
    monkeypatch.setattr(importers, "_fetch", fetch)
    assert resolve_any("https://tidal.com/browse/album/50155180")[0][0].title == "Physical"
    t = resolve_any("https://tidal.com/browse/track/50155181")[0]
    assert [(x.artist, x.title) for x in t] == [("80s Greatest Hits", "Physical")]


# ------------------------------------------------------------------ 1001Tracklists

def test_1001_gosc_zostaje_przy_wykonawcy(monkeypatch):
    strona = ('<div itemprop="tracks"><meta itemprop="name" content="CamelPhat ft. Ali Love - '
              'Constellations"><meta itemprop="byArtist" content="CamelPhat"></div>')
    monkeypatch.setattr(importers, "_fetch", lambda url, h=None: strona)
    t = importers.from_1001tracklists("https://www.1001tracklists.com/tracklist/x")
    assert (t[0].artist, t[0].title) == ("CamelPhat ft. Ali Love", "Constellations")
