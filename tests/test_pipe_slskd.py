"""Testy selekta.slskd_client — czysto, bez działającego slskd.

Ranking wyników (lossless > zgodny czas > wolny slot > bitrate > rozmiar),
konstrukcja klienta (env/argumenty) i szybkie available()==False przy
braku demona.
"""
from __future__ import annotations

import time

import pytest

from selekta.slskd_client import SearchHit, SlskdClient


def _hit(name, lossless, free, length, bitrate=None, size=10_000_000, user=None):
    return SearchHit(username=user or name, filename=name,
                     size=size, bitrate=bitrate, length_s=length,
                     is_lossless=lossless, free_slot=free)


# ---------------------------------------------------------------- rank

def test_rank_full_ordering():
    """Przy równej trafności nazwy: zgodny czas > bezstratność > wolny slot
    > bitrate. Czas jest wyżej niż format, bo dowodzi TOŻSAMOŚCI utworu."""
    best = _hit("a.flac", lossless=True, free=True, length=360)
    busy = _hit("b.flac", lossless=True, free=False, length=360)
    mp3_320 = _hit("d.mp3", lossless=False, free=True, length=360, bitrate=320)
    mp3_128 = _hit("e.mp3", lossless=False, free=True, length=360, bitrate=128)
    wrong_dur = _hit("c.flac", lossless=True, free=True, length=300)

    shuffled = [mp3_128, wrong_dur, best, mp3_320, busy]
    ranked = SlskdClient().rank(shuffled, want_duration_s=360)
    assert [h.filename for h in ranked] == [
        "a.flac", "b.flac", "d.mp3", "e.mp3", "c.flac"
    ]


def test_rank_duration_beats_lossless():
    """FLAC o złym czasie przegrywa z MP3 o zgodnym — bezstratny plik
    INNEGO utworu jest gorszy niż stratny plik właściwego."""
    flac_wrong = _hit("x.flac", lossless=True, free=True, length=200)
    mp3_right = _hit("x.mp3", lossless=False, free=True, length=360, bitrate=320)
    ranked = SlskdClient().rank([flac_wrong, mp3_right], want_duration_s=360)
    assert ranked[0] is mp3_right


def test_rank_lossless_wins_when_duration_ties():
    """Gdy czas jednakowo pasuje, bezstratny wygrywa."""
    flac = _hit("x.flac", lossless=True, free=False, length=360)
    mp3 = _hit("x.mp3", lossless=False, free=True, length=360, bitrate=320)
    assert SlskdClient().rank([mp3, flac], want_duration_s=360)[0] is flac


def test_rank_relevance_outranks_everything():
    """Nazwa pasująca do artysty i tytułu bije format i czas — inaczej
    trafiamy losowy plik, który przypadkiem ma dobrą długość."""
    junk = _hit("VA/set_live_2019.flac", lossless=True, free=True, length=360)
    real = _hit("Nicolas Julian/like this.mp3", lossless=False, free=False,
                length=360, bitrate=320)
    ranked = SlskdClient().rank([junk, real], want_duration_s=360,
                                artist="Nicolas Julian, STORM", title="Like This")
    assert ranked[0] is real


def test_rank_duration_tolerance_boundary():
    """Tolerancja czasu to +/-3 s: 363 s pasuje do 360, 364 już nie."""
    just_in = _hit("in.flac", lossless=True, free=True, length=363)
    just_out = _hit("out.flac", lossless=True, free=True, length=364)
    ranked = SlskdClient().rank([just_out, just_in], want_duration_s=360)
    assert [h.filename for h in ranked] == ["in.flac", "out.flac"]


def test_rank_without_wanted_duration_ignores_length():
    short = _hit("s.flac", lossless=True, free=True, length=100, size=5)
    long = _hit("l.flac", lossless=True, free=True, length=400, size=5)
    ranked = SlskdClient().rank([short, long], want_duration_s=None)
    # bez zadanego czasu żaden nie dostaje bonusu — rozstrzyga reszta klucza
    assert {h.filename for h in ranked[:2]} == {"s.flac", "l.flac"}


def test_rank_none_bitrate_treated_as_zero():
    with_rate = _hit("r.mp3", lossless=False, free=True, length=None, bitrate=192)
    no_rate = _hit("n.mp3", lossless=False, free=True, length=None, bitrate=None)
    ranked = SlskdClient().rank([no_rate, with_rate], want_duration_s=None)
    assert ranked[0] is with_rate


