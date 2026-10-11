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
