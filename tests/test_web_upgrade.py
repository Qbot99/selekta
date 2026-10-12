"""Wymiana utworów w słabej jakości na lepsze źródła.

Stratnej kompresji nie da się cofnąć — górne pasmo zostało wycięte przy
kodowaniu i w pliku go po prostu nie ma. Dlatego jedyna sensowna „naprawa
jakości" to znalezienie lepszego źródła, i to sprawdzamy tutaj: czy apka
poprawnie wskazuje kandydatów do wymiany i czy odrzuca wyniki, które
wcale nie są lepsze.
"""
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
    return TestClient(web.app)


class TestListaDoWymiany:
    def test_dobre_pliki_nie_trafiaja_na_liste(self, client, lib_copy):
        r = client.post("/api/upgrade/list",
                        json={"files": [os.path.join(lib_copy, GOOD_FLAC)]})
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_odrzuca_folder_spoza_biblioteki(self, client, tmp_path_factory):
        poza = tmp_path_factory.mktemp("poza")
        r = client.post("/api/upgrade/list", json={"folder": str(poza)})
        assert r.status_code == 400

    def test_podaje_obecny_format_i_bitrate(self, client, lib_copy):
        """Bez tego nie da się ocenić, czy znaleziony plik JEST lepszy."""
        r = client.post("/api/upgrade/list",
                        json={"files": [os.path.join(lib_copy, f)
                                        for f in (GOOD_FLAC, GOOD_MP3)]})
        for row in r.json()["tracks"]:
            assert set(row) >= {"format", "bitrate", "lossless", "grade", "verdict"}


class TestCoJestLepsze:
    """Filtr „lepsze niż to, co mam" — serce tej funkcji."""

    def _find(self, client, monkeypatch, kandydaci, **body):
        from selekta.slskd_client import SlskdClient
        monkeypatch.setattr(SlskdClient, "available", lambda self: True)
        monkeypatch.setattr(SlskdClient, "search_candidates",
                            lambda self, a, t, d=None, **kw: kandydaci)
        payload = {"artist": "Aquagen", "title": "Silence", "duration": 200}
        payload.update(body)
        r = client.post("/api/upgrade/find", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    def _kand(self, **kw):
        base = {"path": "x/Aquagen - Silence.flac",
                "filename": "Aquagen - Silence.flac", "user": "u", "size": 1,
                "size_mb": 1.0, "bitrate": None, "length_s": 200, "format": "FLAC",
                "lossless": True, "free_slot": True, "title_match": 1.0,
                "artist_match": 1.0, "duration_delta": 0, "duration_ok": True}
        base.update(kw)
        # w prawdziwych wynikach filename ZAWSZE wynika ze ścieżki —
        # atrapa musi się tak zachowywać, inaczej testuje fikcję
        if "path" in kw and "filename" not in kw:
            base["filename"] = os.path.basename(kw["path"].replace("\\", "/"))
        return base

    def test_bezstratny_bije_stratny(self, client, monkeypatch):
        d = self._find(client, monkeypatch, [self._kand()], lossless=False, bitrate=128)
        assert d["count"] == 1
        assert "bezstratny" in d["candidates"][0]["dlaczego"]

    def test_nie_proponuje_bezstratnego_gdy_juz_mam_bezstratny(self, client, monkeypatch):
        d = self._find(client, monkeypatch, [self._kand()], lossless=True, bitrate=0)
        assert d["count"] == 0

    def test_wyzszy_bitrate_liczy_sie_jako_lepszy(self, client, monkeypatch):
        kand = self._kand(lossless=False, format="MP3", bitrate=320, path="x/Aquagen - Silence.mp3")
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128)
        assert d["count"] == 1 and "320" in d["candidates"][0]["dlaczego"]

    def test_taki_sam_bitrate_to_nie_ulepszenie(self, client, monkeypatch):
        kand = self._kand(lossless=False, format="MP3", bitrate=128, path="x/Aquagen - Silence.mp3")
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128)
        assert d["count"] == 0

    def test_klamliwy_naglowek_320_nie_blokuje_uczciwego_320(self, client, monkeypatch):
        """Plik przekodowany ze 128 kbps deklaruje 320, choć pasmo urywa
        się na 16 kHz. Gdy analiza uznała jakość za złą, nagłówek trzeba
        zignorować — inaczej odrzucilibyśmy prawdziwe 320 kbps."""
        kand = self._kand(lossless=False, format="MP3", bitrate=320, path="x/Aquagen - Silence.mp3")
        d = self._find(client, monkeypatch, [kand],
                       lossless=False, bitrate=320, grade="bad")
        assert d["count"] == 1

    def test_inny_utwor_odpada(self, client, monkeypatch):
        """Nazwa pliku nie zawiera istotnych słów tytułu."""
        kand = self._kand(title_match=0.2, path="x/sweet dreams & goodnight.flac")
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128)
        assert d["count"] == 0

    def test_inna_wersja_nie_jest_ulepszeniem(self, client, monkeypatch):
        """Bootleg to nie club mix — podmiana dałaby w secie inny utwór.

        Realny błąd: „Come Into My Dream (Seaven Bootleg)" trafiało
        w „Come (Into My Dream) (Club Mix)".
        """
        kand = self._kand(path="x/Foggy - Come (Into My Dream) (Club Mix).flac")
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128,
                       title="Come Into My Dream (Seaven Bootleg)")
        assert d["count"] == 0

    def test_ta_sama_wersja_przechodzi(self, client, monkeypatch):
        kand = self._kand(path="x/David Guetta ft. Sia - Titanium (Killer Bootleg).flac")
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128,
                       artist="David Guetta", title="Titanium ft. Sia (Killer Bootleg)")
        assert d["count"] == 1

    def test_brak_dlugosci_oznaczony_jako_niepewny(self, client, monkeypatch):
        """Gdy serwer nie poda długości, nie udajemy pewności."""
        kand = self._kand(duration_delta=None, duration_ok=False)
        d = self._find(client, monkeypatch, [kand], lossless=False, bitrate=128)
        assert d["count"] == 1
        assert "nie podał długości" in d["candidates"][0]["pewnosc"]

    def test_inna_dlugosc_odpada(self, client, monkeypatch):
        """Skrót radiowy zamiast extended to nie jest ta sama rzecz."""
        d = self._find(client, monkeypatch, [self._kand(duration_delta=45)],
                       lossless=False, bitrate=128)
        assert d["count"] == 0

    def test_bezstratne_ida_przed_stratnymi(self, client, monkeypatch):
        kandydaci = [self._kand(lossless=False, format="MP3", bitrate=320, path="Aquagen - Silence.mp3"),
                     self._kand(path="Aquagen - Silence.flac")]
        d = self._find(client, monkeypatch, kandydaci, lossless=False, bitrate=128)
        assert [c["format"] for c in d["candidates"]] == ["FLAC", "MP3"]

    def test_brak_slskd_to_czytelny_blad(self, client, monkeypatch):
        from selekta.slskd_client import SlskdClient
        monkeypatch.setattr(SlskdClient, "available", lambda self: False)
        r = client.post("/api/upgrade/find",
                        json={"artist": "Aquagen", "title": "Silence"})
        assert r.status_code == 503


