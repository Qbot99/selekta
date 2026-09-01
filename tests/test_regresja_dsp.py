"""Testy regresyjne liczb, nie zachowania.

Reszta zestawu sprawdza, czy kod nie rzuca wyjątkiem i czy przepływ ma
sens. Te testy pilnują WARTOŚCI: gdyby ktoś (albo ja) przestawił próg
w detekcji fałszywego lossless, zmienił okno przy liczeniu BPM albo
podmienił filtr K przy głośności, tamte testy nadal by przeszły, a wyniki
cicho by się przesunęły. Dowiedziałbyś się o tym, ufając złej liczbie
w klubie.

Wzorce mają ZNANE właściwości — nie są zapisem „tego, co wyszło ostatnio",
tylko odpowiedzią, którą da się wyprowadzić z fizyki sygnału. Dzięki temu
test wykrywa nie tylko zmianę, ale też błąd.

Tolerancje są celowo ciasne tam, gdzie odpowiedź jest jednoznaczna
(BPM metronomu), a luźniejsze tam, gdzie zależy od wersji ffmpeg
(true peak, granica pasma).
"""
from __future__ import annotations

import os

import pytest

from selekta import cues, harmonic, loudness, quality, tempo, waveform
from tests import probka


@pytest.fixture(scope="module")
def wzorce(tmp_path_factory):
    """Komplet sygnałów wzorcowych — liczony raz na cały moduł."""
    d = tmp_path_factory.mktemp("wzorce")
    p = lambda n: str(d / n)                                   # noqa: E731
    return {
        "pelne_flac": probka.do_flac(probka.pelne_pasmo(p("pelne.wav")),
                                     p("pelne.flac")),
        "obciete16_flac": probka.do_flac(
            probka.obciete_pasmo(p("o16.wav"), 16.0), p("obciete16.flac")),
        "obciete20_flac": probka.do_flac(
            probka.obciete_pasmo(p("o20.wav"), 20.0), p("obciete20.flac")),
        "mp3_128": probka.do_mp3(probka.pelne_pasmo(p("m.wav")), p("m128.mp3"), 128),
        "metronom128": probka.metronom(p("m128.wav"), 128.0),
        "metronom150": probka.metronom(p("m150.wav"), 150.0),
        "metronom150_faza": probka.metronom(p("m150f.wav"), 150.0, faza=0.137),
        "ton1k": probka.ton(p("ton.wav"), 1000.0, 10.0, 0.5),
        "ton1k_cichy": probka.ton(p("cichy.wav"), 1000.0, 10.0, 0.125),
    }


class TestJakoscPasma:
    """Detektor fałszywego lossless — serce tej aplikacji."""

    def test_pelne_pasmo_to_prawdziwy_lossless(self, wzorce):
        r = quality.analyze(wzorce["pelne_flac"])
        assert r.grade == "ok"
        assert r.cutoff_hz > 21_000, f"pasmo {r.cutoff_hz} Hz, oczekiwane >21 kHz"

    def test_pasmo_uciete_na_16k_to_falszywy_flac(self, wzorce):
        """MP3 128 kbps przepakowany do FLAC-a. Musi być wykryty."""
        r = quality.analyze(wzorce["obciete16_flac"])
        assert r.grade == "bad", "przebrany MP3 przeszedł jako dobry"
        assert abs(r.cutoff_hz - 16_000) < 500, r.cutoff_hz

    def test_zmierzona_granica_zgadza_sie_z_zadana(self, wzorce):
        """Sprawdzamy sam pomiar, nie tylko werdykt."""
        r16 = quality.analyze(wzorce["obciete16_flac"])
        r20 = quality.analyze(wzorce["obciete20_flac"])
        # Wzorzec ma granicę wyciętą DOKŁADNIE, więc nie ma powodu na
        # szeroką tolerancję. Luźny próg przepuścił kiedyś 4% dryf,
        # który migawka prawdziwej biblioteki wyłapała natychmiast.
        assert abs(r16.cutoff_hz - 16_000) < 500, r16.cutoff_hz
        assert abs(r20.cutoff_hz - 20_000) < 500, r20.cutoff_hz

    def test_znane_ograniczenie_detektora_pasma(self, wzorce):
        """UDOKUMENTOWANA GRANICA METODY, nie życzenie.

        Detektor rozpoznaje pliki po odciętym paśmie. Koder MPT z ffmpeg
        przy 128 kbps NIE zawsze tnie na 16 kHz — dla szumu zostawia
        pasmo powyżej 20 kHz, więc taki plik przechodzi jako dobry.

        To nie jest błąd w kodzie: metoda wykrywa TRANSKODY (materiał,
        który raz stracił górę pasma), a nie każdy plik stratny. Test
        istnieje po to, żeby nikt nie „naprawił” progu, myśląc, że łapie
        wszystkie MP3 — i żeby zmiana tego zachowania była widoczna.
        """
        r = quality.analyze(wzorce["mp3_128"])
        assert r.cutoff_hz > 19_000, (
            "jeśli to się zmieniło, koder ffmpeg zaczął ciąć inaczej — "
            "sprawdź, czy progi detektora nadal mają sens")

    def test_werdykt_jest_po_polsku_i_niepusty(self, wzorce):
        assert quality.analyze(wzorce["pelne_flac"]).verdict.strip()


