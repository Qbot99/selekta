"""Strażnik izolacji: żaden test — także uruchomiony w podprocesie — nie
może pisać do prawdziwego ~/.selekta użytkownika.

Regresja z 11.10.2026: test CLI uruchamiał `selekta analyze` w osobnym
procesie. Podmiany ścieżek z conftestu (monkeypatch) działają tylko w
procesie pytesta, więc podproces liczył HOME po swojemu i dopisywał wpisy
z katalogów tymczasowych do prawdziwego ~/.selekta/cache/harmonic.json
(15 martwych wpisów po kilku przebiegach).

Naprawa: conftest przekierowuje HOME na katalog tymczasowy dla CAŁEJ sesji,
zanim cokolwiek z selekty się zaimportuje — dziedziczą to też podprocesy.
Na koniec sesji hak w conftest porównuje prawdziwy ~/.selekta ze stanem
z początku (tylko odczyt) i oblewa przebieg, gdy test coś tam dopisał.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import subprocess
import sys

import pytest

from tests import conftest


def test_home_w_tescie_nie_jest_prawdziwym_domem():
    dom = os.path.realpath(os.path.expanduser("~"))
    assert dom != os.path.realpath(conftest.PRAWDZIWY_DOM)
    assert os.path.realpath(conftest.DOM_TESTOW) == dom


def test_podproces_dziedziczy_testowy_home():
    """Dokładnie ta luka: podproces nie widział podmian z conftestu."""
    r = subprocess.run(
        [sys.executable, "-c",
         "import os; from selekta import cache, config, wishlist, radar; "
         "print(os.path.expanduser('~')); print(config.STATE_DIR); "
         "print(cache.CACHE_DIR); print(wishlist.STATE_PATH); print(radar.STATE_PATH)"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    prawdziwy = os.path.realpath(conftest.PRAWDZIWY_STAN)
    for linia in r.stdout.split():
        assert not os.path.realpath(linia).startswith(prawdziwy), (
            f"podproces celuje w prawdziwy stan użytkownika: {linia}")
    assert os.path.realpath(r.stdout.split()[0]) == os.path.realpath(conftest.DOM_TESTOW)


def test_zadna_stala_modulu_nie_wskazuje_prawdziwego_stanu():
    """Ścieżki liczone przy imporcie (PLIK = join(STATE_DIR, …)) też."""
    import selekta
    prawdziwy = os.path.realpath(conftest.PRAWDZIWY_STAN)
    zle = []
    for info in pkgutil.iter_modules(selekta.__path__):
        if info.name in ("app",):
            continue
        try:
            mod = importlib.import_module(f"selekta.{info.name}")
        except Exception:                       # noqa: BLE001 — opcjonalne zależności
            continue
        for nazwa, wartosc in vars(mod).items():
            if isinstance(wartosc, str) and wartosc.startswith("/") and \
                    os.path.realpath(wartosc).startswith(prawdziwy):
                zle.append(f"{info.name}.{nazwa}={wartosc}")
    assert not zle, zle


def test_cli_w_podprocesie_pisze_cache_do_testowego_domu(tmp_path):
    """Scenariusz, który przeciekał: analyze na śmieciu w podprocesie."""
    (tmp_path / "podroba.mp3").write_text("to nie jest zaden mp3")
    znaczniki = conftest.znaczniki_sesji(tmp_path)
    przed = conftest.migawka_stanu(znaczniki)
    r = subprocess.run([sys.executable, "-m", "selekta.cli", "analyze",
                        "--folder", str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert "Traceback" not in r.stderr, r.stderr
    po = conftest.migawka_stanu(znaczniki)
    assert not conftest.przecieki(przed, po), conftest.przecieki(przed, po)
    # wpis wylądował w domu testów — czyli izolacja działa, a nie „nic nie zapisano"
    plik = os.path.join(conftest.DOM_TESTOW, ".selekta", "cache", "harmonic.json")
    with open(plik, encoding="utf-8") as fh:
        wpisy = json.load(fh)["entries"].values()
    assert any(str(tmp_path) in str(w.get("path")) for w in wpisy)


def test_przecieki_wykrywaja_nowy_wpis_z_katalogu_testow():
    """Strażnik końca sesji musi umieć zauważyć przeciek (na sztucznej migawce)."""
    z = "/tmp/pytest-of-x/pytest-3/"
    przed = {"cache/harmonic.json": (1, 10, {z: 2})}      # stare martwe wpisy
    po = {"cache/harmonic.json": (2, 20, {z: 3})}
    assert conftest.przecieki(przed, po) == ["cache/harmonic.json"]
    # zmiana bez nowych ścieżek testów (np. działająca apka użytkownika) to nie przeciek
    po_apka = {"cache/harmonic.json": (2, 30, {z: 2})}
    assert conftest.przecieki(przed, po_apka) == []
    nowy = {"cache/x.json": (1, 5, {conftest.znaczniki_sesji()[0]: 1})}
    assert conftest.przecieki({}, nowy) == ["cache/x.json"]
