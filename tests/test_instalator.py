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
        assert "ABC123" in tresc and 'downloads: "/muzyka"' in tresc

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
        assert 'username: "dj"' in tresc and "tajne123" in tresc

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


# ---------------------------------------------------------------------------
# YAML pisany poprawnie — regresje z przeglądu 11.10.2026
# ---------------------------------------------------------------------------
yaml = pytest.importorskip("yaml")


class _Scisly(yaml.SafeLoader):
    """Parser, który — jak część parserów YAML — odrzuca zdublowane klucze."""


def _bez_duplikatow(loader, node, deep=False):
    klucze = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    dup = {k for k in klucze if klucze.count(k) > 1}
    if dup:
        raise ValueError(f"zdublowane klucze: {dup}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Scisly.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _bez_duplikatow)


def _wczytaj(sciezka) -> dict:
    with open(sciezka, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_Scisly)


TRUDNE_HASLA = [
    "zwykle123", "abc #def", "pa: ss", "@start", "*gwiazdka", "%proc",
    "'w cudzyslowie'", '"podwojny"', "[nawias", "{klamra", "!wykrzyk", "|pion",
    "> wiekszy", "- myslnik", "koniec ", " poczatek", "tak", "yes", "123456",
    "1e3", "0x1F", "null", "~", "#hash", "a'b\"c", "back\\slash\\", "tab\tw środku",
    "zażółć gęślą jaźń", "emoji 🎧🔥", "ctrl\x7f\x01", "a: b # c: d",
]


class TestYamlZCudzyslowami:
    @pytest.mark.parametrize("haslo", TRUDNE_HASLA)
    def test_haslo_wraca_identyczne(self, tmp_path, haslo):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="k" * 48,
                                       katalog_pobran="/m", login="dj", haslo=haslo)
        d = _wczytaj(yml)
        assert d["soulseek"]["password"] == haslo
        assert d["soulseek"]["username"] == "dj"
        # ponowny zapis bez danych konta (jak „Skonfiguruj”) nie może ich zmienić
        instalator.zapisz_konfiguracje(str(yml), klucz_api="k" * 48, katalog_pobran="/m")
        assert _wczytaj(yml)["soulseek"]["password"] == haslo
        assert instalator._wyczytaj(yml.read_text(encoding="utf-8"), "password") == haslo

    def test_login_ze_znakami_specjalnymi(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K" * 20, katalog_pobran="/m",
                                       login="dj #1: ziom", haslo="x")
        assert _wczytaj(yml)["soulseek"]["username"] == "dj #1: ziom"

    def test_foldery_ze_znakami_specjalnymi(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        dziwny = "/Users/x/Music/DJ #1: sety 'stare' \"nowe\""
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K" * 20,
                                       katalog_pobran=dziwny,
                                       katalog_niepelnych=dziwny + "/nie",
                                       udostepniane=[dziwny, "/a: b"])
        d = _wczytaj(yml)
        assert d["directories"]["downloads"] == dziwny
        assert d["directories"]["incomplete"] == dziwny + "/nie"
        assert d["shares"]["directories"] == [dziwny, "/a: b"]

    def test_klucz_api_cyfrowy_zostaje_tekstem(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="1" * 48, katalog_pobran="/m")
        klucz = _wczytaj(yml)["web"]["authentication"]["api_keys"]["selekta"]["key"]
        assert klucz == "1" * 48

    def test_autowykrywanie_klucza_czyta_wartosc_w_cudzyslowie(self, tmp_path, monkeypatch):
        from selekta import slskd_ctl
        yml = tmp_path / "slskd.yml"
        instalator.zapisz_konfiguracje(str(yml), klucz_api="abcdef0123456789" * 3,
                                       katalog_pobran="/m")
        monkeypatch.setattr(slskd_ctl, "find_config", lambda: str(yml))
        assert slskd_ctl.api_key_from_slskd_config() == "abcdef0123456789" * 3

    def test_plik_tymczasowy_z_haslem_nigdy_nie_jest_czytelny_dla_innych(
            self, tmp_path, monkeypatch):
        yml = tmp_path / "slskd.yml"
        tryby = []
        oryg = os.replace

        def szpieg(a, b):
            tryby.append(os.stat(a).st_mode & 0o777)
            return oryg(a, b)

        monkeypatch.setattr(instalator.os, "replace", szpieg)
        instalator.zapisz_konfiguracje(str(yml), klucz_api="K" * 20, katalog_pobran="/m",
                                       login="dj", haslo="tajne")
        assert tryby and all(t == 0o600 for t in tryby), [oct(t) for t in tryby]


