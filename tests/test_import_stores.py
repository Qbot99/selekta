"""Testy selekta.stores — deep-linki wyszukiwania w sklepach (czyste, bez sieci)."""
from __future__ import annotations

from selekta.spotify import Track
from selekta.stores import bandcamp_search, beatport_search, buy_links


def _t(artist: str, title: str) -> Track:
    return Track(id="x", artist=artist, title=title)


def test_beatport_search_encodes_spaces_and_ampersand():
    url = beatport_search(_t("A & B", "C D"))
    assert url == "https://www.beatport.com/search?q=A+%26+B+C+D"


def test_bandcamp_search_encodes_and_keeps_item_type():
    url = bandcamp_search(_t("A & B", "C D"))
    assert url == "https://bandcamp.com/search?q=A+%26+B+C+D&item_type=t"


def test_beatport_search_simple_query():
    url = beatport_search(_t("Odymel", "Gucci"))
    assert url == "https://www.beatport.com/search?q=Odymel+Gucci"


def test_unicode_artist_is_percent_encoded_utf8():
    url = beatport_search(_t("Åmrtüm", "dash"))
    assert url == "https://www.beatport.com/search?q=%C3%85mrt%C3%BCm+dash"
    url2 = bandcamp_search(_t("Åmrtüm", "dash"))
    assert url2 == "https://bandcamp.com/search?q=%C3%85mrt%C3%BCm+dash&item_type=t"


def test_special_characters_encoded():
    # ?, =, # i / w tytule nie mogą rozbić query stringa
    url = beatport_search(_t("A?B", "C=D#E/F"))
    assert url == "https://www.beatport.com/search?q=A%3FB+C%3DD%23E%2FF"


def test_buy_links_keys_and_values():
    t = _t("Hardwell, Maddix", "ACID")
    links = buy_links(t)
    assert set(links.keys()) == {"beatport", "qobuz", "juno", "bandcamp"}
    assert links["beatport"] == beatport_search(t)
    assert links["bandcamp"] == bandcamp_search(t)
    assert links["beatport"].startswith("https://www.beatport.com/search?q=")
    assert links["bandcamp"].startswith("https://bandcamp.com/search?q=")
    assert "Hardwell%2C+Maddix+ACID" == links["beatport"].split("q=")[1]


def test_empty_track_produces_query_with_single_plus():
    # query pustego Tracka to " " (artist + spacja + title) → zakodowane "+"
    url = beatport_search(_t("", ""))
    assert url == "https://www.beatport.com/search?q=+"


def test_bootleg_dostaje_trop_do_producenta():
    """Bootlegów nie ma w sklepach — udawanie, że są, marnuje czas DJ-a."""
    from selekta.stores import is_unofficial, gdzie_szukac
    t = _t("Klaas", "Ok Without You (Mr.Cheez Bootleg)")
    assert is_unofficial(t)
    assert "soundcloud" in buy_links(t)
    assert "bootleg" in gdzie_szukac(t)


def test_zwykly_utwor_bez_tropu_do_soundcloud():
    t = _t("Cascada", "What Hurts The Most")
    from selekta.stores import is_unofficial
    assert not is_unofficial(t)
    assert "soundcloud" not in buy_links(t)


def test_radio_edit_jest_oficjalny():
    """Regresja z 1.09.2026: słowo „edit" na liście nieoficjalnych wysyłało
    oficjalny Radio Edit na SoundCloud z komunikatem „nie ma go w sklepach"."""
    from selekta import stores
    assert stores.is_unofficial(_t("Cascada",
                                   "Everytime We Touch (Radio Edit)")) is False
    assert stores.is_unofficial(_t("Ktoś", "Cudzy Utwór (DJ X Edit)")) is True
    assert stores.is_unofficial(_t("Ktoś", "Utwór (Bootleg)")) is True
