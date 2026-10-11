"""Testy selekta.wishlist i selekta.radar — stan użytkownika (izolowany
automatycznie przez conftest), łowca braków i radar nowości.

Bez sieci: check() dostaje sztucznego klienta, radar testowany przez
_register/_load_state oraz artists_from_library na kopii biblioteki.
"""
from __future__ import annotations

import os

import pytest
import requests

from selekta import radar, wishlist
from selekta.slskd_client import SearchHit, SlskdClient


# ---------------------------------------------------------------- wishlist: stan

def test_items_fresh_state_empty():
    assert wishlist.items() == []
    assert not os.path.exists(wishlist.STATE_PATH)  # brak pliku != crash


def test_add_returns_full_entry():
    e = wishlist.add("  Odymel ", " Gucci  ", duration_s=213.5)
    assert len(e["id"]) == 8 and all(c in "0123456789abcdef" for c in e["id"])
    assert e["artist"] == "Odymel" and e["title"] == "Gucci"  # przycięte spacje
    assert e["duration_s"] == 213.5
    assert e["found"] is False
    assert e["added_at"][:2] == "20"  # ISO datetime
    assert wishlist.items() == [e]


def test_add_duplicate_appends_second_entry():
    """Faktyczne zachowanie: duplikat (ten sam artysta/tytuł) NIE jest
    scalany — powstaje drugi wpis z własnym id."""
    a = wishlist.add("Odymel", "Gucci")
    b = wishlist.add("Odymel", "Gucci")
    assert a["id"] != b["id"]
    entries = wishlist.items()
    assert len(entries) == 2
    assert [e["artist"] for e in entries] == ["Odymel", "Odymel"]


def test_add_unicode_and_persistence():
    e = wishlist.add("åmrtüm", "Zażółć gęślą jaźń")
    assert wishlist.items()[0]["title"] == "Zażółć gęślą jaźń"
    assert wishlist.remove(e["id"])["artist"] == "åmrtüm"


def test_remove_by_id():
    a = wishlist.add("A", "1")
    b = wishlist.add("B", "2")
    removed = wishlist.remove(a["id"])
    assert removed == a
    assert wishlist.items() == [b]


def test_remove_by_index():
    wishlist.add("A", "1")
    b = wishlist.add("B", "2")
    removed = wishlist.remove(0)
    assert removed["artist"] == "A"
    assert wishlist.items() == [b]


def test_remove_by_negative_index():
    a = wishlist.add("A", "1")
    wishlist.add("B", "2")
    assert wishlist.remove(-1)["artist"] == "B"
    assert wishlist.items() == [a]


def test_remove_by_numeric_string_falls_back_to_index():
    wishlist.add("A", "1")
    assert wishlist.remove("0")["artist"] == "A"
    assert wishlist.items() == []


def test_remove_nonexistent_returns_none():
    assert wishlist.remove("deadbeef") is None      # puste
    wishlist.add("A", "1")
    assert wishlist.remove("nie-ma-takiego") is None
    assert wishlist.remove(5) is None               # poza zakresem
    assert len(wishlist.items()) == 1               # nic nie zniknęło


# ---------------------------------------------------------------- wishlist: check

class _StubClient:
    """Udaje SlskdClient: search zwraca przygotowane wyniki, rank prawdziwy."""

    def __init__(self, hits):
        self._hits = hits
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return list(self._hits)

    def rank(self, hits, want_duration_s):
        return SlskdClient().rank(hits, want_duration_s)


class _DeadClient:
    def search(self, query):
        raise requests.ConnectionError("slskd padł")

    def rank(self, hits, want):  # pragma: no cover — nieosiągalne
        return hits


def test_check_marks_found_and_records_best_hit():
    wishlist.add("Odymel", "Gucci", duration_s=213)
    flac = SearchHit("userA", "Odymel - Gucci.flac", 30_000_000, None, 213, True, True)
    mp3 = SearchHit("userB", "Odymel - Gucci.mp3", 8_000_000, 320, 213, False, True)
    client = _StubClient([mp3, flac])

    finds, nieudane = wishlist.check(client)
    assert len(finds) == 1 and nieudane == 0
    assert client.queries == ["Odymel Gucci"]
    entry = wishlist.items()[0]
    assert entry["found"] is True
    assert entry["found_hit"]["username"] == "userA"       # wygrał lossless
    assert entry["found_hit"]["is_lossless"] is True
    assert "found_at" in entry

    # drugi przebieg: wpis już znaleziony — nie szukamy ponownie
    assert wishlist.check(client) == ([], 0)
    assert client.queries == ["Odymel Gucci"]


