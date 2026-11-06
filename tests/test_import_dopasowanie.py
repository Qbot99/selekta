"""Dopasowanie playlisty do biblioteki — zbiór prawdy z przeglądu 0.4.2.

Zasada: do „masz" (i do setu) trafia TYLKO ten sam utwór w tej samej
wersji. Ten sam utwór w innej wersji to propozycja („version") do decyzji
użytkownika. Cudzy utwór — nigdy: idzie do „do ściągnięcia" („missing").

Biblioteka jest syntetyczna (nazwy plików, tagi i czasy przepisane z
piaskownicy), więc testy nie czytają żadnego audio.
"""
from __future__ import annotations

import json
import os

import pytest

from selekta import matcher
from selekta.spotify import Track

DANE = json.load(open(os.path.join(os.path.dirname(__file__),
                                   "dane_dopasowania.json"), encoding="utf-8"))


def _wpis(rel: str, artist: str, title: str, dur: float) -> matcher.IndexEntry:
    path = "/biblioteka/" + rel
    stem = os.path.splitext(os.path.basename(rel))[0]
    tokens = matcher.normalize(stem) + matcher.normalize(title) + matcher.normalize(artist)
    return matcher.IndexEntry(path, tokens, dur or None,
                              {"title": title, "artist": artist})


@pytest.fixture(scope="module")
def indeks():
    return [_wpis(*r) for r in DANE["biblioteka"]]


def _klasyfikuj(indeks, artist, title, dur):
    c = matcher.classify_track(Track(id="", artist=artist, title=title,
                                     duration_s=dur), indeks)
    return matcher.lane(c), (os.path.basename(c.path) if c else None)


def _ocen(indeks, przypadki):
    trafne, falszywe_auto, falszywe_masz, zle = 0, 0, 0, []
    for exp, artist, title, dur, plik in przypadki:
        pas, got = _klasyfikuj(indeks, artist, title, dur)
        # duplikaty z dopiskiem pobierania („…_639242269261972010.flac")
        g, w = (os.path.splitext(x or "")[0] for x in (got, plik))
        ten_plik = bool(got and plik and (g.startswith(w) or w.startswith(g)))
        dobrze = pas == exp and (exp == "missing" or ten_plik)
        trafne += dobrze
        if pas == "auto" and not (exp == "auto" and ten_plik):
            falszywe_auto += 1
        if pas != "missing" and exp == "missing":
            falszywe_masz += 1
        if not dobrze:
            zle.append((exp, pas, artist, title, got))
    return trafne, falszywe_auto, falszywe_masz, zle


def test_playlista_100lecie_zgodna_z_prawda(indeks):
    """22 to samo nagranie, 3 inna wersja, 5 brak — przed naprawą:
    1 fałszywe auto (Savage Garden → remiks krótszy o 60 s) i Sultans Of
    Swing w „do rozstrzygnięcia" z plikiem „Walk Of Life"."""
    przypadki = DANE["playlista_100lecie"]
    trafne, fa, fm, zle = _ocen(indeks, przypadki)
    assert zle == []
    assert (trafne, fa, fm) == (30, 0, 0)
    pasy = [p[0] for p in przypadki]
    assert (pasy.count("auto"), pasy.count("version"), pasy.count("missing")) == (22, 3, 5)


def test_przypadki_trudne(indeks):
    """Remiksy, Extended/Original, feat./ft., diakrytyki, inny wykonawca
    tego samego tytułu, tytuły różniące się jednym słowem."""
    trafne, fa, fm, zle = _ocen(indeks, DANE["trudne"])
    assert zle == []
    assert fa == 0 and fm == 0


def test_album_i_playlista_spoza_biblioteki_nie_podmieniaja_plikow(indeks):
    """Confessions on a Dance Floor + All Out 80s: dawniej 16 pozycji
    „do rozstrzygnięcia" wskazywało cudzy plik („Beat It" → „Kick It.wav",
    „Jump" → „Sorry"), a kreator wkładał je do kolumny „masz"."""
    w_bibliotece = set(DANE["w_bibliotece"])
    for artist, title, dur in DANE["spoza_biblioteki"]:
        pas, got = _klasyfikuj(indeks, artist, title, dur)
        if title in w_bibliotece:
            assert pas == "auto", (artist, title, got)
        else:
            assert pas == "missing", (artist, title, pas, got)


@pytest.mark.parametrize("artist,title,dur,cudzy", [
    ("Michael Jackson", "Beat It", 258, "Linds - Kick It.wav"),
    ("Madonna", "Frozen", 372, "Madonna - Like a Prayer.flac"),
    ("The Rocketman", "Una Hora Menos", 164, "The Rocketman - Una Hora Más.flac"),
    ("Ram Jam", "Black Betty", 236, "Braaheim - Black Betty (Extended Mix).mp3"),
])
def test_cudzy_utwor_to_brak(indeks, artist, title, dur, cudzy):
    pas, _got = _klasyfikuj(indeks, artist, title, dur)
    assert pas == "missing"


