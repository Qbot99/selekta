"""Rozkład biblioteki i luki w przejściach.

Sedno: sklep powie, co popularne. Nie powie, że masz czterdzieści kawałków
138 w 11A i ani jednego w 4A, więc z tego gniazda nie ma jak wyjść.
"""
from __future__ import annotations

import pytest

from selekta import statystyki as st


def _utwory(*pary):
    """(bpm, camelot) → lista utworów."""
    return [{"bpm": b, "camelot": k, "title": f"u{i}"} for i, (b, k) in enumerate(pary)]


class TestKoloCamelota:
    def test_rozbiera_poprawne_kody(self):
        assert st.rozbierz("8A") == (8, "A")
        assert st.rozbierz("12b") == (12, "B")

    def test_odrzuca_bledne(self):
        for zly in ("", "13A", "0A", "8C", "abc", None):
            assert st.rozbierz(zly) is None

    def test_zgodne_to_ta_sama_sasiednie_i_rownolegla(self):
        assert set(st.zgodne_tonacje("8A")) == {"8A", "9A", "7A", "8B"}

    def test_koło_zawija_sie_na_12(self):
        assert set(st.zgodne_tonacje("12A")) == {"12A", "1A", "11A", "12B"}
        assert set(st.zgodne_tonacje("1B")) == {"1B", "2B", "12B", "1A"}

    def test_bledna_tonacja_nie_ma_wyjsc(self):
        assert st.zgodne_tonacje("nonsens") == []


class TestZakresTempa:
    def test_miesci_sie_w_pitchu(self):
        assert st._pasuje_tempo(140, 145) is True       # +3.6%
        assert st._pasuje_tempo(140, 148) is True       # +5.7%

    def test_poza_pitchem_odpada(self):
        assert st._pasuje_tempo(140, 155) is False      # +10.7%
        assert st._pasuje_tempo(128, 150) is False

    def test_brak_tempa_to_brak_dopasowania(self):
        assert st._pasuje_tempo(0, 140) is False
        assert st._pasuje_tempo(140, None) is False


class TestLuki:
    def test_gniazdo_bez_wyjsc_jest_zgloszone(self):
        """Osiem utworów w 8A i nic zgodnego dookoła."""
        d = st.policz(_utwory(*[(140, "8A")] * 8))
        assert d["luki"], "brak wyjść musi zostać zgłoszony"
        luka = d["luki"][0]
        assert luka["tonacja"] == "8A" and luka["masz"] == 8
        assert {"9A", "7A", "8B"} <= set(luka["brakujace"])

    def test_gniazdo_z_wyjsciami_nie_jest_luka(self):
        d = st.policz(_utwory(
            *[(140, "8A")] * 6, *[(140, "9A")] * 4,
            *[(141, "7A")] * 4, *[(139, "8B")] * 4, *[(140, "8A")] * 4))
        assert not any(l["tonacja"] == "8A" and l["bpm"] == 140
                       for l in d["luki"])

    def test_wyjscie_poza_zakresem_pitcha_sie_nie_liczy(self):
        """Zgodna tonacja w innym tempie to nie jest wyjście."""
        d = st.policz(_utwory(*[(128, "8A")] * 8, *[(175, "9A")] * 10))
        luka = next(l for l in d["luki"] if l["tonacja"] == "8A")
        assert "9A" in luka["brakujace"], "175 BPM jest poza pitchem od 128"

    def test_male_gniazdo_nie_jest_raportowane(self):
        d = st.policz(_utwory(*[(140, "8A")] * 2))
        assert d["luki"] == []


class TestRozklady:
    def test_liczy_puste_tonacje(self):
        d = st.policz(_utwory((140, "8A")))
        assert len(d["puste_tonacje"]) == 23
        assert "8A" not in d["puste_tonacje"]

    def test_rozklad_obejmuje_cale_kolo(self):
        d = st.policz(_utwory((140, "8A")))
        assert len(d["rozklad_tonacji"]) == 24

    def test_utwory_bez_analizy_sa_pomijane(self):
        d = st.policz([{"bpm": None, "camelot": None, "title": "x"},
                       {"bpm": 140, "camelot": "8A", "title": "y"}])
        assert d["utworow"] == 2 and d["przeanalizowanych"] == 1

    def test_pusta_biblioteka_nie_wywala(self):
        d = st.policz([])
        assert d["przeanalizowanych"] == 0 and d["luki"] == []
        assert len(d["puste_tonacje"]) == 24
