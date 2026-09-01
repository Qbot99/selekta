"""Energia i struktura — druga połowa układania setu.

Porządkowanie harmoniczne mówi, KTÓRE utwory da się złożyć. Te testy
pilnują tego, co mówi, w JAKIEJ KOLEJNOŚCI set ma sens — i że analiza
działa na wskazanym secie, nie tylko na całej bibliotece.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import energia, web
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def _set(*energie):
    return [{"file": f"u{i}.flac", "title": f"Utwor {i}", "srednia": e}
            for i, e in enumerate(energie)]


class TestGraniceFraz:
    def test_frazy_leza_na_wielokrotnosci_taktow(self):
        """16 taktów przy 150 BPM to 25,6 s."""
        g = energia.granice_fraz(120, 150, 0.0)
        assert g[0] == 0.0
        assert abs((g[1] - g[0]) - 25.6) < 0.01

    def test_frazy_startuja_od_kotwicy(self):
        g = energia.granice_fraz(120, 150, 1.8)
        assert g[0] == 1.8

    def test_bez_bpm_nie_ma_fraz(self):
        assert energia.granice_fraz(120, None, 0) == []
        assert energia.granice_fraz(120, 0, 0) == []

    def test_zerowa_dlugosc_nie_wywala(self):
        assert energia.granice_fraz(0, 150, 0) == []

    def test_32_takty_sa_dwa_razy_rzadsze(self):
        a = energia.granice_fraz(300, 150, 0, taktow=16)
        b = energia.granice_fraz(300, 150, 0, taktow=32)
        assert len(a) == 2 * len(b) or len(a) - 1 == 2 * len(b) - 1


class TestLukSetu:
    def test_wykrywa_wczesna_kulminacje(self):
        uwagi = energia.luk_setu(_set(.4, .9, .5, .5, .45, .4, .4, .35))["uwagi"]
        assert any(u["typ"] == "wczesna-kulminacja" for u in uwagi)

    def test_wykrywa_dziure_w_srodku(self):
        uwagi = energia.luk_setu(_set(.4, .5, .6, .30, .62, .7, .75))["uwagi"]
        dziura = next(u for u in uwagi if u["typ"] == "dziura")
        assert dziura["pozycja"] == 3

    def test_wykrywa_plaski_set(self):
        uwagi = energia.luk_setu(_set(.5, .52, .51, .5, .53, .51, .5))["uwagi"]
        assert any(u["typ"] == "plaski" for u in uwagi)

    def test_narastajacy_set_bez_uwag(self):
        r = energia.luk_setu(_set(.35, .42, .5, .58, .66, .74, .82))
        assert r["uwagi"] == []
        assert r["kulminacja"] == 6, "kulminacja na końcu"

    def test_pusty_set_nie_wywala(self):
        assert energia.luk_setu([])["uwagi"] == []

    def test_jeden_utwor_nie_generuje_uwag(self):
        assert energia.luk_setu(_set(.5))["uwagi"] == []


class TestFazaUtworu:
    def _s(self, **kw):
        s = energia.Struktura(czas_s=300)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_glosny_jasny_i_gesty_to_kulminacja(self):
        assert energia._faza(self._s(srednia=.7, jasnosc=3.0,
                                     gestosc_perkusji=6.0)) == "kulminacja"

    def test_cichy_i_rzadki_to_rozgrzewka(self):
        assert energia._faza(self._s(srednia=.3, jasnosc=1.5,
                                     gestosc_perkusji=2.0)) == "rozgrzewka"

    def test_duzy_breakdown_odbiera_punkt(self):
        """Głośny, ale w połowie pusty — to nie jest szczyt setu."""
        pelny = self._s(srednia=.7, jasnosc=3.0, gestosc_perkusji=6.0,
                        breakdown_s=10)
        dziurawy = self._s(srednia=.7, jasnosc=3.0, gestosc_perkusji=6.0,
                           breakdown_s=120)
        assert energia._faza(pelny) == "kulminacja"
        assert energia._faza(dziurawy) != "kulminacja"


class TestZakresAnalizy:
    """Najważniejsze: analiza ma działać na WSKAZANYM secie."""

    def test_zaznaczenie_ogranicza_zakres(self, client):
        """Statystyki liczą tylko utwory z analizą — suma musi się zgadzać
        z liczbą plików w zakresie, nie z całą biblioteką."""
        d = client.post("/api/statystyki", json={"files": [GOOD_MP3]}).json()
        assert d["zakres"] == "zaznaczenie"
        assert d["przeanalizowanych"] + d["bez_analizy"] == 1

    def test_brak_ciala_to_cala_biblioteka(self, client):
        d = client.post("/api/statystyki", json={}).json()
        assert d["zakres"] == "cała biblioteka"
        assert d["przeanalizowanych"] + d["bez_analizy"] > 1

    def test_zaznaczenie_jest_wezsze_niz_biblioteka(self, client):
        jeden = client.post("/api/statystyki", json={"files": [GOOD_MP3]}).json()
        wszystko = client.post("/api/statystyki", json={}).json()
        assert (jeden["przeanalizowanych"] + jeden["bez_analizy"]
                < wszystko["przeanalizowanych"] + wszystko["bez_analizy"])

    def test_nieznana_playlista_to_czytelny_blad(self, client):
        r = client.post("/api/statystyki", json={"name": "nie-ma-takiej"})
        assert r.status_code == 404

    def test_energia_dla_zaznaczenia(self, client):
        d = client.post("/api/energia", json={"files": [GOOD_MP3, GOOD_FLAC]}).json()
        assert d["zakres"] == "zaznaczenie" and d["utworow"] == 2
        assert len(d["punkty"]) == 2
        assert all("faza" in u and "intro_typ" in u for u in d["utwory"])

    def test_energia_odrzuca_pusty_zakres(self, client):
        r = client.post("/api/energia", json={"files": ["nie-ma-takiego.flac"]})
        assert r.status_code == 400

    def test_pliki_spoza_biblioteki_sa_pomijane(self, client):
        r = client.post("/api/energia", json={"files": ["../../etc/hosts"]})
        assert r.status_code == 400
