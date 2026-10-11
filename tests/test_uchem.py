"""Sprawdź uchem — lista wyników, których apka nie jest pewna.

Sedno: wynik pewny i niepewny nie mogą wyglądać tak samo. Testy karmią
moduł sztucznym cache (bez liczenia audio), bo interesuje nas wyłącznie
logika progów i kolejność.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import cache, uchem, web
from tests.conftest import GOOD_FLAC, GOOD_MP3


def _h(bpm=128.0, cb=0.5, key="A minor", ck=0.9):
    return {"bpm": bpm, "confidence_bpm": cb, "key": key, "camelot": "8A",
            "confidence_key": ck}


class TestPowody:
    def test_pewny_wynik_nie_ma_powodow(self):
        assert uchem._powody(_h(), None, None) == []

    def test_niepewne_tempo_to_najwyzsza_waga(self):
        """Metronom 87 BPM z weryfikacji miał pewność 0,04 — decyzja
        o podwojeniu na styku. Taki wynik musi być na górze listy."""
        p = uchem._powody(_h(bpm=87.0, cb=0.04), None, None)
        assert [x.kod for x in p] == ["tempo_niepewne"]
        assert p[0].waga == 3
        assert "174" in p[0].opis and "44" in p[0].opis   # podpowiedź oktaw

    def test_prog_tempa_lezy_ponizej_realnych_utworow(self):
        """Realne utwory klubowe: 0,32-0,62 — żaden nie może trafić na listę
        z powodu samego tempa."""
        for cb in (0.32, 0.41, 0.45, 0.62):
            assert uchem._powody(_h(cb=cb), None, None) == []

    def test_niepewna_tonacja_to_drobiazg(self):
        p = uchem._powody(_h(ck=0.3), None, None)
        assert [x.kod for x in p] == ["tonacja_niepewna"] and p[0].waga == 1

    def test_tempo_zmienne_z_cache_tempo(self):
        p = uchem._powody(_h(), {"stabilne": False, "opis": "tempo pływa"}, None)
        assert p[0].kod == "tempo_zmienne" and "pływa" in p[0].opis

    def test_bpm_nietrafione_podaje_poprawke(self):
        p = uchem._powody(_h(bpm=139.7), {"stabilne": True, "bpm_nietrafione": True,
                                          "bpm_poprawione": 140.0}, None)
        assert p[0].kod == "bpm_nietrafione" and "140.0" in p[0].opis

    def test_transkod_to_najwyzsza_waga_a_warn_drobiazg(self):
        zly = uchem._powody(_h(), None, {"grade": "bad", "verdict": "transkod"})
        assert zly[0].kod == "transkod" and zly[0].waga == 3
        sredni = uchem._powody(_h(), None, {"grade": "warn", "verdict": "20,5 kHz"})
        assert sredni[0].kod == "jakosc_do_oceny" and sredni[0].waga == 1

    def test_powody_posortowane_od_najciezszego(self):
        p = uchem._powody(_h(ck=0.1, cb=0.1), None, {"grade": "warn", "verdict": "x"})
        wagi = [x.waga for x in sorted(p, key=lambda x: -x.waga)]
        assert wagi == sorted(wagi, reverse=True)


class TestSprawdz:
    def test_lista_z_cache_bez_liczenia(self, lib_copy):
        """Dwa pliki: jeden pewny, jeden niepewny — na liście tylko drugi,
        trzeci bez analizy policzony osobno."""
        pliki = [os.path.join(lib_copy, os.path.basename(GOOD_MP3)),
                 os.path.join(lib_copy, os.path.basename(GOOD_FLAC))]
        cache.put(pliki[0], "harmonic", _h())
        cache.put(pliki[1], "harmonic", _h(bpm=85.0, cb=0.12))
        w = uchem.sprawdz(lib_copy)
        assert [u["file"] for u in w["utwory"]] == [pliki[1]]
        assert w["utwory"][0]["waga"] == 3
        assert w["sprawdzonych"] == 2
        assert w["bez_analizy"] >= 1

    def test_kolejnosc_najpilniejsze_na_gorze(self, lib_copy):
        a = os.path.join(lib_copy, os.path.basename(GOOD_MP3))
        b = os.path.join(lib_copy, os.path.basename(GOOD_FLAC))
        cache.put(a, "harmonic", _h(ck=0.2))              # waga 1
        cache.put(b, "harmonic", _h(bpm=85.0, cb=0.1))    # waga 3
        w = uchem.sprawdz(lib_copy)
        assert [u["file"] for u in w["utwory"]] == [b, a]

    def test_raport_tekstowy(self, lib_copy):
        a = os.path.join(lib_copy, os.path.basename(GOOD_MP3))
        cache.put(a, "harmonic", _h(bpm=85.0, cb=0.1))
        tekst = uchem.format_report(uchem.sprawdz(lib_copy))
        assert "do sprawdzenia uchem" in tekst and os.path.basename(a) in tekst
        assert "podwojenie" in tekst

    def test_pusta_biblioteka(self, tmp_path):
        w = uchem.sprawdz(str(tmp_path))
        assert w["utwory"] == [] and w["sprawdzonych"] == 0
        assert "nic do sprawdzania" in uchem.format_report(w)


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    return TestClient(web.app)


class TestEndpoint:
    def test_api_uchem_dodaje_tytul_i_artyste(self, client, lib_copy):
        a = os.path.join(lib_copy, os.path.basename(GOOD_MP3))
        cache.put(a, "harmonic", _h(bpm=85.0, cb=0.1))
        d = client.get("/api/uchem").json()
        assert len(d["utwory"]) == 1
        u = d["utwory"][0]
        assert u["file"] == a and "title" in u and "artist" in u
        assert u["powody"][0]["kod"] == "tempo_niepewne"

    def test_api_uchem_pusto_gdy_wszystko_pewne(self, client):
        d = client.get("/api/uchem").json()
        assert d["utwory"] == []


class TestSiatkaWUchem:
    def test_niepewna_siatka_trafia_na_liste(self):
        p = uchem._powody(_h(), None, None, {"pewnosc_siatki": 0.12, "pewnosc_taktu": 0.9})
        assert [x.kod for x in p] == ["siatka_niepewna"]
        assert p[0].waga == uchem.WAGI["siatka_niepewna"]

    def test_niepewny_takt_to_drobiazg(self):
        p = uchem._powody(_h(), None, None, {"pewnosc_siatki": 0.8, "pewnosc_taktu": 0.1, "battito": 3})
        assert [x.kod for x in p] == ["takt_niepewny"] and "bitu 3" in p[0].opis

    def test_pewna_siatka_milczy(self):
        assert uchem._powody(_h(), None, None, {"pewnosc_siatki": 0.8, "pewnosc_taktu": 0.9}) == []
        assert uchem._powody(_h(), None, None, {}) == []


class TestRecznaKorekta:
    """Przegląd 0.4.2: po „przyjmij” lista dalej pokazywała bpm_nietrafione,
    z poprawką zaokrągloną do 0,1 („127.8” zamiast 127,75)."""

    def test_poprawka_z_dwoma_miejscami(self):
        p = uchem._powody(_h(bpm=128.0), {"stabilne": True, "bpm_nietrafione": True,
                                          "bpm_poprawione": 127.75}, None)
        assert "127.75" in p[0].opis

    def test_po_przyjeciu_poprawki_nie_proponuje_jej_znowu(self):
        tempo = {"stabilne": True, "bpm_nietrafione": True, "bpm_poprawione": 127.75}
        reczna = {"first_beat_s": 0.5, "bpm": 127.75, "battito": 1}
        assert uchem._powody(_h(bpm=128.0), tempo, None, None, reczna) == []

    def test_reczna_siatka_wylacza_alarm_niepewnej_siatki(self):
        c = {"pewnosc_siatki": 0.1, "pewnosc_taktu": 0.9}
        assert uchem._powody(_h(), None, None, c, {"first_beat_s": 0.0}) == []

    def test_sprawdz_czyta_reczna_korekte(self, lib_copy):
        from selekta import waveform
        a = os.path.join(lib_copy, os.path.basename(GOOD_MP3))
        cache.put(a, "harmonic", _h(bpm=128.0))
        cache.put(a, "tempo", {"stabilne": True, "bpm_nietrafione": True, "bpm_poprawione": 127.75})
        assert [u["file"] for u in uchem.sprawdz(lib_copy)["utwory"]] == [a]
        waveform.zapisz_siatke(a, 0.0, 127.75, 1)
        assert uchem.sprawdz(lib_copy)["utwory"] == []
