"""Library health scan — duplicates, covers, corruption, tags, stats.

One read-only pass over a folder (plus one level of subfolders) that
answers: which files are redundant, broken, untagged or coverless?

Duplicate logic reuses matcher.normalize / matcher.mix_signature so the
same notion of "same track, same mix" applies everywhere in selekta:
two files are duplicates when their normalized (artist, base-title) keys
match, their durations agree within DUP_MAX_DELTA_S, and their mix
signatures do not conflict (an Extended Mix is never a duplicate of a
Radio Edit).  Files whose key matches but whose duration drifts further
apart are reported separately as *suspects* — usually a different edit
or a truncated download, worth a human look but not an automatic delete.
"""
from __future__ import annotations

import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from mutagen import File as MutagenFile

from . import covers
from .matcher import mix_signature, normalize
from .quality import QualityReport, analyze

AUDIO_EXT = (".flac", ".mp3", ".wav", ".aiff", ".m4a")

#: keep-priority when copies are otherwise equal (lower = better)
FORMAT_PRIORITY = {".flac": 0, ".wav": 1, ".aiff": 1, ".m4a": 2, ".mp3": 3}

DUP_MAX_DELTA_S = 2.0

GRADE_ICON = {"ok": "✅", "warn": "⚠️", "bad": "❌"}


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------

@dataclass
class FileInfo:
    path: str
    ext: str
    size: int
    duration: float | None = None
    artist: str | None = None
    title: str | None = None
    bitrate: int | None = None
    bits: int | None = None
    mutagen_ok: bool = True


@dataclass
class DuplicateGroup:
    """Files that (probably) carry the same recording."""
    artist: str
    title: str
    files: list[FileInfo]
    keep: FileInfo                 # recommended copy to preserve
    certain: bool                  # True: durations agree ≤ DUP_MAX_DELTA_S


@dataclass
class HealthReport:
    root: str
    files: list[FileInfo]
    duplicates: list[DuplicateGroup]
    suspect_duplicates: list[DuplicateGroup]
    missing_covers: list[str]
    corrupt: list[tuple[str, str]]           # (path, reason)
    missing_tags: list[tuple[str, list[str]]]  # (path, [missing fields])
    format_counts: dict[str, int]
    total_size: int
    total_duration: float
    quality: list[QualityReport] = field(default_factory=list)  # deep only

    @property
    def problem_count(self) -> int:
        redundant = sum(len(g.files) - 1 for g in self.duplicates)
        flawed = sum(1 for q in self.quality if q.grade != "ok")
        return (redundant + len(self.suspect_duplicates)
                + len(self.missing_covers) + len(self.corrupt)
                + len(self.missing_tags) + flawed)


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

def _collect(folder: str) -> list[str]:
    """Wszystkie pliki audio biblioteki, na dowolnej głębokości.

    Jedno źródło prawdy z resztą apki (`matcher.audio_files`) — inaczej
    ekran „Zdrowie" oceniał inny zbiór utworów niż ten, który idzie do
    eksportu, i cicho pomijał pobrania leżące głębiej w podkatalogach.
    """
    from selekta.matcher import audio_files
    return audio_files(folder)


def _first(val) -> str:
    return str(val[0] if isinstance(val, (list, tuple)) else val)


def _read_tags(audio) -> tuple[str | None, str | None]:
    """(artist, title) across tag flavours: Vorbis, ID3 (mp3/wav/aiff), MP4."""
    artist = title = None
    if hasattr(audio, "get"):                       # FLAC / Vorbis comments
        if audio.get("ARTIST"):
            artist = _first(audio.get("ARTIST"))
        if audio.get("TITLE"):
            title = _first(audio.get("TITLE"))
    tags = getattr(audio, "tags", None)
    if tags is not None and hasattr(tags, "get"):
        if artist is None and tags.get("TPE1"):     # ID3
            artist = str(tags["TPE1"])
        if title is None and tags.get("TIT2"):
            title = str(tags["TIT2"])
        if artist is None and tags.get("\xa9ART"):  # MP4 / m4a
            artist = _first(tags["\xa9ART"])
        if title is None and tags.get("\xa9nam"):
            title = _first(tags["\xa9nam"])
    return artist or None, title or None


def _inspect(path: str) -> FileInfo:
    info = FileInfo(path=path, ext=os.path.splitext(path)[1].lower(),
                    size=os.path.getsize(path))
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    if audio is None:
        info.mutagen_ok = False
        return info
    info.duration = getattr(audio.info, "length", None)
    info.bitrate = getattr(audio.info, "bitrate", None)
    info.bits = getattr(audio.info, "bits_per_sample", None)
    try:
        info.artist, info.title = _read_tags(audio)
    except Exception:
        pass
    return info


# --------------------------------------------------------------------------
# duplicates
# --------------------------------------------------------------------------

