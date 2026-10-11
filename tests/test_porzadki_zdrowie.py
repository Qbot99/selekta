"""Zdrowie i Porządki — regresje z przeglądu 0.4.2 (pliki syntetyczne).

* ucięty MP3 (najczęstszy skutek przerwanego pobrania) przechodził jako zdrowy:
  ffmpeg nie zgłasza żadnego błędu, mutagen podaje pełny czas z nagłówka Xing;
* Porządki proponowały zamianę zdrowego MP3 na ucięty FLAC i łączyły pliki
  różniące się czasem o 15 s;
* cofnięcie decyzji po rozjeździe przywracało pliki pod cudze nazwy;
* duplikaty łączyły przechodnio Extended + Original + Radio Edit;
* przy remisie zostawała kopia „… (1).flac” zamiast czystej nazwy;
* raport Zdrowia nie odświeżał się po przeniesieniu duplikatu do kosza.
"""
from __future__ import annotations

import os

import pytest

from selekta import decyzje, health
from tests.syntetyczne import kopia, utnij, utnij_mp3_na_ramce, utwor


@pytest.fixture()
def stan(tmp_path, monkeypatch):
    monkeypatch.setattr(decyzje, "PLIK", str(tmp_path / "decyzje.json"))
    monkeypatch.setattr(decyzje.config, "STATE_DIR", str(tmp_path))
    from selekta import uklad
    uklad.zapomnij()
    return tmp_path


# --------------------------------------------------------------- ucięcie

def test_uciety_mp3_jest_wykrywany(tmp_path):
    p = utwor(str(tmp_path / "Mi - Utwor.mp3"), "Mi", "Utwor", sekund=12, kbps=320)
    zdrowy = utwor(str(tmp_path / "Mi - Zdrowy.mp3"), "Mi", "Zdrowy", sekund=12, kbps=320)
    utnij_mp3_na_ramce(p, 0.5)
    # dokładnie przypadek z przeglądu: ffmpeg nie zgłasza ŻADNEGO błędu
    from selekta.narzedzia import ffmpeg_path
    import subprocess
    err = subprocess.run([ffmpeg_path(), "-v", "error", "-i", p, "-f", "null", "-"],
                         capture_output=True, text=True).stderr.strip()
    assert err == ""
    w = health.integralnosc(p, uzyj_cache=False)
    assert w["ok"] is False and w["uciety"] is True, w
    assert w["zdekodowano_s"] == pytest.approx(6, abs=1)
    assert "ucięty" in w["opis"]
    assert health.integralnosc(zdrowy, uzyj_cache=False)["ok"] is True
    # szybka kontrola (bez dekodowania) — do listy utworów
    dekl, real = health.uciecie_mp3(p)
    assert dekl == pytest.approx(12, abs=0.5) and real == pytest.approx(6, abs=1)
    assert health.uciecie_mp3(zdrowy) is None


def test_zdrowie_zglasza_uciety_mp3(tmp_path):
    p = utwor(str(tmp_path / "Mi - Utwor.mp3"), "Mi", "Utwor", sekund=12, kbps=320)
    utnij_mp3_na_ramce(p, 0.5)
    rep = health.scan(str(tmp_path))
    assert [os.path.basename(x) for x, _ in rep.corrupt] == ["Mi - Utwor.mp3"]


def test_lista_pokazuje_prawdziwy_czas_uciętego_mp3(tmp_path):
    from fastapi.testclient import TestClient
    from selekta import web
    p = utwor(str(tmp_path / "Mi - Utwor.mp3"), "Mi", "Utwor", sekund=12, kbps=320)
    utnij_mp3_na_ramce(p, 0.5)
    web.set_folder(str(tmp_path))
    row = TestClient(web.app).get("/api/tracks").json()["tracks"][0]
    assert row["duration"] <= 7
    assert row["uszkodzony"] is True and "ucięty" in row["uwaga"]


