"""Energia i struktura utworu — druga połowa układania setu.

Porządkowanie harmoniczne mówi, KTÓRE utwory da się złożyć. Nie mówi,
w jakiej kolejności set ma sens: czy nie zaczynasz od kulminacji, czy
w środku nie ma dziury, i czy w ogóle jest gdzie wejść.

Energia jest liczbą BEZWZGLĘDNĄ 0..1 — porównywalną między utworami.
Wcześniej krzywa była dzielona przez maksimum tego samego utworu, więc
mierzyła płaskość obwiedni, nie energię: pad bez rytmu dostawał 1,0
(najwięcej w secie), utwór 25 dB cichszy — tyle samo co głośny, a łuk setu
ogłaszał kulminację na spokojnym otwieraczu (przegląd 0.4.2).

Składniki, każdy na stałej skali (te same progi dla każdego utworu):

* **głośność** — K-ważona głośność jak w EBU R128 (LUFS), liczona z tego
  samego widma co reszta; −30 LUFS → 0, −4 LUFS → 1;
* **uderzenia** — wyraźne onsety na sekundę, tylko gdy jest puls (bramka
  okresowości); 0/s → 0, 8/s → 1 — tempo i gęstość perkusji naraz;
* **tempo** — 80 BPM → 0, 160 BPM → 1;
* **bas** — udział pasma < 150 Hz w mocy; 0 → 0, 0,9 → 1;
* **jasność** — centroida widma; 0,8 kHz → 0, 2,5 kHz → 1.

Wagi: głośność 0,35, uderzenia 0,25, tempo 0,20, bas 0,10, jasność 0,10.
Krzywa w czasie to ta sama formuła w oknach, więc breakdown widać jako
spadek, a cichy utwór leży nisko na całej długości. „Energia utworu”
(pole ``srednia``) to 70. percentyl krzywej — poziom głównej części, na
który nie wpływa długość intra i outra w wersjach extended.

Granice fraz liczymy od kotwicy beatgridu. Ma to sens dopiero od chwili,
gdy kotwica naprawdę stoi na uderzeniu — dlatego serwer przelicza je przy
każdym odczycie z aktualnej (także ręcznie poprawionej) siatki.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .cues import FPS, SR, _decode, _envelopes, _stft_mags, HOP, N_FFT

TAKT = 4                      # uderzenia w takcie (4/4)
FRAZA_TAKTOW = 16             # typowa fraza w muzyce klubowej

# wagi i skale składników energii (patrz opis modułu)
WAGI = {"glosnosc": 0.35, "uderzenia": 0.25, "tempo": 0.20, "bas": 0.10, "jasnosc": 0.10}
# Skale z zakresów fizycznych, nie dopasowane do zestawu:
# * głośność od prawie ciszy (−30 LUFS: ambient, ciche intro) do
#   najgłośniejszych masterów (−4 LUFS) — twarda podłoga wyżej (−20)
#   zrównywała dwa ciche utwory różniące się o 25 dB;
# * udział basu od 0 (pad) do ~0,9 (sama stopa i bas);
# * tempo muzyki tanecznej 80–160 BPM.
# Przy węższych skalach (−24…−6 LUFS, bas do 0,6) cała muzyka klubowa
# wpadała w nasycenie i set techno wychodził „płaski”.
SKALE = {"glosnosc": (-30.0, -4.0), "uderzenia": (0.0, 8.0), "tempo": (80.0, 160.0),
         "bas": (0.0, 0.9), "jasnosc": (0.8, 2.5)}
PERCENTYL_UTWORU = 70
BREAKDOWN_DB = 6.0            # o tyle ciszej od głównej części = breakdown
BAS_HZ = 150.0
OKNO_S = 3.0                  # okno krzywej energii (s), niezależne od liczby punktów
KALIBRACJA_LUFS = 1.26       # mono 11 kHz → stereo R128 (patrz _glosnosc_blokow)
FLUX_MIN = 100.0              # najsłabsze „uderzenie” przy sygnale sprowadzonym do RMS 0,1
SPADEK_BREAKDOWN = 0.12       # o tyle niższa energia okna niż główna część = breakdown
PROG_FAZ = (0.45, 0.68)       # < rozgrzewka, >= kulminacja


@dataclass
class Struktura:
    """Co wiemy o kształcie utworu."""
    krzywa: list[float] = field(default_factory=list)   # energia 0..1 w czasie (bezwzględna)
    czas_s: float = 0.0
    srednia: float = 0.0                # energia utworu 0..1 — porównywalna między utworami
    szczyt_s: float | None = None       # gdzie utwór jest najmocniejszy
    jasnosc: float = 0.0                # centroida widma w kHz
    gestosc_perkusji: float = 0.0       # uderzeń na takt
    breakdown_s: float = 0.0            # łączna długość fragmentów wyraźnie cichszych od głównej części
    intro_typ: str = ""                 # "perkusyjne" | "miękkie" | "od razu"
    faza: str = ""                      # "rozgrzewka" | "środek" | "kulminacja"
    frazy: list[float] = field(default_factory=list)     # granice fraz [s]
    glosnosc_lufs: float | None = None  # K-ważona głośność głównej części (≈ LUFS)
    uderzenia_na_s: float = 0.0         # wyraźne onsety na sekundę (0 bez pulsu)
    udzial_basu: float = 0.0            # udział pasma < 150 Hz w mocy
    skladniki: dict = field(default_factory=dict)        # składniki 0..1 (do wyjaśnień w UI)


# ---------------------------------------------------------------- pomiary

def _k_waga(czest: np.ndarray) -> np.ndarray:
    """|H|² filtra K z ITU-R BS.1770 (półka +4 dB i górnoprzepustowy 38 Hz).

    Norma podaje współczynniki dla 48 kHz; liczymy ich charakterystykę
    w częstotliwościach naszego widma (do 5,5 kHz — tam filtr jest ten sam).
    """
    w = 2 * np.pi * czest / 48000.0
    z = np.exp(-1j * w)

    def h(b, a):
        return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)

    polka = h([1.53512485958697, -2.69169618940638, 1.19839281085285],
              [1.0, -1.69065929318241, 0.73248077421585])
    gorny = h([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
    return np.abs(polka * gorny) ** 2


def _glosnosc_blokow(ms_klatek: np.ndarray) -> np.ndarray:
    """Głośność bloków 400 ms (co 100 ms) z kwadratów średnich klatek [LUFS]."""
    n = max(1, int(round(0.4 * FPS)))
    if ms_klatek.size < n:
        return np.array([-0.691 + 10 * np.log10(ms_klatek.mean() + 1e-12)])
    sk = np.cumsum(np.concatenate([[0.0], ms_klatek]))
    krok = max(1, int(round(0.1 * FPS)))
    starty = np.arange(0, ms_klatek.size - n + 1, krok)
    ms = (sk[starty + n] - sk[starty]) / n
    # Liczymy z sumy mono (L+R)/2 przy 11 kHz, a R128 sumuje moc obu kanałów
    # w pełnym paśmie. Poprawka +1,26 dB skalibrowana względem ffmpeg
    # loudnorm na 6 utworach (techno, pop, rock): różnice po niej ±0,4 dB.
    return -0.691 + 10 * np.log10(ms + 1e-12) + KALIBRACJA_LUFS


def _zintegrowana(bloki: np.ndarray) -> float:
    """Bramkowanie jak w BS.1770: −70 LUFS i −10 LU od średniej."""
    b = bloki[bloki > -70.0]
    if b.size == 0:
        return -70.0
    srednia = 10 * np.log10(np.mean(10 ** (b / 10)))
    b = b[b > srednia - 10.0]
    return float(10 * np.log10(np.mean(10 ** (b / 10)))) if b.size else -70.0


def _okresowosc(flux: np.ndarray, bpm: float | None) -> bool:
    """Czy onsety tworzą puls przy opóźnieniu bitu.

    Zmierzone (autokorelacja fluxu przy 60/bpm): pad bez perkusji -0.56,
    wszystko z perkusją — także ciche i zmiksowane z melodią — od +0.27
    (Flashback) do +0.88.
    """
    if flux.size < 8 or not bpm:
        return False
    f = flux - flux.mean()
    lag = 60.0 / bpm * FPS
    n = int(2 ** np.ceil(np.log2(2 * len(f))))
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, n)) ** 2)[: len(f)]
    ac = ac / (ac[0] + 1e-12)
    return lag < len(ac) - 1 and np.interp(lag, np.arange(len(ac)), ac) >= 0.1


def _onsety(flux: np.ndarray) -> np.ndarray:
    """Maska klatek, w których zaczyna się wyraźne uderzenie.

    Próg na MAD (nie na odchyleniu standardowym, bo std zawyżają same
    kopnięcia), k=3 z pomiarów na realnej bibliotece. Zbocze narastające
    to jedno uderzenie; zbocza bliżej niż 90 ms to to samo uderzenie
    rozmazane na dwie klatki (bez tego bit 8/takt liczył się jako ~10).
    """
    if flux.size < 2:
        return np.zeros(flux.size, dtype=bool)
    med = float(np.median(flux))
    mad = float(np.median(np.abs(flux - med)))
    # Dolny próg bezwzględny (flux z sygnału sprowadzonego do RMS 0,1):
    # migotanie stacjonarnego padu sięga ~20, prawdziwe uderzenia w muzyce
    # 300–800 (zmierzone na 7 utworach od ballady po techno). Bez niego
    # pad bez rytmu dostawał 3 „uderzenia” na sekundę.
    prog = max(med + 3.0 * mad, FLUX_MIN)
    zbocza = np.zeros(flux.size, dtype=bool)
    zbocza[1:] = (flux[1:] > prog) & (flux[:-1] <= prog)
    idx = np.flatnonzero(zbocza)
    if idx.size > 1:
        min_odstep = max(1, int(round(0.09 * FPS)))
        zostaw = np.concatenate([[True], np.diff(idx) >= min_odstep])
        zbocza[:] = False
        zbocza[idx[zostaw]] = True
    return zbocza


def _gestosc(flux: np.ndarray, bpm: float | None) -> float:
    """Ile wyraźnych uderzeń przypada na takt (0, gdy nie ma pulsu)."""
    if flux.size < 8 or not bpm or not _okresowosc(flux, bpm):
        return 0.0
    zbocza = int(_onsety(flux).sum())
    taktow = (flux.size / FPS) / (TAKT * 60.0 / bpm)
    return round(zbocza / taktow, 2) if taktow > 0 else 0.0


def _jasnosc_khz(x: np.ndarray) -> float:
    """Centroida widma — środek ciężkości energii w paśmie."""
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


def _skala(nazwa: str, v: float) -> float:
    lo, hi = SKALE[nazwa]
    return float(np.clip((v - lo) / (hi - lo), 0.0, 1.0))


def energia_z_cech(glosnosc: float, uderzenia: float, bpm: float | None,
                   bas: float, jasnosc: float) -> tuple[float, dict]:
    """Energia 0..1 ze składników na stałych skalach (+ same składniki).

    Tempo liczy się tylko tam, gdzie słychać puls: bez uderzeń (pad,
    breakdown) BPM z tagu nie dodaje energii — rośnie razem z nimi do
    1 uderzenia na sekundę.
    """
    puls = min(1.0, max(0.0, uderzenia) / 1.0)
    sk = {"glosnosc": _skala("glosnosc", glosnosc),
          "uderzenia": _skala("uderzenia", uderzenia),
          "tempo": _skala("tempo", bpm or 0.0) * puls,
          "bas": _skala("bas", bas),
          "jasnosc": _skala("jasnosc", jasnosc)}
    return float(sum(WAGI[k] * v for k, v in sk.items())), sk


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


# ---------------------------------------------------------------- analiza

def analizuj(path: str, bpm: float | None = None,
             kotwica: float = 0.0, punkty: int = 240) -> Struktura:
    """Policz kształt utworu: energię (bezwzględną), jasność, gęstość i frazy."""
    return analizuj_sygnal(_decode(path), bpm=bpm, kotwica=kotwica, punkty=punkty)


def analizuj_sygnal(x: np.ndarray, bpm: float | None = None,
                    kotwica: float = 0.0, punkty: int = 240) -> Struktura:
    """Jak ``analizuj``, ale na zdekodowanym sygnale mono 11 025 Hz."""
    if x.size == 0:
        return Struktura()
    czas = x.size / SR
    mags = _stft_mags(x, N_FFT, HOP)
    if mags.shape[0] < 4:
        return Struktura(czas_s=round(czas, 2))
    czest = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    moc = mags ** 2
    okno = np.hanning(N_FFT)
    # Parseval: średni kwadrat sygnału w klatce z widma (prążki 1..N/2-1 liczą się podwójnie)
    podwoj = np.full(czest.size, 2.0)
    podwoj[0] = podwoj[-1] = 1.0
    norma = 1.0 / (N_FFT * np.sum(okno ** 2))
    ms_k = (moc * (_k_waga(czest) * podwoj)).sum(axis=1) * norma
    ms = (moc * podwoj).sum(axis=1) * norma
    bas_k = (moc[:, czest <= BAS_HZ] * podwoj[czest <= BAS_HZ]).sum(axis=1) * norma
    centroid = (mags * czest).sum(axis=1) / (mags.sum(axis=1) + 1e-12) / 1000.0

    # onsety: z sygnału sprowadzonego do stałego poziomu, żeby liczba
    # uderzeń nie zależała od głośności (za nią odpowiada osobny składnik)
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) or 1.0
    _, _, flux = _envelopes((x / rms * 0.1).astype(np.float32))
    puls = _okresowosc(flux, bpm)
    onsety = _onsety(flux) if puls else np.zeros(flux.size, dtype=bool)

    n = ms.size
    na_okno = max(4, int(round(OKNO_S * FPS)))
    starty = np.arange(0, n, max(1, na_okno // 2))
    e_okien, l_okien, czasy = [], [], []
    for s in starty:
        sl = slice(s, min(n, s + na_okno))
        if sl.stop - sl.start < 4:
            continue
        l_w = _zintegrowana(_glosnosc_blokow(ms_k[sl]))
        aktywne = ms[sl] > 1e-9
        bas_w = float(bas_k[sl].sum() / (ms[sl].sum() + 1e-12))
        cen_w = float(np.median(centroid[sl][aktywne])) if aktywne.any() else 0.0
        ud_w = float(onsety[sl].sum()) / ((sl.stop - sl.start) / FPS)
        e_w, _ = energia_z_cech(l_w, ud_w, bpm, bas_w, cen_w)
        e_okien.append(e_w)
        l_okien.append(l_w)
        czasy.append((sl.start + (sl.stop - sl.start) / 2) / FPS)
    e_okien = np.array(e_okien)
    l_okien = np.array(l_okien)
    czasy = np.array(czasy)

    # energia utworu: poziom głównej części, z cech całego utworu w jej oknach
    prog_glownej = np.percentile(e_okien, PERCENTYL_UTWORU)
    glowna_okna = e_okien >= np.percentile(e_okien, 40)
    glosnosc = _zintegrowana(_glosnosc_blokow(ms_k))
    aktywne = ms > 1e-9
    udzial_basu = float(bas_k[aktywne].sum() / (ms[aktywne].sum() + 1e-12)) if aktywne.any() else 0.0
    jasnosc = _jasnosc_khz(x)
    uderzenia = float(onsety.sum()) / (n / FPS)
    _, skladniki = energia_z_cech(glosnosc, uderzenia, bpm, udzial_basu, jasnosc)

    # breakdown: fragmenty wyraźnie słabsze od głównej części utworu —
    # ciszej o 6 dB ALBO bez bitu (energia niższa o 0,12). Sama głośność
    # nie wystarcza: filtr K tłumi stopę i bas, więc breakdown z samym padem
    # bywa w LUFS prawie tak głośny jak pełny refren (przegląd 0.4.2:
    # 24 s breakdownu w 60 s utworze dawało breakdown_s = 0).
    glowna_db = float(np.median(l_okien[glowna_okna])) if glowna_okna.any() else float(np.max(l_okien))
    krok_s = (starty[1] - starty[0]) / FPS if len(starty) > 1 else czas
    cisza = (l_okien < glowna_db - BREAKDOWN_DB) | (e_okien < prog_glownej - SPADEK_BREAKDOWN)
    breakdown = float(cisza.sum()) * krok_s
    breakdown = min(breakdown, czas)

    # krzywa w stałej liczbie punktów (interpolacja energii okien)
    punkty = max(16, min(punkty, 1000))
    t_pkt = (np.arange(punkty) + 0.5) / punkty * czas
    krzywa = np.interp(t_pkt, czasy, e_okien)

    s = Struktura(
        krzywa=[round(float(v), 3) for v in krzywa],
        czas_s=round(czas, 2),
        srednia=round(float(prog_glownej), 3),
        szczyt_s=round(float(czasy[int(np.argmax(e_okien))]), 1),
        jasnosc=round(jasnosc, 2),
        gestosc_perkusji=_gestosc(flux, bpm),
        breakdown_s=round(breakdown, 1),
        frazy=granice_fraz(czas, bpm, kotwica),
        glosnosc_lufs=round(glosnosc, 1),
        uderzenia_na_s=round(uderzenia, 2),
        udzial_basu=round(udzial_basu, 3),
        skladniki={k: round(v, 3) for k, v in skladniki.items()},
    )
    s.intro_typ = _intro(e_okien, czasy, onsety, s.srednia, czas)
    s.faza = _faza(s)
    return s


def _intro(e_okien: np.ndarray, czasy: np.ndarray, onsety: np.ndarray,
           srednia: float, czas: float) -> str:
    """Czy da się w to wejść bez czekania.

    „perkusyjne” to intro z wyraźnymi uderzeniami — najwygodniejsze do
    miksu; „miękkie” — bez rytmu (pad, wokal); „od razu” — utwór startuje
    pełną energią i wejście trzeba ustawić w konkretnym punkcie.
    """
    if e_okien.size < 2:
        return ""
    dl_intra = min(30.0, czas / 6)
    w_intro = czasy <= max(dl_intra, czasy[0])
    if float(e_okien[w_intro].mean()) >= 0.92 * srednia:
        return "od razu"
    klatki = max(1, int(dl_intra * FPS))
    na_s = float(onsety[:klatki].sum()) / (klatki / FPS)
    return "perkusyjne" if na_s >= 1.0 else "miękkie"


def _faza(s: Struktura) -> str:
    """Gdzie w secie ten utwór ma sens — z bezwzględnej energii.

    Długi breakdown (ponad 1/4 utworu) obniża o jeden poziom: głośny,
    ale w dużej części pusty kawałek to nie szczyt setu.
    """
    poziom = 0 if s.srednia < PROG_FAZ[0] else (2 if s.srednia >= PROG_FAZ[1] else 1)
    if s.czas_s and s.breakdown_s > s.czas_s * 0.25:
        poziom = max(0, poziom - 1)
    return ("rozgrzewka", "środek", "kulminacja")[poziom]


# --------------------------------------------------------------------------
# poziom setu
# --------------------------------------------------------------------------

def luk_setu(utwory: list[dict]) -> dict:
    """Oceń łuk energii całego setu w podanej kolejności.

    Szukamy dwóch rzeczy, które psują set mimo poprawnego doboru tonacji:
    dziury (nagły spadek w środku) i przedwczesnej kulminacji. Energie są
    bezwzględne, więc porównanie sąsiadów ma sens.
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
