"""Integralność pliku: ucięte transfery muszą być wykrywane zawsze.

Przegląd 0.4.2: ucięty MP3 wykryty tylko w 38 na 75 losowych ucięć —
plik z połową danych dostawał „dekoduje się bez błędów”, bo ffmpeg nie
zgłasza błędu, gdy strumień urywa się na granicy ramki. Odpowiedź znamy
z góry: ucinamy sami, więc wiemy, ile brakuje.
"""
from __future__ import annotations

import os
import random
import subprocess

import pytest

from selekta import integralnosc, pipeline
from tests import probka


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def pliki(tmp_path_factory):
    d = tmp_path_factory.mktemp("integr")
    wav = probka.bit_klubowy(str(d / "src.wav"), 128.0, 0.5, sekund=40.0, hihat=0.5)
    out = {"wav": wav}
    for nazwa, args in (("mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]),
                        ("mp3_v0", ["-c:a", "libmp3lame", "-q:a", "0"]),
                        ("mp3_bez_xing", ["-c:a", "libmp3lame", "-b:a", "128k", "-write_xing", "0"]),
                        ("flac", ["-c:a", "flac"]),
                        ("m4a", ["-c:a", "aac", "-b:a", "192k"])):
        ext = {"mp3": ".mp3", "mp3_v0": ".mp3", "mp3_bez_xing": ".mp3", "flac": ".flac", "m4a": ".m4a"}[nazwa]
        p = str(d / f"{nazwa}{ext}")
        _ff("-i", wav, *args, p)
        out[nazwa] = p
    return out


def _utnij(src: str, dst: str, ile_bajtow: int) -> str:
    with open(src, "rb") as fh:
        dane = fh.read()
    with open(dst, "wb") as fh:
        fh.write(dane[:ile_bajtow])
    return dst


@pytest.mark.parametrize("nazwa", ["wav", "mp3", "mp3_v0", "mp3_bez_xing", "flac", "m4a"])
def test_zdrowe_pliki_przechodza(pliki, nazwa):
    w = integralnosc.zbadaj(pliki[nazwa])
    assert w.ok, w.opis
    assert integralnosc.problem(pliki[nazwa]) is None


def test_mp3_z_polowa_danych_jest_uciety(pliki, tmp_path):
    """Dokładnie przypadek z przeglądu: połowa bajtów, zero błędów dekodera."""
    p = _utnij(pliki["mp3"], str(tmp_path / "pol.mp3"), os.path.getsize(pliki["mp3"]) // 2)
    w = integralnosc.zbadaj(p)
    assert not w.ok
    assert w.gdzie == "koniec"
    assert "brakuje końca" in w.opis
    assert w.deklarowane_s - w.zdekodowane_s > 15


@pytest.mark.parametrize("nazwa", ["mp3", "mp3_v0", "mp3_bez_xing"])
def test_losowe_uciecia_mp3_zawsze_wykryte(pliki, tmp_path, nazwa):
    rnd = random.Random(7)
    rozmiar = os.path.getsize(pliki[nazwa])
    for i in range(12):
        frac = rnd.uniform(0.30, 0.97)            # brakuje co najmniej ~1 s
        p = _utnij(pliki[nazwa], str(tmp_path / f"c{i}.mp3"), int(rozmiar * frac))
        w = integralnosc.zbadaj(p)
        assert not w.ok, (nazwa, frac, w.opis)
        assert w.gdzie == "koniec", (nazwa, frac, w.opis)


def test_mp3_bez_naglowka_z_urwanym_naglowkiem_ramki(pliki, tmp_path):
    """Ucięcie zostawiające 2 bajty nagłówka kolejnej ramki."""
    with open(pliki["mp3_bez_xing"], "rb") as fh:
        dane = fh.read()
    i = dane.index(b"\xff\xfb", len(dane) // 2)      # początek ramki w połowie pliku
    while integralnosc._naglowek_ramki(dane, i) is None:
        i = dane.index(b"\xff\xfb", i + 1)
    p = _utnij(pliki["mp3_bez_xing"], str(tmp_path / "h.mp3"), i + 2)
    w = integralnosc.zbadaj(p)
    assert not w.ok and w.gdzie == "koniec", w.opis


def test_m4a_uciety_opisany_jako_koniec(pliki, tmp_path):
    """Przegląd 0.4.2: ucięcia M4A opisywane „w środku utworu”, bo ffprobe
    zwracał 0 s — długość bierzemy z nagłówka mvhd."""
    p = _utnij(pliki["m4a"], str(tmp_path / "u.m4a"), int(os.path.getsize(pliki["m4a"]) * 0.6))
    w = integralnosc.zbadaj(p)
    assert not w.ok
    assert "przy końcu" in w.opis


def test_flac_z_bledna_suma_md5(pliki, tmp_path):
    """Dźwięk dekoduje się, ale nie zgadza się z sumą w STREAMINFO."""
    from mutagen.flac import FLAC
    p = str(tmp_path / "md5.flac")
    _ff("-i", pliki["flac"], "-af", "volume=0.5", "-c:a", "flac", p)
    wzor = FLAC(pliki["flac"]).info.md5_signature
    # podmień sumę na tę z innego dźwięku (bajty 26..42 bloku STREAMINFO)
    with open(p, "r+b") as fh:
        dane = bytearray(fh.read())
        off = dane.index(b"fLaC") + 4 + 4 + 18
        dane[off:off + 16] = wzor.to_bytes(16, "big")
        fh.seek(0)
        fh.write(dane)
    w = integralnosc.zbadaj(p)
    assert not w.ok
    assert "MD5" in w.opis


def test_wav_uciety(pliki, tmp_path):
    p = _utnij(pliki["wav"], str(tmp_path / "u.wav"), int(os.path.getsize(pliki["wav"]) * 0.7))
    w = integralnosc.zbadaj(p)
    assert not w.ok and w.gdzie == "koniec"


def test_bramka_pobran_oblewa_uciety_mp3(pliki, tmp_path):
    p = _utnij(pliki["mp3"], str(tmp_path / "pol.mp3"), os.path.getsize(pliki["mp3"]) // 2)
    c = pipeline.integrity(p)
    assert c.passed is False and c.critical is True
    assert "ucięty" in c.detail


def test_odmiana_liczby_bledow():
    assert integralnosc._bledow(1) == "błąd"
    assert integralnosc._bledow(4) == "błędy"
    assert integralnosc._bledow(5) == "błędów"
    assert integralnosc._bledow(12) == "błędów"
    assert integralnosc._bledow(22) == "błędy"
