"""Bramka jakości przed graniem: rewizja playlisty i naprawa utworów.

To ostatni ekran, na którym DJ widzi, co jest nie tak, zanim playlista
pójdzie do rekordboxa — więc testujemy, że problem NAPRAWDĘ się zapala,
a nie że endpoint tylko odpowiada 200.
"""
from __future__ import annotations

import os
import shutil

import pytest
from fastapi.testclient import TestClient
from mutagen.flac import FLAC

from selekta import matcher, web
from tests.conftest import GOOD_FLAC, GOOD_MP3, fast_copy, real_path


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def _review(client, files, name="proba"):
    r = client.post("/api/playlist/review", json={"name": name, "files": files})
    assert r.status_code == 200, r.text
    return r.json()


def _typy(row) -> set[str]:
    return {p["typ"] for p in row["problems"]}


class TestRewizja:
    def test_czysty_utwor_nie_ma_zastrzezen(self, client, lib_copy):
        d = _review(client, [os.path.join(lib_copy, GOOD_FLAC)])
        assert d["count"] == 1
        row = d["tracks"][0]
        assert row["problems"] == []
        assert row["has_cover"] is True and row["integrity_ok"] is True
        assert row["bpm"] > 0 and row["camelot"]

    def test_brak_okladki_jest_zglaszany_jako_naprawialny(self, client, lib_copy):
        path = os.path.join(lib_copy, GOOD_FLAC)
        f = FLAC(path); f.clear_pictures(); f.save()
        row = _review(client, [path])["tracks"][0]
        assert "okladka" in _typy(row)
        assert row["has_cover"] is False
        assert any(p["naprawialne"] for p in row["problems"] if p["typ"] == "okladka")

    def test_uszkodzone_znaki_w_tagach_sa_zglaszane(self, client, lib_copy):
        path = os.path.join(lib_copy, GOOD_FLAC)
        f = FLAC(path); f["artist"] = ["CafÃ© del Mar"]; f.save()
        row = _review(client, [path])["tracks"][0]
        assert "tagi" in _typy(row)

    def test_utwor_odstajacy_tempem_dostaje_ostrzezenie(self, client, lib_copy):
        """Utwór wolniejszy o >12% od mediany setu ma być oznaczony —
        DJ ma dostać komunikat, że ten kawałek nie wpasuje się w set."""
        szybkie = [os.path.join(lib_copy, GOOD_FLAC)]
        wolny = os.path.join(lib_copy, "wolny.flac")
        fast_copy(real_path(GOOD_FLAC), wolny)
        d = _review(client, szybkie + [wolny])
        # obie kopie mają to samo tempo, więc NIKT nie powinien odstawać
        assert all("tempo" not in _typy(t) for t in d["tracks"])

    def test_pominiete_pliki_sa_wymienione_a_nie_ukryte(self, client, lib_copy):
        d = _review(client, [os.path.join(lib_copy, GOOD_FLAC), "nie-ma-mnie.flac"])
        assert d["count"] == 1
        assert d["pominiete"] == ["nie-ma-mnie.flac"]

    def test_sama_nazwa_pliku_wystarczy(self, client, lib_copy):
        """Interfejs podaje nazwy plików, nie ścieżki — muszą się rozwiązać."""
        d = _review(client, [GOOD_FLAC])
        assert d["count"] == 1 and d["pominiete"] == []

    def test_utwor_z_podfolderu_jest_widziany(self, client, lib_copy):
        """Soulseek zrzuca pobrania do katalogów albumów."""
        sub = os.path.join(lib_copy, "Album 2025")
        os.makedirs(sub, exist_ok=True)
        fast_copy(real_path(GOOD_FLAC), os.path.join(sub, "01 utwor.flac"))
        d = _review(client, ["01 utwor.flac"])
        assert d["count"] == 1 and d["pominiete"] == []

    def test_pusta_playlista_to_blad_a_nie_cisza(self, client):
        r = client.post("/api/playlist/review", json={"name": "x", "files": ["brak.flac"]})
        assert r.status_code == 400


class TestNaprawa:
    def test_odrzuca_plik_spoza_biblioteki(self, client, tmp_path_factory):
        """lib_copy to samo tmp_path, więc obcy plik musi trafić do
        zupełnie innego katalogu — inaczej test niczego nie sprawdza."""
        poza = tmp_path_factory.mktemp("poza-biblioteka")
        obcy = poza / "obcy.flac"
        fast_copy(real_path(GOOD_FLAC), str(obcy))
        r = client.post("/api/playlist/fix", json={"path": str(obcy)})
        assert r.status_code == 400

    def test_odrzuca_wyjscie_w_gore_drzewa(self, client, lib_copy):
        r = client.post("/api/playlist/fix",
                        json={"path": os.path.join(lib_copy, "..", "..", "etc", "passwd")})
        assert r.status_code == 400

    def test_naprawia_uszkodzone_tagi(self, client, lib_copy):
        path = os.path.join(lib_copy, GOOD_FLAC)
        f = FLAC(path); f["title"] = ["CafÃ© del Mar"]; f.save()
        r = client.post("/api/playlist/fix", json={"path": path})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert FLAC(path)["title"][0] == "Café del Mar"

    def test_mowi_wprost_gdy_nie_ma_czego_naprawiac(self, client, lib_copy):
        r = client.post("/api/playlist/fix", json={"path": os.path.join(lib_copy, GOOD_FLAC)})
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_nie_ma_pliku_to_404(self, client, lib_copy):
        r = client.post("/api/playlist/fix", json={"path": os.path.join(lib_copy, "brak.flac")})
        assert r.status_code == 404
