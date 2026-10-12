"""Migawka tonacji na PRAWDZIWEJ muzyce z niezależnie potwierdzoną tonacją.

Prawda (tests/migawka_tonacji.json, pole "prawda") pochodzi z badania
z października 2026 (naprawy/tonacja-wynik.md): utwór trafia tu tylko wtedy,
gdy co najmniej DWA niezależne źródła zgadzają się co do tonacji i żadne
jej nie przeczy — własna analiza rekordboxa, Mixed In Key, Serato, tag
sklepu, Beatport. Utwory sporne (np. rekordbox mówi moll, Beatport dur)
celowo pominięto.

Dwa sprawdziany:
* każdy utwór daje dokładnie ten wynik, co przy zapisie migawki (regresja:
  „czy moja zmiana ruszyła coś, czego nie zamierzałem ruszyć”),
* liczba trafień w prawdę nie spada poniżej zapisanej.

Testy pomijają się same, gdy plików nie ma (obca maszyna, CI). Po
zamierzonej zmianie algorytmu migawkę odświeża:

    python -m tests.test_tonacja_korpus --zapisz
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from selekta import harmonic

MIGAWKA = os.path.join(os.path.dirname(__file__), "migawka_tonacji.json")


def _wczytaj() -> dict:
    try:
        with open(MIGAWKA, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _znajdz(u: dict) -> str | None:
    for kandydat in u["kandydaci"]:
        p = os.path.expanduser(kandydat)
        if os.path.isfile(p) and os.path.getsize(p) == u["rozmiar"]:
            return p
    return None


def tonacja(path: str) -> tuple[str, float]:
    """Sama tonacja, tą samą drogą co harmonic.analyze (bez BPM)."""
    dl = harmonic._duration(path)
    if dl > harmonic.K_MAX_S:
        x = harmonic._decode(path, harmonic.K_SR, (dl - harmonic.K_MAX_S) / 2.0, harmonic.K_MAX_S)
    else:
        x = harmonic._decode(path, harmonic.K_SR, 0.0, max(dl, harmonic.WINDOW_S) + 1.0)
    t, tryb, pewnosc, _alt = harmonic._key_from_signal(x, harmonic.K_SR)
    return harmonic._key_names(t, tryb)[2], round(pewnosc, 2)


dane = _wczytaj()
utwory = [u for u in dane.get("utwory", []) if _znajdz(u)]

pytestmark = [pytest.mark.slow, pytest.mark.regresja,
              pytest.mark.skipif(not utwory, reason="brak migawki tonacji albo plików")]

_wyniki: dict[str, str] = {}


@pytest.mark.parametrize("u", utwory, ids=[u["plik"][:40] for u in utwory])
def test_tonacja_sie_nie_przesunela(u):
    cam, _ = tonacja(_znajdz(u))
    _wyniki[u["plik"]] = cam
    assert cam == u["wynik"], (
        f"{u['plik']}: było {u['wynik']}, jest {cam} (prawda {u['prawda']}). "
        "Jeśli to zamierzona zmiana algorytmu: python -m tests.test_tonacja_korpus --zapisz")


def test_trafienia_w_prawde_nie_spadaja():
    trafione = 0
    for u in utwory:
        cam = _wyniki.get(u["plik"]) or tonacja(_znajdz(u))[0]
        trafione += cam == u["prawda"]
    oczekiwane = sum(u["wynik"] == u["prawda"] for u in utwory)
    assert trafione >= oczekiwane, f"trafień {trafione}/{len(utwory)}, było {oczekiwane}"


if __name__ == "__main__":
    if "--zapisz" in sys.argv:
        d = _wczytaj()
        for u in d.get("utwory", []):
            p = _znajdz(u)
            if p:
                u["wynik"], u["pewnosc"] = tonacja(p)
                print(f"{u['wynik']:>4} {u['pewnosc']:.2f} (prawda {u['prawda']:>4})  {u['plik'][:60]}")
        with open(MIGAWKA, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
