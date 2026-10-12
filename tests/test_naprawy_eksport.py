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


def _plik(path, tresc: bytes | None = None) -> str:
    # pamięć podręczna rozpoznaje pliki po TREŚCI — atrapy muszą się różnić,
    # inaczej trzy „różne” utwory dzieliłyby jedną analizę
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(tresc if tresc is not None else os.fsencode(str(path)).ljust(64, b"\x00"))
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
        monkeypatch.setattr(rekordbox, "settings_path", lambda: None)
        monkeypatch.setattr(rekordbox, "install",
                            lambda p: rekordbox.InstallResult(True, "ok"))
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


# ---------------------------------------------------------------------------
# #111 #121 #108 — wymiana z rekordboxem: cue selekty ≠ ręczna praca, NFC, „#"
# ---------------------------------------------------------------------------

def _xml_rb(path_xml, utwory, product='<PRODUCT Name="rekordbox" Version="7.0.4" Company="AlphaTheta"/>'):
    """utwory: lista (location_surowe, wnętrze TRACK)."""
    tracki = "\n".join(
        f'<TRACK TrackID="{i}" Name="t{i}" Artist="a" Location="{loc}">{wnetrze}</TRACK>'
        for i, (loc, wnetrze) in enumerate(utwory, 1))
    path_xml.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<DJ_PLAYLISTS Version="1.0.0">'
                        f'{product}<COLLECTION Entries="{len(utwory)}">{tracki}'
                        f'</COLLECTION></DJ_PLAYLISTS>', encoding="utf-8")
    return str(path_xml)


def _loc(path):
    from urllib.parse import quote
    return "file://localhost" + quote(path, safe="/")


