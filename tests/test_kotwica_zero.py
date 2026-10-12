"""Ręczna kotwica 0,0 s to świadoma decyzja DJ-a, nie „brak kotwicy”.

Przegląd 0.4.2: eksport i przyjęcie poprawki BPM brały kotwicę przez `or`,
więc 0,0 (utwór zaczyna się od uderzenia w pierwszej próbce) przegrywało
z wyliczoną 0,5 s albo z rekordboxem.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from selekta import cache, dj_export, waveform, web
from tests import probka


def _utwor(tmp_path):
    p = probka.bit_klubowy(str(tmp_path / "u.wav"), 128.0, 0.0, sekund=30.0)
    cache.put(p, "harmonic", {"bpm": 128.0, "key": "A minor", "camelot": "8A",
                              "confidence_bpm": 0.5, "confidence_key": 0.9})
    cache.put(p, "cues", {"first_beat_s": 0.5, "intro_end_s": 8.0, "outro_start_s": 25.0,
                          "drop_s": None, "duration_s": 30.0, "battito": 1,
                          "bpm_siatki": 128.0, "pewnosc_siatki": 0.9, "pewnosc_taktu": 0.8})
    return p


def test_eksport_bierze_reczna_kotwice_zero(tmp_path):
    p = _utwor(tmp_path)
    waveform.zapisz_siatke(p, 0.0, 128.0, 1)
    track = {"path": p, "title": "T", "artist": "A", "duration_s": 30.0, "bpm": 128.0, "key": None}
    (t,) = dj_export.wzbogac_o_siatke([track])
    assert t["first_beat_s"] == 0.0
    out = str(tmp_path / "set.xml")
    dj_export.to_rekordbox_xml([t], "set", out)
    tempo = ET.parse(out).getroot().find(".//COLLECTION/TRACK/TEMPO")
    assert float(tempo.get("Inizio")) == 0.0


def test_przyjecie_bpm_zachowuje_kotwice_zero(tmp_path, monkeypatch):
    p = _utwor(tmp_path)
    waveform.zapisz_siatke(p, 0.0, None, 1)
    monkeypatch.setattr(web, "_tempo_dla", lambda path: {
        "stabilne": True, "bpm_nietrafione": True, "bpm_poprawione": 127.75})
    web.set_folder(str(tmp_path))
    r = TestClient(web.app).post("/api/tempo/przyjmij", json={"file": "u.wav"})
    assert r.status_code == 200, r.text
    assert waveform.wczytaj_siatke(p)["first_beat_s"] == 0.0
    assert waveform.wczytaj_siatke(p)["bpm"] == 127.75
