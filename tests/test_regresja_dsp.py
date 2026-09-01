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
        "metronom85": probka.metronom(p("m85.wav"), 85.0, sekund=60),
        "metronom87": probka.metronom(p("m87.wav"), 87.0, sekund=60),
        "metronom126_5": probka.metronom(p("m1265.wav"), 126.5, sekund=60),
        "metronom140": probka.metronom(p("m140.wav"), 140.0, sekund=60),
        "metronom174": probka.metronom(p("m174.wav"), 174.0, sekund=60),
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
        ("metronom128", 128.0), ("metronom150", 150.0),
        # regresja z 1.09.2026 — te trzy były nietrafione: 85 wychodziło
        # jako 169.5 (prior wciągał na podwojone tempo), 140 jako 139.7
        # i 126.5 jako 126.0 (załamania interpolacji liniowej autokorelacji)
        ("metronom85", 85.0), ("metronom126_5", 126.5), ("metronom140", 140.0),
        # te dwa pilnują, żeby strażnik oktawy nie przesadził w drugą
        # stronę: szybkie tempa mają zostać szybkie
        ("metronom87", 87.0), ("metronom174", 174.0)])
    def test_bpm_metronomu_jest_dokladne(self, wzorce, klucz, oczekiwane):
        a = harmonic.analyze(wzorce[klucz])
        assert abs(a.bpm - oczekiwane) <= 0.1, f"{a.bpm} zamiast {oczekiwane}"

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


class TestTonacja:
    """Detekcja tonacji — jedyny wynik, którego wcześniej nic nie pilnowało.

    Wzorce mają tonację ZNANĄ z teorii muzyki: trójdźwięk durowy ma tercję
    wielką, molowy małą, a kadencja I-IV-V-I rozstrzyga tonację jednoznacznie.
    Nie sprawdzamy więc „czy tak jak ostatnio", tylko czy detektor odczytuje
    to, co w sygnale naprawdę jest.

    Sprawdzian jest ostry celowo: trafienie w jedną tonację bywa przypadkiem,
    trafienie we wszystkie dwadzieścia cztery nie jest.
    """

    def _oczekiwany_camelot(self, tonika: str, tryb: str) -> str:
        tabela = (harmonic._CAMELOT_MAJOR if tryb == "dur"
                  else harmonic._CAMELOT_MINOR)
        return tabela[tonika]

    @pytest.mark.parametrize("tryb", ["dur", "mol"])
    @pytest.mark.parametrize("tonika", probka.NAZWY_NUT)
    def test_kazda_tonacja_jest_rozpoznana(self, tmp_path, tonika, tryb):
        plik = probka.akord_tonalny(
            str(tmp_path / f"{tonika}_{tryb}.wav"), tonika, tryb, sekund=12.0)
        a = harmonic.analyze(plik)
        oczekiwany = self._oczekiwany_camelot(tonika, tryb)
        assert a.camelot == oczekiwany, (
            f"{tonika} {tryb}: wykryto {a.camelot} ({a.key}), "
            f"oczekiwano {oczekiwany}")

    def test_tercja_decyduje_o_trybie(self, tmp_path):
        """Ten sam bas i kwinta — różni je wyłącznie tercja.

        To najostrzejszy sprawdzian rozróżniania dur/mol: sygnały dzielą
        dwie z trzech nut, więc pomyłka w tercji przechodzi niezauważona
        w każdym łagodniejszym teście.
        """
        dur = harmonic.analyze(probka.akord_tonalny(
            str(tmp_path / "dur.wav"), "A", "dur", sekund=12.0))
        mol = harmonic.analyze(probka.akord_tonalny(
            str(tmp_path / "mol.wav"), "A", "mol", sekund=12.0))
        assert dur.camelot == "11B" and dur.key == "A major"
        assert mol.camelot == "8A" and mol.key == "A minor"

    def test_kadencja_tez_trafia(self, tmp_path):
        """Materiał najbliższy prawdziwej muzyce — progresja I-IV-V-I."""
        for tonika, tryb, oczekiwany in (("C", "dur", "8B"),
                                         ("A", "mol", "8A"),
                                         ("F#", "dur", "2B")):
            a = harmonic.analyze(probka.kadencja(
                str(tmp_path / f"k_{tonika}_{tryb}.wav"), tonika, tryb,
                na_akord=2.0, powtorzen=2))
            assert a.camelot == oczekiwany, f"{tonika} {tryb} → {a.camelot}"

    def test_pewnosc_jest_wysoka_dla_jednoznacznego_materialu(self, tmp_path):
        """Zmierzone: wzorce dają pewność 1,000 we wszystkich 24 tonacjach.

        Próg 0,6 zostawia zapas na zmiany w chromagramie, ale wyłapie
        sytuację, w której detektor zaczyna zgadywać.
        """
        a = harmonic.analyze(probka.akord_tonalny(
            str(tmp_path / "p.wav"), "D", "mol", sekund=12.0))
        assert a.confidence_key >= 0.6, a.confidence_key

    def test_korelacja_z_profilem_jest_pilnowana(self, tmp_path):
        """Sam werdykt to za mało — pilnujemy LICZBY, która za nim stoi.

        Odkryte przy budowie tego wzorca: stała FIFTH_DISCOUNT (odejmowanie
        przecieku trzeciej harmonicznej) przesuwa korelację, ale NIE zmienia
        zwycięskiej tonacji. Test patrzący tylko na .camelot przepuszcza taką
        zmianę bez szmeru, choć realnie przestraja detektor.

        Zmierzone dla C-dur, składowa G w chromagramie i korelacja:
            0.0 → G=12.41, r=0.8888
            0.3 → G= 7.02, r=0.8468   (wartość obecna)
            1.0 → G= 0.00, r=0.7219
        Pasmo ±0,02 rozdziela te przypadki z zapasem.

        UWAGA przy ręcznym sprawdzaniu: podmiana stałej na wartość o tej
        samej długości (0.3 → 1.0) nie zmienia rozmiaru pliku, więc Python
        potrafi wczytać zbuforowany bajtkod i pokazać STARY wynik. Trzeba
        uruchamiać z -B albo kasować __pycache__ — inaczej wyjdzie fałszywy
        wniosek, że stała nic nie robi.
        """
        plik = probka.akord_tonalny(str(tmp_path / "k.wav"), "C", "dur",
                                    sekund=12.0)
        x = harmonic._decode(plik, harmonic.SR, 0, 12.0)
        chroma = harmonic._chroma_from_signal(x)
        tonika, tryb, r_najlepsze, _r_drugie = harmonic._best_key(chroma)

        assert harmonic.NOTE_NAMES[tonika] == "C" and tryb == "major"
        assert abs(r_najlepsze - 0.8468) < 0.02, (
            f"korelacja {r_najlepsze:.4f} zamiast ~0.8468 — coś przestroiło "
            f"tor chromagramu (FIFTH_DISCOUNT? pasmo? strojenie?), "
            f"mimo że wykryta tonacja się nie zmieniła")

    def test_tonacja_jest_powtarzalna(self, tmp_path):
        plik = probka.akord_tonalny(str(tmp_path / "r.wav"), "G", "dur",
                                    sekund=12.0)
        a, b = harmonic.analyze(plik), harmonic.analyze(plik)
        assert (a.camelot, a.key) == (b.camelot, b.key)
