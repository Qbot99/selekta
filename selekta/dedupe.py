"""Rozwiązywanie duplikatów — bezpieczna akcja na wynikach ``health.scan``.

Moduł ``health`` potrafi *znaleźć* zdublowane nagrania (np. ten sam utwór
istniejący jako ``.flac`` i jako ``.wav``), ale zostawia decyzję o usunięciu
człowiekowi.  Tutaj domykamy pętlę: dla każdej grupy pewnych duplikatów
wybieramy najlepszą kopię do zachowania, a resztę planujemy do przeniesienia
do kosza (nigdy twardego kasowania) tak, by operacja była w pełni odwracalna.

Wykrywanie duplikatów NIE jest tu pisane od nowa — korzystamy z
``selekta.health.scan`` i konsumujemy jego ``duplicates`` /
``suspect_duplicates``.  Wybór kopii do zachowania idzie wg priorytetu:

    1. bezstratny nad stratnym (a wśród bezstratnych: FLAC nad WAV/AIFF —
       ta sama drabinka ``FORMAT_PRIORITY`` co w ``health``),
    2. wyższa głębia bitowa, a przy równej — wyższy bitrate,
    3. dłuższy czas trwania,
    4. większy rozmiar pliku.

Uszkodzone kopie (zgłoszone przez ``health`` jako ``corrupt``) są odsuwane na
sam koniec kolejki — nigdy nie zostają wybrane do zachowania, jeśli istnieje
zdrowa alternatywa.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from selekta.health import (
    DUP_MAX_DELTA_S,
    FORMAT_PRIORITY,
    DuplicateGroup,
    FileInfo,
    scan,
)

#: rozszerzenia traktowane jako bezstratne
LOSSLESS_EXT = (".flac", ".wav", ".aiff")


# --------------------------------------------------------------------------
# model danych
# --------------------------------------------------------------------------

@dataclass
class DupAction:
    """Zaplanowana decyzja dla jednej grupy duplikatów.

    Attributes:
        keep: ścieżka kopii do zachowania (nigdy nie jest usuwana).
        remove: ścieżki kopii zaplanowanych do przeniesienia do kosza.
        reason: czytelne po polsku uzasadnienie wyboru.
    """

    keep: str
    remove: list[str]
    reason: str
    #: pola pomocnicze do raportu (nie wpływają na logikę apply)
    keep_desc: str = ""
    remove_desc: list[str] = field(default_factory=list)
    reclaim_bytes: int = 0
    suspect: bool = False


# --------------------------------------------------------------------------
# wybór kopii do zachowania
# --------------------------------------------------------------------------

def _rank(info: FileInfo, corrupt: set[str]) -> tuple:
    """Klucz sortowania kopii — mniejszy = lepszy (do zachowania).

    Odwzorowuje priorytet z docstringa modułu.  Uszkodzone i nieczytelne
    pliki lądują na końcu przez pierwsze dwa składniki krotki.
    """
    return (
        info.path in corrupt,                 # False < True → zdrowe najpierw
        not info.mutagen_ok,                  # czytelne najpierw
        FORMAT_PRIORITY.get(info.ext, 9),     # (1) FLAC < WAV/AIFF < M4A < MP3
        -(info.bits or 0),                    # (2a) wyższa głębia bitowa
        -(info.bitrate or 0),                 # (2b) wyższy bitrate
        -(info.duration or 0.0),              # (3) dłuższy czas trwania
        -info.size,                           # (4) większy rozmiar
    )


def _fmt(info: FileInfo) -> str:
    return info.ext.lstrip(".").upper()


def _mb(num_bytes: int) -> float:
    return round(num_bytes / 1_000_000, 2)


def _hms(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _describe(info: FileInfo) -> str:
    parts = [_fmt(info)]
    if info.bits:
        parts.append(f"{info.bits}-bit")
    if info.bitrate:
        parts.append(f"{round(info.bitrate / 1000)} kbps")
    if info.duration:
        parts.append(_hms(info.duration))
    parts.append(f"{_mb(info.size)} MB")
    return ", ".join(parts)


def _reason(keep: FileInfo, runner: FileInfo, n_remove: int,
            suspect: bool) -> str:
    """Uzasadnij wybór, wskazując regułę, która przesądziła (keep vs runner).

    ``runner`` to najlepsza z odrzucanych kopii — porównanie z nią pokazuje,
    który składnik priorytetu faktycznie zadecydował.
    """
    k_ll = keep.ext in LOSSLESS_EXT
    r_ll = runner.ext in LOSSLESS_EXT

    if k_ll and not r_ll:
        core = f"zachowano bezstratny {_fmt(keep)} nad stratnym {_fmt(runner)}"
    elif (k_ll and r_ll
          and FORMAT_PRIORITY.get(keep.ext, 9) != FORMAT_PRIORITY.get(runner.ext, 9)):
        same_depth = (keep.bits and keep.bits == runner.bits)
        depth = f", ta sama głębia {keep.bits}-bit" if same_depth else ""
        core = (f"zachowano {_fmt(keep)} jako preferowany kontener bezstratny "
                f"nad {_fmt(runner)}{depth}")
    elif (keep.bits or 0) != (runner.bits or 0):
        core = (f"zachowano wyższą głębię bitową "
                f"{keep.bits}-bit (nad {runner.bits}-bit)")
    elif (keep.bitrate or 0) != (runner.bitrate or 0):
        core = (f"zachowano wyższy bitrate {round((keep.bitrate or 0) / 1000)} kbps "
                f"(nad {round((runner.bitrate or 0) / 1000)} kbps)")
    elif abs((keep.duration or 0) - (runner.duration or 0)) > 0.05:
        core = (f"zachowano dłuższą kopię "
                f"({_hms(keep.duration)} nad {_hms(runner.duration)})")
    elif keep.size != runner.size:
        core = (f"zachowano większy plik "
                f"({_mb(keep.size)} MB nad {_mb(runner.size)} MB)")
    else:
        core = f"kopie równoważne — zachowano {_fmt(keep)} (pierwsza w kolejności)"

    if n_remove > 1:
        core += f"; odrzucono {n_remove} pozostałych kopii"

    if suspect:
        core = ("PODEJRZANE — czas trwania różni się > "
                f"{DUP_MAX_DELTA_S:g} s (możliwa inna edycja lub ucięta kopia), "
                "zweryfikuj ręcznie przed usunięciem: " + core)
    return core


def _action_for(group: DuplicateGroup, corrupt: set[str],
                suspect: bool) -> DupAction:
    """Zbuduj ``DupAction`` dla jednej grupy duplikatów."""
    ranked = sorted(group.files, key=lambda f: _rank(f, corrupt))
    keep = ranked[0]
    removed = ranked[1:]
    reason = _reason(keep, removed[0], len(removed), suspect)
    return DupAction(
        keep=keep.path,
        remove=[f.path for f in removed],
        reason=reason,
        keep_desc=_describe(keep),
        remove_desc=[_describe(f) for f in removed],
        reclaim_bytes=sum(f.size for f in removed),
        suspect=suspect,
    )


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def plan(folder: str, include_suspect: bool = False) -> list[DupAction]:
    """Zaplanuj rozwiązanie duplikatów w ``folder`` (nic nie zmienia na dysku).

    Uruchamia ``health.scan`` (odczyt), po czym dla każdej grupy PEWNYCH
    duplikatów wybiera najlepszą kopię wg priorytetu z docstringa modułu i
    planuje przeniesienie reszty do kosza.

    Args:
        folder: katalog biblioteki do przeskanowania.
        include_suspect: gdy ``True``, dołącz również grupy podejrzane
            (różny czas trwania — możliwe inne edycje); są one oznaczone
            w ``reason``.  Domyślnie ``False`` — podejrzane są pomijane.

    Returns:
        Lista ``DupAction`` — po jednej na grupę duplikatów.
    """
    report = scan(folder)
    corrupt = {p for p, _ in report.corrupt}

    actions: list[DupAction] = []
    for group in report.duplicates:
        actions.append(_action_for(group, corrupt, suspect=False))
    if include_suspect:
        for group in report.suspect_duplicates:
            actions.append(_action_for(group, corrupt, suspect=True))
    return actions


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def _unique_dest(trash_dir: str, name: str) -> str:
    """Ścieżka w koszu, wolna od kolizji nazw (dopisuje ` (1)`, ` (2)`…)."""
    dest = os.path.join(trash_dir, name)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(name)
    i = 1
    while True:
        candidate = os.path.join(trash_dir, f"{stem} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def apply(actions: list[DupAction], trash_dir: str) -> dict:
    """Wykonaj plan: PRZENIEŚ pliki ``remove`` do ``trash_dir`` (bez kasowania).

    Plik ``keep`` z każdej akcji nie jest nigdy ruszany.  Nazwy w koszu są
    deduplikowane, więc dwa różne pliki o tej samej nazwie się nie nadpiszą.

    Args:
        actions: lista akcji z :func:`plan`.
        trash_dir: katalog kosza (tworzony, jeśli nie istnieje).

    Returns:
        Słownik ``{"przeniesione": [...], "odzyskane_MB": float,
        "błędy": [...]}``.  ``przeniesione`` to pary ``(źródło, cel)``,
        ``błędy`` to pary ``(ścieżka, opis błędu)``.
    """
    os.makedirs(trash_dir, exist_ok=True)
    trash_abs = os.path.abspath(trash_dir)

    keep_paths = {os.path.abspath(a.keep) for a in actions}
    przeniesione: list[tuple[str, str]] = []
    bledy: list[tuple[str, str]] = []
    reclaimed = 0

    for action in actions:
        for src in action.remove:
            src_abs = os.path.abspath(src)
            # bezpiecznik: nigdy nie ruszaj pliku do zachowania
            if src_abs in keep_paths:
                bledy.append((src, "pominięto — ścieżka pokrywa się z 'keep'"))
                continue
            if not os.path.exists(src_abs):
                bledy.append((src, "plik nie istnieje"))
                continue
            try:
                size = os.path.getsize(src_abs)
                dest = _unique_dest(trash_abs, os.path.basename(src_abs))
                shutil.move(src_abs, dest)
                przeniesione.append((src_abs, dest))
                reclaimed += size
            except OSError as exc:
                bledy.append((src, f"{type(exc).__name__}: {exc}"))

    return {
        "przeniesione": przeniesione,
        "odzyskane_MB": round(reclaimed / 1_000_000, 2),
        "błędy": bledy,
    }


# --------------------------------------------------------------------------
# raport
# --------------------------------------------------------------------------

def format_plan(actions: list[DupAction]) -> str:
    """Zbuduj czytelny raport tekstowy planu (po polsku)."""
    if not actions:
        return "Brak duplikatów do rozwiązania. ✅"

    sure = [a for a in actions if not a.suspect]
    suspect = [a for a in actions if a.suspect]
    total_remove = sum(len(a.remove) for a in actions)
    total_reclaim = sum(a.reclaim_bytes for a in actions)

    lines: list[str] = []
    lines.append("Plan rozwiązania duplikatów")
    lines.append(
        f"  grupy: {len(actions)} "
        f"(pewne: {len(sure)}, podejrzane: {len(suspect)}), "
        f"do przeniesienia: {total_remove} plików, "
        f"do odzyskania: {_mb(total_reclaim)} MB"
    )

    def block(action: DupAction) -> None:
        icon = "⚠️" if action.suspect else "❌"
        lines.append("")
        lines.append(f"{icon} {action.reason}")
        lines.append(f"   → zachowaj:      {action.keep}")
        lines.append(f"                    [{action.keep_desc}]")
        for path, desc in zip(action.remove, action.remove_desc):
            lines.append(f"   ✗ do kosza:      {path}")
            lines.append(f"                    [{desc}]")

    if sure:
        lines.append("")
        lines.append("— Pewne duplikaty —")
        for action in sure:
            block(action)
    if suspect:
        lines.append("")
        lines.append("— Podejrzane (do ręcznej weryfikacji) —")
        for action in suspect:
            block(action)

    return "\n".join(lines)
