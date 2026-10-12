"""Oś czasu rekordboxa vs oś selekty — przesunięcie MP3/M4A w eksporcie i imporcie.

Rekordbox nie pomija opóźnienia kodera, które ffmpeg (a więc cała analiza
selekty) pomija. Zmierzone na 130 prawdziwych plikach z przebiegiem fali
z analizy rekordboxa: reguła z rbczas.py trafiała każdy co do próbki.
Bez poprawki siatka i cue z eksportu leżały 25–51 ms przed stopą.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from selekta import cache, dj_export, rbczas, rbimport
from tests import probka


@pytest.fixture()
def wav(tmp_path):
    return probka.metronom(str(tmp_path / "m.wav"), 128.0, sekund=12.0)


def _ffmpeg_mp3(wav, out, *dodatkowe):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-ar", "44100", "-b:a", "192k", *dodatkowe, out],
                   check=True)
    return out


class TestRegula:
    def test_bezstratne_bez_przesuniecia(self, wav):
        assert rbczas.zmierz(wav) == 0.0

    def test_mp3_z_ffmpeg_tag_lavc_to_pominiecie_kodera(self, wav, tmp_path):
        p = _ffmpeg_mp3(wav, str(tmp_path / "lavc.mp3"))
        assert rbczas.ramka_lame(p) == 0
        assert round(rbczas.zmierz(p) * 44100) == 1105

    def test_mp3_bez_tagu_xing(self, wav, tmp_path):
        p = _ffmpeg_mp3(wav, str(tmp_path / "bez.mp3"), "-write_xing", "0")
        assert rbczas.zmierz(p) == 0.0

    @pytest.mark.skipif(shutil.which("lame") is None, reason="brak kodera lame")
    def test_mp3_z_tagiem_lame_dodaje_ramke(self, tmp_path):
        w = probka.metronom(str(tmp_path / "w44.wav"), 128.0, sekund=12.0)
        src = str(tmp_path / "w441.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", w, "-ar", "44100", src], check=True)
        p = str(tmp_path / "lame.mp3")
        subprocess.run(["lame", "--silent", "-b", "192", src, p], check=True)
        assert rbczas.ramka_lame(p) == 1152
        assert round(rbczas.zmierz(p) * 44100) == 1105 + 1152

    def test_wynik_w_pamieci_podrecznej(self, wav, tmp_path, monkeypatch):
        p = _ffmpeg_mp3(wav, str(tmp_path / "c.mp3"))
        pierwszy = rbczas.przesuniecie_s(p)
        monkeypatch.setattr(rbczas, "zmierz", lambda path: (_ for _ in ()).throw(AssertionError("liczy ponownie")))
        assert rbczas.przesuniecie_s(p) == pierwszy

    def test_nieczytelny_plik_to_zero(self, tmp_path):
        z = tmp_path / "zly.mp3"; z.write_bytes(b"nie mp3")
        assert rbczas.zmierz(str(z)) == 0.0


class TestEksport:
    def _xml(self, tmp_path, track):
        out = dj_export.to_rekordbox_xml([track], "x", str(tmp_path / "out.xml"))
        tr = ET.parse(out).getroot().find(".//COLLECTION/TRACK")
        return tr

    def test_siatka_i_cue_przesuniete_o_os_rekordboxa(self, wav, tmp_path):
        p = _ffmpeg_mp3(wav, str(tmp_path / "e.mp3"))
        off = rbczas.przesuniecie_s(p)
        assert off > 0.02
        tr = self._xml(tmp_path, {"path": p, "bpm": 128.0, "first_beat_s": 0.5, "battito": 1,
                                  "intro_end_s": 8.0, "drop_s": None, "outro_start_s": 10.0})
        assert float(tr.find("TEMPO").get("Inizio")) == pytest.approx(0.5 + off, abs=0.0006)
        starty = sorted(float(m.get("Start")) for m in tr.findall("POSITION_MARK"))
        assert starty == pytest.approx([8.0 + off, 10.0 + off], abs=0.0006)

    def test_flac_wav_bez_zmian(self, wav, tmp_path):
        tr = self._xml(tmp_path, {"path": wav, "bpm": 128.0, "first_beat_s": 0.5, "battito": 1})
        assert tr.find("TEMPO").get("Inizio") == "0.500"

    def test_reczna_praca_z_rekordboxa_wraca_co_do_ms(self, wav, tmp_path):
        """Import (oś rekordboxa → selekty) i eksport (z powrotem) znoszą się dokładnie."""
        p = _ffmpeg_mp3(wav, str(tmp_path / "r.mp3"))
        cache.put(p, "harmonic", {"bpm": 128.0, "key": "", "camelot": "8A",
                                  "confidence_bpm": 1, "confidence_key": 1})
        cache.put(p, "cues", {"duration_s": 12.0, "first_beat_s": 0.3, "intro_end_s": 4.0,
                              "outro_start_s": 9.0, "drop_s": None, "battito": 1})
        rbimport._zapisz_stan({rbimport._klucz(p): {
            "first_beat_s": 0.123, "bpm": 128.0, "battito": 2, "zrodlo": "rekordbox",
            "znaczniki": [{"start_s": 1.234, "num": 0, "typ": "0", "nazwa": "A"},
                          {"start_s": 2.0, "koniec_s": 3.5, "num": 1, "typ": "4", "nazwa": "pętla"}]}})
        t = dj_export.wzbogac_o_siatke([{"path": p}], licz_brakujace=False)[0]
        assert t["first_beat_s"] == pytest.approx(0.123 - rbczas.przesuniecie_s(p))
        tr = self._xml(tmp_path, t)
        assert tr.find("TEMPO").get("Inizio") == "0.123"
        marki = {m.get("Name"): (m.get("Start"), m.get("End")) for m in tr.findall("POSITION_MARK")}
        assert marki == {"A": ("1.234", None), "pętla": ("2.000", "3.500")}

    def test_nasze_cue_rozpoznane_po_powrocie(self, wav, tmp_path):
        """Cue selekty zapisane z przesunięciem dalej są rozpoznawane jako nasze, nie ręczne."""
        p = _ffmpeg_mp3(wav, str(tmp_path / "n.mp3"))
        cache.put(p, "cues", {"duration_s": 12.0, "first_beat_s": 0.3, "intro_end_s": 4.0,
                              "outro_start_s": 9.0, "drop_s": None, "battito": 1})
        off = rbczas.przesuniecie_s(p)
        z = rbimport.Znacznik(start_s=round(4.0 + off, 3), num=0, typ="0", nazwa="intro")
        assert rbimport._cue_selekty(z, False, rbimport._wartosci_selekty(p))
