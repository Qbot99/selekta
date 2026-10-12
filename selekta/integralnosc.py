"""Integralność pliku audio: czy dekoduje się w całości i czy nie jest ucięty.

Samo pełne dekodowanie (liczenie błędów ffmpeg) nie wystarcza. Ucięty
transfer MP3 urywa się zwykle na granicy ramki albo w ostatniej ramce, którą
dekoder po cichu pomija — ffmpeg nie zgłasza wtedy ŻADNEGO błędu, a plik
z połową danych dostawał „dekoduje się bez błędów” (przegląd 0.4.2: wykryte
tylko 38 ze 75 losowych ucięć MP3).

Dlatego porównujemy to, co plik ZAPOWIADA w nagłówku, z tym, co naprawdę
da się z niego zdekodować:

* MP3 — liczba ramek z nagłówka Xing/Info/VBRI (LAME, większość plików),
  a dodatkowo przejście po ramkach: ostatnia ramka urwana w połowie to
  pewny znak ucięcia, także w plikach bez nagłówka Xing;
* FLAC — liczba próbek ze STREAMINFO i suma MD5 zdekodowanego dźwięku
  (wykrywa też uszkodzenia, które dekoder przełknie);
* M4A/AAC/ALAC — długość z nagłówka mvhd;
* WAV/AIFF — rozmiar zadeklarowany w nagłówku (WAV nie ma sum kontrolnych,
  więc wyzerowany fragment w środku jest niewykrywalny — mówimy to wprost).

Funkcja ``problem(path)`` ma kontrakt jak dawne ``health._ffmpeg_check``:
opis kłopotu albo ``None`` — można ją podstawić w skanie zdrowia biblioteki.
"""
from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import dataclass

from .narzedzia import ffmpeg_path

# Ucięcie krótsze od tej wartości uznajemy za szum pomiaru (opóźnienie
# kodera, ramka Xing, wypełnienie końca). Zmierzone różnice na zdrowych
# plikach: do ~0,06 s; najkrótsze ucięcie, które ma być wykryte: 1 s.
TOLERANCJA_S = 0.5
TOLERANCJA_WZGL = 0.002          # przy bardzo długich plikach (miksy)


@dataclass
class Integralnosc:
    ok: bool
    opis: str
    bledow: int = 0                     # linie błędów z dekodera
    zdekodowane_s: float | None = None
    deklarowane_s: float | None = None
    gdzie: str = ""                     # "koniec" | "środek" | ""


# ---------------------------------------------------------------- MP3

