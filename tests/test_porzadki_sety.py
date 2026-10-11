"""Kopie utworów w folderach setów to NIE są osobne utwory ani duplikaty.

Regresja z prawdziwej biblioteki (~/Music/selekta, 11.10.2026): sety tworzone
przez kreator leżą w folderze biblioteki i zawierają kopie utworów. dedupe.plan
chciał przenieść do kosza 201 plików, z czego 183 z folderów setów (speeding,
super, super2, super2.2, „DJ set 100lecie”, „Spotify · 5 wrz”), a biblioteka
pokazywała 277 plików przy ~79 utworach.
"""
from __future__ import annotations

import os

import pytest

from selekta import dedupe, health, matcher, uklad
from tests.syntetyczne import set_z, utwor


@pytest.fixture()
def biblioteka(tmp_path):
    """Biblioteka z dwoma setami.

    poza setami: Alfa - Jeden.flac, Alfa - Jeden.mp3 (prawdziwy duplikat,
    ta sama treść w gorszym formacie), album/Beta - Dwa.mp3;
    set „speeding”: kopie Alfy (flac) i Bety + Gamma - Trzy.flac (tylko w setach);
    set „super”: kopie Alfy (flac) i Gammy.
    """
    uklad.zapomnij()
    lib = tmp_path / "selekta"
    alfa = utwor(str(lib / "Alfa - Jeden.flac"), "Alfa", "Jeden", hz=330)
    alfa_mp3 = utwor(str(lib / "Alfa - Jeden.mp3"), "Alfa", "Jeden", hz=330)
    beta = utwor(str(lib / "album" / "Beta - Dwa.mp3"), "Beta", "Dwa", hz=550)
    gamma_src = utwor(str(tmp_path / "pobrane" / "Gamma - Trzy.flac"), "Gamma",
                      "Trzy", hz=770)
    sp = set_z(str(lib), "speeding", [alfa, beta, gamma_src])
    gamma = sp[2]
    set_z(str(lib), "super", [alfa, gamma])
    return {"lib": str(lib), "alfa": alfa, "alfa_mp3": alfa_mp3, "beta": beta,
            "gamma": gamma}


def _w_secie(path: str) -> bool:
    return any(part in ("speeding", "super") for part in path.split(os.sep))


def test_lista_biblioteki_liczy_utwory_nie_kopie(biblioteka):
    pliki = matcher.audio_files(biblioteka["lib"])
    nazwy = sorted(os.path.relpath(p, biblioteka["lib"]) for p in pliki)
    # Alfa ×2 (różne pliki), Beta, Gamma — Gamma raz, choć leży w dwóch setach
    assert len(pliki) == 4, nazwy
    assert sum(1 for n in nazwy if n.endswith("Gamma - Trzy.flac")) == 1
    assert biblioteka["alfa"] in pliki and biblioteka["beta"] in pliki
    # wszystkie pliki nadal osiągalne na żądanie
    assert len(matcher.audio_files(biblioteka["lib"], kopie_w_setach=True)) == 8


def test_uklad_wie_w_jakich_setach_jest_utwor(biblioteka):
    u = uklad.wczytaj(biblioteka["lib"])
    assert u.sety_utworu(biblioteka["alfa"]) == ["speeding", "super"]
    assert u.sety_utworu(biblioteka["beta"]) == ["speeding"]
    assert u.sety_utworu(biblioteka["alfa_mp3"]) == []
    gamma = [p for p in u.utwory if p.endswith("Gamma - Trzy.flac")][0]
    assert u.sety_utworu(gamma) == ["speeding", "super"]
    assert u.w_secie(gamma)


def test_kopia_w_secie_z_innymi_tagami_to_nadal_ten_sam_utwor(biblioteka):
    """Tag poprawiony tylko w oryginale nie robi z kopii osobnego utworu."""
    from tests.syntetyczne import taguj
    kopia = os.path.join(biblioteka["lib"], "super", "Alfa - Jeden.flac")
    taguj(kopia, "Alfa", "Jeden (poprawiony tag w kopii)")
    uklad.zapomnij()
    assert len(matcher.audio_files(biblioteka["lib"])) == 4


def test_plan_duplikatow_nie_rusza_setow(biblioteka):
    akcje = dedupe.plan(biblioteka["lib"])
    do_kosza = [p for a in akcje for p in a.remove]
    assert not [p for p in do_kosza if _w_secie(p)], do_kosza
    # prawdziwy duplikat poza setami nadal jest wykrywany
    assert do_kosza == [biblioteka["alfa_mp3"]]
    assert akcje[0].keep == biblioteka["alfa"]
    assert akcje[0].sety == ["speeding", "super"]


