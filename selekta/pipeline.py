"""Automatyczna weryfikacja pobranego pliku — zamyka pętlę pobierania.

Po tym, jak plik trafi do folderu, przepuszczamy go przez trzy bramki,
każda z istniejącego modułu:

  1. integralność — pełne dekodowanie ffmpeg wykrywa ucięte/uszkodzone
     transfery z Soulseeka (to złapało Heaven & Hell, którego kontrolka
     widmowa w środku utworu nie widziała);
  2. tożsamość — fingerprint vs 30 s preview ze Spotify (to na pewno TEN
     utwór, nie podobnie nazwany);
  3. jakość — analiza widmowa wykrywa fałszywy lossless / słabe źródło.

Gdy plik nie przejdzie, `next_source()` wskazuje kolejny wynik z
Soulseeka od INNEGO użytkownika do ponownej próby.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from . import quality, verify_match
from .slskd_client import SearchHit, SlskdClient
from .spotify import Track


@dataclass
class Check:
    name: str
    passed: bool
    critical: bool
    detail: str


@dataclass
class VerifyResult:
    path: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks if c.critical)

    @property
    def reasons(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]

    def format(self) -> str:
        icon = "✅" if self.ok else "❌"
        lines = [f"{icon} {os.path.basename(self.path)}"]
        for c in self.checks:
            mark = "✓" if c.passed else ("✗" if c.critical else "⚠")
            lines.append(f"    {mark} {c.name}: {c.detail}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# pojedyncze bramki
# --------------------------------------------------------------------------

def integrity(path: str) -> Check:
    """Pełne dekodowanie: liczy błędy ramek i wykrywa ucięcie na końcu."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    errs = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    n = len(errs)
    if n == 0:
        return Check("integralność", True, True, "dekoduje się bez błędów")
    # zlokalizuj czy uszkodzenie jest przy końcu (sygnatura ucięcia)
    dur = _duration(path)
    tail = _errors_in_window(path, max(0.0, dur - 30), 30) if dur else 0
    where = "przy końcu (ucięty transfer)" if tail else "w środku utworu"
    return Check("integralność", False, True,
                 f"{n} błędów dekodowania {where} — pobierz ponownie")


def identity(path: str, track: Track | None) -> Check:
    """Fingerprint pliku vs preview ze Spotify."""
    if track is None or not (track.id or track.preview_url):
        return Check("tożsamość", True, False, "brak utworu odniesienia — pominięto")
    res = verify_match.verify_track(path, track)
    if res is None:
        return Check("tożsamość", True, False, "brak preview do porównania — pominięto")
    passed = res.verdict != "mismatch"
    txt = {"match": "potwierdzony właściwy utwór",
           "uncertain": "niejednoznaczny — sprawdź ręcznie",
           "mismatch": "to NIE ten utwór — odrzuć"}[res.verdict]
    return Check("tożsamość", passed, res.verdict == "mismatch",
                 f"{txt} (podobieństwo {res.score:.2f})")


def sound_quality(path: str) -> Check:
    """Analiza widmowa: fałszywy lossless / słabe źródło."""
    rep = quality.analyze(path)
    passed = rep.grade != "bad"
    return Check("jakość", passed, rep.grade == "bad",
                 f"{rep.cutoff_hz/1000:.1f} kHz — {rep.verdict}")


# --------------------------------------------------------------------------
# orkiestracja
# --------------------------------------------------------------------------

def verify_download(path: str, track: Track | None = None) -> VerifyResult:
    """Przepuść świeżo pobrany plik przez wszystkie bramki."""
    return VerifyResult(path, [
        integrity(path),
        identity(path, track),
        sound_quality(path),
    ])


def next_source(hits: list[SearchHit], tried_users: set[str],
                want_duration_s: float | None = None) -> SearchHit | None:
    """Kolejny najlepszy wynik od użytkownika, którego jeszcze nie próbowano.

    Gdy pobranie zostanie odrzucone przez verify_download, sięgamy po
    inne źródło zamiast wielokrotnie ściągać ten sam uszkodzony plik.
    """
    client = SlskdClient()  # tylko do rankowania (bez sieci)
    ranked = client.rank(hits, want_duration_s)
    for hit in ranked:
        if hit.username not in tried_users:
            return hit
    return None


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _errors_in_window(path: str, start: float, dur: float) -> int:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur),
         "-i", path, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return len([ln for ln in proc.stderr.splitlines() if ln.strip()])
