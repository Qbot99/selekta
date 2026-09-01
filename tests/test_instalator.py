"""Automatyczna instalacja i konfiguracja slskd.

Najważniejsze, czego pilnują te testy: hasło do Soulseeka NIE wypływa
z komputera użytkownika — nie trafia do ustawień selekty, nie wraca
w żadnej odpowiedzi API i plik z nim ma prawa 0600.
"""
from __future__ import annotations

import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from selekta import instalator, web


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


class TestPlatforma:
    def test_rozpoznaje_znane_systemy(self, monkeypatch):
        przypadki = [
            ("Darwin", "arm64", "osx-arm64"), ("Darwin", "x86_64", "osx-x64"),
            ("Linux", "x86_64", "linux-x64"), ("Linux", "aarch64", "linux-arm64"),
            ("Windows", "AMD64", "win-x64"), ("Windows", "ARM64", "win-arm64"),
        ]
        for system, maszyna, oczekiwane in przypadki:
            monkeypatch.setattr(instalator.platform, "system", lambda s=system: s)
            monkeypatch.setattr(instalator.platform, "machine", lambda m=maszyna: m)
            assert instalator.platforma() == oczekiwane

    def test_nieznany_system_to_none(self, monkeypatch):
        monkeypatch.setattr(instalator.platform, "system", lambda: "Plan9")
        assert instalator.platforma() is None


class TestKonfiguracja:
    def test_zapisuje_klucz_i_katalogi(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="ABC123",
                                       katalog_pobran="/muzyka")
        tresc = yml.read_text(encoding="utf-8")
        assert "ABC123" in tresc and "downloads: /muzyka" in tresc

    def test_plik_z_haslem_ma_prawa_0600(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K",
                                       katalog_pobran="/m",
                                       login="ktos", haslo="tajne")
        assert oct(os.stat(yml).st_mode)[-3:] == "600"

    def test_ponowny_zapis_nie_dubluje_bloku(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        for klucz in ("PIERWSZY", "DRUGI"):
            instalator.zapisz_konfiguracje(str(yml), klucz_api=klucz,
                                           katalog_pobran="/m")
        tresc = yml.read_text(encoding="utf-8")
        assert tresc.count(instalator.POCZATEK) == 1
        assert "PIERWSZY" not in tresc and "DRUGI" in tresc

    def test_zapis_bez_danych_konta_ich_nie_kasuje(self, tmp_path):
        """Zmiana katalogu nie może wylogować użytkownika z Soulseeka."""
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K",
                                       katalog_pobran="/a",
                                       login="dj", haslo="tajne123")
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K",
                                       katalog_pobran="/b")
        tresc = yml.read_text(encoding="utf-8")
        assert "username: dj" in tresc and "tajne123" in tresc

    def test_konto_ustawione_wykrywa_komplet(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K", katalog_pobran="/m")
        assert instalator.konto_ustawione(str(yml)) is False
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K", katalog_pobran="/m",
                                       login="dj", haslo="x")
        assert instalator.konto_ustawione(str(yml)) is True

    def test_zachowuje_ustawienia_uzytkownika_spoza_bloku(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        yml.write_text("# moje własne ustawienie\ndebug: true\n", encoding="utf-8")
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K", katalog_pobran="/m")
        assert "debug: true" in yml.read_text(encoding="utf-8")

    def test_klucz_api_jest_losowy_i_dlugi(self):
        a, b = instalator.wygeneruj_klucz(), instalator.wygeneruj_klucz()
        assert a != b and len(a) >= 32


class TestBezpieczenstwoArchiwum:
    def test_odrzuca_archiwum_wychodzace_poza_katalog(self, tmp_path, monkeypatch):
        """Zip slip: wpis '../../evil' nie może nadpisać plików poza celem."""
        zly = tmp_path / "zly.zip"
        with zipfile.ZipFile(zly, "w") as z:
            z.writestr("../../evil.txt", "nie powinno mnie tu być")

        monkeypatch.setattr(instalator, "najnowsze_wydanie",
                            lambda: ("0.0.0", "http://przyklad/zly.zip"))

        class FalszywaOdpowiedz:
            ok = True
            def raise_for_status(self): pass
            def iter_content(self, chunk_size=0):
                yield zly.read_bytes()

        monkeypatch.setattr(instalator.requests, "get",
                            lambda *a, **kw: FalszywaOdpowiedz())
        cel = tmp_path / "cel"
        udane, komunikat, _ = instalator.zainstaluj(str(cel))
        assert udane is False
        assert "poza katalogiem" in komunikat
        assert not (tmp_path.parent / "evil.txt").exists()


class TestHasloNieWyplywa:
    def test_endpoint_konta_nie_zwraca_hasla(self, client, tmp_path, monkeypatch):
        yml = tmp_path / "slskd.yml"
        monkeypatch.setattr(web.slskd_ctl, "find_config", lambda: str(yml))
        monkeypatch.setattr(web.slskd_ctl, "stop", lambda: (True, ""))
        monkeypatch.setattr(web.slskd_ctl, "start", lambda: (True, "ok"))
        monkeypatch.setattr(web.time, "sleep", lambda s: None)
        r = client.post("/api/setup/konto",
                        json={"login": "dj", "haslo": "SuperTajne123"})
        assert r.status_code == 200, r.text
        assert "SuperTajne123" not in r.text

    def test_haslo_nie_trafia_do_ustawien_selekty(self, client, tmp_path,
                                                  monkeypatch):
        yml = tmp_path / "slskd.yml"
        monkeypatch.setattr(web.slskd_ctl, "find_config", lambda: str(yml))
        monkeypatch.setattr(web.slskd_ctl, "stop", lambda: (True, ""))
        monkeypatch.setattr(web.slskd_ctl, "start", lambda: (True, "ok"))
        monkeypatch.setattr(web.time, "sleep", lambda s: None)
        client.post("/api/setup/konto", json={"login": "dj", "haslo": "SuperTajne123"})
        assert "SuperTajne123" not in str(web.config.load())

    def test_stan_kreatora_nie_ujawnia_hasla(self, client):
        assert "haslo" not in client.get("/api/setup/stan").text.lower()

    def test_puste_dane_sa_odrzucane(self, client):
        assert client.post("/api/setup/konto",
                           json={"login": "", "haslo": ""}).status_code == 400
        assert client.post("/api/setup/konto",
                           json={"login": "dj"}).status_code == 400

    def test_absurdalnie_dlugie_dane_odrzucone(self, client):
        r = client.post("/api/setup/konto",
                        json={"login": "d" * 200, "haslo": "x"})
        assert r.status_code == 400
