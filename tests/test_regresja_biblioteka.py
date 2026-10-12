"""Migawka wyników na PRAWDZIWEJ muzyce.

Sygnały syntetyczne dowodzą, że metoda jest poprawna. Nie dowodzą, że
zachowuje się tak samo na materiale, który naprawdę grasz — prawdziwy
utwór ma synkopy, pogłos, breakdowny i offbeatowe hi-haty, których żaden
metronom nie odtworzy.

Ten moduł zapisuje wyniki dla stałego zestawu plików i przy każdym
uruchomieniu sprawdza, czy się nie przesunęły. Nie ocenia, czy wynik jest
POPRAWNY — od tego jest test_regresja_dsp. Odpowiada na inne pytanie:
„czy moja zmiana w kodzie ruszyła coś, czego nie zamierzałem ruszyć".

Testy same się pomijają, gdy nie ma biblioteki albo migawki, więc na
obcej maszynie i w CI nie przeszkadzają. Migawkę tworzy się poleceniem:

    python -m tests.test_regresja_biblioteka --zapisz
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from selekta import cache, harmonic, loudness, matcher, quality, tempo

MIGAWKA = os.path.join(os.path.dirname(__file__), "migawka_biblioteki.json")
ILE_PLIKOW = 12          # tyle wystarczy, żeby wychwycić przesunięcie

# Tolerancje: ciasne tam, gdzie wynik jest jednoznaczny, luźniejsze tam,
# gdzie zależy od wersji ffmpeg i biblioteki numerycznej.
TOLERANCJE = {
    "bpm": 0.5,              # pół uderzenia na minutę
    "cutoff_hz": 600.0,      # granica pasma
    "lufs": 0.3,             # dziesiąte części decybela
    "first_beat_s": 0.020,   # 20 ms — poniżej ćwierci bitu przy 150 BPM
}


def _folder() -> str:
    # REAL_LIB liczony przed przekierowaniem HOME na dom testów (conftest)
    from tests.conftest import REAL_LIB
    return os.path.expanduser(os.environ.get("SELEKTA_LIBRARY_FOLDER", REAL_LIB))


def _pliki() -> list[str]:
    folder = _folder()
    if not os.path.isdir(folder):
        return []
    # stała, powtarzalna próbka: alfabetycznie, zawsze te same pliki
    return sorted(matcher.audio_files(folder))[:ILE_PLIKOW]


def zmierz(path: str) -> dict:
    """Wszystkie liczby, które mogą się po cichu przesunąć."""
    h = harmonic.analyze(path)
    q = quality.analyze(path)
    g = loudness.analyze(path)
    t = tempo.zbadaj(path, h.bpm)
    from selekta import cues
    c = cues.analyze(path, bpm=h.bpm)
    return {
        "bpm": round(h.bpm, 2) if h.bpm else None,
        "camelot": h.camelot,
        "cutoff_hz": round(q.cutoff_hz, 1),
        "grade": q.grade,
        "lufs": round(g.integrated_lufs, 2),
        "first_beat_s": round(c.first_beat_s, 3),
        "tempo_stabilne": bool(t.stabilne),
    }


def zapisz_migawke() -> int:
    pliki = _pliki()
    if not pliki:
        print("nie ma biblioteki — migawki nie da się zrobić")
        return 0
    dane = {}
    for i, p in enumerate(pliki, 1):
        print(f"  [{i}/{len(pliki)}] {os.path.basename(p)[:56]}")
        dane[os.path.basename(p)] = zmierz(p)
    with open(MIGAWKA, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"zapisano {len(dane)} pozycji do {MIGAWKA}")
    return len(dane)


def _wczytaj_migawke() -> dict:
    try:
        with open(MIGAWKA, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


migawka = _wczytaj_migawke()
pliki = _pliki()

pytestmark = pytest.mark.skipif(
    not migawka or not pliki,
    reason="brak migawki albo biblioteki — uruchom "
           "`python -m tests.test_regresja_biblioteka --zapisz`")


@pytest.mark.slow
@pytest.mark.parametrize("nazwa", sorted(migawka)[:ILE_PLIKOW] if migawka else [])
def test_wyniki_sie_nie_przesunely(nazwa):
    """Ten sam plik musi dawać te same liczby co przy zapisie migawki."""
    folder = _folder()
    sciezka = matcher.resolve_in_library(folder, nazwa)
    if not sciezka or not os.path.isfile(sciezka):
        pytest.skip(f"{nazwa} zniknął z biblioteki")

    oczekiwane = migawka[nazwa]
    teraz = zmierz(sciezka)

    rozbieznosci = []
    for pole, wartosc in oczekiwane.items():
        biezaca = teraz.get(pole)
        if wartosc is None or biezaca is None:
            if wartosc != biezaca:
                rozbieznosci.append(f"{pole}: {wartosc} → {biezaca}")
            continue
        tol = TOLERANCJE.get(pole)
        if tol is None:                       # wartości tekstowe i logiczne
            if wartosc != biezaca:
                rozbieznosci.append(f"{pole}: {wartosc!r} → {biezaca!r}")
        elif abs(float(wartosc) - float(biezaca)) > tol:
            rozbieznosci.append(
                f"{pole}: {wartosc} → {biezaca} (tolerancja ±{tol})")

    assert not rozbieznosci, (
        f"wyniki dla „{nazwa}” przesunęły się:\n  " + "\n  ".join(rozbieznosci)
        + "\n\nJeśli to zamierzona zmiana algorytmu, odśwież migawkę:\n"
          "  python -m tests.test_regresja_biblioteka --zapisz")


if __name__ == "__main__":
    if "--zapisz" in sys.argv:
        raise SystemExit(0 if zapisz_migawke() else 1)
    print(__doc__)
