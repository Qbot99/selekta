"""`selekta icons --clear` zdejmuje tylko ikony postawione przez selektę.

Przed naprawą kasował cały com.apple.FinderInfo każdego pliku FLAC/WAV — także
cudze ikony i kolorowe etykiety Findera.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from selekta import finder_icons

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="tylko macOS")

ETYKIETA_I_IKONA = bytes(8) + (0x0400 | 0x000C).to_bytes(2, "big") + bytes(22)


def _fi(path):
    r = subprocess.run(["xattr", "-px", "com.apple.FinderInfo", path],
                       capture_output=True, text=True)
    return bytes.fromhex("".join(r.stdout.split())) if r.returncode == 0 else None


def _ustaw(path, nasza: bool):
    subprocess.run(["xattr", "-wx", "com.apple.FinderInfo", ETYKIETA_I_IKONA.hex(), path],
                   check=True)
    subprocess.run(["xattr", "-wx", "com.apple.ResourceFork", "00", path], check=True)
    if nasza:
        subprocess.run(["xattr", "-w", finder_icons.MARKER, "1", path], check=True)


def test_clear_zostawia_cudze_ikony_i_etykiety(tmp_path):
    nasz = tmp_path / "nasz.flac"; nasz.write_bytes(b"x")
    cudzy = tmp_path / "cudzy.flac"; cudzy.write_bytes(b"x")
    _ustaw(str(nasz), nasza=True)
    _ustaw(str(cudzy), nasza=False)
    assert finder_icons.clear([str(nasz), str(cudzy)]) == 1
    # cudzy plik: bez zmian
    assert _fi(str(cudzy)) == ETYKIETA_I_IKONA
    # nasz: ikona zdjęta, kolorowa etykieta została
    fi = _fi(str(nasz))
    flagi = int.from_bytes(fi[8:10], "big")
    assert flagi & 0x0400 == 0 and flagi & 0x000C == 0x000C
    assert not finder_icons.nasza(str(nasz))
