"""Koniec intra i początek outra na utworach o ZNANEJ budowie.

Przegląd 0.4.2: intro z samą stopą kończyło się na pierwszym uderzeniu
(stopa liczyła się jako „bas na stałe”) — 3/4 wzorców i 26/73 realnych
utworów; outro wypadało średnio 10 s za późno, w środku frazy.
"""
from __future__ import annotations

import numpy as np
import pytest

from selekta import cues
from tests import probka

SR = probka.SR
BPM = 128.0
TAKT = 4 * 60.0 / BPM          # 1,875 s
START = 0.5                    # pierwsza stopa


def _utwor(path, sekcje, wstep_pad_taktow=0):
    """sekcje: lista (liczba taktów, zestaw elementów); pad przed pierwszą stopą opcjonalny."""
    rng = np.random.default_rng(probka.ZIARNO)
    taktow = sum(n for n, _ in sekcje)
    poczatek = START + wstep_pad_taktow * TAKT
    n = int(SR * (poczatek + taktow * TAKT + 2.0))
    x = np.zeros(n)
    t = np.arange(n) / SR
    stopa, hihat = probka._stopa(SR), probka._hihat(SR, rng)
    okres = 60.0 / BPM
    pad = 0.08 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277.2 * t) + np.sin(2 * np.pi * 329.6 * t))
    # linia basu wyraźnie cichsza od stopy — jak w realnych utworach; przy
    # tak ustawionym basie stara metoda („bas na stałe” ≤ 250 Hz) uznawała
    # samą stopę za wejście grooveu i kończyła intro na pierwszym uderzeniu
    bas = 0.1 * np.sin(2 * np.pi * 55 * t)
    if wstep_pad_taktow:
        a, b = int(START * SR), int(poczatek * SR)
        x[a:b] += pad[a:b]
    t0 = poczatek
    for liczba, elementy in sekcje:
        a, b = int(t0 * SR), int((t0 + liczba * TAKT) * SR)
        if "bas" in elementy:
            x[a:b] += bas[a:b]
        if "pad" in elementy:
            x[a:b] += pad[a:b]
        for k in range(liczba * 4):
            i = int((t0 + k * okres) * SR)
            if "stopa" in elementy:
                x[i:i + len(stopa)] += stopa[: max(0, min(len(stopa), n - i))]
            j = int((t0 + (k + 0.5) * okres) * SR)
            if "hihat" in elementy:
                x[j:j + len(hihat)] += 0.4 * hihat[: max(0, min(len(hihat), n - j))]
        t0 += liczba * TAKT
    x = x / np.max(np.abs(x)) * 0.9
    return probka._zapisz_wav(x, path), poczatek


BEZ_BASU = {"stopa", "hihat"}
PELNY = {"stopa", "hihat", "bas", "pad"}


def test_intro_z_sama_stopa_konczy_sie_na_wejsciu_basu(tmp_path):
    p, poczatek = _utwor(str(tmp_path / "a.wav"), [(16, BEZ_BASU), (32, PELNY), (8, BEZ_BASU)])
    c = cues.analyze(p, bpm=BPM)
    oczekiwane = poczatek + 16 * TAKT
    assert abs(c.intro_end_s - oczekiwane) <= TAKT, (c.intro_end_s, oczekiwane)
    assert c.intro_end_s - c.first_beat_s > 10.0          # NIE na pierwszym uderzeniu


def test_outro_na_granicy_frazy(tmp_path):
    p, poczatek = _utwor(str(tmp_path / "b.wav"), [(16, BEZ_BASU), (32, PELNY), (8, BEZ_BASU)])
    c = cues.analyze(p, bpm=BPM)
    oczekiwane = poczatek + 48 * TAKT
    assert abs(c.outro_start_s - oczekiwane) <= TAKT, (c.outro_start_s, oczekiwane)


def test_intro_bez_stopy_konczy_sie_na_pierwszej_stopie(tmp_path):
    """Pad przez 4 takty, potem od razu pełny bit: intro to sam pad."""
    p, poczatek = _utwor(str(tmp_path / "c.wav"), [(40, PELNY)], wstep_pad_taktow=4)
    c = cues.analyze(p, bpm=BPM)
    assert abs(c.intro_end_s - poczatek) <= TAKT, (c.intro_end_s, poczatek)


def test_utwor_bez_intra(tmp_path):
    """Pełny bit od pierwszej stopy — intra nie ma, koniec intra ≈ pierwsze uderzenie."""
    p, poczatek = _utwor(str(tmp_path / "d.wav"), [(40, PELNY)])
    c = cues.analyze(p, bpm=BPM)
    assert c.intro_end_s - c.first_beat_s <= TAKT, (c.intro_end_s, c.first_beat_s)


def test_bez_tempa_dziala_stara_metoda(tmp_path):
    p, _ = _utwor(str(tmp_path / "e.wav"), [(8, BEZ_BASU), (16, PELNY)])
    c = cues.analyze(p, bpm=None)
    assert 0.0 <= c.first_beat_s < c.intro_end_s < c.outro_start_s <= c.duration_s
