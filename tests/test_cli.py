"""CLI — testy przez subprocess na prawdziwej binarce .venv/bin/selekta."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

BIN = [sys.executable, "-m", "selekta.cli"]   # ten sam interpreter co pytest
ALL_COMMANDS = [
    "organize", "verify", "check", "match", "covers", "icons", "analyze",
    "health", "export", "usb", "radar", "wishlist", "hunt", "loudness",
    "cues", "tagfix", "dedupe", "serve",
]


def run(*args, env_home: str | None = None, timeout: int = 120):
    env = os.environ.copy()
    if env_home:
        env["HOME"] = env_home  # izoluje ~/.selekta w subprocesie
    return subprocess.run([*BIN, *args], capture_output=True, text=True,
                          env=env, timeout=timeout)


def test_main_help():
    r = run("--help")
    assert r.returncode == 0
    for cmd in ALL_COMMANDS:
        assert cmd in r.stdout


@pytest.mark.parametrize("cmd", ALL_COMMANDS)
def test_every_subcommand_has_help(cmd):
    r = run(cmd, "--help")
    assert r.returncode == 0, r.stderr


def test_unknown_command_rc2():
    assert run("nieistniejąca-komenda").returncode == 2


def test_missing_folder_is_readable_error_not_traceback():
    r = run("verify", "--folder", "/nie/ma/takiego/folderu")
    assert r.returncode != 0
    # czytelny błąd, nie surowy traceback Pythona
    assert "Traceback" not in r.stderr or "FileNotFoundError" in r.stderr


@pytest.mark.slow
def test_verify_reports_quality(lib_copy):
    r = run("verify", "--folder", lib_copy, "--limit", "2")
    assert r.returncode == 0
    assert "plików bez zastrzeżeń" in r.stdout


@pytest.mark.slow
def test_health_finds_duplicate(lib_copy):
    r = run("health", "--folder", lib_copy)
    assert r.returncode == 0
    assert "Duplikaty" in r.stdout and "Gucci" in r.stdout


@pytest.mark.slow
def test_analyze_shows_key_and_order(lib_copy):
    r = run("analyze", "--folder", lib_copy, "--limit", "2", "--order",
            env_home=lib_copy)  # cache w izolowanym HOME
    assert r.returncode == 0
    assert "BPM" in r.stdout and "kolejność harmoniczna" in r.stdout


@pytest.mark.slow
def test_cues_and_loudness(lib_copy):
    for cmd, needle in (("cues", "drop"), ("loudness", "LUFS")):
        r = run(cmd, "--folder", lib_copy, "--limit", "1", env_home=lib_copy)
        assert r.returncode == 0, r.stderr
        assert needle in r.stdout


def test_tagfix_preview_shows_repair(lib_copy):
    r = run("tagfix", "--folder", lib_copy)
    assert r.returncode == 0
    assert "ÅMRTÜM" in r.stdout and "podgląd" in r.stdout


def test_dedupe_preview(lib_copy):
    r = run("dedupe", "--folder", lib_copy)
    assert r.returncode == 0
    assert "zachowa" in r.stdout  # "zachowaj:"/"zachowano"


def test_export_m3u8(lib_copy):
    r = run("export", "--folder", lib_copy, "--target", "m3u8")
    assert r.returncode == 0
    assert any(f.endswith(".m3u8") for f in os.listdir(lib_copy))


def test_usb_prepare(lib_copy, tmp_path):
    dest = str(tmp_path / "usb")
    r = run("usb", "--folder", lib_copy, "--dest", dest, "--convert-wav", "keep")
    assert r.returncode == 0
    assert "skopiowane" in r.stdout
    assert all(n.isascii() for n in os.listdir(dest))


def test_organize_dry_run_text_source(lib_copy, tmp_path):
    src = tmp_path / "lista.txt"
    src.write_text("Odymel - Gucci\nWidmo - Nie Istnieje\n", encoding="utf-8")
    r = run("organize", str(src), "--folder", lib_copy)
    assert r.returncode == 0
    assert "dopasowanych" in r.stdout and "dry-run" in r.stdout


def test_organize_apply_text_source(lib_copy, tmp_path):
    """--apply na trackliście tekstowej nie może się wywalić na okładce
    (syntetyczne id → cover_bytes musi zwrócić None, nie wyjątek)."""
    src = tmp_path / "lista.txt"
    src.write_text("Odymel - Gucci\n", encoding="utf-8")
    r = run("organize", str(src), "--folder", lib_copy, "--apply")
    assert r.returncode == 0, r.stderr
    assert os.path.isfile(os.path.join(lib_copy, "Odymel - Gucci.flac"))


def test_wishlist_isolated_home(lib_copy, tmp_path):
    home = str(tmp_path)
    r = run("wishlist", "--add", "Artysta - Utwór", env_home=home)
    assert r.returncode == 0 and "dodano" in r.stdout
    r2 = run("wishlist", env_home=home)
    assert "Artysta — Utwór" in r2.stdout
    # stan wylądował w izolowanym HOME, nie u użytkownika
    assert os.path.isfile(os.path.join(home, ".selekta", "wishlist.json"))


class TestBledneWejscie:
    """Błędne wejście = ludzki komunikat, nie ściana tracebacku.

    Regresja z 1.09.2026: moduły miały gotowe polskie komunikaty w wyjątkach,
    ale main() ich nie przechwytywał — użytkownik dostawał surowy stos wywołań
    z komunikatem zakopanym na dole. Do tego pusty folder udawał sukces,
    a plik-śmieć przechodził przez analyze po cichu jako „0.0 BPM".
    """

    def test_nieistniejacy_folder_bez_tracebacku(self):
        r = run("verify", "--folder", "/nie/ma/takiego/folderu")
        assert r.returncode != 0
        assert "Traceback" not in r.stderr and "Traceback" not in r.stdout
        assert "błąd:" in r.stderr and "nie ma folderu" in r.stderr

    def test_pusty_folder_nie_udaje_sukcesu(self, tmp_path):
        r = run("verify", "--folder", str(tmp_path))
        assert r.returncode != 0
        assert "nie zawiera plików audio" in r.stderr
        assert "Traceback" not in r.stderr

    def test_smiec_udajacy_mp3_jest_flagowany_w_verify(self, tmp_path):
        (tmp_path / "podroba.mp3").write_text("to nie jest zaden mp3")
        r = run("verify", "--folder", str(tmp_path))
        assert "Traceback" not in r.stderr and "Traceback" not in r.stdout
        assert "nie da się odczytać" in r.stdout
        assert "0/1" in r.stdout

    def test_smiec_udajacy_mp3_nie_przechodzi_przez_analyze(self, tmp_path):
        (tmp_path / "podroba.mp3").write_text("to nie jest zaden mp3")
        r = run("analyze", "--folder", str(tmp_path))
        assert "Traceback" not in r.stderr and "Traceback" not in r.stdout
        assert "0.0 BPM" not in r.stdout, "śmieć zaraportowany jak wynik"
        assert "brak sygnału" in r.stdout or "nie da się odczytać" in r.stdout
        assert "pominięto 1" in r.stdout

    def test_debug_przywraca_traceback(self):
        r = run("--debug", "verify", "--folder", "/nie/ma/takiego/folderu")
        assert r.returncode != 0
        assert "Traceback" in r.stderr

    def test_organize_z_bzdurnym_zrodlem_po_ludzku(self, tmp_path):
        (tmp_path / "cos.mp3").write_text("x")
        r = run("organize", "zzz ccc vvv", "--folder", str(tmp_path))
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert "nie rozpoznano" in r.stderr


class TestNaprawyZastrzezen:
    """Regresje z listy zastrzeżeń weryfikacji 1.09.2026."""

    def test_export_z_cli_ma_siatke_i_cue(self, tmp_path):
        """XML z terminala był bez TEMPO/POSITION_MARK — pełny eksport
        robiła tylko aplikacja webowa."""
        from tests import probka
        probka.metronom(str(tmp_path / "Test - Utwor.wav"), 128.0, sekund=30)
        dom = tmp_path / "dom"; dom.mkdir()
        r = run("analyze", "--folder", str(tmp_path), env_home=str(dom))
        assert r.returncode == 0
        r = run("export", "--folder", str(tmp_path), "--target", "rekordbox",
                env_home=str(dom))
        assert r.returncode == 0, r.stderr
        xml = (tmp_path / f"{tmp_path.name}.xml").read_text(encoding="utf-8")
        assert "<TEMPO" in xml and 'Bpm="128' in xml, "brak siatki w XML z CLI"

    def test_analyze_apply_nie_uniewaznia_wlasnego_cache(self, tmp_path):
        """Zapis tagów zmieniał mtime po włożeniu do cache, więc następne
        uruchomienie liczyło wszystko od zera.

        Bez pomiaru czasu (dwie wersje tego testu na stoperze okazały się
        niestabilne pod obciążeniem): sprawdzamy wprost semantykę naprawy —
        po --apply wpis w cache ma pasować do NOWEGO mtime pliku."""
        import subprocess
        from tests import probka
        plik = str(tmp_path / "Test - Utwor.wav")
        probka.metronom(plik, 128.0, sekund=30)
        dom = tmp_path / "dom"; dom.mkdir()
        r = run("analyze", "--folder", str(tmp_path), "--apply", env_home=str(dom))
        assert r.returncode == 0, r.stderr
        sonda = subprocess.run(
            [sys.executable, "-c",
             "import sys; from selekta import cache; "
             "sys.exit(0 if cache.get(sys.argv[1], 'harmonic') else 1)",
             plik],
            env={**__import__('os').environ, "HOME": str(dom)},
            capture_output=True, text=True)
        assert sonda.returncode == 0, (
            f"wpis cache nie pasuje do mtime po zapisie tagów — "
            f"następna analiza liczyłaby wszystko od zera "
            f"(stderr sondy: {sonda.stderr[-400:]!r})")



class TestDopasowanieWCli:
    """Przegląd 0.4.2: `organize` oznaczył „✓ Frozen ← Like a Prayer" —
    best_match brał najwyższy wynik ≥ 0,6 bez sprawdzenia tożsamości."""

    def test_organize_nie_bierze_cudzego_pliku(self, lib_copy, tmp_path):
        src = tmp_path / "lista.txt"
        src.write_text("Odymel - Gucci Gang\nKtoś Inny - Gucci\nOdymel - Gucci\n",
                       encoding="utf-8")
        r = run("organize", str(src), "--folder", lib_copy)
        assert r.returncode == 0, r.stderr
        assert "1 dopasowanych, 2 brakujących" in r.stdout
        assert "✓ Odymel — Gucci\n" in r.stdout

    def test_hunt_pobiera_tylko_pewny_wynik(self, lib_copy, monkeypatch, capsys):
        import argparse
        from selekta import cli, wishlist
        from selekta.slskd_client import SearchHit, SlskdClient

        cudzy = SearchHit("u1", "Rick Astley\\Never Gonna Give You Up.flac",
                          40_000_000, None, 213, True, True)
        dobry = SearchHit("u2", "Madonna\\Madonna - Frozen.mp3", 9_000_000, 320, 372, False, True)

        class Klient:
            pobrane = []

            def available(self):
                return True

            def search_track(self, artist, title, duration_s=None):
                return [cudzy, dobry] if title == "Frozen" else [cudzy]

            pewny_wynik = SlskdClient.pewny_wynik

            def download(self, hit):
                Klient.pobrane.append(hit.filename)

        monkeypatch.setattr(cli, "SlskdClient", Klient)
        src = os.path.join(lib_copy, "lista.txt")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("Madonna - Frozen\nOdymel - Gucci\nDonna Summer - Hot Stuff\n")
        cli.cmd_hunt(argparse.Namespace(source=src, folder=lib_copy, download=True))
        out = capsys.readouterr().out
        assert Klient.pobrane == ["Madonna\\Madonna - Frozen.mp3"]
        assert "Odymel — Gucci" not in out          # to już masz
        assert "nie jest na pewno" in out           # Hot Stuff: tylko cudzy wynik
        assert wishlist.items() == []
        assert "Qobuz" in out                       # więcej sklepów niż Beatport


class TestWishlistCli:
    def test_lista_numerowana_i_usuwanie_po_numerze(self, tmp_path):
        home = str(tmp_path)
        for x in ("A - Jeden", "B - Dwa", "C - Trzy"):
            assert run("wishlist", "--add", x, env_home=home).returncode == 0
        lista = run("wishlist", env_home=home).stdout
        assert " 1. · A — Jeden" in lista and " 3. · C — Trzy" in lista
        r = run("wishlist", "--remove", "1", env_home=home)
        assert "usunięto: A — Jeden" in r.stdout      # dawniej znikało „B — Dwa"
        assert "A — Jeden" not in run("wishlist", env_home=home).stdout

    def test_dodanie_bez_myslnika_to_czytelny_blad(self, tmp_path):
        r = run("wishlist", "--add", "Bez myślnika", env_home=str(tmp_path))
        assert r.returncode != 0 and "Artysta - Tytuł" in r.stderr