UZYTKOWNIKA = """\
# moja konfiguracja slskd
directories:
  downloads: /Users/x/Downloads/slsk   # stary folder
  # incomplete: /tmp/x
soulseek:
  username: stary
  password: starehaslo
  listen_port: 50300
web:
  port: 5030
  authentication:
    username: admin
    password: "admin pass"
    api_keys:
      moj:
        key: mojwlasnykluczapi0123456789
        role: readonly
shares:
  directories:
  - /Users/x/Music/udostepnione
debug: true
"""


class TestScalanieZSekcjamiUzytkownika:
    def _zapisz(self, yml, **kw):
        arg = dict(klucz_api="k" * 48, katalog_pobran="/Users/x/Music",
                   katalog_niepelnych="/Users/x/inc")
        arg.update(kw)
        instalator.zapisz_konfiguracje(str(yml), **arg)

    def test_brak_zdublowanych_kluczy_i_zachowane_ustawienia(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        yml.write_text(UZYTKOWNIKA, encoding="utf-8")
        self._zapisz(yml, login="nowy", haslo="nowe #haslo",
                     udostepniane=["/Users/x/Music"])
        d = _wczytaj(yml)                      # ścisły parser: brak duplikatów
        assert d["soulseek"] == {"username": "nowy", "password": "nowe #haslo",
                                 "listen_port": 50300}
        assert d["directories"]["downloads"] == "/Users/x/Music"
        assert d["directories"]["incomplete"] == "/Users/x/inc"
        auth = d["web"]["authentication"]
        assert auth["username"] == "admin" and auth["password"] == "admin pass"
        assert auth["api_keys"]["moj"]["key"] == "mojwlasnykluczapi0123456789"
        assert auth["api_keys"]["selekta"]["key"] == "k" * 48
        assert d["web"]["port"] == 5030 and d["debug"] is True
        assert d["shares"]["directories"] == ["/Users/x/Music/udostepnione", "/Users/x/Music"]
        tresc = yml.read_text(encoding="utf-8")
        assert "# moja konfiguracja slskd" in tresc and "# incomplete: /tmp/x" in tresc

    def test_ponowny_zapis_niczego_nie_zmienia(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        yml.write_text(UZYTKOWNIKA, encoding="utf-8")
        self._zapisz(yml, login="nowy", haslo="h", udostepniane=["/Users/x/Music"])
        raz = yml.read_text(encoding="utf-8")
        self._zapisz(yml, udostepniane=["/Users/x/Music"])
        assert yml.read_text(encoding="utf-8") == raz

    def test_kopia_zapasowa_przed_zapisem(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        yml.write_text(UZYTKOWNIKA, encoding="utf-8")
        self._zapisz(yml)
        kopia = tmp_path / ("slskd.yml" + instalator.KOPIA_PIERWOTNA)
        assert kopia.read_text(encoding="utf-8") == UZYTKOWNIKA
        assert oct(os.stat(kopia).st_mode)[-3:] == "600"
        self._zapisz(yml, login="a", haslo="b")
        # oryginał sprzed pierwszej ingerencji selekty zostaje nietknięty
        assert kopia.read_text(encoding="utf-8") == UZYTKOWNIKA
        assert (tmp_path / ("slskd.yml" + instalator.KOPIA_OSTATNIA)).is_file()

    def test_nietypowy_zapis_nie_jest_psuty(self, tmp_path):
        yml = tmp_path / "slskd.yml"
        tresc = "soulseek: {username: a, password: b}\n"
        yml.write_text(tresc, encoding="utf-8")
        with pytest.raises(ValueError, match="soulseek"):
            self._zapisz(yml, login="x", haslo="y")
        assert yml.read_text(encoding="utf-8") == tresc

    def test_domyslny_plik_slskd_same_komentarze(self, tmp_path):
        """Domyślny slskd.yml to same komentarze — blok selekty jak dotąd."""
        yml = tmp_path / "slskd.yml"
        yml.write_text("# debug: false\n# soulseek:\n#   username: ~\n", encoding="utf-8")
        self._zapisz(yml, login="dj", haslo="p")
        tresc = yml.read_text(encoding="utf-8")
        assert tresc.count(instalator.POCZATEK) == 1
        assert _wczytaj(yml)["soulseek"]["username"] == "dj"


class TestEndpointyPrzyNietypowymPliku:
    def test_konto_przy_nietypowym_pliku_409_i_bez_restartu(self, client, tmp_path,
                                                            monkeypatch):
        yml = tmp_path / "slskd.yml"
        yml.write_text("soulseek: {username: a, password: b}\n", encoding="utf-8")
        wywolania = []
        monkeypatch.setattr(web.slskd_ctl, "find_config", lambda: str(yml))
        monkeypatch.setattr(web.slskd_ctl, "stop", lambda: wywolania.append("stop") or (True, ""))
        monkeypatch.setattr(web.slskd_ctl, "start", lambda: wywolania.append("start") or (True, ""))
        monkeypatch.setattr(web.time, "sleep", lambda s: None)
        r = client.post("/api/setup/konto", json={"login": "dj", "haslo": "x #y"})
        assert r.status_code == 409 and "soulseek" in r.json()["detail"]
        assert wywolania == [] and "x #y" not in r.text
        assert yml.read_text(encoding="utf-8") == "soulseek: {username: a, password: b}\n"

    def test_konfiguruj_scala_z_sekcjami_uzytkownika(self, client, tmp_path, monkeypatch):
        yml = tmp_path / "slskd.yml"
        yml.write_text(UZYTKOWNIKA, encoding="utf-8")
        monkeypatch.setattr(web.slskd_ctl, "find_config", lambda: str(yml))
        r = client.post("/api/setup/konfiguruj", json={})
        assert r.status_code == 200, r.text
        d = _wczytaj(yml)
        assert d["soulseek"]["username"] == "stary"          # konto użytkownika zostaje
        assert d["web"]["authentication"]["api_keys"]["selekta"]["key"]

    def test_konto_przy_cudzym_slskd_nie_restartuje(self, client, tmp_path, monkeypatch):
        """stop() nie zatrzymuje już cudzego slskd — endpoint mówi to wprost
        zamiast udawać restart i kazać czekać 25 s na połączenie."""
        yml = tmp_path / "slskd.yml"
        wywolania = []
        monkeypatch.setattr(web.slskd_ctl, "find_config", lambda: str(yml))
        monkeypatch.setattr(web.slskd_ctl, "stop",
                            lambda: (False, "działający slskd nie pochodzi z instalacji"))
        monkeypatch.setattr(web.slskd_ctl, "start", lambda: wywolania.append("start") or (True, ""))
        monkeypatch.setattr(web.time, "sleep", lambda s: None)
        r = client.post("/api/setup/konto", json={"login": "dj", "haslo": "h"})
        assert r.status_code == 200 and r.json()["restart"] is False
        assert wywolania == [] and _wczytaj(yml)["soulseek"]["password"] == "h"
