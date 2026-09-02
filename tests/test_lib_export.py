"""Testy selekta.dj_export — collect + eksport do rekordbox XML / M3U8 /
Serato .crate (parsowanie prawdziwych formatów wyjściowych)."""
from __future__ import annotations

import os
import shutil
import struct
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import pytest

from selekta import dj_export
from tests.conftest import DUP_WAV, GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3

DUP_WAV_NAME = "Odymel - Gucci.wav"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lib_dir(tmp_path_factory, real_lib) -> str:
    tmp = tmp_path_factory.mktemp("export-lib")
    for name in (GOOD_FLAC, GOOD_MP3, MOJIBAKE_MP3):
        p = os.path.join(real_lib, name)
        if not os.path.isfile(p):
            pytest.skip(f"brak pliku referencyjnego: {name}")
        shutil.copy(p, tmp / name)
    dup = os.path.join(real_lib, DUP_WAV)
    if not os.path.isfile(dup):
        pytest.skip(f"brak pliku referencyjnego: {DUP_WAV}")
    shutil.copy(dup, tmp / DUP_WAV_NAME)
    return str(tmp)


@pytest.fixture(scope="module")
def tracks(lib_dir) -> list[dict]:
    return dj_export.collect(lib_dir)


def _parse_chunks(blob: bytes) -> list[tuple[bytes, bytes]]:
    """Chunki '<4s tag><uint32 len><payload>' (big-endian), całość bez reszty."""
    out: list[tuple[bytes, bytes]] = []
    i = 0
    while i < len(blob):
        tag = blob[i:i + 4]
        (length,) = struct.unpack(">I", blob[i + 4:i + 8])
        out.append((tag, blob[i + 8:i + 8 + length]))
        i += 8 + length
    assert i == len(blob), "chunki nie pokrywają całego pliku"
    return out


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

def test_collect_reads_tags(tracks, lib_dir):
    assert len(tracks) == 4
    by_name = {os.path.basename(t["path"]): t for t in tracks}
    flac = by_name[GOOD_FLAC]
    assert flac["artist"] == "Odymel"
    assert flac["title"] == "Gucci"
    assert flac["duration_s"] == pytest.approx(273.7, abs=0.5)
    assert os.path.isabs(flac["path"])
    mp3 = by_name[GOOD_MP3]
    assert mp3["artist"] == "mischluft, Sachsentrance"
    assert mp3["title"] == "We are Energy"
    # WAV nosi TKEY=8A, mojibake MP3 nosi TBPM=152
    assert by_name[DUP_WAV_NAME]["key"] == "8A"
    assert by_name[MOJIBAKE_MP3]["bpm"] == pytest.approx(152.0)


def test_collect_empty_and_missing_folder(tmp_path):
    assert dj_export.collect(str(tmp_path)) == []
    with pytest.raises(FileNotFoundError):
        dj_export.collect(str(tmp_path / "nie-ma"))


# --------------------------------------------------------------------------
# rekordbox XML
# --------------------------------------------------------------------------

def test_rekordbox_xml_structure(tracks, tmp_path):
    out = str(tmp_path / "playlista.xml")
    assert dj_export.to_rekordbox_xml(tracks, "Moja playlista", out) == out

    root = ET.parse(out).getroot()          # parsowalny XML
    assert root.tag == "DJ_PLAYLISTS"
    assert root.get("Version") == "1.0.0"

    coll = root.find("COLLECTION")
    entries = coll.findall("TRACK")
    assert coll.get("Entries") == str(len(tracks)) == "4"
    assert len(entries) == len(tracks)

    for i, (el, track) in enumerate(zip(entries, tracks), start=1):
        assert el.get("TrackID") == str(i)
        assert el.get("Name") == track["title"]
        assert el.get("Artist") == track["artist"]
        loc = el.get("Location")
        assert loc.startswith("file://localhost/")
        decoded = unquote(loc[len("file://localhost"):])
        assert decoded == track["path"]
        assert os.path.isfile(decoded)      # odkodowana ścieżka istnieje
        assert el.get("TotalTime") == str(int(round(track["duration_s"])))

    node = root.find("PLAYLISTS/NODE/NODE")
    assert node.get("Name") == "Moja playlista"
    assert node.get("Entries") == "4"
    keys = [t.get("Key") for t in node.findall("TRACK")]
    assert keys == ["1", "2", "3", "4"]     # kolejność playlisty = wejściowa


