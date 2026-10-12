"""Audio quality verification — the fake-FLAC detector.

Lossy codecs low-pass the signal: ~16-17 kHz for 128 kbps, ~19 kHz for
192 kbps, ~19,5 kHz for 256 kbps, ~20,2 kHz for 320 kbps. Genuine lossless
keeps energy up to Nyquist. We measure the spectral cutoff on a 60 s window
from the middle of the track, and separately verify that nominal 24-bit
files carry real 24-bit data (not 16 bits padded with zeros).

Najważniejsza lekcja z przeglądu 0.4.2: typowy fałszywy FLAC powstaje
z głośnego utworu klubowego. Dekoder MP3 oddaje szczyty powyżej 0 dBFS,
a zapis do 16/24 bitów je przycina — każde takie przycięcie to krótki
trzask szerokopasmowy, który zalewa pasmo nad cięciem (−46…−63 dB zamiast
cyfrowej ciszy). Uśrednione widmo wyglądało wtedy jak „master z lowpassem”
i 15/15 transkodów MP3 192–320 przechodziło jako „warn”.

Dlatego widmo liczymy TYLKO z ramek bez przyciętych próbek (przycięcie
to próbka na skrajnej wartości pliku — zwykle 1–3 % ramek). W czystych
ramkach transkod pokazuje to, czym jest: ostrą ścianę i cyfrową ciszę nad
nią. Do tego dwa rozstrzygające ślady kodeka MP3/AAC:

* **ściana** — spadek poziomu na szerokości ±0,3–1 kHz wokół cięcia;
  koder tnie ostro (30–60 dB), master z łagodnym filtrem — kilkanaście dB;
* **dziury** — tuż pod cięciem koder MP3 zeruje całe grupy prążków
  w pojedynczych ramkach (pasmo sfb21); w prawdziwym nagraniu szum
  wysokich częstotliwości jest ciągły;
* **zaniki** — to samo w czasie: pasmo pod cięciem znika na jedną granulę
  (~12 ms) i wraca; porównujemy pasmo samo ze sobą, więc nie myli tego
  zbocze filtra masteringowego.

Ściana 19,8–20,9 kHz z ciszą nad nią bywa też śladem porządnej konwersji
48→44,1 kHz przy masteringu — tam „bad” wymaga obu śladów kodeka naraz,
a sama ściana daje „warn” (bramka pobrań przepuszcza, lista „sprawdź
uchem” pokazuje). AAC 256 kbps i część LAME V0 nie zostawiają w widmie
rozstrzygających śladów — tego ta metoda nie wykryje.

Requires ffmpeg on PATH.
"""
from __future__ import annotations

import os
import subprocess
import warnings
from dataclasses import dataclass, field

import numpy as np

from .narzedzia import ffmpeg_path, ffprobe_path  # noqa: F401  (ffprobe: zgodność importów)
from mutagen import File as MutagenFile


@dataclass
class QualityReport:
    path: str
    ext: str
    sample_rate: int
    nominal_bits: int | None
    effective_bits: int | None
    cutoff_hz: float
    grade: str          # "ok" | "warn" | "bad"
    verdict: str
    bitrate_kbps: int | None = None   # z nagłówka; None dla lossless
    cechy: dict = field(default_factory=dict)   # pomiary, na których oparto werdykt


BEZSTRATNE_EXT = (".flac", ".wav", ".aiff", ".aif")

# Progi decyzji dla plików bezstratnych (dB względem poziomu 5–14 kHz).
# Strojone na 27 utworach z biblioteki × 25 wariantów (część strojeniowa:
# oryginał, mastery z lowpassem i konwersją 48→44,1 kHz, przester, ALAC,
# 24 bit, hi-res; transkody MP3 128–320/V0/V2 i AAC 128/256 do FLAC/WAV/AIFF/
# ALAC), sprawdzane na 25 innych utworach (część kontrolna) — raport napraw.
SCIANA_DB = 28.0          # min. spadek na ścianie, żeby uznać ją za cięcie
CISZA_DB = -62.0          # nad ścianą tylko szum zaokrągleń = cyfrowa cisza
PELNE_PASMO_HZ = 20900
STREFA_320_HZ = 19800     # od tej ściany w górę: MP3 320 albo filtr SRC przy masteringu
# poniżej 19,8 kHz: filtr masteringowy daje 22–36 dB, koder 59–72 dB (MP3)
# albo ~35 dB z masą dziur (AAC Apple 128: 0,19–0,36)
SCIANA_KODEKA_DB = 50.0
DZIURY_KODEKA = 0.05
# 19,8–20,9 kHz: stroma ściana z ciszą zostawia też porządna konwersja
# częstotliwości — „bad” tylko z oboma śladami kodeka naraz
SCIANA_320_DB = 45.0
DZIURY_320 = 0.02
ZANIKI_320 = 0.005
# pełne pasmo z dziurami i zanikami: LAME V0 nie tnie pasma — tylko „warn”,
# bo taki sam ślad zostawia rzadka góra pasma niektórych masterów
ZANIKI_V0 = 0.03
DZIURY_V0 = 0.10
PASMO_OK_HZ = 18000       # bez śladów kodeka niżej to już ciemny master: „warn”


