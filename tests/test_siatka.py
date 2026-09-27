"""Siatka beatów ma leżeć na STOPIE — nie na hi-hacie, nie o pół bitu obok.

Regresja z 5.09.2026: set „speeding" (51 utworów hard techno / hard house)
wrócił z rekordboxa z siatkami przesuniętymi o pół bitu w 23 przypadkach.
Dawna faza siatki szła ze spektralnego fluxu, a ten liczy każdy ostry
transjent tak samo — otwarty hi-hat na „i" jest ostrzejszy od stopy,
więc prążek tempa wskazywał hi-haty. Tu jest ten dokładny przypadek jako
wzorzec syntetyczny o ZNANEJ odpowiedzi.

Wszystkie wartości oczekiwane wynikają z konstrukcji sygnału, nie z tego,
„co wyszło ostatnio".
"""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from selekta import cache, cues, siatka
from tests import probka

SR = cues.SR


def _dekoduj(path: str, sr: int = SR) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def _blad_fazy_ms(kotwica: float, prawda: float, bpm: float) -> float:
    """Odległość kotwicy od najbliższej prawdziwej stopy, w ms (cyklicznie)."""
    okres = 60.0 / bpm
    r = (kotwica - prawda) / okres
    return abs((r - round(r)) * okres) * 1000


@pytest.fixture(scope="module")
def wzorce(tmp_path_factory):
    d = tmp_path_factory.mktemp("siatka")
    p = lambda n: str(d / n)                                   # noqa: E731
    return {
        # sama stopa — przypadek bazowy
        "stopa_128": (probka.bit_klubowy(p("a.wav"), 128.0, 0.500), 128.0, 0.500),
        # hi-hat na „i" GŁOŚNIEJSZY od stopy — przypadek z setu „speeding"
        "hat_glosny_150": (probka.bit_klubowy(p("b.wav"), 150.0, 0.250, hihat=4.0), 150.0, 0.250),
        "hat_glosny_140": (probka.bit_klubowy(p("c.wav"), 140.0, 0.420, hihat=3.0), 140.0, 0.420),
        # tempo niecałkowite ma zostać niecałkowite
        "niecalk_143_85": (probka.bit_klubowy(p("d.wav"), 143.85, 0.700, hihat=0.6), 143.85, 0.700),
        # cisza na początku: kotwica nie może wypaść w ciszy
        "cisza_5s": (probka.bit_klubowy(p("e.wav"), 150.0, 0.100, hihat=1.0, cisza=5.0), 150.0, 5.100),
    }


class TestKotwicaNaStopie:
    @pytest.mark.parametrize("klucz", ["stopa_128", "hat_glosny_150", "hat_glosny_140",
                                       "niecalk_143_85", "cisza_5s"])
    def test_kotwica_lezy_na_stopie(self, wzorce, klucz):
        path, bpm, prawda = wzorce[klucz]
        s = siatka.oszacuj(_dekoduj(path), SR, bpm_hint=bpm)
        assert s is not None
        blad = _blad_fazy_ms(s.first_beat_s, prawda, bpm)
        assert blad < 8.0, f"kotwica {s.first_beat_s} obok stopy o {blad:.1f} ms"
        assert s.pewnosc > 0.9

    def test_hihat_glosniejszy_nie_przeciaga_siatki_o_pol_bitu(self, wzorce):
        """Sedno regresji: dawny algorytm dawał tu ~+196 ms = pół bitu przy 150 BPM."""
        path, bpm, prawda = wzorce["hat_glosny_150"]
        c = cues.analyze(path, bpm=bpm)
        assert _blad_fazy_ms(c.first_beat_s, prawda, bpm) < 8.0

    def test_kotwica_nie_wypada_w_ciszy(self, wzorce):
        path, bpm, prawda = wzorce["cisza_5s"]
        s = siatka.oszacuj(_dekoduj(path), SR, bpm_hint=bpm)
        assert s.first_beat_s >= prawda - 0.01

    def test_bez_stop_zwraca_none(self, tmp_path):
        """Ambient bez uderzeń: nie zmyślamy siatki, cues bierze zapasową metodę."""
        p = probka.ton(str(tmp_path / "ton.wav"), 220.0, 30.0, 0.4)
        assert siatka.oszacuj(_dekoduj(p), SR, bpm_hint=120.0) is None
        c = cues.analyze(p, bpm=120.0)
        assert c.bpm_siatki is None and c.pewnosc_siatki is None and c.battito == 1


