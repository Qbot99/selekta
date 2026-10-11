"""`selekta organize --apply` — regresje z przeglądu 0.4.2 (pliki syntetyczne).

Przed naprawą: tytuł z playlisty bez dopisku wersji kasował „(Extended Mix)”
z tagu i z nazwy pliku, bez kopii starych wartości i bez cofnięcia; pierwszy
M4A przerywał całą operację w połowie; zmiana nazwy odcinała analizy i ręczną
siatkę zapisane po ścieżce.
"""
from __future__ import annotations

import os

import pytest

from selekta import cache, health, tagger, waveform
from tests.syntetyczne import utwor


@pytest.fixture()
def stan(tmp_path, monkeypatch):
    monkeypatch.setattr(tagger, "_plik_dziennika", lambda: str(tmp_path / "dziennik.json"))
    return tmp_path


def test_dopisek_wersji_zostaje():
    assert tagger.tytul_z_wersja("Call Me", "Call Me (Extended Mix)", "x") == \
        "Call Me (Extended Mix)"
    assert tagger.tytul_z_wersja("Pressure", "", "Jacidorex - Pressure (Original Mix)") == \
        "Pressure (Original Mix)"
    assert tagger.tytul_z_wersja("Kick It", "Kick It", "Linds - Kick It (feat. X)") == "Kick It"
    assert tagger.tytul_z_wersja("Call Me (Radio Edit)", "Call Me (Extended Mix)", "x") == \
        "Call Me (Radio Edit)"


def test_uporzadkuj_zachowuje_wersje_analizy_i_da_sie_cofnac(tmp_path, stan):
    p = utwor(str(tmp_path / "lib" / "FOVOS - Call Me (Extended Mix).mp3"),
              "FOVOS", "Call Me (Extended Mix)", sekund=5)
    cache.put(p, "harmonic", {"bpm": 128.0})
    waveform.zapisz_siatke(p, 0.123, 128.0)
    w = tagger.uporzadkuj(p, "FOVOS, Sarah de Warren", "Call Me")
    nowa = w["do"]
    assert os.path.basename(nowa) == "FOVOS, Sarah de Warren - Call Me (Extended Mix).mp3"
    assert health.czytaj_tagi(nowa) == ("FOVOS, Sarah de Warren", "Call Me (Extended Mix)")
    assert cache.get(nowa, "harmonic") == {"bpm": 128.0}
    assert waveform.wczytaj_siatke(nowa)["first_beat_s"] == 0.123
    wynik = tagger.cofnij_porzadkowanie()
    assert wynik and wynik[0]["cofniete"]
    assert os.path.isfile(p) and not os.path.exists(nowa)
    assert health.czytaj_tagi(p) == ("FOVOS", "Call Me (Extended Mix)")
    assert cache.get(p, "harmonic") == {"bpm": 128.0}


def test_m4a_jest_obslugiwany(tmp_path, stan):
    p = utwor(str(tmp_path / "Asia - Heat of the Moment.m4a"), "Asia", "Heat", sekund=4)
    w = tagger.uporzadkuj(p, "Asia", "Heat of the Moment")
    assert "blad" not in w, w
    assert health.czytaj_tagi(w["do"]) == ("Asia", "Heat of the Moment")


def test_cli_organize_nie_przerywa_na_bledzie_jednego_pliku(tmp_path, stan, monkeypatch,
                                                           capsys):
    from selekta import cli
    lib = tmp_path / "lib"
    a = utwor(str(lib / "Alfa - Jeden.m4a"), "Alfa", "Jeden", sekund=4, hz=300)
    b = utwor(str(lib / "Beta - Dwa (Extended Mix).mp3"), "Beta", "Dwa (Extended Mix)",
              sekund=4, hz=500)
    zrodlo = tmp_path / "lista.txt"
    zrodlo.write_text("Alfa - Jeden\nBeta - Dwa\nGamma - Nie Ma\n", encoding="utf-8")
    prawdziwy = tagger._zapisz

    def zapisz(path, artist, title, cover):
        if path.endswith(".m4a"):
            raise ValueError("unsupported format: .m4a")
        return prawdziwy(path, artist, title, cover)
    monkeypatch.setattr(tagger, "_zapisz", zapisz)
    monkeypatch.setattr("sys.argv", ["selekta", "organize", str(zrodlo), "--folder",
                                     str(lib), "--apply"])
    cli.main()
    out = capsys.readouterr().out
    assert "pominięto" in out
    assert "Gamma" in out                      # raport brakujących dotarł do końca
    assert os.path.isfile(a)
    assert os.path.isfile(lib / "Beta - Dwa (Extended Mix).mp3")
    assert health.czytaj_tagi(str(lib / "Beta - Dwa (Extended Mix).mp3"))[1] == \
        "Dwa (Extended Mix)"