def test_rekordbox_xml_empty(tmp_path):
    out = str(tmp_path / "pusta.xml")
    dj_export.to_rekordbox_xml([], "Pusta", out)
    root = ET.parse(out).getroot()
    assert root.get("Version") == "1.0.0"
    assert root.find("COLLECTION").get("Entries") == "0"
    assert root.find("COLLECTION").findall("TRACK") == []
    node = root.find("PLAYLISTS/NODE/NODE")
    assert node.get("Name") == "Pusta"
    assert node.findall("TRACK") == []


# --------------------------------------------------------------------------
# M3U8
# --------------------------------------------------------------------------

def test_m3u8_two_lines_per_track(tracks, tmp_path):
    out = str(tmp_path / "lista.m3u8")
    assert dj_export.to_m3u8(tracks, out) == out
    with open(out, encoding="utf-8") as fh:
        content = fh.read()
    lines = content.rstrip("\n").split("\n")
    assert lines[0] == "#EXTM3U"
    assert len(lines) == 1 + 2 * len(tracks)
    for i, track in enumerate(tracks):
        info, path = lines[1 + 2 * i], lines[2 + 2 * i]
        seconds = int(round(track["duration_s"]))
        assert info == f"#EXTINF:{seconds},{track['artist']} - {track['title']}"
        assert path == track["path"]
        assert os.path.isfile(path)


def test_m3u8_empty(tmp_path):
    out = str(tmp_path / "pusta.m3u8")
    dj_export.to_m3u8([], out)
    with open(out, encoding="utf-8") as fh:
        assert fh.read() == "#EXTM3U\n"


# --------------------------------------------------------------------------
# Serato crate
# --------------------------------------------------------------------------

def test_serato_crate_chunks(tracks, tmp_path):
    out = str(tmp_path / "selekta.crate")
    assert dj_export.to_serato_crate(tracks, out) == out
    with open(out, "rb") as fh:
        blob = fh.read()
    assert blob[:4] == b"vrsn"

    chunks = _parse_chunks(blob)
    assert chunks[0][0] == b"vrsn"
    assert chunks[0][1].decode("utf-16-be") == "1.0/Serato ScratchLive Crate"

    otrks = [payload for tag, payload in chunks if tag == b"otrk"]
    assert len(otrks) == len(tracks) == 4
    for payload, track in zip(otrks, tracks):
        inner = _parse_chunks(payload)
        assert len(inner) == 1
        tag, ptrk = inner[0]
        assert tag == b"ptrk"
        rel = ptrk.decode("utf-16-be")
        assert not rel.startswith("/")
        assert "/" + rel == track["path"]   # ścieżka względem korzenia wolumenu
    # poza vrsn i otrk nie ma innych chunków najwyższego poziomu
    assert {tag for tag, _ in chunks} == {b"vrsn", b"otrk"}


def test_serato_crate_empty(tmp_path):
    out = str(tmp_path / "pusty.crate")
    dj_export.to_serato_crate([], out)
    with open(out, "rb") as fh:
        blob = fh.read()
    version = "1.0/Serato ScratchLive Crate"
    assert blob == b"vrsn" + struct.pack(">I", 2 * len(version)) + version.encode("utf-16-be")
    assert len(blob) == 8 + 2 * len(version)


def test_install_serato_crate_sanitizes_name(tracks, tmp_path):
    root = str(tmp_path / "biblioteka")
    path = dj_export.install_serato_crate(tracks, root, crate_name='moja/pl:ay*lista')
    assert path == os.path.join(root, "_Serato_", "Subcrates", "mojaplaylista.crate")
    with open(path, "rb") as fh:
        assert fh.read(4) == b"vrsn"


def test_track_from_file_nonexistent_falls_back_to_filename(tmp_path):
    p = str(tmp_path / "Ktoś - Coś (Remix).mp3")
    track = dj_export.track_from_file(p)
    assert track["artist"] == "Ktoś"
    assert track["title"] == "Coś (Remix)"
    assert track["duration_s"] == 0.0
    assert track["bpm"] is None and track["key"] is None