def _decode(path: str, ss: float, dur: float, fmt: str, extra: list[str]) -> bytes:
    cmd = [ffmpeg_path(), "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", path,
           *extra, "-f", fmt, "-"]
    return subprocess.run(cmd, capture_output=True).stdout


def _stereo(path: str, length: float) -> np.ndarray:
    """Do 60 s ze środka, dwa kanały float32, w natywnym próbkowaniu."""
    ss = max(0.0, length / 2 - 30)
    raw = _decode(path, ss, 60, "f32le", ["-ac", "2"])
    x = np.frombuffer(raw, dtype=np.float32)
    return x[: x.size // 2 * 2].reshape(-1, 2)


def _przyciete(x: np.ndarray) -> np.ndarray:
    """Maska próbek na skrajnej wartości kanału (przycięcie przy zapisie).

    Pojedyncza próbka szczytowa prawdziwego nagrania też tu wpada — to bez
    znaczenia, bo tracimy jedną-dwie ramki. Ważne, żeby złapać KAŻDE
    przycięcie: już jedna przycięta próbka sieje szumem nad cięciem.
    """
    m = np.zeros(x.shape[0], dtype=bool)
    for c in range(x.shape[1]):
        ch = x[:, c]
        hi, lo = float(ch.max()), float(ch.min())
        if hi > 0.5:
            m |= ch >= hi - 1e-6
        if lo < -0.5:
            m |= ch <= lo + 1e-6
    return m


def _pasma(widmo: np.ndarray, czest: np.ndarray, band: float = 100.0):
    nb = int(czest[-1] // band)
    idx = (czest // band).astype(int)
    ok = idx < nb
    suma = np.bincount(idx[ok], weights=widmo[ok], minlength=nb)
    ile = np.bincount(idx[ok], minlength=nb)
    poziomy = 10 * np.log10(suma / np.maximum(ile, 1) + 1e-20)
    return poziomy, (np.arange(nb) + 0.5) * band


def _cutoff_z_widma(levels, centers, ref) -> float:
    for i in range(len(levels) - 1, -1, -1):
        if levels[i] > ref - 42:
            return float(centers[i] + 50)
    return 0.0


def _pomiar(path: str, length: float, sr: int) -> dict | None:
    """Widmo z czystych ramek + cechy kodeka. None dla za krótkiego materiału."""
    x = _stereo(path, length)
    if x.shape[0] < sr * 10:
        return None
    n = 2048 if sr <= 50000 else 4096
    hop = n // 2
    nf = (x.shape[0] - n) // hop
    przyc = _przyciete(x)
    sk = np.concatenate([[0], np.cumsum(przyc)])
    starty = hop * np.arange(nf)
    czyste = (sk[starty + n] - sk[starty]) == 0
    okno = np.hanning(n).astype(np.float32)
    czest = np.fft.rfftfreq(n, 1 / sr)
    idx = np.arange(n)[None, :] + starty[:, None]
    P = np.zeros((nf, n // 2 + 1))
    for c in range(x.shape[1]):
        P += np.abs(np.fft.rfft(x[idx, c] * okno, axis=1)) ** 2
    moc = P.sum(axis=1)
    aktywne = moc > np.percentile(moc, 20) * 0.1
    uzyte = aktywne & czyste
    if uzyte.sum() < max(20, 0.2 * aktywne.sum()):
        uzyte = aktywne                    # prawie wszystko przycięte: bierzemy co jest
    levels, centers = _pasma(P[uzyte].mean(axis=0), czest)
    ref = float(levels[(centers >= 5000) & (centers <= 14000)].mean())
    cut = _cutoff_z_widma(levels, centers, ref)

    def sredni(lo, hi):
        sel = (centers > lo) & (centers < hi)
        return float(levels[sel].mean()) if sel.any() else None

    pod = sredni(cut - 1000, cut - 300)
    nad_tuz = sredni(cut + 300, cut + 1000)
    sciana = (pod - nad_tuz) if pod is not None and nad_tuz is not None else None
    nad = sredni(cut + 300, centers[-1] - 100)
    cisza = (nad - ref) if nad is not None else None

    # dziury: komórki (ramka, prążek) tuż pod cięciem, o 40 dB niższe od
    # najmocniejszego prążka tego pasma w tej samej ramce — liczone tylko
    # w ramkach, w których pasmo w ogóle gra (> 20 dB nad szumem 16 bit)
    sel = (czest > cut - 3000) & (czest < cut - 150)
    dziury = None
    if sel.sum() >= 8:
        L = 10 * np.log10(P[uzyte][:, sel] + 1e-20)
        gra = L.max(axis=1) > (10 * np.log10(n * 0.375 * 2 * (2 ** -15) ** 2 / 12 + 1e-30) + 20)
        if gra.sum() >= 10:
            dziury = float(np.mean(L[gra] < L[gra].max(axis=1, keepdims=True) - 40))
    return {"sr": sr, "cutoff": cut, "sciana_db": sciana, "zaniki": _zaniki(x, sr, cut, przyc), "cisza_db": cisza, "dziury": dziury,
            "ramek": int(nf), "przyciete_ramki": round(float(1 - czyste.mean()), 4),
            "levels": levels, "centers": centers, "ref": ref}


def _zaniki(x: np.ndarray, sr: int, cut: float, przyc: np.ndarray) -> float | None:
    """Udział krótkich zaników w pasmie tuż pod cięciem.

    Koder MP3 w pojedynczej granuli (13 ms) potrafi wyzerować całe pasmo
    współczynnika skali; prawdziwy szum wysokich częstotliwości (talerze,
    pogłos) tak nie znika. Liczymy w krótkich ramkach (~12 ms) pasma po
    500 Hz i sprawdzamy, jak często poziom spada o 15 dB poniżej mediany
    z otoczenia ±46 ms. W przeciwieństwie do „dziur” liczonych w jednej
    ramce nie myli tego zbocze filtra (master z lowpassem) — porównujemy
    pasmo samo ze sobą w czasie.
    """
    n = 512 if sr <= 50000 else 1024
    hop = n // 2
    nf = (x.shape[0] - n) // hop
    gora = min(cut, sr / 2) - 200
    dol = max(gora - 4000, 6000)
    if nf < 50 or gora - dol < 1000:
        return None
    sk = np.concatenate([[0], np.cumsum(przyc)])
    starty = hop * np.arange(nf)
    czyste = (sk[starty + n] - sk[starty]) == 0
    czest = np.fft.rfftfreq(n, 1 / sr)
    sel = (czest >= dol) & (czest < gora)
    idx = np.arange(n)[None, :] + starty[:, None]
    okno = np.hanning(n).astype(np.float32)
    P = np.zeros((nf, int(sel.sum())))
    for c in range(x.shape[1]):
        P += np.abs(np.fft.rfft(x[idx, c] * okno, axis=1)[:, sel]) ** 2
    podloga = 10 * np.log10(n * 0.375 * 2 * (2 ** -15) ** 2 / 12)
    f_sel = czest[sel]
    kontekst = 8
    lacznie = zanikow = 0
    for a in np.arange(dol, gora - 499, 500.0):
        pas = (f_sel >= a) & (f_sel < a + 500)
        if not pas.any():
            continue
        L = 10 * np.log10(P[:, pas].mean(axis=1) + 1e-20)
        # mediana z otoczenia tylko z czystych ramek: ramka z przyciętą
        # próbką ma szum przesteru nad całym pasmem, a jej czysta sąsiadka
        # wyglądałaby przy niej na „zanik”
        Lc = np.where(czyste, L, np.nan)
        okolica = np.lib.stride_tricks.sliding_window_view(
            np.pad(Lc, kontekst, mode="edge"), 2 * kontekst + 1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # okno z samych przyciętych ramek
            med = np.nanmedian(okolica, axis=1)
        med = np.where(np.isnan(med), -np.inf, med)
        ok = czyste & (med > podloga + 25)
        lacznie += int(ok.sum())
        zanikow += int((ok & (L < med - 15)).sum())
    return zanikow / lacznie if lacznie >= 200 else None


def spectral_cutoff(path: str, length: float, sr: int) -> float:
    w = _pomiar(path, length, sr)
    return w["cutoff"] if w else 0.0


def effective_bits(path: str, length: float) -> int:
    ss = max(0.0, length / 2 - 15)
    raw = _decode(path, ss, 30, "s32le", [])
    x = np.frombuffer(raw, dtype=np.int32)
    x = x[x != 0]
    if len(x) == 0:
        return 0
    combined = int(np.bitwise_or.reduce(x))
    tz = 0
    while tz < 32 and not (combined >> tz) & 1:
        tz += 1
    return 32 - tz


def _verdict(cutoff: float, ext: str) -> tuple[str, str]:
    """Werdykt z samego pasma (pliki stratne; zapas, gdy brak pomiaru cech)."""
    lossless = ext in BEZSTRATNE_EXT
    if cutoff >= 20900:
        return "ok", "pełne pasmo — prawdziwy lossless" if lossless else "pełne pasmo — bardzo dobre 320"
    if cutoff >= 19800:
        if not lossless:
            return "ok", "typowe pasmo dla 320 kbps"
        return "warn", "pasmo ~20,5 kHz — możliwy transkod z MP3 320 (albo master z lowpassem)"
    if cutoff >= 18300:
        return "warn", "pasmo ~19 kHz — wygląda na źródło ~256 kbps / V0"
    if cutoff >= 15300:
        return "bad", "pasmo ~16 kHz — źródło ~128–192 kbps"
    return "bad", "bardzo wąskie pasmo — kiepskie źródło"


def _zrodlo_z_ciecia(cutoff: float) -> str:
    pasmo = f" (pasmo ~{cutoff / 1000:.0f} kHz)"
    if cutoff < 17500:
        return "MP3/AAC ~128 kbps" + pasmo
    if cutoff < 19200:
        return "MP3 ~192 kbps / V2" + pasmo
    if cutoff < 19800:
        return "MP3 ~256 kbps" + pasmo
    return "MP3 320 kbps" + pasmo


def ocena_bezstratnego(c: dict, sr: int) -> tuple[str, str]:
    """Werdykt dla kontenera bezstratnego z cech widma czystych ramek.

    Ściana z cyfrową ciszą nad nią sama nie przesądza: podobną zostawia
    konwersja 48→44,1 kHz przy masteringu. Rozstrzyga stromość ściany
    (koder tnie dużo ostrzej niż filtr masteringowy) i ślady kodeka pod
    nią — „dziury” (wyzerowane grupy prążków) i krótkie „zaniki” pasma.
    """
    cut, sciana, cisza = c["cutoff"], c["sciana_db"], c["cisza_db"]
    dziury, zaniki = c.get("dziury") or 0.0, c.get("zaniki") or 0.0
    khz = f"{cut / 1000:.1f} kHz"
    nyq = sr / 2
    ostra = sciana is not None and sciana >= SCIANA_DB
    cicho = cisza is not None and cisza <= CISZA_DB
    pelne = cut >= min(PELNE_PASMO_HZ, nyq - 1200)
    if not pelne and ostra and cicho:
        if cut < STREFA_320_HZ:
            if sciana >= SCIANA_KODEKA_DB or dziury >= DZIURY_KODEKA:
                return "bad", (f"pasmo ucięte ostro na {khz}, nad nim cyfrowa cisza "
                               f"— transkod z {_zrodlo_z_ciecia(cut)}")
            return "warn", (f"pasmo ucięte na {khz} bez wyraźnych śladów kodeka — "
                            f"master z mocnym filtrem albo transkod; sprawdź źródło")
        if sciana >= SCIANA_320_DB and dziury >= DZIURY_320 and zaniki >= ZANIKI_320:
            return "bad", (f"pasmo ucięte ostro na {khz}, nad nim cyfrowa cisza, pod nim "
                           f"ślady kodeka MP3 — transkod z {_zrodlo_z_ciecia(cut)}")
        return "warn", (f"ostra ściana na {khz} — możliwy transkod z MP3 320 albo konwersja "
                        f"częstotliwości przy masteringu; sprawdź źródło")
    if pelne and zaniki >= ZANIKI_V0 and dziury >= DZIURY_V0:
        return "warn", ("pełne pasmo, ale z „dziurami” typowymi dla kodeka MP3 — możliwy "
                        "transkod z MP3 V0; sprawdź źródło")
    if sr > 50000 and cut < min(nyq * 0.6, 26500) and cicho:
        return "warn", (f"deklarowane {sr / 1000:g} kHz, a dźwięk kończy się na {khz} "
                        f"— przepróbkowane z 44,1/48 kHz (jakość CD, nie hi-res)")
    if pelne:
        return "ok", "pełne pasmo — prawdziwy lossless"
    if cut >= PASMO_OK_HZ:
        return "ok", f"pasmo do {khz} z łagodnym zboczem — master z filtrem, bez śladów kodeka"
    return "warn", (f"pasmo tylko do {khz}, ale bez śladów kodeka — master "
                    f"z mocnym lowpassem (brzmi ciemniej)")


def _ocena_stratnego(cutoff: float, ext: str, br: int | None, kanaly: int) -> tuple[str, str]:
    """Pliki stratne: liczba z nagłówka przesądza, pasmo ją potwierdza.

    Samo pasmo nie odróżnia MP3 mono 128 od 320 (LAME przy 128 mono nie
    tnie pasma) — werdykt „typowe pasmo dla 320” był tam mylący.
    """
    grade, verdict = _verdict(cutoff, ext)
    if not br:
        return grade, verdict
    # na kanał: 320 kbps stereo = 160, 256 = 128, 192 = 96, 128 = 64;
    # mono 128 kbps brzmi jak stereo 256 — czyli „warn”, nie „jak 320”
    na_kanal = br / max(1, kanaly)
    if ext in (".m4a", ".mp4", ".aac"):
        na_kanal *= 1.4          # AAC 256 kbps ≈ MP3 320 kbps, AAC 128 ≈ MP3 192
    opis = f"{br} kbps" + (" mono" if kanaly == 1 else "")
    if na_kanal >= 150:
        g = "ok"
    elif na_kanal >= 90:
        g = "warn"
    else:
        g = "bad"
    # pasmo może tylko obniżyć ocenę (np. 320 kbps nadmuchane z 128)
    rang = {"ok": 0, "warn": 1, "bad": 2}
    if rang[grade] > rang[g] and kanaly > 1:
        return grade, f"{opis}, ale {verdict}"
    return g, f"{opis}, pasmo {cutoff / 1000:.1f} kHz"


def analyze(path: str) -> QualityReport:
    audio = MutagenFile(path)
    if audio is None:
        raise ValueError(f"nierozpoznany format audio: {path}")
    sr = audio.info.sample_rate
    length = audio.info.length
    ext = os.path.splitext(path)[1].lower()
    bits = getattr(audio.info, "bits_per_sample", None)
    kodek = str(getattr(audio.info, "codec", "") or "").lower()
    lossless = ext in BEZSTRATNE_EXT or (ext in (".m4a", ".mp4") and kodek == "alac")

    c = _pomiar(path, length, sr)
    cutoff = c["cutoff"] if c else 0.0
    eff = effective_bits(path, length) if bits and bits > 16 else None
    br = None
    if not lossless:
        surowy = getattr(audio.info, "bitrate", 0) or 0
        br = round(surowy / 1000) or None
    if lossless and c:
        grade, verdict = ocena_bezstratnego(c, sr)
    elif lossless:
        grade, verdict = "warn", "za mało materiału do oceny pasma"
    else:
        grade, verdict = _ocena_stratnego(cutoff, ext, br, getattr(audio.info, "channels", 2) or 2)
    if bits and bits > 16 and eff and eff <= 16:
        # deklarowane 24 bity, realnie 16: dopisujemy, ale NIE łagodzimy
        # oceny — wcześniej ten warunek zamieniał wykryty transkod („bad”)
        # na „warn” i fałszywy FLAC w kontenerze 24-bit zawsze przechodził
        if grade == "ok":
            grade = "warn"
        verdict += f"; deklarowane {bits}-bit, realnie {eff}-bit"
    cechy = {}
    if c:
        cechy = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()
                 if k not in ("levels", "centers", "ref")}
    return QualityReport(path, ext, sr, bits, eff, cutoff, grade, verdict, br, cechy)
