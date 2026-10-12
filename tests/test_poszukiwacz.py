"""Lista życzeń szukana w tle w aplikacji (poszukiwacz.py) — bez Soulseeka.

Regresja z przeglądu 11.10.2026: interfejs obiecywał „apka poszuka go
w Soulseeku”, a serwer nigdy nie wołał wyszukiwania (tylko CLI) — pozycje
wisiały jako „szukam” na zawsze. Klient Soulseeka jest tu atrapą: żadnych
zapytań do sieci, żadnych prawdziwych pobrań.
"""
from __future__ import annotations

import time

import pytest
import requests
from fastapi.testclient import TestClient

from selekta import dlqueue, poszukiwacz, web, wishlist
from selekta.slskd_client import SearchHit, SlskdClient, SoulseekOffline


def _hit(nazwa, uzytk="u", lossless=False, bitrate=320, length=300):
    return SearchHit(username=uzytk, filename=f"@@x\\Muzyka\\{nazwa}", size=10_000_000,
                     bitrate=bitrate, length_s=length, is_lossless=lossless, free_slot=True)


class Atrapa(SlskdClient):
    """describe() prawdziwe (czysta logika), sieć podmieniona."""

    def __init__(self, wyniki=None, zalogowany=True, stan="ok", pustki=False, wyjatek=None):
        super().__init__("http://atrapa", "k")
        self.wyniki = wyniki or {}
        self.zalogowany, self._stan, self._pustki, self.wyjatek = zalogowany, stan, pustki, wyjatek
        self.szukane, self.pobrane, self.reset = [], [], 0

    def stan_api(self):
        return self._stan

    def logged_in(self):
        return self.zalogowany

    def network_down(self):
        return self._pustki

    def reset_empty_streak(self):
        self.reset += 1

    def search_track(self, artist, title, duration_s=None, timeout_s=15):
        self.szukane.append((artist, title))
        if self.wyjatek:
            raise self.wyjatek
        return list(self.wyniki.get(title, []))

    def download(self, hit):
        self.pobrane.append(hit.filename)


@pytest.fixture(autouse=True)
def _pusta_kolejka(monkeypatch):
    monkeypatch.setattr(dlqueue, "QUEUE", dlqueue.Queue())
    p = poszukiwacz.Poszukiwacz()
    monkeypatch.setattr(poszukiwacz, "POSZUKIWACZ", p)
    return p


def _wpis(artist, title, dur=None):
    return wishlist.add(artist, title, dur)


class TestCoPobieramySami:
    def test_pewny_plik_pobrany_a_cudzy_flac_nie(self, _pusta_kolejka):
        w = _wpis("Laherte", "Speeding", 300)
        klient = Atrapa({"Speeding": [
            _hit("Zupelnie Inny - Speeding Cars (Remix).flac", lossless=True),
            _hit("Laherte - Speeding (Original Mix).mp3", length=301),
        ]})
        wynik = _pusta_kolejka.cykl(klient)
        assert wynik["zlecone"] == 1
        assert klient.pobrane == ["@@x\\Muzyka\\Laherte - Speeding (Original Mix).mp3"]
        e = next(x for x in wishlist.items() if x["id"] == w["id"])
        assert e["found"] is True and e["stan"] == "zlecone"
        assert e["found_hit"]["filename"].endswith("Laherte - Speeding (Original Mix).mp3")

    def test_bez_znanego_czasu_czeka_na_potwierdzenie(self, _pusta_kolejka):
        w = _wpis("Alt8", "Next 2 Me")
        klient = Atrapa({"Next 2 Me": [_hit("Alt8 - Next 2 Me (Extended Mix).flac", lossless=True)]})
        wynik = _pusta_kolejka.cykl(klient)
        assert wynik["do_potwierdzenia"] == 1 and klient.pobrane == []
        e = next(x for x in wishlist.items() if x["id"] == w["id"])
        assert e["stan"] == "do-potwierdzenia" and not e.get("found")
        assert "Pobierz" in e["opis"]
        # użytkownik klika „Pobierz”
        poszukiwacz.pobierz_kandydata(w["id"], klient)
        assert klient.pobrane == ["@@x\\Muzyka\\Alt8 - Next 2 Me (Extended Mix).flac"]
        assert next(x for x in wishlist.items() if x["id"] == w["id"])["found"] is True

    @pytest.mark.parametrize("nazwa", [
        "Inny Artysta - Speeding.mp3",                     # inny wykonawca
        "Laherte - Speeding (Kowalski Remix).mp3",         # inna wersja
        "Laherte - Speeding Through The Night Sky.mp3",    # dłuższy, inny tytuł
        "Laherte - Speed.mp3",                             # brak słowa tytułu
        "Laherte - Speeding.lrc",                          # nie audio
    ])
    def test_nie_ten_utwor_nie_jest_pobierany(self, _pusta_kolejka, nazwa):
        _wpis("Laherte", "Speeding", 300)
        klient = Atrapa({"Speeding": [_hit(nazwa)]})
        wynik = _pusta_kolejka.cykl(klient)
        assert klient.pobrane == [] and wynik["zlecone"] == 0 and wynik["do_potwierdzenia"] == 0

    def test_zly_czas_odrzucony(self, _pusta_kolejka):
        _wpis("Laherte", "Speeding", 300)
        klient = Atrapa({"Speeding": [_hit("Laherte - Speeding.mp3", length=200)]})
        _pusta_kolejka.cykl(klient)
        assert klient.pobrane == []