class TestWymianaZRekordboxem:
    def test_wlasny_xml_selekty_nie_zamraza_cue(self, tmp_path):
        """Wczytanie XML-a selekty liczyło 51/51 utworów z „ręczną pracą"."""
        lib = tmp_path / "lib"
        p = _plik(lib / "A - B.mp3")
        _analiza(p, 128.0, "8A", first_beat=0.5, intro=16.0, drop=48.0, outro=150.0)
        t = dj_export.wzbogac_o_siatke([dj_export.track_from_file(p)])
        out = str(tmp_path / "set.xml")
        dj_export.to_rekordbox_xml(t, "set", out)
        wynik = rbimport.scal(out, str(lib))
        assert wynik["dopasowane"] == 1
        assert wynik["z_reczna_praca"] == 0
        assert wynik["cue_selekty_pominiete"] == 3
        stan = rbimport.dla_pliku(p)
        assert stan["znaczniki"] == [] and stan["first_beat_s"] is None
        # nowa analiza ma przejść do eksportu, nie stare cue z XML
        _analiza(p, 128.0, "8A", first_beat=0.5, intro=20.0, drop=52.0, outro=160.0)
        t = dj_export.wzbogac_o_siatke([dj_export.track_from_file(p)])[0]
        assert t["znaczniki"] == [] and t["intro_end_s"] == 20.0

    def test_stary_podpis_selekty_tez_jest_rozpoznany(self, tmp_path):
        lib = tmp_path / "lib"
        p = _plik(lib / "A - B.mp3")
        xml = _xml_rb(tmp_path / "x.xml", [(_loc(p),
            '<TEMPO Inizio="0.500" Bpm="128.00" Metro="4/4" Battito="1"/>'
            '<POSITION_MARK Name="intro" Type="0" Start="16.000" Num="0"/>'
            '<POSITION_MARK Name="drop" Type="0" Start="48.000" Num="1"/>')],
            product='<PRODUCT Name="rekordbox" Version="6.0.0" Company="AlphaTheta"/>')
        assert rbimport.scal(xml, str(lib))["z_reczna_praca"] == 0

    def test_w_kolekcji_rekordboxa_przesuniete_cue_to_praca_dja(self, tmp_path):
        lib = tmp_path / "lib"
        p = _plik(lib / "A - B.mp3")
        _analiza(p, 128.0, "8A", intro=16.0, drop=48.0, outro=150.0)
        xml = _xml_rb(tmp_path / "x.xml", [(_loc(p),
            '<POSITION_MARK Name="intro" Type="0" Start="16.000" Num="0" Red="40" Green="226" Blue="20"/>'
            '<POSITION_MARK Name="drop" Type="0" Start="49.250" Num="1"/>'
            '<POSITION_MARK Name="outro" Type="0" Start="150.000" Num="2"/>'
            '<POSITION_MARK Name="moj" Type="0" Start="70.000" Num="3"/>')])
        wynik = rbimport.scal(xml, str(lib))
        assert wynik["z_reczna_praca"] == 1
        nazwy = [z["nazwa"] for z in rbimport.dla_pliku(p)["znaczniki"]]
        assert nazwy == ["drop", "moj"], "przesunięty drop i własne cue zostają"

    def test_stan_sprzed_naprawy_jest_czyszczony_przy_odczycie(self, tmp_path):
        p = _plik(tmp_path / "lib" / "A - B.mp3")
        _analiza(p, 128.0, "8A", intro=16.0, drop=48.0, outro=150.0)
        rbimport._zapisz_stan({p: {"znaczniki": [
            {"start_s": 16.0, "num": 0, "typ": "0", "nazwa": "intro", "koniec_s": None, "kolor": ""},
            {"start_s": 99.0, "num": 4, "typ": "0", "nazwa": "x", "koniec_s": None, "kolor": ""}]}})
        assert [z["nazwa"] for z in rbimport.dla_pliku(p)["znaczniki"]] == ["x"]

    def test_plik_nfd_z_location_w_nfc(self, tmp_path):
        import unicodedata
        lib = tmp_path / "lib"
        nfd = unicodedata.normalize("NFD", "Zażółć - Jaźń.mp3")
        p = _plik(lib / nfd)
        xml = _xml_rb(tmp_path / "x.xml", [(_loc(unicodedata.normalize("NFC", p)),
            '<POSITION_MARK Name="wejście" Type="0" Start="7.000" Num="0"/>')])
        assert rbimport.scal(xml, str(lib))["dopasowane"] == 1
        t = dj_export.wzbogac_o_siatke([{"path": p}], licz_brakujace=False)[0]
        assert [z["nazwa"] for z in t["znaczniki"]] == ["wejście"]

    def test_niezakodowany_krzyzyk_w_location(self, tmp_path):
        lib = tmp_path / "lib"
        p = _plik(lib / "Ktoś - Hit #1.mp3")
        loc = "file://localhost" + p.replace(" ", "%20")       # „#" bez %23
        xml = _xml_rb(tmp_path / "x.xml", [(loc,
            '<POSITION_MARK Name="a" Type="0" Start="1.000" Num="0"/>')])
        assert rbimport.scal(xml, str(lib))["dopasowane"] == 1

    def test_zmienne_tempo_jest_zapamietane(self, tmp_path):
        lib = tmp_path / "lib"
        p = _plik(lib / "A - B.mp3")
        xml = _xml_rb(tmp_path / "x.xml", [(_loc(p),
            '<TEMPO Inizio="0.050" Bpm="137.00" Metro="4/4" Battito="1"/>'
            '<TEMPO Inizio="100.050" Bpm="138.00" Metro="4/4" Battito="1"/>')])
        rbimport.scal(xml, str(lib))
        assert [t["bpm"] for t in rbimport.dla_pliku(p)["tempa"]] == [137.0, 138.0]
        web.set_folder(str(lib))
        assert TestClient(web.app).get("/api/rekordbox/stan").json()["zmienne_tempo"] == 1

    def test_xml_selekty_podpisany_jako_selekta(self, tmp_path):
        out = str(tmp_path / "x.xml")
        dj_export.to_rekordbox_xml([], "x", out)
        assert ET.parse(out).getroot().find("PRODUCT").get("Name") == "selekta"


# ---------------------------------------------------------------------------
# #120 #108 — ustawienia rekordboxa: bajt w bajt, przywracanie tylko klucza,
# wszystkie sety naraz
# ---------------------------------------------------------------------------

USTAWIENIA = ('<?xml version="1.0" encoding="UTF-8"?>\r\n\r\n<PROPERTIES>\r\n'
              '  <VALUE name="language" val="pl"/>\r\n'
              '  <VALUE name="bridgeImportedLibraryFileList" val="pułapka &amp; &quot;x&quot;"/>\r\n'
              '  <VALUE name="bridgeImportedLibraryFile" val="/stary/plik.xml"/>\r\n'
              '  <VALUE name="colour" val="Łódź"/>\r\n</PROPERTIES>\r\n')