class TestSiatkaWEksporcie:
    """Bez elementu TEMPO rekordbox liczy siatkę po swojemu i nasza przepada."""

    def _xml(self, tmp_path, **dodatkowe):
        from selekta import dj_export
        import xml.etree.ElementTree as ET
        track = {"path": str(tmp_path / "u.flac"), "title": "T", "artist": "A",
                 "duration_s": 200.0, "bpm": 150.0, "key": "8A"}
        track.update(dodatkowe)
        out = str(tmp_path / "set.xml")
        dj_export.to_rekordbox_xml([track], "set", out)
        return ET.parse(out).getroot()

    def test_zapisuje_kotwice_beatgridu(self, tmp_path):
        root = self._xml(tmp_path, first_beat_s=1.793)
        tempo = root.find(".//COLLECTION/TRACK/TEMPO")
        assert tempo is not None, "brak elementu TEMPO — rekordbox zgadnie siatkę"
        assert tempo.get("Inizio") == "1.793"
        assert tempo.get("Bpm") == "150.00"
        assert tempo.get("Battito") == "1"

    def test_bez_kotwicy_nie_zmyslamy_siatki(self, tmp_path):
        assert self._xml(tmp_path).find(".//COLLECTION/TRACK/TEMPO") is None

    def test_zapisuje_punkty_cue(self, tmp_path):
        root = self._xml(tmp_path, first_beat_s=0.5, intro_end_s=32.0,
                         drop_s=64.0, outro_start_s=180.0)
        marki = {m.get("Name"): m.get("Start")
                 for m in root.findall(".//COLLECTION/TRACK/POSITION_MARK")}
        assert marki == {"intro": "32.000", "drop": "64.000", "outro": "180.000"}

    def test_brakujacy_drop_nie_tworzy_pustej_marki(self, tmp_path):
        root = self._xml(tmp_path, first_beat_s=0.5, intro_end_s=32.0,
                         drop_s=None, outro_start_s=180.0)
        nazwy = {m.get("Name")
                 for m in root.findall(".//COLLECTION/TRACK/POSITION_MARK")}
        assert nazwy == {"intro", "outro"}

    def test_kotwica_w_zerze_jest_poprawna(self, tmp_path):
        """Utwór może zaczynać się dokładnie na uderzeniu — 0.0 to nie brak."""
        root = self._xml(tmp_path, first_beat_s=0.0)
        tempo = root.find(".//COLLECTION/TRACK/TEMPO")
        assert tempo is not None and tempo.get("Inizio") == "0.000"

    def test_ujemna_kotwica_jest_odrzucana(self, tmp_path):
        """Ujemny czas to błędne dane — lepiej nic, niż zła siatka."""
        assert self._xml(tmp_path, first_beat_s=-0.4).find(
            ".//COLLECTION/TRACK/TEMPO") is None


def test_ponowny_install_ze_znakiem_and_jest_idempotentny(tmp_path, monkeypatch):
    """Regresja z 1.09.2026: imported_library() oddawało ścieżkę w formie
    escapowanej ('&amp;'), więc ponowny install tej samej playlisty z '&'
    w nazwie nie poznawał własnego wpisu i podpinał ją od nowa."""
    from selekta import rekordbox
    ustawienia = tmp_path / "MASTER.SETTING.xml"
    ustawienia.write_text(
        f'<PROPERTIES><VALUE name="{rekordbox.KEY}" val=""/></PROPERTIES>',
        encoding="utf-8")
    monkeypatch.setattr(rekordbox, "settings_path", lambda: str(ustawienia))
    monkeypatch.setattr(rekordbox, "is_running", lambda: False)
    xml = tmp_path / "Moje sety & selekty.xml"
    xml.write_text("<DJ_PLAYLISTS/>", encoding="utf-8")

    pierwszy = rekordbox.install(str(xml))
    assert pierwszy.ok and "była już" not in pierwszy.message
    assert rekordbox.imported_library() == str(xml), "ma wrócić surowa ścieżka"
    drugi = rekordbox.install(str(xml))
    assert drugi.ok and "była już podpięta" in drugi.message, (
        f"drugi install ścieżki z '&' ma poznać własny wpis: {drugi.message}")
