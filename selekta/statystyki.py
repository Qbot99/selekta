"""Rozkład biblioteki i LUKI w możliwych przejściach.

Sklep powie Ci, co jest popularne. Nie powie, czego brakuje WŁAŚNIE TOBIE:
że masz czterdzieści kawałków 138 w 11A i ani jednego w 4A, więc z tego
gniazda nie ma jak wyjść.

Reguły miksu harmonicznego (koło Camelota): z tonacji można wyjść na
tę samą, sąsiednią (±1 na kole) albo równoległą (A↔B przy tym samym
numerze). Tempo ogranicza zakres pitcha CDJ-a — realnie ±6%.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict

ZAKRES_PITCHA = 0.06          # ±6% — tyle daje suwak w CDJ-u
MIN_GNIAZDO = 5               # od tylu utworów mówimy o „gnieździe"
UBOGIE_WYJSCIE = 2            # tyle lub mniej utworów = ślepy zaułek

_CAMELOT = re.compile(r"^(\d{1,2})([AB])$")


def rozbierz(camelot: str) -> tuple[int, str] | None:
    m = _CAMELOT.match((camelot or "").strip().upper())
    if not m:
        return None
    numer = int(m.group(1))
    return (numer, m.group(2)) if 1 <= numer <= 12 else None


def zgodne_tonacje(camelot: str) -> list[str]:
    """Tonacje, w które da się wyjść z podanej — reguły koła Camelota."""
    r = rozbierz(camelot)
    if not r:
        return []
    numer, litera = r
    naprzod = numer % 12 + 1
    wstecz = (numer - 2) % 12 + 1
    rownolegla = "B" if litera == "A" else "A"
    return [f"{numer}{litera}", f"{naprzod}{litera}",
            f"{wstecz}{litera}", f"{numer}{rownolegla}"]


def _pasuje_tempo(a: float, b: float) -> bool:
    """Czy da się zejść z tempa `a` do `b` samym pitchem."""
    if not a or not b:
        return False
    return abs(b - a) / a <= ZAKRES_PITCHA


def _pasmo(bpm: float, szerokosc: int = 4) -> int:
    return int(round(bpm / szerokosc) * szerokosc)


def policz(utwory: list[dict]) -> dict:
    """Rozkład i luki. `utwory` to słowniki z bpm, camelot, title, artist."""
    dobre = [t for t in utwory if t.get("bpm") and t.get("camelot")]

    rozklad_bpm = Counter(_pasmo(t["bpm"]) for t in dobre)
    rozklad_tonacji = Counter(t["camelot"] for t in dobre)

    # gniazda: (tonacja, pasmo tempa) z sensowną liczbą utworów
    gniazda: dict[tuple, list[dict]] = defaultdict(list)
    for t in dobre:
        gniazda[(t["camelot"], _pasmo(t["bpm"]))].append(t)

    luki = []
    for (tonacja, pasmo), lista in sorted(
            gniazda.items(), key=lambda kv: -len(kv[1])):
        if len(lista) < MIN_GNIAZDO:
            continue
        srednie_bpm = sum(t["bpm"] for t in lista) / len(lista)
        wyjscia = []
        for cel in zgodne_tonacje(tonacja):
            ile = sum(1 for t in dobre
                      if t["camelot"] == cel
                      and _pasuje_tempo(srednie_bpm, t["bpm"]))
            # Z utworu w 8A MOŻNA przejść na inny utwór w 8A — liczy się
            # więc całe gniazdo minus ten jeden, z którego wychodzimy.
            if cel == tonacja:
                ile = max(0, ile - 1)
            wyjscia.append({"tonacja": cel, "utworow": ile,
                            "ubogie": ile <= UBOGIE_WYJSCIE})
        slabe = [w for w in wyjscia if w["ubogie"]]
        if slabe:
            luki.append({
                "tonacja": tonacja, "bpm": pasmo, "masz": len(lista),
                "srednie_bpm": round(srednie_bpm, 1),
                "wyjscia": wyjscia,
                "brakujace": [w["tonacja"] for w in slabe],
            })

    # tonacje, w których nie masz NIC
    wszystkie = [f"{n}{l}" for n in range(1, 13) for l in ("A", "B")]
    puste = [k for k in wszystkie if rozklad_tonacji.get(k, 0) == 0]

    return {
        "utworow": len(utwory),
        "przeanalizowanych": len(dobre),
        "rozklad_bpm": [{"bpm": b, "ile": n}
                        for b, n in sorted(rozklad_bpm.items())],
        "rozklad_tonacji": [{"tonacja": k, "ile": rozklad_tonacji.get(k, 0)}
                            for k in wszystkie],
        "puste_tonacje": puste,
        "luki": luki[:12],
        "gniazd": sum(1 for v in gniazda.values() if len(v) >= MIN_GNIAZDO),
    }