def test_rank_empty_list():
    assert SlskdClient().rank([], want_duration_s=300) == []


# ---------------------------------------------------------------- klient

def test_client_strips_trailing_slash_and_sets_key():
    c = SlskdClient(base_url="http://example.invalid:5030/", api_key="sekret")
    assert c.base == "http://example.invalid:5030"
    assert c.headers == {"X-API-Key": "sekret"}


def test_client_no_key_no_header(monkeypatch):
    monkeypatch.delenv("SELEKTA_SLSKD_API_KEY", raising=False)
    c = SlskdClient(base_url="http://example.invalid:5030")
    assert c.headers == {}


def test_client_reads_env(monkeypatch):
    monkeypatch.setenv("SELEKTA_SLSKD_URL", "http://env.invalid:1234/")
    monkeypatch.setenv("SELEKTA_SLSKD_API_KEY", "z-env")
    c = SlskdClient()
    assert c.base == "http://env.invalid:1234"
    assert c.headers == {"X-API-Key": "z-env"}


def test_available_false_and_fast_when_no_slskd():
    """Zamknięty port lokalny: connection refused => False w < 5 s."""
    c = SlskdClient(base_url="http://127.0.0.1:1")
    t0 = time.monotonic()
    assert c.available() is False
    assert time.monotonic() - t0 < 5.0


def test_searchhit_fields():
    h = SearchHit(username="u", filename="żółć.flac", size=1, bitrate=None,
                  length_s=None, is_lossless=True, free_slot=False)
    assert (h.username, h.filename, h.is_lossless) == ("u", "żółć.flac", True)


# ------------------------------------------------- strategia wyszukiwania

from selekta.slskd_client import core_title, primary_artist, relevance, _tokens


class TestPrimaryArtist:
    """Soulseek nie zna pełnych składów — szukamy po głównym wykonawcy."""

    def test_splits_on_comma(self):
        assert primary_artist("Nicolas Julian, STORM, AENJAY") == "Nicolas Julian"

    def test_splits_on_ampersand(self):
        assert primary_artist("Dimitri Vegas & Like Mike") == "Dimitri Vegas"

    def test_splits_on_feat(self):
        assert primary_artist("The Rocketman feat. SHVDZ") == "The Rocketman"
        assert primary_artist("A ft. B") == "A"

    def test_single_artist_unchanged(self):
        assert primary_artist("Massano") == "Massano"

    def test_empty(self):
        assert primary_artist("") == ""


class TestCoreTitle:
    def test_strips_parenthetical(self):
        assert core_title("Call Me (Extended Mix)") == "Call Me"

    def test_strips_brackets(self):
        assert core_title("Gucci [VIP Edit]") == "Gucci"

    def test_plain_title_unchanged(self):
        assert core_title("Gucci") == "Gucci"

    def test_never_returns_empty(self):
        assert core_title("(Extended Mix)") == "(Extended Mix)"


class TestRelevance:
    def test_artist_in_folder_file_without_artist(self):
        """Realny przypadek: artysta w nazwie folderu, plik to '03 - tytul'."""
        path = r"user\Deep House\Nicolas Julian\03 - like this.flac"
        assert relevance(path, _tokens("Nicolas Julian"), _tokens("Like This")) == 1.0

    def test_unrelated_file_scores_zero(self):
        assert relevance(r"user\VA\set_live_2019.flac",
                         _tokens("Nicolas Julian"), _tokens("Like This")) == 0.0

    def test_partial_match_between(self):
        score = relevance("like this.flac", _tokens("Nicolas Julian"),
                          _tokens("Like This"))
        assert 0.0 < score < 1.0

    def test_empty_path(self):
        assert relevance("", _tokens("A"), _tokens("B")) == 0.0


class TestPlausible:
    """Odsiewanie godzinnych setów i urwanych próbek."""

    def test_rejects_dj_set_by_name(self):
        from selekta.slskd_client import _plausible
        assert not _plausible(_hit("Essential Mix 2019.flac", True, True, 360), 360)

    def test_rejects_far_too_long(self):
        from selekta.slskd_client import _plausible
        assert not _plausible(_hit("x.flac", True, True, 3600), 360)

    def test_rejects_snippet(self):
        from selekta.slskd_client import _plausible
        assert not _plausible(_hit("x.flac", True, True, 60), 360)

    def test_accepts_matching_length(self):
        from selekta.slskd_client import _plausible
        assert _plausible(_hit("x.flac", True, True, 358), 360)

    def test_accepts_unknown_length(self):
        from selekta.slskd_client import _plausible
        assert _plausible(_hit("x.flac", True, True, None), 360)


