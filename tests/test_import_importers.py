"""Testy selekta.importers — split_artist_title / from_text / resolve_any.

Część czysta bez sieci (dispatch testowany przez monkeypatch), plus jeden
test @network na prawdziwej playliście YouTube.
"""
from __future__ import annotations

import pytest
import requests

from selekta import importers
from selekta.importers import (
    _clock_s,
    _iso_duration_s,
    from_text,
    resolve_any,
    split_artist_title,
)
from selekta.spotify import Track

_NET_ERRORS = (requests.ConnectionError, requests.Timeout)


# --- split_artist_title -----------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Artist - Title", ("Artist", "Title")),
        ("01. Artist - Title", ("Artist", "Title")),
        ("1) A - B", ("A", "B")),
        ("3] Foo - Bar", ("Foo", "Bar")),
        ("[0:23:45] A - B", ("A", "B")),
        ("(23:45) A - B", ("A", "B")),
        ("23:45 A - B", ("A", "B")),
        # numeracja + znacznik czasu naraz
        ("01. [0:23:45] A - B", ("A", "B")),
        # goły numer jako pierwszy segment "01 - Artist - Title"
        ("01 - Artist - Title", ("Artist", "Title")),
        # en dash i em dash
        ("A – B", ("A", "B")),
        ("A — B", ("A", "B")),
        # myślnik w nazwisku przeżywa (bez spacji wokół "-")
        ("Jean-Michel Jarre - Oxygene", ("Jean-Michel Jarre", "Oxygene")),
        # dodatkowe " - " w tytule zostaje sklejone z powrotem
        ("A - B - C", ("A", "B - C")),
        # białe znaki dookoła
        ("   Artist   -   Title  ", ("Artist", "Title")),
        # unicode
        ("Åmrtüm - Dash", ("Åmrtüm", "Dash")),
    ],
)
def test_split_artist_title_ok(line, expected):
    assert split_artist_title(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Just A Title",          # brak separatora " - "
        "",                       # pusta linia
        "   ",                    # same spacje
        "Artist - ",              # pusty tytuł
        " - ",                    # pusty artysta i tytuł
        "Artist-Title",           # myślnik bez spacji to nie separator
    ],
)
def test_split_artist_title_returns_none(line):
    assert split_artist_title(line) is None


# --- from_text --------------------------------------------------------------


def test_from_text_three_lines_three_tracks():
    text = "1. Foo - Bar\n2. Baz - Qux\n[1:02:03] Ala - Kot\n"
    tracks = from_text(text)
    assert [(t.artist, t.title) for t in tracks] == [
        ("Foo", "Bar"),
        ("Baz", "Qux"),
        ("Ala", "Kot"),
    ]
    for t in tracks:
        assert isinstance(t, Track)
        assert t.id.startswith("text:")
    # syntetyczne id są unikalne per (artist, title)
    assert len({t.id for t in tracks}) == 3


def test_from_text_dedup_case_insensitive():
    text = "Foo - Bar\nfoo - bar\nFOO - BAR\nFoo - Baz\n"
    tracks = from_text(text)
    assert [(t.artist, t.title) for t in tracks] == [("Foo", "Bar"), ("Foo", "Baz")]


def test_from_text_skips_blank_and_unparseable_lines():
    text = "\n\nnie ma separatora\nFoo - Bar\n\n???\n"
    tracks = from_text(text)
    assert [(t.artist, t.title) for t in tracks] == [("Foo", "Bar")]


def test_from_text_empty_input():
    assert from_text("") == []
    assert from_text("\n\n   \n") == []


def test_from_text_synth_id_stable():
    a = from_text("Foo - Bar")[0]
    b = from_text("foo - BAR")[0]  # id liczone z lowercase → identyczne
    assert a.id == b.id


# --- resolve_any (czyste + dispatch przez monkeypatch) ----------------------


def test_resolve_any_plain_text():
    tracks, source = resolve_any("Foo - Bar\nBaz - Qux")
    assert source == "tekst"
    assert [(t.artist, t.title) for t in tracks] == [("Foo", "Bar"), ("Baz", "Qux")]