class TestTempoSoulseeka:
    def test_ta_sama_pozycja_nie_szukana_w_kolko(self, _pusta_kolejka):
        _wpis("A", "Brak")
        klient = Atrapa({})
        _pusta_kolejka.cykl(klient)
        _pusta_kolejka.cykl(klient)
        assert klient.szukane == [("A", "Brak")]
        e = wishlist.items()[0]
        assert e["stan"] == "szukam" and e["proby"] == 1 and e["szukano_at"]

    def test_kilka_pozycji_na_cykl(self, _pusta_kolejka):
        for i in range(poszukiwacz.NA_CYKL + 3):
            _wpis("A", f"T{i}")
        klient = Atrapa({})
        _pusta_kolejka.cykl(klient)
        assert len(klient.szukane) == poszukiwacz.NA_CYKL

    def test_kolejka_pobierania_ma_pierwszenstwo(self, _pusta_kolejka, monkeypatch):
        _wpis("A", "T")
        monkeypatch.setattr(dlqueue.QUEUE, "_ensure_worker", lambda: None)
        dlqueue.QUEUE.add([{"artist": "X", "title": "Y"}])
        klient = Atrapa({})
        assert _pusta_kolejka.cykl(klient)["pominiety"] == "kolejka"
        assert klient.szukane == []

    def test_pustki_to_przerwa_wg_kolejki(self, _pusta_kolejka):
        _wpis("A", "T")
        klient = Atrapa({}, pustki=True)
        _pusta_kolejka.cykl(klient)
        assert klient.szukane == [] and klient.reset == 1
        assert _pusta_kolejka.pauza_do - time.time() == pytest.approx(
            dlqueue.PUSTKI_BACKOFF_S[0], abs=2)
        assert _pusta_kolejka.cykl(klient)["pominiety"] == "przerwa"

    def test_odciecie_przez_serwer_to_przerwa(self, _pusta_kolejka):
        _wpis("A", "T")
        _wpis("B", "U")
        klient = Atrapa({}, wyjatek=SoulseekOffline("odcięty"))
        _pusta_kolejka.cykl(klient)
        assert len(klient.szukane) == 1        # nie dobijamy serwera dalej
        assert _pusta_kolejka.pauza_do > time.time() + 10

    def test_rozlaczony_soulseek_nic_nie_szuka(self, _pusta_kolejka):
        _wpis("A", "T")
        klient = Atrapa({}, zalogowany=False)
        assert _pusta_kolejka.cykl(klient)["pominiety"] == "offline"
        assert klient.szukane == []

    def test_blad_sieci_nie_zabija_cyklu(self, _pusta_kolejka):
        _wpis("A", "T")
        klient = Atrapa({}, wyjatek=requests.ConnectionError("x"))
        _pusta_kolejka.cykl(klient)          # bez wyjątku


class TestZapisListy:
    def test_wpis_dodany_w_trakcie_szukania_nie_ginie(self, _pusta_kolejka):
        _wpis("A", "T")

        class Wolna(Atrapa):
            def search_track(self, artist, title, duration_s=None, timeout_s=15):
                wishlist.add("Nowy", "W trakcie")     # użytkownik klika w tym czasie
                return []

        _pusta_kolejka.cykl(Wolna({}))
        assert {w["title"] for w in wishlist.items()} == {"T", "W trakcie"}


class TestAplikacja:
    def test_serve_uruchamia_poszukiwacza(self, monkeypatch, tmp_path, _pusta_kolejka):
        import uvicorn
        uruchomione = []
        monkeypatch.setattr(_pusta_kolejka, "start", lambda: uruchomione.append(1))
        monkeypatch.setattr(web.obserwator.OBSERWATOR, "start", lambda f: None)
        monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
        web.serve(str(tmp_path), port=0)
        assert uruchomione == [1]

    def test_api_pokazuje_stan_i_pobiera_potwierdzone(self, lib_copy, monkeypatch,
                                                       _pusta_kolejka):
        web.set_folder(lib_copy)
        c = TestClient(web.app)
        w = _wpis("Alt8", "Next 2 Me")
        poszukiwacz.aktualizuj(w["id"], stan="do-potwierdzenia",
                               kandydat={"username": "u", "filename": "x\\Alt8 - Next 2 Me.flac",
                                         "size": 5, "bitrate": None, "length_s": 300,
                                         "is_lossless": True})
        d = c.get("/api/wishlist").json()
        assert "poszukiwacz" in d and d["items"][0]["stan"] == "do-potwierdzenia"
        pobrane = []
        monkeypatch.setattr(SlskdClient, "available", lambda self: True)
        monkeypatch.setattr(SlskdClient, "download", lambda self, h: pobrane.append(h.filename))
        r = c.post("/api/wishlist/pobierz", json={"id": w["id"]})
        assert r.status_code == 200, r.text
        assert pobrane == ["x\\Alt8 - Next 2 Me.flac"] and r.json()["item"]["found"] is True
        assert c.post("/api/wishlist/pobierz", json={"id": "nie-ma"}).status_code == 404
