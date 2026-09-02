"""Testy selekta.tagfix: looks_mojibake, repair, scan, fix_file."""
from __future__ import annotations

import os

import pytest
from mutagen.id3 import ID3

from selekta.tagfix import fix_file, looks_mojibake, repair, scan
from tests.conftest import GOOD_MP3, MOJIBAKE_MP3

BROKEN_ARTIST = "Ã…MRTÃœM"
FIXED_ARTIST = "ÅMRTÜM"


# ----------------------------------------------------------- looks_mojibake

class TestLooksMojibake:
    @pytest.mark.parametrize("text", [
        BROKEN_ARTIST,          # UTF-8 'ÅMRTÜM' odczytane jako cp1252
        "BeyoncÃ©",             # UTF-8 'Beyoncé' odczytane jako cp1252
        "CafÃ© del Mar",
        "â€žP",                 # 'â€ž' = mojibake cudzysłowu „ (marker â€)
    ])
    def test_true_for_broken(self, text):
        assert looks_mojibake(text) is True

    @pytest.mark.parametrize("text", [
        "Öwes",
        "Beyoncé",
        "Zażółć gęślą jaźń",
        "Motörhead",
        "åmrtüm - dash",        # poprawne małe diakrytyki, nie mojibake
        "plain ascii title",
        "",
    ])
    def test_false_for_correct(self, text):
        assert looks_mojibake(text) is False


# ------------------------------------------------------------------- repair

class TestRepair:
    def test_reverses_mojibake(self):
        assert repair(BROKEN_ARTIST) == FIXED_ARTIST
        assert repair("BeyoncÃ©") == "Beyoncé"

    def test_reverses_double_encoding(self):
        double = "Beyoncé".encode("utf-8").decode("cp1252") \
                          .encode("utf-8").decode("cp1252")
        assert double == "BeyoncÃƒÂ©"
        assert repair(double) == "Beyoncé"

    @pytest.mark.parametrize("text", [
        "Öwes", "Beyoncé", "Zażółć gęślą jaźń", "Motörhead",
        "plain ascii", "",
    ])
    def test_correct_text_untouched(self, text):
        assert repair(text) == text

    def test_idempotent(self):
        once = repair(BROKEN_ARTIST)
        assert repair(once) == once == FIXED_ARTIST


# --------------------------------------------------------------------- scan

class TestScan:
    def test_finds_exactly_the_mojibake_artist(self, lib_copy):
        expected_path = os.path.join(lib_copy, MOJIBAKE_MP3)
        if not os.path.isfile(expected_path):
            pytest.skip("brak kopii mojibake w lib_copy")
        hits = scan(lib_copy)
        assert hits == [(expected_path, "ARTIST", BROKEN_ARTIST, FIXED_ARTIST)]

    def test_empty_folder(self, tmp_path):
        assert scan(str(tmp_path)) == []

    def test_nonexistent_folder(self, tmp_path):
        assert scan(str(tmp_path / "nie-istnieje")) == []

    def test_folder_with_non_audio_only(self, tmp_path):
        (tmp_path / "notatki.txt").write_bytes(BROKEN_ARTIST.encode("utf-8"))
        assert scan(str(tmp_path)) == []


# ----------------------------------------------------------------- fix_file

