"""„Dociągnij okładkę” — regresje z przeglądu 0.4.2 (iTunes podstawiony atrapą).

Przed naprawą: artysta i tytuł brane z NAZWY pliku nadpisywały poprawne tagi
(„Linds” → „Kick It”), iTunes dopasowywany tylko po tytule (plik Lindsa dostał
okładkę Natashy Bedingfield), istniejąca okładka podmieniana bez pytania, M4A
kończył się błędem 500, a CLI `covers --fill` przerywało pętlę na pierwszym M4A.
"""
from __future__ import annotations

import os

import pytest

from selekta import covers, health
from tests.syntetyczne import obraz, utwor

JPEG_ITUNES = b"\xff\xd8\xff\xe0" + b"okladka-z-itunes" * 50


class _Odp:
    def __init__(self, dane=None, content=b"", ok=True):
        self._dane, self.content, self.ok = dane, content, ok

    def json(self):
        return self._dane


@pytest.fixture()
def itunes(monkeypatch):
    """Atrapa iTunes: wyniki ustawiane w teście, pytania zapisywane."""
    stan = {"wyniki": [], "pytania": []}

    def get(url, headers=None, timeout=None):
        if "itunes.apple.com/search" in url:
            stan["pytania"].append(url)
            return _Odp({"results": stan["wyniki"]})
        return _Odp(content=JPEG_ITUNES)

    monkeypatch.setattr(covers.requests, "get", get)
    return stan


def _wynik(artysta, tytul, sekund=6):
    return {"artistName": artysta, "trackName": tytul, "collectionName": "Album",
            "trackTimeMillis": int(sekund * 1000),
            "artworkUrl100": "https://is1.example/100x100bb.jpg"}


def test_okladka_innego_wykonawcy_o_tym_samym_tytule_odrzucona(tmp_path, itunes):
    p = utwor(str(tmp_path / "Kick It.flac"), "Linds", "Kick It")
    itunes["wyniki"] = [_wynik("Natasha Bedingfield", "Kick It (Acoustic)")]
    w = covers.uzupelnij(p)
    assert w["status"] == "brak"
    assert covers.embedded_art(p) is None


def test_tagi_artysty_i_tytulu_zostaja_nietkniete(tmp_path, itunes):
    # nazwa pliku małymi literami i bez artysty — szukamy po TAGACH
    p = utwor(str(tmp_path / "kick it.flac"), "Linds", "Kick It")
    itunes["wyniki"] = [_wynik("Natasha Bedingfield", "Kick It"), _wynik("Linds", "Kick It")]
    w = covers.uzupelnij(p)
    assert w["status"] == "dodano", w
    assert "Linds" in w["opis"]
    assert health.czytaj_tagi(p) == ("Linds", "Kick It")
    assert covers.embedded_art(p) == JPEG_ITUNES
    assert "Linds" in itunes["pytania"][0]


def test_istniejaca_okladka_nie_jest_podmieniana(tmp_path, itunes):
    stara = obraz("jpg", "blue")
    p = utwor(str(tmp_path / "Odymel - Hot Stuff.mp3"), "Odymel", "Hot Stuff", okladka=stara)
    itunes["wyniki"] = [_wynik("Odymel", "Hot Stuff")]
    w = covers.uzupelnij(p)
    assert w["status"] == "jest"
    assert covers.embedded_art(p) == stara
    assert itunes["pytania"] == []          # nawet nie pytamy iTunes


def test_m4a_dostaje_okladke_i_jest_widoczny(tmp_path, itunes):
    p = utwor(str(tmp_path / "1.16 . Urszula Sipińska . Mam Cudownych Rodziców.m4a"),
              "Urszula Sipińska", "Mam Cudownych Rodziców")
    assert health.czytaj_tagi(p) == ("Urszula Sipińska", "Mam Cudownych Rodziców")
    itunes["wyniki"] = [_wynik("Urszula Sipińska", "Mam cudownych rodziców")]
    w = covers.uzupelnij(p)
    assert w["status"] == "dodano", w
    assert covers.embedded_art(p) == JPEG_ITUNES


def test_m4a_z_okladka_nie_jest_bez_okladki(tmp_path):
    png = obraz("png")
    p = utwor(str(tmp_path / "a.m4a"), "A", "B", okladka=png)
    assert covers.embedded_art(p) == png
    assert covers.mime_obrazu(png) == "image/png"


