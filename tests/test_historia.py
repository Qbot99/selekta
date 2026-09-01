"""Historia sesji — co naprawdę poszło na parkiet.

Metryka „martwy balast" ma sens tylko wtedy, gdy wiadomo, co zagrałeś.
Bez historii to przeczucie, nie liczba.
"""
from __future__ import annotations

import os
from urllib.parse import quote

import pytest

from selekta import historia
from tests.conftest import GOOD_FLAC, GOOD_MP3


def _xml(tmp_path, lib_copy, playlisty: str, extra_tracks: str = "") -> str:
    def loc(p):
        return "file://localhost" + quote(p, safe="/")
    kolekcja = "".join(
        f'<TRACK TrackID="{i+1}" Name="U{i}" Artist="A{i}" Location="{loc(os.path.join(lib_copy, n))}"/>'
        for i, n in enumerate((GOOD_FLAC, GOOD_MP3)))
    plik = tmp_path / "rb.xml"
    plik.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="rekordbox" Version="6.7.7"/>
<COLLECTION Entries="2">{kolekcja}{extra_tracks}</COLLECTION>
<PLAYLISTS><NODE Type="0" Name="ROOT">{playlisty}</NODE></PLAYLISTS>
</DJ_PLAYLISTS>''', encoding="utf-8")
    return str(plik)


@pytest.fixture(autouse=True)
def _izoluj(tmp_path, monkeypatch):
    monkeypatch.setattr(historia, "PLIK", str(tmp_path / "historia.json"))
    monkeypatch.setattr(historia.config, "STATE_DIR", str(tmp_path))


class TestRozpoznawanieDaty:
    @pytest.mark.parametrize("nazwa,oczekiwana", [
        ("2026-08-31", "2026-08-31"),
        ("2026_08_31", "2026-08-31"),
        ("31.08.2026", "2026-08-31"),
        ("Luzztro 2026-08-31 (2)", "2026-08-31"),
        ("2026-8-5", "2026-08-05"),
    ])
    def test_wyciaga_date(self, nazwa, oczekiwana):
        assert historia.rozpoznaj_date(nazwa) == oczekiwana

    @pytest.mark.parametrize("nazwa", ["bez daty", "", "2026-13-01", "2026-01-45"])
    def test_odrzuca_bledne(self, nazwa):
        assert historia.rozpoznaj_date(nazwa) == ""


class TestWyciaganieSesji:
    def test_playlista_z_data_to_sesja(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-08-31"><TRACK Key="1"/></NODE>')
        s = historia.wczytaj_sesje(xml, lib_copy)
        assert len(s) == 1 and s[0].data == "2026-08-31"

    def test_folder_history_liczy_sie_bez_daty(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="0" Name="HISTORY">'
                   '<NODE Type="1" Name="piatek"><TRACK Key="1"/></NODE></NODE>')
        assert len(historia.wczytaj_sesje(xml, lib_copy)) == 1

    def test_zwykla_playlista_nie_jest_sesja(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="Ulubione"><TRACK Key="1"/></NODE>')
        assert historia.wczytaj_sesje(xml, lib_copy) == []

    def test_opcja_bierze_wszystkie_playlisty(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="Ulubione"><TRACK Key="1"/></NODE>')
        assert len(historia.wczytaj_sesje(xml, lib_copy,
                                          wszystkie_playlisty=True)) == 1

    def test_kolejnosc_utworow_jest_zachowana(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-08-31">'
                   '<TRACK Key="2"/><TRACK Key="1"/></NODE>')
        s = historia.wczytaj_sesje(xml, lib_copy)[0]
        assert os.path.basename(s.sciezki[0]) == GOOD_MP3

    def test_liczy_utwory_spoza_biblioteki(self, tmp_path, lib_copy):
        extra = ('<TRACK TrackID="9" Name="Znikl" '
                 'Location="file://localhost/nie/ma/x.flac"/>')
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-08-31">'
                   '<TRACK Key="1"/><TRACK Key="9"/></NODE>', extra)
        s = historia.wczytaj_sesje(xml, lib_copy)[0]
        assert len(s.sciezki) == 1 and s.nieodnalezione == 1

    def test_sesje_sa_sortowane_po_dacie(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-09-01"><TRACK Key="1"/></NODE>'
                   '<NODE Type="1" Name="2026-08-01"><TRACK Key="2"/></NODE>')
        assert [s.data for s in historia.wczytaj_sesje(xml, lib_copy)] == \
            ["2026-08-01", "2026-09-01"]


class TestZapisIMetryki:
    def _wczytaj(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-08-15">'
                   '<TRACK Key="1"/><TRACK Key="2"/></NODE>'
                   '<NODE Type="1" Name="2026-08-31"><TRACK Key="1"/></NODE>')
        return historia.wczytaj_sesje(xml, lib_copy)

    def test_ponowny_import_nie_dubluje(self, tmp_path, lib_copy):
        sesje = self._wczytaj(tmp_path, lib_copy)
        assert historia.dopisz(sesje)["nowe"] == 2
        drugi = historia.dopisz(sesje)
        assert drugi["nowe"] == 0 and drugi["juz_znane"] == 2

    def test_liczy_ile_razy_zagrany(self, tmp_path, lib_copy):
        historia.dopisz(self._wczytaj(tmp_path, lib_copy))
        d = historia.podsumowanie(lib_copy)
        naj = {x["file"]: x["zagran"] for x in d["najczestsze"]}
        assert naj[GOOD_FLAC] == 2 and naj[GOOD_MP3] == 1

    def test_zapamietuje_ostatnie_granie(self, tmp_path, lib_copy):
        historia.dopisz(self._wczytaj(tmp_path, lib_copy))
        d = historia.podsumowanie(lib_copy)
        ostatnio = {x["file"]: x["ostatnio"] for x in d["najczestsze"]}
        assert ostatnio[GOOD_FLAC] == "2026-08-31"

    def test_martwy_balast_to_niegrane(self, tmp_path, lib_copy):
        historia.dopisz(self._wczytaj(tmp_path, lib_copy))
        d = historia.podsumowanie(lib_copy)
        martwe = {x["file"] for x in d["martwe"]}
        assert GOOD_FLAC not in martwe and GOOD_MP3 not in martwe
        assert d["martwy_balast"] == d["w_bibliotece"] - 2

    def test_liczy_powtorzone_przejscia(self, tmp_path, lib_copy):
        xml = _xml(tmp_path, lib_copy,
                   '<NODE Type="1" Name="2026-08-01">'
                   '<TRACK Key="1"/><TRACK Key="2"/></NODE>'
                   '<NODE Type="1" Name="2026-08-02">'
                   '<TRACK Key="1"/><TRACK Key="2"/></NODE>')
        historia.dopisz(historia.wczytaj_sesje(xml, lib_copy))
        p = historia.podsumowanie(lib_copy)["ulubione_przejscia"]
        assert p and p[0]["razy"] == 2

    def test_pojedyncze_przejscie_nie_jest_nawykiem(self, tmp_path, lib_copy):
        historia.dopisz(self._wczytaj(tmp_path, lib_copy))
        assert historia.podsumowanie(lib_copy)["ulubione_przejscia"] == []

    def test_bez_historii_wszystko_jest_martwe(self, lib_copy):
        d = historia.podsumowanie(lib_copy)
        assert d["sesji"] == 0
        assert d["martwy_balast"] == d["w_bibliotece"]

    def test_wyczysc_kasuje_sesje(self, tmp_path, lib_copy):
        historia.dopisz(self._wczytaj(tmp_path, lib_copy))
        assert historia.wyczysc() == 2
        assert historia.sesje() == []
