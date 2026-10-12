"""Siatka beatów zakotwiczona w STOPIE, nie w byle jakim onsecie.

Skąd ten moduł. Set „speeding" (51 utworów, 5.09.2026) wrócił z rekordboxa
z siatką „mocno przesuniętą". Kontrola trzema niezależnymi metodami
pokazała, że 23 z 51 siatek leżało dokładnie o PÓŁ BITU obok stopy,
a kolejne kilkanaście o 60–140 ms. Mechanizm: faza siatki była liczona
z widma spektralnego fluxu, a flux liczy każdy ostry transjent tak samo.
W hard techno i hard house najostrzejszym transjentem bywa otwarty hi-hat
na „i" — więc prążek tempa wskazywał hi-haty, nie stopę. Na wzorcach
syntetycznych: stopa + hi-hat głośniejszy od stopy = siatka o pół bitu
obok, w 6 przypadkach na 11.

Zasada: uderzeniem, na którym DJ trzyma siatkę, jest stopa. Stopę poznaje
się po tym, że po transjencie ROŚNIE energia pasma 40–160 Hz. Dlatego:

1. transjenty bierzemy z obwiedni SZEROKOPASMOWEJ (precyzja czasu ~1 ms;
   sama obwiednia basu ma zbyt wolne zbocze i spóźnia się o 60–100 ms),
2. każdy transjent ważymy przyrostem basu tuż po nim (tożsamość stopy),
3. z tak ważonego pociągu impulsów liczymy BPM (prążek widma z zoomem,
   rozdzielczość ~0,003 BPM na 5 minutach) i fazę (średnia kołowa),
4. kotwica = pierwszy MOCNY kick leżący na siatce — nigdy w ciszy intra,
5. jedynkę taktu wskazują skoki energii na granicach sekcji (w górę
   i w dół) i powrót stopy po fillu; rekordbox dostaje ją jako Battito.

Wszystko na numpy + sygnale, który cues.py i tak już zdekodował.

Weryfikacja (27.09.2026, set „speeding"): 101 niezależnych siatek z własnej
analizy rekordboxa (pliki ANLZ) — stara siatka w ≤25 ms od rekordboxa
w 17 przypadkach, ta w 68. Essentia i librosa siadają na hi-hatach tak samo
jak stary flux, więc nie nadają się tu na arbitra.

Bas na „i” głośniejszy od stopy (hard house) — dawniej znana słabość —
rozstrzyga spadek tonu: stopa to ton opadający, basowa nuta trzyma wysokość.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# progi z pomiarów na wzorcach syntetycznych i secie „speeding" (wrzesień 2026)
MIN_TRANSJENTOW = 30       # poniżej nie ma z czego liczyć siatki
MIN_KICKOW_DO_TAKTU = 32   # jedynka taktu wymaga przynajmniej 8 taktów
ZOOM_BPM = 3.0             # szukamy prążka tempa ±3 BPM wokół podpowiedzi
SNAP_BPM = 0.02            # tak blisko liczby całkowitej = producent ustawił całkowitą
SNAP_BPM_NIEPEWNE = 0.06   # przy słabej spójności kicków pomiar jest szerszy — snap też
PROG_PEWNOSCI = 0.25       # poniżej: „sprawdź uchem", siatka może być obok
PROG_TRANSJENTU = 0.01     # minimalne zbocze log-obwiedni na ms, żeby liczyć je za uderzenie


@dataclass
class Siatka:
    bpm: float                  # BPM siatki (dostrojone do stopy)
    first_beat_s: float         # kotwica: pierwszy mocny kick NA siatce
    battito: int = 1            # numer bitu w takcie dla kotwicy (1–4), jak w XML rekordboxa
    pewnosc: float = 0.0        # spójność fazy kicków, 0–1 (1 = wszystkie idealnie na siatce)
    pewnosc_taktu: float = 0.0  # przewaga wybranej jedynki nad drugą kandydatką, 0–1
    kickow: int = 0             # ile mocnych stóp policzono
    opis: str = ""
    # Znaczniki TEMPO dla rekordboxa: [{"t": s, "bpm": x.xx, "battito": 1–4}].
    # Stała siatka = 1 znacznik (albo kilka kotwiczących, gdy samo zaokrąglenie
    # BPM do 0,01 rozjechałoby siatkę pod koniec utworu); tempo zmienne = siatka
    # dynamiczna, znacznik na początku każdego taktu, w którym tempo się zmienia.
    znaczniki: list = field(default_factory=list)
    tryb: str = "stała"         # "stała" | "dynamiczna"
    bpm_dokladne: float | None = None   # z regresji po wszystkich stopach
    odchylka_ms: float | None = None    # najgorsze okno 16 bitów: mediana |stopa − linia|
    flaga: str | None = None    # powód „sprawdź uchem” — siatka może nie trzymać


# ---------------------------------------------------------------- obwiednie

def _szybka_dl(n: int) -> int:
    """Najmniejsza długość ≥ n złożona z 2, 3 i 5 — FFT o długości z dużym
    czynnikiem pierwszym bywa kilkakrotnie wolniejsze (5-minutowy utwór)."""
    best = 1 << (n - 1).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _obwiednia_pasma(x: np.ndarray, sr: int, lo: float, hi: float,
                     wygladz_s: float, krok: int) -> np.ndarray:
    """Obwiednia pasma [lo, hi] Hz co `krok` próbek (~1 ms).

    Filtr robimy w widmie (bez scipy), obwiednię z sygnału analitycznego,
    a potem bierzemy maksimum w każdym koszyku — maksimum, bo chodzi o to,
    KIEDY uderzenie się zaczyna, nie ile ma średnio energii.
    """
    n = _szybka_dl(x.size)                     # dopełnienie zerami: ta sama obwiednia, szybsze FFT
    widmo = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    widmo[(f < lo) | (f > hi)] = 0.0
    analityczny = np.zeros(n, dtype=complex)
    analityczny[:widmo.size] = widmo
    analityczny[1:(n + 1) // 2] *= 2.0
    obw = np.abs(np.fft.ifft(analityczny, n))[:x.size]
    w = max(1, int(sr * wygladz_s))
    if w > 1:
        obw = np.convolve(obw, np.ones(w) / w, mode="same")
    m = (obw.size // krok) * krok
    return obw[:m].reshape(-1, krok).max(axis=1)


def _sygnal_pasma(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    """Sygnał (nie obwiednia) przefiltrowany do [lo, hi] Hz — do liczenia przejść przez zero."""
    n = _szybka_dl(x.size)
    widmo = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    widmo[(f < lo) | (f > hi)] = 0.0
    return np.fft.irfft(widmo, n)[:x.size].astype(np.float32)


def _funkcja_onsetow(e: np.ndarray) -> np.ndarray:
    """Dodatnie zbocza log-obwiedni — ostre tam, gdzie coś uderza."""
    ref = float(np.percentile(e, 60)) + 1e-9
    le = np.log1p(e / ref)
    d = np.maximum(np.diff(le, prepend=le[0]), 0.0)
    return np.convolve(d, np.ones(3) / 3, mode="same")


def _szczyty(d: np.ndarray, fps: float, min_odstep_ms: float = 100.0
             ) -> tuple[np.ndarray, np.ndarray]:
    """Lokalne maksima funkcji onsetów: wyraźne globalnie i wobec otoczenia (4 s)."""
    dodatnie = d[d > 0]
    if dodatnie.size < 10:
        return np.zeros(0), np.zeros(0)
    # Próg względny (12 % najsilniejszych zboczy) ORAZ bezwzględny: prawdziwe
    # uderzenie podnosi log-obwiednię o >0,05 na milisekundę, a szum
    # numeryczny i falowanie obwiedni czystego tonu dają ~1e-6 — bez podłogi
    # ton bez żadnych uderzeń dostawał „siatkę" ze 190 stopami.
    prog = max(0.12 * float(np.percentile(dodatnie, 99.5)), PROG_TRANSJENTU)
    okolica = np.convolve(d, np.ones(4000) / 4000, mode="same")
    kand = np.where((d[1:-1] > d[:-2]) & (d[1:-1] >= d[2:])
                    & (d[1:-1] > prog) & (d[1:-1] > 2.5 * okolica[1:-1]))[0] + 1
    kolejnosc = kand[np.argsort(-d[kand])]
    zajete = np.zeros(d.size, dtype=bool)
    md = int(min_odstep_ms * fps / 1000.0)
    wybrane = []
    for i in kolejnosc:
        lo, hi = max(0, i - md), min(d.size, i + md + 1)
        if not zajete[lo:hi].any():
            wybrane.append(i)
            zajete[i] = True
    idx = np.array(sorted(wybrane), dtype=int)
    return idx / fps, d[idx]


def _transjenty(x: np.ndarray, sr: int, e_szer: np.ndarray | None = None):
    """Transjenty szerokopasmowe + waga „stopowatości" z przyrostu basu po nich."""
    krok = max(1, int(round(sr / 1000.0)))
    fps = sr / krok
    if e_szer is None:
        e_szer = _obwiednia_pasma(x, sr, 20.0, min(10_000.0, sr / 2 - 1), 0.003, krok)
    d_all = _funkcja_onsetow(e_szer)
    e_low = _obwiednia_pasma(x, sr, 40.0, 160.0, 0.005, krok)
    t_on, s_on = _szczyty(d_all, fps)
    if t_on.size == 0:
        return t_on, s_on, np.zeros(0), d_all, e_low, fps
    idx = (t_on * fps).astype(int)
    w_po, w_przed = int(0.10 * fps), int(0.05 * fps)
    po = np.array([e_low[i:i + w_po].max() if i + w_po <= e_low.size else 0.0 for i in idx])
    przed = np.array([np.median(e_low[max(0, i - w_przed):i]) if i > 2 else 0.0 for i in idx])
    ref = float(np.percentile(po, 90)) + 1e-9
    # bas PO transjencie i jego PRZYROST: hi-hat nie ma basu, a sam bas bez
    # transjentu (sustain) nie ma przyrostu — stopa ma obie rzeczy
    waga = np.clip(po / ref, 0.0, 1.5) * np.clip((po - przed) / ref, 0.0, None) ** 0.5
    return t_on, s_on, waga, d_all, e_low, fps


