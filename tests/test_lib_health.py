"""Testy selekta.health — skan zdrowia biblioteki (duplikaty, okładki,
uszkodzenia, tagi, statystyki) na spreparowanych kopiach realnych plików."""
from __future__ import annotations

import os
import shutil

import pytest

from selekta import health
from tests.conftest import (
    CORRUPT_FLAC,
    DUP_WAV,
    GOOD_FLAC,
    GOOD_MP3,
    MOJIBAKE_MP3,
)

DUP_WAV_NAME = "Odymel - Gucci.wav"


# --------------------------------------------------------------------------
# fixtures (module scope: jeden skan na moduł zamiast jednego na test)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lib_dir(tmp_path_factory, real_lib) -> str:
    """Ta sama zawartość co conftest.lib_copy, ale współdzielona w module
    (testy health tylko czytają)."""
    tmp = tmp_path_factory.mktemp("health-lib")
    for name in (GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3):
        src = os.path.join(real_lib, name)
        if not os.path.isfile(src):
            pytest.skip(f"brak pliku referencyjnego: {name}")
        shutil.copy(src, tmp / name)
    dup = os.path.join(real_lib, DUP_WAV)
    if not os.path.isfile(dup):
        pytest.skip(f"brak pliku referencyjnego: {DUP_WAV}")
    shutil.copy(dup, tmp / DUP_WAV_NAME)
    # ten sam warunek co w conftest.lib_copy: mojibake + brak okładki
    from tests.conftest import _make_broken
    _make_broken(tmp / MOJIBAKE_MP3)
    return str(tmp)


@pytest.fixture(scope="module")
def report(lib_dir) -> health.HealthReport:
    return health.scan(lib_dir)


# --------------------------------------------------------------------------
# zawartość spreparowanego folderu
# --------------------------------------------------------------------------

def test_lib_copy_contains_expected_files(lib_copy):
    """conftest.lib_copy faktycznie zawiera FLAC + jego duplikat WAV."""
    names = sorted(os.listdir(lib_copy))
    assert GOOD_FLAC in names
    assert DUP_WAV_NAME in names          # duplikat tego samego utworu
    assert GOOD_MP3 in names
    assert MOJIBAKE_MP3 in names


# --------------------------------------------------------------------------
# scan: duplikaty
# --------------------------------------------------------------------------

def test_scan_detects_duplicate_group(report):
    assert len(report.duplicates) == 1
    group = report.duplicates[0]
    assert group.artist == "Odymel"
    assert group.title == "Gucci"
    assert group.certain is True
    names = sorted(os.path.basename(f.path) for f in group.files)
    assert names == [GOOD_FLAC, DUP_WAV_NAME]
    # FLAC ma priorytet formatu nad WAV
    assert os.path.basename(group.keep.path) == GOOD_FLAC
    # keep jest pierwszy na liście plików grupy
    assert group.files[0] is group.keep
    assert report.suspect_duplicates == []


def test_scan_file_infos(report):
    assert len(report.files) == 4
    by_name = {os.path.basename(f.path): f for f in report.files}
    flac = by_name[GOOD_FLAC]
    assert flac.ext == ".flac"
    assert flac.mutagen_ok is True
    assert flac.artist == "Odymel" and flac.title == "Gucci"
    assert flac.bits == 16
    assert flac.duration == pytest.approx(273.7, abs=0.5)
    wav = by_name[DUP_WAV_NAME]
    assert wav.ext == ".wav"
    # duplikaty: czas trwania zgadza się w granicy DUP_MAX_DELTA_S
    assert abs(wav.duration - flac.duration) <= health.DUP_MAX_DELTA_S
    assert by_name[GOOD_MP3].bitrate == 320000


# --------------------------------------------------------------------------
# scan: formaty, rozmiary, okładki, tagi
# --------------------------------------------------------------------------