_MP3_BITRATY = {
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_MP3_PROBKOWANIE = {1: [44100, 48000, 32000], 2: [22050, 24000, 16000],
                    2.5: [11025, 12000, 8000]}


def _naglowek_ramki(b: bytes, i: int):
    """(długość ramki, próbek w ramce, próbkowanie, wersja, mono) albo None."""
    if i + 4 > len(b) or b[i] != 0xFF or (b[i + 1] & 0xE0) != 0xE0:
        return None
    v = (b[i + 1] >> 3) & 3
    warstwa = (b[i + 1] >> 1) & 3
    br_i = (b[i + 2] >> 4) & 15
    sr_i = (b[i + 2] >> 2) & 3
    pad = (b[i + 2] >> 1) & 1
    if v == 1 or warstwa != 1 or br_i in (0, 15) or sr_i == 3:
        return None                     # tylko Layer III, bez free-format
    wersja = {3: 1, 2: 2, 0: 2.5}[v]
    br = _MP3_BITRATY[(1 if wersja == 1 else 2, 3)][br_i] * 1000
    sr = _MP3_PROBKOWANIE[wersja][sr_i]
    probek = 1152 if wersja == 1 else 576
    dl = (probek // 8 * br) // sr + pad
    mono = ((b[i + 3] >> 6) & 3) == 3
    return dl, probek, sr, wersja, mono


def _mp3_ramki(path: str) -> dict | None:
    """Przejdź po ramkach MP3: nagłówek Xing/VBRI i czy ostatnia ramka jest cała."""
    try:
        with open(path, "rb") as fh:
            b = fh.read()
    except OSError:
        return None
    i = 0
    if b[:3] == b"ID3" and len(b) >= 10:
        rozm = ((b[6] & 0x7F) << 21) | ((b[7] & 0x7F) << 14) | ((b[8] & 0x7F) << 7) | (b[9] & 0x7F)
        i = 10 + rozm + (10 if b[5] & 0x10 else 0)
    # pierwsza ramka: synchronizacja potwierdzona kolejną ramką
    koniec_szukania = min(len(b), i + 1024 * 1024)
    while i < koniec_szukania:
        h = _naglowek_ramki(b, i)
        if h and _naglowek_ramki(b, i + h[0]):
            break
        i += 1
    else:
        return None
    dl0, probek, sr, wersja, mono = _naglowek_ramki(b, i)
    # Xing/Info siedzi za informacją boczną, VBRI zawsze 32 bajty za nagłówkiem
    boczna = (17 if mono else 32) if wersja == 1 else (9 if mono else 17)
    xing = b[i + 4 + boczna: i + 8 + boczna] in (b"Xing", b"Info")
    vbri = b[i + 36: i + 40] == b"VBRI"
    ramek, pos, urwana = 0, i, False
    while pos < len(b):
        h = _naglowek_ramki(b, pos)
        if h is None:
            # 1–3 bajty zaczynające się od bajtu synchronizacji to nagłówek
            # ramki urwany w połowie
            reszta = len(b) - pos
            urwana = 0 < reszta < 4 and b[pos] == 0xFF
            break
        if pos + h[0] > len(b):
            urwana = True               # ramka sięga za koniec pliku
            break
        ramek += 1
        pos += h[0]
    # to, co zostaje za ostatnią ramką, powinno być tagiem (ID3v1, APE,
    # Lyrics3) albo niczym; śmieci w środku pokaże dekoder
    return {"xing": xing or vbri, "ramek": ramek, "urwana": urwana,
            "probek_w_ramce": probek, "sr": sr}


# ---------------------------------------------------------------- MP4

def _mp4_urwany(path: str) -> bool:
    """Czy ostatni blok (atom) kontenera MP4/M4A sięga za koniec pliku.

    ffmpeg domyślnie zapisuje indeks (moov) na końcu, więc ucięty transfer
    traci go razem z końcem danych — pliku nie da się wtedy w ogóle otworzyć
    i dawniej opisywaliśmy to jako „błędy w środku utworu”.
    """
    try:
        rozmiar = os.path.getsize(path)
        with open(path, "rb") as fh:
            pos = 0
            while pos + 8 <= rozmiar:
                fh.seek(pos)
                nag = fh.read(16)
                dl = struct.unpack(">I", nag[:4])[0]
                if dl == 1 and len(nag) >= 16:
                    dl = struct.unpack(">Q", nag[8:16])[0]
                elif dl == 0:
                    return False                # atom do końca pliku
                if dl < 8:
                    return False                # nie MP4 albo śmieci — oceni dekoder
                if pos + dl > rozmiar:
                    return True
                pos += dl
            return 0 < rozmiar - pos < 8
    except OSError:
        return False


# ---------------------------------------------------------------- nagłówki

def _wav_dane(path: str) -> tuple[int, int] | None:
    """(zadeklarowany rozmiar danych, faktycznie dostępny) dla WAV."""
    try:
        with open(path, "rb") as fh:
            naglowek = fh.read(12)
            if naglowek[:4] not in (b"RIFF", b"RF64") or naglowek[8:12] != b"WAVE":
                return None
            rozmiar_pliku = os.fstat(fh.fileno()).st_size
            while True:
                ch = fh.read(8)
                if len(ch) < 8:
                    return None
                ident, dl = ch[:4], struct.unpack("<I", ch[4:])[0]
                if ident == b"data":
                    return dl, rozmiar_pliku - fh.tell()
                fh.seek(dl + (dl & 1), 1)
    except OSError:
        return None


def deklarowana_dlugosc(path: str) -> tuple[float | None, str]:
    """Długość zapowiadana przez nagłówek pliku [s] i jej źródło.

    ``None``, gdy plik nie niesie niezależnej informacji o długości (np. MP3
    CBR bez nagłówka Xing — tam długość i tak liczy się z rozmiaru pliku).
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path)
    except Exception:                       # noqa: BLE001 — uszkodzony nagłówek
        audio = None
    if ext == ".flac":
        info = getattr(audio, "info", None)
        if info is not None and getattr(info, "total_samples", 0) and info.sample_rate:
            return info.total_samples / info.sample_rate, "STREAMINFO"
        return None, ""
    if ext == ".mp3":
        r = _mp3_ramki(path)
        if r and r["xing"] and audio is not None and audio.info.length > 0:
            return float(audio.info.length), "Xing"
        return None, ""
    if ext in (".m4a", ".mp4", ".aac", ".alac"):
        if audio is not None and audio.info.length > 0:
            return float(audio.info.length), "mvhd"
        return None, ""
    if ext == ".wav":
        dane = _wav_dane(path)
        info = getattr(audio, "info", None)
        if dane and info is not None and dane[0] not in (0, 0xFFFFFFFF) and info.length > 0:
            return float(info.length), "RIFF"
        return None, ""
    if ext in (".aif", ".aiff"):
        if audio is not None and audio.info.length > 0:
            return float(audio.info.length), "COMM"
        return None, ""
    return None, ""


# ---------------------------------------------------------------- dekodowanie

def _dekoduj(path: str, md5_kodek: str | None, od: float | None = None,
             dlugosc: float | None = None) -> tuple[list[str], float | None, str | None]:
    """Pełne dekodowanie: (linie błędów, zdekodowane sekundy, MD5 próbek)."""
    cmd = [ffmpeg_path(), "-v", "error", "-nostdin"]
    if od is not None:
        cmd += ["-ss", str(od)]
    if dlugosc is not None:
        cmd += ["-t", str(dlugosc)]
    cmd += ["-i", path, "-map", "0:a:0"]
    if md5_kodek:
        cmd += ["-c:a", md5_kodek, "-f", "md5", "-"]
    else:
        cmd += ["-f", "null", "-"]
    cmd += ["-progress", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"ffmpeg: {type(exc).__name__}"], None, None
    bledy = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    if proc.returncode != 0 and not bledy:
        bledy = [f"ffmpeg zakończył się kodem {proc.returncode}"]
    czas, md5 = None, None
    for ln in proc.stdout.splitlines():
        if ln.startswith("out_time_us="):
            try:
                czas = int(ln.split("=", 1)[1]) / 1e6
            except ValueError:
                pass
        elif ln.startswith("MD5="):
            md5 = ln.split("=", 1)[1].strip().lower()
    return bledy, czas, md5


def _flac_md5(path: str) -> tuple[str | None, str | None]:
    """(MD5 ze STREAMINFO, kodek PCM, którym ffmpeg odtworzy te same bajty)."""
    try:
        from mutagen.flac import FLAC
        info = FLAC(path).info
    except Exception:                       # noqa: BLE001
        return None, None
    if not getattr(info, "md5_signature", 0):
        return None, None                   # koder nie zapisał sumy
    kodek = {16: "pcm_s16le", 24: "pcm_s24le"}.get(info.bits_per_sample)
    if kodek is None:
        return None, None
    return f"{info.md5_signature:032x}", kodek


# ---------------------------------------------------------------- API

def zbadaj(path: str) -> Integralnosc:
    """Pełna kontrola integralności jednego pliku."""
    ext = os.path.splitext(path)[1].lower()
    md5_wzor, md5_kodek = _flac_md5(path) if ext == ".flac" else (None, None)
    bledy, zdekodowane, md5 = _dekoduj(path, md5_kodek)
    deklarowane, zrodlo = deklarowana_dlugosc(path)
    n = len(bledy)

    powody, gdzie = [], ""
    if deklarowane and zdekodowane is not None:
        brak = deklarowane - zdekodowane
        if brak > max(TOLERANCJA_S, TOLERANCJA_WZGL * deklarowane):
            powody.append(f"brakuje końca: zdekodowano {_mmss(zdekodowane)} "
                          f"z {_mmss(deklarowane)} zapowiadanych w nagłówku")
            gdzie = "koniec"
    if ext == ".mp3":
        r = _mp3_ramki(path)
        if r and r["urwana"] and not gdzie:
            powody.append("ostatnia ramka urwana w połowie")
            gdzie = "koniec"
    if ext in (".m4a", ".mp4", ".aac", ".alac") and not gdzie and _mp4_urwany(path):
        powody.append("plik urwany — ostatni blok danych sięga za koniec pliku")
        gdzie = "koniec"
    if md5_wzor and md5 and md5 != md5_wzor and not powody:
        powody.append("suma kontrolna dźwięku (MD5) nie zgadza się z nagłówkiem")
    if n:
        if not gdzie:
            # zlokalizuj, czy błędy leżą przy końcu (sygnatura ucięcia)
            dl = deklarowane or zdekodowane or 0.0
            ogon = (_dekoduj(path, None, max(0.0, dl - 30), 30)[0] if dl else [])
            gdzie = "koniec" if ogon else "środek"
        powody.insert(0, f"{n} {_bledow(n)} dekodowania")

    if not powody:
        return Integralnosc(True, "dekoduje się w całości, bez błędów", 0,
                            zdekodowane, deklarowane, "")
    miejsce = {"koniec": "przy końcu (ucięty transfer)",
               "środek": "w środku utworu"}.get(gdzie, "")
    opis = "; ".join(powody) + (f" — {miejsce}" if miejsce else "") + " — pobierz ponownie"
    return Integralnosc(False, opis, n, zdekodowane, deklarowane, gdzie)


def problem(path: str) -> str | None:
    """Opis kłopotu z plikiem albo None, gdy plik jest cały (kontrakt jak
    ``health._ffmpeg_check``)."""
    wynik = zbadaj(path)
    return None if wynik.ok else wynik.opis


def _bledow(n: int) -> str:
    if n == 1:
        return "błąd"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "błędy"
    return "błędów"


def _mmss(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 60)}:{s % 60:04.1f}"
