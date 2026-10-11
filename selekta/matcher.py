"""Match Spotify tracks to local audio files.

Scoring combines token overlap (filename + existing tags), duration
agreement, and mix-version awareness (an Extended Mix must not match
a Radio Edit silently).
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

from mutagen import File as MutagenFile

from .spotify import Track

AUDIO_EXT = (".flac", ".mp3", ".wav", ".aiff", ".m4a", ".ogg")

MIX_WORDS = {
    "extended", "radio", "club", "dub", "vip", "remix", "rmx", "bootleg",
    "edit", "rework", "instrumental", "acapella",
}
NOISE = {
    "original", "mix", "feat", "ft", "featuring", "the", "and", "www", "pl",
    "com", "flac", "mp3", "wav",
}


def normalize(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in NOISE]


def mix_signature(tokens: list[str]) -> frozenset[str]:
    return frozenset(t for t in tokens if t in MIX_WORDS)


@dataclass
class Candidate:
    path: str
    score: float
    duration_delta: float | None
    reason: str
    identity: float = 0.0       # zgodność artysty+tytułu BEZ słów o wersji
    same_version: bool = True   # czy wersja miksu też się zgadza


def _file_tokens(path: str) -> tuple[list[str], float | None]:
    tokens = normalize(os.path.splitext(os.path.basename(path))[0])
    duration = None
    try:
        audio = MutagenFile(path)
        if audio is not None:
            duration = getattr(audio.info, "length", None)
            for key in ("TITLE", "ARTIST"):
                val = audio.get(key) if hasattr(audio, "get") else None
                if val:
                    tokens += normalize(str(val[0] if isinstance(val, list) else val))
            if getattr(audio, "tags", None) and hasattr(audio.tags, "get"):
                for key in ("TIT2", "TPE1"):
                    if audio.tags.get(key):
                        tokens += normalize(str(audio.tags[key]))
    except Exception:
        pass
    return tokens, duration


def _score_tokens(track: Track, want: list[str], have: list[str],
                  duration: float | None, path: str) -> Candidate:
    overlap = len(set(want) & set(have)) / len(set(want))
    score = overlap

    # Tożsamość liczona BEZ słów opisujących wersję ("extended", "radio"...).
    # Dzięki temu „Flashback (Radio Edit)" rozpoznaje posiadany
    # „Flashback (Extended Mix)" jako TEN SAM utwór w innej wersji,
    # zamiast raportować go jako brakujący.
    core_want = {t for t in want if t not in MIX_WORDS}
    core_have = {t for t in have if t not in MIX_WORDS}
    identity = (len(core_want & core_have) / len(core_want)) if core_want else 0.0

    delta = None
    if track.duration_s and duration:
        delta = abs(duration - track.duration_s)
        if delta <= 3:
            score += 0.25          # same edit, near-certain confirmation
        elif delta > 45:
            score -= 0.15          # probably a different mix/version

    want_mix, have_mix = mix_signature(want), mix_signature(have)
    if want_mix == have_mix:
        score += 0.1
    elif want_mix and have_mix and not (want_mix & have_mix):
        score -= 0.3               # e.g. asked for remix, file is radio edit

    return Candidate(path, round(score, 3), delta, f"overlap={overlap:.2f}",
                     identity=round(identity, 3),
                     same_version=(want_mix == have_mix))


def score_file(track: Track, path: str) -> Candidate:
    want = normalize(track.artist) + normalize(track.title)
    have, duration = _file_tokens(path)
    if not want or not have:
        return Candidate(path, 0.0, None, "no tokens")
    return _score_tokens(track, want, have, duration, path)


SKIP_DIRS = {"_selekta_kosz"}


def format_rank(path: str) -> int:
    """Im mniej, tym lepiej — kolejność przydatności dla DJ-a.

    Rozstrzyga remisy, gdy ten sam utwór leży w bibliotece w kilku
    formatach. FLAC przed WAV, bo niesie tagi i okładkę; bezstratne
    przed stratnym.
    """
    ext = os.path.splitext(path)[1].lower()
    return {".flac": 0, ".aiff": 1, ".aif": 1, ".wav": 2,
            ".m4a": 3, ".mp3": 4}.get(ext, 5)


def audio_files(folder: str, kopie_w_setach: bool = False) -> list[str]:
    """Utwory biblioteki — RÓWNIEŻ w podfolderach, ale bez kopii z setów.

    Soulseek i Nicotine+ zapisują pobrania do katalogów albumów
    (``downloads/Nazwa albumu/01 utwor.flac``), więc płaskie listowanie
    gubiło większość świeżo pobranych utworów: nie było ich ani w
    bibliotece, ani w dopasowaniu, ani w eksporcie. Pomijamy katalogi
    ukryte i kosz.

    Foldery setów (katalog z ``_selekta.json``) trzymają KOPIE utworów
    z biblioteki. Liczone osobno zawyżały bibliotekę (277 plików przy
    ~79 utworach), dublowały listę i kolejność, a „Usuń duplikaty” chciało
    je wyrzucić do kosza. Każdy utwór występuje tu raz; utwór, który leży
    tylko w setach, reprezentuje jedna jego kopia (szczegóły: ``uklad``).
    ``kopie_w_setach=True`` zwraca wszystkie pliki, łącznie z kopiami.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"nie ma folderu: {folder}")
    from .uklad import wczytaj
    u = wczytaj(folder)
    return list(u.wszystkie if kopie_w_setach else u.utwory)