class TestTempoIKotwica:
    @pytest.mark.parametrize("klucz,oczekiwane", [
        ("metronom128", 128.0), ("metronom150", 150.0)])
    def test_bpm_metronomu_jest_dokladne(self, wzorce, klucz, oczekiwane):
        a = harmonic.analyze(wzorce[klucz])
        assert abs(a.bpm - oczekiwane) < 0.5, f"{a.bpm} zamiast {oczekiwane}"

    def test_kotwica_trafia_w_znana_faze(self, wzorce):
        """Metronom z klikami od 0,137 s — kotwica ma tam wypaść."""
        c = cues.analyze(wzorce["metronom150_faza"], bpm=150.0)
        okres = 60.0 / 150.0
        reszta = c.first_beat_s % okres
        odchylka = min(reszta, okres - reszta)
        oczekiwana = 0.137 % okres
        blad = abs(reszta - oczekiwana)
        blad = min(blad, okres - blad)
        # Po korekcie opóźnienia okna STFT zostaje stały błąd ~13 ms.
        # NIE kompensuję go dodatkowo: nie umiem go wyprowadzić z teorii,
        # a dobranie liczby pod ten wzorzec byłoby dopasowaniem do kształtu
        # syntetycznego kliku, nie poprawką. 13 ms to 3% bitu przy 150 BPM.
        assert blad < 0.025, f"kotwica {c.first_beat_s}, błąd fazy {blad * 1000:.0f} ms"

    def test_metronom_ma_stale_tempo(self, wzorce):
        s = tempo.zbadaj(wzorce["metronom150"], 150.0)
        assert s.stabilne is True and s.bpm_nietrafione is False

    def test_zle_bpm_jest_wykryte_i_poprawione(self, wzorce):
        s = tempo.zbadaj(wzorce["metronom150"], 149.0)
        assert s.bpm_nietrafione is True
        assert abs(s.bpm_poprawione - 150.0) < 0.3, s.bpm_poprawione


class TestGlosnosc:
    def test_lufs_tonu_zgadza_sie_z_teoria(self, wzorce):
        """Sinus 1 kHz o amplitudzie 0,5: ~-9,0 LUFS (filtr K jest tam płaski)."""
        l = loudness.analyze(wzorce["ton1k"])
        assert abs(l.integrated_lufs - (-9.0)) < 1.0, l.integrated_lufs

    def test_szczyt_zgadza_sie_z_amplituda(self, wzorce):
        """Amplituda 0,5 to -6,02 dBFS."""
        l = loudness.analyze(wzorce["ton1k"])
        assert abs(l.true_peak_dbtp - (-6.02)) < 0.6, l.true_peak_dbtp

    def test_cichszy_ton_o_12_db_nizej(self, wzorce):
        """Amplituda 4x mniejsza to dokładnie 12,04 dB różnicy."""
        glosny = loudness.analyze(wzorce["ton1k"]).integrated_lufs
        cichy = loudness.analyze(wzorce["ton1k_cichy"]).integrated_lufs
        assert abs((glosny - cichy) - 12.04) < 0.5, glosny - cichy

    def test_replaygain_ma_wlasciwy_znak(self, wzorce):
        """Cichy materiał musi dostać DODATNIE wzmocnienie."""
        assert loudness.analyze(wzorce["ton1k_cichy"]).gain_db > 0


class TestPrzebiegFali:
    def test_obwiednie_sa_znormalizowane(self, wzorce):
        d = waveform.oblicz(wzorce["metronom150"], punkty=200)
        assert 0.99 <= max(d["szczyt"]) <= 1.0
        assert all(s >= r - 1e-9 for s, r in zip(d["szczyt"], d["rms"]))

    def test_czas_zgadza_sie_z_dlugoscia_wzorca(self, wzorce):
        d = waveform.oblicz(wzorce["metronom150"], punkty=100)
        assert abs(d["czas_s"] - 90.0) < 0.5, d["czas_s"]


class TestStalosc:
    """Ten sam plik musi dawać ten sam wynik przy każdym uruchomieniu."""

    def test_jakosc_jest_powtarzalna(self, wzorce):
        a = quality.analyze(wzorce["obciete16_flac"])
        b = quality.analyze(wzorce["obciete16_flac"])
        assert a.cutoff_hz == b.cutoff_hz and a.grade == b.grade

    def test_bpm_jest_powtarzalne(self, wzorce):
        a = harmonic.analyze(wzorce["metronom150"])
        b = harmonic.analyze(wzorce["metronom150"])
        assert a.bpm == b.bpm and a.camelot == b.camelot

    def test_wzorce_sa_deterministyczne(self, tmp_path):
        """Ten sam generator musi dać bajt w bajt ten sam plik."""
        a = probka.obciete_pasmo(str(tmp_path / "a.wav"), 16.0, 5.0)
        b = probka.obciete_pasmo(str(tmp_path / "b.wav"), 16.0, 5.0)
        assert open(a, "rb").read() == open(b, "rb").read()