def test_plan_z_podejrzanymi_tez_nie_rusza_setow(biblioteka):
    akcje = dedupe.plan(biblioteka["lib"], include_suspect=True)
    assert not [p for a in akcje for p in a.remove if _w_secie(p)]


def test_apply_nie_przeniesie_pliku_z_setu_nawet_na_zyczenie(biblioteka):
    plik_setu = os.path.join(biblioteka["lib"], "speeding", "Alfa - Jeden.flac")
    akcja = dedupe.DupAction(keep=biblioteka["alfa"], remove=[plik_setu], reason="test")
    wynik = dedupe.apply([akcja], korzen=biblioteka["lib"])
    assert wynik["przeniesione"] == []
    assert os.path.isfile(plik_setu)
    assert "setu" in wynik["błędy"][0][1]


def test_zdrowie_liczy_utwory_i_nie_zglasza_kopii_w_setach(biblioteka):
    rep = health.scan(biblioteka["lib"])
    assert len(rep.files) == 4
    assert len(rep.duplicates) == 1
    grupa = rep.duplicates[0]
    assert sorted(f.path for f in grupa.files) == sorted(
        [biblioteka["alfa"], biblioteka["alfa_mp3"]])


def test_api_duplikaty_pokazuja_foldery_i_sety(biblioteka):
    from fastapi.testclient import TestClient
    from selekta import web
    web.set_folder(biblioteka["lib"])
    web._HEALTH_CACHE.update(sig=None, report=None)
    c = TestClient(web.app)
    d = c.get("/api/dedupe").json()
    assert len(d["actions"]) == 1
    a = d["actions"][0]
    # pełna ścieżka względem biblioteki — „zostaw” i „usuń” nie wyglądają identycznie
    assert a["keep"] == "Alfa - Jeden.flac"
    assert a["remove"] == ["Alfa - Jeden.mp3"]
    assert a["sety"] == ["speeding", "super"]
    t = c.get("/api/tracks").json()
    assert t["count"] == 4
    alfa = [r for r in t["tracks"] if r["rel"] == "Alfa - Jeden.flac"][0]
    assert alfa["w_setach"] == ["speeding", "super"]


def test_api_usun_duplikaty_wykonuje_to_co_pokazano(biblioteka):
    """apply przenosi tylko pliki, które użytkownik widział (body.remove)."""
    from fastapi.testclient import TestClient
    from selekta import web
    web.set_folder(biblioteka["lib"])
    web._HEALTH_CACHE.update(sig=None, report=None)
    c = TestClient(web.app)
    plan = c.get("/api/dedupe").json()["actions"]
    r = c.post("/api/dedupe/apply", json={"remove": plan[0]["remove"]}).json()
    assert r["moved"] == 1
    assert r["przeniesione"][0]["z"] == "Alfa - Jeden.mp3"
    assert r["przeniesione"][0]["w_koszu"].startswith("_selekta_kosz/")
    # sety nietknięte
    for s in ("speeding", "super"):
        assert os.path.isfile(os.path.join(biblioteka["lib"], s, "Alfa - Jeden.flac"))
    # cofnięcie przez przywracanie z kosza
    w_koszu = os.path.join(biblioteka["lib"], r["przeniesione"][0]["w_koszu"])
    c.post("/api/tracks/przywroc", json={"w_koszu": w_koszu}).raise_for_status()
    assert os.path.isfile(biblioteka["alfa_mp3"])


def test_kopia_w_secie_dostaje_policzone_analizy(tmp_path, monkeypatch):
    """Eksport setu nie liczy od nowa tego, co już policzono dla oryginału."""
    from selekta import cache, config, playlists
    from tests.syntetyczne import utwor
    lib = tmp_path / "lib"
    p = utwor(str(lib / "Alfa - Jeden.flac"), "Alfa", "Jeden")
    cache.put(p, "harmonic", {"bpm": 128.0, "camelot": "8A"})
    monkeypatch.setattr(config, "get", lambda k, d=None: str(lib) if k == "downloads_root" else d)
    wynik = playlists.collect("moj set", [p])
    (kopia,) = wynik["copied"]
    assert cache.get(kopia, "harmonic") == {"bpm": 128.0, "camelot": "8A"}