def resolve_in_library(folder: str, name: str) -> str | None:
    """Znajdź plik po samej nazwie — gdziekolwiek w bibliotece leży."""
    if os.path.isabs(name) and os.path.isfile(name):
        return name
    base = os.path.basename(name)
    direct = os.path.join(folder, base)
    if os.path.isfile(direct):
        return direct
    for p in audio_files(folder):
        if os.path.basename(p) == base:
            return p
    for p in audio_files(folder, kopie_w_setach=True):   # kopia w secie
        if os.path.basename(p) == base:
            return p
    return None


def best_match(track: Track, folder: str, threshold: float = 0.6) -> Candidate | None:
    files = audio_files(folder)
    candidates = sorted(
        (score_file(track, p) for p in files),
        key=lambda c: (c.score, -format_rank(c.path), c.path), reverse=True
    )
    if candidates and candidates[0].score >= threshold:
        return candidates[0]
    return None


def index_paths(paths: list[str]) -> list[tuple[str, list[str], float | None]]:
    """Indeks ograniczony do podanych plików — do sprawdzania, czy utwór
    JUŻ jest na playliście, bez przeszukiwania całej biblioteki."""
    out = []
    for p in paths:
        have, dur = _file_tokens(p)
        out.append((p, have, dur))
    return out


def library_index(folder: str) -> list[tuple[str, list[str], float | None]]:
    """Precompute (path, tokens, duration) once so a whole playlist can be
    scored without re-reading every file's tags per track."""
    out = []
    for p in audio_files(folder):
        have, dur = _file_tokens(p)
        out.append((p, have, dur))
    return out


def _pick_key(c: "Candidate") -> tuple:
    """Klucz wyboru kandydata. Przy remisie wyniku decyduje format,
    a na końcu ścieżka — żeby wybór był powtarzalny, a nie zależny od
    kolejności listowania katalogów."""
    return (c.identity, c.score, -format_rank(c.path), c.path)


def classify_track(track: Track, index) -> Candidate | None:
    """Najlepszy kandydat z gotowego indeksu biblioteki (bez progu).

    Wyboru dokonujemy po TOŻSAMOŚCI (artysta + tytuł bez słów o wersji),
    a dopiero potem po wyniku. Inaczej kara za inną wersję miksu spycha
    właściwy plik poniżej przypadkowego utworu — „Flashback (Radio Edit)"
    dopasowywał się do zupełnie obcego kawałka zamiast do posiadanego
    „Flashback (Extended Mix)".
    """
    want = normalize(track.artist) + normalize(track.title)
    if not want:
        return None
    best = None
    for path, have, duration in index:
        if not have:
            continue
        c = _score_tokens(track, want, have, duration, path)
        if best is None or _pick_key(c) > _pick_key(best):
            best = c
    return best
