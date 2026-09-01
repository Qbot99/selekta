"""Testy selekta.tagger: safe_name, tag_file, rename_file.

Testy mutujące działają wyłącznie na kopiach z fixture `lib_copy`.
"""
from __future__ import annotations

import os

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.wave import WAVE

from selekta.covers import embedded_art
from selekta.tagger import rename_file, safe_name, tag_file
from tests.conftest import GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3

# Minimalny "JPEG" — poprawny nagłówek + rozpoznawalna zawartość.
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"selekta-test-cover" * 8


# ---------------------------------------------------------------- safe_name

class TestSafeName:
    def test_removes_all_forbidden_chars(self):
        # Każdy ze znaków / \ : ? " < > | * znika bez śladu.
        assert safe_name('A<b>:c?"d', "x|y*z\\w/v") == "Abcd - xyzwv"

    def test_plain_name_untouched(self):
        assert safe_name("Odymel", "Gucci") == "Odymel - Gucci"

    def test_trailing_dots_trimmed_inner_kept(self):
        # Kropki w środku zostają (Mr.Machine), końcowe znikają (FAT32).
        assert safe_name("AC/DC", "T.N.T.") == "ACDC - T.N.T"
        assert safe_name("Mr.Machine", "Ballad") == "Mr.Machine - Ballad"

    def test_strips_surrounding_whitespace(self):
        assert safe_name(" a", "b ") == "a - b"

    def test_empty_inputs_give_bare_dash(self):
        assert safe_name("", "") == "-"

    def test_unicode_preserved(self):
        # Diakrytyki nie są znakami zabronionymi — zostają.
        assert safe_name("Beyoncé", "Déjà Vu") == "Beyoncé - Déjà Vu"

    def test_alternating_trailing_dots_and_spaces_fully_trimmed(self):
        result = safe_name("a", "b. .")
        assert not result.endswith((" ", ".")), repr(result)


# ----------------------------------------------------------------- tag_file

class TestTagFile:
    def test_flac_writes_tags_and_cover(self, lib_copy):
        path = os.path.join(lib_copy, GOOD_FLAC)
        tag_file(path, "Nowy Artysta", "Nowy Tytuł", FAKE_JPEG)
        audio = FLAC(path)
        assert audio["TITLE"] == ["Nowy Tytuł"]
        assert audio["ARTIST"] == ["Nowy Artysta"]
        assert len(audio.pictures) == 1
        assert audio.pictures[0].data == FAKE_JPEG
        assert audio.pictures[0].mime == "image/jpeg"
        assert audio.pictures[0].type == 3  # front cover

    def test_mp3_writes_tags_and_cover(self, lib_copy):
        path = os.path.join(lib_copy, GOOD_MP3)
        tag_file(path, "Ktoś Inny", "Inny Utwór", FAKE_JPEG)
        tags = ID3(path)
        assert str(tags["TIT2"]) == "Inny Utwór"
        assert str(tags["TPE1"]) == "Ktoś Inny"
        apics = tags.getall("APIC")
        assert len(apics) == 1
        assert apics[0].data == FAKE_JPEG
        assert apics[0].mime == "image/jpeg"

    def test_wav_writes_tags_and_cover(self, lib_copy):
        path = os.path.join(lib_copy, "Odymel - Gucci.wav")
        if not os.path.isfile(path):
            pytest.skip("brak kopii WAV w lib_copy")
        tag_file(path, "Odymel", "Gucci", FAKE_JPEG)
        audio = WAVE(path)
        assert str(audio.tags["TIT2"]) == "Gucci"
        assert str(audio.tags["TPE1"]) == "Odymel"
        assert embedded_art(path) == FAKE_JPEG

    def test_cover_none_keeps_existing_art(self, lib_copy):
        path = os.path.join(lib_copy, GOOD_FLAC)
        before = embedded_art(path)
        assert before is not None
        tag_file(path, "Odymel", "Gucci", None)
        assert embedded_art(path) == before  # okładka nietknięta

    def test_unicode_tags_roundtrip(self, lib_copy):
        path = os.path.join(lib_copy, GOOD_MP3)
        tag_file(path, "Zażółć Gęślą", "Jaźń (Öwes Remix)", None)
        tags = ID3(path)
        assert str(tags["TPE1"]) == "Zażółć Gęślą"
        assert str(tags["TIT2"]) == "Jaźń (Öwes Remix)"

    def test_unsupported_extension_raises(self, tmp_path):
        bogus = tmp_path / "utwor.ogg"
        bogus.write_bytes(b"not audio")
        with pytest.raises(ValueError, match=r"unsupported format: \.ogg"):
            tag_file(str(bogus), "a", "b", None)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            tag_file(str(tmp_path / "nie-ma.flac"), "a", "b", None)


# --------------------------------------------------------------- rename_file

class TestRenameFile:
    def test_plain_rename(self, lib_copy):
        src = os.path.join(lib_copy, GOOD_FLAC)
        dst = rename_file(src, "Inny", "Kawałek")
        assert dst == os.path.join(lib_copy, "Inny - Kawałek.flac")
        assert os.path.isfile(dst)
        assert not os.path.exists(src)

    def test_extension_preserved(self, lib_copy):
        src = os.path.join(lib_copy, GOOD_MP3)
        dst = rename_file(src, "A", "B")
        assert dst.endswith(".mp3")
        assert os.path.basename(dst) == "A - B.mp3"

    def test_forbidden_chars_removed_in_target(self, lib_copy):
        src = os.path.join(lib_copy, GOOD_MP3)
        dst = rename_file(src, "AC/DC", 'Rock: "The Best"?')
        assert os.path.basename(dst) == "ACDC - Rock The Best.mp3"
        assert os.path.isfile(dst)

    def test_case_only_rename_on_apfs(self, tmp_path):
        # APFS jest case-insensitive: zmiana samej wielkości liter musi iść
        # przez nazwę tymczasową, a plik pośredni nie może zostać na dysku.
        src = tmp_path / "odymel - gucci.flac"
        src.write_bytes(b"dane")
        dst = rename_file(str(src), "ODYMEL", "GUCCI")
        assert os.path.basename(dst) == "ODYMEL - GUCCI.flac"
        assert os.path.isfile(dst)
        # dokładna wielkość liter na dysku
        assert "ODYMEL - GUCCI.flac" in os.listdir(tmp_path)
        assert not any(n.endswith(".renaming") for n in os.listdir(tmp_path))

    def test_noop_when_name_already_correct(self, lib_copy):
        src = os.path.join(lib_copy, GOOD_FLAC)
        assert rename_file(src, "Odymel", "Gucci") == src
        assert os.path.isfile(src)

    def test_collision_raises_file_exists(self, lib_copy):
        src = os.path.join(lib_copy, MOJIBAKE_MP3)
        if not os.path.isfile(src):
            pytest.skip("brak kopii mojibake w lib_copy")
        # Cel istnieje: GOOD_MP3 już nazywa się tak samo.
        with pytest.raises(FileExistsError):
            rename_file(src, "mischluft, Sachsentrance", "We are Energy")
        assert os.path.isfile(src)  # źródło nietknięte

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            rename_file(str(tmp_path / "brak.flac"), "a", "b")