def test_scan_format_counts_and_totals(lib_dir, report):
    assert report.format_counts == {"FLAC": 1, "MP3": 2, "WAV": 1}
    expected_size = sum(
        os.path.getsize(os.path.join(lib_dir, n)) for n in os.listdir(lib_dir)
    )
    assert report.total_size == expected_size
    assert report.total_size > 100_000_000        # ~116 MB realnych plików
    # suma czasów trwania czterech utworów (~4,6 + 4,6 + 4,4 + 6,2 min)
    assert report.total_duration == pytest.approx(1180.3, abs=5.0)
    assert report.root == os.path.abspath(lib_dir)


def test_scan_missing_covers_and_tags(report):
    # jedyny plik bez okładki to mojibake MP3
    assert [os.path.basename(p) for p in report.missing_covers] == [MOJIBAKE_MP3]
    # wszystkie 4 pliki mają ARTIST i TITLE
    assert report.missing_tags == []
    assert report.corrupt == []


def test_problem_count_matches_fields(report):
    """problem_count policzony ręcznie z pól raportu."""
    redundant = sum(len(g.files) - 1 for g in report.duplicates)
    flawed = sum(1 for q in report.quality if q.grade != "ok")
    expected = (redundant + len(report.suspect_duplicates)
                + len(report.missing_covers) + len(report.corrupt)
                + len(report.missing_tags) + flawed)
    assert report.problem_count == expected
    # konkretnie: 1 zbędna kopia + 1 brak okładki = 2
    assert redundant == 1
    assert report.problem_count == 2


# --------------------------------------------------------------------------
# scan: uszkodzony plik
# --------------------------------------------------------------------------

def test_scan_flags_corrupt_flac(tmp_path, real_lib):
    src = os.path.join(real_lib, CORRUPT_FLAC)
    if not os.path.isfile(src):
        pytest.skip(f"brak pliku referencyjnego: {CORRUPT_FLAC}")
    shutil.copy(src, tmp_path / CORRUPT_FLAC)

    report = health.scan(str(tmp_path))
    assert len(report.corrupt) == 1
    path, reason = report.corrupt[0]
    assert os.path.basename(path) == CORRUPT_FLAC
    assert "ucięty" in reason or "uszkodzon" in reason or "błędy dekodowania" in reason
    # jedynym problemem jest uszkodzenie (plik ma tagi i okładkę)
    assert report.missing_tags == []
    assert report.missing_covers == []
    assert report.problem_count == 1


# --------------------------------------------------------------------------
# print_report
# --------------------------------------------------------------------------

def test_print_report_does_not_raise(report, capsys):
    health.print_report(report)
    out = capsys.readouterr().out
    assert "Raport zdrowia biblioteki:" in out
    assert "— Duplikaty —" in out
    assert "Odymel — Gucci" in out
    assert "→ zachowaj" in out
    assert "do usunięcia" in out
    assert "bez okładki" in out
    assert "Podsumowanie: 2 problemy do naprawy" in out


# --------------------------------------------------------------------------
# przypadki brzegowe
# --------------------------------------------------------------------------

def test_empty_folder_clean_report(tmp_path, capsys):
    report = health.scan(str(tmp_path))
    assert report.files == []
    assert report.duplicates == []
    assert report.suspect_duplicates == []
    assert report.missing_covers == []
    assert report.corrupt == []
    assert report.missing_tags == []
    assert report.format_counts == {}
    assert report.total_size == 0
    assert report.total_duration == 0
    assert report.problem_count == 0
    health.print_report(report)
    out = capsys.readouterr().out
    assert "0 plików" in out
    assert "biblioteka zdrowa" in out


def test_scan_nonexistent_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        health.scan(str(tmp_path / "nie-ma-takiego-folderu"))


def test_scan_ignores_non_audio_and_dotfiles(tmp_path):
    (tmp_path / "notatki.txt").write_text("hello")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    report = health.scan(str(tmp_path))
    assert report.files == []
    assert report.problem_count == 0
