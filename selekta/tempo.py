"""Czy siatka utrzyma się do końca utworu — wniosek z silnika siatki (siatka.py).

Wcześniej ten moduł liczył fazę w oknach ze spektralnego fluxu, który myli
hi-haty z uderzeniami. Wychodziły z tego fałszywe alarmy „tempo faluje”
(20 z 73 utworów o stałym tempie w przeglądzie 0.4.2) i „poprawki” gorsze
od oryginału (137,06 zamiast 137,0). Teraz źródło prawdy jest jedno:
silnik siatki śledzi stopy przez cały utwór, sam wylicza dokładne BPM
z regresji i sam decyduje, czy tempo jest stałe, czy potrzebna jest siatka
dynamiczna. Ten moduł tylko tłumaczy jego wynik na odpowiedź dla ekranu.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cues import SR, _decode

PROG_NIETRAFIONE = 0.02   # podane BPM różni się od zmierzonego o więcej — warto poprawić
MIN_DLUGOSC_S = 40.0      # krócej: za mało taktów, żeby mówić o stabilności przez cały utwór


@dataclass
class Stabilnosc:
    """Czy tempo trzyma się przez cały utwór.

    Rozdzielamy dwie rzeczy, które łatwo pomylić:

    * **BPM lekko nietrafione** — tempo jest stałe, ale nasze oszacowanie
      różni się o ułamek procenta. Faza wędruje wtedy równo, po prostej,
      a lek jest jeden: poprawić liczbę. To NIE jest zmienne tempo i nie
      ma powodu straszyć tym użytkownika.
    * **tempo naprawdę zmienne** — faza nie układa się w prostą. Tego nie
      naprawi żadna pojedyncza liczba i dopiero to jest ostrzeżeniem.
    """
    stabilne: bool = True
    bpm_nietrafione: bool = False
    bpm_poprawione: float | None = None
    dryf_s: float = 0.0            # rozjazd z powodu złego BPM [s]
    dryf_bitu: float = 0.0
    wahanie_bitu: float = 0.0      # rozjazd, którego NIE naprawi lepsze BPM
    okien: int = 0
    opis: str = ""


def zbadaj(path: str, bpm: float | None) -> Stabilnosc:
    """Sprawdź, czy stałe BPM opisuje ten utwór do samego końca."""
    if not bpm or bpm <= 0:
        return Stabilnosc(opis="bez BPM nie ma czego sprawdzać")
    x = _decode(path)
    if x.size == 0:
        return Stabilnosc(opis="nie udało się odczytać dźwięku")
    if x.size < SR * MIN_DLUGOSC_S:
        return Stabilnosc(opis="utwór za krótki, żeby ocenić stabilność tempa")
    from . import siatka
    s = siatka.oszacuj(x, SR, bpm)
    if s is None:
        return Stabilnosc(opis="za mało wyraźnych uderzeń, żeby ocenić stabilność tempa")
    okien = len(s.znaczniki)
    if s.tryb == "dynamiczna":
        return Stabilnosc(stabilne=False, okien=okien, wahanie_bitu=round((s.odchylka_ms or 0) / 1000 * bpm / 60, 3),
                          opis=(f"tempo faluje — zmienia się w trakcie utworu; selekta ustawi siatkę dynamiczną "
                                f"({okien} znaczników tempa, każdy dopasowany do stóp). "
                                + ("Sprawdź uchem: " + s.flaga if s.flaga else "Przed graniem przesłuchaj przejścia.")))
    dokladne = s.bpm_dokladne or s.bpm
    if abs(dokladne - bpm) > PROG_NIETRAFIONE:
        okres_p, okres_d = 60.0 / bpm, 60.0 / dokladne
        dl = x.size / SR
        dryf = abs(okres_p - okres_d) * (dl / okres_d)
        return Stabilnosc(stabilne=True, bpm_nietrafione=True, bpm_poprawione=round(float(s.bpm), 2),
                          dryf_s=round(dryf, 3), dryf_bitu=round(dryf / okres_d, 3), okien=okien,
                          opis=(f"tempo jest stałe, ale podane {bpm:.2f} BPM jest obok — przy nim siatka "
                                f"rozjechałaby się o {round(dryf * 1000)} ms do końca utworu. "
                                f"Zmierzone ze stóp: {s.bpm:g} BPM."))
    return Stabilnosc(okien=okien, opis="tempo stałe, siatka utrzyma się do końca"
                      + (f" ({s.flaga})" if s.flaga else ""))
