"""Odsłuch kontrolny: stopy vs siatka (lampki) i hot cue stawiane w selekcie."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from selekta import dj_export, hotcue, siatka


# ------------------------------------------------------------------ bity siatki

def test_bity_stalej_siatki_od_poczatku_z_numerami_taktu():
    # 120 BPM = bit co 0,5 s; kotwica 1,25 s jest bitem 3 → wcześniej są bity 1 i 2
    bity = siatka.bity_siatki(120.0, 1.25, 3, None, 4.0)
    assert bity[:4] == [(0.25, 1), (0.75, 2), (1.25, 3), (1.75, 4)]
    assert bity[-1] == (3.75, 4) and all(0 <= t < 4.0 for t, _ in bity)


def test_bity_siatki_dynamicznej_odcinkami():
    zn = [{"t": 0.0, "bpm": 120.0, "battito": 1}, {"t": 2.0, "bpm": 60.0, "battito": 1}]
    bity = siatka.bity_siatki(None, None, 1, zn, 5.0)
    assert bity == [(0.0, 1), (0.5, 2), (1.0, 3), (1.5, 4), (2.0, 1), (3.0, 2), (4.0, 3)]


def test_bez_siatki_brak_bitow():
    assert siatka.bity_siatki(None, None, 1, None, 100.0) == []


# ------------------------------------------------------------------ stopa

def _kick(sr, n_bitow=40, bpm=128.0, hat=True):
    """Stopa (opadający sinus 50–120 Hz) na bitach + hi-hat (szum) na „i”."""
    okres = 60.0 / bpm
    x = np.zeros(int(sr * (n_bitow * okres + 1.0)), dtype=np.float32)
    tk = np.arange(int(0.15 * sr)) / sr
    f = 50 + 70 * np.exp(-tk * 30)
    kick = (np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-tk * 18)).astype(np.float32)
    rng = np.random.default_rng(1)
    hh = (rng.standard_normal(int(0.03 * sr)) * np.exp(-np.arange(int(0.03 * sr)) / sr * 150)
          * 0.9).astype(np.float32)
    for k in range(n_bitow):
        i = int((0.5 + k * okres) * sr)
        x[i:i + kick.size] += kick
        if hat:
            j = int((0.5 + (k + 0.5) * okres) * sr)
            x[j:j + hh.size] += hh
    return x, [0.5 + k * okres for k in range(n_bitow)]


def test_stopy_na_bitach_a_nie_na_hihatach():
    sr = 11025
    x, prawdziwe = _kick(sr)
    st = siatka.stopy(x, sr)
    mocne = [t for t, w in st if w >= 0.6]
    assert len(mocne) >= 0.8 * len(prawdziwe)
    for t in mocne:                       # każda mocna „stopa” leży na bicie, nie na „i”
        assert min(abs(t - p) for p in prawdziwe) < 0.015


def test_cisza_bez_stop():
    assert siatka.stopy(np.zeros(11025 * 5, dtype=np.float32), 11025) == []


# ------------------------------------------------------------------ hot cue

@pytest.fixture
def pamiec(tmp_path, monkeypatch):
    monkeypatch.setattr(hotcue, "PLIK", str(tmp_path / "hotcue.json"))
    return str(tmp_path / "Utwor.flac")


def test_ustaw_zastap_usun(pamiec):
    hotcue.ustaw(pamiec, 1, 32.1234)
    hotcue.ustaw(pamiec, 0, 0.5)
    lista = hotcue.ustaw(pamiec, 1, 64.0)                  # ten sam slot: nowy czas
    assert [(z["num"], z["start_s"]) for z in lista] == [(0, 0.5), (1, 64.0)]
    assert hotcue.usun(pamiec, 0) == [z for z in lista if z["num"] == 1]
    assert hotcue.dla_pliku(pamiec)[0]["kolor"] == hotcue.KOLORY[1]


def test_zle_sloty_i_czasy(pamiec):
    for num, t in ((8, 1.0), (-1, 1.0), (0, -2.0)):
        with pytest.raises(ValueError):
            hotcue.ustaw(pamiec, num, t)
    assert hotcue.dla_pliku(pamiec) == []


def test_scal_zastepuje_tylko_zajete_sloty():
    rb = [{"num": 0, "start_s": 1.0, "nazwa": "rb A"}, {"num": 3, "start_s": 9.0},
          {"num": -1, "start_s": 2.0, "nazwa": "memory"}]
    moje = [{"num": 0, "start_s": 5.0, "nazwa": ""}]
    wynik = hotcue.scal(rb, moje)
    assert {(z["num"], z["start_s"]) for z in wynik} == {(0, 5.0), (3, 9.0), (-1, 2.0)}


# ------------------------------------------------------------------ eksport

def _xml(tmp_path, **pola):
    track = {"path": str(tmp_path / "u.flac"), "title": "T", "artist": "A",
             "duration_s": 200.0, "bpm": 150.0, "first_beat_s": 0.4,
             "intro_end_s": 30.0, "drop_s": 60.0, "outro_start_s": 180.0}
    track.update(pola)
    out = str(tmp_path / "set.xml")
    dj_export.to_rekordbox_xml([track], "set", out)
    return {int(m.get("Num")): float(m.get("Start"))
            for m in ET.parse(out).getroot().iter("POSITION_MARK")}


def test_hot_cue_z_selekty_w_eksporcie_auto_cue_w_wolnych_slotach(tmp_path):
    cue = _xml(tmp_path, hot_cue=[{"num": 1, "start_s": 64.0, "typ": "0"},
                                  {"num": 4, "start_s": 90.0, "typ": "0"}])
    assert cue[1] == 64.0 and cue[4] == 90.0          # drop z analizy ustąpił
    assert cue[0] == 30.0 and cue[2] == 180.0         # intro/outro zostały


def test_hot_cue_z_selekty_nie_kasuje_pracy_z_rekordboxa(tmp_path):
    cue = _xml(tmp_path, znaczniki=[{"num": 0, "start_s": 12.0, "typ": "0"},
                                    {"num": 2, "start_s": 44.0, "typ": "0"}],
               hot_cue=[{"num": 0, "start_s": 16.0, "typ": "0"}])
    assert cue == {0: 16.0, 2: 44.0}                   # bez auto cue: jest ręczna praca


def test_bez_hot_cue_eksport_jak_dawniej(tmp_path):
    assert _xml(tmp_path) == {0: 30.0, 1: 60.0, 2: 180.0}