class TestSearchTrackCascade:
    """Drabina scalająca: artysta+rdzeń -> artysta+pełny tytuł -> sam tytuł.

    Kluczowa różnica wobec starej kaskady: wyniki kolejnych szczebli są
    SCALANE, a schodzimy z drabiny dopiero po dowodzie tożsamości
    (pełny tytuł w ścieżce + czas ±3 s), a nie gdy cokolwiek się znalazło.
    """

    def _client_with(self, results_by_query):
        c = SlskdClient()
        used = []

        def fake_search(query, timeout_s=15):
            used.append(query)
            return results_by_query.get(query, [])

        c.search = fake_search
        return c, used

    def test_first_rung_is_artist_plus_core_title(self):
        good = _hit(r"Nicolas Julian\03 - like this.flac", True, True, 228)
        c, used = self._client_with({"Nicolas Julian Like This": [good]})
        out = c.search_track("Nicolas Julian, STORM, AENJAY", "Like This", 228)
        assert out and out[0] is good
        assert used[0] == "Nicolas Julian Like This"
        assert len(used) == 1          # dowód tożsamości -> koniec po 1 zapytaniu

    def test_merges_across_rungs(self):
        """Słaby wynik z 1. szczebla NIE blokuje lepszego z kolejnego."""
        weak = _hit(r"VA\like this (radio edit).mp3", False, True, 150, bitrate=128)
        good = _hit(r"Nicolas Julian\like this.flac", True, True, 228)
        c, used = self._client_with({
            "Nicolas Julian Like This": [weak],
            "Like This": [good],
        })
        out = c.search_track("Nicolas Julian", "Like This", 228)
        assert out[0] is good          # właściwy czas wygrywa
        assert weak in out             # a słabszy nie ginie — jest niżej
        assert len(used) >= 2          # zeszliśmy niżej po drabinie

    def test_falls_back_to_title_only(self):
        good = _hit(r"VA\like this (original mix).flac", True, True, 228)
        c, used = self._client_with({"Like This": [good]})
        out = c.search_track("Nieznany Ktos", "Like This", 228)
        assert out and out[0] is good
        assert used[-1] == "Like This"

    def test_returns_empty_when_nothing_matches(self):
        junk = _hit(r"VA\zupelnie co innego.flac", True, True, 228)
        c, _ = self._client_with({"A B": [junk], "B": [junk]})
        assert c.search_track("A", "B", 228) == []

    def test_filters_out_dj_mix(self):
        mix = _hit(r"Nicolas Julian\dj set 2019.flac", True, True, 3600)
        c, _ = self._client_with({"Nicolas Julian Like This": [mix]})
        assert c.search_track("Nicolas Julian", "Like This", 228) == []

    def test_duplicate_query_text_not_repeated(self):
        """Gdy tytuł nie ma nawiasów, szczeble 1 i 2 są identyczne —
        drugiego nie wysyłamy, o ile pierwszy coś zwrócił."""
        good = _hit(r"Massano\the lights.flac", True, True, 329)
        c, used = self._client_with({"Massano The Lights": [good]})
        c.search_track("Massano", "The Lights", 329)
        assert used.count("Massano The Lights") == 1


class TestBuildLadder:
    def test_rungs_go_from_narrow_to_broad(self):
        from selekta.slskd_client import build_ladder
        rungs = build_ladder("A, B", "Tytul (Extended Mix)")
        assert rungs == ["A Tytul", "A Tytul (Extended Mix)", "Tytul", "A"]

    def test_deduplicates_identical_rungs(self):
        from selekta.slskd_client import build_ladder
        rungs = build_ladder("A", "Tytul")
        assert rungs == ["A Tytul", "Tytul", "A"]     # bez powtórzeń

    def test_last_rung_is_artist_alone(self):
        """Szeroka sieć na koniec — metoda, której DJ używa ręcznie w
        Nicotine+: wyszukać artystę i dobrać tytuł z listy wyników.
        Bywa jedyną, która trafia, bo Soulseek dopasowuje dosłownie."""
        from selekta.slskd_client import build_ladder
        assert build_ladder("Cascada", "What Hurts The Most")[-1] == "Cascada"