def test_czas_trwania_odrzuca_inny_utwor_o_tej_samej_nazwie(tmp_path, itunes):
    p = utwor(str(tmp_path / "Asia - Heat of the Moment.flac"), "Asia", "Heat of the Moment",
              sekund=6)
    itunes["wyniki"] = [_wynik("Asia", "Heat of the Moment", sekund=240)]
    assert covers.uzupelnij(p)["status"] == "brak"


def test_kopia_w_secie_dostaje_te_sama_okladke(tmp_path, itunes):
    from tests.syntetyczne import kopia
    p = utwor(str(tmp_path / "lib" / "Linds - Kick It.wav"), "Linds", "Kick It")
    k = kopia(p, str(tmp_path / "lib" / "set" / "Linds - Kick It.wav"))
    itunes["wyniki"] = [_wynik("Linds", "Kick It")]
    w = covers.uzupelnij(p, kopie=[k])
    assert w["status"] == "dodano" and w["kopii"] == 1
    assert covers.embedded_art(k) == JPEG_ITUNES


def test_analizy_przetrwaja_dodanie_okladki(tmp_path, itunes):
    from selekta import cache
    p = utwor(str(tmp_path / "Linds - Kick It.flac"), "Linds", "Kick It")
    cache.put(p, "harmonic", {"bpm": 128.0, "camelot": "8A"})
    itunes["wyniki"] = [_wynik("Linds", "Kick It")]
    assert covers.uzupelnij(p)["status"] == "dodano"
    assert cache.get(p, "harmonic") == {"bpm": 128.0, "camelot": "8A"}


def test_api_m4a_bez_bledu_500_i_409_przy_istniejacej(tmp_path, itunes):
    from fastapi.testclient import TestClient
    from selekta import web
    lib = tmp_path / "lib"
    utwor(str(lib / "Asia - Heat of the Moment.m4a"), "Asia", "Heat of the Moment")
    utwor(str(lib / "Ma - Okladke.mp3"), "Ma", "Okladke", okladka=obraz())
    web.set_folder(str(lib))
    c = TestClient(web.app)
    itunes["wyniki"] = [_wynik("Asia", "Heat of the Moment")]
    r = c.post("/api/covers/fill", params={"file": "Asia - Heat of the Moment.m4a"})
    assert r.status_code == 200, r.text
    r = c.post("/api/covers/fill", params={"file": "Ma - Okladke.mp3"})
    assert r.status_code == 409
    t = {x["file"]: x for x in c.get("/api/tracks").json()["tracks"]}
    m4a = t["Asia - Heat of the Moment.m4a"]
    assert (m4a["artist"], m4a["title"], m4a["has_cover"]) == ("Asia", "Heat of the Moment", True)
    r = c.get("/api/cover", params={"file": "Ma - Okladke.mp3"})
    assert r.headers["content-type"] == "image/jpeg"


def test_cli_covers_fill_nie_przerywa_petli(tmp_path, itunes, capsys, monkeypatch):
    from selekta import cli
    lib = tmp_path / "lib"
    utwor(str(lib / "A - Pierwszy.m4a"), "A", "Pierwszy")
    utwor(str(lib / "B - Drugi.mp3"), "B", "Drugi")
    p3 = utwor(str(lib / "C - Trzeci.flac"), "C", "Trzeci")
    itunes["wyniki"] = [_wynik("A", "Pierwszy"), _wynik("Bebe", "Drugi"), _wynik("C", "Trzeci")]

    def boom(path, cover):
        if path.endswith(".m4a"):
            raise ValueError("unsupported format: .m4a")
        from selekta import tagger
        tagger._zapisz(path, None, None, cover)
    monkeypatch.setattr("selekta.tagger.zapisz_okladke", boom)
    monkeypatch.setattr("sys.argv", ["selekta", "covers", "--folder", str(lib), "--fill"])
    cli.main()
    out = capsys.readouterr().out
    assert "C - Trzeci.flac" in out and "unsupported" in out
    assert covers.embedded_art(p3) == JPEG_ITUNES


def test_wielu_artystow_na_liscie(tmp_path):
    from mutagen.flac import FLAC
    p = utwor(str(tmp_path / "x.flac"), "Maddix", "Ritmo")
    a = FLAC(p)
    a["ARTIST"] = ["Maddix", "Feles"]
    a.save()
    assert health.czytaj_tagi(p) == ("Maddix, Feles", "Ritmo")
