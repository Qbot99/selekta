"""Siatka z kilkoma znacznikami TEMPO — od analizy, przez edytor, do XML-a rekordboxa.

Pojedyncza kotwica + BPM nie opisze utworu, którego tempo się zmienia
(nagrania na żywo, stare disco, remiksy z przyspieszeniem). Te testy pilnują,
żeby pełna siatka nie spłaszczała się po drodze do jednego znacznika:
ani z analizy, ani z ręcznej pracy w rekordboksie, ani z edytora selekty.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from selekta import cache, dj_export, rbimport, siatka, tempo, waveform, web
from tests.conftest import GOOD_MP3

DYN = [{"t": 0.5, "bpm": 120.0, "battito": 1},
       {"t": 32.5, "bpm": 121.0, "battito": 1},
       {"t": 64.236, "bpm": 122.0, "battito": 3}]


def _cues(path, **nad):
    c = {"duration_s": 200.0, "first_beat_s": 0.5, "intro_end_s": 16.5, "outro_start_s": 150.0,
         "drop_s": 48.5, "battito": 1, "bpm_siatki": 121.0, "pewnosc_siatki": 0.9,
         "pewnosc_taktu": 0.9, "znaczniki": DYN, "tryb_siatki": "dynamiczna",
         "flaga_siatki": None, "odchylka_siatki_ms": 2.1, "bpm_dokladne": 121.02}
    c.update(nad)
    cache.put(path, "harmonic", {"bpm": 121.0, "key": "A minor", "camelot": "8A",
                                 "confidence_bpm": 0.9, "confidence_key": 0.9})
    cache.put(path, "cues", c)


def _tempa_xml(xml_path):
    tr = ET.parse(xml_path).getroot().find(".//COLLECTION/TRACK")
    return [(float(t.get("Inizio")), float(t.get("Bpm")), int(t.get("Battito"))) for t in tr.findall("TEMPO")]


@pytest.fixture()
def plik(lib_copy):
    p = os.path.join(lib_copy, os.path.basename(GOOD_MP3))
    web.set_folder(lib_copy)
    return p


class TestJedynkiTaktu:
    def test_jedynki_z_numerem_bitu_kotwicy(self):
        j = siatka.jedynki_taktu([{"t": 0.5, "bpm": 120.0, "battito": 3}], 6.0)
        assert [round(x, 3) for x in j] == [1.5, 3.5, 5.5]

    def test_kazdy_znacznik_zaczyna_siatke_od_nowa(self):
        zn = [{"t": 0.5, "bpm": 120.0, "battito": 1}, {"t": 10.5, "bpm": 125.0, "battito": 1}]
        j = siatka.jedynki_taktu(zn, 20.0)
        assert 10.5 in [round(x, 3) for x in j]
        assert all(abs((b - a) - 1.92) < 1e-6 for a, b in zip(j[5:], j[6:]))   # 4 bity po 0,48 s

    def test_cue_na_najblizszej_jedynce(self):
        assert siatka.do_taktu(9.9, [5.5, 7.5, 9.5, 11.5]) == 9.5
        assert siatka.do_taktu(None, [1.0]) is None


class TestEksport:
    def test_siatka_dynamiczna_z_analizy_idzie_w_calosci(self, plik, tmp_path):
        _cues(plik)
        t = dj_export.wzbogac_o_siatke([{"path": plik}], licz_brakujace=False)[0]
        out = dj_export.to_rekordbox_xml([t], "x", str(tmp_path / "a.xml"))
        assert _tempa_xml(out) == [(0.5, 120.0, 1), (32.5, 121.0, 1), (64.236, 122.0, 3)]

    def test_reczna_siatka_dynamiczna_z_rekordboxa_wraca(self, plik, tmp_path):
        _cues(plik, znaczniki=[{"t": 0.4, "bpm": 121.0, "battito": 1}], tryb_siatki="stała")
        rbimport._zapisz_stan({rbimport._klucz(plik): {
            "first_beat_s": 0.25, "bpm": 100.0, "battito": 1,
            "tempa": [{"inizio_s": 0.25, "bpm": 100.0, "battito": 1, "metro": "4/4"},
                      {"inizio_s": 60.25, "bpm": 101.5, "battito": 2, "metro": "4/4"}]}})
        t = dj_export.wzbogac_o_siatke([{"path": plik}], licz_brakujace=False)[0]
        out = dj_export.to_rekordbox_xml([t], "x", str(tmp_path / "b.xml"))
        assert _tempa_xml(out) == [(0.25, 100.0, 1), (60.25, 101.5, 2)]

    def test_reczna_poprawka_w_selekcie_wygrywa(self, plik, tmp_path):
        _cues(plik)
        przes = [{**z, "t": z["t"] + 0.01} for z in DYN]
        waveform.zapisz_siatke(plik, przes[0]["t"], 121.0, 1, przes)
        t = dj_export.wzbogac_o_siatke([{"path": plik}], licz_brakujace=False)[0]
        out = dj_export.to_rekordbox_xml([t], "x", str(tmp_path / "c.xml"))
        assert [round(x[0], 3) for x in _tempa_xml(out)] == [0.51, 32.51, 64.246]


class TestEdytor:
    def test_waveform_podaje_te_sama_siatke_co_eksport(self, plik):
        _cues(plik)
        d = TestClient(web.app).get("/api/waveform", params={"file": os.path.basename(plik)}).json()
        assert d["tryb_siatki"] == "dynamiczna" and d["zrodlo_siatki"] == "analiza"
        assert [z["t"] for z in d["znaczniki"]] == [0.5, 32.5, 64.236]
        assert d["bpm"] == 121.02

    def test_stala_siatka_z_kotwicami_to_nie_zmienne_tempo(self, plik):
        _cues(plik, znaczniki=[{"t": 0.5, "bpm": 121.0, "battito": 1},
                               {"t": 95.7, "bpm": 121.0, "battito": 1}], tryb_siatki="stała")
        d = TestClient(web.app).get("/api/waveform", params={"file": os.path.basename(plik)}).json()
        assert d["tryb_siatki"] == "stała" and len(d["znaczniki"]) == 2

    def test_zapis_przesunietej_siatki_dynamicznej(self, plik):
        _cues(plik)
        k = TestClient(web.app)
        przes = [{**z, "t": z["t"] - 0.02} for z in DYN]
        r = k.post("/api/siatka", json={"file": os.path.basename(plik), "first_beat_s": 9.9,
                                        "bpm": 121.02, "battito": 1, "znaczniki": przes})
        assert r.status_code == 200, r.text
        assert r.json()["first_beat_s"] == 0.48, "kotwica = pierwszy znacznik"
        d = k.get("/api/waveform", params={"file": os.path.basename(plik)}).json()
        assert d["zrodlo_siatki"] == "reczna" and d["znaczniki"][2]["t"] == pytest.approx(64.216)

    def test_jeden_znacznik_to_blad(self, plik):
        _cues(plik)
        r = TestClient(web.app).post("/api/siatka", json={
            "file": os.path.basename(plik), "first_beat_s": 0.5, "znaczniki": [DYN[0]]})
        assert r.status_code == 400

    def test_reset_wraca_do_siatki_z_analizy(self, plik):
        _cues(plik)
        waveform.zapisz_siatke(plik, 0.7, 121.0, 1)
        j = TestClient(web.app).post("/api/siatka", json={"file": os.path.basename(plik), "reset": True}).json()
        assert j["first_beat_s"] == 0.5 and j["tryb_siatki"] == "dynamiczna"


class TestStabilnoscZAnalizy:
    def test_tempo_czyta_wynik_analizy_bez_dekodowania(self, monkeypatch):
        monkeypatch.setattr(tempo, "_decode", lambda p: (_ for _ in ()).throw(AssertionError("dekoduje")))
        c = {"duration_s": 200.0, "znaczniki": DYN, "tryb_siatki": "dynamiczna", "bpm_siatki": 121.0,
             "bpm_dokladne": 121.02, "odchylka_siatki_ms": 2.0, "flaga_siatki": None}
        s = tempo.zbadaj("/nie/ma/pliku.mp3", 121.0, c)
        assert s.stabilne is False and "dynamiczną" in s.opis and s.okien == 3

    def test_stale_z_poprawka_bpm(self, monkeypatch):
        monkeypatch.setattr(tempo, "_decode", lambda p: (_ for _ in ()).throw(AssertionError("dekoduje")))
        c = {"duration_s": 300.0, "znaczniki": [{"t": 0.3, "bpm": 128.0, "battito": 1}],
             "tryb_siatki": "stała", "bpm_siatki": 128.0, "bpm_dokladne": 128.0004}
        s = tempo.zbadaj("/x.mp3", 127.9, c)
        assert s.stabilne and s.bpm_nietrafione and s.bpm_poprawione == 128.0
