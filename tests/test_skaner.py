"""Szukanie muzyki na całym komputerze (selekta.skaner, /api/skaner).

Pliki są atrapami (losowe bajty), a czas trwania podstawiamy — testy
sprawdzają, CO skaner bierze, a czego nie, bez dekodowania audio.
"""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from selekta import skaner, web


def _plik(sciezka, rozmiar=600_000, tresc: bytes | None = None) -> str:
    os.makedirs(os.path.dirname(sciezka), exist_ok=True)
    with open(sciezka, "wb") as fh:
        fh.write(tresc if tresc is not None else os.urandom(rozmiar))
    return str(sciezka)


@pytest.fixture()
def dom(tmp_path, monkeypatch):
    """Sztuczny dom z biblioteką w Music; czas trwania z nazwy („krotki” = 30 s)."""
    d = tmp_path / "dom"
    (d / "Music").mkdir(parents=True)
    monkeypatch.setattr(skaner, "_czas_i_tagi",
                        lambda p: (30.0 if "krotki" in os.path.basename(p) else 240.0, {"artist": "", "title": ""}))
    with skaner._lock:
        skaner._STAN.clear()
        skaner._STAN.update({"etap": "", "w_toku": False})
    return d


def _skan(dom, **kw):
    return skaner.skanuj(str(dom / "Music"), [str(dom)], dom=str(dom), **kw)


def _sciezki(w):
    return sorted(p["path"] for g in w["foldery"] for p in g["pliki"])


def test_pomija_system_programy_pakiety_i_biblioteke(dom):
    dobry = _plik(dom / "Downloads" / "Artysta - Utwor.mp3")
    for zly in ("Library/Application Support/Gra/muzyka.mp3",   # dane aplikacji
                ".ukryty/a.mp3",
                "Projekty/Piosenka.logicx/Media/stem.wav",      # pakiet projektu
                "kod/node_modules/pakiet/dzwiek.mp3",
                "Music/selekta/juz w bibliotece.mp3",          # sama biblioteka
                "Downloads/notatka.txt"):
        _plik(dom / zly)
    w = _skan(dom)
    assert _sciezki(w) == [dobry]
    assert w["foldery"][0]["folder"] == str(dom / "Downloads")


def test_kopia_pliku_z_biblioteki_pod_inna_nazwa_nie_jest_nowa(dom):
    tresc = os.urandom(700_000)
    _plik(dom / "Music" / "Artysta - Utwor.flac", tresc=tresc)
    _plik(dom / "Desktop" / "stara nazwa.flac", tresc=tresc)
    inny = _plik(dom / "Desktop" / "inny.flac", rozmiar=700_000)   # ten sam rozmiar, inna treść
    w = _skan(dom)
    assert w["juz_w_bibliotece"] == 1
    assert _sciezki(w) == [inny]


def test_krotkie_dzwieki_i_male_pliki_pominiete(dom):
    _plik(dom / "Sample" / "krotki loop.wav")
    _plik(dom / "Sample" / "maly.mp3", rozmiar=50_000)
    dlugi = _plik(dom / "Sample" / "caly utwor.wav")
    w = _skan(dom)
    assert _sciezki(w) == [dlugi] and w["krotkie"] == 2


def test_ten_sam_plik_w_dwoch_miejscach_raz_z_krotsza_sciezka(dom):
    tresc = os.urandom(650_000)
    krotsza = _plik(dom / "Muza" / "a.mp3", tresc=tresc)
    _plik(dom / "Muza" / "kopia zapasowa 2019" / "a.mp3", tresc=tresc)
    w = _skan(dom)
    assert _sciezki(w) == [krotsza] and w["kopie"] == 1


def test_korzenie_bez_dysku_systemowego(tmp_path):
    wol = tmp_path / "Volumes"
    (wol / "USB").mkdir(parents=True)
    os.symlink("/", wol / "Macintosh HD")
    dom = tmp_path / "Users" / "ja"
    dom.mkdir(parents=True)
    (tmp_path / "Users" / "Shared").mkdir()
    assert skaner.korzenie(str(dom), str(wol)) == [
        str(dom), str(tmp_path / "Users" / "Shared"), str(wol / "USB")]


def test_cel_zachowuje_sciezke_zrodla(tmp_path):
    lib = str(tmp_path / "Music")
    dom = str(tmp_path / "dom")
    assert skaner.cel_dla(os.path.join(dom, "Downloads", "x", "a.mp3"), lib, dom=dom) == \
        os.path.join(lib, "Z komputera", "Downloads", "x", "a.mp3")
    wol = str(tmp_path / "Volumes")
    assert skaner.cel_dla(os.path.join(wol, "USB", "set", "b.flac"), lib, dom=dom, wolumeny=wol) == \
        os.path.join(lib, "Z komputera", "USB", "set", "b.flac")


