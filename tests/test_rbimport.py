"""Round-trip z rekordboxem — ręczna praca użytkownika wygrywa.

Sedno: hot cue postawione na CDJ-u, kolory, oceny i komentarze istnieją
tylko dlatego, że ktoś je ustawił. Eksport ma je oddać nietknięte, a nie
zastąpić własnym wyliczeniem.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from urllib.parse import quote

import pytest

from selekta import dj_export, rbimport
from tests.conftest import GOOD_FLAC, GOOD_MP3


def _xml_rekordboxa(tmp_path, sciezka_utworu, **nadpisz):
    atrybuty = {
        "Name": "Wavey", "Artist": "Eli Brown", "AverageBpm": "145.00",
        "Tonality": "6B", "Colour": "0xFF007F", "Rating": "204",
        "PlayCount": "17", "Comments": "wchodzi zawsze",
    }
    atrybuty.update(nadpisz)
    attr = " ".join(f'{k}="{v}"' for k, v in atrybuty.items() if v is not None)
    loc = "file://localhost" + quote(str(sciezka_utworu), safe="/")
    plik = tmp_path / "rekordbox.xml"
    plik.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="rekordbox" Version="6.7.7"/>
<COLLECTION Entries="1">
<TRACK TrackID="1" {attr} Location="{loc}">
  <TEMPO Inizio="1.793" Bpm="145.00" Metro="4/4" Battito="1"/>
  <POSITION_MARK Name="wejscie" Type="0" Start="7.012" Num="0"
                 Red="40" Green="226" Blue="20"/>
  <POSITION_MARK Name="drop" Type="0" Start="27.307" Num="1"/>
  <POSITION_MARK Name="petla" Type="4" Start="60.000" End="66.620" Num="2"/>
  <POSITION_MARK Name="" Type="0" Start="1.793" Num="-1"/>
</TRACK></COLLECTION></DJ_PLAYLISTS>''', encoding="utf-8")
    return str(plik)


class TestCzytanieXml:
    def test_czyta_wszystkie_pola(self, tmp_path, lib_copy):
        plik = os.path.join(lib_copy, GOOD_FLAC)
        w = rbimport.wczytaj_xml(_xml_rekordboxa(tmp_path, plik))[0]
        assert w.artist == "Eli Brown" and w.title == "Wavey"
        assert w.bpm == 145.0 and w.tonality == "6B"
        assert w.kolor == "0xFF007F" and w.ocena == 204 and w.odtworzen == 17
        assert w.komentarz == "wchodzi zawsze"
        assert w.first_beat_s == 1.793

    def test_rozroznia_hot_cue_od_memory_cue(self, tmp_path, lib_copy):
        w = rbimport.wczytaj_xml(
            _xml_rekordboxa(tmp_path, os.path.join(lib_copy, GOOD_FLAC)))[0]
        hot = [z for z in w.znaczniki if z.hot]
        pamieciowe = [z for z in w.znaczniki if not z.hot]
        assert len(hot) == 3 and len(pamieciowe) == 1
        assert [z.etykieta for z in hot] == ["hot cue A", "hot cue B", "hot cue C"]

    def test_czyta_petle_z_koncem(self, tmp_path, lib_copy):
        w = rbimport.wczytaj_xml(
            _xml_rekordboxa(tmp_path, os.path.join(lib_copy, GOOD_FLAC)))[0]
        petla = next(z for z in w.znaczniki if z.typ == "4")
        assert petla.start_s == 60.0 and petla.koniec_s == 66.62

    def test_czyta_kolor_znacznika(self, tmp_path, lib_copy):
        w = rbimport.wczytaj_xml(
            _xml_rekordboxa(tmp_path, os.path.join(lib_copy, GOOD_FLAC)))[0]
        assert w.znaczniki[1].kolor == "#28E214"      # 40,226,20

    def test_wykrywa_brak_recznej_pracy(self, tmp_path, lib_copy):
        goly = tmp_path / "goly.xml"
        loc = "file://localhost" + quote(os.path.join(lib_copy, GOOD_FLAC), safe="/")
        goly.write_text(f'''<?xml version="1.0"?><DJ_PLAYLISTS Version="1.0.0">
<COLLECTION Entries="1"><TRACK TrackID="1" Name="X" Artist="Y"
 Location="{loc}"/></COLLECTION></DJ_PLAYLISTS>''', encoding="utf-8")
        assert rbimport.wczytaj_xml(str(goly))[0].ma_reczna_prace is False


class TestScalanie:
    def test_dopasowuje_po_sciezce(self, tmp_path, lib_copy, monkeypatch):
        monkeypatch.setattr(rbimport, "PLIK", str(tmp_path / "stan.json"))
        monkeypatch.setattr(rbimport.config, "STATE_DIR", str(tmp_path))
        plik = os.path.join(lib_copy, GOOD_FLAC)
        r = rbimport.scal(_xml_rekordboxa(tmp_path, plik), lib_copy)
        assert r["dopasowane"] == 1 and r["z_reczna_praca"] == 1
        assert rbimport.dla_pliku(plik)["ocena"] == 204

    def test_zglasza_nieodnalezione(self, tmp_path, lib_copy, monkeypatch):
        monkeypatch.setattr(rbimport, "PLIK", str(tmp_path / "stan.json"))
        monkeypatch.setattr(rbimport.config, "STATE_DIR", str(tmp_path))
        r = rbimport.scal(_xml_rekordboxa(tmp_path, "/nie/ma/pliku.flac"), lib_copy)
        assert r["dopasowane"] == 0 and r["nieodnalezionych"] == 1

    def test_dopasowuje_po_nazwie_gdy_sciezka_sie_zmienila(self, tmp_path,
                                                           lib_copy, monkeypatch):
        """Biblioteka mogła się przenieść — nazwa pliku wystarczy."""
        monkeypatch.setattr(rbimport, "PLIK", str(tmp_path / "stan.json"))
        monkeypatch.setattr(rbimport.config, "STATE_DIR", str(tmp_path))
        stara = os.path.join("/gdzies/indziej", GOOD_FLAC)
        r = rbimport.scal(_xml_rekordboxa(tmp_path, stara), lib_copy)
        assert r["dopasowane"] == 1

    def test_zapomnij_kasuje_wpis(self, tmp_path, lib_copy, monkeypatch):
        monkeypatch.setattr(rbimport, "PLIK", str(tmp_path / "stan.json"))
        monkeypatch.setattr(rbimport.config, "STATE_DIR", str(tmp_path))
        plik = os.path.join(lib_copy, GOOD_FLAC)
        rbimport.scal(_xml_rekordboxa(tmp_path, plik), lib_copy)
        assert rbimport.wyczysc(plik) == 1
        assert rbimport.dla_pliku(plik) is None


class TestRecznaPracaWygrywa:
    """Najważniejsza własność całego round-tripu."""

    def _eksportuj(self, tmp_path, **dane):
        track = {"path": str(tmp_path / "u.flac"), "title": "T", "artist": "A",
                 "duration_s": 200.0, "bpm": 145.0, "key": "6B",
                 "intro_end_s": 32.0, "drop_s": 64.0, "outro_start_s": 180.0}
        track.update(dane)
        out = str(tmp_path / "set.xml")
        dj_export.to_rekordbox_xml([track], "set", out)
        return ET.parse(out).getroot().find(".//COLLECTION/TRACK")

    def test_reczne_cue_zastepuja_wyliczone(self, tmp_path):
        el = self._eksportuj(tmp_path, znaczniki=[
            {"start_s": 7.012, "num": 0, "typ": "0", "nazwa": "wejscie"},
            {"start_s": 60.0, "num": 2, "typ": "4", "nazwa": "petla",
             "koniec_s": 66.62}])
        marki = el.findall("POSITION_MARK")
        assert len(marki) == 2, "nasze intro/drop/outro nie mogą się dokleić"
        assert marki[0].get("Name") == "wejscie"
        assert marki[1].get("End") == "66.620"

    def test_bez_recznych_uzywamy_wlasnych(self, tmp_path):
        nazwy = {m.get("Name") for m in self._eksportuj(tmp_path).findall("POSITION_MARK")}
        assert nazwy == {"intro", "drop", "outro"}

    def test_kolor_ocena_i_komentarz_przechodza(self, tmp_path):
        el = self._eksportuj(tmp_path, kolor="0xFF007F", ocena=204,
                             odtworzen=17, komentarz="wchodzi zawsze")
        assert el.get("Colour") == "0xFF007F"
        assert el.get("Rating") == "204" and el.get("PlayCount") == "17"
        assert el.get("Comments") == "wchodzi zawsze"

    def test_kolor_znacznika_wraca_jako_rgb(self, tmp_path):
        el = self._eksportuj(tmp_path, znaczniki=[
            {"start_s": 7.0, "num": 0, "typ": "0", "nazwa": "x",
             "kolor": "#28E214"}])
        m = el.find("POSITION_MARK")
        assert (m.get("Red"), m.get("Green"), m.get("Blue")) == ("40", "226", "20")

    def test_pusta_lista_znacznikow_to_nie_reczna_praca(self, tmp_path):
        nazwy = {m.get("Name")
                 for m in self._eksportuj(tmp_path, znaczniki=[]).findall("POSITION_MARK")}
        assert nazwy == {"intro", "drop", "outro"}
