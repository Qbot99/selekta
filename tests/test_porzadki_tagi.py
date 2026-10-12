"""Naprawa tagów — regresje z przeglądu 0.4.2 (pliki syntetyczne).

Przed naprawą: drugi artysta z tagu wielowartościowego znikał, napisy mieszane
(krzaczki obok poprawnych liter) nie były wykrywane, skan szedł tylko jeden
poziom w głąb i przeglądał kosz, zapis kasował policzone analizy (mtime w kluczu
pamięci) i po cichu podnosił ID3 do v2.4.
"""
from __future__ import annotations

import os

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TPE1

from selekta import cache, tagfix
from tests.syntetyczne import utwor


def test_drugi_artysta_nie_znika(tmp_path):
    p = utwor(str(tmp_path / "x.flac"), "A", "T")
    a = FLAC(p)
    a["ARTIST"] = ["KsiÄ™ĹĽyc", "Fēlēs"]
    a.save()
    zmiany = tagfix.fix_file(p, dry_run=False)
    assert zmiany == [("ARTIST", "KsiÄ™ĹĽyc; Fēlēs", "Księżyc; Fēlēs")]
    assert FLAC(p)["ARTIST"] == ["Księżyc", "Fēlēs"]


def test_napis_mieszany_jest_wykrywany_i_naprawiany(tmp_path):
    p = utwor(str(tmp_path / "x.mp3"), "Ã…MRTÃœM & Öwes", "Dash")
    hits = tagfix.scan(str(tmp_path))
    assert hits == [(p, "ARTIST", "Ã…MRTÃœM & Öwes", "ÅMRTÜM & Öwes")]


def test_zakres_jak_lista_utworow_bez_kosza(tmp_path):
    gleboko = utwor(str(tmp_path / "Album" / "CD1" / "a.mp3"), "Ã…MRTÃœM", "A")
    w_koszu = utwor(str(tmp_path / "_selekta_kosz" / "b.mp3"), "Ã…MRTÃœM", "B")
    pliki = {h[0] for h in tagfix.scan(str(tmp_path))}
    assert gleboko in pliki
    assert w_koszu not in pliki


def test_analizy_przetrwaja_naprawe(tmp_path):
    p = utwor(str(tmp_path / "x.flac"), "Ã…MRTÃœM", "T")
    cache.put(p, "harmonic", {"bpm": 128.0, "camelot": "8A"})
    tagfix.fix_file(p, dry_run=False)
    assert cache.get(p, "harmonic") == {"bpm": 128.0, "camelot": "8A"}


def test_wersja_id3_zostaje(tmp_path):
    p = utwor(str(tmp_path / "x.mp3"), None, "T")
    t = ID3(p)
    t.add(TPE1(encoding=1, text="Ã…MRTÃœM"))
    t.save(p, v2_version=3)
    tagfix.fix_file(p, dry_run=False)
    t = ID3(p)
    assert t.version[:2] == (2, 3)
    assert str(t["TPE1"]) == "ÅMRTÜM"


def test_api_naprawia_tez_kopie_w_secie(tmp_path):
    from fastapi.testclient import TestClient
    from selekta import uklad, web
    from tests.syntetyczne import set_z
    uklad.zapomnij()
    lib = tmp_path / "lib"
    p = utwor(str(lib / "amrtum - dash.mp3"), "Ã…MRTÃœM", "Dash")
    (k,) = set_z(str(lib), "speeding", [p])
    web.set_folder(str(lib))
    c = TestClient(web.app)
    hits = c.get("/api/tagfix").json()["hits"]
    assert [h["file"] for h in hits] == ["amrtum - dash.mp3"]   # utwór raz, nie dwa
    r = c.post("/api/tagfix/apply").json()
    assert r["fixed"] == 1 and r["kopii"] == 1
    assert str(ID3(k)["TPE1"]) == "ÅMRTÜM"
    assert c.get("/api/tagfix").json()["hits"] == []


def test_poprawne_napisy_nietkniete():
    for t in ("Öwes", "Zażółć gęślą jaźń", "MĂŞTI", "Fēlēs", "Âme", "Tiësto", "Dvořák",
              "Sipińska", "Łódź", "CÂŞTIG"):
        assert tagfix.repair(t) == t, t