# ---------------------------------------------------------------- tempo i faza

def _bpm_z_autokorelacji(d: np.ndarray, fps: float, lo: float = 60.0, hi: float = 200.0) -> float:
    """Zgrubne tempo pociągu impulsów, gdy nie ma żadnej podpowiedzi."""
    n = int(2 ** np.ceil(np.log2(2 * d.size)))
    moc = np.abs(np.fft.rfft(d - d.mean(), n)) ** 2
    ac = np.fft.irfft(moc, n)[:d.size]
    ac /= ac[0] + 1e-12
    opoznienia = np.arange(int(fps * 60 / hi), int(fps * 60 / lo) + 1)

    def ocena(L: int) -> float:
        s = sum(w * ac[h * L] for h, w in ((1, 1.0), (2, .75), (3, .5), (4, .5)) if h * L < ac.size)
        return s - 0.5 * ac[L // 2]

    oceny = np.array([ocena(int(L)) for L in opoznienia])
    i = int(np.argmax(oceny))
    L = float(opoznienia[i])
    if 0 < i < oceny.size - 1:
        y0, y1, y2 = oceny[i - 1], oceny[i], oceny[i + 1]
        den = y0 - 2 * y1 + y2
        if den != 0:
            L += 0.5 * (y0 - y2) / den
    return 60.0 * fps / L


def _snap(bpm: float, tol: float) -> float:
    """Tempo całkowite albo połówkowe, gdy pomiar leży w `tol` od takiego."""
    if abs(bpm - round(bpm)) < tol:
        return float(round(bpm))
    if abs(bpm * 2 - round(bpm * 2)) < 2 * tol:
        return round(bpm * 2) / 2.0
    return bpm


def _bpm_dostroj(imp: np.ndarray, fps: float, bpm0: float) -> tuple[float, float]:
    """Prążek tempa w widmie pociągu impulsów, ±ZOOM_BPM wokół podpowiedzi.

    Ośmiokrotne dopełnienie zerami plus doprecyzowanie bezpośrednim DFT
    w 81 punktach wokół prążka daje rozdzielczość ~0,003 BPM na 5 minutach.
    Producent prawie zawsze ustawia tempo całkowite (rzadziej połówkowe),
    więc gdy pomiar leży w SNAP_BPM od takiej liczby, bierzemy ją: 128,000
    zamiast 128,004 to mniej rozjazdu w rekordboksie, nie więcej.
    """
    t = np.arange(imp.size) / fps
    n = int(2 ** np.ceil(np.log2(imp.size * 8)))
    widmo = np.fft.rfft(imp - imp.mean(), n)
    f = np.fft.rfftfreq(n, 1.0 / fps)
    sel = (f >= (bpm0 - ZOOM_BPM) / 60.0) & (f <= (bpm0 + ZOOM_BPM) / 60.0)
    if not sel.any():
        return float(bpm0), 0.0
    mag, fs = np.abs(widmo[sel]), f[sel]
    i = int(np.argmax(mag))
    df = fs[1] - fs[0] if fs.size > 1 else 1.0 / imp.size * fps
    kand = fs[i] + np.linspace(-1, 1, 81) * df
    z = np.array([np.sum(imp * np.exp(-2j * np.pi * fc * t)) for fc in kand])
    j = int(np.argmax(np.abs(z)))
    bpm = 60.0 * float(kand[j])
    ostrosc = float(np.abs(z[j]) / (np.median(mag) + 1e-12))
    return _snap(bpm, SNAP_BPM), ostrosc


def _faza(t_on: np.ndarray, waga: np.ndarray, okres: float) -> tuple[float, float]:
    """Faza siatki jako średnia kołowa kicków; spójność = |z|/Σw."""
    z = np.sum(waga * np.exp(2j * np.pi * t_on / okres))
    faza = float((np.angle(z) / (2 * np.pi)) * okres % okres)
    spojnosc = float(abs(z) / (waga.sum() + 1e-12))
    # dostrojenie: jeszcze raz, ale tylko po tych, które już leżą blisko siatki
    r = (t_on - faza) / okres
    odchylka = (r - np.round(r)) * okres
    blisko = np.abs(odchylka) < 0.15 * okres
    if blisko.sum() >= 10:
        z2 = np.sum(waga[blisko] * np.exp(2j * np.pi * t_on[blisko] / okres))
        faza = float((np.angle(z2) / (2 * np.pi)) * okres % okres)
    return faza, spojnosc


# ---------------------------------------------------------------- jedynka taktu

def _jedynka(x: np.ndarray, sr: int, kotwica: float, okres: float,
             e_low: np.ndarray, fps: float, e_szer: np.ndarray | None = None) -> tuple[int, float]:
    """Który z czterech bitów jest jedynką taktu.

    Dowody, każdy jako głos na klasę bitu mod 4: stopień energii — bas, RMS
    i góra — czyli pierwszy bit nowej sekcji, oraz spadek basu/RMS na
    początku przejścia. Głos dostaje premię, gdy leży też na
    granicy frazy (8/16/32 bity): sekcje w muzyce klubowej zaczynają się
    na jedynce frazy, a to najbardziej odporny dowód, jaki mamy bez ucha.
    Zwraca (b, pewnosc): jedynki leżą na liniach o indeksie ≡ b (mod 4).
    """
    czas = x.size / sr
    n_b = int((czas - kotwica) / okres)
    if n_b < MIN_KICKOW_DO_TAKTU:
        return 0, 0.0
    krok = max(1, int(round(sr / 1000.0)))
    e_all = e_szer if e_szer is not None else _obwiednia_pasma(x, sr, 20.0, sr / 2 - 1, 0.003, krok)
    e_hi = _obwiednia_pasma(x, sr, 2000.0, min(9000.0, sr / 2 - 1), 0.003, krok)
    granice = kotwica + np.arange(n_b + 1) * okres
    idx = np.clip((granice * fps).astype(int), 0, e_all.size - 1)

    def seg(e: np.ndarray, i: int) -> np.ndarray:
        return e[idx[i]:max(idx[i] + 1, idx[i + 1])]

    lb = np.log10(np.array([seg(e_low, i).max() for i in range(n_b)]) + 1e-6)
    lr = np.log10(np.array([np.sqrt(np.mean(seg(e_all, i) ** 2)) for i in range(n_b)]) + 1e-6)
    lh = np.log10(np.array([seg(e_hi, i).max() for i in range(n_b)]) + 1e-6)
    # Dowody tylko ze STOPNI energii — sekcja zaczyna się (i kończy) na jedynce.
    # Crash jako osobny dowód psuł wynik: szczyt góry pasma wypada często na
    # „4”, na końcu narastającego risera przed nową frazą (zmierzone na 163
    # siatkach rekordboxa: z crashem 128 zgodnych jedynek, bez 147, ze stopniami
    # w górę i w dół 150).
    dowody: list[tuple[int, float]] = []
    for v, prog in ((lb, 0.25), (lr, 0.2), (lh, 0.3)):
        for n in range(2, n_b - 2):
            skok = v[n] - v[n - 2:n].max()
            trzyma = v[n + 1:n + 3].min() - v[n - 2:n].max()
            if skok >= prog and trzyma >= 0.5 * prog:
                dowody.append((n, min(skok, 0.8)))                     # stopień w górę: nowa sekcja
    for v, prog in ((lb, 0.25), (lr, 0.2)):
        for n in range(2, n_b - 2):
            spad = v[n - 2:n].min() - v[n]
            trzyma = v[n - 2:n].min() - v[n + 1:n + 3].max()
            if spad >= prog and trzyma >= 0.5 * prog:
                dowody.append((n, min(spad, 0.8)))                     # stopień w dół: przejście/breakdown
    if not dowody:
        return 0, 0.0
    glosy = np.zeros(4)
    for n, w in dowody:
        b = n % 4
        glosy[b] += w * (1 + 0.5 * (n % 8 == b) + 0.5 * (n % 16 == b) + 0.5 * (n % 32 == b))
    kol = np.argsort(-glosy)
    pewnosc = float((glosy[kol[0]] - glosy[kol[1]]) / (glosy[kol[0]] + 1e-9))
    return int(kol[0]), pewnosc


# ---------------------------------------------------------------- model siatki przez cały utwór

TOL_OKNA_S = 0.005          # siatka „trzyma”, gdy w każdym oknie mediana |stopa − linia| ≤ 5 ms
OKNO_BITOW = 16             # okno kontroli: 4 takty
ROZJAZD_ZAOKR_S = 0.002     # ile wolno uciec przez zapis BPM z dokładnością 0,01 w XML
LAPANIE = 0.10              # stopa liczy się do bitu, gdy leży w ±10 % okresu od przewidywania
FLAGA_OKNA_S = 0.012        # okno dalej niż tyle od siatki dynamicznej — flaga (2+ takie okna)
UDZIAL_STALEGO = 0.6        # tyle okien musi leżeć na jednej prostej, żeby tempo uznać za stałe


def _regresja(n: np.ndarray, t: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Odporna prosta t = a + b·n (odrzuca odstające: |reszta| > max(3 ms, 4·MAD))."""
    maska = np.ones(n.size, dtype=bool)
    a = b = 0.0
    for _ in range(6):
        if maska.sum() < 2:
            break
        A = np.vstack([np.ones(int(maska.sum())), n[maska]]).T
        (a, b), *_ = np.linalg.lstsq(A, t[maska], rcond=None)
        r = t - (a + b * n)
        mad = float(np.median(np.abs(r[maska] - np.median(r[maska])))) * 1.4826
        nowa = np.abs(r) <= max(0.003, 4.0 * mad)
        if np.array_equal(nowa, maska):
            break
        maska = nowa
    return float(a), float(b), t - (a + b * n)


def _okna_odchylek(n: np.ndarray, reszty: np.ndarray, okno: int = OKNO_BITOW) -> list[tuple[int, float]]:
    """Mediana reszt w oknach po `okno` bitów (z zakładką), tylko okna z ≥ 6 stopami."""
    out = []
    if n.size == 0:
        return out
    for start in range(int(n.min()), int(n.max()) + 1, okno // 2):
        m = (n >= start) & (n < start + okno)
        if m.sum() >= 6:
            out.append((start, float(np.median(reszty[m]))))
    return out


def _sledz_bity(t_kick: np.ndarray, okres: float, faza: float) -> tuple[np.ndarray, np.ndarray]:
    """Przypisz mocnym stopom numery bitów, idąc przez utwór z lokalnym tempem.

    Globalne przypisanie (faza + n·okres) zawodzi, gdy tempo pływa (stare
    nagrania, live) albo BPM jest minimalnie obok — po kilku minutach stopy
    lądują przy sąsiednim bicie. Tu każdy bit przewidujemy z ostatnich
    złapanych stóp, więc tracker idzie za muzyką; po przerwie bez stopy
    (breakdown) szuka jej szerzej, bo tempo mogło się w tym czasie zmienić.
    Zwraca (numery bitów, czasy) samych stóp, które złapały się na bit.
    """
    if t_kick.size < 8:
        return np.zeros(0, int), np.zeros(0)
    t_kick = np.sort(t_kick)
    # start: stopa w najgęstszym miejscu zgodnym z globalną fazą
    r = (t_kick - faza) / okres
    na = np.abs(r - np.round(r)) < LAPANIE
    if not na.any():
        return np.zeros(0, int), np.zeros(0)
    i0 = int(np.flatnonzero(na)[na.sum() // 2])
    n_out, t_out = {0: t_kick[i0]}, None

    def krok(kierunek: int) -> None:
        ostatnie = [(0, t_kick[i0])]
        n, t_prev, przerwa = 0, t_kick[i0], 0
        lokalny = okres
        while True:
            n += kierunek
            przewidywany = t_prev + kierunek * lokalny * (przerwa + 1)
            if przewidywany < -okres or przewidywany > t_kick[-1] + okres:
                break
            zasieg = (LAPANIE if przerwa < 8 else 0.22) * lokalny
            j = int(np.searchsorted(t_kick, przewidywany))
            kand = [k for k in (j - 1, j) if 0 <= k < t_kick.size and abs(t_kick[k] - przewidywany) <= zasieg]
            if not kand:
                przerwa += 1
                continue
            k = min(kand, key=lambda k: abs(t_kick[k] - przewidywany))
            n_out[n] = t_kick[k]
            ostatnie.append((n, t_kick[k]))
            ostatnie = ostatnie[-17:]
            if len(ostatnie) >= 4:                      # lokalne tempo z ostatnich złapanych stóp
                nn = np.array([o[0] for o in ostatnie], float); tt = np.array([o[1] for o in ostatnie])
                lokalny = abs(float(np.polyfit(nn, tt, 1)[0]))
            t_prev, przerwa = t_kick[k], 0

    krok(+1)
    krok(-1)
    nn = np.array(sorted(n_out))
    return nn, np.array([n_out[k] for k in nn])


def _udzial_na_linii(okna: list[tuple[int, float]], tol: float = TOL_OKNA_S) -> float:
    """Jaka część okien 16-bitowych leży na linii (|mediana| ≤ tol)."""
    if not okna:
        return 0.0
    return float(np.mean([abs(v) <= tol for _, v in okna]))


def _model_siatki(n: np.ndarray, t: np.ndarray, dl_s: float) -> dict:
    """Najprostsza siatka, która trzyma się stóp przez cały utwór.

    STAŁE tempo poznajemy po tym, że większość okien 16-bitowych leży na jednej
    prostej (zmierzone: reszty 0,1–0,5 ms), a okna odstające to pojedyncze
    sekcje, po których odchyłka wraca do zera — przefiltrowana stopa w build-upie
    ma późniejszy atak, ale bit muzyczny jest ten sam (Laherte — Speeding:
    4 okna po 20 ms, reszta ≤ 0,6 ms). Utwór grany na żywo albo nagranie
    z taśmy rozjeżdża się NARASTAJĄCO i żadna prosta nie obejmie większości okien.

    Kolejność prób dla stałego tempa: całkowite → połówkowe → 0,01 (z kotwicami,
    gdy samo zaokrąglenie do 0,01 rozjechałoby siatkę) → siatka dynamiczna.
    """
    a, b, reszty = _regresja(n, t)
    bpm_dokl = 60.0 / b
    okna = _okna_odchylek(n, reszty)
    udzial = _udzial_na_linii(okna)
    wynik = dict(bpm_dokladne=round(bpm_dokl, 4))
    n_min, n_max = int(n.min()), int(n.max())

    if udzial >= UDZIAL_STALEGO:                        # tempo stałe
        for kandydat in (round(bpm_dokl), round(bpm_dokl * 2) / 2.0, round(bpm_dokl, 2)):
            okres = 60.0 / kandydat
            r_k = t - n * okres
            a_k = float(np.median(r_k[np.abs(reszty) <= TOL_OKNA_S])) if np.any(np.abs(reszty) <= TOL_OKNA_S) \
                else float(np.median(r_k))              # kotwica z bitów leżących na linii
            o_k = _okna_odchylek(n, t - (a_k + n * okres))
            if _udzial_na_linii(o_k) >= udzial - 0.02:
                return {**wynik, "tryb": "stała", "znaczniki": [(a_k + n_min * okres, float(kandydat), n_min)],
                        "odchylka_ms": round(1000 * float(np.median([abs(v) for _, v in o_k])), 1),
                        "udzial_na_linii": round(_udzial_na_linii(o_k), 2)}
        # zapis z dokładnością 0,01 rozjeżdża się na długim utworze — kotwice co M bitów
        bpm2 = round(bpm_dokl, 2)
        blad_na_bit = abs(60.0 / bpm2 - b)
        co = max(OKNO_BITOW, int(ROZJAZD_ZAOKR_S / blad_na_bit)) if blad_na_bit > 0 else n_max - n_min + 1
        co = max(4, (co // 4) * 4)
        zn = [(a + k * b, float(bpm2), k) for k in range(n_min, n_max + 1, co)]
        return {**wynik, "tryb": "stała", "znaczniki": zn,
                "odchylka_ms": round(1000 * float(np.median([abs(v) for _, v in okna])), 1),
                "udzial_na_linii": round(udzial, 2)}

    # Tempo zmienne: wygładzone tempo (regresja lokalna po ±8 bitach, odporna na
    # pojedyncze stopy obok), znacznik dopiero tam, gdzie poprzedni przestaje
    # trafiać — inaczej siatka szłaby za szumem pomiaru, nie za muzyką.
    pelne = np.arange(n_min, n_max + 1)
    gladkie = np.empty(pelne.size)
    for i, nb in enumerate(pelne):
        m = np.abs(n - nb) <= 8
        gladkie[i] = np.nan
        if m.sum() >= 4 and np.unique(n[m]).size >= 3:   # ≥ 3 różne bity — inaczej prosta nieokreślona
            aa, bb, _ = _regresja(n[m], t[m])
            if 0.2 < bb < 2.0:                           # okres 30–300 BPM; reszta to zdegenerowany fit
                gladkie[i] = aa + bb * nb
    ok = ~np.isnan(gladkie)
    gladkie = np.interp(pelne, pelne[ok], gladkie[ok]) if ok.any() else np.interp(pelne, n, t)
    zn: list[tuple[float, float, int]] = []
    i = 0
    while i < pelne.size - 4:
        dt4 = gladkie[i + 4] - gladkie[i]
        bpm_taktu = round(240.0 / dt4, 2) if dt4 > 0.8 else round(60.0 / b, 2)
        zn.append((float(gladkie[i]), float(bpm_taktu), int(pelne[i])))
        okres = 60.0 / bpm_taktu
        j = i + 4                                       # jak długo ten znacznik trafia?
        while j + 4 < pelne.size and abs(gladkie[i] + (j + 4 - i) * okres - gladkie[j + 4]) <= ROZJAZD_ZAOKR_S * 2:
            j += 4
        i = j
    linie_n = np.array([z[2] for z in zn])
    reszty_d = np.empty(n.size)
    for k, (nk, tk) in enumerate(zip(n, t)):
        j = max(0, int(np.searchsorted(linie_n, nk, side="right")) - 1)
        t0, bpm0, n0 = zn[j]
        reszty_d[k] = tk - (t0 + (nk - n0) * 60.0 / bpm0)
    o_d = _okna_odchylek(n, reszty_d)
    zle = [(st, v) for st, v in o_d if abs(v) > FLAGA_OKNA_S]
    return {**wynik, "tryb": "dynamiczna", "znaczniki": zn,
            "odchylka_ms": round(1000 * float(np.median([abs(v) for _, v in o_d])), 1) if o_d else None,
            "udzial_na_linii": round(_udzial_na_linii(o_d), 2),
            "zle_okno_s": float(np.interp(zle[0][0], n, t)) if len(zle) >= 2 else None}


# ---------------------------------------------------------------- v3: grzebień przez cały utwór

GRZEBIEN_ZAKRES_BPM = 0.15   # wokół prążka tempa — prążek trafia z dokładnością ~0,003–0,05
GRZEBIEN_KROK_BPM = 0.0005   # 0,0005 BPM = ~1 ms rozjazdu na 5 minutach
GRZEBIEN_SIGMA_S = 0.002     # stopa „na linii”, gdy leży w ~2 ms od niej
TOL_INLIER_S = 0.006         # stopa do regresji: ≤ 6 ms od linii
TOL_OKNA_V3_S = 0.008        # okno 16 bitów trzyma siatkę: |mediana| ≤ 8 ms
UDZIAL_OKIEN_STALEJ = 0.7    # tyle okien musi trzymać, żeby jedna stała siatka wystarczyła
TRAFIENIE_OKNA_S = 0.003     # okno „dokładnie na linii”
DRYF_MAX_S = 0.008           # narastający rozjazd okien od początku do końca, który wciąż znaczy „stałe tempo”
MIN_ODCINEK_BITOW = 64       # odcinek ze stałym tempem: co najmniej 16 taktów


def _grzebien(t: np.ndarray, w: np.ndarray, bpm_lo: float, bpm_hi: float,
              krok: float = GRZEBIEN_KROK_BPM, sigma_s: float = GRZEBIEN_SIGMA_S) -> tuple[float, float, float]:
    """Stałe tempo i faza, przy których najwięcej wagi stóp leży NA liniach — w całym utworze naraz.

    Dla każdego kandydata BPM: histogram faz stóp (koszyki 0,5 ms) wygładzony
    jądrem Gaussa ±2 ms (kołowo), wynik = najwyższy szczyt. Prawdziwe tempo
    układa stopy z intra, środka i outra w JEDEN szczyt; tempo o 0,01 obok
    rozmywa go o ~20 ms na 5 minutach. Nie śledzimy bitów po kolei, więc
    breakdown bez stopy niczego nie gubi. Zwraca (bpm, faza [s], wynik).
    """
    kand = np.arange(bpm_lo, bpm_hi + krok / 2, krok)
    calk = np.arange(np.ceil(bpm_lo * 2) / 2, bpm_hi + 1e-9, 0.5)       # całkowite i połówkowe zawsze
    kand = np.unique(np.round(np.concatenate([kand, calk]), 4))
    best = (-1.0, float(kand[0]), 0.0)
    for bpm in kand:
        okres = 60.0 / bpm
        nb = max(8, int(round(okres / 0.0005)))
        idx = ((t % okres) / okres * nb).astype(int) % nb
        h = np.bincount(idx, weights=w, minlength=nb)
        sig = sigma_s / okres * nb
        f = np.fft.rfftfreq(nb)
        hs = np.fft.irfft(np.fft.rfft(h) * np.exp(-2 * (np.pi * f * sig) ** 2), nb)
        j = int(np.argmax(hs))
        if hs[j] > best[0]:
            best = (float(hs[j]), float(bpm), (j + 0.5) / nb * okres)
    return best[1], best[2], best[0]


def _okna_v3(t: np.ndarray, w: np.ndarray, a: float, okres: float, okno: int = OKNO_BITOW):
    """Mediany odchyłek stóp od linii t = a + n·okres w oknach po `okno` bitów (≥ 6 stóp blisko linii)."""
    n = np.round((t - a) / okres)
    r = t - (a + n * okres)
    blisko = np.abs(r) < 0.15 * okres
    out = []
    if not blisko.any():
        return out
    n_b, r_b = n[blisko], r[blisko]
    for start in range(int(n_b.min()), int(n_b.max()) + 1, okno // 2):
        m = (n_b >= start) & (n_b < start + okno)
        if m.sum() >= 6:
            out.append((start, float(np.median(r_b[m]))))
    return out


def _dopasuj_odcinek(t: np.ndarray, w: np.ndarray, bpm_lo: float, bpm_hi: float) -> dict | None:
    """Stała siatka dla jednego odcinka: grzebień → regresja po stopach na liniach → okna."""
    if t.size < 16:
        return None
    if bpm_hi - bpm_lo > 0.4:
        # szeroki zakres: najpierw zgrubnie (krok 0,02, jądro 6 ms), potem dokładnie wokół
        zgr, _f, _w = _grzebien(t, w, bpm_lo, bpm_hi, krok=0.02, sigma_s=0.006)
        bpm_lo, bpm_hi = zgr - 0.06, zgr + 0.06
    bpm, faza, wynik = _grzebien(t, w, bpm_lo, bpm_hi)
    okres = 60.0 / bpm
    n = np.round((t - faza) / okres)
    r = t - (faza + n * okres)
    moc = w >= 0.2 * float(np.percentile(w, 90))
    ok = (np.abs(r) <= TOL_INLIER_S) & moc
    if ok.sum() >= 12 and np.unique(n[ok]).size >= 8:
        a, b, _ = _regresja(n[ok], t[ok])
        if not 0.2 < b < 2.0:
            a, b = faza, okres
    else:
        a, b = faza, okres
    # Tempo całkowite/połówkowe, gdy trzyma stopy PRAWIE tak dobrze jak najlepsze.
    # Dwie grupy stóp (klik w intrze, korpus dalej) przechylają dopasowanie
    # o 0,01 BPM, a to 20 ms rozjazdu na końcu (Lucid: 131,99 → 132,0, wyniki
    # 1,38 vs 1,36). Producent ustawia tempo w DAW — przy remisie wygrywa
    # liczba okrągła; przy wyraźnej przewadze (Dash Berlin 127,99) pomiar.
    bpm_r = 60.0 / b
    for kand in (round(bpm_r), round(bpm_r * 2) / 2.0):
        if abs(kand - bpm_r) <= 0.03 and abs(kand - bpm_r) > 1e-4:
            _b2, f2, w2 = _grzebien(t, w, kand - 1e-6, kand + 1e-6)
            _b3, _f3, w_r = _grzebien(t, w, bpm_r - 1e-6, bpm_r + 1e-6)
            if w2 >= 0.97 * max(w_r, wynik):
                b = 60.0 / kand
                r2 = t - (f2 + np.round((t - f2) / b) * b)
                bliskie = (np.abs(r2) <= TOL_INLIER_S) & moc
                a = f2 + (float(np.median(r2[bliskie])) if bliskie.sum() >= 8 else 0.0)
            break
    okna = _okna_v3(t[moc], w[moc], a, b)
    udzial = float(np.mean([abs(v) <= TOL_OKNA_V3_S for _, v in okna])) if okna else 0.0
    return dict(a=a, okres=b, bpm_dokladne=60.0 / b, okna=okna, udzial=udzial,
                n_min=int(np.round((t.min() - a) / b)), n_max=int(np.round((t.max() - a) / b)))


def _stale_tempo(okna: list[tuple[int, float]]) -> bool:
    """Czy jedna stała siatka opisuje utwór — mimo sekcji z inną stopą.

    Sekcja z innym brzmieniem stopy (klik, filtr, inna próbka) przesuwa okna
    o stałą wartość skokiem i potem wraca — to nie zmiana tempa (Pegassi —
    Flashback: 150,0004 BPM, okna −12 i −32 ms między oknami w 0 ± 2 ms;
    W&W — Heaven: druga połowa z klikiem przed korpusem, okna ±19 ms).
    Zmiana albo falowanie tempa daje NARASTAJĄCY rozjazd: kilka okien z rzędu
    w jedną stronę, krokami podobnej wielkości. Tego szukamy — oraz trendu
    w oknach leżących dokładnie na linii.
    """
    if len(okna) < 4:
        return True
    n = np.array([s for s, _ in okna], float); v = np.array([x for _, x in okna])
    # Poziomy: sekcje z inną stopą to PŁASKOWYŻE na kilku poziomach (0 i +22 ms —
    # G&G — Paper Cuts, Dee Dee — Forever), a przejście między nimi wygląda
    # jak rampa, bo okna zachodzą na siebie. Jeśli najczęstszy poziom (±3 ms)
    # obejmuje ≥ 30 % okien i wraca w pierwszej i ostatniej tercji utworu,
    # tempo jest stałe. Falujące tempo nie ma takiego poziomu (rozmywa się
    # w ciągłość), a zła liczba BPM przesuwa poziom z czasem (trend niżej).
    kosz = np.round(v / 0.003)
    wart, ile = np.unique(kosz, return_counts=True)
    sasiedzi = np.array([ile[np.abs(wart - k) <= 1].sum() for k in wart])
    poziom = wart[int(np.argmax(sasiedzi))]
    na_poziomie = np.abs(kosz - poziom) <= 1
    lo, hi = n.min(), n.max()
    if (na_poziomie.sum() >= 0.3 * len(v)
            and na_poziomie[n <= lo + (hi - lo) / 3].any() and na_poziomie[n >= lo + 2 * (hi - lo) / 3].any()):
        nachylenie = np.polyfit(n[na_poziomie], v[na_poziomie], 1)[0] if np.ptp(n[na_poziomie]) > 0 else 0.0
        if abs(nachylenie) * (hi - lo) <= DRYF_MAX_S:
            return True
    kroki = np.diff(v)
    seria: list[float] = []
    for k in kroki:
        if abs(k) >= 0.0005 and (not seria or np.sign(k) == np.sign(seria[-1])):
            seria.append(float(k))
        else:
            seria = [float(k)] if abs(k) >= 0.0005 else []
        if len(seria) >= 3:
            suma = abs(sum(seria))
            if suma > 0.010 and max(abs(x) for x in seria) <= 0.6 * suma:
                return False                       # narasta krokami — tempo się zmienia
    trafione = np.abs(v) <= TRAFIENIE_OKNA_S
    if trafione.sum() >= 3 and np.ptp(n[trafione]) > 0:
        nachylenie = np.polyfit(n[trafione], v[trafione], 1)[0]
        if abs(nachylenie) * (n.max() - n.min()) > DRYF_MAX_S:
            return False
    return True


ODSTAJE_OKNO_S = 0.015      # okno „obok stóp”
ODSTAJE_SERIA = 6           # tyle okien z rzędu (≈ 12 taktów) obok = sekcja nie trzyma siatki


def _sekcja_obok(okna: list[tuple[int, float]], a: float, okres: float) -> tuple[float, float] | None:
    """(początek, koniec) [s] najdłuższej serii ≥ 6 okien leżących > 15 ms obok siatki (ten sam znak).

    Sklejony edit (Juaan — Carasho: pierwsze 2 minuty 38–51 ms obok reszty)
    albo zmiana tempa, której model nie złapał. Pojedyncza sekcja z filtrowaną
    stopą (Laherte — Speeding: 4 okna po 20 ms) jest krótsza i nie alarmuje.
    """
    najl, start, dl, znak = None, None, 0, 0
    for s, v in okna:
        z = int(np.sign(v)) if abs(v) > ODSTAJE_OKNO_S else 0
        if z and z == znak:
            dl += 1
        else:
            znak, dl, start = z, (1 if z else 0), (s if z else None)
        if dl >= ODSTAJE_SERIA and (najl is None or dl > najl[1]):
            najl = (start, dl)
    if najl is None:
        return None
    return float(a + najl[0] * okres), float(a + (najl[0] + (najl[1] + 1) * OKNO_BITOW // 2) * okres)


def _sekcja_przesunieta(e: np.ndarray, fps: float, linie: np.ndarray, t_od: float, t_do: float) -> bool:
    """Czy w sekcji [t_od, t_do] TEN SAM dźwięk leży przesunięty względem siatki.

    Porównujemy uśredniony kształt bitu (obwiednia 200 Hz–10 kHz, ±60 ms)
    w sekcji i w reszcie utworu. Sklejony edit (Juaan — Carasho) przesuwa
    cały kształt — korelacja ma szczyt przy przesunięciu. Sekcja z inną stopą
    na tej samej siatce (G&G — Paper Cuts, płaskowyż +22 ms samych onsetów)
    ma kształt na miejscu — szczyt przy zerze — i alarm byłby fałszywy.
    """
    h = int(0.06 * fps)
    idx = np.round(np.asarray(linie) * fps).astype(int)
    ok = (idx - 2 * h >= 0) & (idx + 2 * h < e.size)
    w_sekcji = ok & (linie >= t_od) & (linie < t_do)
    poza = ok & ~((linie >= t_od - 4) & (linie < t_do + 4))
    if w_sekcji.sum() < 16 or poza.sum() < 16:
        return True                                  # nie da się porównać — zostaw alarm
    pa = np.mean([e[i - 2 * h:i + 2 * h] for i in idx[w_sekcji]], axis=0)
    pb = np.mean([e[i - h:i + h] for i in idx[poza]], axis=0)
    pb = (pb - pb.mean()) / (pb.std() + 1e-12)
    best_lag, best_c = 0, -1.0
    for lag in range(-h, h + 1):
        seg = pa[h + lag:3 * h + lag]
        seg = (seg - seg.mean()) / (seg.std() + 1e-12)
        c = float(np.mean(seg * pb))
        if c > best_c:
            best_c, best_lag = c, lag
    return best_c > 0.5 and abs(best_lag) / fps > 0.008


def _zapis_bpm(bpm_dokl: float) -> float:
    """BPM do XML-a: całkowite/połówkowe, gdy pomiar leży tuż obok, inaczej 0,01."""
    for kand in (round(bpm_dokl), round(bpm_dokl * 2) / 2.0):
        if abs(bpm_dokl - kand) <= 0.002:
            return float(kand)
    return round(bpm_dokl, 2)


def _znaczniki_odcinka(a: float, okres: float, n_od: int, n_do: int) -> list[tuple[float, float, int]]:
    """Znaczniki TEMPO jednego odcinka stałego tempa; kotwice, gdy zaokrąglenie BPM by uciekło."""
    bpm_z = _zapis_bpm(60.0 / okres)
    blad_na_bit = abs(60.0 / bpm_z - okres)
    co = (n_do - n_od + 1) if blad_na_bit < 1e-9 else max(OKNO_BITOW, int(ROZJAZD_ZAOKR_S / blad_na_bit))
    co = max(4, (co // 4) * 4)
    return [(a + k * okres, float(bpm_z), k) for k in range(n_od, n_do + 1, co)]


def _model_v3(t: np.ndarray, w: np.ndarray, bpm: float, dl_s: float) -> dict | None:
    """Najprostsza siatka, która trzyma stopy przez cały utwór.

    1. Jedna stała siatka z grzebienia (prawie cała muzyka klubowa).
    2. Gdy za mało okien trzyma: kilka odcinków o stałym tempie (zmiana tempa
       w trakcie, np. intro 120 → 128), dzielonych tam, gdzie siatka się
       rozjeżdża — każdy odcinek co najmniej 16 taktów.
    3. Gdy i to nie trzyma (nagranie na żywo, taśma): siatka dynamiczna jak
       wcześniej, ale zawsze z prośbą o sprawdzenie uchem.
    """
    lo, hi = bpm - GRZEBIEN_ZAKRES_BPM, bpm + GRZEBIEN_ZAKRES_BPM
    cala = _dopasuj_odcinek(t, w, lo, hi)
    if cala is None:
        return None
    wynik = dict(bpm_dokladne=round(cala["bpm_dokladne"], 4))
    okna = cala["okna"]
    if _stale_tempo(okna):
        zn = _znaczniki_odcinka(cala["a"], cala["okres"], cala["n_min"], cala["n_max"])
        return {**wynik, "tryb": "stała", "znaczniki": zn, "udzial_na_linii": round(cala["udzial"], 2),
                "odchylka_ms": round(1000 * float(np.median([abs(v) for _, v in okna])), 1) if okna else None,
                "sekcja_obok": _sekcja_obok(okna, cala["a"], cala["okres"])}

    # 2. odcinki stałego tempa: dziel rekurencyjnie tam, gdzie siatka przestaje trzymać
    def podziel(t_od: float, t_do: float, glebokosc: int) -> list[dict] | None:
        m = (t >= t_od) & (t < t_do)
        o = _dopasuj_odcinek(t[m], w[m], bpm * 0.9, bpm * 1.1) if m.sum() >= 32 else None
        if o is None:
            return None
        o.update(t_od=t_od, t_do=t_do)
        if o["udzial"] >= 0.85 or glebokosc >= 3:
            return [o]
        # podział w oknie, gdzie odchyłka zmienia znak trendu najmocniej
        dl_bitu = o["okres"]
        if (t_do - t_od) < 2 * MIN_ODCINEK_BITOW * dl_bitu:
            return [o]
        najl = None
        for frac in np.linspace(0.25, 0.75, 11):
            sr = t_od + frac * (t_do - t_od)
            if sr - t_od < MIN_ODCINEK_BITOW * dl_bitu or t_do - sr < MIN_ODCINEK_BITOW * dl_bitu:
                continue
            ml, mr = (t >= t_od) & (t < sr), (t >= sr) & (t < t_do)
            L = _dopasuj_odcinek(t[ml], w[ml], bpm * 0.9, bpm * 1.1)
            R = _dopasuj_odcinek(t[mr], w[mr], bpm * 0.9, bpm * 1.1)
            if L is None or R is None:
                continue
            ocena = (L["udzial"] * (sr - t_od) + R["udzial"] * (t_do - sr)) / (t_do - t_od)
            if najl is None or ocena > najl[0]:
                najl = (ocena, sr)
        if najl is None or najl[0] < o["udzial"] + 0.15:
            return [o]
        lewa = podziel(t_od, najl[1], glebokosc + 1)
        prawa = podziel(najl[1], t_do, glebokosc + 1)
        return (lewa or []) + (prawa or []) if lewa and prawa else [o]

    odcinki = podziel(float(t.min()) - 1e-3, float(t.max()) + 1e-3, 0) or []
    if len(odcinki) > 1:
        wazony = sum(o["udzial"] * (o["t_do"] - o["t_od"]) for o in odcinki) / sum(o["t_do"] - o["t_od"] for o in odcinki)
        rozne_tempo = max(o["bpm_dokladne"] for o in odcinki) - min(o["bpm_dokladne"] for o in odcinki) > 0.05
        if wazony >= 0.85 and rozne_tempo:
            zn: list[tuple[float, float, int]] = []
            n_bazowy = 0
            for i, o in enumerate(odcinki):
                n_od = int(np.ceil((o["t_od"] - o["a"]) / o["okres"] - 1e-9))
                n_do = int(np.floor((o["t_do"] - o["a"]) / o["okres"]))
                if i == 0:
                    n_od = o["n_min"]
                if i == len(odcinki) - 1:
                    n_do = o["n_max"]
                kawalki = _znaczniki_odcinka(o["a"], o["okres"], n_od, max(n_od, n_do))
                if zn:
                    # numer bitu ciągły przez granicę: ile bitów poprzedniego tempa do startu odcinka
                    t_pop, bpm_pop, n_pop = zn[-1]
                    n_bazowy = n_pop + int(round((kawalki[0][0] - t_pop) / (60.0 / bpm_pop)))
                else:
                    n_bazowy = kawalki[0][2]
                for tz, bz, nz in kawalki:
                    zn.append((tz, bz, n_bazowy + (nz - kawalki[0][2])))
            return {**wynik, "tryb": "odcinki", "znaczniki": zn, "udzial_na_linii": round(wazony, 2),
                    "odchylka_ms": round(1000 * float(np.median([abs(v) for o in odcinki for _, v in o["okna"]])), 1)}

    # 3. ostatnia deska: siatka dynamiczna (dotychczasowy model), zawsze oflagowana
    return None


KLIK_OD_S, KLIK_DO_S = -0.050, -0.008   # gdzie szukać kliku przed linią siatki


def _obwiednia_kliku(x: np.ndarray, sr: int, krok: int) -> np.ndarray:
    """Obwiednia wysokich częstotliwości BEZ echa wstecz: |druga różnica| wygładzona 1 ms.

    Filtr pasmowy w widmie (jak w _obwiednia_pasma) jest nieprzyczynowy —
    ostry atak stopy „dzwoni” w paśmie 2–8 kHz także PRZED sobą i taki
    pogłos wyglądałby jak klik. Druga różnica to filtr 3-próbkowy:
    wzmacnia górę (×1,2 przy 4 kHz, ×0,0008 przy 100 Hz), a w czasie
    nic się nie rozmywa.
    """
    d2 = np.abs(np.diff(x, 2, prepend=[x[0], x[0]]))
    w = max(1, int(sr * 0.001))
    d2 = np.convolve(d2, np.ones(w) / w, mode="same")
    m = (d2.size // krok) * krok
    return d2[:m].reshape(-1, krok).max(axis=1)


def _korekta_kliku(e_hi: np.ndarray, e_all: np.ndarray, fps: float, linie: np.ndarray,
                   e_low: np.ndarray | None = None, e_srod: np.ndarray | None = None) -> tuple[float, bool]:
    """Przesunięcie siatki [s] na POCZĄTEK stopy, gdy ten nie leży na linii; (przesunięcie, pewne?).

    DJ słyszy początek stopy w jej najwcześniejszym ostrym ataku. W hard techno
    stopa bywa złożona: klik (wysokie pasmo) i 20–50 ms później basowy korpus,
    a między stopami gra ciągły bas („rumble”). Szerokopasmowe onsety łapią
    wtedy korpus albo nutę basu — siatka stała 13–57 ms obok (zmierzone na
    233 siatkach rekordboxa: The Nighttrain, Pegassi — 227kg, Eli Brown —
    Wavey, Nicolas Julian — Like This, The Rocketman — Una Hora Más…).

    Na profilu uśrednionym po 64 najgłośniejszych bitach (±¼ bitu, maks. 90 ms)
    szukamy narostów wysokiego pasma; każdy ważymy tym, czy po nim ROŚNIE bas
    (korpus stopy), czy gaśnie (klaps, hi-hat, koniec poprzedniej nuty).
    Przesuwamy, gdy najlepszy kandydat leży > 8 ms od linii, przy linii nie ma
    porównywalnego narostu (< 40 %) i kandydata od linii nie dzieli cisza
    (samotny klaps 76 ms przed stopą — PP DJ Killer — zostaje bez zmian).
    „Pewne” = kandydat wyraźny (siła ≥ 3) i przy linii prawie nic (< 25 %).
    """
    okres = float(np.median(np.diff(linie))) if len(linie) > 2 else 0.5
    h = int(min(0.25 * okres, 0.09) * fps)
    dl = min(e_hi.size, e_all.size, e_low.size if e_low is not None else e_hi.size)
    idx = np.round(np.asarray(linie) * fps).astype(int)
    idx = idx[(idx - h - 25 >= 0) & (idx + h + 65 < dl)]
    if idx.size < 32:
        return 0.0, True
    glosnosc = np.array([e_all[i:i + int(0.05 * fps)].max() for i in idx])
    wyb = idx[np.argsort(-glosnosc)[:64]]
    hf = np.mean([e_hi[i - h - 25:i + h + 66] for i in wyb], axis=0)
    bb = np.mean([e_all[i - h - 25:i + h + 66] for i in wyb], axis=0)
    lo = np.mean([e_low[i - h - 25:i + h + 66] for i in wyb], axis=0) if e_low is not None else None
    sr_ = np.mean([e_srod[i - h - 25:i + h + 66] for i in wyb], axis=0) if e_srod is not None else bb
    w2 = max(1, int(0.002 * fps))
    zero = h + 25                                   # indeks linii w profilu

    def narosty(prof: np.ndarray) -> list[tuple[int, float, float]]:
        """(początek względem linii [klatki], siła, siła × przyrost basu po nim)."""
        ps = np.convolve(prof, np.ones(w2) / w2, mode="same")
        d = np.diff(ps, prepend=ps[0])
        med = float(np.median(prof)) + 1e-12
        out = []
        for i in range(zero - h, zero + h + 1):
            if d[i] > 0 and d[i] >= d[i - 1] and d[i] >= d[i + 1]:
                sila = float((prof[i:i + 9].max() - prof[i - 15:i + 1].min()) / med)
                j = i
                while j > zero - h - 20 and d[j - 1] > 0.3 * d[i]:
                    j -= 1
                bas = 1.0
                if lo is not None:
                    po, przed = lo[j:j + 60].max(), lo[max(0, j - 20):j + 1].mean() + 1e-12
                    bas = float(min(po / przed, 3.0))
                out.append((j - zero, sila, sila * bas))
        return out

    kand = narosty(hf)
    if not kand:
        return 0.0, True
    najl = max(kand, key=lambda k: k[2])
    przes_glosnosci = _korekta_glosnosci(sr_, lo, zero, h, fps)
    # Narost NA linii mierzymy od niej samej: kolejne ząbki tego samego kliku,
    # który zaczął się wcześniej (åmrtüm — dash: klik od −20 ms), nie są
    # osobnym uderzeniem na linii.
    przy = 0.0
    if hf[zero - 15:zero + 1].min() <= hf[zero - 25:zero - 4].min() * 1.3:
        przy = max([k[2] for k in kand if abs(k[0]) <= 4] or [0.0])
    if abs(najl[0]) <= 8 or przy >= 0.4 * najl[2]:
        return przes_glosnosci, True
    if najl[0] < 0 and -najl[0] > 6:
        # klik PRZED linią: między nim a linią nie może być ciszy — inaczej to
        # osobne, wcześniejsze uderzenie (samotny klaps 76 ms przed stopą).
        # Po linii cisza jest normalna: sidechain „oddycha” tuż przed stopą.
        dno = float(bb[zero + najl[0] + 3:zero - 2].min())
        if dno < 0.08 * float(bb[zero - h:zero + h].max()):   # cisza (PP DJ Killer: 2 %), nie dołek (åmrtüm: 15 %)
            return przes_glosnosci, True
    pewne = najl[1] >= 3.0 and przy < 0.25 * najl[2]
    return najl[0] / fps, pewne


def _korekta_glosnosci(bb: np.ndarray, lo: np.ndarray | None, zero: int, h: int, fps: float) -> float:
    """Mała poprawka (≤ 30 ms) na skok CAŁEJ głośności, gdy stopa nie ma kliku.

    Blr, Left 2 Dust — Lights: atak stopy to skok |x| o ~50 % 13 ms przed
    linią, wysokie pasmo w tym miejscu spada; Black Light Smoke — Perfecto:
    skok 10 ms po linii. Profil log-głośności PASMA 200 Hz–10 kHz (bez basu,
    którego zmarszczki ~70 Hz udawały narosty przy linii), wygładzony 4 ms,
    narost = przyrost w 10 ms. Przesuwamy, gdy najsilniejszy narost
    w ±30 ms leży > 8 ms od linii, jest ≥ 0,12 (×1,3) i co najmniej 2× silniejszy
    od narostu przy linii; po nim musi rosnąć bas (to stopa, nie werbel).
    """
    w4 = max(1, int(0.004 * fps))
    lg = np.log10(bb + 1e-3 * (float(bb.max()) + 1e-12))
    lg = np.convolve(lg, np.ones(w4) / w4, mode="same")
    k10 = int(0.010 * fps)
    z30 = int(0.030 * fps)

    def narost(i: int) -> float:
        return float(lg[i + k10 // 2] - lg[i - k10 // 2]) if i - k10 // 2 >= 0 and i + k10 // 2 < lg.size else 0.0

    oceny = [(i - zero, narost(i)) for i in range(zero - z30, zero + z30 + 1)]
    najl = max(oceny, key=lambda o: o[1])
    przy = max(o[1] for o in oceny if abs(o[0]) <= 4)
    if abs(najl[0]) <= 8 or najl[1] < 0.12 or najl[1] < 2 * max(przy, 0.0):
        return 0.0
    # narost musi prowadzić do GŁOŚNEGO miejsca bitu (≥ połowa maksimum pasma):
    # cichy szmer przy syntetycznej stopie bez góry pasma to nie atak
    j = zero + najl[0]
    if lg[min(lg.size - 1, j + k10)] < float(lg.max()) - 0.3:
        return 0.0
    if lo is not None:
        if lo[j:j + 60].max() < 1.15 * (lo[max(0, j - 20):j + 1].mean() + 1e-12):
            return 0.0
    return najl[0] / fps


def _spadek_tonu(x_bas: np.ndarray, sr: int, t: float) -> float:
    """Ile razy częstotliwość dźwięku basowego spada w pierwszych 60 ms po uderzeniu.

    Stopa to ton opadający (ok. 120 → 50 Hz w kilkadziesiąt ms), a basowa nuta
    na „i” trzyma wysokość. Liczymy przejścia przez zero sygnału 30–250 Hz
    tuż po ataku i chwilę później.
    """
    i = int(t * sr)
    a, b = x_bas[i + int(0.002 * sr): i + int(0.022 * sr)], x_bas[i + int(0.035 * sr): i + int(0.075 * sr)]
    if a.size < 10 or b.size < 10:
        return 1.0
    za = np.count_nonzero(np.diff(np.signbit(a))) / a.size
    zb = np.count_nonzero(np.diff(np.signbit(b))) / b.size
    return float((za + 1e-6) / (zb + 1e-6))


def _rozstrzygnij_pol_bitu(t_on, w, x_bas, sr, okres, faza):
    """Faza stóp czy pół bitu obok? Głos wagi basowej sprawdzony spadkiem tonu.

    Zwraca (faza, flaga): flaga, gdy dowody się kłócą — wtedy NIE zgadujemy
    po cichu, tylko prosimy o sprawdzenie uchem.
    """
    # Kandydaci z OBU faz bez progu siły: przy basie na „i” 4× głośniejszym
    # od stopy żadna stopa nie mieści się wśród „mocnych” uderzeń utworu.
    r = (t_on - faza) / okres
    odl = np.abs(r - np.round(r))
    z_basem = w > 0.02 * float(np.percentile(w, 90))
    na_fazie = z_basem & (odl < 0.1)
    na_pol = z_basem & (np.abs(odl - 0.5) < 0.1)
    if na_fazie.sum() < 16 or na_pol.sum() < 16:
        return faza, None                               # brak drugiej kandydatki — nie ma sporu
    def sredni_spadek(maska):
        idx = np.flatnonzero(maska)
        idx = idx[np.argsort(-w[idx])][:120]
        return float(np.median([_spadek_tonu(x_bas, sr, float(t_on[i])) for i in idx]))
    s_faza, s_pol = sredni_spadek(na_fazie), sredni_spadek(na_pol)
    if s_pol > 1.15 * s_faza and s_pol > 1.2:
        return (faza + okres / 2) % okres, None         # stopa jest na „i” obecnej fazy — przesuwamy
    if s_faza < 1.1 and s_pol < 1.1:
        return faza, "nie da się odróżnić stopy od basu na „i” — sprawdź siatkę uchem"
    return faza, None


def jedynki_taktu(znaczniki: list, dl_s: float) -> list[float]:
    """Czasy jedynek taktu (pierwszych bitów) według znaczników TEMPO.

    Znacznik {"t", "bpm", "battito"} zaczyna siatkę od nowa w swoim miejscu;
    ``battito`` to numer bitu w takcie dla bitu leżącego dokładnie w ``t``.
    Przed pierwszym znacznikiem siatka biegnie wstecz z jego tempem — tak
    samo rysuje ją rekordbox.
    """
    import math
    zn = sorted((z for z in znaczniki or [] if z.get("bpm")), key=lambda z: z["t"])
    out: list[float] = []
    for i, z in enumerate(zn):
        okres = 60.0 / float(z["bpm"])
        koniec = zn[i + 1]["t"] - 1e-6 if i + 1 < len(zn) else dl_s + okres
        k = math.ceil(-z["t"] / okres) if i == 0 else 0
        while z["t"] + k * okres < koniec:
            if (int(z.get("battito") or 1) - 1 + k) % 4 == 0:
                out.append(z["t"] + k * okres)
            k += 1
    return out


def do_taktu(t: float | None, jedynki: list[float]) -> float | None:
    """Najbliższa jedynka taktu — punkt cue stawiany obok bitu nie łapie kwantyzacji."""
    if t is None or not jedynki:
        return t
    return min(jedynki, key=lambda j: abs(j - t))


def battito_dla(b: int) -> int:
    """Numer bitu (1–4) kotwicy, gdy jedynki leżą na indeksach ≡ b (mod 4)."""
    return (4 - b) % 4 + 1


# ---------------------------------------------------------------- API

def oszacuj(x: np.ndarray, sr: int, bpm_hint: float | None = None,
            od_s: float = 0.0) -> Siatka | None:
    """Siatka beatów dla zdekodowanego sygnału mono; None, gdy nie ma stóp.

    `bpm_hint` (z harmonic) rozstrzyga oktawę tempa; sam prążek dostraja
    liczbę w ±ZOOM_BPM. Bez podpowiedzi tempo idzie z autokorelacji.
    `od_s` to początek muzyki: kotwica nie wypadnie w ciszy ani w szumie
    przed pierwszym dźwiękiem.
    """
    if x.size < sr * 10:
        return None
    x = np.asarray(x, dtype=np.float64)
    e_szer = _obwiednia_pasma(x, sr, 20.0, min(10_000.0, sr / 2 - 1), 0.003, max(1, int(round(sr / 1000.0))))
    t_on, s_on, waga, d_all, e_low, fps = _transjenty(x, sr, e_szer)
    if t_on.size < MIN_TRANSJENTOW or not np.any(waga > 0):
        return None
    w = s_on * waga
    imp = np.zeros(d_all.size)
    imp[(t_on * fps).astype(int)] = w
    bpm0 = float(bpm_hint) if bpm_hint and bpm_hint > 0 else _bpm_z_autokorelacji(imp, fps)
    bpm, _ostrosc = _bpm_dostroj(imp, fps, bpm0)
    okres = 60.0 / bpm
    faza, spojnosc = _faza(t_on, w, okres)
    # Przy słabej spójności (breakdowny, sekcje z przesuniętą stopą) prążek
    # bywa o kilka setnych obok: 154,96 zamiast 155 — dalej i tak decyduje
    # regresja po stopach z całego utworu, a ta podpowiedź tylko ustawia start.
    if spojnosc < 0.5:
        snap = _snap(bpm, SNAP_BPM_NIEPEWNE)
        if snap != bpm:
            bpm, okres = snap, 60.0 / snap
            faza, spojnosc = _faza(t_on, w, okres)

    # Pół bitu obok? Waga basu bywa oszukana przez głośny bas na „i” —
    # sprawdzamy, czy na wybranej fazie leży opadający ton stopy.
    x_bas = _sygnal_pasma(x, sr, 30.0, 250.0)
    faza, flaga = _rozstrzygnij_pol_bitu(t_on, w, x_bas, sr, okres, faza)
    del x_bas

    # Stopy = mocne uderzenia BLISKO wybranej fazy (próg względem nich samych):
    # gdy bas na „i” jest głośniejszy, najmocniejsze uderzenia utworu to bas.
    r = (t_on - faza) / okres
    blisko = np.abs(r - np.round(r)) < 0.2
    if blisko.sum() >= 16:
        mocne = blisko & (w >= 0.35 * float(np.percentile(w[blisko], 90)))
    else:
        mocne = w >= 0.35 * float(np.percentile(w, 90))
    dl_s = x.size / sr
    # v3: stała siatka z grzebienia po wszystkich stopach naraz (bez śledzenia
    # bit po bicie, które gubiło się w breakdownach i rozjeżdżało siatkę),
    # odcinki stałego tempa przy skokowej zmianie, dynamiczna dopiero na końcu
    model = _model_v3(t_on[mocne], w[mocne], bpm, dl_s) if mocne.sum() >= 16 else None
    if model is None:
        n_b, t_b = _sledz_bity(t_on[mocne], okres, faza)
        if n_b.size >= 16:
            model = _model_siatki(n_b, t_b, dl_s)
            if model["tryb"] == "dynamiczna":
                flaga = flaga or ("tempo zmienia się w trakcie (nagranie na żywo?) — siatka dynamiczna, "
                                  "sprawdź uchem przejścia")
        else:                               # za mało stóp na model — stała siatka z prążka
            model = {"tryb": "stała", "znaczniki": [(faza, round(bpm, 2), 0)], "bpm_dokladne": None,
                     "odchylka_ms": None}
            flaga = flaga or "za mało wyraźnych stóp, żeby sprawdzić siatkę przez cały utwór"
    zn = model["znaczniki"]
    bpm = zn[0][1]; okres = 60.0 / bpm
    # Klik przed korpusem stopy: przesuń CAŁĄ siatkę na klik (patrz _korekta_kliku)
    krok_ms = max(1, int(round(sr / 1000.0)))
    e_hi = _obwiednia_kliku(x, sr, krok_ms)
    e_cale = e_szer
    linie_glowne = zn[0][0] + np.arange(int((dl_s - zn[0][0]) / okres)) * okres
    e_srod = _obwiednia_pasma(x, sr, 200.0, min(10_000.0, sr / 2 - 1), 0.002, krok_ms)
    przes_kliku, pewne = _korekta_kliku(e_hi, e_cale, sr / krok_ms, linie_glowne[linie_glowne > 0],
                                        e_low if e_low.size else None, e_srod)
    del e_srod
    if przes_kliku:
        zn = [(tz + przes_kliku, bz, nz) for tz, bz, nz in zn]
        if not pewne:
            flaga = flaga or ("stopa złożona (klik i korpus osobno) — siatka ustawiona na klik, "
                              "sprawdź uchem, czy trafia")
    del e_hi
    if model.get("sekcja_obok") is not None:
        t_od, t_do = model["sekcja_obok"]
        linie_s = zn[0][0] + np.arange(int((dl_s - zn[0][0]) / okres)) * okres
        e_s = _obwiednia_pasma(x, sr, 200.0, min(10_000.0, sr / 2 - 1), 0.002, krok_ms)
        if _sekcja_przesunieta(e_s, sr / krok_ms, linie_s[linie_s > 0], t_od, t_do):
            model["zle_okno_s"] = t_od
        del e_s
    if model.get("zle_okno_s") is not None:
        m, s_ = divmod(int(max(0.0, model["zle_okno_s"])), 60)
        flaga = flaga or (f"siatka nie trzyma się stóp ok. {m}:{s_:02d} — sprawdź uchem"
                          + ("" if model["tryb"] == "dynamiczna" else " (sklejony edit albo zmiana tempa?)"))

    # Kotwicą jest PIERWSZY słyszalny bit na tej siatce po początku muzyki —
    # także w filtrowanym intrze, gdzie stopa nie ma jeszcze basu (Odymel —
    # Gucci: bity od 9 s, pełna stopa dopiero od 16 s).
    t0, _b0, n0 = zn[0]
    faza0 = t0 % okres
    r = (t_on - faza0) / okres
    na_siatce = np.abs((r - np.round(r)) * okres) < 0.08 * okres
    po_starcie = t_on >= max(0.0, od_s - 0.05)
    slyszalne = s_on >= 0.3 * float(np.median(s_on[na_siatce])) if na_siatce.any() else s_on > 0
    for maska in (na_siatce & po_starcie & slyszalne, na_siatce & mocne):
        if maska.any():
            pierwszy = float(t_on[maska][0])
            break
    else:
        pierwszy = float(t_on[int(np.argmax(w))])
    kotwica = faza0 + np.round((pierwszy - faza0) / okres) * okres
    while kotwica < 0:
        kotwica += okres
    if kotwica > t0 + 1e-6 and len(zn) > 1:
        kotwica = t0                        # siatka dynamiczna zaczyna się od pierwszego znacznika
    n_kotwicy = n0 + int(round((kotwica - t0) / okres))

    b, pewnosc_taktu = _jedynka(x, sr, kotwica, okres, e_low, fps, e_szer)
    battito0 = battito_dla(b)
    znaczniki = []
    for i, (tz, bz, nz) in enumerate(zn):
        tz = kotwica if i == 0 else tz
        nz = n_kotwicy if i == 0 else nz
        znaczniki.append({"t": round(float(tz), 4), "bpm": float(bz),
                          "battito": (battito0 - 1 + (nz - n_kotwicy)) % 4 + 1})
    kickow = int(mocne.sum())
    if spojnosc < PROG_PEWNOSCI and not flaga:
        flaga = "stopa niewyraźna — siatka może leżeć obok, sprawdź uchem"
    opis = (flaga or ("siatka dynamiczna — tempo zmienia się w trakcie, znacznik w każdym takcie"
                      if model["tryb"] == "dynamiczna" else
                      f"tempo zmienia się skokowo — {len(zn)} odcinków stałego tempa"
                      if model["tryb"] == "odcinki" else "siatka na stopie przez cały utwór"))
    return Siatka(bpm=round(float(bpm), 3), first_beat_s=round(float(kotwica), 3),
                  battito=battito0, pewnosc=round(spojnosc, 3),
                  pewnosc_taktu=round(pewnosc_taktu, 2), kickow=kickow, opis=opis,
                  znaczniki=znaczniki, tryb=model["tryb"], bpm_dokladne=model.get("bpm_dokladne"),
                  odchylka_ms=model.get("odchylka_ms"), flaga=flaga)
