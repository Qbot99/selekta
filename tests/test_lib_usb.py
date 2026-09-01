"""Testy selekta.usb — przygotowanie pendrive'a pod CDJ (kopiowanie,
konwersja WAV→AIFF, ASCII-owe nazwy, pomijanie nie-audio)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess

import pytest

from selekta import usb
from tests.conftest import DUP_WAV, GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3

DUP_WAV_NAME = "Odymel - Gucci.wav"


def _md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def _ffprobe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return float(out.stdout.strip())


# --------------------------------------------------------------------------
# fixtures: jedno przygotowanie USB na moduł (testy tylko czytają wynik)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def usb_env(tmp_path_factory, real_lib):
    """(src, dest, report) — src jak lib_copy + playlist.txt + .DS_Store."""
    src = tmp_path_factory.mktemp("usb-src")
    for name in (GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3):
        p = os.path.join(real_lib, name)
        if not os.path.isfile(p):
            pytest.skip(f"brak pliku referencyjnego: {name}")
        shutil.copy(p, src / name)
    dup = os.path.join(real_lib, DUP_WAV)
    if not os.path.isfile(dup):
        pytest.skip(f"brak pliku referencyjnego: {DUP_WAV}")
    shutil.copy(dup, src / DUP_WAV_NAME)
    (src / "playlist.txt").write_text("nie audio")
    (src / ".DS_Store").write_bytes(b"\x00\x01")

    dest = tmp_path_factory.mktemp("usb-dest")
    report = usb.prepare(str(src), str(dest))
    return str(src), str(dest), report


# --------------------------------------------------------------------------
# kopiowanie 1:1 i konwersja WAV→AIFF
# --------------------------------------------------------------------------

def test_mp3_copied_byte_identical(usb_env):
    src, dest, report = usb_env
    copies = [p for p in report.copied if os.path.basename(p) == GOOD_MP3]
    assert len(copies) == 1
    assert _md5(copies[0]) == _md5(os.path.join(src, GOOD_MP3))


def test_flac_copied_byte_identical(usb_env):
    src, dest, report = usb_env
    copies = [p for p in report.copied if os.path.basename(p) == GOOD_FLAC]
    assert len(copies) == 1
    assert _md5(copies[0]) == _md5(os.path.join(src, GOOD_FLAC))


def test_wav_converted_to_aiff_same_duration(usb_env):
    src, dest, report = usb_env
    assert len(report.converted) == 1
    aiff = report.converted[0]
    assert aiff.endswith(".aiff")
    assert os.path.dirname(aiff) == dest
    wav_dur = _ffprobe_duration(os.path.join(src, DUP_WAV_NAME))
    assert _ffprobe_duration(aiff) == pytest.approx(wav_dur, abs=0.2)
    # żaden surowy WAV nie trafił na pendrive
    assert not any(n.lower().endswith(".wav") for n in os.listdir(dest))


def test_aiff_carries_tags_and_cover(usb_env):
    from mutagen.aiff import AIFF
    _, _, report = usb_env
    audio = AIFF(report.converted[0])
    assert audio.tags is not None
    assert str(audio.tags["TIT2"]) == "Gucci"
    assert str(audio.tags["TPE1"]) == "Odymel"
    apics = audio.tags.getall("APIC")
    assert len(apics) == 1
    assert len(apics[0].data) > 1000  # realna okładka, nie pusty blob


# --------------------------------------------------------------------------
# nazwy, pomijanie, raport
# --------------------------------------------------------------------------

def test_dest_names_are_plain_ascii(usb_env):
    _, dest, _ = usb_env
    names = os.listdir(dest)
    assert len(names) == 4  # 2×MP3 + FLAC + AIFF
    for name in names:
        assert name.isascii(), name
        assert not name.startswith(".")
    # mojibake'owa nazwa pliku została zrzucona do ASCII
    assert not any("å" in n or "ü" in n for n in names)
    assert any(n.lower().endswith("dash.mp3") for n in names)


def test_txt_skipped_with_reason_dsstore_ignored(usb_env):
    _, dest, report = usb_env
    assert report.skipped == [("playlist.txt", "to nie plik audio")]
    # dotfile w ogóle nie wchodzi do przetwarzania ani na pendrive
    assert ".DS_Store" not in os.listdir(dest)
    assert "playlist.txt" not in os.listdir(dest)


def test_report_totals(usb_env):
    _, dest, report = usb_env
    assert len(report.copied) == 3
    assert len(report.converted) == 1
    dest_bytes = sum(
        os.path.getsize(os.path.join(dest, n)) for n in os.listdir(dest)
    )
    assert report.total_bytes == dest_bytes
    assert report.total_bytes > 50_000_000


def test_format_report_polish(usb_env):
    _, _, report = usb_env
    text = report.format_report()
    assert "Przygotowanie USB pod CDJ zakończone:" in text
    assert "skopiowane pliki: 3" in text
    assert "skonwertowane z WAV: 1" in text
    assert "pominięte: 1" in text
    assert "playlist.txt: to nie plik audio" in text
    assert "łącznie zapisano:" in text


# --------------------------------------------------------------------------
# convert_wav: None / błędna wartość
# --------------------------------------------------------------------------

def test_convert_wav_none_copies_wav_verbatim(lib_copy, tmp_path):
    wav_src = os.path.join(lib_copy, DUP_WAV_NAME)
    if not os.path.isfile(wav_src):
        pytest.skip("lib_copy nie zawiera duplikatu WAV")
    dest = str(tmp_path / "usb")
    report = usb.prepare(lib_copy, dest, convert_wav=None)
    assert report.converted == []
    wavs = [p for p in report.copied if p.endswith(".wav")]
    assert len(wavs) == 1
    assert _md5(wavs[0]) == _md5(wav_src)


@pytest.mark.parametrize("bad", ["ogg", "mp3", "AIFF64", ""])
def test_invalid_convert_wav_raises(tmp_path, bad):
    with pytest.raises(ValueError):
        usb.prepare(str(tmp_path), str(tmp_path / "usb"), convert_wav=bad)


# --------------------------------------------------------------------------
# przypadki brzegowe
# --------------------------------------------------------------------------

def test_empty_source_folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    report = usb.prepare(str(src), str(tmp_path / "usb"))
    assert report.copied == []
    assert report.converted == []
    assert report.skipped == []
    assert report.total_bytes == 0
    assert "łącznie zapisano: 0.0 MB (0 B)" in report.format_report()


def test_nonexistent_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        usb.prepare(str(tmp_path / "nie-ma"), str(tmp_path / "usb"))


def test_on_progress_called_per_entry(lib_copy, tmp_path):
    # uwaga: lib_copy == tmp_path, więc listę plików źródłowych zdejmujemy
    # PRZED utworzeniem katalogu docelowego
    src_files = sorted(
        e for e in os.listdir(lib_copy)
        if not e.startswith(".") and os.path.isfile(os.path.join(lib_copy, e))
    )
    calls: list[tuple[int, int, str]] = []
    usb.prepare(lib_copy, str(tmp_path / "usb"), convert_wav=None,
                on_progress=lambda done, total, name: calls.append((done, total, name)))
    n = len(calls)
    assert n == len(src_files) == 4
    assert [c[0] for c in calls] == list(range(1, n + 1))
    assert all(c[1] == n for c in calls)
    assert sorted(c[2] for c in calls) == src_files


def test_ascii_fold_examples():
    assert usb.ascii_fold("Öwes") == "Owes"
    assert usb.ascii_fold("Más") == "Mas"
    assert usb.ascii_fold("łza Łódź") == "lza Lodz"
    assert usb.ascii_fold("Straße œuvre") == "Strasse oeuvre"
    assert usb.ascii_fold("") == ""
    assert usb.ascii_fold("plain ASCII 123") == "plain ASCII 123"


class TestBezpieczenstwoCDJ:
    """Uszkodzony plik albo dziwna nazwa na pendrive = przerwany set."""

    def test_znaki_sterujace_sa_usuwane_z_nazw(self):
        """Przechodzą przez system plików, ale wieszają parser w CDJ-u."""
        from selekta.tagger import FORBIDDEN
        assert FORBIDDEN.sub("", "Utw\x07or\x00zly") == "Utworzly"

    def test_zakazane_znaki_exfat_sa_usuwane(self):
        from selekta.tagger import FORBIDDEN
        assert FORBIDDEN.sub("", 'a/b\\c:d?e"f<g>h|i*j') == "abcdefghij"

    def test_polskie_znaki_przezywaja_filtr(self):
        from selekta.tagger import FORBIDDEN
        assert FORBIDDEN.sub("", "Zażółć gęślą jaźń") == "Zażółć gęślą jaźń"

    def test_weryfikacja_wykrywa_uciety_plik(self, tmp_path):
        from selekta import usb
        src = tmp_path / "src.flac"; src.write_bytes(b"x" * 10000)
        uciety = tmp_path / "uciety.flac"; uciety.write_bytes(b"x" * 5000)
        r = usb.zweryfikuj([(str(src), str(uciety))])
        assert r["ok"] is False and len(r["rozne"]) == 1

    def test_weryfikacja_wykrywa_przeklamany_bajt(self, tmp_path):
        from selekta import usb
        src = tmp_path / "src.flac"; src.write_bytes(b"x" * 10000)
        zly = tmp_path / "zly.flac"; zly.write_bytes(b"x" * 9999 + b"y")
        assert usb.zweryfikuj([(str(src), str(zly))])["ok"] is False

    def test_weryfikacja_wykrywa_brak_pliku(self, tmp_path):
        from selekta import usb
        src = tmp_path / "src.flac"; src.write_bytes(b"x")
        r = usb.zweryfikuj([(str(src), str(tmp_path / "nie-ma.flac"))])
        assert r["brakujace"] and r["ok"] is False

    def test_identyczna_kopia_przechodzi(self, tmp_path):
        import shutil
        from selekta import usb
        src = tmp_path / "src.flac"; src.write_bytes(b"x" * 10000)
        dst = tmp_path / "dst.flac"; shutil.copy2(src, dst)
        r = usb.zweryfikuj([(str(src), str(dst))])
        assert r["ok"] is True and r["zgodne"] == 1

    def test_konwersja_nie_jest_porownywana_bajt_w_bajt(self, tmp_path):
        """WAV→AIFF ma z założenia inną zawartość — liczy się, że powstał."""
        from selekta import usb
        src = tmp_path / "src.wav"; src.write_bytes(b"x" * 10000)
        dst = tmp_path / "dst.aiff"; dst.write_bytes(b"cokolwiek")
        assert usb.zweryfikuj([(str(src), str(dst))])["ok"] is True
