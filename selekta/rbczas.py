"""Oś czasu rekordboxa a oś czasu selekty — przesunięcie zależne od pliku.

Selekta dekoduje dźwięk przez ffmpeg, a ffmpeg na starcie POMIJA opóźnienie
kodera zapisane w pliku (MP3: tag Xing/Info z LAME/Lavc, zwykle 1105 próbek;
AAC/M4A: lista edycji, np. 1600 próbek). Rekordbox tego nie robi — jego oś
czasu jest dla takich plików PÓŹNIEJSZA o pominięte próbki. Do tego tag
„LAME” (wielkimi literami) rekordbox odtwarza jako ramkę dźwięku: kolejne
1152 próbki (576 dla MPEG-2/2.5) ciszy na początku.

Zmierzone 12.10.2026 na 124 plikach z przebiegiem fali z analizy rekordboxa
(ANLZ PWV3, korelacja z dekodowaniem ffmpeg co do próbki):
FLAC/WAV 0; MP3 bez tagu 0; Lavc/Lavf/„Lame” = pominięcie ffmpeg (1105/529/0);
„LAME” = pominięcie + 1152; M4A = pominięcie (1600). Bez tej poprawki siatka
i cue z selekty lądowały w rekordboksie 25–51 ms za wcześnie.

Każdy czas wysyłany do XML-a rekordboxa trzeba więc PRZESUNĄĆ o
``przesuniecie_s(plik)``, a czas wczytany z rekordboxa — o tyle cofnąć.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess

from . import cache

RODZAJ_CACHE = "rbczas"


def _pierwsza_ramka(path: str, ile: int = 4096) -> bytes:
    """Pierwsza ramka MPEG audio (po tagu ID3v2) albo b''."""
    with open(path, "rb") as fh:
        d = fh.read(10)
        start = 0
        if d[:3] == b"ID3" and len(d) == 10:
            size = (d[6] << 21) | (d[7] << 14) | (d[8] << 7) | d[9]
            start = 10 + size + (10 if d[5] & 0x10 else 0)
        fh.seek(start)
        d = fh.read(ile + 65536)
    for i in range(len(d) - 4):
        if (d[i] == 0xFF and (d[i + 1] & 0xE0) == 0xE0 and ((d[i + 1] >> 1) & 3) == 1
                and ((d[i + 2] >> 4) & 15) not in (0, 15) and ((d[i + 2] >> 2) & 3) != 3):
            return d[i:i + ile]
    return b""


def ramka_lame(path: str) -> int:
    """Ile próbek ciszy rekordbox doda, odtwarzając ramkę Info z tagiem „LAME” (0, gdy nie doda)."""
    fr = _pierwsza_ramka(path)
    if len(fr) < 200:
        return 0
    wersja = (fr[1] >> 3) & 3            # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    mono = ((fr[3] >> 6) & 3) == 3
    crc = 0 if fr[1] & 1 else 2
    if wersja == 3:
        boczna, probek = (17 if mono else 32), 1152
    else:
        boczna, probek = (9 if mono else 17), 576
    x = 4 + crc + boczna
    if fr[x:x + 4] not in (b"Xing", b"Info"):
        return 0
    flagi = struct.unpack(">I", fr[x + 4:x + 8])[0]
    t = x + 8 + (4 if flagi & 1 else 0) + (4 if flagi & 2 else 0) + (100 if flagi & 4 else 0) + (4 if flagi & 8 else 0)
    return probek if fr[t:t + 4] == b"LAME" else 0


def _pominiecie_ffmpeg(path: str) -> tuple[int, int]:
    """(próbki pomijane przez ffmpeg na starcie, częstotliwość próbkowania)."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate:packet=side_data_list", "-show_packets",
         "-read_intervals", "%+#1", "-of", "json", path],
        capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout or "{}")
    sr = int(((d.get("streams") or [{}])[0]).get("sample_rate") or 0)
    skip = 0
    for pk in d.get("packets") or []:
        for sd in pk.get("side_data_list") or []:
            if sd.get("side_data_type") == "Skip Samples":
                skip = int(sd.get("skip_samples") or 0)
        break
    return skip, sr


def zmierz(path: str) -> float:
    """Przesunięcie [s] bez pamięci podręcznej (0,0 dla formatów bez opóźnienia kodera)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".wav", ".aif", ".aiff", ".flac"):
        return 0.0                       # PCM i FLAC: obie osie zaczynają się od pierwszej próbki
    try:
        skip, sr = _pominiecie_ffmpeg(path)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0
    if not sr:
        return 0.0
    dodatek = ramka_lame(path) if ext == ".mp3" else 0
    return (skip + dodatek) / sr


def przesuniecie_s(path: str) -> float:
    """O ile sekund oś rekordboxa jest PÓŹNIEJSZA niż oś selekty dla tego pliku."""
    try:
        zapis = cache.get(path, RODZAJ_CACHE)
    except OSError:
        return 0.0
    if zapis is not None and "s" in zapis:
        return float(zapis["s"])
    s = zmierz(path)
    try:
        cache.put(path, RODZAJ_CACHE, {"s": s})
    except OSError:
        pass
    return s


def do_rekordboxa(path: str, t: float | None) -> float | None:
    """Czas selekty → czas w XML-u rekordboxa."""
    return None if t is None else t + przesuniecie_s(path)


def z_rekordboxa(path: str, t: float | None) -> float | None:
    """Czas z XML-a rekordboxa → czas selekty."""
    return None if t is None else t - przesuniecie_s(path)
