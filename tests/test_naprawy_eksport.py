"""Naprawy obszaru „eksport" (przegląd 0.4.2, październik 2026).

Każda klasa odtwarza jeden błąd z listy: test padał na kodzie sprzed
naprawy i pilnuje, żeby nie wrócił. Dane syntetyczne — bez prawdziwej
biblioteki użytkownika.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from selekta import cache, dj_export, rbimport, rekordbox, web


def _plik(path, tresc: bytes = b"\x00" * 64) -> str:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(tresc)
    return str(path)


def _analiza(path: str, bpm: float, camelot: str, key: str = "A minor",
             first_beat: float = 0.25, intro: float = 16.0, drop: float = 48.0,
             outro: float = 150.0) -> None:
    """Wpisz do cache gotową analizę — bez liczenia audio."""
    cache.put(path, "harmonic", {"bpm": bpm, "key": key, "camelot": camelot,
                                 "confidence_bpm": 0.9, "confidence_key": 0.8})
    cache.put(path, "cues", {"duration_s": 200.0, "first_beat_s": first_beat,
                             "intro_end_s": intro, "outro_start_s": outro,
                             "drop_s": drop, "battito": 1, "bpm_siatki": None,
                             "pewnosc_siatki": None, "pewnosc_taktu": None})


@pytest.fixture()
def biblioteka(tmp_path):
    """Biblioteka jak u użytkownika: NIC w folderze głównym, wszystko w
    podfolderach albumów, plus folder setu z kopią jednego utworu."""
    lib = tmp_path / "biblioteka"
    a = _plik(lib / "Album A" / "Artysta A - Pierwszy.mp3", b"A" * 100)
    b = _plik(lib / "Album B" / "CD1" / "Artysta B - Drugi.mp3", b"B" * 200)
    c = _plik(lib / "Album C" / "Artysta C - Trzeci.mp3", b"C" * 300)
    # folder setu: kopia „Pierwszy" (ta sama nazwa i rozmiar) + utwór,
    # który istnieje TYLKO w secie
    s = lib / "moj set"
    _plik(s / "Artysta A - Pierwszy.mp3", b"A" * 100)
    d = _plik(s / "Artysta D - Tylko w secie.mp3", b"D" * 400)
    (s / "_selekta.json").write_text(json.dumps({"name": "moj set", "files": []}))
    return {"folder": str(lib), "pliki": [a, b, c, d]}


@pytest.fixture()
def klient(biblioteka):
    web.set_folder(biblioteka["folder"])
    return TestClient(web.app)


# ---------------------------------------------------------------------------
# #112 #113 #128 — eksport całej biblioteki widział ją jako pustą
# ---------------------------------------------------------------------------

class TestEksportCalejBiblioteki:
    def test_collect_czyta_podfoldery_bez_kopii_z_setow(self, biblioteka):
        sciezki = [t["path"] for t in dj_export.collect(biblioteka["folder"])]
        assert sorted(sciezki) == sorted(biblioteka["pliki"]), (
            "eksport ma widzieć utwory w podfolderach, kopię z folderu setu raz")

    def test_folder_setu_wskazany_wprost_to_ten_set(self, biblioteka):
        set_ = os.path.join(biblioteka["folder"], "moj set")
        nazwy = sorted(os.path.basename(p) for p in dj_export.pliki_biblioteki(set_))
        assert nazwy == ["Artysta A - Pierwszy.mp3", "Artysta D - Tylko w secie.mp3"]

    @pytest.mark.parametrize("cel", ["m3u8", "rekordbox", "serato"])
    def test_api_export_nie_jest_pusty(self, klient, biblioteka, cel, tmp_path,
                                       monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "dom"))
        r = klient.post("/api/export", json={"target": cel, "order": "set"})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 4

    def test_nazwa_eksportu_nie_wychodzi_z_biblioteki(self, klient, biblioteka):
        r = klient.post("/api/export", json={"target": "m3u8",
                                             "name": "../../poza/WERYF"})
        assert r.status_code == 200, r.text
        sciezka = os.path.realpath(r.json()["path"])
        assert os.path.dirname(sciezka) == os.path.realpath(biblioteka["folder"])

    def test_install_calej_biblioteki_ma_siatke_cue_i_reczna_prace(
            self, klient, biblioteka, monkeypatch):
        """Wcześniej: 400 „biblioteka jest pusta", a na płaskim folderze XML
        bez TEMPO i POSITION_MARK — ręczne hot cue przepadały."""
        a, b, c, d = biblioteka["pliki"]
        for p, bpm, cam in ((a, 126.0, "8A"), (b, 128.0, "8A"),
                            (c, 130.0, "9A"), (d, 127.0, "7A")):
            _analiza(p, bpm, cam)
        rbimport._zapisz_stan({os.path.abspath(b): {
            "znaczniki": [{"start_s": 33.3, "num": 3, "typ": "0",
                           "nazwa": "moje", "koniec_s": None, "kolor": ""}]}})
        zapisane = {}
        monkeypatch.setattr(rekordbox, "install", lambda p: zapisane.setdefault(
            "p", p) and rekordbox.InstallResult(True, "ok"))
        r = klient.post("/api/rekordbox/install", json={})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 4
        root = ET.parse(r.json()["path"]).getroot()
        utwory = root.findall("COLLECTION/TRACK")
        assert len(utwory) == 4
        assert all(t.find("TEMPO") is not None for t in utwory)
        po_nazwie = {t.get("Location").rsplit("/", 1)[-1]: t for t in utwory}
        reczny = po_nazwie["Artysta%20B%20-%20Drugi.mp3"]
        assert [m.get("Name") for m in reczny.findall("POSITION_MARK")] == ["moje"]
        inny = po_nazwie["Artysta%20A%20-%20Pierwszy.mp3"]
        assert {m.get("Name") for m in inny.findall("POSITION_MARK")} == {
            "intro", "drop", "outro"}

    def test_order_nie_dubluje_kopii(self, klient, biblioteka):
        for p in biblioteka["pliki"]:
            _analiza(p, 128.0, "8A")
        # kopia w secie też ma analizę — wcześniej wychodziła drugi raz
        kopia = os.path.join(biblioteka["folder"], "moj set", "Artysta A - Pierwszy.mp3")
        _analiza(kopia, 128.0, "8A")
        d = klient.get("/api/order").json()["order"]
        assert len(d) == 4
        assert len({o["path"] for o in d}) == 4


class TestCliEksport:
    def _run(self, *args, home):
        env = {**os.environ, "HOME": home}
        return subprocess.run([sys.executable, "-m", "selekta.cli", *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def test_pusta_biblioteka_to_blad_a_nie_pusty_plik(self, tmp_path):
        lib = tmp_path / "lib"
        _plik(lib / "Album" / "okladka.jpg")
        out = tmp_path / "wynik.xml"
        r = self._run("export", "--folder", str(lib), "--target", "rekordbox",
                      "--out", str(out), home=str(tmp_path / "dom"))
        assert r.returncode != 0
        assert "nie znalazłem żadnych utworów" in r.stderr
        assert not out.exists()

    def test_biblioteka_z_podfolderami(self, biblioteka, tmp_path):
        out = tmp_path / "lista.m3u8"
        r = self._run("export", "--folder", biblioteka["folder"], "--target",
                      "m3u8", "--out", str(out), home=str(tmp_path / "dom"))
        assert r.returncode == 0, r.stderr
        linie = [l for l in out.read_text().splitlines() if not l.startswith("#")]
        assert sorted(linie) == sorted(biblioteka["pliki"])


# ---------------------------------------------------------------------------
# #109 #186 #122 — tonacja w XML: jeden zapis, bez śmieci z tagów
# ---------------------------------------------------------------------------

MIK_8B = "eyJrZXkiOiI4QiIsInNvdXJjZSI6Im1peGVkaW5rZXkiLCJhbGdvcml0aG0iOjk0fQ=="


def _flac(path, **tagi) -> str:
    from mutagen.flac import FLAC
    from tests import probka
    wav = str(path) + ".wav"
    probka.ton(wav, 440.0, sekund=1.0)
    probka.do_flac(wav, str(path))
    os.remove(wav)
    f = FLAC(str(path))
    for k, v in tagi.items():
        f[k] = v
    f.save()
    return str(path)


class TestTonacja:
    @pytest.mark.parametrize("surowa,camelot,rb", [
        ("8A", "8A", "Am"), ("08a", "8A", "Am"), ("10m", "5A", "Cm"),
        ("1d", "8B", "C"), ("C Minor", "5A", "Cm"), ("B Minor", "10A", "Bm"),
        ("F", "7B", "F"), ("A minor", "8A", "Am"), ("F#m", "11A", "F#m"),
        ("Gbm", "11A", "F#m"), ("Bbm", "3A", "A#m"), ("Db Major", "3B", "C#"),
        (MIK_8B, "8B", "C"), ("8A/Am", "8A", "Am"),
        ("?", None, None), ("", None, None), ("13A", None, None),
        ("eyJub3BlIjoxfQ==", None, None), ("Off key", None, None),
    ])
    def test_normalizacja(self, surowa, camelot, rb):
        assert dj_export.tonacja_camelot(surowa) == camelot
        assert dj_export.tonacja_rekordbox(surowa) == rb

    def test_blob_mixed_in_key_nie_trafia_do_rekordboxa(self, tmp_path):
        p = _flac(tmp_path / "blk. - Enter.flac", KEY=MIK_8B)
        t = dj_export.track_from_file(p)
        assert t["key"] == "8B"
        out = str(tmp_path / "x.xml")
        dj_export.to_rekordbox_xml([t], "x", out)
        assert ET.parse(out).getroot().find("COLLECTION/TRACK").get("Tonality") == "C"

    def test_jeden_zapis_w_calym_xml(self, tmp_path):
        pliki = [_flac(tmp_path / "a.flac", INITIALKEY="F"),
                 _flac(tmp_path / "b.flac", INITIALKEY="C Minor"),
                 _flac(tmp_path / "c.flac", INITIALKEY="10m"),
                 _flac(tmp_path / "d.flac", INITIALKEY="9A"),
                 _flac(tmp_path / "e.flac", INITIALKEY="śmieć")]
        out = str(tmp_path / "x.xml")
        dj_export.to_rekordbox_xml([dj_export.track_from_file(p) for p in pliki],
                                   "x", out)
        ton = [t.get("Tonality") for t in ET.parse(out).getroot().findall("COLLECTION/TRACK")]
        assert ton == ["F", "Cm", "Cm", "Em", None]

    def test_analiza_selekty_wygrywa_z_tagiem(self, tmp_path):
        """Apka pokazuje analizę (8A) — rekordbox ma dostać to samo, nie tag „F"."""
        p = _flac(tmp_path / "a.flac", INITIALKEY="F")
        cache.put(p, "harmonic", {"bpm": 128.0, "key": "A minor", "camelot": "8A",
                                  "confidence_bpm": 0.9, "confidence_key": 0.9})
        assert dj_export.track_from_file(p)["key"] == "8A"
        t = dj_export.wzbogac_o_siatke([{"path": p, "key": "F", "bpm": 128.0}],
                                       licz_brakujace=False)[0]
        assert dj_export.tonacja_rekordbox(t["key"]) == "Am"

    def test_stan_nie_zglasza_tej_samej_tonacji_w_innym_zapisie(self, tmp_path):
        a = _plik(tmp_path / "lib" / "a.mp3")
        b = _plik(tmp_path / "lib" / "b.mp3")
        c = _plik(tmp_path / "lib" / "c.mp3")
        for p, cam in ((a, "7B"), (b, "8A"), (c, "9A")):
            cache.put(p, "harmonic", {"bpm": 128.0, "key": "", "camelot": cam,
                                      "confidence_bpm": 1, "confidence_key": 1})
        rbimport._zapisz_stan({a: {"tonality": "F"}, b: {"tonality": "Am"},
                               c: {"tonality": "Am"}})
        web.set_folder(str(tmp_path / "lib"))
        d = TestClient(web.app).get("/api/rekordbox/stan").json()
        assert [r["file"] for r in d["rozbieznosci"]] == ["c.mp3"]
