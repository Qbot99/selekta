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
5. jedynkę taktu wskazują crashe, skoki energii na granicach sekcji
   i powrót stopy po fillu; rekordbox dostaje ją jako Battito.

Wszystko na numpy + sygnale, który cues.py i tak już zdekodował.

Weryfikacja (27.09.2026, set „speeding"): 101 niezależnych siatek z własnej
analizy rekordboxa (pliki ANLZ) — stara siatka w ≤25 ms od rekordboxa
w 17 przypadkach, ta w 68. Essentia i librosa siadają na hi-hatach tak samo
jak stary flux, więc nie nadają się tu na arbitra.

ZNANA SŁABOŚĆ: tonalny bas na „i" głośniejszy od stopy co najmniej dwa
razy (wzorzec syntetyczny L w tests/test_siatka.py) przeciąga siatkę na
siebie — waga basowa nie odróżnia stopy od twardo zaatakowanego basu.
Realny przykład z donkiem na „i" (Pegassi — MOAA) wyszedł dobrze, ale
przy takim materiale sprawdź siatkę uchem.
"""
from __future__ import annotations

from dataclasses import dataclass

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


# ---------------------------------------------------------------- obwiednie

def _obwiednia_pasma(x: np.ndarray, sr: int, lo: float, hi: float,
                     wygladz_s: float, krok: int) -> np.ndarray:
    """Obwiednia pasma [lo, hi] Hz co `krok` próbek (~1 ms).

    Filtr robimy w widmie (bez scipy), obwiednię z sygnału analitycznego,
    a potem bierzemy maksimum w każdym koszyku — maksimum, bo chodzi o to,
    KIEDY uderzenie się zaczyna, nie ile ma średnio energii.
    """
    n = x.size
    widmo = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    widmo[(f < lo) | (f > hi)] = 0.0
    analityczny = np.zeros(n, dtype=complex)
    analityczny[:widmo.size] = widmo
    analityczny[1:(n + 1) // 2] *= 2.0
    obw = np.abs(np.fft.ifft(analityczny, n))
    w = max(1, int(sr * wygladz_s))
    if w > 1:
        obw = np.convolve(obw, np.ones(w) / w, mode="same")
    m = (obw.size // krok) * krok
    return obw[:m].reshape(-1, krok).max(axis=1)


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


def _transjenty(x: np.ndarray, sr: int):
    """Transjenty szerokopasmowe + waga „stopowatości" z przyrostu basu po nich."""
    krok = max(1, int(round(sr / 1000.0)))
    fps = sr / krok
    d_all = _funkcja_onsetow(_obwiednia_pasma(x, sr, 20.0, min(10_000.0, sr / 2 - 1), 0.003, krok))
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
             e_low: np.ndarray, fps: float) -> tuple[int, float]:
    """Który z czterech bitów jest jedynką taktu.

    Dowody, każdy jako głos na klasę bitu mod 4: crash (skok góry pasma
    wyróżniający się nad ±8 bitami), stopień energii — bas, RMS i góra —
    czyli pierwszy bit nowej sekcji. Głos dostaje premię, gdy leży też na
    granicy frazy (8/16/32 bity): sekcje w muzyce klubowej zaczynają się
    na jedynce frazy, a to najbardziej odporny dowód, jaki mamy bez ucha.
    Zwraca (b, pewnosc): jedynki leżą na liniach o indeksie ≡ b (mod 4).
    """
    czas = x.size / sr
    n_b = int((czas - kotwica) / okres)
    if n_b < MIN_KICKOW_DO_TAKTU:
        return 0, 0.0
    krok = max(1, int(round(sr / 1000.0)))
    e_all = _obwiednia_pasma(x, sr, 20.0, sr / 2 - 1, 0.003, krok)
    e_hi = _obwiednia_pasma(x, sr, 2000.0, min(9000.0, sr / 2 - 1), 0.003, krok)
    granice = kotwica + np.arange(n_b + 1) * okres
    idx = np.clip((granice * fps).astype(int), 0, e_all.size - 1)

    def seg(e: np.ndarray, i: int) -> np.ndarray:
        return e[idx[i]:max(idx[i] + 1, idx[i + 1])]

    lb = np.log10(np.array([seg(e_low, i).max() for i in range(n_b)]) + 1e-6)
    lr = np.log10(np.array([np.sqrt(np.mean(seg(e_all, i) ** 2)) for i in range(n_b)]) + 1e-6)
    lh = np.log10(np.array([seg(e_hi, i).max() for i in range(n_b)]) + 1e-6)
    dowody: list[tuple[int, float]] = []
    for n in range(8, n_b - 8):
        med = np.median(np.concatenate([lh[n - 8:n], lh[n + 1:n + 9]]))
        if lh[n] - med >= 0.2 and lh[n] >= lh[n - 3:n + 4].max():
            dowody.append((n, min(lh[n] - med, 0.6) * 2.5))          # crash
    for v, prog in ((lb, 0.25), (lr, 0.2), (lh, 0.3)):
        for n in range(2, n_b - 2):
            skok = v[n] - v[n - 2:n].max()
            trzyma = v[n + 1:n + 3].min() - v[n - 2:n].max()
            if skok >= prog and trzyma >= 0.5 * prog:
                dowody.append((n, min(skok, 0.8)))                     # stopień: nowa sekcja
    if not dowody:
        return 0, 0.0
    glosy = np.zeros(4)
    for n, w in dowody:
        b = n % 4
        glosy[b] += w * (1 + 0.5 * (n % 8 == b) + 0.5 * (n % 16 == b) + 0.5 * (n % 32 == b))
    kol = np.argsort(-glosy)
    pewnosc = float((glosy[kol[0]] - glosy[kol[1]]) / (glosy[kol[0]] + 1e-9))
    return int(kol[0]), pewnosc


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
    t_on, s_on, waga, d_all, e_low, fps = _transjenty(x, sr)
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
    # bywa o kilka setnych obok: 154,96 zamiast 155. Precyzja pomiaru maleje
    # z pewnością, więc i tolerancja snapu rośnie — hard techno o 154,96 BPM
    # nie istnieje, a 0,04 BPM to 8 ms rozjazdu na końcu 5-minutowego utworu.
    if spojnosc < 0.5:
        snap = _snap(bpm, SNAP_BPM_NIEPEWNE)
        if snap != bpm:
            bpm, okres = snap, 60.0 / snap
            faza, spojnosc = _faza(t_on, w, okres)

    # Fazę wyznaczyły stopy; kotwicą jest natomiast PIERWSZY słyszalny bit
    # na tej siatce po początku muzyki — także w filtrowanym intrze, gdzie
    # stopa nie ma jeszcze basu (Odymel — Gucci: bity od 9 s, pełna stopa
    # dopiero od 16 s). Zapas: pierwsza mocna stopa, potem najmocniejsza.
    r = (t_on - faza) / okres
    na_siatce = np.abs((r - np.round(r)) * okres) < 0.08 * okres
    po_starcie = t_on >= max(0.0, od_s - 0.05)
    slyszalne = s_on >= 0.3 * float(np.median(s_on[na_siatce])) if na_siatce.any() else s_on > 0
    mocne = w >= 0.35 * float(np.percentile(w, 90))
    for maska in (na_siatce & po_starcie & slyszalne, na_siatce & mocne):
        if maska.any():
            pierwszy = float(t_on[maska][0])
            break
    else:
        pierwszy = float(t_on[int(np.argmax(w))])
    kotwica = faza + np.round((pierwszy - faza) / okres) * okres
    while kotwica < 0:
        kotwica += okres

    b, pewnosc_taktu = _jedynka(x, sr, kotwica, okres, e_low, fps)
    kickow = int(mocne.sum())
    opis = ("siatka na stopie" if spojnosc >= PROG_PEWNOSCI
            else "stopa niewyraźna — siatka może leżeć obok, sprawdź uchem")
    return Siatka(bpm=round(bpm, 3), first_beat_s=round(float(kotwica), 3),
                  battito=battito_dla(b), pewnosc=round(spojnosc, 3),
                  pewnosc_taktu=round(pewnosc_taktu, 2), kickow=kickow, opis=opis)
