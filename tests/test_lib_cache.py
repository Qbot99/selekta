"""Testy selekta.cache — trwały cache wyników analizy audio.

CACHE_DIR jest per-test przekierowany do katalogu tymczasowego przez
autouse fixture `_isolate_user_state` z conftest.
"""
from __future__ import annotations

import json
import os
import threading

import pytest

from selekta import cache


@pytest.fixture()
def audio_file(tmp_path) -> str:
    p = tmp_path / "utwór ż.flac"     # unicode w nazwie pliku
    p.write_bytes(b"fLaC" + b"\x00" * 128)
    return str(p)


def _store(kind_filename: str) -> dict:
    with open(os.path.join(cache.CACHE_DIR, kind_filename), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# roundtrip + unieważnianie
# --------------------------------------------------------------------------

def test_put_get_roundtrip(audio_file):
    data = {"bpm": 146.0, "key": "8A", "lista": [1, 2, 3], "zagn": {"a": None}}
    assert cache.get(audio_file, "harmonic") is None   # przed zapisem
    cache.put(audio_file, "harmonic", data)
    assert cache.get(audio_file, "harmonic") == data
    # kopertowy JSON na dysku: kind + wpis z odciskiem pliku
    store = _store("harmonic.json")
    assert store["kind"] == "harmonic"
    (entry,) = store["entries"].values()
    st = os.stat(audio_file)
    assert entry["path"] == os.path.abspath(audio_file)
    assert entry["mtime_ns"] == st.st_mtime_ns
    assert entry["size"] == st.st_size
    assert entry["data"] == data


def test_get_none_after_mtime_change(audio_file):
    cache.put(audio_file, "harmonic", {"bpm": 146.0})
    assert cache.get(audio_file, "harmonic") is not None
    os.utime(audio_file, (1_000_000_000, 1_000_000_000))   # "podmiana" pliku
    assert cache.get(audio_file, "harmonic") is None


def test_get_none_after_content_change(audio_file):
    cache.put(audio_file, "quality", {"grade": "ok"})
    with open(audio_file, "wb") as fh:
        fh.write(b"inne dane o innym rozmiarze")
    assert cache.get(audio_file, "quality") is None


def test_get_nonexistent_file_returns_none(tmp_path):
    assert cache.get(str(tmp_path / "nie-ma.flac"), "harmonic") is None


def test_put_nonexistent_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        cache.put(str(tmp_path / "nie-ma.flac"), "harmonic", {"x": 1})


def test_put_unserializable_data_raises(audio_file):
    with pytest.raises(TypeError):
        cache.put(audio_file, "harmonic", {"zbior": {1, 2}})
    # nieudany zapis nie zostawia wpisu ani pliku tymczasowego
    assert cache.get(audio_file, "harmonic") is None
    leftovers = [n for n in os.listdir(cache.CACHE_DIR) if n.endswith(".tmp")]
    assert leftovers == []


def test_key_for_changes_with_mtime(audio_file):
    k1 = cache.key_for(audio_file)
    assert isinstance(k1, str) and len(k1) == 32
    os.utime(audio_file, (1_000_000_000, 1_000_000_000))
    assert cache.key_for(audio_file) != k1
    with pytest.raises(OSError):
        cache.key_for(audio_file + ".brak")


def test_put_prunes_stale_fingerprints(audio_file):
    cache.put(audio_file, "harmonic", {"v": 1})
    os.utime(audio_file, (1_000_000_000, 1_000_000_000))
    cache.put(audio_file, "harmonic", {"v": 2})
    store = _store("harmonic.json")
    assert len(store["entries"]) == 1          # stary odcisk usunięty
    assert cache.get(audio_file, "harmonic") == {"v": 2}


# --------------------------------------------------------------------------
# clear / stats
# --------------------------------------------------------------------------

def test_clear_kind_and_all_counts(tmp_path):
    files = []
    for i in range(3):
        p = tmp_path / f"a{i}.mp3"
        p.write_bytes(b"x" * (10 + i))
        files.append(str(p))
    cache.put(files[0], "harmonic", {"i": 0})
    cache.put(files[1], "harmonic", {"i": 1})
    cache.put(files[2], "quality", {"grade": "ok"})

    assert cache.clear("harmonic") == 2
    assert cache.clear("harmonic") == 0        # już wyczyszczony
    assert cache.get(files[0], "harmonic") is None
    assert cache.get(files[2], "quality") == {"grade": "ok"}   # nietknięty
    assert cache.clear() == 1                  # zostało tylko quality
    assert cache.clear() == 0


def test_clear_on_missing_cache_dir():
    assert not os.path.isdir(cache.CACHE_DIR)  # nic jeszcze nie zapisano
    assert cache.clear() == 0
    assert cache.clear("harmonic") == 0


def test_stats(tmp_path):
    assert cache.stats() == {"_total_entries": 0, "_total_bytes": 0}
    for i in range(2):
        p = tmp_path / f"s{i}.mp3"
        p.write_bytes(b"y" * (5 + i))
        cache.put(str(p), "harmonic", {"i": i})
    p3 = tmp_path / "s3.mp3"
    p3.write_bytes(b"z")
    cache.put(str(p3), "loudness", {"lufs": -8.5})

    stats = cache.stats()
    assert stats["harmonic"] == 2
    assert stats["loudness"] == 1
    assert stats["_total_entries"] == 3
    assert stats["_total_bytes"] > 0
    assert stats["_total_bytes"] == sum(
        os.path.getsize(os.path.join(cache.CACHE_DIR, n))
        for n in os.listdir(cache.CACHE_DIR) if n.endswith(".json")
    )


# --------------------------------------------------------------------------
# dziwne nazwy kind
# --------------------------------------------------------------------------

def test_weird_kind_name(audio_file):
    kind = "a/b:c"
    cache.put(audio_file, kind, {"x": 1})
    assert cache.get(audio_file, kind) == {"x": 1}
    # plik na dysku to k_<md5>.json, a prawdziwa nazwa siedzi w środku
    names = os.listdir(cache.CACHE_DIR)
    assert len(names) == 1
    assert names[0].startswith("k_") and names[0].endswith(".json")
    assert "/" not in names[0] and ":" not in names[0]
    assert _store(names[0])["kind"] == kind
    assert cache.stats()[kind] == 1
    assert cache.clear(kind) == 1
    assert cache.get(audio_file, kind) is None


def test_unicode_kind_name(audio_file):
    cache.put(audio_file, "tonacja żółć", {"k": "8A"})
    assert cache.get(audio_file, "tonacja żółć") == {"k": "8A"}
    assert cache.stats()["tonacja żółć"] == 1


# --------------------------------------------------------------------------
# zapisy pod rząd / równoległe
# --------------------------------------------------------------------------

def test_many_sequential_puts_keep_valid_json(tmp_path):
    files = []
    for i in range(8):
        p = tmp_path / f"t{i}.mp3"
        p.write_bytes(b"q" * (20 + i))
        files.append(str(p))
    for i, p in enumerate(files):
        cache.put(p, "harmonic", {"i": i})

    store = _store("harmonic.json")          # poprawny JSON po 8 zapisach
    assert len(store["entries"]) == 8
    for i, p in enumerate(files):
        assert cache.get(p, "harmonic") == {"i": i}
    assert cache.stats()["_total_entries"] == 8


def test_parallel_puts_leave_valid_json(tmp_path):
    """Zapisy z wielu wątków: reguła 'ostatni wygrywa', plik zawsze spójny."""
    files = []
    for i in range(6):
        p = tmp_path / f"w{i}.mp3"
        p.write_bytes(b"r" * (30 + i))
        files.append(str(p))

    def worker(path: str, i: int) -> None:
        for j in range(5):
            cache.put(path, "harmonic", {"i": i, "j": j})

    threads = [threading.Thread(target=worker, args=(p, i))
               for i, p in enumerate(files)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    store = _store("harmonic.json")          # nieuszkodzony JSON
    assert store["kind"] == "harmonic"
    assert 1 <= len(store["entries"]) <= 6
    for entry in store["entries"].values():
        assert set(entry) >= {"path", "mtime_ns", "size", "data"}
        assert entry["data"]["j"] in range(5)   # kompletny, spójny wpis
    # brak plików tymczasowych po zakończeniu
    assert [n for n in os.listdir(cache.CACHE_DIR) if n.endswith(".tmp")] == []
    assert cache.stats()["_total_entries"] == len(store["entries"])
