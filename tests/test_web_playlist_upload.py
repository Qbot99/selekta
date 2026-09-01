"""Wgrywanie playlisty z komputera i wskazywanie folderu z muzyką."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import web
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    web._EXTRA_ROOTS.clear()
    return TestClient(web.app)


class TestWgrywaniePliku:
    def test_m3u_ze_sciezkami_trafia_od_razu_do_mam(self, client, lib_copy):
        """Wpis wskazujący istniejący plik nie wymaga zgadywania."""
        p = os.path.join(lib_copy, GOOD_FLAC)
        tresc = f"#EXTM3U\n#EXTINF:274,Odymel - Gucci\n{p}\n"
        r = client.post("/api/playlist/upload",
                        files={"file": ("set.m3u8", tresc, "audio/x-mpegurl")})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["counts"]["auto"] == 1
        assert d["auto"][0]["from_file"] is True
        assert d["name"] == "set"

    def test_tracklista_bez_sciezek_dopasowuje_sie_do_biblioteki(self, client):
        r = client.post("/api/playlist/upload",
                        files={"file": ("lista.txt", "Odymel - Gucci\n", "text/plain")})
        assert r.status_code == 200
        d = r.json()
        assert d["counts"]["total"] == 1
        assert (d["auto"] or d["resolve"])[0]["file"] == GOOD_FLAC

    def test_pusty_plik_to_czytelny_blad(self, client):
        r = client.post("/api/playlist/upload",
                        files={"file": ("x.m3u", "   ", "text/plain")})
        assert r.status_code == 400

    def test_za_duzy_plik_odrzucony(self, client):
        duzy = "#EXTM3U\n" + ("#EXTINF:1,a - b\n/x.mp3\n" * 400_000)
        r = client.post("/api/playlist/upload",
                        files={"file": ("wielki.m3u", duzy, "text/plain")})
        assert r.status_code == 400
        assert "duży" in r.json()["detail"]


class TestWskazanieSciezki:
    def test_folder_z_muzyka_jako_playlista(self, client, lib_copy):
        r = client.post("/api/playlist/local", json={"path": lib_copy})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["origin"] == "dysk:folder"
        assert d["counts"]["auto"] >= 3
        assert all(x.get("from_file") for x in d["auto"])

    def test_nie_ma_sciezki_to_404(self, client):
        r = client.post("/api/playlist/local", json={"path": "/nie/ma/takiej"})
        assert r.status_code == 404

    def test_pusta_sciezka_to_400(self, client):
        assert client.post("/api/playlist/local", json={"path": ""}).status_code == 400


class TestZaufaneFoldery:
    def test_folder_spoza_biblioteki_dopiero_po_wskazaniu(self, client, tmp_path_factory,
                                                          monkeypatch):
        """Naprawa poza biblioteką jest możliwa TYLKO dla folderu, który
        użytkownik sam wybrał w oknie Findera."""
        from selekta import folderpick
        from tests.conftest import fast_copy, real_path
        poza = tmp_path_factory.mktemp("moja-muzyka")
        plik = str(poza / GOOD_MP3)
        fast_copy(real_path(GOOD_MP3), plik)

        assert client.post("/api/playlist/fix", json={"path": plik}).status_code == 400

        monkeypatch.setattr(folderpick, "available", lambda: True)
        monkeypatch.setattr(folderpick, "choose_folder", lambda prompt="": str(poza))
        r = client.post("/api/pick", json={"what": "folder"})
        assert r.status_code == 200 and r.json()["ok"] is True

        # teraz ten sam plik jest dozwolony
        assert client.post("/api/playlist/fix", json={"path": plik}).status_code != 400

    def test_anulowanie_okna_nie_jest_bledem(self, client, monkeypatch):
        from selekta import folderpick
        def anuluj(prompt=""):
            raise folderpick.PickCancelled("nie wybrano folderu")
        monkeypatch.setattr(folderpick, "available", lambda: True)
        monkeypatch.setattr(folderpick, "choose_folder", anuluj)
        r = client.post("/api/pick", json={"what": "folder"})
        assert r.status_code == 200 and r.json()["cancelled"] is True