class TestNieTenUtwor:
    """Regresje z prawdziwego skanu: 5 z 7 pobrań było innym utworem."""

    def _find(self, client, monkeypatch, kandydaci, **body):
        from selekta.slskd_client import SlskdClient
        monkeypatch.setattr(SlskdClient, "available", lambda self: True)
        monkeypatch.setattr(SlskdClient, "search_candidates",
                            lambda self, a, t, d=None, **kw: kandydaci)
        payload = {"artist": "A", "title": "T", "duration": 200,
                   "lossless": False, "bitrate": 128}
        payload.update(body)
        r = client.post("/api/upgrade/find", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    def _kand(self, path, **kw):
        base = {"path": path, "filename": os.path.basename(path),
                "user": "u", "size": 1, "size_mb": 1.0, "bitrate": None,
                "length_s": 200, "format": "FLAC", "lossless": True,
                "free_slot": True, "title_match": 1.0, "artist_match": 1.0,
                "duration_delta": 0, "duration_ok": True}
        base.update(kw)
        return base

    def test_tytul_zawarty_w_dluzszym_to_inny_utwor(self, client, monkeypatch):
        """„United" mieści się w „United in Unhallowed Grace"."""
        k = self._kand("x/04 - United in Unhallowed Grace.flac")
        d = self._find(client, monkeypatch, [k], artist="Mark OH", title="United")
        assert d["count"] == 0

    def test_icarus_nie_jest_icarus_and_pegasus(self, client, monkeypatch):
        k = self._kand("x/03 - Anders Ilar - Icarus & Pegasus.flac")
        d = self._find(client, monkeypatch, [k], artist="Ralphie B", title="Icarus")
        assert d["count"] == 0

    def test_ten_sam_tytul_inny_artysta_odpada(self, client, monkeypatch):
        """„Cherry Blossom" ma i Marcel Woods, i Harry Kaze."""
        k = self._kand("x/08. Harry Kaze, Sam Zloty - Cherry Blossom.flac",
                       artist_match=0.0)
        d = self._find(client, monkeypatch, [k],
                       artist="Marcel Woods", title="Cherry Blossom")
        assert d["count"] == 0

    def test_numer_sciezki_i_nazwisko_nie_sa_nadmiarem(self, client, monkeypatch):
        """Poprawne trafienie ma numer i artystę w nazwie — to norma."""
        k = self._kand("x/15. Aquagen - Hard To Say I'm Sorry.flac")
        d = self._find(client, monkeypatch, [k],
                       artist="Aquagen", title="Hard To Say I'm Sorry")
        assert d["count"] == 1

    def test_niezgodny_artysta_odpada(self, client, monkeypatch):
        k = self._kand("x/08. Freefall.flac", artist_match=0.0)
        d = self._find(client, monkeypatch, [k],
                       artist="Jeckyll & Hyde", title="Freefall")
        assert d["count"] == 0


class TestNiskiBitrateWNaglowku:
    """Przegląd 0.4.2: MP3 128 kbps MONO z pełnym pasmem → „ok", poza listą."""

    def _mp3(self, lib_copy, nazwa, kanaly):
        import subprocess
        from selekta.narzedzia import ffmpeg_path
        p = os.path.join(lib_copy, nazwa)
        subprocess.run([ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "anoisesrc=d=4:c=white:a=0.3", "-ac", str(kanaly), "-b:a", "128k", p],
                       check=True)
        from selekta import cache
        cache.put(p, "quality", {"grade": "ok", "verdict": "pełne pasmo", "cutoff_hz": 20000})
        return p

    def test_mono_128_trafia_na_liste(self, client, lib_copy):
        p = self._mp3(lib_copy, "Ktoś - Mono.mp3", 1)
        d = client.post("/api/upgrade/list", json={"files": [p]}).json()
        assert d["count"] == 1
        row = d["tracks"][0]
        assert row["grade"] == "warn" and "128 kbps" in row["verdict"] and "mono" in row["verdict"]

    def test_dobry_flac_dalej_poza_lista(self, client, lib_copy):
        d = client.post("/api/upgrade/list",
                        json={"files": [os.path.join(lib_copy, GOOD_FLAC)]}).json()
        assert d["count"] == 0
