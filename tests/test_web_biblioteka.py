"""Zarządzanie biblioteką z poziomu apki: dodawanie, usuwanie, podgląd.

Kluczowa obietnica: usunięcie NIE kasuje pliku, tylko przenosi go do kosza.
Pomyłka w bibliotece DJ-a jest nieodwracalna, plik w koszu kosztuje miejsce.
"""
from __future__ import annotations

import io
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from selekta import decyzje, web
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


class TestUsuwanieDoKosza:
    def test_usuniety_plik_trafia_do_kosza(self, client, lib_copy):
        r = client.post("/api/tracks/usun", json={"file": GOOD_MP3})
        assert r.status_code == 200, r.text
        d = r.json()
        assert not os.path.exists(os.path.join(lib_copy, GOOD_MP3))
        assert os.path.isfile(d["w_koszu"]), "plik musi istnieć w koszu"
        assert decyzje.KOSZ in d["w_koszu"]

    def test_przywrocenie_cofa_usuniecie(self, client, lib_copy):
        d = client.post("/api/tracks/usun", json={"file": GOOD_MP3}).json()
        r = client.post("/api/tracks/przywroc", json={"w_koszu": d["w_koszu"]})
        assert r.status_code == 200, r.text
        assert os.path.isfile(os.path.join(lib_copy, GOOD_MP3))

    def test_nie_da_sie_usunac_spoza_biblioteki(self, client):
        r = client.post("/api/tracks/usun", json={"file": "../../../etc/hosts"})
        assert r.status_code == 400

    def test_przywrocenie_spoza_biblioteki_odrzucone(self, client,
                                                     tmp_path_factory):
        # UWAGA: lib_copy leży w tym samym tmp_path, więc katalog „obcy”
        # musi pochodzić z osobnego korzenia — inaczej test niczego nie bada
        obcy_dir = tmp_path_factory.mktemp("poza-biblioteka")
        obcy = obcy_dir / "obcy.flac"
        obcy.write_bytes(b"x")
        r = client.post("/api/tracks/przywroc", json={"w_koszu": str(obcy)})
        assert r.status_code == 400

    def test_przywrocenie_nie_nadpisuje_istniejacego(self, client, lib_copy):
        d = client.post("/api/tracks/usun", json={"file": GOOD_MP3}).json()
        # ktoś w międzyczasie wstawił plik o tej samej nazwie
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC),
                     os.path.join(lib_copy, GOOD_MP3))
        r = client.post("/api/tracks/przywroc", json={"w_koszu": d["w_koszu"]})
        assert r.status_code == 409


class TestDodawanie:
    def test_dodaje_plik_audio(self, client, lib_copy):
        dane = open(os.path.join(lib_copy, GOOD_MP3), "rb").read()
        r = client.post("/api/tracks/dodaj",
                        files={"file": ("nowy-utwor.mp3", io.BytesIO(dane),
                                        "audio/mpeg")})
        assert r.status_code == 200, r.text
        assert os.path.isfile(os.path.join(lib_copy, "nowy-utwor.mp3"))

    def test_odrzuca_plik_nieaudio(self, client):
        r = client.post("/api/tracks/dodaj",
                        files={"file": ("notatka.txt", io.BytesIO(b"tekst"),
                                        "text/plain")})
        assert r.status_code == 400
        assert "audio" in r.json()["detail"]

    def test_odrzuca_pusty_plik(self, client, lib_copy):
        r = client.post("/api/tracks/dodaj",
                        files={"file": ("pusty.mp3", io.BytesIO(b""), "audio/mpeg")})
        assert r.status_code == 400
        assert not os.path.exists(os.path.join(lib_copy, "pusty.mp3"))

    def test_nie_nadpisuje_istniejacego(self, client, lib_copy):
        oryginal = os.path.join(lib_copy, GOOD_MP3)
        rozmiar = os.path.getsize(oryginal)
        r = client.post("/api/tracks/dodaj",
                        files={"file": (GOOD_MP3, io.BytesIO(b"\x00" * 64),
                                        "audio/mpeg")})
        assert r.status_code == 200
        assert os.path.getsize(oryginal) == rozmiar, "oryginał nietknięty"
        assert r.json()["file"] != GOOD_MP3, "kopia dostaje inną nazwę"

    def test_dodaje_ze_sciezki(self, client, lib_copy, tmp_path_factory):
        zrodlo = tmp_path_factory.mktemp("zrodlo") / "z-dysku.flac"
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC), zrodlo)
        r = client.post("/api/tracks/dodaj-sciezke", json={"path": str(zrodlo)})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1
        assert os.path.isfile(os.path.join(lib_copy, "z-dysku.flac"))

    def test_sciezka_bez_audio_to_czytelny_blad(self, client, tmp_path_factory):
        pusty = tmp_path_factory.mktemp("bez-audio")
        (pusty / "nic.txt").write_text("nic")
        r = client.post("/api/tracks/dodaj-sciezke", json={"path": str(pusty)})
        assert r.status_code == 400


class TestOdpornoscNaUszkodzone:
    """Przerwane pobieranie zostawia plik-ogryzek. Nie może wywalić apki."""

    def test_uszkodzony_plik_nie_psuje_listowania(self, client, lib_copy):
        zepsuty = os.path.join(lib_copy, "ogryzek.flac")
        with open(zepsuty, "wb") as fh:
            fh.write(b"fLaC" + b"\x00" * 40)     # sam nagłówek, reszta śmieci
        r = client.get("/api/tracks")
        assert r.status_code == 200, "listowanie musi przetrwać"
        wiersze = {t["file"]: t for t in r.json()["tracks"]}
        assert "ogryzek.flac" in wiersze
        assert wiersze["ogryzek.flac"]["uszkodzony"] is True

    def test_zdrowy_plik_nie_jest_oznaczony(self, client):
        r = client.get("/api/tracks")
        zdrowe = [t for t in r.json()["tracks"] if t["file"] == GOOD_FLAC]
        assert zdrowe and zdrowe[0]["uszkodzony"] is False


class TestOdtwarzanie:
    def test_zwraca_audio_z_obsluga_zakresu(self, client):
        r = client.get(f"/api/audio?file={GOOD_MP3}", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
        assert r.headers["accept-ranges"] == "bytes"
        assert len(r.content) == 100

    def test_bez_zakresu_oddaje_calosc(self, client, lib_copy):
        r = client.get(f"/api/audio?file={GOOD_MP3}")
        assert r.status_code == 200
        assert len(r.content) == os.path.getsize(os.path.join(lib_copy, GOOD_MP3))

    def test_nie_wypuszcza_plikow_spoza_biblioteki(self, client):
        r = client.get("/api/audio?file=../../../etc/hosts")
        assert r.status_code == 400