class TestOdbiorWynikow:
    """slskd oddaje wyniki dopiero po zakończeniu wyszukiwania.

    Zmierzone na żywo: przy `searchTimeout` 8 s stan „Completed" pojawia
    się dopiero po ok. 30 s, a `/responses` w trakcie zwraca PUSTĄ listę.
    Wcześniejsza wersja czytała po `timeout_s + 10` i dostawała zero
    wyników w 5 na 6 prób — przy zapytaniach, które realnie zwracały
    ponad tysiąc plików.
    """

    def _client(self, monkeypatch, stany, odpowiedzi):
        import selekta.slskd_client as sc
        from selekta.slskd_client import SlskdClient
        kolejka = list(stany)
        wywolania = {"responses": 0}

        class Odp:
            def __init__(self, data): self._d = data
            def json(self): return self._d
            def raise_for_status(self): pass
            status_code = 200

        def fake_post(url, **kw):
            return Odp({"id": "sid-1"})

        def fake_get(url, **kw):
            if url.endswith("/responses"):
                wywolania["responses"] += 1
                return Odp(odpowiedzi)
            return Odp({"state": kolejka.pop(0) if kolejka else "Completed"})

        monkeypatch.setattr(sc.requests, "post", fake_post)
        monkeypatch.setattr(sc.requests, "get", fake_get)
        monkeypatch.setattr(sc.requests, "delete", lambda *a, **k: Odp({}))
        monkeypatch.setattr(sc.time, "sleep", lambda s: None)
        c = SlskdClient(base_url="http://x", api_key="k")
        monkeypatch.setattr(c, "_pace", lambda: None)
        return c, wywolania

    def test_czeka_az_wyszukiwanie_sie_zakonczy(self, monkeypatch):
        odp = [{"username": "u", "hasFreeUploadSlot": True,
                "files": [{"filename": "a\\b.flac", "size": 1}]}]
        c, licznik = self._client(
            monkeypatch, ["InProgress"] * 20 + ["Completed, TimedOut"], odp)
        hits = c.search("cokolwiek")
        assert len(hits) == 1                      # nie czytamy w trakcie
        assert licznik["responses"] == 1

    def test_akceptuje_kazdy_stan_koncowy(self, monkeypatch):
        """slskd kończy jako „Completed, TimedOut" albo
        „Completed, ResponseLimitReached" — oba są zakończeniem."""
        for stan in ("Completed, TimedOut", "Completed, ResponseLimitReached",
                     "Completed, Cancelled"):
            c, _ = self._client(monkeypatch, [stan], [])
            assert c.search("x") == []

    def test_nie_wisi_w_nieskonczonosc(self, monkeypatch):
        """Gdy stan nigdy nie osiągnie „Completed", i tak wychodzimy."""
        import selekta.slskd_client as sc
        zegar = {"t": 0.0}
        monkeypatch.setattr(sc.time, "monotonic", lambda: zegar["t"], raising=False)
        c, _ = self._client(monkeypatch, ["InProgress"] * 10_000, [])
        real_time = sc.time.time
        monkeypatch.setattr(sc.time, "time", lambda: (zegar.update(t=zegar["t"] + 5)
                                                      or zegar["t"]))
        assert c.search("x") == []
        monkeypatch.setattr(sc.time, "time", real_time)


class TestBezpiecznikSieci:
    """Seria pustych odpowiedzi = urwane połączenie, nie brak utworu.

    Bez tego masowa operacja sama się nakręcała: każdy nieudany utwór
    wysyłał do 12 zapytań (4 szczeble × 3 próby), co dobijało połączenie
    i sprawiało, że kolejne utwory też szły pełną drabiną. Skanowanie
    playlisty wyleciało w ten sposób po trzech utworach — 21 kolejnych
    dostało 502.
    """

    def test_liczy_pustki_z_rzedu(self):
        from selekta.slskd_client import SlskdClient, EMPTY_STREAK_LIMIT
        c = SlskdClient()
        for _ in range(EMPTY_STREAK_LIMIT):
            assert not c.network_down()
            c._note_result([])
        assert c.network_down()

    def test_jedno_trafienie_kasuje_licznik(self):
        from selekta.slskd_client import SlskdClient
        c = SlskdClient()
        for _ in range(9):
            c._note_result([])
        assert c.network_down()
        c._note_result(["cokolwiek"])
        assert not c.network_down()

    def test_drabina_nie_eskaluje_w_martwa_siec(self, monkeypatch):
        """Po serii pustek nie próbujemy kolejnych szczebli."""
        from selekta.slskd_client import SlskdClient, SoulseekOffline
        c = SlskdClient()
        zapytania = []

        def pusto(query, timeout_s=8):
            zapytania.append(query)
            c._note_result([])
            return []

        monkeypatch.setattr(c, "search", pusto)
        monkeypatch.setattr(c, "logged_in", lambda: False)
        with pytest.raises(SoulseekOffline):
            c.search_track("Jakis Artysta", "Jakis Tytul", 200)
        # bez bezpiecznika byłoby 12 zapytań (4 szczeble × 3 próby)
        assert len(zapytania) <= 6, zapytania


