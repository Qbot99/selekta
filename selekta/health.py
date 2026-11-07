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
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from mutagen import File as MutagenFile

from . import covers
from .matcher import MIX_WORDS, mix_signature, normalize
from .quality import QualityReport, analyze
from .narzedzia import ffmpeg_path, ffprobe_path

AUDIO_EXT = (".flac", ".mp3", ".wav", ".aiff", ".m4a")

#: keep-priority when copies are otherwise equal (lower = better)
FORMAT_PRIORITY = {".flac": 0, ".wav": 1, ".aiff": 1, ".m4a": 2, ".mp3": 3}

DUP_MAX_DELTA_S = 2.0

#: o ile zdekodowany dźwięk może być krótszy od długości z nagłówka, zanim
#: uznamy plik za ucięty (ta sama tolerancja co przy duplikatach)
UCIECIE_TOLERANCJA_S = 2.0

#: wersja wyniku dekodowania w cache — podbić przy zmianie sposobu oceny
_WERSJA_DEKODU = 2

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
    w_secie: bool = False          # plik leży w folderze setu (kopia, nietykalna)
    sety: list[str] = field(default_factory=list)   # sety, w których utwór jest użyty


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


def _wszystkie(val) -> str:
    """Wszystkie wartości pola naraz: ['Maddix', 'Feles'] → 'Maddix, Feles'.

    Tag ARTIST bywa wielowartościowy (FLAC, MP4, ID3v2.4). Branie tylko
    pierwszej wartości gubiło gościa z listy, z wyszukiwania i z okładek.
    """
    if isinstance(val, (list, tuple)):
        czesci = [str(v).strip() for v in val if str(v).strip()]
        return ", ".join(dict.fromkeys(czesci))
    tekst = getattr(val, "text", None)            # ramka ID3
    if tekst is not None:
        return _wszystkie(list(tekst))
    return str(val).strip()


def _read_tags(audio) -> tuple[str | None, str | None]:
    """(artist, title) across tag flavours: Vorbis, ID3 (mp3/wav/aiff), MP4."""
    artist = title = None
    tags = getattr(audio, "tags", None)
    if hasattr(audio, "get") and not hasattr(tags, "getall"):  # Vorbis / MP4
        if audio.get("ARTIST"):
            artist = _wszystkie(audio.get("ARTIST"))
        if audio.get("TITLE"):
            title = _wszystkie(audio.get("TITLE"))
    if tags is not None and hasattr(tags, "get"):
        def pole(klucz):
            # Vorbis (FLAC/OGG) rzuca ValueError na klucz spoza ASCII („©nam”):
            # plik z samym artystą wychodził przez to jako zupełnie bez tagów
            try:
                return tags.get(klucz)
            except (ValueError, KeyError):
                return None
        if artist is None and pole("TPE1"):         # ID3
            artist = _wszystkie(pole("TPE1"))
        if title is None and pole("TIT2"):
            title = _wszystkie(pole("TIT2"))
        if artist is None and pole("\xa9ART"):      # MP4 / m4a
            artist = _wszystkie(pole("\xa9ART"))
        if title is None and pole("\xa9nam"):
            title = _wszystkie(pole("\xa9nam"))
    return artist or None, title or None


def czytaj_tagi(path: str) -> tuple[str, str]:
    """Artysta i tytuł z tagów pliku (puste, gdy brak albo plik nieczytelny).

    Jedno miejsce dla wszystkich formatów: FLAC/OGG (Vorbis), MP3/WAV/AIFF
    (ID3) i M4A (MP4: ©ART/©nam). Wcześniej lista utworów czytała tylko
    Vorbis i ID3, więc każdy plik M4A był „?” bez tytułu.
    """
    try:
        audio = MutagenFile(path)
        if audio is None:
            return "", ""
        artist, title = _read_tags(audio)
    except Exception:                              # noqa: BLE001
        return "", ""
    return artist or "", title or ""


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