class TestFixFile:
    def test_dry_run_reports_but_does_not_write(self, lib_copy):
        path = os.path.join(lib_copy, MOJIBAKE_MP3)
        if not os.path.isfile(path):
            pytest.skip("brak kopii mojibake w lib_copy")
        changes = fix_file(path, dry_run=True)
        assert changes == [("ARTIST", BROKEN_ARTIST, FIXED_ARTIST)]
        # Tag na dysku pozostał zepsuty:
        assert str(ID3(path)["TPE1"]) == BROKEN_ARTIST

    def test_wet_run_repairs_tag(self, lib_copy):
        path = os.path.join(lib_copy, MOJIBAKE_MP3)
        if not os.path.isfile(path):
            pytest.skip("brak kopii mojibake w lib_copy")
        changes = fix_file(path, dry_run=False)
        assert changes == [("ARTIST", BROKEN_ARTIST, FIXED_ARTIST)]
        assert str(ID3(path)["TPE1"]) == FIXED_ARTIST
        # Druga naprawa nie ma już nic do roboty:
        assert fix_file(path, dry_run=False) == []
        # Po naprawie scan folderu jest czysty:
        assert scan(os.path.dirname(path)) == []

    def test_healthy_file_untouched(self, lib_copy):
        path = os.path.join(lib_copy, GOOD_MP3)
        before = str(ID3(path)["TPE1"])
        assert fix_file(path, dry_run=False) == []
        assert str(ID3(path)["TPE1"]) == before == "mischluft, Sachsentrance"

    def test_default_is_dry_run(self, lib_copy):
        path = os.path.join(lib_copy, MOJIBAKE_MP3)
        if not os.path.isfile(path):
            pytest.skip("brak kopii mojibake w lib_copy")
        fix_file(path)  # bez argumentu — musi być bezpieczne
        assert str(ID3(path)["TPE1"]) == BROKEN_ARTIST

    def test_nonexistent_file_returns_empty(self, tmp_path):
        # _read_fields połyka błędy odczytu -> brak pól -> brak zmian.
        assert fix_file(str(tmp_path / "brak.mp3"), dry_run=True) == []


from selekta import tagfix


class TestCp1250:
    """Polskie mojibake — UTF-8 przeczytane jako cp1250.

    Regresja z 1.09.2026: moduł odwracał tylko cp1252/latin-1, a najczęstsze
    krzaczki w starych polskich MP3 pochodzą z cp1250 (Ĺ/Ľ/Ă nie istnieją
    w cp1252, więc naprawa je pomijała).
    """

    def test_odwraca_polskie_mojibake(self):
        zepsute = "Zażółć gęślą jaźń".encode("utf-8").decode("cp1250")
        assert "ĹĽ" in zepsute            # upewniamy się, że to cp1250-krzaczki
        assert tagfix._decode_repair(zepsute) == "Zażółć gęślą jaźń"

    def test_przyklad_z_weryfikacji(self):
        assert tagfix._decode_repair("ZaĹĽĂłĹ‚Ä‡ gÄ™Ĺ›lÄ… jaĹşĹ„") == \
            "Zażółć gęślą jaźń"

    def test_zdrowe_polskie_tagi_nietkniete(self):
        for ok in ("Zażółć gęślą jaźń", "Kwęgiel — Łódź (Oryginał)",
                   "Beyoncé", "Öwes", "ÅMRTÜM po naprawie"):
            assert tagfix._decode_repair(ok) is None, f"ruszono zdrowy: {ok!r}"


class TestRumunskaKolizja:
    """Kontrprzykłady z kontroli 1.09.2026: para Ă/Â + Ş koduje się w cp1250
    do POPRAWNEGO UTF-8, więc bezpiecznik enkodowania nie działa i zdrowe
    rumuńskie wersaliki były „naprawiane" na śmieci."""

    ZDROWE = ["MĂŞTI", "CÂŞTIG", "PĂŞUNE", "MĂŞTILE", "CÂŞTIGURI",
              "MĂŞTI - CÂŞTIG"]

    def test_zdrowe_rumunskie_nietkniete(self):
        for w in self.ZDROWE:
            assert tagfix._decode_repair(w) is None, f"ruszono: {w!r}"

    def test_zdrowe_rumunskie_nie_wygladaja_na_mojibake(self):
        for w in self.ZDROWE:
            assert tagfix.looks_mojibake(w) is False, w

    def test_polskie_mojibake_dalej_naprawiane(self):
        assert tagfix._decode_repair("ZaĹĽĂłĹ‚Ä‡ gÄ™Ĺ›lÄ… jaĹşĹ„") == \
            "Zażółć gęślą jaźń"
        assert tagfix._decode_repair("GĂłry") == "Góry"
