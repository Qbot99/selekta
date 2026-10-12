"""Wykrywanie struktury utworu: intro/outro, pierwsze uderzenie i drop.

DJ potrzebuje dwóch rzeczy z każdego utworu: dokładnego pierwszego
uderzenia (kotwica beatgridu) oraz kilku punktów cue opisujących
przebieg energii — koniec intra, początek outra i ewentualny drop
(breakdown -> drop). Wszystko liczymy z obwiedni energii, bez zewnętrznych
zależności poza ffmpeg/numpy.

Sygnał dekodujemy do mono 11025 Hz (ffmpeg) i liczymy krótkookienkowy
STFT (okno ~93 ms, hop ~46 ms). Z niego powstają trzy obwiednie na klatkę:

  * total  — energia szerokopasmowa (ogólna głośność aranżacji),
  * low    — energia pasma <=250 Hz (stopa + bas),
  * flux   — spektralny flux (detektor onsetów, do pierwszego uderzenia).

Punkty czasowe:

  * first_beat_s  — pierwszy wyraźny onset po ciszy/fade-inie; przy podanym
    BPM dociągany do najbliższego silnego transientu w obrębie jednego bitu.
  * intro_end_s   — pierwsza granica frazy (co 4 takty od jedynki), na której
    coś wchodzi (bas, melodia, wyraźny skok w którymś paśmie); bez tempa —
    chwila, od której energia basu utrzymuje się trwale.
  * outro_start_s — ostatnia granica frazy w drugiej połowie, za którą coś
    odchodzi albo przed którą jest przejście; bez tempa — koniec ostatniego
    trwałego odcinka pełnej energii.
  * drop_s        — największy skok energii poprzedzony wcześniejszym
    spadkiem (breakdown -> drop); None, gdy brak wyraźnego.

Wartości są zawsze uporządkowane: 0 <= first_beat < intro_end < outro_start
< duration, a drop (jeśli jest) leży w środku utworu. Pusty lub bardzo
krótki plik zwraca Cues z sensownymi zerami zamiast wyjątku.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import math

import numpy as np

from . import siatka
from .narzedzia import ffmpeg_path, ffprobe_path

# ---------------------------------------------------------------- stałe

SR = 11025            # częstotliwość analizy (mono)
N_FFT = 1024          # okno STFT ~92.9 ms
HOP = 512             # hop ~46.4 ms  ->  fps ~21.53 klatek/s
FPS = SR / HOP
# Klatka k obejmuje próbki [k*HOP, k*HOP+N_FFT), a indeks etykietuje jej
# POCZĄTEK. Czas zdarzenia leży bliżej środka okna, więc bez tej poprawki
# każdy moment liczony z klatek wypada systematycznie o pół okna za wcześnie
# — przy 150 BPM to 12% bitu, czyli widocznie przesunięta siatka.
# Stosujemy ją TYLKO tam, gdzie faza zamienia się na moment w pliku:
# przy pomiarze dryfu tempa jest to stałe przesunięcie, które i tak
# znika przy odejmowaniu, a na sztucznej obwiedni w testach nie ma
# żadnego okna STFT, więc korekta byłaby błędem.
OPOZNIENIE_OKNA_S = N_FFT / (2 * SR)

LOW_HZ = 250.0        # górna granica pasma "stopa + bas"

# okna wygładzania i analizy (w sekundach)
SMOOTH_S = 0.75       # wygładzanie obwiedni poziomu
SUSTAIN_S = 3.0       # jak długo energia musi się utrzymać, by uznać ją za trwałą
DROP_WIN_S = 2.5      # okno przed/po do wykrycia skoku energii (drop)

MIN_LEN_S = 3.0       # krótszy materiał traktujemy jako zbyt krótki
EPS = 0.05            # minimalny odstęp między punktami (porządkowanie)


@dataclass
class Cues:
    duration_s: float
    first_beat_s: float
    intro_end_s: float
    outro_start_s: float
    drop_s: float | None
    # siatka beatów (moduł siatka.py): kotwica leży na STOPIE, nie na byle onsecie
    battito: int = 1                     # numer bitu w takcie dla kotwicy (1–4)
    bpm_siatki: float | None = None      # BPM dostrojone do stopy (całkowite, gdy tak wychodzi)
    pewnosc_siatki: float | None = None  # spójność kicków z siatką, 0–1
    pewnosc_taktu: float | None = None   # przewaga jedynki taktu nad drugą kandydatką, 0–1


# ---------------------------------------------------------------- dekodowanie

def _duration(path: str) -> float:
    """Długość utworu w sekundach (ffprobe); 0.0 gdy nieznana."""
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _decode(path: str) -> np.ndarray:
    """Cały utwór jako mono float32 PCM przez ffmpeg (wzorzec z quality.py)."""
    out = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-i", path,
         "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def _stft_mags(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """Magnitudy STFT, okno Hanninga (jak w harmonic.py)."""
    n_frames = (len(x) - n_fft) // hop
    if n_frames < 1:
        return np.zeros((0, n_fft // 2 + 1))
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1))


# ---------------------------------------------------------------- obwiednie

def _envelopes(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Zwraca (total, low, flux) — energię szerokopasmową, energię pasma
    niskiego (stopa+bas) i spektralny flux (onsety) na klatkę."""
    mags = _stft_mags(x, N_FFT, HOP)
    if mags.shape[0] == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    low_band = freqs <= LOW_HZ

    power = mags ** 2
    total = power.sum(axis=1)
    low = power[:, low_band].sum(axis=1)
    # spektralny flux na logarytmicznie skompresowanych magnitudach
    flux = np.maximum(np.diff(np.log1p(1000.0 * mags), axis=0), 0.0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])           # wyrównanie długości do total
    return total, low, flux