def klucz_utworu(path: str, artist: str | None,
                 title: str | None) -> tuple[frozenset, frozenset] | None:
    """(rdzeń, wersja) — JEDNA reguła „to ten sam utwór w tej samej wersji”.

    Używają jej Zdrowie, „Usuń duplikaty” i Porządki (``decyzje``). Wcześniej
    każdy ekran miał swoją: Zdrowie uznawało pusty dopisek za zgodny z
    każdym („Original Mix” łączył Extended z Radio Edit w jedną grupę
    i Radio Edit szedł do kosza), a Porządki nie.

    * rdzeń = słowa artysty i tytułu bez słów o wersji; z tagów, a z nazwy
      pliku (bez numeru ścieżki i śmieci) tylko wtedy, gdy tagów brak;
    * wersja = słowa o miksie (extended, radio, edit, remix…) z tytułu
      w tagach ORAZ z nazwy pliku — dopisek „(Club Mix)” bywa tylko
      w nazwie. Dwa pliki to ta sama wersja tylko przy RÓWNYCH wersjach
      (równość jest przechodnia, więc nie powstają łańcuchy).
    """
    from .tagfix import clean_stem
    stem = os.path.splitext(os.path.basename(path))[0]
    stem_czysty = clean_stem(stem) or stem
    if artist and title:
        tokeny = normalize(artist) + normalize(title)
    else:
        tokeny = normalize(stem_czysty)
    rdzen = frozenset(t for t in tokeny if t not in MIX_WORDS)
    if not rdzen:
        return None
    wersja = mix_signature(tokeny) | mix_signature(normalize(stem))
    return rdzen, frozenset(wersja)


def _dup_key(info: FileInfo):
    return klucz_utworu(info.path, info.artist, info.title)


_KOPIA_W_NAZWIE = re.compile(r"(\s\(\d+\)|_\d{6,})$")


def nazwa_kopii(path: str) -> bool:
    """Czy nazwa wygląda na kopię: „… (1).flac”, „…_639242269261972010.flac”."""
    return bool(_KOPIA_W_NAZWIE.search(os.path.splitext(os.path.basename(path))[0]))


def _pick_keep(files: list[FileInfo], corrupt: set[str]) -> FileInfo:
    return min(files, key=lambda f: (
        f.path in corrupt,
        not f.mutagen_ok,
        FORMAT_PRIORITY.get(f.ext, 9),
        -(f.bits or 0),
        -(f.bitrate or 0),
        nazwa_kopii(f.path),          # przy remisie czysta nazwa, nie „(1)”
        f.path,
    ))


def _po_czasie(members: list[FileInfo]) -> list[list[FileInfo]]:
    """Podziel pliki na kubełki o czasie trwania zgodnym co do DUP_MAX_DELTA_S.

    Każdy kubełek mierzymy względem jego pierwszego pliku, więc nie powstają
    łańcuchy (A≈B, B≈C, ale A≠C). Pliki bez czasu lądują osobno.
    """
    kubelki: list[list[FileInfo]] = []
    for f in sorted(members, key=lambda x: (x.duration is None, x.duration or 0, x.path)):
        if f.duration is not None:
            for k in kubelki:
                if (k[0].duration is not None
                        and abs(k[0].duration - f.duration) <= DUP_MAX_DELTA_S):
                    k.append(f)
                    break
            else:
                kubelki.append([f])
        else:
            kubelki.append([f])
    return kubelki


def _find_duplicates(
    files: list[FileInfo], corrupt: set[str],
) -> tuple[list[DuplicateGroup], list[DuplicateGroup]]:
    """Grupy duplikatów wśród plików biblioteki.

    Kopie w folderach setów NIE biorą udziału: to nie są zbędne pliki, tylko
    zawartość setów (i ścieżki w XML-ach rekordboxa). Gdyby trafiły do grupy,
    „Usuń duplikaty” rozbiłoby sety.
    """
    buckets: dict[tuple, list[FileInfo]] = defaultdict(list)
    for info in files:
        if info.w_secie:
            continue
        key = _dup_key(info)
        if key is not None:
            buckets[key].append(info)

    def make_group(infos: list[FileInfo], certain: bool):
        keep = _pick_keep(infos, corrupt)
        infos = sorted(infos, key=lambda f: (f is not keep, f.path))  # keep first
        artist, title = _identity(keep)
        return DuplicateGroup(artist, title, infos, keep, certain)

    sure: list[DuplicateGroup] = []
    suspect: list[DuplicateGroup] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        kubelki = _po_czasie(members)
        for k in kubelki:
            if len(k) > 1 and all(f.duration is not None for f in k):
                sure.append(make_group(k, certain=True))
        if len(kubelki) > 1:
            # ta sama nazwa i wersja, ale czasy się rozjechały: inna edycja
            # albo ucięta kopia — do obejrzenia przez człowieka
            suspect.append(make_group(members, certain=False))
    by_name = lambda g: (g.artist.lower(), g.title.lower())  # noqa: E731
    return sorted(sure, key=by_name), sorted(suspect, key=by_name)


