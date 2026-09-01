"""Bezpieczeństwo API — traversal, złe parametry, odporność."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from selekta import web


@pytest.fixture()
def client(lib_copy):
    web.set_folder(lib_copy)
    web._HEALTH_CACHE.update(sig=None, report=None)
    return TestClient(web.app)


TRAVERSALS = [
    "../../../etc/passwd",
    "..%2F..%2F..%2Fetc%2Fpasswd",
    "/etc/passwd",
    "....//....//etc/passwd",
]


@pytest.mark.parametrize("path", TRAVERSALS)
@pytest.mark.parametrize("endpoint", ["/api/track", "/api/cover", "/api/analyze"])
def test_traversal_blocked(client, endpoint, path):
    method = client.post if endpoint == "/api/analyze" else client.get
    r = method(endpoint, params={"file": path})
    assert r.status_code in (400, 404), f"{endpoint} {path} -> {r.status_code}"


@pytest.mark.parametrize("endpoint", ["/api/track", "/api/cover", "/api/analyze"])
def test_empty_file_param(client, endpoint):
    method = client.post if endpoint == "/api/analyze" else client.get
    assert method(endpoint, params={"file": ""}).status_code == 400
    assert method(endpoint, params={"file": "   "}).status_code == 400


def test_missing_file_404_not_500(client):
    assert client.get("/api/track", params={"file": "widmo.flac"}).status_code == 404


def test_directory_is_not_a_file(client, lib_copy):
    import os
    os.makedirs(os.path.join(lib_copy, "podfolder.flac"), exist_ok=True)
    r = client.get("/api/track", params={"file": "podfolder.flac"})
    assert r.status_code == 404  # katalog nie przechodzi jako plik


def test_import_wrong_body_types(client):
    # brak body / złe typy nie mogą dać 500
    assert client.post("/api/import", json={}).status_code == 400
    assert client.post("/api/import", json={"text": None}).status_code in (400, 422)


def test_usb_dest_does_not_touch_source_library(client, tmp_path, lib_copy):
    # UWAGA: lib_copy i tmp_path tego testu to TEN SAM katalog pytest —
    # dest musi być rodzeństwem, nie dzieckiem biblioteki
    import os
    dest = str(tmp_path.parent / "usb-dest-security")
    before = sorted(os.listdir(lib_copy))
    r = client.post("/api/usb", json={"dest": dest, "convert": "keep"})
    assert r.status_code == 200
    assert sorted(os.listdir(lib_copy)) == before  # źródło nietknięte