def _smooth(a: np.ndarray, sec: float) -> np.ndarray:
    """Wygładzanie ruchomą średnią o oknie `sec` sekund."""
    w = max(1, int(round(sec * FPS)))
    if w <= 1 or a.size == 0:
        return a
    kernel = np.ones(w) / w
    return np.convolve(a, kernel, mode="same")


def _levels(env: np.ndarray) -> tuple[float, float]:
    """(dolny poziom szumu, typowy poziom "pełnej" energii) z percentyli."""
    if env.size == 0:
        return 0.0, 1.0
    floor = float(np.percentile(env, 5))
    hi = env > np.percentile(env, 60)
    full = float(np.median(env[hi])) if hi.any() else float(np.percentile(env, 90))
    if full <= floor:
        full = floor + 1e-9
    return floor, full


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Przedziały [start, end) kolejnych wartości True w masce logicznej."""
    if mask.size == 0 or not mask.any():
        return []
    d = np.diff(mask.astype(np.int8))
    starts = list(np.where(d == 1)[0] + 1)
    ends = list(np.where(d == -1)[0] + 1)
    if mask[0]:
        starts.insert(0, 0)
    if mask[-1]:
        ends.append(mask.size)
    return list(zip(starts, ends))


# ---------------------------------------------------------------- detekcje

def faza_siatki(flux: np.ndarray, bpm: float | None) -> float:
    """Przesunięcie siatki beatów względem początku pliku, w sekundach.

    Pojedynczy onset to za mało: pierwszym dźwiękiem bywa fade-in, sweep
    albo oddech wokalisty, więc kotwica lądowała obok siatki — przy 150 BPM
    nawet o pół uderzenia, co psuje synchronizację w rekordboksie.

    Zamiast tego liczymy FAZĘ prążka tempa w widmie obwiedni onsetów.
    Każde uderzenie w całym utworze dokłada się do jednego zespolonego
    sumowania, więc wynik jest odporny na pojedyncze fałszywe onsety
    i ma rozdzielczość lepszą niż jedna klatka analizy.
    """
    if not bpm or bpm <= 0 or flux.size < 8:
        return 0.0
    okres = 60.0 / bpm
    t = np.arange(flux.size) / FPS
    z = np.sum(flux * np.exp(-2j * np.pi * t / okres))
    if abs(z) < 1e-9:
        return 0.0
    # kąt prążka → moment pierwszego uderzenia w obrębie jednego okresu
    zgrubna = float(((-np.angle(z) / (2 * np.pi)) * okres) % okres)
    return _dostroj_faze(flux, okres, zgrubna)


def _suma_na_siatce(flux: np.ndarray, okres: float, faza: float) -> float:
    """Średnia siła onsetów w punktach siatki, z interpolacją między klatkami.

    Obwiednia ma ~21,5 klatki na sekundę, więc zaokrąglanie pozycji siatki
    do klatki gubi nawet 23 ms — przy 150 BPM to 6% bitu. Interpolacja
    liniowa pozwala porównywać fazy dokładniej, niż wynika z rozdzielczości.
    """
    if flux.size < 2:
        return 0.0
    czasy = np.arange(faza, flux.size / FPS, okres)
    if czasy.size == 0:
        return 0.0
    return float(np.mean(np.interp(czasy * FPS, np.arange(flux.size), flux)))


def _dostroj_faze(flux: np.ndarray, okres: float, zgrubna: float) -> float:
    """Popraw fazę drobnym przeszukaniem wokół oszacowania z widma.

    Widmo daje dobry punkt startowy, ale obwiednia onsetów nie jest czystą
    sinusoidą — realne uderzenie ma ostre zbocze, więc szczyt bywa lekko
    obok prążka. Sprawdzamy okolicę i wybieramy fazę o najmocniejszych
    trafieniach w uderzenia.
    """
    najlepsza, najlepszy_wynik = zgrubna, -1.0
    krok = okres / 120.0                       # ok. 3 ms przy 150 BPM
    for i in range(-20, 21):                   # ±1/6 bitu wokół oszacowania
        kandydat = (zgrubna + i * krok) % okres
        wynik = _suma_na_siatce(flux, okres, kandydat)
        if wynik > najlepszy_wynik:
            najlepsza, najlepszy_wynik = kandydat, wynik
    return najlepsza


def _poczatek_muzyki(total: np.ndarray) -> int:
    """Klatka, od której utwór faktycznie gra (po ciszy i fade-inie)."""
    if total.size == 0:
        return 0
    floor, full = _levels(total)
    thr = floor + 0.10 * (full - floor)
    above = np.where(total > thr)[0]
    return int(above[0]) if above.size else 0


def _first_beat(total: np.ndarray, flux: np.ndarray,
                bpm: float | None) -> float:
    """Czas pierwszego uderzenia [s] — kotwica beatgridu, leżąca NA siatce.

    Zwracamy sekundy, nie numer klatki: zaokrąglenie do klatki (46 ms)
    zjadałoby 6% bitu przy 150 BPM, a właśnie o tę precyzję tu chodzi.
    """
    if total.size == 0:
        return 0
    i0 = _poczatek_muzyki(total)
    if not bpm or bpm <= 0:
        # bez tempa nie ma siatki — zostaje najmocniejszy onset przy starcie
        half = int(round(0.25 * FPS))
        lo, hi = max(0, i0 - half), min(flux.size, i0 + half + 1)
        klatka = lo + int(np.argmax(flux[lo:hi])) if hi > lo else i0
        return klatka / FPS

    okres = 60.0 / bpm
    # Dopiero tutaj faza staje się momentem w pliku, więc dopiero tutaj
    # trzeba oddać opóźnienie okna STFT. Sama faza_siatki liczy czystą
    # matematykę na obwiedni i nie wie, jak ta obwiednia powstała.
    przesuniecie = (faza_siatki(flux, bpm) + OPOZNIENIE_OKNA_S) % okres
    start = i0 / FPS
    # pierwsze uderzenie siatki nie wcześniejsze niż początek muzyki
    k = math.ceil((start - przesuniecie) / okres - 1e-9)
    return przesuniecie + max(k, 0) * okres


def _intro_end(low: np.ndarray, start: int) -> int:
    """Pierwsza klatka, od której bas (pasmo niskie) utrzymuje się trwale."""
    low_s = _smooth(low, SMOOTH_S)
    if low_s.size == 0:
        return start
    floor, full = _levels(low_s)
    thr = floor + 0.35 * (full - floor)
    on = low_s > thr
    w = max(1, int(round(SUSTAIN_S * FPS)))
    n = low_s.size
    for f in range(start, n):
        seg = on[f:min(n, f + w)]
        if seg.size and seg.mean() >= 0.9:
            return f
    return start


# ---------------------------------------------------------------- struktura na siatce fraz
#
# Koniec intra i początek outra wypadają na granicach fraz (wielokrotności
# 4 taktów od jedynki) — tak liczy je rekordbox i tak gra DJ. Zamiast
# szukać „basu na stałe” (stopa też jest basem, więc intro z samą stopą
# kończyło się na pierwszym uderzeniu: 3/4 wzorców i 26/73 realnych
# utworów w przeglądzie 0.4.2) porównujemy całe takty: poziom w pięciu
# pasmach, poziom całości i „bas trwały” (25. percentyl pasma < 120 Hz —
# stopa między uderzeniami cichnie, linia basu nie).
#
# Strojone na 19 utworach speeding z frazami rekordboxa (PSSI), sprawdzane
# na 32 innych (raport napraw): intro ±4 s 5/19 → 13/19 (strojenie),
# 16/32 → 20/32 (kontrola); outro 3/19 → 13/19, 8/31 → 16/31.

_PASMA = {"sub": (0.0, 120.0), "low": (0.0, 250.0), "lowmid": (250.0, 1000.0),
          "mid": (1000.0, 3000.0), "high": (3000.0, SR / 2.0)}
NOWOSC_DB = 1.5          # zmiana mediany 2 taktów w którymkolwiek paśmie
OKNO_TAKTOW = 2
WSTEP_MIN_TAKTOW = 2     # tyle taktów grania przed pierwszą jedynką = intro bez stopy
INTRO_MAX_TAKTOW = 32
PRZEJSCIE_DB = 3.0       # takt ciszej o tyle przed granicą = przejście (fill) przed outrem
OUTRO_MIN_TAKTOW = 4


def _pasma(x: np.ndarray) -> dict[str, np.ndarray]:
    """Moc na klatkę w pasmach do porównywania taktów."""
    mags = _stft_mags(x, N_FFT, HOP)
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    moc = mags ** 2
    out = {k: moc[:, (freqs > lo) & (freqs <= hi)].sum(axis=1) if lo > 0
           else moc[:, freqs <= hi].sum(axis=1) for k, (lo, hi) in _PASMA.items()}
    out["total"] = moc.sum(axis=1)
    return out


def _takty(pasma: dict, first_beat_s: float, bpm: float, battito: int):
    """Cechy taktów (dB) od pierwszej jedynki — także przed nią, dopóki gra.

    Zwraca (początki taktów [s], macierz cech, indeks taktu z jedynką, jedynka [s]).
    """
    okres = 60.0 / bpm
    takt = 4 * okres
    d0 = first_beat_s + ((1 - int(battito or 1)) % 4) * okres
    tot = pasma["total"]
    czas = tot.size / FPS
    p5, p60 = np.percentile(tot, 5), np.percentile(tot, 60)
    prog = p5 + 0.02 * (p60 - p5)
    k0 = 0
    while d0 + (k0 - 1) * takt >= 0:
        a, b = int(round((d0 + (k0 - 1) * takt) * FPS)), int(round((d0 + k0 * takt) * FPS))
        if b <= a or tot[a:b].mean() <= prog:
            break
        k0 -= 1
    starty = d0 + np.arange(k0, int((czas - d0) / takt)) * takt
    klucze = ("sub", "low", "lowmid", "mid", "high", "total")
    F = np.zeros((len(starty), len(klucze) + 1))
    for i, t in enumerate(starty):
        a, b = int(round(t * FPS)), max(int(round((t + takt) * FPS)), int(round(t * FPS)) + 1)
        for j, k in enumerate(klucze):
            F[i, j] = 10 * np.log10(pasma[k][a:b].mean() + 1e-12)
        F[i, -1] = 10 * np.log10(np.percentile(pasma["sub"][a:b], 25) + 1e-12)   # bas trwały
    return starty, F, -k0, d0


def _zmiana(F: np.ndarray, c: int, okno: int) -> np.ndarray | None:
    przed, po = F[max(0, c - okno):c], F[c:c + okno]
    if len(po) < okno or len(przed) == 0:
        return None
    return np.median(po, axis=0) - np.median(przed, axis=0)


def _intro_end_frazy(pasma: dict, first_beat_s: float, bpm: float, battito: int) -> float:
    """Koniec intra [s]: pierwsza granica frazy, na której coś wchodzi.

    Kandydaci: pierwsza jedynka (gdy przed nią gra już coś bez stopy — wtedy
    to jest intro) i co 4 takty dalej, do 32 taktów i 45 % utworu. Gdy nic
    wyraźnie nie wchodzi, utwór nie ma intra — zwracamy pierwszą jedynkę.
    """
    starty, F, i0, d0 = _takty(pasma, first_beat_s, bpm, battito)
    if len(starty) < i0 + 2 * OKNO_TAKTOW:
        return d0
    limit = min(i0 + INTRO_MAX_TAKTOW, int(len(starty) * 0.45))
    kandydaci = ([i0] if i0 >= WSTEP_MIN_TAKTOW else []) + list(range(i0 + 4, limit + 1, 4))
    for c in kandydaci:
        z = _zmiana(F, c, OKNO_TAKTOW)
        if z is not None and float(z.max()) >= NOWOSC_DB:
            return float(starty[c])
    return float(d0)


def _outro_start_frazy(pasma: dict, first_beat_s: float, bpm: float, battito: int) -> float | None:
    """Początek outra [s]: ostatnia granica frazy w drugiej połowie utworu,
    za którą coś wyraźnie odchodzi albo przed którą jest przejście (takt
    ciszej o 3 dB, po nim powrót) — co najmniej 4 takty przed końcem."""
    starty, F, i0, _ = _takty(pasma, first_beat_s, bpm, battito)
    n = len(starty)
    czas = pasma["total"].size / FPS
    kandydaci = [c for c in range(i0 + 4, n - OUTRO_MIN_TAKTOW + 1, 4) if starty[c] >= 0.5 * czas]
    for c in reversed(kandydaci):
        z = _zmiana(F, c, OKNO_TAKTOW)
        przejscie = (c >= 5 and F[c - 1, 5] <= np.median(F[c - 5:c - 1, 5]) - PRZEJSCIE_DB
                     and F[c, 5] >= F[c - 1, 5] + PRZEJSCIE_DB / 2)
        if (z is not None and float(z.min()) <= -NOWOSC_DB) or przejscie:
            return float(starty[c])
    return None


def _outro_start(total: np.ndarray, end_limit: int) -> int:
    """Klatka, od której energia trwale opada (początek outra)."""
    tot_s = _smooth(total, SMOOTH_S)
    if tot_s.size == 0:
        return end_limit
    floor, full = _levels(tot_s)
    thr = floor + 0.50 * (full - floor)
    on = tot_s > thr
    w = max(1, int(round(SUSTAIN_S * FPS)))
    runs = [r for r in _true_runs(on) if (r[1] - r[0]) >= w]
    if not runs:
        return end_limit
    # koniec ostatniego trwałego odcinka pełnej energii
    return int(runs[-1][1])


def _drop(total: np.ndarray, lo: int, hi: int) -> int | None:
    """Klatka największego skoku energii poprzedzonego spadkiem, albo None.

    "Wcześniejszy spadek" musi być prawdziwym breakdownem — obniżeniem
    energii PO wcześniejszej pełnej sekcji, a nie samym intrem. Dlatego
    wymagamy, by przed zagłębieniem energia zdążyła już osiągnąć pełny
    poziom (prefix-max), co odcina wejście z intra do głównego grooveu.
    """
    tot_s = _smooth(total, 1.0)
    if tot_s.size == 0 or hi - lo < int(FPS):
        return None
    floor, full = _levels(tot_s)
    span = full - floor
    w = max(1, int(round(DROP_WIN_S * FPS)))
    prefix_max = np.maximum.accumulate(tot_s)

    thr_break = floor + 0.55 * span        # "cichy" breakdown przed dropem
    thr_high = floor + 0.65 * span         # pełna energia po dropie
    best_rise = 0.30 * span                # minimalny znaczący skok
    best_f: int | None = None
    for f in range(max(lo, w), min(hi, tot_s.size - 1)):
        pre = float(tot_s[f - w:f].mean())
        post = float(tot_s[f:f + w].mean())
        rise = post - pre
        # energia musiała już być pełna PRZED zagłębieniem (prawdziwy breakdown)
        prior_full = prefix_max[f - w - 1] > thr_high if f - w - 1 >= 0 else False
        if prior_full and pre < thr_break and post > thr_high and rise > best_rise:
            best_rise = rise
            best_f = f
    return best_f


# ---------------------------------------------------------------- API

def analyze(path: str, bpm: float | None = None) -> Cues:
    """Wykryj punkty struktury utworu z obwiedni energii.

    path -- ścieżka do pliku audio (dowolny format czytany przez ffmpeg).
    bpm  -- opcjonalne BPM; pozwala dociągnąć pierwsze uderzenie do bitu.
    """
    duration = _duration(path)
    x = _decode(path)
    if duration <= 0.0 and x.size:
        duration = x.size / SR

    # pusty lub zbyt krótki materiał -> sensowne zera, bez wyjątku
    if x.size < SR * MIN_LEN_S:
        return Cues(round(duration, 3), 0.0, 0.0, round(max(duration, 0.0), 3), None)

    total, low, flux = _envelopes(x)
    if total.size == 0:
        return Cues(round(duration, 3), 0.0, 0.0, round(duration, 3), None)

    n = total.size
    # Siatka: przy znanym tempie kotwicę i BPM daje moduł siatka (stopa,
    # nie hi-hat). Spektralny flux zostaje tylko jako zapas, gdy w utworze
    # nie ma wyraźnych stóp (ambient, a cappella) albo nie ma tempa.
    s = siatka.oszacuj(x, SR, bpm, od_s=_poczatek_muzyki(total) / FPS) if bpm else None
    if s is not None:
        first_beat = s.first_beat_s
    else:
        first_beat = _first_beat(total, flux, bpm)
    fb = int(round(first_beat * FPS))          # dalsze kroki liczą w klatkach
    ie = _intro_end(low, fb)
    os_ = _outro_start(total, n)
    dr = _drop(total, ie, os_)

    # zamiana klatek na sekundy (first_beat mamy już dokładny)
    intro_end = ie / FPS
    outro_start = os_ / FPS
    drop = (dr / FPS) if dr is not None else None
    # Przy znanym tempie intro i outro liczymy na siatce fraz (patrz wyżej);
    # stare obwiedniowe wartości zostają tylko jako zapas bez tempa.
    bpm_frazy = (s.bpm if s is not None and s.bpm else bpm)
    if bpm_frazy and bpm_frazy > 0:
        pasma = _pasma(x)
        battito = s.battito if s is not None else 1
        intro_end = _intro_end_frazy(pasma, first_beat, bpm_frazy, battito)
        o = _outro_start_frazy(pasma, first_beat, bpm_frazy, battito)
        if o is not None:
            outro_start = o

    # porządkowanie: 0 <= first_beat < intro_end < outro_start < duration
    first_beat = max(0.0, min(first_beat, duration))
    intro_end = max(intro_end, first_beat + EPS)
    outro_start = min(outro_start, duration - EPS)
    if outro_start <= intro_end:
        outro_start = min((intro_end + duration) / 2.0, duration - EPS)
    if intro_end >= outro_start:
        intro_end = max(first_beat + EPS, outro_start - EPS)

    # drop musi leżeć w środku (między intro a outrem)
    if drop is not None and not (intro_end < drop < outro_start):
        drop = None

    return Cues(
        round(duration, 3),
        round(first_beat, 3),
        round(intro_end, 3),
        round(outro_start, 3),
        round(drop, 3) if drop is not None else None,
        battito=s.battito if s else 1,
        bpm_siatki=s.bpm if s else None,
        pewnosc_siatki=s.pewnosc if s else None,
        pewnosc_taktu=s.pewnosc_taktu if s else None,
    )


def _mmss(seconds: float) -> str:
    """Sekundy -> "m:ss"."""
    s = int(round(max(0.0, seconds)))
    return f"{s // 60}:{s % 60:02d}"


def format_report(c: Cues) -> str:
    """Jednolinijkowe podsumowanie punktów cue po polsku (mm:ss)."""
    drop = _mmss(c.drop_s) if c.drop_s is not None else "brak"
    takt = f" (bit {c.battito} taktu)" if c.battito != 1 else ""
    return (
        f"Czas {_mmss(c.duration_s)} | "
        f"pierwsze uderzenie {_mmss(c.first_beat_s)}{takt} | "
        f"koniec intra {_mmss(c.intro_end_s)} | "
        f"początek outra {_mmss(c.outro_start_s)} | "
        f"drop {drop}"
    )