@pytest.fixture()
def ustawienia(tmp_path, monkeypatch):
    plik = tmp_path / "rekordbox3.settings"
    plik.write_bytes(USTAWIENIA.encode("utf-8"))
    monkeypatch.setattr(rekordbox, "settings_path", lambda: str(plik))
    monkeypatch.setattr(rekordbox, "is_running", lambda: False)
    monkeypatch.setattr(sys, "platform", "darwin")
    return plik


class TestUstawieniaRekordboxa:
    def test_install_zmienia_tylko_wartosc_klucza_i_zostawia_crlf(self, ustawienia, tmp_path):
        xml = tmp_path / "set.xml"; xml.write_text("<DJ_PLAYLISTS/>")
        assert rekordbox.install(str(xml)).ok
        po = ustawienia.read_bytes()
        assert po.count(b"\r\n") == USTAWIENIA.encode().count(b"\r\n")
        assert po == USTAWIENIA.encode().replace(b"/stary/plik.xml", str(xml).encode())

    def test_przywracanie_nie_cofa_pozniejszych_zmian(self, ustawienia, tmp_path):
        xml = tmp_path / "set.xml"; xml.write_text("<DJ_PLAYLISTS/>")
        assert rekordbox.install(str(xml)).ok
        # użytkownik zmienia język w rekordboksie PO instalacji
        ustawienia.write_bytes(ustawienia.read_bytes().replace(b'val="pl"', b'val="en"'))
        res = rekordbox.restore()
        assert res.ok, res.message
        assert ustawienia.read_bytes() == USTAWIENIA.encode().replace(b'val="pl"', b'val="en"')

    def test_wszystkie_sety_widoczne_naraz(self, ustawienia, tmp_path, monkeypatch):
        a, b = _plik(tmp_path / "a.mp3"), _plik(tmp_path / "b.mp3")
        c = _plik(tmp_path / "c.mp3")
        x1, x2 = str(tmp_path / "s1.xml"), str(tmp_path / "s2.xml")
        dj_export.to_rekordbox_xml([{"path": a}, {"path": b}], "piątek", x1)
        dj_export.to_rekordbox_xml([{"path": b}, {"path": c}], "sobota", x2)
        assert rekordbox.install_set(x1, "piątek").ok
        # drugi set przy DZIAŁAJĄCYM rekordboksie: plik już podpięty, nie
        # trzeba ruszać ustawień — wystarczy odświeżyć panel
        monkeypatch.setattr(rekordbox, "is_running", lambda: True)
        res = rekordbox.install_set(x2, "sobota")
        assert res.ok, res.message
        assert rekordbox.imported_library() == rekordbox.polaczony_path()
        root = ET.parse(rekordbox.polaczony_path()).getroot()
        assert len(root.findall("COLLECTION/TRACK")) == 3        # b raz
        sety = {n.get("Name"): len(n.findall("TRACK"))
                for n in root.iter("NODE") if n.get("Type") == "1"}
        assert sety == {"piątek": 2, "sobota": 2}


# ---------------------------------------------------------------------------
# #116 #117 #118 — pendrive
# ---------------------------------------------------------------------------

def _wav(path, tagi: bool = True) -> str:
    from mutagen.id3 import COMM, GEOB, TBPM, TCON, TIT2, TKEY, TPE1
    from mutagen.wave import WAVE
    from tests import probka
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    probka.ton(str(path), 440.0, sekund=1.0)
    if tagi:
        w = WAVE(str(path)); w.add_tags()
        for r in (TIT2(encoding=3, text="Gucci"), TPE1(encoding=3, text="Odymel"),
                  TBPM(encoding=3, text="146"), TKEY(encoding=3, text="Am"),
                  TCON(encoding=3, text="Hard Techno"),
                  COMM(encoding=3, lang="eng", desc="", text="8A - Energy 7"),
                  GEOB(encoding=0, mime="application/octet-stream",
                       desc="CuePoints", data=b"mik")):
            w.tags.add(r)
        w.save()
    return str(path)


