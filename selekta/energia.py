"""Energia i struktura utworu — druga połowa układania setu.

Porządkowanie harmoniczne mówi, KTÓRE utwory da się złożyć. Nie mówi,
w jakiej kolejności set ma sens: czy nie zaczynasz od kulminacji, czy
w środku nie ma dziury, i czy w ogóle jest gdzie wejść.

Liczymy trzy rzeczy, każda z innego powodu:

* **krzywa energii** — RMS w czasie mówi, gdzie utwór ma masę;
* **jasność** (centroida widma) — odróżnia gęste techno od melodyjnego
  progresywnego przy tym samym RMS-ie;
* **gęstość perkusji** — liczba uderzeń na takt; po niej poznać
  breakdown i to, czy intro nadaje się do wejścia.

Granice fraz liczymy od kotwicy beatgridu. Ma to sens dopiero od chwili,
gdy kotwica naprawdę stoi na uderzeniu — przy przesuniętej frazy
wypadałyby obok i cała funkcja byłaby myląca.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .cues import FPS, SR, _decode, _envelopes, _stft_mags, HOP, N_FFT

TAKT = 4                      # uderzenia w takcie (4/4)
FRAZA_TAKTOW = 16             # typowa fraza w muzyce klubowej
CICHO = 0.35                  # próg breakdownu względem mediany energii


@dataclass
class Struktura:
    """Co wiemy o kształcie utworu."""
    krzywa: list[float] = field(default_factory=list)   # energia 0..1 w czasie
    czas_s: float = 0.0
    srednia: float = 0.0
    szczyt_s: float | None = None       # gdzie utwór jest najmocniejszy
    jasnosc: float = 0.0                # centroida widma w kHz
    gestosc_perkusji: float = 0.0       # uderzeń na takt
    breakdown_s: float = 0.0            # łączna długość cichych fragmentów
    intro_typ: str = ""                 # "perkusyjne" | "miękkie" | "od razu"
    faza: str = ""                      # "rozgrzewka" | "środek" | "kulminacja"
    frazy: list[float] = field(default_factory=list)     # granice fraz [s]


def _jasnosc_khz(x: np.ndarray) -> float:
    """Centroida widma — środek ciężkości energii w paśmie.

    Odróżnia gęste, ostre techno od melodyjnego kawałka o tej samej
    głośności. Sama głośność tego nie pokaże.
    """
    mags = _stft_mags(x, N_FFT, HOP)        # (klatki, prążki)
    if mags.size == 0:
        return 0.0
    czest = np.linspace(0, SR / 2, mags.shape[1])
    energia_klatek = mags.sum(axis=1)
    aktywne = energia_klatek > energia_klatek.max() * 0.05
    if not aktywne.any():
        return 0.0
    centroidy = (mags[aktywne] * czest).sum(axis=1) / energia_klatek[aktywne]
    return float(np.median(centroidy) / 1000.0)


def _gestosc(flux: np.ndarray, bpm: float | None) -> float:
    """Ile wyraźnych uderzeń przypada na takt.

    Dwa mechanizmy, każdy z pomiarów:

    * BRAMKA OKRESOWOŚCI — perkusja koreluje sama ze sobą przy opóźnieniu
      bitu, migotanie szumu na padzie nie. Zmierzone (autokorelacja fluxu
      przy 60/bpm): pad bez perkusji -0.56, wszystko z perkusją — także
      ciche i zmiksowane z melodią — od +0.27 (Flashback) do +0.88.
      Poniżej progu zwracamy 0: nie ma pulsu, nie ma gęstości.
    * PRÓG NA MAD (nie na odchyleniu standardowym, bo std zawyżają same
      kopnięcia). k=3 z pomiarów na realnej bibliotece: utwory klubowe
      139-150 BPM dają 4.7-6.9 zbocza na takt (syntetyczny bit 8.0), więc
      próg fazy >= 4.0 jest osiągalny z zapasem; wcześniejsze k=8 było
      przestrojone pod syntetyki i realne techno dawało 1.1-1.8, przez co
      peak-time lądował w „rozgrzewce". Liczymy zbocza narastające
      (osobne uderzenia), nie klatki nad progiem.
    """
    if flux.size < 8 or not bpm:
        return 0.0
    f = flux - flux.mean()
    lag = 60.0 / bpm * FPS
    n = int(2 ** np.ceil(np.log2(2 * len(f))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, n)) ** 2)[: len(f)]
    ac = ac / (ac[0] + 1e-12)
    if lag >= len(ac) - 1 or np.interp(lag, np.arange(len(ac)), ac) < 0.1:
        return 0.0
    med = float(np.median(flux))
    mad = float(np.median(np.abs(flux - med)))
    prog = med + 3.0 * mad
    zbocza = int(np.sum((flux[1:] > prog) & (flux[:-1] <= prog)))
    taktow = (flux.size / FPS) / (TAKT * 60.0 / bpm)
    return round(zbocza / taktow, 2) if taktow > 0 else 0.0


def granice_fraz(czas_s: float, bpm: float | None, kotwica: float,
                 taktow: int = FRAZA_TAKTOW) -> list[float]:
    """Momenty, w których wypada granica frazy — tam się wchodzi i wychodzi.

    Liczone od kotwicy beatgridu, więc wartość ma sens tylko wtedy, gdy
    kotwica stoi na uderzeniu.
    """
    if not bpm or bpm <= 0 or czas_s <= 0:
        return []
    dlugosc = taktow * TAKT * 60.0 / bpm
    granice, t = [], float(kotwica)
    while t < czas_s:
        if t >= 0:
            granice.append(round(t, 3))
        t += dlugosc
    return granice


def _intro(krzywa: np.ndarray, jasnosc_intro: float, srednia: float) -> str:
    """Czy da się w to wejść bez czekania.

    „perkusyjne" to intro na samych bębnach — najwygodniejsze do miksu.
    „od razu" znaczy, że utwór startuje pełną energią i wejście trzeba
    ustawić w konkretnym punkcie.
    """
    if krzywa.size < 4:
        return ""
    poczatek = float(krzywa[:max(2, krzywa.size // 12)].mean())
    if poczatek > 0.75 * srednia:
        return "od razu"
    # próg 1.4 kHz z pomiarów po naprawie centroidy (analiza mono 11 kHz):
    # realne utwory klubowe mają jasność 1.16-1.54; stare 2.0/2.2 były
    # kalibrowane pod zepsutą funkcję zwracającą zawsze ~2.76
    return "perkusyjne" if jasnosc_intro > 1.4 else "miękkie"


def analizuj(path: str, bpm: float | None = None,
             kotwica: float = 0.0, punkty: int = 240) -> Struktura:
    """Policz kształt utworu: energię, jasność, gęstość i frazy."""
    x = _decode(path)
    if x.size == 0:
        return Struktura()
    czas = x.size / SR
    total, low, flux = _envelopes(x)
    if total.size == 0:
        return Struktura(czas_s=round(czas, 2))

    # krzywa energii w stałej liczbie punktów — porównywalna między utworami
    punkty = max(16, min(punkty, 1000))
    na_punkt = max(1, total.size // punkty)
    uzyte = na_punkt * min(punkty, total.size // na_punkt)
    if uzyte == 0:
        return Struktura(czas_s=round(czas, 2))
    kubelki = total[:uzyte].reshape(-1, na_punkt)
    krzywa = kubelki.mean(axis=1)
    maks = float(krzywa.max()) or 1.0
    krzywa = krzywa / maks

    mediana = float(np.median(krzywa))
    cisza = krzywa < (mediana * CICHO)
    breakdown = float(cisza.sum()) / krzywa.size * czas

    jasnosc = _jasnosc_khz(x)
    jasnosc_intro = _jasnosc_khz(x[: int(SR * min(30.0, czas / 4))])

    s = Struktura(
        krzywa=[round(float(v), 3) for v in krzywa],
        czas_s=round(czas, 2),
        srednia=round(float(krzywa.mean()), 3),
        szczyt_s=round(float(np.argmax(krzywa)) / krzywa.size * czas, 1),
        jasnosc=round(jasnosc, 2),
        gestosc_perkusji=_gestosc(flux, bpm),
        breakdown_s=round(breakdown, 1),
        frazy=granice_fraz(czas, bpm, kotwica),
    )
    s.intro_typ = _intro(krzywa, jasnosc_intro, s.srednia)
    s.faza = _faza(s)
    return s


def _faza(s: Struktura) -> str:
    """Gdzie w secie ten utwór ma sens.

    Trzy sygnały naraz, bo każdy z osobna myli: głośny, ale ciemny
    i rzadki kawałek to nie kulminacja, tylko podkład.
    """
    punkty = 0
    if s.srednia >= 0.55:
        punkty += 1
    if s.jasnosc >= 1.4:
        punkty += 1
    if s.gestosc_perkusji >= 4.0:
        punkty += 1
    if s.breakdown_s > s.czas_s * 0.25:
        punkty -= 1                      # dużo pustki = raczej nie szczyt
    if punkty >= 3:
        return "kulminacja"
    if punkty <= 0:
        return "rozgrzewka"
    return "środek"


# --------------------------------------------------------------------------
# poziom setu
# --------------------------------------------------------------------------

def luk_setu(utwory: list[dict]) -> dict:
    """Oceń łuk energii całego setu w podanej kolejności.

    Szukamy dwóch rzeczy, które psują set mimo poprawnego doboru tonacji:
    dziury (nagły spadek w środku) i przedwczesnej kulminacji.
    """
    if not utwory:
        return {"punkty": [], "uwagi": [], "kulminacja": None}

    punkty = [{"i": i, "file": t.get("file", ""),
               "artist": t.get("artist", ""), "title": t.get("title", ""),
               "energia": round(float(t.get("srednia") or 0), 3),
               "faza": t.get("faza", ""), "bpm": t.get("bpm")}
              for i, t in enumerate(utwory)]

    energie = [p["energia"] for p in punkty]
    n = len(energie)
    szczyt = int(np.argmax(energie)) if n else 0
    uwagi = []

    # kulminacja za wcześnie — zostaje długa zjazdowa końcówka
    if n >= 5 and szczyt < n * 0.4:
        uwagi.append({
            "typ": "wczesna-kulminacja", "pozycja": szczyt,
            "opis": f"najmocniejszy utwór jest na pozycji {szczyt + 1} z {n} — "
                    f"po nim zostaje długi zjazd"})

    # dziura: wyraźny spadek między sąsiadami w środku setu
    for i in range(1, n - 1):
        spadek = energie[i - 1] - energie[i]
        if spadek > 0.22 and energie[i + 1] > energie[i] + 0.15:
            uwagi.append({
                "typ": "dziura", "pozycja": i,
                "opis": f"„{punkty[i]['title'] or punkty[i]['file']}” siada "
                        f"o {round(spadek * 100)}% względem poprzedniego "
                        f"i zaraz wracasz w górę"})

    # cały set na jednym poziomie — brak dramaturgii
    if n >= 6 and (max(energie) - min(energie)) < 0.18:
        uwagi.append({
            "typ": "plaski", "pozycja": None,
            "opis": "energia prawie się nie zmienia przez cały set — "
                    "brakuje narastania"})

    return {"punkty": punkty, "uwagi": uwagi, "kulminacja": szczyt}