def test_rozna_dlugosc_wyklucza_te_sama_wersje(indeks):
    """„To the Moon & Back" 339 s vs plik 280 s: dawniej wynik 0,95 i auto."""
    pas, got = _klasyfikuj(indeks, "Savage Garden", "To the Moon & Back", 339.4)
    assert pas == "version"
    assert got.startswith("05 - To the Moon & Back")


def test_nazwa_remiksu_spoza_mix_words_rozroznia_wersje(indeks):
    """„Techno" nie było w MIX_WORDS — „Take Me to the Rave" brało
    „(Techno Mix)" za ten sam utwór, nawet przy identycznym czasie."""
    pas, _ = _klasyfikuj(indeks, "Rocco, Pulsedriver, Ninkid", "Take Me to the Rave", 196)
    assert pas == "version"
    pas, _ = _klasyfikuj(indeks, "Rocco, Pulsedriver, Ninkid",
                         "Take Me to the Rave (Techno Mix)", 196)
    assert pas == "auto"


def test_original_mix_rowny_extended_przy_tym_samym_czasie(indeks):
    pas, got = _klasyfikuj(indeks, "Fenrick", "Make Me Sick (Original Mix)", 244)
    assert (pas, got) == ("auto", "Fenrick - Make Me Sick (Extended Mix).mp3")


def test_dwie_edycje_tego_samego_utworu_wybor_po_czasie(indeks):
    a = _klasyfikuj(indeks, "Madonna", "4 Minutes (feat. Justin Timberlake and Timbaland)", 189.7)
    b = _klasyfikuj(indeks, "Madonna", "4 Minutes (feat. Justin Timberlake and Timbaland)", 245.1)
    assert a == ("auto", "04. 4 Minutes (feat. Justin Timberlake and Timbaland).flac")
    assert b == ("auto", "02. 4 Minutes (feat. Justin Timberlake and Timbaland).flac")


def test_plik_bez_wykonawcy_tylko_przy_zgodnym_czasie():
    """Anonimowy plik „Sorry.flac" (bez tagów, bez artysty w nazwie, folder
    bez nazwiska) nie może być propozycją dla „Madonna — Sorry" — to mógłby
    być cudzy utwór o tym samym tytule."""
    idx = [matcher.IndexEntry("/x/Nowe/Sorry.flac", ["sorry"], 200.0,
                              {"title": "", "artist": ""})]
    pas, _ = _klasyfikuj(idx, "Madonna", "Sorry", 281.9)
    assert pas == "missing"
    pas, _ = _klasyfikuj(idx, "Madonna", "Sorry", 201.0)
    assert pas == "auto"


def test_folder_z_nazwiskiem_potwierdza_wykonawce():
    idx = [matcher.IndexEntry("/x/Madonna - Confessions/01 - Hung Up.flac",
                              ["01", "hung", "up"], 336.0, {"title": "", "artist": ""})]
    assert _klasyfikuj(idx, "Madonna", "Hung Up", 337.7)[0] == "auto"
    assert _klasyfikuj(idx, "Kylie Minogue", "Hung Up", 337.7)[0] == "missing"


def test_lane_dla_braku_kandydata():
    assert matcher.lane(None) == "missing"


def test_wspolni_wykonawcy_nie_robia_z_cudzego_tytulu_tego_samego_utworu():
    """„Adrenalin - Remix" (2:37) dostawał w 0.4.2 wynik 0,93 i pas „auto"
    na „Unendlichkeit (Remix)" (3:18): trzej wykonawcy i słowo „remix" to
    5 z 6 słów, więc inny tytuł prawie nie obniżał wyniku."""
    plik = _wpis("speeding/MilleniumKid, JBS, The Boy The G - Unendlichkeit (Remix).flac",
                 "MilleniumKid, JBS, The Boy The G", "Unendlichkeit (Remix)", 198.5)
    wykonawcy = "The Boy The G, MilleniumKid, JBS"
    assert _klasyfikuj([plik], wykonawcy, "Adrenalin - Remix", 157)[0] == "missing"
    # identyczny czas też nie może zastąpić zgodnego tytułu
    assert _klasyfikuj([plik], wykonawcy, "Adrenalin - Remix", 198.5)[0] == "missing"
    assert _klasyfikuj([plik], wykonawcy, "Unendlichkeit - Remix", 198.5)[0] == "auto"