def _identity(info: FileInfo) -> tuple[str, str]:
    """Displayable (artist, title); tags first, filename as fallback."""
    if info.artist and info.title:
        return info.artist, info.title
    stem = os.path.splitext(os.path.basename(info.path))[0]
    artist, _, title = stem.partition(" - ")
    if not title:
        artist, title = "", stem
    return info.artist or artist, info.title or title


def _dup_key(info: FileInfo):
    artist, title = _identity(info)
    title_tokens = normalize(title)
    sig = mix_signature(title_tokens)
    key = (frozenset(normalize(artist)), frozenset(title_tokens) - sig)
    return (key if key[1] else None), sig


def _mixes_compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    # same convention as matcher.score_file: only two *named* mixes with
    # nothing in common are considered different versions
    return not (a and b and not (a & b))


def _pick_keep(files: list[FileInfo], corrupt: set[str]) -> FileInfo:
    return min(files, key=lambda f: (
        f.path in corrupt,
        FORMAT_PRIORITY.get(f.ext, 9),
        -(f.bits or 0),
        -(f.bitrate or 0),
        -f.size,
    ))


def _components(items: list[int], linked) -> list[list[int]]:
    """Connected components over items given a pairwise predicate."""
    parent = {i: i for i in items}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in items:
        for b in items:
            if a < b and linked(a, b):
                parent[find(a)] = find(b)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in items:
        groups[find(i)].append(i)
    return [g for g in groups.values() if len(g) > 1]


def _find_duplicates(
    files: list[FileInfo], corrupt: set[str],
) -> tuple[list[DuplicateGroup], list[DuplicateGroup]]:
    buckets: dict[tuple, list[tuple[FileInfo, frozenset[str]]]] = defaultdict(list)
    for info in files:
        key, sig = _dup_key(info)
        if key is not None:
            buckets[key].append((info, sig))

    def make_group(members: list[tuple[FileInfo, frozenset[str]]], certain: bool):
        infos = [m[0] for m in members]
        keep = _pick_keep(infos, corrupt)
        infos.sort(key=lambda f: (f is not keep, f.path))  # keep first
        artist, title = _identity(keep)
        return DuplicateGroup(artist, title, infos, keep, certain)

    sure: list[DuplicateGroup] = []
    suspect: list[DuplicateGroup] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        idx = list(range(len(members)))

        def close(a: int, b: int) -> bool:
            (fa, sa), (fb, sb) = members[a], members[b]
            if not _mixes_compatible(sa, sb):
                return False
            if fa.duration is None or fb.duration is None:
                return False
            return abs(fa.duration - fb.duration) <= DUP_MAX_DELTA_S

        def related(a: int, b: int) -> bool:
            return _mixes_compatible(members[a][1], members[b][1])

        strict = _components(idx, close)
        for comp in strict:
            sure.append(make_group([members[i] for i in comp], certain=True))
        claimed = {i for comp in strict for i in comp}
        for comp in _components(idx, related):
            rest = [i for i in comp if i not in claimed]
            if len(comp) > len(rest) > 0 or len(rest) > 1:
                # same key, mixes compatible, but durations drifted apart:
                # different edit or truncated copy — flag for a human
                suspect.append(make_group([members[i] for i in comp],
                                          certain=False))
    by_name = lambda g: (g.artist.lower(), g.title.lower())  # noqa: E731
    return sorted(sure, key=by_name), sorted(suspect, key=by_name)


# --------------------------------------------------------------------------
# corruption
# --------------------------------------------------------------------------

