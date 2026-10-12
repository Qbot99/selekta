"""BPM and musical key detection plus harmonic set ordering (Mixed In Key style).

Named harmonic.py (not analysis.py) because analysis.py was being
edited concurrently by another session when this module was added.

BPM: spectral-flux onset envelope, autocorrelated and scored on a dense
tempo grid with comb-filter harmonics (a real tempo also shows energy at
2x/3x/4x its beat period).  A log-normal tempo prior centered on club
tempos implements the octave fold: a half/double-tempo lobe only wins
when its raw score dominates the true tempo's by a wide margin.

Key (v3, październik 2026): cały utwór (do 10 min) zdekodowany osobno
w 11 025 Hz -> estymacja stroju (A != 440 Hz) -> widmo w półtonach
własnego stroju utworu -> wybielanie (tłumi perkusję i szum) ->
nieujemna transkrypcja nut słownikiem z harmonicznymi (alikwoty basu nie
udają tercji) -> chroma basu (41-130 Hz) i środka (130-1047 Hz) -> profile
Krumhansla.  Dur/moll: profile + kontrast tercji; bez tercji (bas techno:
pryma + kwinta) tryb jest umowny — moll, jak w rekordboxie i Mixed In Key,
z pewnością poniżej progu „sprawdź uchem”.  Pewność = słabsze z dwóch
ogniw (tonika, tryb); key_alt podpowiada drugą możliwość.
Badanie i liczby: naprawy/tonacja-wynik.md (zgodność z prawdą z >= 2
niezależnych źródeł: rekordbox, Mixed In Key, Serato, Beatport).

Tags: TBPM/TKEY (ID3: MP3, WAV, AIFF) and BPM/INITIALKEY (Vorbis: FLAC)
get standard values the DJ software expects; the Camelot code goes only
into CAMELOT (Vorbis; COMMENT only when it holds no note of the DJ) /
TXXX:CAMELOT (ID3).

Analysis window (BPM): 75 s starting at 1/3 of the track duration, skipping
intros and outros.  Key: the whole track (see above).
"""
from __future__ import annotations

import re

import subprocess
from dataclasses import dataclass

import numpy as np

from .narzedzia import ffmpeg_path, ffprobe_path
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TBPM, TKEY, TXXX
from mutagen.wave import WAVE

# ---------------------------------------------------------------- constants

SR = 22050            # analysis sample rate (one decode serves BPM + key)
WINDOW_S = 75.0       # analysis window length

# BPM stage
B_NFFT = 2048
B_HOP = 256           # -> 86.13 envelope frames per second
BPM_MIN, BPM_MAX = 60.0, 200.0
# log-normal tempo prior: the soft "fold octaves toward club tempos" rule.
# A half/double-tempo lobe only wins when its raw comb score beats the
# club-range lobe by more than the prior ratio.
TEMPO_CENTER = 140.0
TEMPO_SIGMA = 0.5     # octaves
AC_UP = 16            # upsampling autokorelacji (gładka interpolacja opóźnień)

# Key stage (tonacja v3, październik 2026 — opis w docstringu _key_from_signal)
K_SR = 11025          # tonacja: osobne dekodowanie CAŁEGO utworu (do K_MAX_S)
K_MAX_S = 480.0       # dłuższe pliki (sety, miksy): środkowe 8 minut (~21 MB próbek)
K_NFFT = 8192         # 0,74 s okna -> 1,35 Hz: półtony rozdzielone już od ~40 Hz
K_HOP = 4096
K_MIDI_MIN = 24       # C1 (32,7 Hz)
K_NUT = 82            # półtony C1..A7 (do ~3,7 kHz)
K_BAS = (28, 52)      # E1-D#3: 41-130 Hz (bas i strojona stopa niosą tonikę)
K_SROD = (52, 96)     # E3-B6: 130-1047 Hz (akordy, pady, wokal)
K_WYBIEL = 18         # wybielanie widma: średnia/odchylenie w oknie +-18 półtonów
K_ALIKW_S = 0.7       # słownik nut: amplituda h-tej harmonicznej = s^(h-1)
K_ALIKW_H = 8         # ...dla h = 1..8
K_NNLS_IT = 30        # iteracje nieujemnej transkrypcji
K_TERCJA_MIN = 0.1    # tercja słabsza niż 10% prymy/kwinty = brak tercji
K_TERCJA_PELNA = 0.5  # tercja >= 50% prymy/kwinty = w pełni wiarygodny świadek trybu
K_MOLL = 0.03         # lekka przewaga mollu przy remisie profili (konwencja klubowa)
K_SKALA_TONIKI = 0.2  # przewaga korelacji 0,2 nad inną toniką = pewność 1
K_SKALA_TRYBU = 0.25  # przewaga mollu/duru 0,25 = pewność 1
K_PEWNOSC_BEZ_TERCJI = 0.3  # tryb umowny: zawsze poniżej progu „sprawdź uchem” (0,4)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles (index 0 = tonic)
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_CAMELOT_MAJOR = {"B": "1B", "F#": "2B", "C#": "3B", "G#": "4B", "D#": "5B",
                  "A#": "6B", "F": "7B", "C": "8B", "G": "9B", "D": "10B",
                  "A": "11B", "E": "12B"}