# --------------------------------------------------------------------------
# corruption
# --------------------------------------------------------------------------

def _mm_ss(sekundy: float) -> str:
    s = int(round(sekundy or 0))
    return f"{s // 60}:{s % 60:02d}"


def _dekoduj(path: str) -> tuple[list[str], float | None, str | None]:
    """Pełne dekodowanie ścieżki dźwiękowej ffmpeg-iem.

    Zwraca (linie błędów, zdekodowany czas w s, błąd uruchomienia). Czas
    bierzemy z ``-progress`` — to, ile dźwięku NAPRAWDĘ dało się odczytać.
    """
    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-nostdin", "-v", "error", "-i", path,
             "-map", "0:a:0", "-f", "null", "-progress", "pipe:1", "-nostats", "-"],
            capture_output=True, text=True, timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return [], None, f"ffmpeg: {type(e).__name__}"
    czas = None
    for linia in proc.stdout.splitlines():
        if linia.startswith("out_time_us="):
            try:
                czas = int(linia.split("=", 1)[1]) / 1_000_000
            except ValueError:
                pass
    bledy = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    if proc.returncode != 0 and not bledy:
        bledy = [f"kod wyjścia {proc.returncode}"]
    return bledy, czas, None


def _naglowek_mp3(path: str) -> bool:
    """Czy MP3 ma nagłówek Xing/Info/VBRI z liczbą ramek.

    Tylko wtedy długość z nagłówka jest DEKLARACJĄ, z którą można porównać
    dźwięk. Bez nagłówka mutagen zgaduje czas z rozmiaru pliku — dla VBR
    potrafi się pomylić dwukrotnie i dałby fałszywe „ucięty”.
    """
    try:
        from mutagen.mp3 import MP3
        info = MP3(path).info
        off = getattr(info, "frame_offset", None)
        if off is None:
            return False
        with open(path, "rb") as fh:
            fh.seek(off)
            ramka = fh.read(256)
        return any(m in ramka for m in (b"Xing", b"Info", b"VBRI"))
    except Exception:                              # noqa: BLE001
        return False


def _koniec_dzwieku_mp3(path: str, info) -> float | None:
    """Szacowany czas dźwięku, który FIZYCZNIE jest w pliku MP3 (bez dekodowania).

    Nagłówek Xing/VBRI podaje liczbę ramek i bajtów całego strumienia. Gdy
    pobieranie się urwie, nagłówek nadal obiecuje pełną długość, ale bajtów
    jest mniej — mutagen pokazuje wtedy 40 s, a dźwięku jest 18,7 s.
    """
    try:
        off = getattr(info, "frame_offset", None)
        bitrate = getattr(info, "bitrate", 0) or 0
        if off is None or bitrate <= 0:
            return None
        size = os.path.getsize(path)
        koniec = size
        with open(path, "rb") as fh:
            if size > 128:
                fh.seek(size - 128)
                if fh.read(3) == b"TAG":          # ID3v1
                    koniec -= 128
            if koniec > 32:
                fh.seek(koniec - 32)
                stopka = fh.read(32)
                if stopka[:8] == b"APETAGEX":     # APEv2 na końcu
                    koniec -= int.from_bytes(stopka[12:16], "little") + 32
        return max(0.0, (koniec - off) * 8 / bitrate)
    except (OSError, ValueError):
        return None


def uciecie_mp3(path: str) -> tuple[float, float] | None:
    """(czas z nagłówka, czas faktycznie w pliku), gdy MP3 jest ucięty; inaczej None.

    Szybka kontrola bez dekodowania (odczyt nagłówka i rozmiaru) — nadaje się
    do listy utworów. Pełną pewność daje ``integralnosc`` (dekodowanie).
    """
    if not path.lower().endswith(".mp3") or not _naglowek_mp3(path):
        return None
    try:
        from mutagen.mp3 import MP3
        info = MP3(path).info
    except Exception:                              # noqa: BLE001
        return None
    deklarowany = getattr(info, "length", 0) or 0
    realny = _koniec_dzwieku_mp3(path, info)
    if realny is None or deklarowany <= 0:
        return None
    if deklarowany - realny > UCIECIE_TOLERANCJA_S:
        return deklarowany, realny
    return None


