"""„Sprawdź wszystkie”: tagi z nazw plików (tylko puste pola, z cofaniem) i okładki."""
from __future__ import annotations

import os
import shutil

import pytest
from mutagen import File as MutagenFile

from selekta import health, porzadek
from tests.conftest import GOOD_FLAC


@pytest.mark.parametrize("stem, oczekiwane", [
    ("055f8a1ba1 - Anabel Englund - Get Busy [Ultra Records]", "Anabel Englund - Get Busy"),
    ("Benson - How I Like It (Official Lyric Video) [Ultra Records]", "Benson - How I Like It"),
    ("MEDUZA - Bad Memories ( Seaven Bootleg )", "MEDUZA - Bad Memories (Seaven Bootleg)"),
    ("Anabel Englund - So Hot (MK Remix) [Official Video]", "Anabel Englund - So Hot (MK Remix)"),
])
def test_oczysc_nazwe(stem, oczekiwane):
    assert porzadek.oczysc_nazwe(stem) == (oczekiwane, True)


def test_nazwa_z_youtube_sie_nie_nadaje():
    assert porzadek.oczysc_nazwe("YTDown.com YouTube WORKI Media lJLNGw0HsJ4 008 128k")[1] is False


@pytest.fixture
def plik(tmp_path, lib_copy, monkeypatch):
    monkeypatch.setattr(porzadek, "DZIENNIK", str(tmp_path / "dziennik.json"))
    lib = tmp_path / "lib"
    lib.mkdir()

    def zrob(nazwa, artist=None, title=None):
        p = str(lib / nazwa)
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC), p)
        a = MutagenFile(p)
        a.delete()
        a.clear_pictures()
        if artist:
            a["ARTIST"] = [artist]
        if title:
            a["TITLE"] = [title]
        a.save()
        return p
    return str(lib), zrob


def test_uzupelnia_tylko_puste_pola_i_cofa(plik, monkeypatch):
    lib, zrob = plik
    monkeypatch.setattr(porzadek.matcher, "_file_tokens", lambda p: ([], 200.0))
    pusty = zrob("0a1b2c3d4e - Anabel Englund - Get Busy [Ultra Records].flac")
    z_artysta = zrob("Ktos Inny - Cos.flac", artist="Prawdziwy Artysta")
    niepewny = zrob("Aquagen Hard To Say Im Sorry.flac")
    w = porzadek.uzupelnij_tagi(lib)
    assert w["zapisane"] == 2
    assert health.czytaj_tagi(pusty) == ("Anabel Englund", "Get Busy")
    assert health.czytaj_tagi(z_artysta) == ("Prawdziwy Artysta", "Cos")   # artysta nietknięty
    assert health.czytaj_tagi(niepewny) == ("", "")                        # bez separatora: nie ruszamy
    assert porzadek.cofnij_tagi()["przywrocone"] == 2
    assert health.czytaj_tagi(pusty) == ("", "")
    assert health.czytaj_tagi(z_artysta)[0] == "Prawdziwy Artysta"


def test_powtorzony_artysta_i_krotki_efekt(plik, monkeypatch):
    lib, zrob = plik
    p = zrob("Delerium - Delerium - Silence.flac")
    monkeypatch.setattr(porzadek.matcher, "_file_tokens", lambda x: ([], 200.0))
    pr = porzadek.propozycja(p)
    assert (pr["artist"], pr["title"]) == ("Delerium", "Silence") and not pr["pewne"]
    efekt = zrob("Windows XP - Error Sound.flac")
    monkeypatch.setattr(porzadek.matcher, "_file_tokens", lambda x: ([], 3.0))
    assert porzadek.propozycja(efekt)["pewne"] is False


def test_okladki_tylko_dla_plikow_bez_okladki_i_bez_czekania_w_testach(plik, monkeypatch):
    lib, zrob = plik
    zrob("A - B.flac", "A", "B")
    wolane = []
    monkeypatch.setattr(porzadek.time, "sleep", lambda s: None)
    monkeypatch.setattr(porzadek.covers, "uzupelnij",
                        lambda p, kopie=None: wolane.append(p) or {"status": "brak", "opis": ""})
    w = porzadek.uzupelnij_okladki(lib)
    assert len(wolane) == 1 and w["dodane"] == 0 and w["brak"] == ["A - B.flac"]


def test_flac_z_samym_artysta_ma_artyste(plik):
    """Regresja: Vorbis rzucał ValueError na „©nam” i cały plik był „bez tagów”."""
    lib, zrob = plik
    assert health.czytaj_tagi(zrob("X - Y.flac", artist="Tylko Artysta")) == ("Tylko Artysta", "")