def _ffmpeg_check(path: str) -> str | None:
    """Full decode; returns an error description or None when clean."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"ffmpeg: {type(e).__name__}"
    err = proc.stderr.strip()
    if proc.returncode != 0 or err:
        first = err.splitlines()[0] if err else f"kod wyjścia {proc.returncode}"
        return f"ffmpeg: {first}"
    return None


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def scan(folder: str, deep: bool = False) -> HealthReport:
    """Read-only health scan of folder + its immediate subfolders."""
    root = os.path.abspath(os.path.expanduser(folder))
    files = [_inspect(p) for p in _collect(root)]

    corrupt: list[tuple[str, str]] = []
    for info in files:
        reasons = []
        if not info.mutagen_ok:
            reasons.append("mutagen nie otwiera pliku")
        ffmpeg_err = _ffmpeg_check(info.path)
        if ffmpeg_err:
            reasons.append(ffmpeg_err)
        if reasons:
            corrupt.append((info.path, "; ".join(reasons)))
    corrupt_paths = {p for p, _ in corrupt}

    duplicates, suspects = _find_duplicates(files, corrupt_paths)

    readable = [f.path for f in files if f.mutagen_ok]
    _, missing_covers = covers.audit(readable)

    missing_tags = []
    for info in files:
        if not info.mutagen_ok:
            continue                       # already reported as corrupt
        gaps = [name for name, val in (("ARTIST", info.artist),
                                       ("TITLE", info.title)) if not val]
        if gaps:
            missing_tags.append((info.path, gaps))

    format_counts: dict[str, int] = defaultdict(int)
    for info in files:
        format_counts[info.ext.lstrip(".").upper()] += 1

    quality: list[QualityReport] = []
    if deep:
        for i, info in enumerate(files, 1):
            rel = os.path.relpath(info.path, root)
            print(f"  jakość [{i}/{len(files)}] {rel} ...", flush=True)
            try:
                quality.append(analyze(info.path))
            except Exception as e:
                print(f"    ⚠️ analiza nieudana: {e}")

    return HealthReport(
        root=root,
        files=files,
        duplicates=duplicates,
        suspect_duplicates=suspects,
        missing_covers=missing_covers,
        corrupt=corrupt,
        missing_tags=missing_tags,
        format_counts=dict(sorted(format_counts.items())),
        total_size=sum(f.size for f in files),
        total_duration=sum(f.duration or 0 for f in files),
        quality=quality,
    )


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def _files_pl(n: int) -> str:
    """Polish plural: 1 plik, 2-4 pliki, 5+ plików (22 pliki, 25 plików)."""
    if n == 1:
        return "1 plik"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} pliki"
    return f"{n} plików"


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _describe(info: FileInfo) -> str:
    fmt = info.ext.lstrip(".").upper()
    parts = [fmt]
    if info.bits:
        parts.append(f"{info.bits}-bit")
    if info.bitrate:
        parts.append(f"{round(info.bitrate / 1000)} kbps")
    if info.duration:
        parts.append(_hms(info.duration))
    return ", ".join(parts)


def print_report(report: HealthReport) -> None:
    rel = lambda p: os.path.relpath(p, report.root)  # noqa: E731
    print(f"\nRaport zdrowia biblioteki: {report.root}")
    print(f"{_files_pl(len(report.files))}, "
          f"{report.total_size / 1e9:.2f} GB, {_hms(report.total_duration)}")

    print("\n— Formaty —")
    for fmt, n in report.format_counts.items():
        print(f"  {fmt}: {n}")

    print("\n— Duplikaty —")
    if not report.duplicates and not report.suspect_duplicates:
        print("  ✅ nie znaleziono duplikatów")
    for g in report.duplicates:
        print(f"  ❌ {g.artist} — {g.title}  ({len(g.files)} kopii)")
        for f in g.files:
            mark = "→ zachowaj" if f is g.keep else "  do usunięcia"
            print(f"     {mark}: {rel(f.path)}  [{_describe(f)}]")
    for g in report.suspect_duplicates:
        print(f"  ⚠️ podejrzenie: {g.artist} — {g.title} "
              f"(ta sama nazwa, ale czas trwania różni się > {DUP_MAX_DELTA_S:g} s "
              f"— inna edycja albo ucięta kopia; sprawdź ręcznie)")
        for f in g.files:
            mark = "→ lepsza kopia" if f is g.keep else "               "
            print(f"     {mark}: {rel(f.path)}  [{_describe(f)}]")

    print("\n— Okładki —")
    if not report.missing_covers:
        print("  ✅ wszystkie pliki mają okładkę")
    else:
        print(f"  ⚠️ {_files_pl(len(report.missing_covers))} bez okładki:")
        for p in report.missing_covers:
            print(f"     ✗ {rel(p)}")

    print("\n— Uszkodzone pliki —")
    if not report.corrupt:
        print("  ✅ wszystkie pliki dekodują się bez błędów")
    else:
        for p, reason in report.corrupt:
            print(f"  ❌ {rel(p)}")
            print(f"     {reason}")

    print("\n— Tagi —")
    if not report.missing_tags:
        print("  ✅ wszystkie pliki mają ARTIST i TITLE")
    else:
        for p, gaps in report.missing_tags:
            print(f"  ⚠️ {rel(p)}: brak {', '.join(gaps)}")

    if report.quality:
        print("\n— Jakość (deep) —")
        counts = defaultdict(int)
        for q in report.quality:
            counts[q.grade] += 1
        print("  " + "   ".join(
            f"{GRADE_ICON[g]} {g}: {counts[g]}" for g in ("ok", "warn", "bad")))
        for q in report.quality:
            if q.grade != "ok":
                print(f"  {GRADE_ICON[q.grade]} {rel(q.path)}")
                print(f"     cutoff {q.cutoff_hz / 1000:.1f} kHz — {q.verdict}")

    n = report.problem_count
    if n == 0:
        print("\nPodsumowanie: biblioteka zdrowa ✅")
    else:
        few = n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
        word = "problem" if n == 1 else ("problemy" if few else "problemów")
        print(f"\nPodsumowanie: {n} {word} do naprawy — szczegóły wyżej.")