_CAMELOT_MINOR = {"G#": "1A", "D#": "2A", "A#": "3A", "F": "4A", "C": "5A",
                  "G": "6A", "D": "7A", "A": "8A", "E": "9A", "B": "10A",
                  "F#": "11A", "C#": "12A"}


@dataclass
class TrackAnalysis:
    bpm: float             # one decimal, e.g. 146.0
    key: str               # "A minor"
    camelot: str           # "8A"
    confidence_bpm: float  # 0..1
    confidence_key: float  # 0..1
    key_alt: str = ""      # druga możliwość (Camelot), np. "11B" gdy dur/moll niepewny


# ---------------------------------------------------------------- decoding

def _decode(path: str, sr: int, ss: float, dur: float) -> np.ndarray:
    """Mono float32 PCM via ffmpeg, same pattern as quality/verify_match."""
    out = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", path,
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def _duration(path: str) -> float:
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _stft_mags(x: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    n_frames = (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1))


# ---------------------------------------------------------------- BPM

def _bpm_from_signal(x: np.ndarray) -> tuple[float, float]:
    mags = _stft_mags(x, B_NFFT, B_HOP)
    # spectral flux on log-compressed magnitudes, half-wave rectified
    env = np.maximum(np.diff(np.log1p(1000.0 * mags), axis=0), 0.0).sum(axis=1)
    env = env - env.mean()

    fps = SR / B_HOP
    # autocorrelation via FFT (much faster than np.correlate at ~25k frames),
    # band-limit-upsampled AC_UP razy przez dopełnienie widma mocy zerami:
    # interpolacja liniowa po surowych klatkach ma załamania na całkowitych
    # opóźnieniach i systematycznie znosiła szczyt o 0.3-0.5 BPM (każda
    # wielokrotność taktu ciągnęła do własnego całkowitego opóźnienia)
    n = int(2 ** np.ceil(np.log2(2 * len(env))))
    power = np.abs(np.fft.rfft(env, n)) ** 2
    ac = np.fft.irfft(power, n * AC_UP)[: len(env) * AC_UP] * AC_UP
    ac = ac / (ac[0] + 1e-9)

    # dense tempo grid: integer envelope lags are several BPM apart around
    # club tempos, so fractional-lag interpolation is needed to tell 146
    # from 148
    grid = np.arange(BPM_MIN, BPM_MAX, 0.05)
    lag_idx = np.arange(len(ac), dtype=float)

    def _ac_at(lag_frames: np.ndarray) -> np.ndarray:
        pos = lag_frames * AC_UP
        out = np.zeros_like(np.atleast_1d(pos))
        valid = pos < len(ac) - 1
        out[valid] = np.interp(np.atleast_1d(pos)[valid], lag_idx, ac)
        return out

    scores = np.zeros_like(grid)
    for mult, w in ((1, 1.0), (2, 0.9), (3, 0.4), (4, 0.4)):
        scores += w * _ac_at(60.0 * fps / grid * mult)

    prior = np.exp(-0.5 * (np.log2(grid / TEMPO_CENTER) / TEMPO_SIGMA) ** 2)
    weighted = np.clip(scores, 0.0, None) * prior

    # winning lobe under the prior
    i0 = int(np.argmax(weighted))

    # strażnik oktawy: prior potrafi wciągnąć wolny utwór na podwojone tempo
    # (85 -> ~170), ale wtedy WŁASNY takt zwycięzcy nie ma poparcia
    # w autokorelacji (ac ~ 0), a takt o połowę wolniejszy ma pełne (ac ~ 1);
    # u prawowitych zwycięzców poparcie własnego taktu to >= ~0.7 — zmierzone
    # na metronomach 85-174 i realnej bibliotece, progi z ~3x zapasem
    half = grid[i0] / 2.0
    if half >= BPM_MIN:
        lag = 60.0 * fps / grid[i0]
        if _ac_at(np.array([lag]))[0] < 0.2 and _ac_at(np.array([2 * lag]))[0] > 0.5:
            refuted = grid[i0]
            lobe = np.abs(grid - half) <= 2.0
            i0 = int(np.flatnonzero(lobe)[np.argmax(weighted[lobe])])
        else:
            refuted = None
    else:
        refuted = None

    # raw local peak (+-2 BPM) around the winning lobe
    lo = int(np.searchsorted(grid, grid[i0] - 2.0))
    hi = int(np.searchsorted(grid, grid[i0] + 2.0))
    i = lo + int(np.argmax(scores[lo:hi]))

    # clamped parabolic refinement (offset limited to half a grid step)
    best = float(grid[i])
    if 0 < i < len(grid) - 1:
        a, b, c = scores[i - 1], scores[i], scores[i + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-12:
            best += 0.05 * float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    if abs(best - round(best)) < 0.3:
        best = float(round(best))

    # confidence: margin over the strongest competing lobe (>=3 BPM away);
    # obalone podwojenie nie jest konkurentem — jego takt nie istnieje
    s1 = float(weighted[i0])
    mask = np.abs(grid - grid[i0]) >= 3.0
    if refuted is not None:
        mask &= np.abs(grid - refuted) >= 3.0
    s2 = float(weighted[mask].max()) if mask.any() else 0.0
    conf = 0.0 if s1 <= 0 else float(np.clip(1.0 - s2 / s1, 0.0, 1.0))
    return round(best, 1), round(conf, 2)


# ---------------------------------------------------------------- key

def _strojenie_sygnalu(x: np.ndarray, sr: int) -> float:
    """Odchyłka stroju nagrania od A=440 Hz w półtonach (-0,5..0,5)."""
    n_fft = K_NFFT * max(1, int(round(sr / K_SR)))
    hop = K_HOP * max(1, int(round(sr / K_SR)))
    return _strojenie_z_widma(_ramki_widma(x, n_fft, hop), sr, n_fft)


def _strojenie_z_widma(paczki, sr: int, n_fft: int) -> float:
    """Szczyty widma 100-2000 Hz, częstotliwość doprecyzowana interpolacją
    paraboliczną, odchyłki od siatki półtonów uśrednione kołowo (waga =
    amplituda szczytu). W korpusie (październik 2026) mediana to -7 ct,
    a kilkanaście utworów (bootlegi, stare płyty) jest przestrojonych o
    20-45 ct — przy 45 ct nuty leżą w połowie między półtonami.
    """
    f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    band = np.flatnonzero((f >= 100.0) & (f <= 2000.0))
    lo, hi = int(band[0]), int(band[-1])
    z = 0j
    for mags in paczki:
        mb = mags[:, lo - 1:hi + 2]
        lg = np.log(mb + 1e-9)
        c = lg[:, 1:-1]
        pk = ((c > lg[:, :-2]) & (c > lg[:, 2:])
              & (c > c.max(axis=1, keepdims=True) - np.log(10.0)))
        r, k = np.nonzero(pk)
        a, b, g = lg[r, k], lg[r, k + 1], lg[r, k + 2]
        d = 0.5 * (a - g) / (a - 2 * b + g + 1e-12)
        m = 12.0 * np.log2((lo + k + d) * (sr / n_fft) / 440.0)
        z += np.sum(mb[r, k + 1] * np.exp(2j * np.pi * (m - np.round(m))))
    return float(np.angle(z) / (2 * np.pi)) if abs(z) > 0 else 0.0


def _ramki_widma(x: np.ndarray, n_fft: int, hop: int):
    """Widmo amplitudowe w paczkach klatek (oszczędnie z pamięcią przy
    całych utworach)."""
    win = np.hanning(n_fft).astype(np.float32)
    n = (len(x) - n_fft) // hop
    for a in range(0, max(n, 0), 128):
        b = min(n, a + 128)
        idx = np.arange(n_fft)[None, :] + hop * np.arange(a, b)[:, None]
        yield np.abs(np.fft.rfft(x[idx] * win, axis=1))


_SLOWNIK: np.ndarray | None = None


def _slownik_nut() -> np.ndarray:
    """Wzorce nut (półtony x nuty): harmoniczne h=1..H z amplitudą s^(h-1)."""
    global _SLOWNIK
    if _SLOWNIK is None:
        w = np.zeros((K_NUT, K_NUT))
        for n in range(K_NUT):
            for h in range(1, K_ALIKW_H + 1):
                k = n + int(round(12 * np.log2(h)))
                if k < K_NUT:
                    w[k, n] += K_ALIKW_S ** (h - 1)
        _SLOWNIK = w / np.linalg.norm(w, axis=0, keepdims=True)
    return _SLOWNIK


def _wybiel(y: np.ndarray) -> np.ndarray:
    """Odejmij lokalną średnią widma (+-K_WYBIEL półtonów) i podziel przez
    lokalne odchylenie; ujemne -> 0. Zostają szczyty nut, znika szeroki
    szum perkusji (stopa, werbel, hi-hat, przesterowany bas)."""
    n = y.shape[1]
    c = np.cumsum(np.pad(y, ((0, 0), (1, 0))), axis=1)
    c2 = np.cumsum(np.pad(y * y, ((0, 0), (1, 0))), axis=1)
    lo = np.clip(np.arange(n) - K_WYBIEL, 0, n)
    hi = np.clip(np.arange(n) + K_WYBIEL + 1, 0, n)
    cnt = (hi - lo)[None, :]
    mu = (c[:, hi] - c[:, lo]) / cnt
    var = np.maximum((c2[:, hi] - c2[:, lo]) / cnt - mu * mu, 1e-12)
    return np.maximum(0.0, (y - mu) / np.sqrt(var))


def _chroma_bas_srodek(x: np.ndarray, sr: int = K_SR) -> tuple[np.ndarray, np.ndarray, float]:
    """-> (chroma basu, chroma środka, odchyłka stroju w półtonach).

    1. strojenie nagrania (A != 440 Hz),
    2. widmo -> półtony C1..A7 względem WŁASNEGO stroju utworu,
    3. wybielanie (tłumi perkusję i szum),
    4. nieujemna transkrypcja nut słownikiem z harmonicznymi: alikwoty
       basu (np. 5. harmoniczna = tercja WIELKA nad toniką piłokształtnego
       basu) są przypisane basowi, a nie liczone jako osobne nuty —
       to one wciągały mollowe utwory klubowe w dur,
    5. suma aktywacji nut po całym utworze, osobno bas i środek.
    """
    n_fft = K_NFFT * max(1, int(round(sr / K_SR)))
    hop = K_HOP * max(1, int(round(sr / K_SR)))
    # dwa przebiegi po paczkach klatek zamiast trzymania całego widma
    # w pamięci (oszczędność RAM kosztem ~0,3 s na utwór)
    dev = _strojenie_z_widma(_ramki_widma(x, n_fft, hop), sr, n_fft)
    f = np.fft.rfftfreq(n_fft, 1.0 / sr)
    with np.errstate(divide="ignore"):
        m = 69.0 + 12.0 * np.log2(np.maximum(f, 1e-9) / 440.0) - dev
    s = np.round(m - K_MIDI_MIN).astype(int)
    ok = np.flatnonzero((f > 0) & (s >= 0) & (s < K_NUT))
    mapa = np.zeros((len(ok), K_NUT), np.float32)
    mapa[np.arange(len(ok)), s[ok]] = 1.0
    paczki = [mags[:, ok] @ mapa for mags in _ramki_widma(x, n_fft, hop)]
    if not paczki:
        return np.zeros(12), np.zeros(12), dev
    y = _wybiel(np.concatenate(paczki).astype(np.float64))
    w = _slownik_nut()
    v = y.T
    akt = w.T @ v
    wtv = akt.copy()
    wtw = w.T @ w
    for _ in range(K_NNLS_IT):
        akt *= wtv / (wtw @ akt + 1e-9)
    suma = akt.sum(axis=1)                       # nuty, cały utwór
    midi = K_MIDI_MIN + np.arange(K_NUT)

    def _zloz(lo: int, hi: int) -> np.ndarray:
        c = np.zeros(12)
        sel = (midi >= lo) & (midi < hi)
        np.add.at(c, midi[sel] % 12, suma[sel])
        return c

    return _zloz(*K_BAS), _zloz(*K_SROD), dev


def _chroma_from_signal(x: np.ndarray, sr: int = K_SR) -> np.ndarray:
    """Chroma do profili: bas i środek, każde znormalizowane, ważone po równo."""
    cb, cs, _ = _chroma_bas_srodek(x, sr)
    return cb / (cb.sum() + 1e-12) + cs / (cs.sum() + 1e-12)


def _korelacje(chroma: np.ndarray) -> np.ndarray:
    """Korelacja z profilami Krumhansla: [0]=dur, [1]=moll; [tryb, tonika]."""
    c = (chroma - chroma.mean()) / (chroma.std() + 1e-9)
    r = np.zeros((2, 12))
    for i, prof in enumerate((KS_MAJOR, KS_MINOR)):
        p = (prof - prof.mean()) / prof.std()
        for t in range(12):
            r[i, t] = float(np.dot(c, np.roll(p, t)) / 12)
    return r


def _best_key(chroma: np.ndarray) -> tuple[int, str, float, float]:
    """Return (tonic pitch class, mode, best r, runner-up r) — sam profil,
    bez reguły tercji (pilnowane przez testy korelacji)."""
    r = _korelacje(chroma)
    order = np.argsort(r.ravel())[::-1]
    m, t = divmod(int(order[0]), 12)
    return t, ("major", "minor")[m], float(r.ravel()[order[0]]), float(r.ravel()[order[1]])


def _key_from_signal(x: np.ndarray, sr: int = K_SR) -> tuple[int, str, float, str]:
    """Tonacja z sygnału -> (tonika, tryb, pewność 0..1, alternatywa Camelot).

    Tonika: najlepsza korelacja chromy (bas + środek) z profilami Krumhansla.
    Tryb przy tej tonice:
    * tercja obecna (>= K_TERCJA_MIN prymy/kwinty w środku pasma) — decyduje
      suma dwóch świadków: przewagi profilu mollowego nad durowym (z lekką
      przewagą mollu przy remisie, K_MOLL) i kontrastu tercji małej/wielkiej;
    * tercji brak (bas techno: pryma + kwinta) — tryb jest UMOWNY: moll,
      jak w rekordboxie i Mixed In Key, a pewność spada poniżej progu
      „sprawdź uchem”, z alternatywą = równoległa durowa.
    Pewność = słabsze z dwóch ogniw: przewaga toniki nad najlepszą tonacją
    o innej tonice (pomyłki kwintowe/relatywne) i przewaga trybu (pomyłki
    równoległe). Sprawdzone na korpusie: wśród wyników z pewnością < 0,4
    błędów jest wielokrotnie więcej niż wśród pozostałych.
    """
    cb, cs, _ = _chroma_bas_srodek(x, sr)
    if cb.sum() <= 0 and cs.sum() <= 0:
        return 0, "minor", 0.0, ""
    chroma = cb / (cb.sum() + 1e-12) + cs / (cs.sum() + 1e-12)
    r = _korelacje(chroma)
    m, t = np.unravel_index(int(np.argmax(r)), r.shape)
    t = int(t)
    srod = cs / (cs.max() + 1e-12)
    tercja = max(srod[(t + 3) % 12], srod[(t + 4) % 12])
    oparcie = max(srod[t], srod[(t + 7) % 12], 1e-9)
    dr = r[1, t] - r[0, t] + K_MOLL
    bez_tercji = tercja < K_TERCJA_MIN * oparcie
    if bez_tercji:
        mode = 1
        conf_tryb = K_PEWNOSC_BEZ_TERCJI
    else:
        # dwaj świadkowie trybu (dodatni = moll): przewaga profilu mollowego
        # nad durowym przy tej tonice i kontrast tercji małej/wielkiej
        # w środku pasma, ważony tym, jak wyraźna jest tercja w ogóle
        z = dr / K_SKALA_TRYBU
        m3, M3 = srod[(t + 3) % 12], srod[(t + 4) % 12]
        tc = (m3 - M3) / (m3 + M3 + 1e-12) * min(1.0, tercja / (K_TERCJA_PELNA * oparcie))
        mode = 1 if z + tc >= 0 else 0
        zgodni = z * tc >= 0
        conf_tryb = float(np.clip(max(abs(z), abs(tc)) if zgodni else abs(z + tc), 0.0, 1.0))
    # przewaga toniki: najlepsza tonacja o innej tonice (dowolny tryb)
    inne = np.delete(r, t, axis=1)
    m_ton = r[:, t].max() - inne.max()
    i_inna = np.unravel_index(int(np.argmax(inne)), inne.shape)
    t_inna = int(i_inna[1] + (1 if i_inna[1] >= t else 0))
    conf_ton = float(np.clip(m_ton / K_SKALA_TONIKI, 0.0, 1.0))
    conf = min(conf_ton, conf_tryb)
    mode_s = ("major", "minor")[mode]
    if conf_tryb <= conf_ton:                     # słabsze ogniwo: tryb
        alt = _key_names(t, ("minor", "major")[mode])[2]
    else:                                         # słabsze ogniwo: tonika
        alt = _key_names(t_inna, ("major", "minor")[int(i_inna[0])])[2]
    return t, mode_s, conf, alt


def _key_names(tonic: int, mode: str) -> tuple[str, str, str]:
    """-> ("A minor", "Am", "8A")."""
    note = NOTE_NAMES[tonic]
    if mode == "major":
        return f"{note} major", note, _CAMELOT_MAJOR[note]
    return f"{note} minor", f"{note}m", _CAMELOT_MINOR[note]


def standard_key(ta: TrackAnalysis) -> str:
    """Tag notation for TKEY/INITIALKEY: "Am", "F#m", "C"."""
    note, _, mode = ta.key.partition(" ")
    return f"{note}m" if mode == "minor" else note


# ---------------------------------------------------------------- API

def analyze(path: str) -> TrackAnalysis:
    """Analyze BPM and musical key of one track."""
    length = _duration(path)
    ss = length / 3.0 if length > 0 else 30.0
    dur = WINDOW_S if length <= 0 else min(WINDOW_S, max(20.0, length - ss - 1))
    x = _decode(path, SR, ss, dur)
    if len(x) < SR * 20 and ss > 0:          # short file: retry from the top
        x = _decode(path, SR, 0.0, WINDOW_S)
    if len(x) < SR * 10:
        return TrackAnalysis(0.0, "?", "?", 0.0, 0.0)

    bpm, conf_b = _bpm_from_signal(x)
    # tonacja z CAŁEGO utworu (osobne dekodowanie w niższym próbkowaniu):
    # wstępy z samym basem i stopą też niosą tonikę — na korpusie cały
    # utwór wyraźnie wygrywał z oknem 75 s, z którego liczone jest BPM
    if length > K_MAX_S:
        xk = _decode(path, K_SR, (length - K_MAX_S) / 2.0, K_MAX_S)
    else:
        xk = _decode(path, K_SR, 0.0, max(length, WINDOW_S) + 1.0)
    if len(xk) < K_SR * 5:
        xk = _decode(path, K_SR, 0.0, WINDOW_S)
    tonic, mode, conf_k, alt = _key_from_signal(xk, K_SR)
    key_name, _, camelot = _key_names(tonic, mode)
    return TrackAnalysis(bpm, key_name, camelot, conf_b, round(conf_k, 2), alt)


_KOD_CAMELOT = re.compile(r"^\d{1,2}[AB]$")


def write_tags(path: str, ta: TrackAnalysis) -> None:
    """Write BPM/key tags: standard notation in TKEY/INITIALKEY, Camelot
    in CAMELOT (Vorbis) / TXXX:CAMELOT (ID3).

    Vorbis COMMENT gets the Camelot code only when it is empty or holds
    nothing but a Camelot code from an earlier run — a DJ's own note
    („Kupione na Beatport — zagrać po 2 w nocy”) is never overwritten.
    """
    bpm_s = f"{ta.bpm:g}"
    key_s = standard_key(ta)
    low = path.lower()
    if low.endswith(".flac"):
        audio = FLAC(path)
        audio["BPM"] = bpm_s
        audio["INITIALKEY"] = key_s
        audio["CAMELOT"] = ta.camelot
        stare = [c.strip() for c in (audio.get("COMMENT") or []) if c.strip()]
        if all(_KOD_CAMELOT.match(c) for c in stare):
            audio["COMMENT"] = ta.camelot
        audio.save()
        return
    if low.endswith(".wav"):
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
    tags.delall("TBPM")
    tags.delall("TKEY")
    tags.delall("TXXX:CAMELOT")
    tags.add(TBPM(encoding=3, text=bpm_s))
    tags.add(TKEY(encoding=3, text=key_s))
    tags.add(TXXX(encoding=3, desc="CAMELOT", text=ta.camelot))
    if low.endswith(".wav"):
        audio.save()
    else:
        tags.save(path)


# ---------------------------------------------------------------- set order

def _camelot_distance(c1: str, c2: str) -> float:
    """0 same key, 1 adjacent number same letter / same number other letter."""
    try:
        n1, l1 = int(c1[:-1]), c1[-1]
        n2, l2 = int(c2[:-1]), c2[-1]
    except (ValueError, IndexError):
        return 3.0                     # unknown key: neutral-ish penalty
    d = abs(n1 - n2)
    d = min(d, 12 - d)
    return float(d + (0 if l1 == l2 else 1))


def _bpm_cost(b1: float, b2: float) -> float:
    """Normalized jump: 1.0 at the edge of the +-6 % pitch range, steep beyond."""
    if b1 <= 0 or b2 <= 0:
        return 3.0
    rel = abs(b2 - b1) / ((b1 + b2) / 2.0)
    if rel <= 0.06:
        return rel / 0.06
    return 1.0 + 8.0 * (rel - 0.06) / 0.06


def _pair_cost(a: TrackAnalysis, b: TrackAnalysis) -> float:
    """Koszt przejścia z utworu a do b: harmonia + skok tempa."""
    return _camelot_distance(a.camelot, b.camelot) + _bpm_cost(a.bpm, b.bpm)


def route_cost(seq: list[tuple[str, TrackAnalysis]]) -> float:
    """Łączny koszt całej trasy — suma kosztów kolejnych przejść."""
    return float(sum(_pair_cost(seq[k][1], seq[k + 1][1])
                     for k in range(len(seq) - 1)))


def _two_opt(seq: list[tuple[str, TrackAnalysis]],
             keep_first: bool = True, max_passes: int = 40
             ) -> list[tuple[str, TrackAnalysis]]:
    """Wygładź trasę przez odwracanie odcinków (2-opt) — symetryczny koszt
    `_pair_cost`. Zostaje jako narzędzie pomocnicze (punkt odniesienia);
    `order_set` używa pełniejszej optymalizacji poniżej."""
    n = len(seq)
    if n < 4:
        return seq
    seq = list(seq)
    lo = 1 if keep_first else 0
    for _ in range(max_passes):
        improved = False
        for i in range(lo, n - 1):
            for j in range(i + 1, n):
                before = after = 0.0
                if i > 0:
                    before += _pair_cost(seq[i - 1][1], seq[i][1])
                    after += _pair_cost(seq[i - 1][1], seq[j][1])
                if j < n - 1:
                    before += _pair_cost(seq[j][1], seq[j + 1][1])
                    after += _pair_cost(seq[i][1], seq[j + 1][1])
                if after < before - 1e-9:
                    seq[i:j + 1] = list(reversed(seq[i:j + 1]))
                    improved = True
        if not improved:
            break
    return seq


# Układanie setu — wagi funkcji celu (`_koszt_przejscia` + `_Uklad`).
# Dobrane na secie speeding (51) i „DJ set 100lecie" (22), pomiar:
# selekta-weryfikacja/naprawy/eksport/skrypty/b2_kolejnosc_przed_po.py.
#   zgodne przejście (ta sama tonacja / ±1 na kole / A↔B) prawie darmowe,
#   niezgodne kosztuje tyle, co skok tempa o ~4,5× zakres pitcha,
#   zejście tempem w dół: liniowo, a ponad 3 % stromo (bez 150→129),
#   dwa niezgodne przejścia z rzędu dostają dopłatę — seria „zgrzytów"
#   jest gorsza niż te same zgrzyty rozrzucone; na końcu setu zgrzyt
#   waży więcej; utwór daleko od swojego miejsca w profilu tempa kosztuje.
K_SASIEDNIA = 0.4
K_NIEZGODNA = 4.5
K_KROK_DALEJ = 0.5
K_SPADEK = 2.0
K_SPADEK_DUZY = 20.0
K_SERIA = 8.0
K_PROFIL = 0.5                 # za każdą pozycję poza miejscem w profilu tempa
PROFIL_TEMPA = 0.04            # ±4 % tempa: tyle zgrywa się samym pitchem (CDJ: ±6 %)
K_KONCOWKA = 2.0               # zgrzyt na samym końcu setu waży (1 + K_KONCOWKA)×


def _zgodne_tonacje(c1: str, c2: str) -> bool | None:
    """True/False wg reguł koła Camelota; None, gdy tonacja nieznana."""
    try:
        n1, l1 = int(c1[:-1]), c1[-1]
        n2, l2 = int(c2[:-1]), c2[-1]
    except (ValueError, IndexError, TypeError):
        return None
    d = abs(n1 - n2)
    d = min(d, 12 - d)
    return (l1 == l2 and d <= 1) or (d == 0 and l1 != l2)


def _koszt_przejscia(a: TrackAnalysis, b: TrackAnalysis) -> float:
    """Koszt zagrania b po a: tonacja + tempo + kara za zejście tempem."""
    zg = _zgodne_tonacje(a.camelot, b.camelot)
    if zg is None:
        ton = 2.0
    elif zg:
        ton = 0.0 if a.camelot == b.camelot else K_SASIEDNIA
    else:
        ton = K_NIEZGODNA + K_KROK_DALEJ * max(0.0, _camelot_distance(a.camelot, b.camelot) - 2)
    tempo = _bpm_cost(a.bpm, b.bpm)
    if a.bpm > 0 and b.bpm > 0 and b.bpm < a.bpm:
        rel = (a.bpm - b.bpm) / ((a.bpm + b.bpm) / 2.0)
        # zejście tempem: liniowo, a ponad 3 % (≈ 4–5 BPM) stromo — duże
        # spadki w środku setu (150→129) mają nie wracać
        tempo += K_SPADEK * rel / 0.06 + K_SPADEK_DUZY * max(0.0, rel - 0.03) / 0.03
    return ton + tempo


class _Uklad:
    """Optymalizacja kolejności (indeksy utworów) na pełnej funkcji celu.

    Funkcja celu = koszty przejść (`_koszt_przejscia`: tonacja, tempo,
                   kara za zejście tempem)
                 + K_SERIA za każde niezgodne przejście tuż po niezgodnym
                 + dopłata za niezgodne przejścia w ostatniej ćwiartce setu
                 + K_PROFIL za każdą pozycję, o którą utwór odszedł od
                   swojego miejsca w profilu tempa.

    Miejsce w profilu: pozycje, które w secie posortowanym po BPM zajmują
    utwory w tempie ±PROFIL_TEMPA od tego utworu — w tym zakresie DJ
    zgra je samym pitchem, więc kolejność jest dowolna (tu wygrywa
    tonacja). Sam koszt przejść tego nie pilnował: dużo drobnych zejść
    (155→152→150→147→144→140→138) było z osobna tanich, a razem dawało
    „fale" zamiast narastania, zależnie nawet od kolejności wejścia.
    """

    def __init__(self, tas: list[TrackAnalysis]):
        n = self.n = len(tas)
        self.C = np.array([[_koszt_przejscia(a, b) if i != j else 0.0
                            for j, b in enumerate(tas)] for i, a in enumerate(tas)])
        self.Z = np.array([[_zgodne_tonacje(a.camelot, b.camelot) is False
                            for b in tas] for a in tas], dtype=bool)
        self.Cl, self.Zl = self.C.tolist(), self.Z.tolist()
        znane = sorted(t.bpm for t in tas if t.bpm > 0)
        import bisect
        self.od, self.do = [], []
        for t in tas:
            if t.bpm <= 0 or not znane:          # bez tempa: gdziekolwiek
                self.od.append(-1e9); self.do.append(1e9)
                continue
            self.od.append(bisect.bisect_left(znane, t.bpm * (1 - PROFIL_TEMPA)))
            self.do.append(bisect.bisect_right(znane, t.bpm * (1 + PROFIL_TEMPA)) - 1)
        self._od, self._do = np.array(self.od, dtype=float), np.array(self.do, dtype=float)
        # waga zgrzytu na końcu setu: od 75 % długości rośnie liniowo do
        # 1 + K_KONCOWKA — kulminacja ma iść gładko (przegląd: 5 niezgodnych
        # przejść w ostatnich 6)
        poczatek = 0.75 * (n - 1)
        self.konc = [1.0 + K_KONCOWKA * max(0.0, (k + 1 - poczatek) / max(1.0, (n - 1) - poczatek))
                     for k in range(max(1, n - 1))]
        self._konc = np.array(self.konc)

    def cel(self, seq) -> float:
        s = np.asarray(seq)
        if len(s) < 2:
            return 0.0
        z = self.Z[s[:-1], s[1:]]
        poz = np.arange(len(s))
        odejscie = np.maximum(0.0, np.maximum(self._od[s] - poz, poz - self._do[s]))
        return float(self.C[s[:-1], s[1:]].sum()
                     + K_NIEZGODNA * ((self._konc[:len(z)] - 1.0) * z).sum()
                     + K_SERIA * np.count_nonzero(z[:-1] & z[1:])
                     + K_PROFIL * odejscie.sum())

    def _cel_okna(self, w: list[int], start: int) -> float:
        """Część funkcji celu dla okna w, które zaczyna się na pozycji start."""
        C, Z, od, do, konc = self.Cl, self.Zl, self.od, self.do, self.konc
        tot, zly = 0.0, False
        for k, (a, b) in enumerate(zip(w, w[1:]), start):
            tot += C[a][b]
            z = Z[a][b]
            if z:
                tot += K_NIEZGODNA * (konc[k] - 1.0)
                if zly:
                    tot += K_SERIA
            zly = z
        prof = 0.0
        for k, x in enumerate(w, start):
            if k < od[x]:
                prof += od[x] - k
            elif k > do[x]:
                prof += k - do[x]
        return tot + K_PROFIL * prof

    def dopracuj(self, seq: list[int], okno: int = 10, max_przebiegow: int = 25) -> list[int]:
        """Przenoszenie odcinków 1–3 utworów (także odwróconych) w promieniu
        `okno` pozycji i odwracanie ich w miejscu (pierwszy utwór stoi).
        Różnicę funkcji celu liczymy dokładnie na oknie wokół zmiany — poza
        nim obie kolejności są identyczne, pozycje też."""
        seq = list(seq)
        n = len(seq)
        for _ in range(max_przebiegow):
            poprawa = False
            for L in (1, 2, 3):
                i = 1
                while i + L <= n:
                    e = i + L - 1
                    seg = seq[i:e + 1]
                    odw = seg[::-1]
                    reszta = seq[:i] + seq[e + 1:]
                    najlepsza, ruch = -1e-9, None
                    for q in range(max(1, i - okno), min(len(reszta), i + okno) + 1):
                        if q == i:
                            if L == 1:
                                continue
                            warianty = (odw,)
                        else:
                            warianty = (seg, odw) if L > 1 else (seg,)
                        lo = max(0, min(i, q) - 2)
                        hi = min(n, max(e, q + L - 1) + 3)
                        stary = self._cel_okna(seq[lo:hi], lo)
                        for sg in warianty:
                            okno_nowe = (reszta[lo:min(q, hi)]
                                         + sg[max(0, lo - q):max(0, hi - q)]
                                         + reszta[max(q, lo - L):max(q, hi - L)])
                            d = self._cel_okna(okno_nowe, lo) - stary
                            if d < najlepsza:
                                najlepsza, ruch = d, (q, sg)
                    if ruch is not None:
                        q, sg = ruch
                        seq = reszta[:q] + sg + reszta[q:]
                        poprawa = True
                    i += 1
            if not poprawa:
                break
        return seq


def _ulozenie(tas: list[TrackAnalysis], pierwszy: int) -> list[int]:
    """Kolejność indeksów: rosnące tempo, dopracowanie, kilka kopnięć."""
    import itertools
    import random

    n = len(tas)
    u = _Uklad(tas)
    reszta = [i for i in range(n) if i != pierwszy]
    if n <= 8:                                   # mały set: pełny przegląd
        return min(([pierwszy, *p] for p in itertools.permutations(reszta)), key=u.cel)
    # Stałe ziarno — ekran i eksport zawsze dostają ten sam set; starty nie
    # zależą od kolejności wejścia (remisy rozstrzyga tonacja i tempo).
    rng = random.Random(20261011 + n)

    def start(tasuj: bool) -> list[int]:
        """Rosnące tempo; przy równym BPM zachłannie po tonacji."""
        seq = [pierwszy]
        zostaly = sorted(reszta, key=lambda i: (tas[i].bpm if tas[i].bpm > 0 else 1e9,
                                                tas[i].camelot, i))
        if tasuj:
            rng.shuffle(zostaly)
            zostaly.sort(key=lambda i: tas[i].bpm if tas[i].bpm > 0 else 1e9)
        while zostaly:
            a, prog = seq[-1], tas[zostaly[0]].bpm
            grupa = [j for j, x in enumerate(zostaly) if tas[x].bpm == prog]
            seq.append(zostaly.pop(min(grupa, key=lambda j: (u.Cl[a][zostaly[j]], j))))
        return seq

    best, best_c = None, float("inf")
    for tasuj in ((False, True, True) if n <= 120 else (False,)):
        kand = u.dopracuj(start(tasuj))
        c = u.cel(kand)
        if c < best_c - 1e-9:
            best, best_c = kand, c
    # „kopnięcia": zamiana dwóch sąsiednich odcinków (lokalny podwójny most)
    # i ponowne dopracowanie
    iteracji = 20 if n <= 80 else (6 if n <= 200 else 2)
    for _ in range(iteracji):
        p1 = rng.randint(1, n - 2)
        p2 = min(n - 1, p1 + rng.randint(1, 6))
        p3 = min(n, p2 + rng.randint(1, 6))
        if not p1 < p2 < p3:
            continue
        kand = u.dopracuj(best[:p1] + best[p2:p3] + best[p1:p2] + best[p3:])
        c = u.cel(kand)
        if c < best_c - 1e-9:
            best, best_c = kand, c
    return best


def order_set(
    items: list[tuple[str, TrackAnalysis]],
    optimize: bool = True,
) -> list[tuple[str, TrackAnalysis, str]]:
    """Ułóż utwory do grania: harmonicznie i z narastającym tempem.

    Funkcja celu (`_koszt_przejscia` + dopłata K_SERIA): zgodne przejścia
    na kole Camelota są prawie darmowe, niezgodne drogie, zejście tempem
    w dół droższe niż wejście w górę (set ma narastać — tak podpisuje go
    ekran), a dwa niezgodne przejścia z rzędu dostają dopłatę. Stary
    układ (zachłanny łańcuch + 2-opt na symetrycznym koszcie) zostawiał
    na końcu serię 5 niezgodnych przejść i zjeżdżał w środku 150→129 BPM.

    Start: najniższe BPM (rozgrzewka), dalej rosnące tempo; potem
    dopracowanie na pełnej funkcji celu (`_Uklad`: przejścia, serie
    niezgodnych, profil tempa) i kilka deterministycznych „kopnięć"
    (iterowane przeszukiwanie lokalne). Do 8 utworów — pełny przegląd.

    Każdy wpis niesie adnotację przejścia DO niego, np. „8A->9A, 146->148"
    (pierwszy: „start").
    """
    if not items:
        return []
    kolejnosc = sorted(range(len(items)),
                       key=lambda i: items[i][1].bpm if items[i][1].bpm > 0 else 1e9)
    pierwszy = kolejnosc[0]
    if optimize and len(items) > 2:
        idx = _ulozenie([ta for _n, ta in items], pierwszy)
    else:
        idx = kolejnosc
    chain = [items[i] for i in idx]

    ordered = [(chain[0][0], chain[0][1], "start")]
    for k in range(1, len(chain)):
        prev, cur = chain[k - 1][1], chain[k][1]
        ordered.append((chain[k][0], chain[k][1],
                        f"{prev.camelot}->{cur.camelot}, "
                        f"{prev.bpm:.0f}->{cur.bpm:.0f}"))
    return ordered