class TestTrafnoscTytulu:
    """Tytuł liczymy z nazwy pliku, nie z całej ścieżki."""

    def _cechy(self, nazwa, artysta, tytul):
        from selekta.slskd_client import _hit_features, _tokens, primary_artist, SearchHit
        h = SearchHit("u", nazwa, 1, None, 200, True, True)
        return _hit_features(h, 1, 1, 200,
                             _tokens(primary_artist(artysta)), _tokens(tytul))

    def test_nazwa_albumu_nie_udaje_tytulu(self):
        """Szukając „Captain Jack" nie chcemy „Sir Yes Sir" z tej samej płyty."""
        zly = self._cechy("Captain Jack - The Mission/02 - Sir Yes Sir.flac",
                          "Captain Jack", "Captain Jack")
        dobry = self._cechy("Captain Jack - The Mission/03 - Captain Jack.flac",
                            "Captain Jack", "Captain Jack")
        assert dobry["tcov"] > zly["tcov"]
        assert dobry["tcov"] == 1.0

    def test_tylko_wlasciwy_plik_dowodzi_tozsamosci(self):
        from selekta.slskd_client import _identity_proven
        zly = self._cechy("Captain Jack - The Mission/02 - Sir Yes Sir.flac",
                          "Captain Jack", "Captain Jack")
        assert not _identity_proven(zly)

    def test_plik_nazwany_numerem_nadal_znajdowalny(self):
        """Tytuł bywa tylko w nazwie folderu — taki plik ma się liczyć,
        ale słabiej, żeby nigdy nie zakończył wyszukiwania przedwcześnie."""
        from selekta.slskd_client import _identity_proven
        f = self._cechy("Odymel - Gucci/01.flac", "Odymel", "Gucci")
        assert 0 < f["tcov"] < 1.0
        assert not _identity_proven(f)

    def test_describe_tez_liczy_z_nazwy_pliku(self):
        from selekta.slskd_client import SlskdClient, SearchHit
        c = SlskdClient()
        h = SearchHit("u", "Captain Jack - The Mission/02 - Sir Yes Sir.flac",
                      1, None, 200, True, True)
        d = c.describe(h, "Captain Jack", "Captain Jack", 200)
        assert d["title_match"] == 0.0
        assert d["artist_match"] == 1.0      # artysta wolno z całej ścieżki


def test_jakosc_wygrywa_z_wolnym_slotem():
    """320 kbps z zajętym slotem > 128 kbps z wolnym.

    Regresja z 1.09.2026: „free" stało w _RANK_ORDER przed „br", więc dla
    MP3 popularna 128-tka z wolnym slotem ogrywała 320-tkę z kolejką.
    Wolny slot przyspiesza pobranie, ale nie ratuje jakości — dokładnie
    ta pomyłka zapełniła kiedyś bibliotekę 128-tkami.
    """
    c = SlskdClient(base_url="http://localhost:9", api_key="x")
    szybkie_128 = [SearchHit(f"u{i}", "Artist - Tytul X.mp3", 4_000_000,
                             128, 200, False, True) for i in range(5)]
    wolne_320 = SearchHit("u320", "Artist - Tytul X.mp3", 9_600_000,
                          320, 200, False, False)
    ranked = c.rank(szybkie_128 + [wolne_320], want_duration_s=200,
                    artist="Artist", title="Tytul X")
    assert ranked[0].bitrate == 320, (
        f"wygrał {ranked[0].bitrate} kbps (free_slot="
        f"{ranked[0].free_slot}) — jakość ma stać przed wolnym slotem")
