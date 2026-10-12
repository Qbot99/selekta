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


SZEROKOSC_GNIAZDA = 4.0       # BPM: tyle mieści się „bez ruszania pitcha"


def _gniazda(dobre: list[dict]) -> list[tuple[str, float, list[dict]]]:
    """Gniazda: utwory w tej samej tonacji, których tempo mieści się w oknie
    SZEROKOSC_GNIAZDA BPM — okno przesuwne, nie sztywne kubełki.

    Sztywne kubełki z zaokrągleniem dzieliły 140–141,5 i 142–142,5 BPM na
    dwa pasma, więc sześć utworów 8A, które da się zmiksować bez ruszania
    pitcha, nie tworzyło gniazda. Teraz bierzemy najgęstsze okno, potem
    następne z tego, co zostało.
    """
    po_tonacji: dict[str, list[dict]] = defaultdict(list)
    for t in dobre:
        po_tonacji[t["camelot"]].append(t)
    wynik = []
    for tonacja, lista in po_tonacji.items():
        zostaly = sorted(lista, key=lambda t: t["bpm"])
        while zostaly:
            najlepsze = (0, 0)                      # (ile, start)
            j = 0
            for i in range(len(zostaly)):
                while zostaly[i]["bpm"] - zostaly[j]["bpm"] > SZEROKOSC_GNIAZDA:
                    j += 1
                if i - j + 1 > najlepsze[0]:
                    najlepsze = (i - j + 1, j)
            ile, start = najlepsze
            grupa = zostaly[start:start + ile]
            wynik.append((tonacja, sum(t["bpm"] for t in grupa) / len(grupa), grupa))
            zostaly = zostaly[:start] + zostaly[start + ile:]
    return wynik


def rozklad_formatow(sciezki: list[str]) -> list[dict]:
    """Ile utworów w jakim formacie (i ile miejsca zajmują)."""
    import os

    ile: Counter = Counter()
    bajty: Counter = Counter()
    for p in sciezki:
        ext = os.path.splitext(p)[1].lower().lstrip(".") or "?"
        ext = {"aif": "aiff"}.get(ext, ext)
        ile[ext] += 1
        try:
            bajty[ext] += os.path.getsize(p)
        except OSError:
            pass
    bezstratne = {"flac", "wav", "aiff"}
    return [{"format": f.upper(), "ile": n, "mb": round(bajty[f] / 1_000_000),
             "bezstratny": f in bezstratne}
            for f, n in sorted(ile.items(), key=lambda kv: (-kv[1], kv[0]))]


def policz(utwory: list[dict]) -> dict:
    """Rozkład i luki. `utwory` to słowniki z bpm, camelot, title, artist."""
    dobre = [t for t in utwory if t.get("bpm") and t.get("camelot")]

    rozklad_bpm = Counter(_pasmo(t["bpm"]) for t in dobre)
    rozklad_tonacji = Counter(t["camelot"] for t in dobre)

    # gniazda: ta sama tonacja, tempo w oknie SZEROKOSC_GNIAZDA BPM
    gniazda = _gniazda(dobre)

    luki = []
    for tonacja, srednie_bpm, lista in sorted(gniazda, key=lambda g: -len(g[2])):
        if len(lista) < MIN_GNIAZDO:
            continue
        pasmo = int(round(srednie_bpm))
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
        "gniazd": sum(1 for _t, _b, v in gniazda if len(v) >= MIN_GNIAZDO),
    }
