"""Biblioteka to nie płaski katalog.

Soulseek i Nicotine+ zapisują pobrania do katalogów albumów
(``downloads/Nazwa albumu/01 utwor.flac``). Dopóki apka listowała tylko
wierzch, świeżo pobrane utwory były niewidoczne: nie było ich w
bibliotece, nie dopasowywały się do playlisty i nie trafiały do eksportu.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import matcher, spotify, web
from tests.conftest import GOOD_FLAC, fast_copy, real_path


@pytest.fixture()
def z_podfolderem(lib_copy):
    """Biblioteka z utworem schowanym o dwa poziomy w głąb."""
    glebok = os.path.join(lib_copy, "Album 2025", "CD1")
    os.makedirs(glebok, exist_ok=True)
    fast_copy(real_path(GOOD_FLAC), os.path.join(glebok, "07 schowany.flac"))
    return lib_copy


class TestSpisPlikow:
    def test_widzi_utwory_w_podfolderach(self, z_podfolderem):
        pliki = matcher.audio_files(z_podfolderem)
        assert any(os.path.basename(p) == "07 schowany.flac" for p in pliki)

    def test_pomija_kosz(self, lib_copy):
        kosz = os.path.join(lib_copy, "_selekta_kosz")
        os.makedirs(kosz, exist_ok=True)
        fast_copy(real_path(GOOD_FLAC), os.path.join(kosz, "wyrzucony.flac"))
        assert all("_selekta_kosz" not in p for p in matcher.audio_files(lib_copy))

    def test_pomija_katalogi_ukryte(self, lib_copy):
        ukryty = os.path.join(lib_copy, ".cache")
        os.makedirs(ukryty, exist_ok=True)
        fast_copy(real_path(GOOD_FLAC), os.path.join(ukryty, "smiec.flac"))
        assert all("/.cache/" not in p for p in matcher.audio_files(lib_copy))

    def test_brak_folderu_to_czytelny_blad(self):
        with pytest.raises(FileNotFoundError):
            matcher.audio_files("/nie/ma/takiego/folderu")

    def test_kolejnosc_jest_powtarzalna(self, z_podfolderem):
        assert matcher.audio_files(z_podfolderem) == matcher.audio_files(z_podfolderem)


class TestRozwiazywanieNazw:
    def test_znajduje_po_samej_nazwie_w_podfolderze(self, z_podfolderem):
        p = matcher.resolve_in_library(z_podfolderem, "07 schowany.flac")
        assert p and os.path.isfile(p)

    def test_zwraca_none_gdy_nie_ma(self, lib_copy):
        assert matcher.resolve_in_library(lib_copy, "nie-ma-mnie.flac") is None


class TestRemisFormatow:
    def test_flac_wygrywa_z_wav_przy_takim_samym_wyniku(self, lib_copy):
        """lib_copy zawiera ten sam utwór jako FLAC i jako WAV. Wybór nie
        może zależeć od kolejności listowania katalogów."""
        t = spotify.Track(id="", artist="Odymel", title="Gucci", duration_s=274)
        wybor = matcher.classify_track(t, matcher.library_index(lib_copy))
        assert os.path.basename(wybor.path) == GOOD_FLAC
        assert matcher.format_rank("a.flac") < matcher.format_rank("a.wav")
        assert matcher.format_rank("a.wav") < matcher.format_rank("a.mp3")


class TestBibliotekaWDashboardzie:
    def test_api_tracks_pokazuje_podfoldery(self, z_podfolderem):
        web.set_folder(z_podfolderem)
        web._HEALTH_CACHE.update(sig=None, report=None)
        c = TestClient(web.app)
        d = c.get("/api/tracks").json()
        assert any(t["file"] == "07 schowany.flac" for t in d["tracks"])

    def test_okladka_utworu_z_podfolderu_sie_otwiera(self, z_podfolderem):
        web.set_folder(z_podfolderem)
        c = TestClient(web.app)
        r = c.get("/api/cover", params={"file": "07 schowany.flac"})
        assert r.status_code == 200 and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN")

    def test_nadal_nie_wypuszcza_poza_biblioteke(self, z_podfolderem):
        web.set_folder(z_podfolderem)
        c = TestClient(web.app)
        r = c.get("/api/cover", params={"file": "../../../../etc/passwd"})
        assert r.status_code == 400


class TestSpoznionePobrania:
    def test_collect_dociaga_utwor_ktory_doszedl_po_kliknieciu_dalej(self, lib_copy):
        """Sedno zgłoszonego błędu: pobranie kończy się PO tym, jak
        interfejs wysłał listę plików. Utwór i tak ma trafić na playlistę."""
        web.set_folder(lib_copy)
        c = TestClient(web.app)
        r = c.post("/api/playlist/collect", json={
            "name": "spozniona", "files": [],          # interfejs nic nie zdążył
            "tracks": [{"artist": "Odymel", "title": "Gucci", "duration": 274}],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] == 1
        assert d["late"] == [GOOD_FLAC]