def _mp3(path) -> str:
    from tests import probka
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    wav = str(path) + ".wav"
    probka.ton(wav, 330.0 + sum(os.fsencode(str(path))) % 60, sekund=1.0)   # różna treść
    probka.do_mp3(wav, str(path))
    os.remove(wav)
    return str(path)


@pytest.fixture()
def lib_usb(tmp_path):
    lib = tmp_path / "lib"
    pliki = [_mp3(lib / "Album" / "Ąę - Łódź.mp3"),
             _mp3(lib / "Album 2" / "CD1" / "B - Drugi.mp3"),
             _wav(lib / "Album" / "Odymel - Gucci.wav")]
    web.set_folder(str(lib))
    return {"lib": str(lib), "pliki": pliki, "klient": TestClient(web.app),
            "dest": str(tmp_path / "USB")}


class TestPendrive:
    def test_cala_biblioteka_z_podfolderami_i_weryfikacja(self, lib_usb):
        r = lib_usb["klient"].post("/api/usb", json={"dest": lib_usb["dest"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["copied"] == 2 and d["converted"] == 1
        assert d["weryfikacja"]["ok"] and d["weryfikacja"]["sprawdzonych"] == 3
        assert "export.pdb" in d["co_powstaje"]

    def test_zly_parametr_convert_to_400(self, lib_usb):
        r = lib_usb["klient"].post("/api/usb", json={"dest": lib_usb["dest"],
                                                     "convert": "mp3"})
        assert r.status_code == 400 and "aiff" in r.json()["detail"]

    def test_cel_w_bibliotece_odrzucony(self, lib_usb):
        r = lib_usb["klient"].post("/api/usb", json={
            "dest": os.path.join(lib_usb["lib"], "Album")})
        assert r.status_code == 400 and "bibliotece" in r.json()["detail"]
        assert not any("(2)" in f for f in os.listdir(os.path.join(lib_usb["lib"], "Album")))

    def test_brak_miejsca_przed_kopiowaniem(self, lib_usb, monkeypatch):
        import collections
        from selekta import usb
        monkeypatch.setattr(usb.shutil, "disk_usage",
                            lambda p: collections.namedtuple("u", "total used free")(10**9, 10**9, 1000))
        r = lib_usb["klient"].post("/api/usb", json={"dest": lib_usb["dest"]})
        assert r.status_code == 400 and "wolnego" in r.json()["detail"]
        assert os.listdir(lib_usb["dest"]) == []

    def test_enospc_w_trakcie_przerywa_kopiowanie(self, lib_usb, monkeypatch):
        import errno
        from selekta import usb
        prawdziwe = usb.shutil.copyfile
        wywolan = []

        def copyfile(src, dst):
            wywolan.append(src)
            if len(wywolan) == 1:
                with open(dst, "wb") as fh:
                    fh.write(b"polowa")            # częściowo zapisany plik
                raise OSError(errno.ENOSPC, "No space left on device")
            return prawdziwe(src, dst)
        monkeypatch.setattr(usb.shutil, "copyfile", copyfile)
        rep = usb.prepare(None, lib_usb["dest"], pliki=lib_usb["pliki"])
        assert rep.przerwano
        assert len(wywolan) == 1, "po ENOSPC nie wolno pisać dalej"
        assert len(rep.skipped) == 3 and rep.copied == [] and rep.converted == []
        assert os.listdir(lib_usb["dest"]) == []

    def test_pliki_appledouble_sa_sprzatane(self, lib_usb, monkeypatch):
        from selekta import usb
        prawdziwe = usb.shutil.copyfile

        def copyfile(src, dst):           # tak zachowuje się macOS na FAT32
            prawdziwe(src, dst)
            with open(os.path.join(os.path.dirname(dst), "._" + os.path.basename(dst)), "wb") as fh:
                fh.write(b"\x00\x05\x16\x07")
        monkeypatch.setattr(usb.shutil, "copyfile", copyfile)
        rep = usb.prepare(None, lib_usb["dest"], pliki=lib_usb["pliki"], convert_wav=None)
        assert rep.usuniete_appledouble == 3
        assert not [n for n in os.listdir(lib_usb["dest"]) if n.startswith("._")]

    @pytest.mark.parametrize("cel", ["aiff", "flac"])
    def test_wav_po_konwersji_zachowuje_bpm_i_tonacje(self, lib_usb, cel):
        from selekta import usb
        wav = lib_usb["pliki"][2]
        rep = usb.prepare(None, lib_usb["dest"], pliki=[wav], convert_wav=cel)
        out = rep.converted[0]
        if cel == "aiff":
            from mutagen.aiff import AIFF
            t = AIFF(out).tags
            assert str(t["TBPM"]) == "146" and str(t["TKEY"]) == "Am"
            assert str(t["TCON"]) == "Hard Techno" and t.getall("GEOB")
            assert t.getall("COMM")[0].text[0] == "8A - Energy 7"
        else:
            from mutagen.flac import FLAC
            f = FLAC(out)
            assert f["BPM"] == ["146"] and f["INITIALKEY"] == ["Am"] and f["GENRE"] == ["Hard Techno"]
        assert usb.zweryfikuj(rep.pary)["ok"]

    def test_weryfikacja_konwersji_wykrywa_ucieta(self, lib_usb, tmp_path):
        from selekta import usb
        from tests import probka
        krotki = probka.ton(str(tmp_path / "krotki.wav"), 440.0, sekund=0.3)
        aiff = str(tmp_path / "x.aiff")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", krotki, aiff], check=True)
        assert not usb.zweryfikuj([(lib_usb["pliki"][2], aiff)])["ok"]

    def test_set_w_kolejnosci_z_numerami(self, lib_usb, monkeypatch, tmp_path):
        from selekta import playlists
        root = tmp_path / "sety"; (root / "piatek").mkdir(parents=True)
        monkeypatch.setattr(playlists, "root", lambda: str(root))
        a, b, _w = lib_usb["pliki"]
        _analiza(a, 130.0, "9A"); _analiza(b, 120.0, "8A")
        (root / "piatek" / "_selekta.json").write_text(json.dumps({"files": [a, b]}))
        r = lib_usb["klient"].post("/api/usb", json={"dest": lib_usb["dest"], "name": "piatek"})
        assert r.status_code == 200, r.text
        assert sorted(os.listdir(lib_usb["dest"])) == ["01 B - Drugi.mp3", "02 Ae - Lodz.mp3"]


# ---------------------------------------------------------------------------
# #124 #125 #127 — historia, mediana sesji, statystyki
# ---------------------------------------------------------------------------

def _xml_historia(path, sesje: dict[str, list[str]]):
    """sesje: nazwa → lista ścieżek."""
    wszystkie = sorted({p for l in sesje.values() for p in l})
    tid = {p: str(i) for i, p in enumerate(wszystkie, 1)}
    kol = "".join(f'<TRACK TrackID="{tid[p]}" Location="{_loc(p)}"/>' for p in wszystkie)
    pl = "".join(f'<NODE Type="1" Name="{n}" Entries="{len(l)}">'
                 + "".join(f'<TRACK Key="{tid[p]}"/>' for p in l) + "</NODE>"
                 for n, l in sesje.items())
    path.write_text(f'<DJ_PLAYLISTS><COLLECTION>{kol}</COLLECTION><PLAYLISTS>'
                    f'<NODE Type="0" Name="ROOT">{pl}</NODE></PLAYLISTS></DJ_PLAYLISTS>')
    return str(path)


class TestHistoriaIStatystyki:
    def test_zakres_dat_po_drugim_pliku_ze_starsza_sesja(self, tmp_path):
        from selekta import historia
        lib = tmp_path / "lib"
        a, b = _plik(lib / "a.mp3"), _plik(lib / "b.mp3")
        historia.dopisz(historia.wczytaj_sesje(_xml_historia(
            tmp_path / "1.xml", {"2026-07-05": [a], "2026-09-12": [b]}), str(lib)))
        historia.dopisz(historia.wczytaj_sesje(_xml_historia(
            tmp_path / "2.xml", {"2026-06-01": [a, b]}), str(lib)))
        assert historia.podsumowanie(str(lib))["zakres_dat"] == ["2026-06-01", "2026-09-12"]
        assert [s["data"] for s in historia.sesje()] == ["2026-06-01", "2026-07-05", "2026-09-12"]

    def test_kopia_w_secie_nie_robi_z_oryginalu_martwego_balastu(self, tmp_path):
        from selekta import historia
        lib = tmp_path / "lib"
        oryg = _plik(lib / "Album" / "Hit.mp3", b"H" * 50)
        kopia = _plik(lib / "set" / "Hit.mp3", b"H" * 50)
        (lib / "set" / "_selekta.json").write_text("{}")
        _plik(lib / "Album" / "Nigdy.mp3", b"N" * 60)
        historia.dopisz(historia.wczytaj_sesje(_xml_historia(
            tmp_path / "h.xml", {"2026-08-01": [kopia]}), str(lib)))
        d = historia.podsumowanie(str(lib))
        assert d["w_bibliotece"] == 2
        assert [m["file"] for m in d["martwe"]] == ["Nigdy.mp3"]
        assert oryg

    def test_mediana_bpm_sesji_przy_parzystej_liczbie(self, tmp_path):
        a, b = _plik(tmp_path / "a.mp3"), _plik(tmp_path / "b.mp3")
        _analiza(a, 129.0, "8A"); _analiza(b, 150.0, "8A")
        assert web._metryki_sesji([a, b])["bpm_mediana"] == 139.5

    def test_gniazdo_z_okna_tempa_nie_z_kubelkow(self):
        from selekta import statystyki as st
        utwory = [{"bpm": b, "camelot": "8A", "title": str(i)}
                  for i, b in enumerate((140, 140.5, 141, 141.5, 142, 142.5))]
        d = st.policz(utwory)
        assert d["gniazd"] == 1, "6 utworów 8A w 140–142,5 BPM to jedno gniazdo"

    def test_statystyki_maja_rozklad_formatow(self, klient, biblioteka):
        d = klient.get("/api/statystyki").json()
        assert d["rozklad_formatow"][0]["format"] == "MP3"
        d = klient.post("/api/statystyki", json={}).json()
        assert sum(f["ile"] for f in d["rozklad_formatow"]) >= 4


# ---------------------------------------------------------------------------
# #102 #106 #107 #123 #115 — zaznaczenie, M4A w bramce, zapomnij, Serato
# ---------------------------------------------------------------------------

class TestDrobneEksportu:
    def test_zaznaczenie_ze_sciezka_wzgledna_bierze_wlasciwy_plik(self, tmp_path, monkeypatch):
        """Dwa różne „01 - Intro.mp3" z dwóch albumów — UI wysyła ścieżkę
        względną, a wyszukiwanie po nazwie brało pierwszy z brzegu."""
        from selekta import playlists
        lib = tmp_path / "lib"
        _plik(lib / "A" / "01 - Intro.mp3", b"A" * 10)
        b = _plik(lib / "B" / "01 - Intro.mp3", b"B" * 20)
        monkeypatch.setattr(playlists, "root", lambda: str(tmp_path / "sety"))
        web.set_folder(str(lib))
        r = TestClient(web.app).post("/api/playlist/from-selection",
                                     json={"name": "x", "files": ["B/01 - Intro.mp3"]})
        assert r.status_code == 200, r.text
        with open(r.json()["files"][0], "rb") as fh:
            assert fh.read() == b"B" * 20
        sciezki, _ = web._zakres({"files": ["B/01 - Intro.mp3"]})
        assert sciezki == [b]

    def test_m4a_z_tagami_i_okladka_nie_jest_zglaszany(self, tmp_path):
        from mutagen.mp4 import MP4, MP4Cover
        from selekta import covers
        from tests import probka
        wav = probka.ton(str(tmp_path / "x.wav"), 440.0, sekund=1.0)
        m4a = str(tmp_path / "Urszula - Malinowy.m4a")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", m4a], check=True)
        f = MP4(m4a)
        f["\xa9ART"] = ["Urszula Sipińska"]; f["\xa9nam"] = ["Malinowy"]
        f["covr"] = [MP4Cover(b"\xff\xd8\xff" + b"0" * 2000, imageformat=MP4Cover.FORMAT_JPEG)]
        f.save()
        assert web._tags(m4a) == ("Urszula Sipińska", "Malinowy")
        assert covers.embedded_art(m4a) is not None

    def test_napraw_m4a_bez_tagow_nie_konczy_sie_500(self, tmp_path, monkeypatch):
        from selekta import covers
        from tests import probka
        wav = probka.ton(str(tmp_path / "x.wav"), 440.0, sekund=1.0)
        m4a = str(tmp_path / "Ktos - Cos.m4a")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", m4a], check=True)
        monkeypatch.setattr(covers, "from_itunes", lambda a, t: None)
        web.set_folder(str(tmp_path))
        r = TestClient(web.app, raise_server_exceptions=False).post(
            "/api/playlist/fix", json={"path": m4a})
        assert r.status_code == 200, r.text
        # po scaleniu z naprawami importu M4A ma zapis tagów — nazwa z pliku trafia do tagów
        assert r.json()["ok"] and "Ktos — Cos" in r.json()["message"], r.text

    def test_zapomnij_utwor_z_folderu_playlisty(self, tmp_path, monkeypatch):
        from selekta import playlists
        lib = tmp_path / "lib"; lib.mkdir()
        sety = tmp_path / "sety"
        p = _plik(sety / "piatek" / "A - B.mp3")
        monkeypatch.setattr(playlists, "root", lambda: str(sety))
        rbimport._zapisz_stan({p: {"ocena": 3}})
        web.set_folder(str(lib))
        r = TestClient(web.app).post("/api/rekordbox/zapomnij", json={"file": p})
        assert r.status_code == 200, r.text
        assert r.json()["usunietych"] == 1

    def test_serato_crate_na_woluminie_utworow(self, tmp_path, monkeypatch):
        zewn = str(tmp_path / "Volumes" / "USB")
        a = _plik(tmp_path / "home" / "a.mp3")
        b = _plik(tmp_path / "Volumes" / "USB" / "Muzyka" / "b.mp3")
        monkeypatch.setattr(dj_export, "_wolumin",
                            lambda p: zewn if p.startswith(zewn) else None)
        sciezki = dj_export.install_serato_crates([{"path": a}, {"path": b}],
                                                  str(tmp_path / "Music"), "set")
        assert sorted(sciezki) == sorted([
            str(tmp_path / "Music" / "_Serato_" / "Subcrates" / "set.crate"),
            os.path.join(zewn, "_Serato_", "Subcrates", "set.crate")])

    def test_wolumin_z_sciezki(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert dj_export._wolumin("/Volumes/DJ USB/Muzyka/a.mp3") == "/Volumes/DJ USB"
        assert dj_export._wolumin("/Users/x/a.mp3") is None


# ---------------------------------------------------------------------------
# #99 #25 — kolejność setu: bez serii zgrzytów na końcu, tempo narasta
# ---------------------------------------------------------------------------

# BPM i Camelot setu speeding (51 utworów) z analizy w piaskownicy przeglądu
SPEEDING = [
    (128, "7B"), (129, "1A"), (130, "7B"), (135, "5A"), (135, "7A"), (137, "1A"),
    (137, "5A"), (138, "12B"), (138, "5A"), (140, "10A"), (140, "2B"), (140, "3A"),
    (144, "10A"), (144, "8A"), (145, "6B"), (146, "6A"), (146, "8A"), (147, "8B"),
    (147, "9A"), (148, "12B"), (148, "2A"), (148, "8A"), (150, "10A"), (150, "12A"),
    (150, "1A"), (150, "2A"), (150, "2B"), (150, "2B"), (150, "8A"), (150, "8A"),
    (150, "8A"), (150, "8A"), (150, "8A"), (152, "10A"), (152, "1A"), (152, "8A"),
    (154, "9A"), (155, "12A"), (155, "1A"), (155, "3A"), (155, "3A"), (155, "5B"),
    (155, "7A"), (155, "7B"), (155, "8A"), (155, "8A"), (155, "8B"), (165, "10A"),
    (165, "10A"), (165, "5A"), (174, "3A")]


def _zgodne(c1, c2):
    n1, l1, n2, l2 = int(c1[:-1]), c1[-1], int(c2[:-1]), c2[-1]
    d = min(abs(n1 - n2), 12 - abs(n1 - n2))
    return (l1 == l2 and d <= 1) or (d == 0 and l1 != l2)


def _spearman(x):
    """Korelacja rang pozycji i wartości (remisy = średnia ranga)."""
    n = len(x)
    order = sorted(range(n), key=lambda i: x[i])
    rangi = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rangi[order[k]] = (i + j) / 2
        i = j + 1
    m = (n - 1) / 2
    cov = sum((p - m) * (r - m) for p, r in enumerate(rangi))
    vp = sum((p - m) ** 2 for p in range(n))
    vr = sum((r - m) ** 2 for r in rangi)
    return cov / (vp * vr) ** 0.5


def _ta(bpm, cam):
    from selekta import harmonic
    return harmonic.TrackAnalysis(float(bpm), "", cam, 0.9, 0.9)


class TestKolejnoscSetu:
    @pytest.mark.parametrize("tasuj", [False, True])
    def test_speeding_bez_zgrzytow_na_koncu_i_bez_duzych_spadkow(self, tasuj):
        import random
        from selekta import harmonic
        items = [(f"{i:02d}.mp3", _ta(b, c)) for i, (b, c) in enumerate(SPEEDING)]
        if tasuj:
            random.Random(7).shuffle(items)
        out = harmonic.order_set(items)
        tas = [ta for _n, ta, _x in out]
        assert sorted(n for n, _t, _x in out) == sorted(n for n, _t in items)
        zg = [_zgodne(a.camelot, b.camelot) for a, b in zip(tas, tas[1:])]
        spadki = [a.bpm - b.bpm for a, b in zip(tas, tas[1:])]
        # przed: 5 niezgodnych w ostatnich 10 przejściach, zejście 150→129
        # (pojedynczy spadek 10 BPM), suma zejść 57 BPM, korelacja 0,66
        assert zg[-10:].count(False) <= 3, "końcówka setu pełna zgrzytów"
        serie, biez = [], 0
        for z in zg:
            biez = 0 if z else biez + 1
            serie.append(biez)
        assert max(serie) <= 3
        assert max(spadki) <= 5, f"duży spadek tempa w środku setu: {max(spadki)} BPM"
        assert sum(x for x in spadki if x > 0) <= 35
        assert tas[0].bpm == 128 and tas[-1].bpm == 174
        assert _spearman([t.bpm for t in tas]) >= 0.8, "tempo ma narastać"
        assert sum(zg) / len(zg) >= 0.74            # przed: 76 % (kosztem zjazdu 150→129)

    def test_kolo_12a_przy_stalym_tempie_same_zgodne(self):
        from selekta import harmonic
        items = [(f"{n}A", _ta(128, f"{n}A")) for n in (5, 9, 1, 12, 3, 7, 2, 11, 4, 8, 6, 10)]
        tas = [ta for _n, ta, _x in harmonic.order_set(items)]
        assert all(_zgodne(a.camelot, b.camelot) for a, b in zip(tas, tas[1:]))

    def test_male_zestawy_blisko_optimum_funkcji_celu(self):
        """Pełny przegląd permutacji (start = najniższe BPM) na 30 losowych
        zestawach po 7 utworów — algorytm ma trafiać w optimum."""
        import itertools
        import random
        from selekta import harmonic
        rng = random.Random(99)
        trafione = 0
        for _ in range(30):
            items = [(str(i), _ta(rng.choice(range(124, 150)),
                                  f"{rng.randint(1, 12)}{rng.choice('AB')}"))
                     for i in range(7)]
            u = harmonic._Uklad([t for _n, t in items])
            pierwszy = min(range(7), key=lambda i: items[i][1].bpm)
            opt = min(u.cel([pierwszy, *p]) for p in itertools.permutations(
                [i for i in range(7) if i != pierwszy]))
            idx = {n: i for i, (n, _t) in enumerate(items)}
            wynik = u.cel([idx[n] for n, _t, _x in harmonic.order_set(items)])
            assert wynik <= opt * 1.05 + 1e-9
            trafione += abs(wynik - opt) < 1e-9
        assert trafione >= 27

    def test_ta_sama_kolejnosc_przy_kazdym_wywolaniu(self):
        from selekta import harmonic
        items = [(f"{i:02d}", _ta(b, c)) for i, (b, c) in enumerate(SPEEDING)]
        a = [n for n, _t, _x in harmonic.order_set(items)]
        b = [n for n, _t, _x in harmonic.order_set(list(items))]
        assert a == b, "ekran i eksport muszą dostać ten sam set"
