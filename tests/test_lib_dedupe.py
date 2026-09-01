"""Testy selekta.dedupe — plan/apply/format_plan na kopii biblioteki."""
from __future__ import annotations

import os

import pytest

from selekta import dedupe
from tests.conftest import GOOD_FLAC

DUP_WAV_NAME = "Odymel - Gucci.wav"


def _require_pair(lib_copy) -> tuple[str, str]:
    """(ścieżka FLAC, ścieżka WAV) w lib_copy; skip gdy któregoś brak."""
    flac = os.path.join(lib_copy, GOOD_FLAC)
    wav = os.path.join(lib_copy, DUP_WAV_NAME)
    if not (os.path.isfile(flac) and os.path.isfile(wav)):
        pytest.skip("lib_copy nie zawiera pary FLAC+WAV")
    return flac, wav


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def test_plan_keeps_flac_removes_wav(lib_copy):
    flac, wav = _require_pair(lib_copy)
    actions = dedupe.plan(lib_copy)
    assert len(actions) == 1
    action = actions[0]
    assert action.keep == flac
    assert action.remove == [wav]
    assert action.suspect is False
    # uzasadnienie po polsku, wskazujące regułę kontenera bezstratnego
    assert action.reason == (
        "zachowano FLAC jako preferowany kontener bezstratny nad WAV, "
        "ta sama głębia 16-bit"
    )
    assert action.reclaim_bytes == os.path.getsize(wav)
    assert "FLAC" in action.keep_desc
    assert len(action.remove_desc) == 1 and "WAV" in action.remove_desc[0]


def test_plan_empty_folder(tmp_path):
    assert dedupe.plan(str(tmp_path)) == []


# --------------------------------------------------------------------------
# format_plan
# --------------------------------------------------------------------------

def test_format_plan_lists_keep_and_remove(lib_copy):
    flac, wav = _require_pair(lib_copy)
    actions = dedupe.plan(lib_copy)
    text = dedupe.format_plan(actions)
    assert "Plan rozwiązania duplikatów" in text
    assert "→ zachowaj:" in text
    assert "do kosza:" in text
    assert flac in text
    assert wav in text
    assert "do odzyskania:" in text


def test_format_plan_empty():
    assert dedupe.format_plan([]) == "Brak duplikatów do rozwiązania. ✅"


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def test_apply_moves_remove_to_trash(lib_copy, tmp_path):
    flac, wav = _require_pair(lib_copy)
    wav_size = os.path.getsize(wav)
    trash = str(tmp_path / "kosz")

    actions = dedupe.plan(lib_copy)
    result = dedupe.apply(actions, trash)

    # keep nietknięty, remove przeniesiony (nie skasowany)
    assert os.path.isfile(flac)
    assert not os.path.exists(wav)
    assert os.listdir(trash) == [DUP_WAV_NAME]
    assert result["błędy"] == []
    assert result["przeniesione"] == [(wav, os.path.join(trash, DUP_WAV_NAME))]
    assert result["odzyskane_MB"] == round(wav_size / 1_000_000, 2)
    assert result["odzyskane_MB"] > 0
    assert os.path.getsize(os.path.join(trash, DUP_WAV_NAME)) == wav_size


def test_apply_trash_name_collision(lib_copy, tmp_path):
    _, wav = _require_pair(lib_copy)
    trash = tmp_path / "kosz"
    trash.mkdir()
    (trash / DUP_WAV_NAME).write_bytes(b"zajete")  # kolizja nazwy w koszu

    result = dedupe.apply(dedupe.plan(lib_copy), str(trash))

    assert result["błędy"] == []
    (src, dest), = result["przeniesione"]
    assert src == wav
    stem, ext = os.path.splitext(DUP_WAV_NAME)
    assert os.path.basename(dest) == f"{stem} (1){ext}"
    # istniejący plik w koszu nie został nadpisany
    assert (trash / DUP_WAV_NAME).read_bytes() == b"zajete"


def test_apply_missing_file_reports_error(tmp_path):
    keep = tmp_path / "keep.flac"
    keep.write_bytes(b"flac")
    missing = str(tmp_path / "nie-ma.wav")
    action = dedupe.DupAction(keep=str(keep), remove=[missing], reason="test")

    result = dedupe.apply([action], str(tmp_path / "kosz"))

    assert result["przeniesione"] == []
    assert result["odzyskane_MB"] == 0.0
    assert result["błędy"] == [(missing, "plik nie istnieje")]
    assert keep.is_file()


def test_apply_never_moves_keep(tmp_path):
    keep = tmp_path / "keep.flac"
    keep.write_bytes(b"flac")
    # celowo błędna akcja: remove wskazuje na keep
    action = dedupe.DupAction(keep=str(keep), remove=[str(keep)], reason="test")

    result = dedupe.apply([action], str(tmp_path / "kosz"))

    assert keep.is_file()
    assert result["przeniesione"] == []
    assert len(result["błędy"]) == 1
    path, reason = result["błędy"][0]
    assert path == str(keep)
    assert "keep" in reason


def test_apply_empty_actions(tmp_path):
    trash = str(tmp_path / "kosz")
    result = dedupe.apply([], trash)
    assert result == {"przeniesione": [], "odzyskane_MB": 0.0, "błędy": []}
    assert os.path.isdir(trash)  # kosz tworzony na zapas
