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
            "folder", "slskd", "uruchomiony", "klucz", "konto"}
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

    def test_krok_konta_odsyla_do_panelu_slskd(self, client):
        kroki = {k["id"]: k for k in client.get("/api/setup/stan").json()["kroki"]}
        konto = kroki["konto"]
        if not konto["gotowe"]:
            assert konto["akcja"] == "otworz-panel-slskd"
            assert konto["panel"].startswith("http://localhost:")
            assert "nie przechowuje" in konto["opis"]

    def test_zaden_krok_nie_prosi_o_haslo(self, client):
        tresc = str(client.get("/api/setup/stan").json())
        assert "haslo" not in tresc.replace("hasło", "haslo").replace(
            "hasło i", "").lower() or "nie przechowuje" in tresc

    def test_nie_ma_endpointu_przyjmujacego_haslo(self, client):
        sciezki = [r.path for r in web.app.routes]
        assert not [p for p in sciezki if "password" in p or "haslo" in p]
