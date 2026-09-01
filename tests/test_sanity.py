"""Sanity: infrastruktura testowa działa, fixtures wskazują realne pliki."""
from tests.conftest import GOOD_FLAC


def test_sample_resolves(sample):
    assert sample(GOOD_FLAC).endswith(".flac")


def test_lib_copy_isolated(lib_copy, real_lib):
    import os
    assert lib_copy != real_lib
    assert any(f.endswith(".flac") for f in os.listdir(lib_copy))


def test_state_isolated():
    from selekta import wishlist
    assert ".selekta" not in wishlist.STATE_PATH or "pytest" in wishlist.STATE_PATH
