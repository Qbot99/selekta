"""Analiza głośności (LUFS) i wyliczanie ReplayGain 2.0.

DJ-e chcą, żeby utwory w secie nie skakały poziomem: cichszy kawałek
wpuszczony po głośnym „ginie", a za głośny przesterowuje kanał. rekordbox,
Serato i odtwarzacze CDJ czytają tagi ReplayGain i cofają/podbijają
odtwarzanie zgodnie z zapisaną korektą, dzięki czemu cała biblioteka gra na
jednym, spójnym poziomie.

Mierzymy trzy wielkości zdefiniowane w EBU R128 / ITU-R BS.1770:

* **integrated LUFS** — zintegrowana głośność całego utworu (bramkowana),
* **true peak (dBTP)** — szczyt sygnału z uwzględnieniem nadpróbkowania,
* **loudness range (LU)** — rozpiętość dynamiki głośności.

Wszystko liczy filtr ``loudnorm`` z ffmpeg w trybie pomiaru
(``print_format=json``), którego raport (pola ``input_i``, ``input_tp``,
``input_lra``) parsujemy z stderr.

Korekta ``gain_db`` sprowadza utwór do referencji ReplayGain 2.0 (-18 LUFS)
i jest dodatkowo ograniczana tak, aby po jej zastosowaniu true peak nie
przekroczył -1 dBTP — inaczej podbicie cichego, ale szczytującego materiału
wprowadziłoby przester.

Wymaga ffmpeg na PATH.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass

from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
from mutagen.wave import WAVE

# ---------------------------------------------------------------- stałe

TARGET_LUFS = -18.0     # referencja ReplayGain 2.0
PEAK_CEILING_DBTP = -1.0  # dopuszczalny true peak po korekcie

# Blok JSON drukowany przez loudnorm nie ma zagnieżdżonych klamr, więc
# wystarczy dopasować najbliższą parę {...} zawierającą "input_i".
_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


@dataclass
class Loudness:
    integrated_lufs: float   # zintegrowana głośność (LUFS), np. -7.4
    true_peak_dbtp: float    # true peak (dBTP), np. +0.5
    loudness_range_lu: float  # rozpiętość głośności (LU)
    gain_db: float           # korekta ReplayGain do -18 LUFS (dB)


# ---------------------------------------------------------------- obliczenia

def _compute_gain(integrated_lufs: float, true_peak_dbtp: float) -> float:
    """Korekta do -18 LUFS z ograniczeniem przez sufit true peak.

    ``gain = -18 - integrated``, następnie przycięta tak, aby
    ``true_peak + gain <= -1 dBTP`` (brak przesteru po podbiciu).
    Gdy pomiar się nie powiódł (NaN), zwraca 0.0 — brak korekty.
    """
    if math.isnan(integrated_lufs):
        return 0.0
    gain = TARGET_LUFS - integrated_lufs
    if not math.isnan(true_peak_dbtp):
        gain = min(gain, PEAK_CEILING_DBTP - true_peak_dbtp)
    return gain


def true_peak_linear(l: Loudness) -> float:
    """Liniowy współczynnik szczytu z true peak w dBTP (10**(dBTP/20))."""
    if math.isnan(l.true_peak_dbtp):
        return float("nan")
    return 10.0 ** (l.true_peak_dbtp / 20.0)


# ---------------------------------------------------------------- pomiar

def _run_loudnorm(path: str) -> dict[str, str]:
    """Uruchom loudnorm w trybie pomiaru i sparsuj blok JSON z stderr."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = None
    for match in _JSON_RE.finditer(proc.stderr):
        pass  # interesuje nas ostatni (i jedyny) blok pomiaru
    if match is None:
        raise ValueError("brak raportu loudnorm w wyjściu ffmpeg")
    return json.loads(match.group(0))


def analyze(path: str) -> Loudness:
    """Zmierz głośność utworu i policz korektę ReplayGain.

    Gdy pliku nie da się zdekodować albo ffmpeg nie zwróci raportu,
    zwraca ``Loudness`` z pomiarami NaN i ``gain_db`` = 0.0 (brak korekty),
    dzięki czemu dalsze etapy potoku nie wysypią się na jednym pliku.
    """
    try:
        data = _run_loudnorm(path)
        integrated = float(data["input_i"])
        true_peak = float(data["input_tp"])
        lra = float(data["input_lra"])
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        nan = float("nan")
        return Loudness(nan, nan, nan, 0.0)
    gain = _compute_gain(integrated, true_peak)
    return Loudness(integrated, true_peak, lra, gain)


# ---------------------------------------------------------------- tagi

def write_tags(path: str, l: Loudness) -> None:
    """Zapisz tagi ReplayGain (track gain + track peak).

    * FLAC (Vorbis): ``REPLAYGAIN_TRACK_GAIN`` = "±X.XX dB",
      ``REPLAYGAIN_TRACK_PEAK`` = liniowy szczyt jako tekst.
    * MP3 / WAV (ID3): ramki ``TXXX`` o opisach ``REPLAYGAIN_TRACK_GAIN``
      i ``REPLAYGAIN_TRACK_PEAK`` (konwencja odczytywana m.in. przez
      rekordbox i Mixxx).

    Zapisuje wyłącznie te dwa pola — pozostałe tagi zostają nietknięte.
    Przy nieudanym pomiarze (NaN) nie zapisuje nic.
    """
    if math.isnan(l.gain_db) or math.isnan(l.true_peak_dbtp):
        return
    gain_s = f"{l.gain_db:+.2f} dB"
    peak_s = f"{true_peak_linear(l):.6f}"
    low = path.lower()

    if low.endswith(".flac"):
        audio = FLAC(path)
        audio["REPLAYGAIN_TRACK_GAIN"] = gain_s
        audio["REPLAYGAIN_TRACK_PEAK"] = peak_s
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

    # Usuwamy tylko własne ramki, żeby nie mnożyć duplikatów przy powtórce.
    for desc in ("REPLAYGAIN_TRACK_GAIN", "REPLAYGAIN_TRACK_PEAK"):
        tags.delall(f"TXXX:{desc}")
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=gain_s))
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text=peak_s))

    if low.endswith(".wav"):
        audio.save()
    else:
        tags.save(path)


# ---------------------------------------------------------------- raport

def format_report(l: Loudness) -> str:
    """Jednolinijkowe podsumowanie pomiaru po polsku."""
    if math.isnan(l.integrated_lufs):
        return "głośność: błąd dekodowania — brak pomiaru"
    return (
        f"głośność {l.integrated_lufs:+.1f} LUFS | "
        f"true peak {l.true_peak_dbtp:+.1f} dBTP | "
        f"zakres {l.loudness_range_lu:.1f} LU | "
        f"ReplayGain {l.gain_db:+.2f} dB"
    )
