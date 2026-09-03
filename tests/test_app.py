"""Launcher wersji do pobrania (Selekta.app) — bez otwierania przeglądarki."""
from __future__ import annotations

import os
import socket

from selekta import app


class TestSplash:
    def test_ma_logo_i_adres(self):
        h = app.splash_html("http://127.0.0.1:8756")
        assert "http://127.0.0.1:8756" in h
        assert "data:image/png;base64," in h, "logo z packaging/logo.png ma być osadzone"
        assert "/api/status" in h and "no-cors" in h

    def test_bez_logo_nie_pada(self, monkeypatch):
        monkeypatch.setattr(app, "_logo_b64", lambda: "")
        h = app.splash_html("http://127.0.0.1:1")
        assert "SELEKTA" in h and "<img" not in h

    def test_zapisuje_plik_i_otwiera(self, monkeypatch, tmp_path):
        otwarte = []
        monkeypatch.setattr(app.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setattr(app.webbrowser, "open", lambda u: otwarte.append(u))
        app._otworz_splash("http://127.0.0.1:8756")
        assert otwarte and otwarte[0].startswith("file://")
        plik = otwarte[0][len("file://"):]
        assert os.path.isfile(plik)
        assert "8756" in open(plik, encoding="utf-8").read()


class TestStart:
    def test_wolny_port_domyslny_albo_inny(self):
        p = app._wolny_port()
        assert isinstance(p, int) and 1024 <= p <= 65535

    def test_wolny_port_omija_zajety(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            zajety = s.getsockname()[1]
            s.listen(1)
            assert app._wolny_port(zajety) != zajety

    def test_folder_biblioteki_istnieje(self, monkeypatch):
        from selekta import config
        monkeypatch.setattr(config, "get", lambda k: "")
        assert os.path.isdir(app._folder_biblioteki())

    def test_folder_z_ustawien_ma_pierwszenstwo(self, monkeypatch, tmp_path):
        from selekta import config
        monkeypatch.setattr(config, "get", lambda k: str(tmp_path))
        assert app._folder_biblioteki() == str(tmp_path)
