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


# ---------------------------------------------------------------------------
# Regresje z przeglądu 11.10.2026
# ---------------------------------------------------------------------------
class _Odp:
    def __init__(self, kod, dane=None):
        self.status_code, self.ok, self._d = kod, kod < 400, dane or {}

    def json(self):
        return self._d


def _udawany_slskd(monkeypatch, kod_sesji=200, zalogowany=True):
    """requests.get w kliencie slskd → odpowiedzi jak z prawdziwego API (bez sieci)."""
    from selekta import slskd_client

    def get(url, headers=None, timeout=None):
        if kod_sesji is None:
            raise slskd_client.requests.ConnectionError("odmowa połączenia")
        if url.endswith("/api/v0/session"):
            return _Odp(kod_sesji)
        if url.endswith("/api/v0/server"):
            return _Odp(200 if kod_sesji == 200 else kod_sesji, {"isLoggedIn": zalogowany})
        return _Odp(404)

    monkeypatch.setattr(slskd_client.requests, "get", get)


class TestZlyKluczToNieWylaczonySlskd:
    def test_klient_rozroznia_stany(self, monkeypatch):
        from selekta.slskd_client import SlskdClient
        for kod, stan in ((200, "ok"), (401, "klucz"), (403, "klucz"), (None, "brak"),
                          (500, "blad")):
            _udawany_slskd(monkeypatch, kod_sesji=kod)
            assert SlskdClient("http://x", "k").stan_api() == stan, kod

    def test_polaczenie_przy_zlym_kluczu(self, client, monkeypatch):
        _udawany_slskd(monkeypatch, kod_sesji=401)
        d = client.get("/api/setup/polaczenie").json()
        assert d["stan"] == "zly-klucz"
        assert "klucz" in d["opis"] and "nie odpowiada" not in d["opis"]

    def test_polaczenie_gdy_slskd_nie_dziala(self, client, monkeypatch):
        _udawany_slskd(monkeypatch, kod_sesji=None)
        assert client.get("/api/setup/polaczenie").json()["stan"] == "brak-slskd"

    def test_kropka_stanu_przy_zlym_kluczu_nie_kaze_uruchamiac(self, client, monkeypatch):
        _udawany_slskd(monkeypatch, kod_sesji=401)
        d = client.get("/api/status").json()
        assert d["level"] == "red"
        assert "klucz" in (d["label"] + d["hint"]).lower()
        assert "uruchom" not in d["hint"].lower()


class TestKrokiBezSprzecznosci:
    """slskd działa i jest zalogowany, ale spoza znanych ścieżek (Docker,
    inny HOME, konto wpisane w panelu slskd) — kreator nie może proponować
    pobrania 55 MB ani pisać „połączony” przy niezrobionym kroku."""

    def _stan(self, client, monkeypatch, zalogowany=True, kod=200, proces=False):
        from selekta import config, slskd_ctl
        monkeypatch.setattr(slskd_ctl, "find_binary", lambda: "")
        monkeypatch.setattr(slskd_ctl, "find_config", lambda: "")
        # proces=False: np. Docker — pgrep go nie widzi, ale API odpowiada
        monkeypatch.setattr(slskd_ctl, "is_running", lambda: proces)
        config.save({"slskd_api_key": "k" * 48})
        _udawany_slskd(monkeypatch, kod_sesji=kod, zalogowany=zalogowany)
        return {k["id"]: k for k in client.get("/api/setup/stan").json()["kroki"]}

    @pytest.mark.parametrize("proces", [True, False])
    def test_dzialajacy_zalogowany_slskd_spoza_znanych_sciezek(self, client, monkeypatch,
                                                                proces):
        kroki = self._stan(client, monkeypatch, proces=proces)
        assert kroki["slskd"]["gotowe"] is True and kroki["slskd"]["akcja"] is None
        assert "55 MB" not in kroki["slskd"]["opis"]
        assert kroki["konto"]["gotowe"] is True
        assert kroki["uruchomiony"]["gotowe"] is True

    def test_opis_nigdy_nie_mowi_polaczony_przy_niegotowym_kroku(self, client, monkeypatch):
        for zalogowany in (True, False):
            for k in self._stan(client, monkeypatch, zalogowany=zalogowany,
                                proces=True).values():
                if not k["gotowe"]:
                    assert "połączony" not in k["opis"], k

    def test_zly_klucz_to_niegotowa_konfiguracja(self, client, monkeypatch):
        kroki = self._stan(client, monkeypatch, kod=401)
        assert kroki["konfiguracja"]["gotowe"] is False
        assert "klucz" in kroki["konfiguracja"]["opis"]
        assert kroki["slskd"]["gotowe"] is True        # działa — nie „zainstaluj”


class TestPominZapamietane:
    def test_pomin_przezywa_restart(self, client):
        from selekta import config
        assert client.get("/api/setup/stan").json()["pominiety"] is False
        assert client.post("/api/setup/pomin", json={}).json()["pominiety"] is True
        assert config.load()["kreator_pominiety"] is True       # w config.json, nie w karcie
        assert client.get("/api/setup/stan").json()["pominiety"] is True
        client.post("/api/setup/pomin", json={"pominiety": False})
        assert client.get("/api/setup/stan").json()["pominiety"] is False

    def test_powloka_nie_pokazuje_kreatora_po_pominieciu(self):
        import os
        js = open(os.path.join(os.path.dirname(web.__file__), "static", "ekrany",
                               "_powloka.js"), encoding="utf-8").read()
        assert "pominiety" in js, "start() musi respektować zapamiętane „Pomiń”"
        wj = open(os.path.join(os.path.dirname(web.__file__), "static", "ekrany",
                               "wiecej.js"), encoding="utf-8").read()
        assert "/api/setup/pomin" in wj


class TestKonfigurujPrzyOdrzuconymKluczu:
    def test_bierze_dzialajacy_klucz_z_konfiguracji_slskd(self, client, monkeypatch, tmp_path):
        from selekta import config, slskd_client, slskd_ctl
        yml = tmp_path / "slskd.yml"
        yml.write_text("web:\n  authentication:\n    api_keys:\n      moj:\n"
                       "        key: dzialajacy0123456789abcdef\n", encoding="utf-8")
        tresc = yml.read_text(encoding="utf-8")
        monkeypatch.setattr(slskd_ctl, "find_config", lambda: str(yml))
        config.save({"slskd_api_key": "stary-klucz-0123456789"})

        def get(url, headers=None, timeout=None):
            ok = (headers or {}).get("X-API-Key") == "dzialajacy0123456789abcdef"
            return _Odp(200 if ok else 401)

        monkeypatch.setattr(slskd_client.requests, "get", get)
        r = client.post("/api/setup/konfiguruj", json={})
        assert r.status_code == 200 and "działający klucz" in r.json()["message"]
        assert config.load()["slskd_api_key"] == "dzialajacy0123456789abcdef"
        assert yml.read_text(encoding="utf-8") == tresc          # pliku nie ruszamy
