"""Regresje z przeglądu infrastruktury 11.10.2026 (różne drobne pozycje).

Każda klasa odpowiada jednej pozycji z listy napraw; w docstringu: co było
źle i jak to widział użytkownik.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from selekta import web
from tests.conftest import GOOD_MP3

ROOT = os.path.dirname(web.__file__)


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


def _kandydat(**kw):
    k = {"path": "@@u\\Muzyka\\mischluft, Sachsentrance - We are Energy.mp3",
         "filename": "mischluft, Sachsentrance - We are Energy.mp3",
         "user": "ktos", "size": 9_000_000, "size_mb": 9.0, "bitrate": 320,
         "length_s": 200, "format": "MP3", "lossless": False, "free_slot": True,
         "title_match": 1.0, "artist_match": 1.0, "duration_delta": 0,
         "duration_ok": True}
    k.update(kw)
    return k


class TestLepszaWersjaZnaPrawdziwyBitrate:
    """„Szukaj lepszej wersji” wysyłało bitrate:0 — dla zdrowego MP3 320 apka
    proponowała jako „lepsze” inne MP3 320 („320 kbps z pełnym pasmem”)."""

    def _find(self, client, monkeypatch, **body):
        from selekta.slskd_client import SlskdClient
        monkeypatch.setattr(SlskdClient, "available", lambda self: True)
        monkeypatch.setattr(SlskdClient, "search_candidates",
                            lambda self, a, t, d=None, **kw: [_kandydat()])
        payload = {"artist": "mischluft, Sachsentrance", "title": "We are Energy",
                   "duration": 200, "lossless": False, "grade": "ok"}
        payload.update(body)
        r = client.post("/api/upgrade/find", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    def test_serwer_czyta_bitrate_z_pliku(self, client, monkeypatch):
        d = self._find(client, monkeypatch, bitrate=0, file=GOOD_MP3)
        assert d["count"] == 0, d["candidates"]

    def test_ui_wysyla_plik_i_bitrate(self):
        js = open(os.path.join(ROOT, "static", "ekrany", "biblioteka.js"),
                  encoding="utf-8").read()
        wywolanie = js[js.index("'/api/upgrade/find'"):][:300]
        assert "bitrate:0" not in wywolanie.replace(" ", "")
        assert "file:" in wywolanie

    def test_zly_plik_dalej_pozwala_na_320(self, client, monkeypatch):
        """Gdy analiza uznała jakość za złą (transkod), nagłówek 320 kłamie."""
        d = self._find(client, monkeypatch, bitrate=0, file=GOOD_MP3, grade="bad")
        assert d["count"] == 1


# ---------------------------------------------------------------- kolejka

class TestUszkodzonaKolejkaNieBlokujeStartu:
    """Jedna zła pozycja w kolejka.json (attempts null / '2x') rzucała z
    wczytaj(), a serve() tego nie łapał — apka nie startowała wcale."""

    def test_zla_pozycja_pominieta_reszta_wczytana(self, monkeypatch):
        from selekta import dlqueue
        q = dlqueue.Queue()
        monkeypatch.setattr(q, "_ensure_worker", lambda: None)
        with open(dlqueue.PLIK_KOLEJKI, "w", encoding="utf-8") as fh:
            json.dump([{"artist": "a", "title": "t", "attempts": None},
                       {"artist": "b", "title": "u", "attempts": "2x"},
                       {"artist": "c", "title": "v", "status": "waiting"},
                       {"artist": "d", "title": "w", "duration": "zła"}], fh)
        assert q.wczytaj() == 2
        st = q.state()
        assert [j["artist"] for j in st["jobs"]] == ["c", "d"]
        assert st["jobs"][1]["duration"] is None
        assert "pominięto 2" in q.state()["note"]

    def test_serve_startuje_mimo_bledu_kolejki(self, monkeypatch, tmp_path):
        import uvicorn
        from selekta import dlqueue, obserwator, poszukiwacz
        def pada():
            raise ValueError("zepsuta kolejka")
        monkeypatch.setattr(dlqueue.QUEUE, "wczytaj", pada)
        monkeypatch.setattr(obserwator.OBSERWATOR, "start", lambda f: None)
        monkeypatch.setattr(poszukiwacz.POSZUKIWACZ, "start", lambda: None)
        ruszyl = []
        monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: ruszyl.append(1))
        web.serve(str(tmp_path), port=0)
        assert ruszyl == [1]


# ---------------------------------------------------------------- transfery

class _Odp:
    def __init__(self, kod=200, dane=None):
        self.status_code, self.ok, self._d = kod, kod < 400, dane

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(str(self.status_code))


class TestTransfery:
    def test_najnowsze_najpierw(self, monkeypatch):
        from selekta import slskd_client
        pliki = [{"id": str(i), "filename": f"x\\{i}.mp3", "state": "Completed, Succeeded",
                  "requestedAt": f"2026-08-2{i}T10:00:00"} for i in (1, 3, 2)]
        monkeypatch.setattr(slskd_client.requests, "get", lambda *a, **kw: _Odp(200, [
            {"username": "u", "directories": [{"files": pliki}]}]))
        rows = slskd_client.SlskdClient("http://x", "k").downloads()
        assert [r["id"] for r in rows] == ["3", "2", "1"]

    def test_anulowanie_koduje_nazwe_uzytkownika(self, monkeypatch):
        from selekta import slskd_client
        adresy = []
        monkeypatch.setattr(slskd_client.requests, "delete",
                            lambda url, **kw: adresy.append(url) or _Odp(204))
        assert slskd_client.SlskdClient("http://x", "k").cancel_download("DJ Ziom?#1/a", "id 1")
        assert adresy == ["http://x/api/v0/transfers/downloads/DJ%20Ziom%3F%231%2Fa/id%201"]

    def test_endpoint_nie_melduje_sukcesu_gdy_slskd_odmowil(self, client, monkeypatch):
        from selekta.slskd_client import SlskdClient
        monkeypatch.setattr(SlskdClient, "cancel_download", lambda self, u, i: False)
        r = client.post("/api/transfers/cancel", json={"user": "u", "id": "1"})
        assert r.status_code == 502
        monkeypatch.setattr(SlskdClient, "cancel_download", lambda self, u, i: True)
        assert client.post("/api/transfers/cancel", json={"user": "u", "id": "1"}).json() == {"ok": True}


# ---------------------------------------------------------------- obserwator

class TestObserwatorNieMieliUszkodzonego:
    """Uszkodzony plik był analizowany od nowa co skan (6× w kilka minut)
    i opóźniał analizę nowych plików."""

    def test_uszkodzony_plik_tylko_raz_do_zmiany(self, tmp_path, monkeypatch):
        from selekta import obserwator
        (tmp_path / "zepsuty.mp3").write_bytes(b"\0" * 1000)
        o = obserwator.Obserwator()
        o._folder = str(tmp_path)
        wolane = []
        monkeypatch.setattr(o, "_ustabilizowany", lambda p: True)
        monkeypatch.setattr(o, "przeanalizuj", lambda p: wolane.append(p) or False)
        for _ in range(4):
            o.skan()
        assert len(wolane) == 1
        assert o.stan()["pominiete_uszkodzone"] == 1
        # plik się zmienił (np. pobrany ponownie) — spróbuj jeszcze raz
        (tmp_path / "zepsuty.mp3").write_bytes(b"\0" * 2000)
        o.skan()
        assert len(wolane) == 2


# ---------------------------------------------------------------- cache

class TestLicznikAnalizTylkoDlaBiblioteki:
    """Ustawienia pokazywały „450 utworów z BPM i tonacją” przy 277-utworowej
    bibliotece — licznik brał też martwe wpisy (usunięte pliki)."""

    def test_licznik_biblioteki_pomija_martwe(self, client, lib_copy, tmp_path_factory):
        from selekta import cache, matcher
        pliki = matcher.audio_files(lib_copy)
        for p in pliki:
            cache.put(p, "harmonic", {"bpm": 120})
        obcy = tmp_path_factory.mktemp("obcy") / "usuniety.mp3"
        obcy.write_bytes(b"x")
        cache.put(str(obcy), "harmonic", {"bpm": 1})
        obcy.unlink()
        d = client.get("/api/cache").json()
        assert d["harmonic"] == len(pliki) + 1                 # surowa liczba wpisów
        assert d["w_bibliotece"]["harmonic"] == len(pliki)

    def test_ustawienia_pokazuja_licznik_biblioteki(self):
        js = open(os.path.join(ROOT, "static", "ekrany", "wiecej.js"), encoding="utf-8").read()
        assert "w_bibliotece" in js


# ---------------------------------------------------------------- CLI

def _cli(monkeypatch, capsys, *argv):
    import sys
    from selekta import cli
    monkeypatch.setattr(sys, "argv", ["selekta", *argv])
    try:
        cli.main()
    except SystemExit as e:
        if e.code not in (None, 0):
            raise
    return capsys.readouterr().out


class TestPomocCLI:
    def test_opis_glowny_wymienia_wszystkie_komendy(self, monkeypatch, capsys):
        import re
        from selekta import cli
        out = _cli(monkeypatch, capsys, "--help")
        komendy = re.search(r"\{([a-z,]+)\}", out).group(1).split(",")
        for k in komendy:
            assert re.search(rf"^  {k}\s", cli.__doc__, re.M), f"brak „{k}” w opisie"


class TestWishlistCLI:
    def test_lista_numerowana_i_usuwanie_po_numerze(self, monkeypatch, capsys):
        from selekta import wishlist
        wishlist.add("A", "Pierwszy")
        drugi = wishlist.add("B", "Drugi")
        out = _cli(monkeypatch, capsys, "wishlist")
        assert "1. A — Pierwszy" in out and "2. B — Drugi" in out and drugi["id"] in out
        out = _cli(monkeypatch, capsys, "wishlist", "--remove", "2")
        assert "Drugi" in out
        assert [w["title"] for w in wishlist.items()] == ["Pierwszy"]

    def test_usuwanie_po_id(self, monkeypatch, capsys):
        from selekta import wishlist
        w = wishlist.add("A", "X")
        _cli(monkeypatch, capsys, "wishlist", "--remove", w["id"])
        assert wishlist.items() == []


class TestHuntPobieraWlasciwyUtwor:
    """`hunt --download` brał rank() bez artysty i tytułu — wygrywał FLAC
    innego wykonawcy zamiast MP3 właściwego utworu."""

    def _uruchom(self, monkeypatch, capsys, duration):
        from selekta import cli, spotify
        from selekta.slskd_client import SearchHit, SlskdClient
        t = spotify.Track(id="", artist="Laherte", title="Speeding", duration_s=duration)
        monkeypatch.setattr(cli, "_load_tracks", lambda src: [t])
        monkeypatch.setattr(SlskdClient, "available", lambda self: True)
        wyniki = [SearchHit("x", "@@y\\Mix\\Zupelnie Inny - Inny Utwor (Testowy Remix).flac",
                            40_000_000, None, 300, True, True),
                  SearchHit("z", "@@z\\Laherte - Speeding (Original Mix).mp3",
                            12_000_000, 320, 301, False, True)]
        monkeypatch.setattr(SlskdClient, "search_track", lambda self, a, t, d=None, **kw: wyniki)
        pobrane = []
        monkeypatch.setattr(SlskdClient, "download", lambda self, h: pobrane.append(h.filename))
        out = _cli(monkeypatch, capsys, "hunt", "x", "--download")
        return pobrane, out

    def test_pobiera_mp3_wlasciwego_utworu(self, monkeypatch, capsys):
        pobrane, out = self._uruchom(monkeypatch, capsys, 300)
        assert pobrane == ["@@z\\Laherte - Speeding (Original Mix).mp3"]

    def test_bez_czasu_nie_pobiera_w_ciemno(self, monkeypatch, capsys):
        pobrane, out = self._uruchom(monkeypatch, capsys, None)
        assert pobrane == [] and "potwierd" in out


class TestMatchBezSpotify:
    """`selekta match` sprawdzał tylko próbki Spotify — dla list tekstowych,
    Apple i YouTube nic (0/0), choć apka ma już próbki z iTunes."""

    def test_proba_itunes_gdy_brak_spotify(self, monkeypatch, capsys, tmp_path):
        from selekta import cli, matcher, spotify, verify_match
        t = spotify.Track(id="", artist="A", title="T", duration_s=200)
        monkeypatch.setattr(cli, "_load_tracks", lambda src: [t])
        monkeypatch.setattr(matcher, "best_match",
                            lambda tr, folder: matcher.Candidate(str(tmp_path / "A - T.mp3"),
                                                                 0.9, 0, "test"))
        monkeypatch.setattr(verify_match, "verify_track", lambda p, tr: None)
        monkeypatch.setattr(verify_match, "verify_by_name",
                            lambda p, a, tt: (verify_match.MatchResult(0.91, 30.0, "match"),
                                              "iTunes: A — T"))
        out = _cli(monkeypatch, capsys, "match", "x", "--folder", str(tmp_path))
        assert "1/1" in out and "iTunes" in out


    def test_probka_innego_wykonawcy_nie_jest_dowodem(self, monkeypatch, capsys, tmp_path):
        from selekta import cli, matcher, spotify, verify_match
        t = spotify.Track(id="", artist="Fuego", title="El Diablo", duration_s=200)
        monkeypatch.setattr(cli, "_load_tracks", lambda src: [t])
        monkeypatch.setattr(matcher, "best_match",
                            lambda tr, folder: matcher.Candidate(str(tmp_path / "x.flac"),
                                                                 0.9, 0, "test"))
        monkeypatch.setattr(verify_match, "verify_track", lambda p, tr: None)
        monkeypatch.setattr(verify_match, "verify_by_name",
                            lambda p, a, tt: (verify_match.MatchResult(0.05, 60.0, "mismatch"),
                                              "Franko — El Diablo"))
        out = _cli(monkeypatch, capsys, "match", "x", "--folder", str(tmp_path))
        assert "innego" in out and "❌" not in out and "0/0" in out


# ---------------------------------------------------------------- slskd stop

class TestZatrzymanieTylkoNaszegoSlskd:
    """stop() robił `pkill -x slskd` — zatrzymywał KAŻDY slskd użytkownika,
    także uruchomiony spoza selekty (np. w innym folderze)."""

    def _procesy(self, monkeypatch, procesy, binarka):
        from selekta import slskd_ctl
        monkeypatch.setattr(slskd_ctl, "_procesy_slskd", lambda: procesy)
        monkeypatch.setattr(slskd_ctl, "find_binary", lambda: binarka)
        zabite = []
        monkeypatch.setattr(slskd_ctl, "_zabij", lambda pid: zabite.append(pid))
        komendy = []
        monkeypatch.setattr(slskd_ctl.subprocess, "run",
                            lambda cmd, **kw: komendy.append(cmd))
        return zabite, komendy

    def test_zatrzymuje_tylko_proces_z_naszej_binarki(self, monkeypatch):
        from selekta import slskd_ctl
        zabite, komendy = self._procesy(monkeypatch, [(11, "/a/slskd"), (22, "/b/slskd")],
                                        "/a/slskd")
        ok, _ = slskd_ctl.stop()
        assert ok and zabite == [11]
        assert not any("pkill" in c for c in komendy)

    def test_cudzy_slskd_zostaje(self, monkeypatch):
        from selekta import slskd_ctl
        zabite, _ = self._procesy(monkeypatch, [(22, "/b/slskd")], "/a/slskd")
        ok, msg = slskd_ctl.stop()
        assert not ok and zabite == [] and "uruchomi" in msg


class TestPakietMaNumerKompilacji:
    def test_info_plist_ma_cfbundleversion(self):
        spec = open(os.path.join(os.path.dirname(ROOT), "packaging", "selekta.spec"),
                    encoding="utf-8").read()
        assert '"CFBundleVersion"' in spec