def test_dodaj_kopiuje_nie_rusza_oryginalu_i_nie_nadpisuje(dom):
    src = _plik(dom / "Downloads" / "a.mp3")
    with open(src, "rb") as fh:
        tresc = fh.read()
    lib = str(dom / "Music")
    w = _skan(dom)
    pliki = [p for g in w["foldery"] for p in g["pliki"]]
    d = skaner.dodaj(pliki, lib, dom=str(dom))
    cel = os.path.join(lib, "Z komputera", "Downloads", "a.mp3")
    assert d["dodane"] == 1 and os.path.isfile(src)
    with open(cel, "rb") as fh:
        assert fh.read() == tresc
    # drugi raz ten sam plik: pominięty, nie dubluje się
    assert skaner.dodaj(pliki, lib, dom=str(dom))["pominiete"] == 1
    # inny plik pod tą samą nazwą: obok, z numerem — nic nie nadpisujemy
    _plik(src)
    skaner.dodaj([{**pliki[0], "size": os.path.getsize(src)}], lib, dom=str(dom))
    assert os.path.isfile(os.path.join(lib, "Z komputera", "Downloads", "a (2).mp3"))
    with open(cel, "rb") as fh:
        assert fh.read() == tresc


def test_brak_miejsca_na_pelne_kopie_nic_nie_kopiuje(dom, monkeypatch):
    src = _plik(dom / "Volumes" / "USB" / "a.mp3")
    monkeypatch.setattr(skaner.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 500_000_000})())
    with pytest.raises(ValueError, match="za mało miejsca"):
        skaner.dodaj([{"path": src, "size": 600_000, "ten_sam_dysk": False}],
                     str(dom / "Music"), dom=str(dom))
    assert not os.path.exists(dom / "Music" / "Z komputera")


def _czekaj(client):
    for _ in range(200):
        d = client.get("/api/skaner").json()
        if not d["w_toku"]:
            return d
        time.sleep(0.05)
    raise AssertionError("skaner nie skończył")


def test_api_skan_i_dodanie_tylko_tego_co_skan_znalazl(dom, monkeypatch):
    monkeypatch.setattr(skaner, "korzenie", lambda d=None, w="/Volumes": [str(dom)])
    monkeypatch.setattr(skaner.os.path, "expanduser",
                        lambda p: p.replace("~", str(dom), 1) if p.startswith("~") else p)
    web.set_folder(str(dom / "Music"))
    client = TestClient(web.app)
    assert client.post("/api/skaner/dodaj", json={"foldery": [str(dom)]}).status_code == 409

    src = _plik(dom / "Downloads" / "a.mp3")
    assert client.post("/api/skaner/start").status_code == 200
    d = _czekaj(client)
    assert [g["folder"] for g in d["wynik"]["foldery"]] == [str(dom / "Downloads")]

    # folder spoza wyniku skanu: odmowa, nic nie kopiujemy
    r = client.post("/api/skaner/dodaj", json={"foldery": [str(dom / "Documents")]})
    assert r.status_code == 409
    assert client.post("/api/skaner/dodaj", json={"foldery": "zle"}).status_code == 400

    assert client.post("/api/skaner/dodaj", json={"foldery": [str(dom / "Downloads")]}).status_code == 200
    d = _czekaj(client)
    assert d["dodawanie"]["dodane"] == 1
    assert os.path.isfile(dom / "Music" / "Z komputera" / "Downloads" / "a.mp3")
    assert os.path.isfile(src)


def test_plik_tylko_w_icloud_nie_jest_czytany(dom, monkeypatch):
    """Otwarcie pliku „dataless” ściąga go z iCloud — skaner ma go tylko policzyć."""
    w_chmurze = _plik(dom / "Desktop" / "z chmury.mp3")
    lokalny = _plik(dom / "Desktop" / "lokalny.mp3")
    prawdziwy_stat = os.stat

    class Stat:
        def __init__(self, st, flagi):
            self._st, self.st_flags = st, flagi

        def __getattr__(self, nazwa):
            return getattr(self._st, nazwa)

    def stat(p, *a, **kw):
        st = prawdziwy_stat(p, *a, **kw)
        return Stat(st, skaner.SF_DATALESS) if str(p) == w_chmurze else st

    czytane = []
    monkeypatch.setattr(skaner.os, "stat", stat)
    monkeypatch.setattr(skaner, "odcisk", lambda p, r=None: czytane.append(p) or p)
    w = _skan(dom)
    assert _sciezki(w) == sorted([lokalny, w_chmurze]) and w["w_chmurze"] == 1
    assert w_chmurze not in czytane                       # nie otwarty = nie pobrany
    z = next(p for g in w["foldery"] for p in g["pliki"] if p["path"] == w_chmurze)
    assert z["w_chmurze"] and not z["ten_sam_dysk"]       # pobranie liczy się do miejsca


def test_projekty_z_kodem_pominiete_ale_nie_caly_dom(dom):
    (dom / ".git").mkdir()                          # dom jako repozytorium kropek
    utwor = _plik(dom / "Muzyka" / "utwor.mp3")
    _plik(dom / "kod" / "badanie" / "synt" / "metronom.wav")
    (dom / "kod" / "badanie" / "venv").mkdir(parents=True)
    _plik(dom / "strona" / "public_html" / "dzwiek.mp3")
    _plik(dom / "strona" / "public_html" / "wp-config.php", rozmiar=10)
    w = _skan(dom)
    assert _sciezki(w) == [utwor] and w["projekty"] == 2
