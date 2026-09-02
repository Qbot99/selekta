"""Testy selekta.spotify — parse_input / Track (czyste) + fetch przez embed (@network)."""
from __future__ import annotations

import pytest
import requests

from selekta import spotify
from selekta.spotify import Track, parse_input

TRACK_ID = "6JkQb1qCCJDBV7kW5vJUAH"   # Hardwell, Maddix, Luciana - ACID
DEAD_ID = "0000000000000000000000"    # poprawny format, nieistniejący utwór
PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"  # publiczna playlista Spotify "Today's Top Hits"

_NET_ERRORS = (requests.ConnectionError, requests.Timeout)


# --- parse_input (czyste, bez sieci) ---------------------------------------


def test_parse_input_track_url():
    assert parse_input(f"https://open.spotify.com/track/{TRACK_ID}") == [
        ("track", TRACK_ID)
    ]


def test_parse_input_track_url_with_query_params():
    url = f"https://open.spotify.com/track/{TRACK_ID}?si=abc123&utm_source=copy"
    assert parse_input(url) == [("track", TRACK_ID)]


def test_parse_input_playlist_url():
    assert parse_input(f"https://open.spotify.com/playlist/{PLAYLIST_ID}") == [
        ("playlist", PLAYLIST_ID)
    ]


def test_parse_input_album_url():
    assert parse_input("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy") == [
        ("album", "4aawyAB9vmqN3uQ7FjRGTy")
    ]


def test_parse_input_embed_url():
    assert parse_input(f"https://open.spotify.com/embed/track/{TRACK_ID}") == [
        ("track", TRACK_ID)
    ]


def test_parse_input_duplicates_removed_order_kept():
    text = (
        f"https://open.spotify.com/track/aaa111 "
        f"https://open.spotify.com/playlist/{PLAYLIST_ID} "
        f"https://open.spotify.com/track/aaa111 "
        f"https://open.spotify.com/track/bbb222"
    )
    assert parse_input(text) == [
        ("track", "aaa111"),
        ("playlist", PLAYLIST_ID),
        ("track", "bbb222"),
    ]


def test_parse_input_urls_embedded_in_prose():
    text = (
        "sprawdź to: https://open.spotify.com/track/xyz789 super numer!\n"
        "i jeszcze https://open.spotify.com/embed/playlist/qwe456 na koniec"
    )
    assert parse_input(text) == [("track", "xyz789"), ("playlist", "qwe456")]


def test_parse_input_no_links_returns_empty_list():
    assert parse_input("zwykły tekst bez linków") == []
    assert parse_input("") == []
    assert parse_input("https://example.com/track/abc") == []


def test_parse_input_intl_prefixed_url():
    url = f"https://open.spotify.com/intl-pl/track/{TRACK_ID}"
    assert parse_input(url) == [("track", TRACK_ID)]


# --- Track (czyste) ---------------------------------------------------------


def test_track_query_concatenates_artist_and_title():
    t = Track(id="x", artist="Hardwell, Maddix", title="ACID")
    assert t.query == "Hardwell, Maddix ACID"


def test_track_defaults():
    t = Track(id="abc", artist="A", title="B")
    assert t.duration_s is None
    assert t.cover_url == ""
    assert t.preview_url == ""
    assert t.artists == []


def test_track_artists_default_not_shared_between_instances():
    a = Track(id="1", artist="A", title="T")
    b = Track(id="2", artist="B", title="U")
    a.artists.append("A")
    assert b.artists == []


# --- fetch przez embed (@network) -------------------------------------------


@pytest.mark.network
def test_track_fetch_good_id():
    try:
        t = spotify.track(TRACK_ID)
    except _NET_ERRORS as e:
        pytest.skip(f"brak sieci: {e}")
    assert t.id == TRACK_ID
    assert "Hardwell" in t.artist
    assert t.title == "ACID"
    assert t.duration_s is not None and 170 <= t.duration_s <= 200
    assert t.cover_url.startswith("https://")
    assert t.preview_url.startswith("https://")
    assert "Hardwell" in t.artists and len(t.artists) >= 2
    assert t.query == f"{t.artist} ACID"


@pytest.mark.network
def test_track_fetch_bad_id_raises_runtime_error():
    # RuntimeError z polskim komunikatem, a NIE KeyError z wnętrza parsera
    try:
        with pytest.raises(RuntimeError, match="nierozpoznany utwór"):
            spotify.track(DEAD_ID)
    except _NET_ERRORS as e:
        pytest.skip(f"brak sieci: {e}")


@pytest.mark.network
def test_resolve_skips_dead_link_keeps_good_one():
    text = (
        f"https://open.spotify.com/track/{TRACK_ID}\n"
        f"https://open.spotify.com/track/{DEAD_ID}\n"
    )
    try:
        tracks = spotify.resolve(text)
    except _NET_ERRORS as e:
        pytest.skip(f"brak sieci: {e}")
    assert len(tracks) == 1
    assert tracks[0].id == TRACK_ID
    assert tracks[0].title == "ACID"


@pytest.mark.network
def test_playlist_tracks_public_playlist():
    try:
        tracks = spotify.playlist_tracks(PLAYLIST_ID)
    except _NET_ERRORS as e:
        pytest.skip(f"brak sieci: {e}")
    assert len(tracks) >= 20
    for t in tracks:
        assert isinstance(t, Track)
        assert t.id and t.artist and t.title
        assert t.duration_s is not None and t.duration_s > 0
    # brak duplikatów id w obrębie playlisty
    ids = [t.id for t in tracks]
    assert len(ids) == len(set(ids))


def test_album_pytany_przez_endpoint_albumu(monkeypatch):
    """Regresja z 1.09.2026: '"playlist" if True else "album"' kierowało
    linki do ALBUMÓW na endpoint playlisty; pustą odpowiedź resolve()
    po cichu połykał i album dawał 0 utworów."""
    from selekta import spotify
    zapytane = []

    def udawany_entity(kind, sid):
        zapytane.append((kind, sid))
        return {"trackList": []}

    monkeypatch.setattr(spotify, "_entity", udawany_entity)
    spotify.playlist_tracks("ID1")                      # domyślnie playlista
    spotify.playlist_tracks("ID2", kind="album")
    spotify.resolve("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy")
    assert zapytane == [("playlist", "ID1"), ("album", "ID2"),
                        ("album", "4aawyAB9vmqN3uQ7FjRGTy")]
