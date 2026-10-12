"""Energia i struktura — druga połowa układania setu.

Porządkowanie harmoniczne mówi, KTÓRE utwory da się złożyć. Te testy
pilnują tego, co mówi, w JAKIEJ KOLEJNOŚCI set ma sens — i że analiza
działa na wskazanym secie, nie tylko na całej bibliotece.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from selekta import energia, web
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def _set(*energie):
    return [{"file": f"u{i}.flac", "title": f"Utwor {i}", "srednia": e}
            for i, e in enumerate(energie)]


class TestGraniceFraz:
    def test_frazy_leza_na_wielokrotnosci_taktow(self):
        """16 taktów przy 150 BPM to 25,6 s."""
        g = energia.granice_fraz(120, 150, 0.0)
        assert g[0] == 0.0
        assert abs((g[1] - g[0]) - 25.6) < 0.01

    def test_frazy_startuja_od_kotwicy(self):
        g = energia.granice_fraz(120, 150, 1.8)
        assert g[0] == 1.8

    def test_bez_bpm_nie_ma_fraz(self):
        assert energia.granice_fraz(120, None, 0) == []
        assert energia.granice_fraz(120, 0, 0) == []

    def test_zerowa_dlugosc_nie_wywala(self):
        assert energia.granice_fraz(0, 150, 0) == []

    def test_32_takty_sa_dwa_razy_rzadsze(self):
        a = energia.granice_fraz(300, 150, 0, taktow=16)
        b = energia.granice_fraz(300, 150, 0, taktow=32)
        assert len(a) == 2 * len(b) or len(a) - 1 == 2 * len(b) - 1


class TestLukSetu:
    def test_wykrywa_wczesna_kulminacje(self):
        uwagi = energia.luk_setu(_set(.4, .9, .5, .5, .45, .4, .4, .35))["uwagi"]
        assert any(u["typ"] == "wczesna-kulminacja" for u in uwagi)

    def test_wykrywa_dziure_w_srodku(self):
        uwagi = energia.luk_setu(_set(.4, .5, .6, .30, .62, .7, .75))["uwagi"]
        dziura = next(u for u in uwagi if u["typ"] == "dziura")
        assert dziura["pozycja"] == 3

    def test_wykrywa_plaski_set(self):
        uwagi = energia.luk_setu(_set(.5, .52, .51, .5, .53, .51, .5))["uwagi"]
        assert any(u["typ"] == "plaski" for u in uwagi)

    def test_narastajacy_set_bez_uwag(self):
        r = energia.luk_setu(_set(.35, .42, .5, .58, .66, .74, .82))
        assert r["uwagi"] == []
        assert r["kulminacja"] == 6, "kulminacja na końcu"

    def test_pusty_set_nie_wywala(self):
        assert energia.luk_setu([])["uwagi"] == []

    def test_jeden_utwor_nie_generuje_uwag(self):
        assert energia.luk_setu(_set(.5))["uwagi"] == []


class TestFazaUtworu:
    def _s(self, **kw):
        s = energia.Struktura(czas_s=300)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_glosny_jasny_i_gesty_to_kulminacja(self):
        assert energia._faza(self._s(srednia=.7, jasnosc=3.0,
                                     gestosc_perkusji=6.0)) == "kulminacja"

    def test_cichy_i_rzadki_to_rozgrzewka(self):
        assert energia._faza(self._s(srednia=.3, jasnosc=1.1,
                                     gestosc_perkusji=2.0)) == "rozgrzewka"

    def test_duzy_breakdown_odbiera_punkt(self):
        """Głośny, ale w połowie pusty — to nie jest szczyt setu."""
        pelny = self._s(srednia=.7, jasnosc=3.0, gestosc_perkusji=6.0,
                        breakdown_s=10)
        dziurawy = self._s(srednia=.7, jasnosc=3.0, gestosc_perkusji=6.0,
                           breakdown_s=120)
        assert energia._faza(pelny) == "kulminacja"
        assert energia._faza(dziurawy) != "kulminacja"


class TestZakresAnalizy:
    """Najważniejsze: analiza ma działać na WSKAZANYM secie."""

    def test_zaznaczenie_ogranicza_zakres(self, client):
        """Statystyki liczą tylko utwory z analizą — suma musi się zgadzać
        z liczbą plików w zakresie, nie z całą biblioteką."""
        d = client.post("/api/statystyki", json={"files": [GOOD_MP3]}).json()
        assert d["zakres"] == "zaznaczenie"
        assert d["przeanalizowanych"] + d["bez_analizy"] == 1

    def test_brak_ciala_to_cala_biblioteka(self, client):
        d = client.post("/api/statystyki", json={}).json()
        assert d["zakres"] == "cała biblioteka"
        assert d["przeanalizowanych"] + d["bez_analizy"] > 1

    def test_zaznaczenie_jest_wezsze_niz_biblioteka(self, client):
        jeden = client.post("/api/statystyki", json={"files": [GOOD_MP3]}).json()
        wszystko = client.post("/api/statystyki", json={}).json()
        assert (jeden["przeanalizowanych"] + jeden["bez_analizy"]
                < wszystko["przeanalizowanych"] + wszystko["bez_analizy"])

    def test_nieznana_playlista_to_czytelny_blad(self, client):
        r = client.post("/api/statystyki", json={"name": "nie-ma-takiej"})
        assert r.status_code == 404

    def test_energia_dla_zaznaczenia(self, client):
        d = client.post("/api/energia", json={"files": [GOOD_MP3, GOOD_FLAC]}).json()
        assert d["zakres"] == "zaznaczenie" and d["utworow"] == 2
        assert len(d["punkty"]) == 2
        assert all("faza" in u and "intro_typ" in u for u in d["utwory"])

    def test_energia_odrzuca_pusty_zakres(self, client):
        r = client.post("/api/energia", json={"files": ["nie-ma-takiego.flac"]})
        assert r.status_code == 400

    def test_pliki_spoza_biblioteki_sa_pomijane(self, client):
        r = client.post("/api/energia", json={"files": ["../../etc/hosts"]})
        assert r.status_code == 400


class TestJasnosc:
    """Centroida widma na sygnałach o znanej barwie.

    Regresja z 1.09.2026: oś częstotliwości była budowana z liczby KLATEK
    zamiast liczby PRĄŻKÓW, przez co funkcja liczyła centroidę czasową
    (kiedy gra dźwięk), a nie widmową (jak wysoko brzmi) — i każdy
    stacjonarny sygnał dostawał identyczne ~SR/4 niezależnie od barwy.
    """

    def _sinus(self, hz, sekund=8.0):
        t = np.arange(int(energia.SR * sekund)) / energia.SR
        return 0.5 * np.sin(2 * np.pi * hz * t)

    def test_niski_ton_to_niska_centroida(self):
        assert energia._jasnosc_khz(self._sinus(200)) == pytest.approx(0.2, abs=0.05)

    def test_wysoki_ton_to_wysoka_centroida(self):
        assert energia._jasnosc_khz(self._sinus(3000)) == pytest.approx(3.0, abs=0.1)

    def test_barwa_a_nie_polozenie_w_czasie(self):
        """Rozstrzygający kontrtest z weryfikacji: ton grający tylko w
        pierwszej ćwiartce utworu ma mieć tę samą centroidę co grający cały
        czas — liczy się wysokość, nie moment."""
        caly = self._sinus(400, 8.0)
        cwiartka = caly.copy()
        cwiartka[len(cwiartka) // 4:] = 0.0
        pelna = energia._jasnosc_khz(caly)
        ucieta = energia._jasnosc_khz(cwiartka)
        assert pelna == pytest.approx(0.4, abs=0.05)
        assert ucieta == pytest.approx(pelna, abs=0.05)

    def test_ciemne_vs_jasne_rozdzielone_progiem_faz(self):
        """Próg 1.4 kHz w _intro/_faza (z pomiarów na realnej bibliotece:
        utwory klubowe 1.16-1.54) ma rozdzielać ciemny pad od jasnej
        perkusji — przed naprawą osi wszystko było 'jasne' (2.76)."""
        rng = np.random.default_rng(7)
        ciemny_pad = self._sinus(150) + 0.3 * self._sinus(300)
        jasny_szum = rng.standard_normal(int(energia.SR * 8.0)) * 0.3
        assert energia._jasnosc_khz(ciemny_pad) < 1.4
        assert energia._jasnosc_khz(jasny_szum) > 1.4


class TestGestoscPerkusji:
    """Regresja z 1.09.2026: próg mediana+std łapał migotanie szumu i pad
    bez perkusji dostawał kilkanaście „uderzeń" na takt (a stąd zawyżoną
    fazę). Po przejściu na MAD i zbocza pad ma dawać zero."""

    def _flux(self, x):
        from selekta.cues import _envelopes
        return _envelopes(x.astype(np.float32))[2]

    def _pad(self, sekund=30.0):
        t = np.arange(int(energia.SR * sekund)) / energia.SR
        pad = (np.sin(2*np.pi*110*t) + 0.6*np.sin(2*np.pi*165*t)
               + 0.4*np.sin(2*np.pi*220*t))
        return pad * 0.4 * (1 + 0.3*np.sin(2*np.pi*0.1*t))

    def _bit(self, sekund=30.0):
        t = np.arange(int(energia.SR * sekund)) / energia.SR
        x = np.zeros_like(t)
        okres = int(energia.SR * 60 / 128)
        for i in range(0, len(t) - 2000, okres):
            x[i:i+800] += (np.sin(2*np.pi*55*np.arange(800)/energia.SR)
                           * np.exp(-np.arange(800)/200))
        rng = np.random.default_rng(3)
        x += 0.1*rng.standard_normal(len(t))*(np.arange(len(t)) % (okres//2) < 900)
        return x

    def test_pad_bez_perkusji_ma_zero(self):
        """Bramka okresowości: pad nie koreluje przy opóźnieniu bitu
        (zmierzone AC -0.56), więc gęstość ma być dokładnie 0."""
        assert energia._gestosc(self._flux(self._pad()), 128.0) == 0.0

    def test_bit_ma_pelna_gestosc(self):
        assert energia._gestosc(self._flux(self._bit()), 128.0) > 6.0

    def test_cichy_bit_tez_wykryty(self):
        assert energia._gestosc(self._flux(self._bit() * 0.05), 128.0) > 6.0

    def test_perkusja_na_tle_melodii_wykryta(self):
        miks = self._pad() * 0.7 + self._bit() * 0.5
        assert energia._gestosc(self._flux(miks), 128.0) > 6.0


# --------------------------------------------------------------------------
# energia bezwzględna — porównywalna między utworami
# --------------------------------------------------------------------------

_SR = 44100


def _utwor(sek=40, poziom_db=-8.0, breakdown=None, perkusja=True, bas=True, bpm=140.0):
    """Syntetyczny utwór o znanej budowie (jak w przeglądzie 0.4.2)."""
    rng = np.random.default_rng(1)
    n = int(_SR * sek)
    t = np.arange(n) / _SR
    x = np.zeros(n)
    okres = 60.0 / bpm
    if perkusja:
        for b in np.arange(0, sek, okres):
            i, dl = int(b * _SR), int(0.15 * _SR)
            if i + dl > n:
                break
            tt = np.arange(dl) / _SR
            x[i:i + dl] += np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18)
        for b in np.arange(okres / 2, sek, okres):
            i, dl = int(b * _SR), int(0.04 * _SR)
            if i + dl > n:
                break
            x[i:i + dl] += 0.3 * rng.standard_normal(dl) * np.exp(-np.arange(dl) / _SR * 80)
    if bas:
        x += 0.25 * np.sin(2 * np.pi * 55 * t)
    pad = 0.15 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277.2 * t)
                  + np.sin(2 * np.pi * 329.6 * t))
    x += pad
    if breakdown:
        a, b = int(breakdown[0] * _SR), int(breakdown[1] * _SR)
        x[a:b] = pad[a:b]
    return x / np.max(np.abs(x)) * 10 ** (poziom_db / 20)


def _wav(path, x):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(_SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


@pytest.fixture(scope="module")
def synt(tmp_path_factory):
    d = tmp_path_factory.mktemp("energia")
    pliki = {
        "bit": _wav(d / "bit.wav", _utwor()),
        "bit_cichy": _wav(d / "bit_cichy.wav", _utwor(poziom_db=-33.0)),
        "breakdown": _wav(d / "breakdown.wav", _utwor(sek=60, breakdown=(18, 42))),
        "pad": _wav(d / "pad.wav", _utwor(perkusja=False, bas=False, poziom_db=-20.0)),
        "pad_glosny": _wav(d / "pad_glosny.wav", _utwor(perkusja=False, bas=False)),
    }
    return {k: energia.analizuj(p, bpm=140.0) for k, p in pliki.items()}


class TestEnergiaBezwzgledna:
    """Przegląd 0.4.2: krzywa dzielona przez maksimum TEGO utworu — sam pad
    dostawał 1,0 (najwięcej w secie), a utwór 25 dB cichszy tyle samo co
    głośny. Kulminacja setu lądowała na spokojnym otwieraczu."""

    def test_pad_bez_rytmu_ponizej_pelnego_bitu(self, synt):
        assert synt["pad"].srednia < synt["bit"].srednia - 0.2
        assert synt["pad_glosny"].srednia < synt["bit"].srednia

    def test_cichszy_o_25_db_ma_nizsza_energie(self, synt):
        assert synt["bit_cichy"].srednia < synt["bit"].srednia - 0.05
        assert synt["bit_cichy"].glosnosc_lufs < synt["bit"].glosnosc_lufs - 20

    def test_pad_bez_rytmu_nie_ma_uderzen(self, synt):
        assert synt["pad"].uderzenia_na_s == 0.0
        assert synt["pad_glosny"].uderzenia_na_s == 0.0
        assert synt["pad"].faza == "rozgrzewka"

    def test_breakdown_24_s_jest_widoczny(self, synt):
        """Przegląd: breakdown_s = 0,0 mimo 24 s breakdownu w 60 s utworze."""
        assert 18.0 <= synt["breakdown"].breakdown_s <= 30.0
        assert synt["bit"].breakdown_s <= 3.0

    def test_krzywa_bezwzgledna_cichy_utwor_lezy_nisko(self, synt):
        assert max(synt["bit_cichy"].krzywa) < max(synt["bit"].krzywa)
        assert max(synt["pad"].krzywa) < 0.2

    def test_luk_setu_nie_stawia_kulminacji_na_padzie(self, synt):
        kolej = ["pad", "bit_cichy", "breakdown", "bit", "pad_glosny"]
        utwory = [{"file": k, "title": k, "srednia": synt[k].srednia} for k in kolej]
        luk = energia.luk_setu(utwory)
        assert kolej[luk["kulminacja"]] in ("bit", "breakdown")


class TestFrazyZAktualnejSiatki:
    """Przegląd 0.4.2: po ręcznej zmianie kotwicy /api/energia dalej zwracało
    frazy od starej; ręczna kotwica 0,0 s była ignorowana (`or`)."""

    @pytest.fixture()
    def klient_synt(self, tmp_path, monkeypatch):
        from selekta import cache, cues, waveform
        p = _wav(tmp_path / "utwor.wav", _utwor(sek=40, bpm=128.0))
        cache.put(p, "harmonic", {"bpm": 128.0, "key": "A minor", "camelot": "8A",
                                  "confidence_bpm": 0.5, "confidence_key": 0.9})
        cache.put(p, "cues", {"first_beat_s": 0.5, "intro_end_s": 8.0, "outro_start_s": 30.0,
                              "drop_s": None, "duration_s": 40.0, "battito": 1,
                              "bpm_siatki": 128.0, "pewnosc_siatki": 0.9, "pewnosc_taktu": 0.8})

        def nie_licz(*a, **k):
            raise AssertionError("energia nie może liczyć punktów cue (38 s na utwór)")
        monkeypatch.setattr(cues, "analyze", nie_licz)
        web.set_folder(str(tmp_path))
        return TestClient(web.app), p, waveform

    def _frazy(self, klient, p):
        d = klient.post("/api/energia", json={"files": [os.path.basename(p)]}).json()
        return d["utwory"][0]["frazy"]

    def test_frazy_przesuwaja_sie_po_korekcie(self, klient_synt):
        klient, p, waveform = klient_synt
        assert self._frazy(klient, p)[0] == 0.5
        waveform.zapisz_siatke(p, 2.375, 128.0)
        assert self._frazy(klient, p)[0] == 2.375

    def test_reczna_kotwica_zero_jest_szanowana(self, klient_synt):
        klient, p, waveform = klient_synt
        waveform.zapisz_siatke(p, 0.0, 128.0)
        assert self._frazy(klient, p)[0] == 0.0

    def test_bez_siatki_nie_zmyslamy_fraz(self, klient_synt):
        from selekta import cache
        klient, p, _ = klient_synt
        cache.clear("cues")
        assert self._frazy(klient, p) == []
