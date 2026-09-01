"""Wspólne fixtures dla całego pakietu testów selekta.

Zasady:
- Prawdziwa biblioteka (~/.local/share/nicotine/downloads) jest TYLKO DO
  ODCZYTU — testy mutujące działają wyłącznie na kopiach (`lib_copy`).
- Stan użytkownika w ~/.selekta (wishlist, radar, cache) jest izolowany
  automatycznie — żaden test nie dotyka prawdziwych plików stanu.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

REAL_LIB = os.path.expanduser("~/.local/share/nicotine/downloads")

# Realne pliki o znanych, zweryfikowanych własnościach:
GOOD_FLAC = "Odymel - Gucci.flac"              # zdrowy, okładka, klucz 8A, ~146 BPM
GOOD_MP3 = "mischluft, Sachsentrance - We are Energy.mp3"   # zdrowy MP3 320
GOOD_WAV = "Pegassi - MOAA (Extended).wav"     # 24-bit WAV, okładka
CORRUPT_FLAC = "Mike Candys, Shaun Baker, Evelyn - Heaven & Hell.flac"  # ucięty koniec
MOJIBAKE_MP3 = "åmrtüm - dash.mp3"             # TPE1 = mojibake UTF-8-jako-cp1252
FAKE_FLAC = "MilleniumKid, JBS, The Boy The G - Unendlichkeit (Remix).flac"  # źródło ~128k
DUP_WAV = os.path.join("Inne - poza playlistą", "Odymel - Gucci - 8A - 146.wav")


def real_path(name: str) -> str:
    """Ścieżka do realnego pliku; test jest pomijany, gdy pliku brak."""
    p = os.path.join(REAL_LIB, name)
    if not os.path.isfile(p):
        pytest.skip(f"brak pliku referencyjnego: {name}")
    return p


@pytest.fixture(scope="session")
def real_lib() -> str:
    if not os.path.isdir(REAL_LIB):
        pytest.skip("brak realnej biblioteki")
    return REAL_LIB


@pytest.fixture()
def sample(real_lib):
    """sample('Odymel - Gucci.flac') -> pełna ścieżka (skip gdy brak)."""
    return real_path


def fast_copy(src: str, dst: str) -> None:
    """Niezależna kopia pliku, najtaniej jak się da.

    Na APFS (macOS) używa klonu copy-on-write: kopia jest natychmiastowa i
    zajmuje ~0 bajtów do pierwszego zapisu, a mimo to jest w pełni
    niezależna. Bez tego pakiet testów kopiował ~116 MB na KAŻDY test
    korzystający z lib_copy i zapychał dysk (realnie: 19 GB w /tmp).
    """
    if sys.platform == "darwin":
        if subprocess.run(["cp", "-c", src, dst],
                          capture_output=True).returncode == 0:
            return
    shutil.copy(src, dst)


@pytest.fixture()
def lib_copy(tmp_path, real_lib) -> str:
    """Świeża kopia małego, różnorodnego zestawu plików do testów mutujących:
    zdrowy FLAC + mojibake MP3 + zdrowy MP3 + duplikat WAV tego samego utworu."""
    for name in (GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3):
        src = os.path.join(real_lib, name)
        if os.path.isfile(src):
            fast_copy(src, str(tmp_path / name))
    dup = os.path.join(real_lib, DUP_WAV)
    if os.path.isfile(dup):
        fast_copy(dup, str(tmp_path / "Odymel - Gucci.wav"))
    _make_broken(tmp_path / MOJIBAKE_MP3)
    return str(tmp_path)


def _make_broken(path) -> None:
    """Wymuś w KOPII warunki, których wymagają testy: mojibake w ARTIST
    i brak okładki.

    Bez tego testy zależałyby od tego, że plik w prawdziwej bibliotece
    pozostanie zepsuty — a użytkownik może go naprawić (i naprawił),
    przez co testy zaczynały padać bez żadnej regresji w kodzie.
    """
    if not path.is_file():
        return
    from mutagen.id3 import ID3, ID3NoHeaderError, TPE1
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.delall("TPE1")
    tags.add(TPE1(encoding=3, text="Ã…MRTÃœM"))
    tags.save(str(path))


@pytest.fixture(autouse=True)
def _isolate_user_state(monkeypatch, tmp_path_factory):
    """Przekieruj cały stan ~/.selekta do katalogu tymczasowego.

    Chroni prawdziwe wishlist.json / radar.json / cache użytkownika przed
    każdym testem, także takim, który woła te moduły pośrednio.
    """
    state = tmp_path_factory.mktemp("selekta-state")
    from selekta import cache, config, radar, wishlist

    monkeypatch.setattr(cache, "CACHE_DIR", str(state / "cache"))
    monkeypatch.setattr(wishlist, "STATE_DIR", str(state))
    monkeypatch.setattr(wishlist, "STATE_PATH", str(state / "wishlist.json"))
    monkeypatch.setattr(radar, "STATE_DIR", str(state))
    monkeypatch.setattr(radar, "STATE_PATH", str(state / "radar.json"))
    # config trzyma klucz API slskd — bez tej izolacji testy czytałyby
    # prawdziwe ustawienia użytkownika (i jego sekrety)
    monkeypatch.setattr(config, "STATE_DIR", str(state))
    monkeypatch.setattr(config, "CONFIG_PATH", str(state / "config.json"))
    for var in ("SELEKTA_SLSKD_URL", "SELEKTA_SLSKD_API_KEY", "SELEKTA_SLSKD_BINARY"):
        monkeypatch.delenv(var, raising=False)
    yield

@pytest.fixture()
def no_cover_mp3(tmp_path, real_lib) -> str:
    """MP3 z gwarancją braku okładki — tworzony na kopii.

    Nie polegamy na tym, że któryś plik w bibliotece użytkownika akurat
    nie ma okładki: użytkownik może ją dociągnąć (i dociągnął).
    """
    src = os.path.join(real_lib, GOOD_MP3)
    if not os.path.isfile(src):
        pytest.skip("brak pliku referencyjnego")
    dst = tmp_path / "bez-okladki.mp3"
    fast_copy(src, str(dst))
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        tags = ID3(str(dst))
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.save(str(dst))
    return str(dst)