class TestTempoSiatki:
    def test_dostraja_bpm_mimo_nietrafionej_podpowiedzi(self, wzorce):
        """harmonic zaokrągla do 0,1 i potrafi minąć się o ułamek; siatka ma to poprawić."""
        path, bpm, _ = wzorce["stopa_128"]
        s = siatka.oszacuj(_dekoduj(path), SR, bpm_hint=bpm + 0.7)
        assert s.bpm == 128.0

    def test_tempo_calkowite_zostaje_calkowite(self, wzorce):
        path, bpm, _ = wzorce["hat_glosny_150"]
        assert siatka.oszacuj(_dekoduj(path), SR, bpm_hint=150.3).bpm == 150.0

    def test_tempo_niecalkowite_zostaje_niecalkowite(self, wzorce):
        path, bpm, _ = wzorce["niecalk_143_85"]
        s = siatka.oszacuj(_dekoduj(path), SR, bpm_hint=144.0)
        assert abs(s.bpm - 143.85) < 0.01, s.bpm

    def test_cues_niesie_bpm_siatki(self, wzorce):
        path, bpm, _ = wzorce["stopa_128"]
        c = cues.analyze(path, bpm=128.4)
        assert c.bpm_siatki == 128.0 and c.pewnosc_siatki > 0.9


class TestJedynkaTaktu:
    @pytest.mark.parametrize("jedynka,bpm,faza", [(0, 150.0, 0.30), (2, 128.0, 0.61), (3, 155.0, 0.15)])
    def test_battito_wskazuje_prawdziwa_jedynke(self, tmp_path, jedynka, bpm, faza):
        """Crash na jedynce co 16 bitów + fill przed jedynką frazy: rekordbox
        ma liczyć takty od właściwego bitu, a nie zawsze od kotwicy."""
        p = probka.bit_klubowy(str(tmp_path / f"t{jedynka}.wav"), bpm, faza,
                               sekund=90.0, hihat=1.5, crash=1.2, jedynka=jedynka)
        s = siatka.oszacuj(_dekoduj(p), SR, bpm_hint=bpm)
        okres = 60.0 / bpm
        jedynka_wg_siatki = s.first_beat_s + ((1 - s.battito) % 4) * okres
        prawdziwa = faza + jedynka * okres
        roznica = round((jedynka_wg_siatki - prawdziwa) / okres) % 4
        assert roznica == 0, f"battito {s.battito} przy kotwicy {s.first_beat_s}"
        assert s.pewnosc_taktu > 0.5

    def test_bez_dowodow_zostaje_jedynka(self, wzorce):
        path, bpm, _ = wzorce["stopa_128"]
        s = siatka.oszacuj(_dekoduj(path), SR, bpm_hint=bpm)
        assert s.battito == 1 and s.pewnosc_taktu == 0.0

    def test_battito_dla(self):
        assert [siatka.battito_dla(b) for b in range(4)] == [1, 4, 3, 2]