def _ocen(path: str, deklarowany: float | None, ufam_deklaracji: bool) -> dict:
    bledy, czas, awaria = _dekoduj(path)
    wynik = {"wersja": _WERSJA_DEKODU, "bledow": len(bledy), "zdekodowano_s": czas,
             "deklarowano_s": deklarowany, "uciety": False, "ok": True, "opis": ""}
    if awaria:
        wynik.update(ok=False, opis=awaria)
        return wynik
    uciety = (ufam_deklaracji and deklarowany and czas is not None
              and deklarowany - czas > UCIECIE_TOLERANCJA_S)
    if uciety:
        wynik.update(ok=False, uciety=True,
                     opis=(f"ucięty — gra tylko {_mm_ss(czas)} z {_mm_ss(deklarowany)} "
                           f"(przerwane pobieranie)"))
    elif bledy:
        pierwszy = bledy[0][:120]
        if czas and deklarowany and abs(deklarowany - czas) <= UCIECIE_TOLERANCJA_S:
            opis = (f"{len(bledy)} uszkodzonych miejsc w dźwięku — gra do końca, "
                    f"ale możliwe trzaski ({pierwszy})")
        else:
            opis = f"błędy dekodowania ({len(bledy)}): {pierwszy}"
        wynik.update(ok=False, opis=opis)
    else:
        wynik["opis"] = "dekoduje się w całości, bez błędów"
    return wynik


def integralnosc(path: str, uzyj_cache: bool = True) -> dict:
    """Czy plik da się odczytać do końca — i czy „koniec” to naprawdę koniec.

    Wspólna funkcja dla Zdrowia i (docelowo) bramki pobrań w ``pipeline``:
    pełne dekodowanie ffmpeg + porównanie zdekodowanej długości z długością
    zadeklarowaną w nagłówku (Xing/VBRI w MP3, STREAMINFO w FLAC, nagłówek
    WAV). Sam brak komunikatów ffmpeg nie wystarcza: MP3 ucięty na granicy
    ramki dekoduje się „bez błędów”, tylko krócej.

    Zwraca słownik: ok, uciety, opis (po polsku), bledow, zdekodowano_s,
    deklarowano_s. Wynik jest zapamiętywany (cache „zdrowie”, klucz =
    plik + mtime + rozmiar), więc ponowny skan nie dekoduje wszystkiego od nowa.
    """
    from . import cache
    if uzyj_cache:
        hit = cache.get(path, "zdrowie")
        if hit and hit.get("wersja") == _WERSJA_DEKODU:
            return hit
    deklarowany, ufam = None, False
    try:
        audio = MutagenFile(path)
        if audio is not None:
            deklarowany = getattr(audio.info, "length", None)
            ufam = (not path.lower().endswith(".mp3")) or _naglowek_mp3(path)
    except Exception:                              # noqa: BLE001
        audio = None
    wynik = _ocen(path, deklarowany, ufam)
    try:
        cache.put(path, "zdrowie", wynik)
    except (OSError, TypeError, ValueError):
        pass
    return wynik


def _ffmpeg_check(path: str) -> str | None:
    """Opis problemu z dekodowaniem albo None, gdy plik jest cały."""
    w = integralnosc(path)
    return None if w["ok"] else w["opis"]


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def scan(folder: str, deep: bool = False, postep=None) -> HealthReport:
    """Skan zdrowia biblioteki (tylko odczyt).

    Utwory = ``matcher.audio_files`` (każdy raz; kopie w folderach setów
    nie są osobnymi utworami). ``postep(zrobione, wszystkie)`` — opcjonalne
    wywołanie po każdym pliku (pasek postępu w aplikacji).
    """
    from .uklad import wczytaj
    root = os.path.abspath(os.path.expanduser(folder))
    paths = _collect(root)
    uklad = wczytaj(root)
    files = []
    for p in paths:
        info = _inspect(p)
        info.w_secie = uklad.w_secie(p)
        info.sety = uklad.sety_utworu(p)
        files.append(info)

    corrupt: list[tuple[str, str]] = []
    for i, info in enumerate(files, 1):
        reasons = []
        if not info.mutagen_ok:
            reasons.append("nie da się otworzyć pliku (to nie jest poprawny plik audio)")
        else:
            ffmpeg_err = _ffmpeg_check(info.path)
            if ffmpeg_err:
                reasons.append(ffmpeg_err)
        if reasons:
            corrupt.append((info.path, "; ".join(reasons)))
        if postep:
            try:
                postep(i, len(files))
            except Exception:                      # noqa: BLE001
                pass
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
