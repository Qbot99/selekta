"""Radar nowych wydań i sondy doktora — bez sieci (nagrane odpowiedzi).

Regresje z przeglądu 11.10.2026:
- Bandcamp brał pierwszą podpowiedź wyszukiwarki, gdy nie było dokładnego
  trafienia → ABBA dostawała stronę amatora „abba”, Asia/Bon Jovi/Boney M.
  podróbki, Anastacia cudzy profil;
- pierwsze sprawdzenie zgłaszało cały katalog jako „nowości” (ABBA z 1997);
- `selekta radar` w terminalu oznaczał znaleziska jako widziane, ale nie
  zapisywał ich dla ekranu Radar;
- doktor korzystał z pamięci radaru, więc każde kolejne „Sprawdź teraz”
  dawało Beatport/Bandcamp „0 wydań — strona mogła się zmienić”.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from selekta import doktor, radar

# Odpowiedzi publicznego API podpowiedzi Bandcampu (autocomplete_elastic,
# filtr „b”) nagrane 11.10.2026 — pierwsze pozycje plus wszystkie o tej
# samej nazwie co szukany artysta.
NAGRANE = {
    "ABBA": [
        ("Abba Gargando", "https://abbagargando.bandcamp.com"),
        ("Abba Gabba", "https://abbagabba.bandcamp.com"),
        ("BLACK ABBA", "https://blackabba.bandcamp.com"),
        ("Joe Abba", "https://joeabba.bandcamp.com"),
        ("Tribute to ABBA", "https://tributetoabba.bandcamp.com"),
        ("abba", "https://abba.bandcamp.com"),           # amator z Vancouver
        ("Ichiko Aoba", "https://ichikoaoba.bandcamp.com"),
        ("ABBA", "https://abbalmao.bandcamp.com"),        # druga „ABBA” (Oklahoma)
    ],
    "Alt8": [
        ("Alt8", "https://alt8.bandcamp.com"),            # prawdziwy, Barcelona
        ("HAUS of ALTR", "https://hausofaltr.bandcamp.com"),
        ("ALT236", "https://alt236.bandcamp.com"),
        ("ALT", "https://altmusic8.bandcamp.com"),
    ],
    "Asia": [
        ("1asia", "https://1asia.bandcamp.com"),
        ("Planet Asia", "https://planet-asia.bandcamp.com"),
        ("Asia Minor", "https://asiaminor-ams.bandcamp.com"),
        ("Asia", "https://asia-noumeno.bandcamp.com"),
        ("ASIA", "https://asia-enregistrements.bandcamp.com"),
    ],
    "Bon Jovi": [
        ("Bon Jovi Bon VN", "https://bonjovibonvn.bandcamp.com"),
        ("Ciao Bon Jovi Jon Bon Jon Jovi Jon", "https://cbjjbjjj.bandcamp.com"),
        ("Bon Don Jovi", "https://bondonjovi.bandcamp.com"),
    ],
    "Boney M.": [
        ("boneyM", "https://boneym1.bandcamp.com"),
        ("Boner M", "https://bonerm.bandcamp.com"),
    ],
    "Anastacia": [
        ("nantzin anastacia lopez lopez", "https://nantzinanastacialopezlopez.bandcamp.com"),
    ],
    "Bklava": [
        ("Dálava", "https://dalavamusic.bandcamp.com"),
    ],
}


@pytest.fixture()
def nagrany_bandcamp(monkeypatch):
    """Strona wyszukiwania za ścianą bota (jak naprawdę), podpowiedzi z nagrań."""
    zapytania = []
    monkeypatch.setattr(radar, "_get", lambda url: None)

    def post(url, payload):
        zapytania.append(payload["search_text"])
        wyniki = [{"type": "b", "name": n, "item_url_root": u}
                  for n, u in NAGRANE.get(payload["search_text"], [])]
        return {"auto": {"results": wyniki}}

    monkeypatch.setattr(radar, "_post_json", post)
    return zapytania


class TestBandcampTylkoWlasciwyArtysta:
    @pytest.mark.parametrize("artysta", ["ABBA", "Asia", "Bon Jovi", "Boney M.",
                                         "Anastacia", "Bklava"])
    def test_cudza_albo_niejednoznaczna_strona_odrzucona(self, nagrany_bandcamp, artysta):
        assert radar._bandcamp_artist_page(artysta) is None

    def test_jednoznaczna_zgodnosc_przyjeta(self, nagrany_bandcamp):
        assert radar._bandcamp_artist_page("Alt8") == "https://alt8.bandcamp.com"

    def test_bez_strony_brak_wydan_i_brak_pobierania(self, nagrany_bandcamp, monkeypatch):
        pobrane = []
        monkeypatch.setattr(radar, "_get", lambda url: pobrane.append(url))
        assert radar.check_bandcamp("ABBA") == []
        assert not [u for u in pobrane if "/music" in u]

    def test_strona_html_bez_dokladnego_trafienia_nie_zgaduje(self, monkeypatch):
        html = """
        <li class="searchresult band"><div class="heading"><a href="x">Bon Jovi Bon VN</a></div>
        <div class="itemurl"><a href="https://bonjovibonvn.bandcamp.com?from=sr">x</a></div></li>
        """
        monkeypatch.setattr(radar, "_get", lambda url: html)
        monkeypatch.setattr(radar, "_post_json", lambda url, p: {"auto": {"results": []}})
        assert radar._bandcamp_artist_page("Bon Jovi") is None

    def test_normalizacja_nazwy(self):
        assert radar._norm_nazwa("Öwes") == radar._norm_nazwa("owes")
        assert radar._norm_nazwa("Dimitri Vegas & Like Mike") == \
            radar._norm_nazwa("dimitri vegas and like mike")
        assert radar._norm_nazwa("Boney M.") != radar._norm_nazwa("boneyM")


def _wyd(rid, data=None, zrodlo="beatport"):
    return {"id": f"{zrodlo}:{rid}", "title": f"T{rid}", "url": f"https://x/{rid}",
            "date": data, "source": zrodlo}


class TestPierwszeSprawdzenieNieZasypuje:
    def test_pierwsze_sprawdzenie_zglasza_tylko_swieze(self):
        swieza = (date.today() - timedelta(days=10)).isoformat()
        nowe = radar._register("ABBA", [_wyd(1, "1997-07-02"), _wyd(2, "2001-06-18"),
                                         _wyd(3, swieza)], "beatport")
        assert [n["id"] for n in nowe] == ["beatport:3"]
        assert len(radar._load_state()["ABBA"]["seen"]) == 3

    def test_bandcamp_bez_dat_przy_pierwszym_razie_tylko_zapamietuje(self):
        assert radar._register("Alt8", [_wyd(1, None, "bandcamp")], "bandcamp") == []
        nowe = radar._register("Alt8", [_wyd(1, None, "bandcamp"), _wyd(2, None, "bandcamp")],
                               "bandcamp")
        assert [n["id"] for n in nowe] == ["bandcamp:2"]

    def test_stare_wydanie_wyplywajace_pozniej_to_nie_nowosc(self):
        radar._register("X", [_wyd(1, "2025-01-01")], "beatport")
        swieza = date.today().isoformat()
        nowe = radar._register("X", [_wyd(1, "2025-01-01"), _wyd(2, "2003-01-01"),
                                     _wyd(3, swieza)], "beatport")
        assert [n["id"] for n in nowe] == ["beatport:3"]

    def test_pierwszy_raz_liczony_osobno_dla_sklepu(self):
        radar._register("Y", [_wyd(1, "2020-01-01")], "beatport")
        # Bandcamp sprawdzany pierwszy raz — zapamiętuje, nie zgłasza
        assert radar._register("Y", [_wyd(9, None, "bandcamp")], "bandcamp") == []

    def test_pamiec_sprzed_zmiany_nie_zasypuje(self, tmp_path):
        with open(radar.STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"Z": {"last_check": "2026-01-01", "seen": ["beatport:1"]}}, fh)
        nowe = radar._register("Z", [_wyd(1, "2020-01-01"), _wyd(2, None)], "beatport")
        assert [n["id"] for n in nowe] == ["beatport:2"]

    def test_awaria_sklepu_nie_zasiewa(self):
        radar._register("W", [], "bandcamp")
        assert "bandcamp" not in radar._load_state()["W"]["zrodla"]


class TestTerminalZapisujeDlaEkranu:
    def test_check_all_zapisuje_wyniki_dla_dashboardu(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(radar, "artists_from_library", lambda f: {"Alfa", "Beta"})
        monkeypatch.setattr(radar, "check_bandcamp", lambda a: [])
        monkeypatch.setattr(radar, "check_beatport", lambda a: [
            {"id": f"bp:{a}", "title": f"{a} EP", "url": f"https://bp/{a}",
             "date": date.today().isoformat(), "source": "beatport"}])
        news = radar.check_all(str(tmp_path), notify_new=False)
        assert set(news) == {"Alfa", "Beta"}
        w = radar.wyniki()
        assert {it["artist"] for it in w["items"]} == {"Alfa", "Beta"}
        assert w["checked_at"] and w["last"]["new"] == 2


def _strona_beatport(artysta: str) -> str:
    dane = {"props": {"pageProps": {"dehydratedState": {"queries": [{"state": {"data": {
        "data": [{"release_id": i, "release_name": f"Wydanie {i}",
                  "release_date": "2024-05-0%d" % i,
                  "artists": [{"artist_name": artysta}]} for i in range(1, 4)]}}}]}}}}
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(dane) + "</script></html>")


class TestDoktorNiezaleznyOdPamieciRadaru:
    def test_dwa_sprawdzenia_z_rzedu_oba_ok(self, monkeypatch):
        monkeypatch.setattr(radar, "_get", lambda url: _strona_beatport(doktor.BEATPORT_ARTYSTA))
        pierwsza, druga = doktor._beatport(), doktor._beatport()
        assert pierwsza.ok and druga.ok, druga.opis
        assert "3 wydań" in druga.opis

    def test_doktor_nie_dopisuje_artystow_do_radaru(self, monkeypatch):
        monkeypatch.setattr(radar, "_get", lambda url: _strona_beatport(doktor.BEATPORT_ARTYSTA))
        doktor._beatport()
        assert radar._load_state() == {}

    def test_bandcamp_sonda_dwa_razy(self, monkeypatch):
        strona_muzyki = ('<li><a href="/album/syro"><p class="title">Syro</p></a></li>'
                         '<li><a href="/track/xmas-evet10"><p class="title">XMAS</p></a></li>')
        monkeypatch.setattr(radar, "_bandcamp_artist_page",
                            lambda a: "https://aphextwin.bandcamp.com")
        monkeypatch.setattr(radar, "_get", lambda url: strona_muzyki)
        assert doktor._bandcamp().ok and doktor._bandcamp().ok
        assert radar._load_state() == {}


class TestSondaSlskd:
    def _status(self, monkeypatch, **pola):
        from selekta import slskd_ctl
        monkeypatch.setattr(slskd_ctl, "status", lambda: slskd_ctl.Status(**pola))

    def test_dzialajacy_spoza_znanych_folderow_to_nie_brak_instalacji(self, monkeypatch):
        self._status(monkeypatch, binary="", running=False, reachable=True,
                     authorized=True, logged_in=True)
        assert doktor._slskd().ok

    def test_zly_klucz_nazwany_po_imieniu(self, monkeypatch):
        self._status(monkeypatch, binary="/x/slskd", running=True, reachable=True,
                     authorized=False)
        s = doktor._slskd()
        assert not s.ok and "klucz" in s.opis

    def test_brak_instalacji(self, monkeypatch):
        self._status(monkeypatch, binary="", running=False, reachable=False)
        assert "nie zainstalowany" in doktor._slskd().opis
