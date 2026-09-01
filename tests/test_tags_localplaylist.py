"""Playlisty z dysku: M3U/PLS/XML rekordboxa/NML Traktora/CSV/tekst.

DJ ma playlisty już na komputerze — wyeksportowane z rekordboxa, Traktora
czy Serato. Kluczowe jest to, że wpis wskazujący na istniejący plik ma dać
gotową ścieżkę: wtedy nie trzeba niczego zgadywać ani pobierać.
"""
from __future__ import annotations

import os

import pytest

from selekta import localplaylist as lp
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def utwory(lib_copy):
    return [os.path.join(lib_copy, GOOD_FLAC), os.path.join(lib_copy, GOOD_MP3)]


def _zapisz(tmp_path, nazwa: str, tresc: str) -> str:
    p = tmp_path / nazwa
    p.write_text(tresc, encoding="utf-8")
    return str(p)


class TestM3U:
    def test_sciezki_bezwzgledne_daja_gotowe_pliki(self, tmp_path, utwory):
        tresc = "#EXTM3U\n" + "".join(
            f"#EXTINF:245,Artysta {i} - Tytuł {i}\n{p}\n" for i, p in enumerate(utwory))
        parsed = lp.from_file(_zapisz(tmp_path, "set.m3u8", tresc))
        assert parsed.kind == "m3u8"
        assert len(parsed.found) == 2
        assert parsed.entries[0].artist == "Artysta 0"
        assert parsed.entries[0].duration_s == 245

    def test_sciezki_wzgledne_liczone_od_pliku_playlisty(self, tmp_path, lib_copy):
        # playlista leży OBOK utworu, więc "plik.flac" ma się rozwiązać
        tresc = f"#EXTM3U\n#EXTINF:245,Ktoś - Utwór\n{GOOD_FLAC}\n"
        p = os.path.join(lib_copy, "lista.m3u")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(tresc)
        parsed = lp.from_file(p)
        assert len(parsed.found) == 1

    def test_brakujacy_plik_nie_dostaje_sciezki(self, tmp_path):
        tresc = "#EXTM3U\n#EXTINF:200,Ktoś - Nie Ma\n/nie/ma/pliku.flac\n"
        parsed = lp.from_file(_zapisz(tmp_path, "x.m3u", tresc))
        assert parsed.entries[0].path is None
        assert parsed.entries[0].title == "Nie Ma"

    def test_bez_extinf_bierze_nazwe_z_pliku(self, tmp_path, utwory):
        parsed = lp.from_file(_zapisz(tmp_path, "goly.m3u", utwory[0] + "\n"))
        assert parsed.entries[0].title
        assert parsed.entries[0].path == utwory[0]

    def test_komentarze_sa_pomijane(self, tmp_path, utwory):
        tresc = f"#EXTM3U\n# jakiś komentarz\n#PLAYLIST:Mój set\n{utwory[0]}\n"
        assert len(lp.from_file(_zapisz(tmp_path, "k.m3u", tresc)).entries) == 1


class TestPozostaleFormaty:
    def test_pls(self, tmp_path, utwory):
        tresc = ("[playlist]\nNumberOfEntries=1\n"
                 f"File1={utwory[0]}\nTitle1=Ktoś - Utwór\nLength1=300\n")
        parsed = lp.from_file(_zapisz(tmp_path, "l.pls", tresc))
        assert parsed.kind == "pls" and len(parsed.found) == 1
        assert parsed.entries[0].duration_s == 300

    def test_xml_rekordboxa(self, tmp_path, utwory):
        import urllib.parse
        loc = "file://localhost" + urllib.parse.quote(utwory[0])
        tresc = ('<?xml version="1.0"?><DJ_PLAYLISTS><COLLECTION>'
                 f'<TRACK Name="Gucci" Artist="Odymel" TotalTime="274" Location="{loc}"/>'
                 '</COLLECTION></DJ_PLAYLISTS>')
        parsed = lp.from_file(_zapisz(tmp_path, "rb.xml", tresc))
        assert parsed.kind == "xml"
        assert parsed.entries[0].artist == "Odymel"
        assert parsed.entries[0].duration_s == 274
        assert parsed.found and parsed.found[0].path == utwory[0]

    def test_nml_traktora_ze_sciezka_dwukropkowa(self, tmp_path, utwory):
        d, n = os.path.split(utwory[0])
        tresc = ('<?xml version="1.0"?><NML><COLLECTION>'
                 f'<ENTRY ARTIST="Odymel" TITLE="Gucci">'
                 f'<LOCATION DIR="{d.replace("/", "/:")}/:" FILE="{n}" VOLUME="Macintosh HD"/>'
                 '<INFO PLAYTIME="274"/></ENTRY></COLLECTION></NML>')
        parsed = lp.from_file(_zapisz(tmp_path, "t.nml", tresc))
        assert parsed.kind == "nml"
        assert parsed.found and parsed.found[0].path == utwory[0]

    def test_csv_z_naglowkiem(self, tmp_path):
        tresc = "name,artist,time\nGucci,Odymel,4:34\nWavey,Eli Brown,3:20\n"
        parsed = lp.from_file(_zapisz(tmp_path, "s.csv", tresc))
        assert [e.artist for e in parsed.entries] == ["Odymel", "Eli Brown"]
        assert parsed.entries[0].duration_s == 274

    def test_csv_z_tabulatorami(self, tmp_path):
        tresc = "artist\ttitle\nOdymel\tGucci\n"
        parsed = lp.from_file(_zapisz(tmp_path, "s.csv", tresc))
        assert parsed.entries[0].title == "Gucci"

    def test_zwykly_tekst(self, tmp_path):
        parsed = lp.from_file(_zapisz(tmp_path, "lista.txt", "Odymel - Gucci\nEli Brown - Wavey\n"))
        assert len(parsed.entries) == 2

    def test_folder_jako_playlista(self, lib_copy):
        parsed = lp.from_folder(lib_copy)
        assert parsed.kind == "folder"
        assert len(parsed.found) == len(parsed.entries) >= 3


class TestRozpoznawanieTypu:
    @pytest.mark.parametrize("tresc,oczekiwany", [
        ("#EXTM3U\n#EXTINF:1,a - b\n", "m3u"),
        ("[playlist]\nFile1=x\n", "pls"),
        ('<?xml version="1.0"?><DJ_PLAYLISTS/>', "xml"),
        ('<NML VERSION="19"/>', "nml"),
    ])
    def test_po_tresci_gdy_nazwa_nic_nie_mowi(self, tresc, oczekiwany):
        assert lp.sniff(tresc, "bez-rozszerzenia") == oczekiwany

    def test_rozszerzenie_ma_pierwszenstwo(self):
        assert lp.sniff("Odymel - Gucci", "lista.m3u8") == "m3u8"
