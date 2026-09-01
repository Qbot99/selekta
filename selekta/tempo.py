"""Wykrywanie zmiennego tempa — czy siatka utrzyma się do końca utworu.

Jedna kotwica plus stałe BPM działa tylko dla materiału zrobionego na
siatce. Stare rippy z winyla, edity live'owe i część bootlegów dryfują:
początek wygląda idealnie, a w drugiej połowie siatka jest obok bitu.
Bez ostrzeżenia DJ dowiaduje się o tym na parkiecie.

Mierzymy to wprost, a nie przez porównywanie oszacowań BPM: w kolejnych
oknach liczymy FAZĘ siatki tym samym sposobem co przy kotwicy, a potem
rozwijamy ją w czasie. Stałe tempo daje fazę płaską. Tempo choćby
odrobinę inne niż przyjęte daje fazę wędrującą liniowo — a nachylenie
tej prostej mówi, o ile siatka rozjedzie się do końca.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .cues import FPS, _decode, _envelopes, faza_siatki

OKNO_S = 20.0            # długość okna pomiarowego
KROK_S = 10.0            # co ile stawiamy okno (połowa okna = zakładka)
MIN_OKIEN = 4            # przy krótszym materiale nie ma czego badać
PROG_BITU = 0.25         # rozjazd powyżej ćwierci bitu psuje synchronizację
PROG_WAHANIA = 0.07      # MAD reszt powyżej tego = tempo naprawdę faluje
MIN_PEWNOSC = 0.06       # poniżej tego okno nie ma słyszalnego pulsu


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


def _faza_i_pewnosc(flux: np.ndarray, bpm: float) -> tuple[float, float]:
    """Faza siatki i to, na ile ten fragment w ogóle ma puls.

    Pewność to udział prążka tempa w całej energii onsetów. W breakdownie
    albo ambientowym intrze perkusji nie ma, więc faza jest przypadkowa —
    bez tej miary takie okna udawałyby falujące tempo i apka krzyczałaby
    na co drugim utworze.
    """
    if flux.size < 8 or bpm <= 0:
        return 0.0, 0.0
    okres = 60.0 / bpm
    t = np.arange(flux.size) / FPS
    z = np.sum(flux * np.exp(-2j * np.pi * t / okres))
    suma = float(np.sum(np.abs(flux)))
    if suma <= 0:
        return 0.0, 0.0
    faza = float(((-np.angle(z) / (2 * np.pi)) * okres) % okres)
    return faza, float(abs(z) / suma)


def _fazy_w_oknach(flux: np.ndarray, bpm: float
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fazy w kolejnych oknach: (czasy, fazy, pewności).

    Faza jest liczona względem POCZĄTKU fragmentu, a okna zaczynają się
    w różnych momentach — dlatego dodajemy przesunięcie okna. Bez tego
    nawet równy metronom wyglądałby na dryfujący.
    """
    okno = int(OKNO_S * FPS)
    krok = int(KROK_S * FPS)
    okres = 60.0 / bpm
    czasy, fazy, pewnosci = [], [], []
    for start in range(0, max(1, flux.size - okno + 1), krok):
        wycinek = flux[start:start + okno]
        if wycinek.size < okno // 2:
            break
        lokalna, pewnosc = _faza_i_pewnosc(wycinek, bpm)
        czasy.append((start + okno / 2) / FPS)
        fazy.append((lokalna + start / FPS) % okres)
        pewnosci.append(pewnosc)
    return np.array(czasy), np.array(fazy), np.array(pewnosci)


def _rozwin(fazy: np.ndarray, okres: float) -> np.ndarray:
    """Rozwiń fazę, żeby przeskok z końca okresu na początek nie udawał skoku.

    Faza żyje w [0, okres). Utwór, którego tempo jest minimalnie wyższe
    od przyjętego, daje ciąg 0.05, 0.15, 0.25, 0.35... aż przeskoczy przez
    zero. Bez rozwinięcia zobaczylibyśmy nagły spadek zamiast równej rampy.
    """
    if fazy.size == 0:
        return fazy
    return np.unwrap(fazy / okres * 2 * np.pi) / (2 * np.pi) * okres


def zbadaj(path: str, bpm: float | None) -> Stabilnosc:
    """Sprawdź, czy stałe BPM opisuje ten utwór do samego końca."""
    if not bpm or bpm <= 0:
        return Stabilnosc(opis="bez BPM nie ma czego sprawdzać")
    x = _decode(path)
    if x.size == 0:
        return Stabilnosc(opis="nie udało się odczytać dźwięku")
    _total, _low, flux = _envelopes(x)
    czasy, fazy, pewnosci = _fazy_w_oknach(flux, bpm)
    # Zostawiamy tylko okna z wyraźnym pulsem. Breakdown i ambientowe intro
    # nie mówią nic o tempie, a potrafią zepsuć cały pomiar.
    if pewnosci.size:
        prog = max(MIN_PEWNOSC, float(np.median(pewnosci)) * 0.6)
        maska = pewnosci >= prog
        czasy, fazy = czasy[maska], fazy[maska]
    if czasy.size < MIN_OKIEN:
        return Stabilnosc(okien=int(czasy.size),
                          opis="za mało fragmentów z wyraźnym bitem, "
                               "żeby ocenić stabilność tempa")

    okres = 60.0 / bpm
    rozwiniete = _rozwin(fazy, okres)
    czas_utworu = flux.size / FPS

    # Prosta dopasowana do fazy opisuje STAŁE tempo różniące się od
    # przyjętego. Reszta po jej odjęciu to dopiero prawdziwa zmienność.
    nachylenie, wyraz = np.polyfit(czasy, rozwiniete, 1)
    reszty = rozwiniete - (nachylenie * czasy + wyraz)

    dryf = float(abs(nachylenie) * czas_utworu)
    # Odchylenie MEDIANOWE, nie rozstęp. Pojedynczy breakdown, który
    # przemknął przez filtr pewności, potrafi dać pół bitu rozstępu przy
    # idealnie równym utworze — zmierzone: prawdziwa muzyka ma MAD 0,01-0,04,
    # a syntetyczna rampa tempa 0,11. Rozstęp tych przypadków nie rozdziela.
    wahanie = (float(np.median(np.abs(reszty - np.median(reszty))))
               if reszty.size else 0.0)

    s = Stabilnosc(
        okien=int(czasy.size),
        dryf_s=round(dryf, 3), dryf_bitu=round(dryf / okres, 3),
        wahanie_bitu=round(wahanie / okres, 3),
    )

    # 1) czy tempo NAPRAWDĘ faluje — tego nie naprawi żadna liczba
    if s.wahanie_bitu > PROG_WAHANIA and czasy.size >= MIN_OKIEN + 2:
        s.stabilne = False
        s.opis = (f"tempo faluje — nawet po poprawieniu BPM siatka odchyla "
                  f"się o {s.wahanie_bitu:.2f} bitu. Ustaw ją ręcznie na "
                  f"fragmencie, który grasz.")
        return s

    # 2) tempo stałe, ale nasza liczba minimalnie nietrafiona
    if s.dryf_bitu > PROG_BITU:
        s.bpm_nietrafione = True
        s.bpm_poprawione = round(bpm / (1 + nachylenie), 2)
        s.opis = (f"tempo jest stałe, ale BPM lekko nietrafione — przy "
                  f"{bpm:.2f} siatka rozjeżdża się o {round(dryf * 1000)} ms "
                  f"do końca utworu. Lepiej pasuje {s.bpm_poprawione}.")
        return s

    s.opis = "tempo stałe, siatka utrzyma się do końca"
    return s