def test_uszkodzona_ramka_nie_jest_opisana_jako_ucięcie(tmp_path):
    p = utwor(str(tmp_path / "A - B.flac"), "A", "B", sekund=10)
    rozmiar = os.path.getsize(p)
    with open(p, "r+b") as fh:                 # popsuj kawałek w środku
        fh.seek(rozmiar // 2)
        fh.write(b"\x00" * 64)
    w = health.integralnosc(p, uzyj_cache=False)
    assert w["ok"] is False
    assert "ucięty" not in w["opis"]


# --------------------------------------------------------------- decyzje

def test_porzadki_nie_proponuja_zamiany_mp3_na_uciety_flac(tmp_path, stan):
    lib = tmp_path / "lib"
    flac = utwor(str(lib / "Gamma - Uciety.flac"), "Gamma", "Uciety", sekund=10)
    mp3 = utwor(str(lib / "Gamma - Uciety.mp3"), "Gamma", "Uciety", sekund=10)
    utnij(flac, 0.55)
    nowe = decyzje.skanuj(str(lib))
    assert len(nowe) == 1
    d = nowe[0]
    assert d["zostaw"] == mp3, "zdrowy MP3 musi zostać"
    assert d["usun"] == [flac]
    assert d["rodzaj"] == "duplikat"
    assert "uszkodz" in d["powod"]


def test_porzadki_tolerancja_czasu_jak_w_zdrowiu(tmp_path, stan):
    lib = tmp_path / "lib"
    utwor(str(lib / "Mi - Utwor.flac"), "Mi", "Utwor", sekund=12)
    utwor(str(lib / "Mi - Utwor.mp3"), "Mi", "Utwor", sekund=6)
    assert decyzje.skanuj(str(lib)) == []


def test_porzadki_i_zdrowie_maja_jedna_regule_wersji(tmp_path, stan):
    lib = tmp_path / "lib"
    for nazwa in ("Iota - Numer (Extended Mix).flac", "Iota - Numer (Original Mix).flac",
                  "Iota - Numer (Radio Edit).flac"):
        utwor(str(lib / nazwa), "Iota", "Numer", sekund=8, hz=500)
    rep = health.scan(str(lib))
    assert rep.duplicates == [], "Extended, Original i Radio Edit to różne wersje"
    assert decyzje.skanuj(str(lib)) == []


def test_remis_zostawia_czysta_nazwe(tmp_path):
    lib = tmp_path / "lib"
    czysta = utwor(str(lib / "Theta - Bliźniak.flac"), "Theta", "Bliźniak", sekund=6)
    kopia(czysta, str(lib / "Theta - Bliźniak (1).flac"))
    from selekta import dedupe
    akcje = dedupe.plan(str(lib))
    assert akcje[0].keep == czysta
    assert "czystą nazwą" in akcje[0].reason


def test_uzasadnienie_mowi_o_uszkodzeniu(tmp_path):
    lib = tmp_path / "lib"
    flac = utwor(str(lib / "Gamma - Uciety.flac"), "Gamma", "Uciety", sekund=10)
    utwor(str(lib / "Gamma - Uciety.mp3"), "Gamma", "Uciety", sekund=10)
    utnij(flac, 0.55)
    from selekta import dedupe
    akcje = dedupe.plan(str(lib), include_suspect=True)
    assert akcje and akcje[0].remove == [flac]
    assert "uszkodzony" in akcje[0].reason


def test_cofniecie_po_rozjezdzie_przywraca_wlasne_nazwy(tmp_path, stan):
    lib = tmp_path / "lib"
    a = utwor(str(lib / "Theta - Bliźniak.flac"), "Theta", "Bliźniak", sekund=6)
    b = kopia(a, str(lib / "Theta - Bliźniak (2).flac"))
    c = kopia(a, str(lib / "Theta - Bliźniak (3).flac"))
    d = decyzje.skanuj(str(lib))[0]
    assert d["zostaw"] == a and sorted(d["usun"]) == sorted([b, c])
    os.remove(b)                              # plik znika przed zatwierdzeniem
    decyzje.zatwierdz(d["id"])
    assert not os.path.exists(c)
    decyzje.cofnij(d["id"])
    assert os.path.isfile(c), "plik wraca pod SWOJĄ nazwą"
    assert not os.path.exists(b), "a nie pod nazwą pliku, którego już nie było"
    assert os.path.isfile(a)


def test_pominieta_decyzje_mozna_przywrocic_do_kolejki(tmp_path, stan):
    lib = tmp_path / "lib"
    a = utwor(str(lib / "Theta - Bliźniak.flac"), "Theta", "Bliźniak", sekund=6)
    kopia(a, str(lib / "Theta - Bliźniak (2).flac"))
    d = decyzje.skanuj(str(lib))[0]
    decyzje.odrzuc(d["id"])
    assert decyzje.cofnij(d["id"])["stan"] == "czeka"
    assert decyzje.czekajace()


def test_porzadki_nie_ruszaja_setow(tmp_path, stan):
    from tests.syntetyczne import set_z
    lib = tmp_path / "lib"
    a = utwor(str(lib / "Alfa - Jeden.flac"), "Alfa", "Jeden", sekund=6)
    set_z(str(lib), "speeding", [a])
    set_z(str(lib), "super", [a])
    assert decyzje.skanuj(str(lib)) == []


# --------------------------------------------------------------- odświeżenie

def test_zdrowie_odswieza_sie_po_przeniesieniu_do_kosza(tmp_path):
    from fastapi.testclient import TestClient
    from selekta import web
    lib = tmp_path / "lib"
    a = utwor(str(lib / "Theta - Bliźniak.flac"), "Theta", "Bliźniak", sekund=6)
    kopia(a, str(lib / "Theta - Bliźniak (1).flac"))
    web.set_folder(str(lib))
    c = TestClient(web.app)
    assert len(c.get("/api/health").json()["duplicates"]) == 1
    c.post("/api/dedupe/apply", json={}).raise_for_status()
    h = c.get("/api/health").json()
    assert h["duplicates"] == [], h
    assert h["files"] == 1


def test_zdrowie_w_tle_nie_blokuje(tmp_path):
    import time
    from fastapi.testclient import TestClient
    from selekta import web
    lib = tmp_path / "lib"
    for i in range(3):
        utwor(str(lib / f"A - T{i}.flac"), "A", f"T{i}", sekund=4, hz=300 + 50 * i)
    web.set_folder(str(lib))
    c = TestClient(web.app)
    r = c.get("/api/health", params={"tlo": 1}).json()
    koniec = time.time() + 60
    while r.get("w_toku") and time.time() < koniec:
        time.sleep(0.2)
        r = c.get("/api/health", params={"tlo": 1}).json()
    assert r["files"] == 3
    d = c.get("/api/dedupe", params={"tlo": 1}).json()
    assert d["actions"] == []


# --------------------------------------------------------------- odtwarzanie

def test_audio_zakres_koncowy_i_caly_plik(tmp_path):
    from fastapi.testclient import TestClient
    from selekta import web
    p = utwor(str(tmp_path / "A - B.wav"), "A", "B", sekund=12)
    dane = open(p, "rb").read()
    web.set_folder(str(tmp_path))
    c = TestClient(web.app)
    r = c.get("/api/audio", params={"file": "A - B.wav"}, headers={"Range": "bytes=-500"})
    assert r.status_code == 206
    assert r.content == dane[-500:]
    assert r.headers["content-range"] == f"bytes {len(dane) - 500}-{len(dane) - 1}/{len(dane)}"
    r = c.get("/api/audio", params={"file": "A - B.wav"}, headers={"Range": "bytes=1000-"})
    assert r.status_code == 206 and r.content == dane[1000:]
    r = c.get("/api/audio", params={"file": "A - B.wav"})
    assert r.status_code == 200 and r.content == dane


# --------------------------------------------------------------- pobierz ponownie

def test_pobierz_ponownie_z_tagow_bez_dubli(tmp_path):
    from fastapi.testclient import TestClient
    from selekta import web, wishlist
    utwor(str(tmp_path / "Asia-Heat of the Moment.flac"), "Asia", "Heat of the Moment")
    web.set_folder(str(tmp_path))
    c = TestClient(web.app)
    r = c.post("/api/redownload", json={"file": "Asia-Heat of the Moment.flac"}).json()
    assert (r["artist"], r["title"]) == ("Asia", "Heat of the Moment")
    c.post("/api/redownload", json={"file": "Asia-Heat of the Moment.flac"})
    assert [(w["artist"], w["title"]) for w in wishlist.items()] == [("Asia", "Heat of the Moment")]
    assert c.post("/api/redownload", json={"file": ""}).status_code == 400
    assert c.post("/api/redownload", json={"file": "nie-ma.flac"}).status_code == 404


# --------------------------------------------------------------- kropka stanu

def test_status_zly_klucz_to_nie_wylaczony_slskd(monkeypatch):
    from fastapi.testclient import TestClient
    import requests
    from selekta import web

    class Odp:
        def __init__(self, kod):
            self.status_code, self.ok = kod, kod < 400

        def json(self):
            return {}

    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: Odp(401))
    d = TestClient(web.app).get("/api/status").json()
    assert d["label"] == "slskd: zły klucz API"
    assert "Uruchom slskd" not in d["hint"]

    def brak(url, headers=None, timeout=None):
        raise requests.ConnectionError("nie ma")
    monkeypatch.setattr(requests, "get", brak)
    assert TestClient(web.app).get("/api/status").json()["label"] == "slskd nie działa"