class TestEksportSiatki:
    def test_xml_dostaje_battito_i_bpm_siatki(self, tmp_path, monkeypatch):
        """Eksport bierze BPM dostrojone do stopy, nie tag „137.81" z pliku."""
        import xml.etree.ElementTree as ET
        from selekta import dj_export
        p = probka.bit_klubowy(str(tmp_path / "u.wav"), 128.0, 0.5, sekund=40.0)
        monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"), raising=False)
        cache.put(p, "harmonic", {"bpm": 128.4, "key": "Am", "camelot": "8A",
                                  "confidence_bpm": 0.5, "confidence_key": 0.5})
        cache.put(p, "cues", {"first_beat_s": 0.5, "intro_end_s": 8.0, "outro_start_s": 30.0,
                              "drop_s": None, "duration_s": 40.0, "battito": 3,
                              "bpm_siatki": 128.0, "pewnosc_siatki": 0.9, "pewnosc_taktu": 0.8})
        track = {"path": p, "title": "T", "artist": "A", "duration_s": 40.0, "bpm": 137.81, "key": None}
        out = str(tmp_path / "set.xml")
        dj_export.to_rekordbox_xml(dj_export.wzbogac_o_siatke([track]), "set", out)
        tempo = ET.parse(out).getroot().find(".//COLLECTION/TRACK/TEMPO")
        assert tempo.get("Battito") == "3"
        assert tempo.get("Bpm") == "128.00" and tempo.get("Inizio") == "0.500"

    def test_niepewna_siatka_nie_nadpisuje_bpm(self, tmp_path, monkeypatch):
        import xml.etree.ElementTree as ET
        from selekta import dj_export
        p = probka.bit_klubowy(str(tmp_path / "u.wav"), 128.0, 0.5, sekund=40.0)
        monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"), raising=False)
        cache.put(p, "harmonic", {"bpm": 128.0, "key": "Am", "camelot": "8A",
                                  "confidence_bpm": 0.5, "confidence_key": 0.5})
        cache.put(p, "cues", {"first_beat_s": 0.5, "intro_end_s": 8.0, "outro_start_s": 30.0,
                              "drop_s": None, "duration_s": 40.0, "battito": 1,
                              "bpm_siatki": 127.0, "pewnosc_siatki": 0.1, "pewnosc_taktu": 0.0})
        track = {"path": p, "title": "T", "artist": "A", "duration_s": 40.0, "bpm": 128.0, "key": None}
        out = str(tmp_path / "set.xml")
        dj_export.to_rekordbox_xml(dj_export.wzbogac_o_siatke([track]), "set", out)
        assert ET.parse(out).getroot().find(".//COLLECTION/TRACK/TEMPO").get("Bpm") == "128.00"


class TestWersjaPamieci:
    def test_stare_kotwice_odpadly(self):
        """Wersja 2 liczyła fazę z fluxu (pół bitu obok) — wyniki muszą się przeliczyć."""
        assert cache.WERSJE["cues"] >= 3


class TestZnaneSlabosci:
    """Udokumentowane granice metody — test ma PAŚĆ, gdy granica zniknie
    (strict xfail), żeby ktoś nie zostawił nieaktualnej dokumentacji."""

    def _offbeat_bass(self, path: str, bpm: float, t0: float, poziom: float, sekund: float = 60.0) -> str:
        import wave, struct
        sr = probka.SR
        rng = np.random.default_rng(7)
        okres = 60.0 / bpm; n = int(sr * sekund); x = np.zeros(n)
        stopa = probka._stopa(sr); hat = probka._hihat(sr, rng)
        t = np.arange(int(0.25 * sr)) / sr
        bas = (np.sign(np.sin(2 * np.pi * 55 * t)) * 0.6 + 0.4 * np.sin(2 * np.pi * 55 * t)) * np.exp(-t / 0.12) * np.minimum(1, t / 0.004)
        i = 0
        while True:
            tb = t0 + i * okres; s = int(round(tb * sr))
            if s >= n: break
            x[s:s + len(stopa)] += stopa[:n - s]
            so = int(round((tb + okres / 2) * sr))
            if so < n:
                x[so:so + len(hat)] += 1.5 * hat[:n - so]
                if i >= 16: x[so:so + len(bas)] += poziom * bas[:n - so]
            i += 1
        return probka._zapisz_wav(0.8 * x / (np.abs(x).max() + 1e-9), path)

    def test_bas_na_i_rowny_stopie_nie_przeciaga(self, tmp_path):
        p = self._offbeat_bass(str(tmp_path / "b1.wav"), 135.0, 0.31, 1.0)
        s = siatka.oszacuj(_dekoduj(p), SR, bpm_hint=135.0)
        assert _blad_fazy_ms(s.first_beat_s, 0.31, 135.0) < 8.0

    @pytest.mark.xfail(strict=True, reason="znana słabość: tonalny bas na „i” ≥2× głośniejszy od stopy przeciąga siatkę")
    def test_bas_na_i_dwa_razy_glosniejszy(self, tmp_path):
        p = self._offbeat_bass(str(tmp_path / "b2.wav"), 135.0, 0.31, 2.0)
        s = siatka.oszacuj(_dekoduj(p), SR, bpm_hint=135.0)
        assert _blad_fazy_ms(s.first_beat_s, 0.31, 135.0) < 8.0
