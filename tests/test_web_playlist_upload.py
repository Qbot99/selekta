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


# --------------------------------------------------------------------------
# Przegląd 0.4.2: eksport .txt z rekordboxa (UTF-16, tabulatory) → 400,
# a pełny XML kolekcji wczytywał wszystkie utwory bez wyboru playlisty.

_RB_TXT = ("#\tArtwork\tTrack Title\tArtist\tAlbum\tGenre\tBPM\tRating\tTime\tKey\tDate Added\r\n"
           "1\t\tGucci\tOdymel\t\tTechno\t146.00\t\t04:34\t8A\t2026-09-01\r\n"
           "2\t\tHung Up\tMadonna\tConfessions\tPop\t125.00\t\t05:37\t5A\t2026-09-01\r\n")


@pytest.mark.parametrize("kodowanie,nazwa", [
    ("utf-16", "playlista.txt"), ("utf-8", "playlista.txt"), ("utf-8", "playlista.csv")])
def test_eksport_txt_z_rekordboxa(client, kodowanie, nazwa):
    r = client.post("/api/playlist/upload",
                    files={"file": (nazwa, _RB_TXT.encode(kodowanie), "text/plain")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["counts"]["total"] == 2
    assert d["auto"][0]["file"] == GOOD_FLAC
    assert {(x["artist"], x["title"], x["duration"]) for x in d["missing"]} == {
        ("Madonna", "Hung Up", 337)}


_RB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="rekordbox"/>
<COLLECTION Entries="5">
  <TRACK TrackID="1" Name="Gucci" Artist="Odymel" TotalTime="274" Location="file://localhost/nie/ma/Odymel%20-%20Gucci.flac"/>
  <TRACK TrackID="2" Name="Hung Up" Artist="Madonna" TotalTime="337" Location="file://localhost/x/2.flac"/>
  <TRACK TrackID="3" Name="Sorry" Artist="Madonna" TotalTime="282" Location="file://localhost/x/3.flac"/>
  <TRACK TrackID="4" Name="Frozen" Artist="Madonna" TotalTime="372" Location="file://localhost/x/4.flac"/>
  <TRACK TrackID="5" Name="Jump" Artist="Madonna" TotalTime="238" Location="file://localhost/x/5.flac"/>
</COLLECTION>
<PLAYLISTS><NODE Type="0" Name="ROOT" Count="2">
  <NODE Name="Warm-up" Type="1" KeyType="0" Entries="2"><TRACK Key="4"/><TRACK Key="2"/></NODE>
  <NODE Name="Sety" Type="0" Count="1">
    <NODE Name="Peak" Type="1" KeyType="0" Entries="1"><TRACK Key="1"/></NODE>
  </NODE>
</NODE></PLAYLISTS></DJ_PLAYLISTS>"""


def test_pelny_xml_rekordboxa_pyta_o_playliste(client):
    r = client.post("/api/playlist/upload",
                    files={"file": ("kolekcja.xml", _RB_XML, "text/xml")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["wybor_playlisty"] == [{"name": "Warm-up", "count": 2},
                                    {"name": "Sety / Peak", "count": 1}]
    assert "auto" not in d
    r = client.post("/api/playlist/upload", params={"playlista": "Warm-up"},
                    files={"file": ("kolekcja.xml", _RB_XML, "text/xml")})
    d = r.json()
    # kolejność playlisty, nie kolekcji; tylko jej utwory
    wiersze = d["auto"] + d["resolve"] + d["missing"]
    assert sorted((x["title"]) for x in wiersze) == ["Frozen", "Hung Up"]
    assert d["name"] == "Warm-up" and d["counts"]["total"] == 2
    r = client.post("/api/playlist/upload", params={"playlista": "Sety / Peak"},
                    files={"file": ("kolekcja.xml", _RB_XML, "text/xml")})
    assert r.json()["auto"][0]["file"] == GOOD_FLAC


def test_xml_z_jedna_playlista_bez_pytania(client, tmp_path):
    jedna = _RB_XML.replace('<NODE Name="Sety" Type="0" Count="1">', '<!--').replace(
        '</NODE>\n</NODE></PLAYLISTS>', '--></NODE></PLAYLISTS>')
    from selekta import localplaylist
    e = localplaylist.parse_text(jedna, "xml")
    assert [x.title for x in e] == ["Frozen", "Hung Up"]
    p = tmp_path / "jedna.xml"
    p.write_text(_RB_XML, encoding="utf-8")
    r = client.post("/api/playlist/local", json={"path": str(p), "playlista": "Warm-up"})
    assert r.status_code == 200 and r.json()["counts"]["total"] == 2
