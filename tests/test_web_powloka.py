"""Powłoka nowego dashboardu (projekt graficzny 3.09.2026).

Pilnujemy tras, od których zależy wszystko inne: strona główna serwuje
powłokę, skrypty ekranów i zasoby są dostępne pod /static, stary dashboard
zostaje pod /stary jako siatka bezpieczeństwa, a /static nie wypuszcza
niczego spoza katalogu static.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from selekta import web

STATIC = os.path.join(os.path.dirname(web.__file__), "static")


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    return TestClient(web.app)


def test_strona_glowna_to_powloka(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="nav"' in html and 'id="player"' in html
    assert "/static/ekrany/_powloka.js" in html
    for ekran in ("kreator", "biblioteka", "set", "porzadki", "wiecej"):
        assert f"/static/ekrany/{ekran}.js" in html


def test_skrypty_ekranow_istnieja_i_sa_serwowane(client):
    for nazwa in os.listdir(os.path.join(STATIC, "ekrany")):
        if nazwa.endswith(".js"):
            r = client.get(f"/static/ekrany/{nazwa}")
            assert r.status_code == 200, nazwa
            assert "javascript" in r.headers["content-type"]


def test_zasoby_graficzne(client):
    for nazwa in ("selekta-mark.png", "selekta-logo.png"):
        r = client.get(f"/static/assets/{nazwa}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_stary_dashboard_zostaje(client):
    r = client.get("/stary")
    assert r.status_code == 200 and "TRYB AUTOMATYCZNY" in r.text


def test_static_nie_wypuszcza_poza_katalog(client):
    for sciezka in ("/static/../web.py", "/static/%2e%2e/web.py", "/static/../../pyproject.toml"):
        r = client.get(sciezka)
        assert r.status_code in (400, 403, 404), sciezka
        assert "FastAPI(" not in r.text and "[project]" not in r.text


def test_skrypty_ekranow_maja_poprawna_skladnie():
    """`node --check` na każdym skrypcie ekranu — literówka w JS psuje cały
    dashboard po cichu (przeglądarka loguje błąd, użytkownik widzi pustkę)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("brak node — sprawdzenie składni JS pominięte")
    katalog = os.path.join(STATIC, "ekrany")
    for nazwa in sorted(os.listdir(katalog)):
        if nazwa.endswith(".js"):
            r = subprocess.run([node, "--check", os.path.join(katalog, nazwa)],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"{nazwa}: {r.stderr[-400:]}"


def test_powloka_rejestruje_wszystkie_pozycje_nawigacji():
    """Każda pozycja nawigacji w index.html ma ekran zarejestrowany w którymś
    skrypcie — inaczej klik pokazuje „ekran jeszcze nie jest gotowy"."""
    import re
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    pozycje = set(re.findall(r'data-ekran="([a-z]+)"', html))
    katalog = os.path.join(STATIC, "ekrany")
    zarejestrowane = set()
    for nazwa in os.listdir(katalog):
        if nazwa.endswith(".js"):
            js = open(os.path.join(katalog, nazwa), encoding="utf-8").read()
            zarejestrowane |= set(re.findall(r"S\.ekran\(\s*['\"]([a-z]+)['\"]", js))
    brak = pozycje - zarejestrowane
    assert not brak, f"pozycje nawigacji bez ekranu: {sorted(brak)}"


def test_czcionki_sa_lokalne(client):
    """Dashboard nie może zależeć od Google Fonts: apka do pobrania ma
    wyglądać tak samo bez internetu i nie wysyłać zapytań na zewnątrz."""
    html = client.get("/").text
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html
    css = client.get("/static/fonts/fonts.css")
    assert css.status_code == 200 and "Urbanist" in css.text and "DM Mono" in css.text
    import re
    pliki = set(re.findall(r"/static/fonts/([\w.-]+\.woff2)", css.text))
    assert pliki, "fonts.css nie wskazuje żadnych plików woff2"
    for nazwa in pliki:
        r = client.get(f"/static/fonts/{nazwa}")
        assert r.status_code == 200 and len(r.content) > 1000, nazwa


def test_status_zwraca_wersje(client):
    """Regresja 3.09.2026: użycie pomocnika weszło do /api/status, definicja
    nie — dev przeszedł, a pakiet .app padał na pierwszym zapytaniu."""
    d = client.get("/api/status").json()
    assert d["level"] in ("red", "amber", "green")
    assert isinstance(d.get("wersja"), str) and d["wersja"]


def test_style_ekranow_nie_koliduja_klasami_stanu():
    """Regresja 5.09.2026: w kreatorze reguła `.kr .done` (nakładka końcowa,
    position:absolute na całą treść) łapała także kroki paska `.krok.done`
    i kafle etapów `.etap.done` — ta sama waga selektora, a stała później
    w arkuszu. Ukończony krok przejmował pozycję nakładki, rozlewał się na
    formularz i przechwytywał kliknięcia: nie dało się przejść dalej
    z kroku „Nazwa setu".

    Klasy stanu (done/on/run/ok/bad) są krótkie i wracają w wielu miejscach,
    więc reguła kontenera nie może celować w samą taką klasę — musi ją
    zawęzić własną nazwą elementu (`.krok.done`, `.etap.done`, `.gotowe`).
    """
    import re
    STANY = ("done", "on", "run", "ok", "bad", "warn", "active")
    katalog = os.path.join(STATIC, "ekrany")
    winne = []
    for nazwa in sorted(os.listdir(katalog)):
        if not nazwa.endswith(".js"):
            continue
        js = open(os.path.join(katalog, nazwa), encoding="utf-8").read()
        for selektor in re.findall(r"^\s*([.#][^{}\n]{1,120}?)\s*\{", js, flags=re.M):
            for czesc in selektor.split(","):
                czesc = czesc.strip()
                # ostatni człon selektora: czy to goła klasa stanu?
                ostatni = czesc.split()[-1] if czesc.split() else ""
                if ostatni.lstrip(".") in STANY and ostatni.startswith(".") and ostatni.count(".") == 1:
                    winne.append(f"{nazwa}: {czesc}")
    assert not winne, (
        "reguły celujące w gołą klasę stanu — złapią każdy element z tą klasą:\n  "
        + "\n  ".join(winne))