def test_resolve_any_text_without_tracks_raises_polish_import_error():
    with pytest.raises(ImportError, match="nie rozpoznano żadnych utworów"):
        resolve_any("to tylko luźny tekst\nbez żadnych utworów")


def test_resolve_any_empty_string_raises():
    with pytest.raises(ImportError):
        resolve_any("")


def test_resolve_any_unknown_host_raises_polish_import_error():
    with pytest.raises(ImportError, match="nieznane źródło: example.com"):
        resolve_any("https://example.com/playlist/123")


def test_resolve_any_dispatches_spotify(monkeypatch):
    sentinel = [Track(id="s1", artist="A", title="T")]
    seen = {}

    def fake_resolve(text):
        seen["text"] = text
        return sentinel

    monkeypatch.setattr(importers, "spotify_resolve", fake_resolve)
    url = "https://open.spotify.com/track/6JkQb1qCCJDBV7kW5vJUAH"
    tracks, source = resolve_any(url)
    assert source == "spotify"
    assert tracks is sentinel
    assert seen["text"] == url  # do spotify trafia cały wklejony tekst


def test_resolve_any_dispatches_apple_music_and_adds_scheme(monkeypatch):
    seen = {}

    def fake_apple(url):
        seen["url"] = url
        return [Track(id="a1", artist="X", title="Y")]

    monkeypatch.setattr(importers, "from_apple_music", fake_apple)
    # goły host bez https:// też ma zadziałać
    tracks, source = resolve_any("music.apple.com/pl/playlist/top/pl.abc123")
    assert source == "apple-music"
    assert seen["url"] == "https://music.apple.com/pl/playlist/top/pl.abc123"
    assert [(t.artist, t.title) for t in tracks] == [("X", "Y")]


@pytest.mark.parametrize(
    "url, source, attr",
    [
        ("https://www.youtube.com/playlist?list=PLx", "youtube", "from_youtube"),
        ("https://tidal.com/browse/playlist/uuid-1", "tidal", "from_tidal"),
        ("https://www.1001tracklists.com/tracklist/x/y.html", "1001tracklists",
         "from_1001tracklists"),
        ("https://soundcloud.com/user/sets/myset", "soundcloud", "from_soundcloud"),
    ],
)
def test_resolve_any_dispatch_table(monkeypatch, url, source, attr):
    monkeypatch.setattr(
        importers, attr, lambda u: [Track(id="z", artist="A", title="B")]
    )
    tracks, got_source = resolve_any(url)
    assert got_source == source
    assert len(tracks) == 1


# --- pomocnicze parsery czasu (czyste) --------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("PT5M56S", 356.0),
        ("PT1H2M3S", 3723.0),
        ("PT45S", 45.0),
        ("PT3M", 180.0),
        (None, None),
        ("", None),
        ("bzdura", None),
        ("PT", None),
    ],
)
def test_iso_duration_s(value, expected):
    assert _iso_duration_s(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("3:45", 225.0),
        ("1:02:03", 3723.0),
        ("0:59", 59.0),
        (None, None),
        ("", None),
        ("nie-czas", None),
        ("1:2", None),  # sekundy muszą mieć 2 cyfry
    ],
)
def test_clock_s(value, expected):
    assert _clock_s(value) == expected


# --- @network: jedna prawdziwa playlista YouTube ----------------------------


@pytest.mark.network
def test_resolve_any_real_youtube_playlist():
    url = "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj"
    try:
        tracks, source = resolve_any(url)
    except _NET_ERRORS as e:
        pytest.skip(f"brak sieci: {e}")
    except ImportError as e:
        if "błąd sieci" in str(e):
            pytest.skip(f"brak sieci: {e}")
        raise
    assert source == "youtube"
    assert len(tracks) >= 20
    for t in tracks:
        assert t.artist and t.title
        assert t.id.startswith("yt:")
    # duża część pozycji ma czas trwania z badge'a
    with_dur = [t for t in tracks if t.duration_s]
    assert len(with_dur) >= len(tracks) // 2