def test_check_network_error_is_skipped_not_fatal():
    wishlist.add("A", "1")
    finds, nieudane = wishlist.check(_DeadClient())
    assert finds == [] and nieudane == 1, (
        "błąd sieci ma być POLICZONY — zlewanie go z 'nic nowego' "
        "ukrywało martwego slskd miesiącami")
    assert wishlist.items()[0]["found"] is False


def test_check_no_hits_leaves_entry_pending():
    wishlist.add("A", "1")
    assert wishlist.check(_StubClient([])) == ([], 0)
    assert wishlist.items()[0]["found"] is False


# ---------------------------------------------------------------- notify

def test_notify_does_not_raise_and_returns_bool():
    ok = wishlist.notify('cudzysłów " backslash \\ zażółć', title='sel"ekta')
    assert isinstance(ok, bool)


def test_notify_missing_osascript_returns_false(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent-bin")
    assert wishlist.notify("x") is False


# ---------------------------------------------------------------- radar: stan

def _rel(rid, title="T"):
    return {"id": rid, "title": title, "url": f"https://x/{rid}", "source": "test"}


def test_radar_load_state_fresh_empty():
    assert radar._load_state() == {}


def test_radar_register_first_check_reports_only_fresh_releases():
    """Pierwsze sprawdzenie zapamiętuje katalog; nowością jest tylko świeże wydanie.

    Wcześniej cały katalog (ABBA z 1997) lądował w „nowościach”.
    """
    from datetime import datetime, timedelta
    swieze = {**_rel("a"), "date": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")}
    stare = {**_rel("b"), "date": "1997-07-02"}
    bez_daty = _rel("c")
    new = radar._register("Artist", [swieze, stare, bez_daty])
    assert [f["id"] for f in new] == ["a"]
    state = radar._load_state()
    assert state["Artist"]["seen"] == ["a", "b", "c"]
    assert state["Artist"]["last_check"] is not None


def test_radar_register_second_same_returns_empty():
    found = [_rel("a"), _rel("b")]
    radar._register("Artist", found)
    assert radar._register("Artist", found) == []


def test_radar_register_new_id_returns_only_new():
    radar._register("Artist", [_rel("a")])
    new = radar._register("Artist", [_rel("a"), _rel("c")])
    assert [f["id"] for f in new] == ["c"]
    assert radar._load_state()["Artist"]["seen"] == ["a", "c"]


def test_radar_register_separate_artists_independent():
    radar._register("One", [_rel("a")])
    radar._register("Two", [])                 # pierwsze sprawdzenie Two
    new = radar._register("Two", [_rel("a")])  # ten sam id, inny artysta
    assert [f["id"] for f in new] == ["a"]


def test_radar_register_empty_found_seeds_artist():
    assert radar._register("Nowy", []) == []
    assert radar._load_state()["Nowy"]["seen"] == []


# ---------------------------------------------------------------- radar: biblioteka

def test_artists_from_library_lib_copy(lib_copy):
    artists = radar.artists_from_library(lib_copy)
    assert "Odymel" in artists
    # wieloartystowy tag "mischluft, Sachsentrance" rozbity po przecinku
    assert "mischluft" in artists
    assert "Sachsentrance" in artists
    assert "mischluft, Sachsentrance" not in artists


def test_artists_from_library_empty_dir(tmp_path):
    assert radar.artists_from_library(str(tmp_path)) == set()


def test_artists_from_library_nonexistent_dir():
    assert radar.artists_from_library("/nie/ma/takiego/katalogu") == set()


def test_artists_from_library_ignores_non_audio(tmp_path):
    (tmp_path / "notatka.txt").write_text("Artist - Tytuł")
    assert radar.artists_from_library(str(tmp_path)) == set()
