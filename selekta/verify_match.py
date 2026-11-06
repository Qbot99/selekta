"""Acoustic verification: is this file really that track?

Spotify exposes a ~30 s MP3 preview for nearly every track. We decode
both the preview and the local file, reduce each to an onset-strength
envelope (spectral flux — robust across codecs, bitrates and loudness),
and slide the preview over the track computing normalized correlation.
A high peak means the preview's audio literally occurs inside the file:
the download is the right recording, regardless of what it is named.

Different edits of the same track (radio vs extended) still share their
audio, so they match; a similarly named but different track does not.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np
import requests

from . import matcher
from .spotify import UA, Track
from .narzedzia import ffmpeg_path, ffprobe_path

SR = 11025          # analysis sample rate — plenty for onsets, fast to decode
N_FFT = 512
HOP = 256           # ~43 envelope frames per second
MATCH_THRESHOLD = 0.50
REJECT_THRESHOLD = 0.30


@dataclass
class MatchResult:
    score: float          # peak normalized correlation, 0..1
    offset_s: float       # where in the file the preview aligns
    verdict: str          # "match" | "uncertain" | "mismatch"
    note: str = ""


def _decode(source: str | bytes, max_s: float | None = None) -> np.ndarray:
    cmd = [ffmpeg_path(), "-v", "error"]
    if isinstance(source, bytes):
        cmd += ["-i", "pipe:0"]
    else:
        cmd += ["-i", source]
    if max_s:
        cmd += ["-t", str(max_s)]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    out = subprocess.run(
        cmd, input=source if isinstance(source, bytes) else None, capture_output=True
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


N_BANDS = 16


def _band_envelopes(x: np.ndarray) -> np.ndarray:
    """Per-band onset strength, shape (frames, N_BANDS).

    A single summed envelope is dominated by the 4/4 kick and correlates
    with *any* techno track at the same BPM; the band-resolved pattern
    (where in the spectrum each onset happens) is specific to the actual
    melody and sound design of the recording.
    """
    if len(x) < N_FFT * 4:
        return np.zeros((0, N_BANDS))
    n_frames = (len(x) - N_FFT) // HOP
    window = np.hanning(N_FFT)
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    mags = np.abs(np.fft.rfft(x[idx] * window, axis=1))
    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    edges = np.geomspace(100, 5000, N_BANDS + 1)
    bands = np.stack(
        [
            mags[:, (freqs >= lo) & (freqs < hi)].sum(axis=1)
            for lo, hi in zip(edges[:-1], edges[1:])
        ],
        axis=1,
    )
    flux = np.maximum(np.diff(np.log1p(1000 * bands), axis=0), 0)
    # per-band standardization: without it the kick/bass bands carry
    # most of the energy and two different tracks built on the same
    # drum loop cross-match; equal-weighted bands let melody vote too
    flux = flux / (flux.std(axis=0, keepdims=True) + 1e-9)
    return flux


def _ncc_curve(track_b: np.ndarray, prev_b: np.ndarray) -> np.ndarray:
    """Normalized correlation of the multi-band preview pattern at every
    possible alignment along the track. Empty array when too short."""
    n, m = len(track_b), len(prev_b)
    if n < m or m < 43:      # need at least ~1 s of preview envelope
        return np.zeros(0)
    p = prev_b - prev_b.mean(axis=0)
    p_norm = np.sqrt((p**2).sum()) + 1e-9

    dots = np.zeros(n - m + 1)
    w_sum = np.zeros((n - m + 1, track_b.shape[1]))
    w_sum2_total = np.zeros(n - m + 1)
    for b in range(track_b.shape[1]):
        col = track_b[:, b]
        dots += np.correlate(col, p[:, b], mode="valid")
        csum = np.cumsum(np.concatenate(([0.0], col)))
        csum2 = np.cumsum(np.concatenate(([0.0], col**2)))
        w_sum[:, b] = csum[m:] - csum[:-m]
        w_sum2_total += csum2[m:] - csum2[:-m]
    # window variance across all bands jointly
    w_var = np.maximum(w_sum2_total - (w_sum**2).sum(axis=1) / m, 1e-9)
    return dots / (np.sqrt(w_var) * p_norm)


def preview_bytes(track: Track) -> bytes | None:
    if not track.preview_url:
        return None
    r = requests.get(track.preview_url, headers=UA, timeout=20)
    return r.content if r.ok and len(r.content) > 10_000 else None


def verify(path: str, preview: bytes) -> MatchResult:
    """Alignment-consistent scoring: the preview is split into three
    segments and their correlation curves are summed at a SHARED
    alignment (segment i evaluated one chunk further along the file).
    The same recording peaks jointly at one offset; a merely similar
    track (same artist, same drum samples) peaks at unrelated offsets,
    so no shared alignment scores high. Loop-heavy club tracks stay
    matchable because repeats help, not hurt, a joint alignment."""
    track_env = _band_envelopes(_decode(path))
    prev_env = _band_envelopes(_decode(preview))
    m = len(prev_env)
    fps = SR / HOP
    chunk = m // 3
    if chunk < fps * 2:      # preview too short to chunk — single pass
        curve = _ncc_curve(track_env, prev_env)
        if len(curve) == 0:
            return MatchResult(0.0, 0.0, "mismatch")
        best = int(np.argmax(curve))
        score = float(curve[best])
    else:
        curves = [
            _ncc_curve(track_env, prev_env[i * chunk : (i + 1) * chunk])
            for i in range(3)
        ]
        valid = len(track_env) - 3 * chunk + 1
        if valid < 1 or any(len(c) == 0 for c in curves):
            return MatchResult(0.0, 0.0, "mismatch")
        combined = (
            curves[0][:valid]
            + curves[1][chunk : chunk + valid]
            + curves[2][2 * chunk : 2 * chunk + valid]
        ) / 3
        best = int(np.argmax(combined))
        score = float(combined[best])

    offset = best / fps
    if score >= MATCH_THRESHOLD:
        verdict = "match"
    elif score <= REJECT_THRESHOLD:
        verdict = "mismatch"
    else:
        verdict = "uncertain"

    # club releases by one artist often share literal intro/outro beat
    # sections (DJ-friendly design), so a match that lands only at the
    # very edge of the file proves shared tooling, not the same track —
    # demote it for a human ear to settle
    note = ""
    duration = len(track_env) / fps
    center = offset + (m / 2) / fps
    if verdict == "match" and duration > 60 and not (
        0.12 * duration < center < 0.88 * duration
    ):
        verdict = "uncertain"
        note = "dopasowanie tylko w intrze/outrze — możliwy wspólny loop artysty"
    return MatchResult(round(score, 3), round(offset, 1), verdict, note)


_RANGA = {"mismatch": 0, "uncertain": 1, "match": 2}


def verify_track(path: str, track: Track) -> MatchResult | None:
    """Plik vs 30-sekundowa próbka; None, gdy żadne źródło nie dało próbki.

    Gdy próbka ze Spotify NIE potwierdza utworu, pytamy drugie, niezależne
    źródło (iTunes). Przegląd 0.4.2: „Dancing Queen" dostało od próbki
    Spotify 0,25 („to NIE ten utwór — odrzuć"), a ten sam plik z próbką
    z iTunes 0,79. Próbka bywa wycięta z innego wydania (inny master,
    wersja singlowa), więc jedno źródło nie może samo skazać właściwego
    pliku. Rozstrzyga lepszy werdykt; w nocie zostają oba wyniki.
    """
    try:
        data = preview_bytes(track)
    except requests.RequestException:
        data = None
    res = verify(path, data) if data else None
    if res is not None and res.verdict == "match":
        return res
    druga = None
    if track.artist or track.title:
        try:
            druga = verify_by_name(path, track.artist, track.title)
        except Exception:  # noqa: BLE001 — drugie źródło jest tylko pomocą
            druga = None
    if druga is None:
        return res
    res2, opis = druga
    if res is None:
        res2.note = "; ".join(x for x in (res2.note, f"próbka z iTunes: {opis}") if x)
        return res2
    if _RANGA[res2.verdict] > _RANGA[res.verdict]:
        note = (f"Spotify {res.score:.2f}, iTunes {res2.score:.2f} — drugie źródło "
                f"potwierdza ({opis})")
        if res2.note:
            note += f"; {res2.note}"
        return MatchResult(res2.score, res2.offset_s, res2.verdict, note)
    res.note = "; ".join(x for x in (res.note, f"iTunes też nie potwierdza ({res2.score:.2f})") if x)
    return res


def preview_itunes(artist: str, title: str) -> tuple[bytes, str] | None:
    """30-sekundowa próbka utworu z iTunes — (dane, opis znaleziska).

    Spotify wymaga klucza i coraz częściej nie podaje `preview_url`;
    iTunes oddaje próbkę bez uwierzytelniania i jest już używany w apce
    do okładek. Dla weryfikacji wystarczy: porównujemy przebieg widmowy,
    nie jakość.
    """
    from urllib.parse import quote_plus
    term = quote_plus(f"{artist} {title}".strip())
    if not term:
        return None
    try:
        r = requests.get(
            f"https://itunes.apple.com/search?term={term}&entity=song&limit=5",
            headers=UA, timeout=15)
        results = r.json().get("results", [])
    except (requests.RequestException, ValueError):
        return None

    # Próbka cudzego utworu skazałaby dobry plik, więc tożsamość sprawdzamy
    # tym samym porównaniem co dopasowanie do biblioteki. Dawniej wystarczał
    # fragment tytułu bez wykonawcy: „b" pasowało do „(Key Ab Ver.)".
    chce = Track(id="", artist=artist or "", title=title or "")
    oceny = [(matcher.verdict_for_name(
        chce, f"{i.get('artistName', '')} - {i.get('trackName', '')}.m4a", None), i)
        for i in results]
    # ta sama wersja przed inną: próbka remiksu gorzej potwierdzi oryginał
    for _werdykt, item in sorted((o for o in oceny if o[0]), key=lambda o: -o[0]):
        url = item.get("previewUrl")
        if not url:
            continue
        try:
            audio = requests.get(url, headers=UA, timeout=25)
        except requests.RequestException:
            continue
        if audio.ok and len(audio.content) > 10_000:
            opis = f"{item.get('artistName','')} — {item.get('trackName','')}"
            return audio.content, opis
    return None


def verify_by_name(path: str, artist: str, title: str) -> tuple[MatchResult, str] | None:
    """Sprawdź plik odciskiem akustycznym, mając tylko artystę i tytuł.

    Zwraca (wynik, opis źródła) albo None, gdy nie udało się pobrać próbki
    — brak próbki to NIE jest dowód niezgodności i nie wolno go tak
    traktować.
    """
    podglad = preview_itunes(artist, title)
    if not podglad:
        return None
    dane, opis = podglad
    try:
        return verify(path, dane), opis
    except Exception:                          # noqa: BLE001
        return None
