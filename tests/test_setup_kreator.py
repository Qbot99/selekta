"""Kreator pierwszego uruchomienia — lista kroków dla nowego użytkownika.

Ważne ograniczenie, którego pilnujemy testem: selekta NIE przyjmuje ani
nie przechowuje hasła do Soulseeka. Użytkownik wpisuje je bezpośrednio
w panelu slskd; my tylko sprawdzamy, czy połączenie działa.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from selekta import web


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


class TestStanKreatora:
    def test_zwraca_wszystkie_kroki(self, client):
        d = client.get("/api/setup/stan").json()
        assert {k["id"] for k in d["kroki"]} == {
            "folder", "slskd", "konfiguracja", "konto", "uruchomiony"}
        assert d["krokow"] == 5

    def test_kazdy_krok_ma_tytul_i_opis(self, client):
        for k in client.get("/api/setup/stan").json()["kroki"]:
            assert k["tytul"] and k["opis"], f"krok {k['id']} bez opisu"
            assert isinstance(k["gotowe"], bool)

    def test_folder_z_muzyka_jest_wykryty(self, client):
        kroki = {k["id"]: k for k in client.get("/api/setup/stan").json()["kroki"]}
        assert kroki["folder"]["gotowe"] is True
        assert "utworów" in kroki["folder"]["opis"]

    def test_nastepny_krok_wskazuje_pierwszy_niezrobiony(self, client):
        d = client.get("/api/setup/stan").json()
        niezrobione = [k["id"] for k in d["kroki"] if not k["gotowe"]]
        if niezrobione:
            assert d["nastepny"] == niezrobione[0]
        else:
            assert d["nastepny"] is None and d["gotowe"] is True

    def test_zrobionych_zgadza_sie_z_krokami(self, client):
        d = client.get("/api/setup/stan").json()
        assert d["zrobionych"] == sum(1 for k in d["kroki"] if k["gotowe"])


class TestBezpieczenstwoHasla:
    """Hasło do Soulseeka nie ma prawa przejść przez selektę."""

    def test_krok_konta_prosi_o_dane_a_nie_je_wymysla(self, client):
        """Login i hasło podaje użytkownik — apka ich nie generuje."""
        kroki = {k["id"]: k for k in client.get("/api/setup/stan").json()["kroki"]}
        konto = kroki["konto"]
        if not konto["gotowe"]:
            # istotne jest DZIAŁANIE (użytkownik podaje dane), nie brzmienie
            # opisu — ten zależy od tego, czy konto jest już zapisane
            assert konto["akcja"] == "podaj-konto"
            assert konto["opis"]

    def test_stan_kreatora_nigdy_nie_zawiera_wartosci_hasla(self, client):
        """Lista kroków to opis stanu — nie ma prawa nieść danych logowania."""
        d = client.get("/api/setup/stan").json()
        for k in d["kroki"]:
            assert "password" not in k and "haslo" not in k

    def test_nie_ma_endpointu_przyjmujacego_haslo(self, client):
        sciezki = [r.path for r in web.app.routes]
        assert not [p for p in sciezki if "password" in p or "haslo" in p]
