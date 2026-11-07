"""Kolejka decyzji — kod, który rusza pliki, więc pilnujemy go szczególnie.

Najważniejsza własność: NIC nie znika bez zatwierdzenia, a zatwierdzone
da się cofnąć. Testy sprawdzają obie strony tej obietnicy.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from mutagen import File as MutagenFile

from selekta import decyzje
from tests.conftest import GOOD_FLAC, GOOD_MP3


@pytest.fixture
def biblioteka(tmp_path, lib_copy, monkeypatch):
    """Ten SAM utwór w dwóch jakościach: bezstratny i stratny.

    Grupowanie idzie po tagach, nie po nazwie pliku — dwie różne piosenki
    przemianowane na to samo nie utworzą grupy. Dlatego robimy prawdziwą
    parę: jedno źródło, przekodowane, z identycznymi tagami.
    """
    monkeypatch.setattr(decyzje, "PLIK", str(tmp_path / "decyzje.json"))
    monkeypatch.setattr(decyzje.config, "STATE_DIR", str(tmp_path))
    folder = tmp_path / "lib"
    folder.mkdir()
    zrodlo = os.path.join(lib_copy, GOOD_FLAC)

    lepszy = folder / "Artysta - Utwor.flac"
    shutil.copy2(zrodlo, lepszy)
    gorszy = folder / "Artysta - Utwor (kopia).mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(zrodlo),
                    "-b:a", "128k", str(gorszy)], check=True)

    for sciezka in (lepszy, gorszy):
        audio = MutagenFile(str(sciezka), easy=True)
        audio["artist"] = ["Artysta"]
        audio["title"] = ["Utwor"]
        audio.save()
    return str(folder), str(lepszy), str(gorszy)


class TestSkanowanie:
    def test_skan_nie_rusza_plikow(self, biblioteka):
        folder, lepszy, gorszy = biblioteka
        przed = {p: os.path.getsize(p) for p in (lepszy, gorszy)}
        decyzje.skanuj(folder)
        for p, rozmiar in przed.items():
            assert os.path.isfile(p), "skan nie może niczego usuwać"
            assert os.path.getsize(p) == rozmiar

    def test_pojedynczy_utwor_nie_tworzy_decyzji(self, tmp_path, lib_copy,
                                                 monkeypatch):
        monkeypatch.setattr(decyzje, "PLIK", str(tmp_path / "d.json"))
        monkeypatch.setattr(decyzje.config, "STATE_DIR", str(tmp_path))
        folder = tmp_path / "solo"
        folder.mkdir()
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC), folder / "jeden.flac")
        assert decyzje.skanuj(str(folder)) == []

    def test_odrzucona_nie_wraca_przy_kolejnym_skanie(self, biblioteka):
        folder, _, _ = biblioteka
        nowe = decyzje.skanuj(folder)
        assert nowe, "powinna powstać przynajmniej jedna propozycja"
        decyzje.odrzuc(nowe[0]["id"])
        assert decyzje.skanuj(folder) == []
        assert decyzje.czekajace() == []


class TestNiebezpieczneGrupowanie:
    """Propozycja skasowania DOBREGO utworu to najgorszy możliwy błąd."""

    def _plik(self, folder, nazwa, artysta, tytul, lib_copy):
        cel = os.path.join(folder, nazwa)
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC), cel)
        audio = MutagenFile(cel, easy=True)
        audio["artist"] = [artysta]; audio["title"] = [tytul]
        audio.save()
        return cel

    def test_bootleg_nie_jest_kopia_oryginalu(self, biblioteka, lib_copy):
        """Wersja bywa TYLKO w nazwie pliku, a tag ma goły tytuł.

        Realny przypadek: „Captain Jack - Captain Jack (Oski & Citos
        Bootleg).mp3" i „1-02 - Captain Jack.flac" mają identyczne tagi.
        """
        folder, _, _ = biblioteka
        osobny = os.path.join(folder, "inne"); os.makedirs(osobny, exist_ok=True)
        self._plik(osobny, "Kto - Piosenka.flac", "Kto", "Piosenka", lib_copy)
        self._plik(osobny, "Kto - Piosenka (Ktos Bootleg).flac", "Kto", "Piosenka",
                   lib_copy)
        grupy = decyzje._grupuj(osobny)
        assert all(len(v) == 1 for v in grupy.values()), \
            "oryginał i bootleg nie mogą trafić do jednej grupy"

    def test_club_mix_nie_jest_kopia(self, biblioteka, lib_copy):
        folder, _, _ = biblioteka
        osobny = os.path.join(folder, "inne2"); os.makedirs(osobny, exist_ok=True)
        self._plik(osobny, "A - B.flac", "A", "B", lib_copy)
        self._plik(osobny, "A - B [Club Mix].flac", "A", "B", lib_copy)
        grupy = decyzje._grupuj(osobny)
        assert all(len(v) == 1 for v in grupy.values())

    def test_rozne_dlugosci_to_nie_kopie(self, biblioteka, lib_copy, tmp_path):
        """Radio edit i wersja klubowa to różne rzeczy, nawet przy tych tagach."""
        folder, _, _ = biblioteka
        osobny = os.path.join(folder, "inne3"); os.makedirs(osobny, exist_ok=True)
        dlugi = self._plik(osobny, "C - D.flac", "C", "D", lib_copy)
        krotki = os.path.join(osobny, "C - D short.flac")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dlugi,
                        "-t", "45", krotki], check=True)
        audio = MutagenFile(krotki, easy=True)
        audio["artist"] = ["C"]; audio["title"] = ["D"]; audio.save()
        grupy = decyzje._grupuj(osobny)
        assert all(len(v) == 1 for v in grupy.values()), \
            "pliki różniące się czasem o minuty to nie kopie"


class TestZatwierdzanieOdwracalne:
    def test_zatwierdzenie_przenosi_do_kosza_a_nie_kasuje(self, biblioteka):
        folder, _, _ = biblioteka
        d = decyzje.skanuj(folder)[0]
        usuwany = d["usun"][0]
        wynik = decyzje.zatwierdz(d["id"])
        assert not os.path.exists(usuwany), "plik miał zniknąć z biblioteki"
        assert len(wynik["w_koszu"]) == 1
        assert os.path.isfile(wynik["w_koszu"][0]), "plik musi być w koszu"
        assert decyzje.KOSZ in wynik["w_koszu"][0]

    def test_zachowany_plik_zostaje_nietkniety(self, biblioteka):
        folder, _, _ = biblioteka
        d = decyzje.skanuj(folder)[0]
        rozmiar = os.path.getsize(d["zostaw"])
        decyzje.zatwierdz(d["id"])
        assert os.path.isfile(d["zostaw"])
        assert os.path.getsize(d["zostaw"]) == rozmiar

    def test_cofniecie_przywraca_pliki(self, biblioteka):
        folder, _, _ = biblioteka
        d = decyzje.skanuj(folder)[0]
        usuwany = d["usun"][0]
        decyzje.zatwierdz(d["id"])
        assert not os.path.exists(usuwany)
        decyzje.cofnij(d["id"])
        assert os.path.isfile(usuwany), "cofnięcie ma przywrócić plik"
        assert decyzje.czekajace(), "decyzja wraca do rozpatrzenia"

    def test_nie_da_sie_zatwierdzic_dwa_razy(self, biblioteka):
        folder, _, _ = biblioteka
        d = decyzje.skanuj(folder)[0]
        decyzje.zatwierdz(d["id"])
        with pytest.raises(ValueError):
            decyzje.zatwierdz(d["id"])

    def test_cofnac_mozna_tylko_zatwierdzona(self, biblioteka):
        folder, _, _ = biblioteka
        d = decyzje.skanuj(folder)[0]
        with pytest.raises(ValueError):
            decyzje.cofnij(d["id"])

    def test_nieznane_id_to_czytelny_blad(self, biblioteka):
        with pytest.raises(KeyError):
            decyzje.zatwierdz("nie-ma-takiej")


class TestWeryfikacjaPobrania:
    """Regresje z realnego skanu: 5 z 7 pobrań było innym utworem."""

    def test_brak_slow_tytulu_to_zastrzezenie(self, biblioteka):
        _, lepszy, _ = biblioteka
        powody = decyzje._powody_niezgodnosci(lepszy, "Artysta", "Zupelnie Inny", None)
        assert any("brakuje słów" in p for p in powody)

    def test_brak_artysty_to_zastrzezenie(self, biblioteka):
        _, lepszy, _ = biblioteka
        powody = decyzje._powody_niezgodnosci(lepszy, "Kogos Innego", "Utwor", None)
        assert any("artysty" in p for p in powody)

    def test_zla_dlugosc_to_zastrzezenie(self, biblioteka):
        _, lepszy, _ = biblioteka
        powody = decyzje._powody_niezgodnosci(lepszy, "Artysta", "Utwor", 9000)
        assert any("czas" in p for p in powody)

    def test_zgodny_plik_bez_zastrzezen(self, biblioteka):
        _, lepszy, _ = biblioteka
        from selekta import matcher
        _tok, czas = matcher._file_tokens(lepszy)
        assert decyzje._powody_niezgodnosci(lepszy, "Artysta", "Utwor", czas) == []

    def test_podejrzane_pobranie_trafia_do_kolejki(self, biblioteka):
        folder, lepszy, _ = biblioteka
        zadania = [{"artist": "Ktos Inny", "title": "Inny Utwor",
                    "status": "done", "file": os.path.basename(lepszy),
                    "duration": None}]
        nowe = decyzje.sprawdz_pobrane(folder, zadania)
        assert len(nowe) == 1
        assert nowe[0]["rodzaj"] == "podejrzany"
        assert nowe[0]["dowody"]["zastrzezenia"]
        assert os.path.isfile(lepszy), "weryfikacja niczego nie usuwa"

    def test_poprawne_pobranie_nie_zasmieca_kolejki(self, biblioteka):
        folder, lepszy, _ = biblioteka
        from selekta import matcher
        _tok, czas = matcher._file_tokens(lepszy)
        zadania = [{"artist": "Artysta", "title": "Utwor", "status": "done",
                    "file": os.path.basename(lepszy), "duration": czas}]
        assert decyzje.sprawdz_pobrane(folder, zadania) == []


class TestWyborWersji:
    """„Duplikaty i wersje”: wszystkie kopie utworu, polecana najlepsza,
    a wybór należy do użytkownika — i da się go cofnąć."""

    def test_kopie_od_najlepszej_z_kazdej_kopii(self, biblioteka):
        folder, lepszy, gorszy = biblioteka
        for start in (lepszy, gorszy):
            d = decyzje.kopie_utworu(folder, start)
            assert [o["path"] for o in d["kopie"]] == [lepszy, gorszy]
            assert d["najlepsza"] == lepszy and d["kopie"][0]["polecana"]
            assert d["kopie"][1]["rel"] == os.path.basename(gorszy)
            assert not any(o["inna_dlugosc"] for o in d["kopie"])

    def test_wybor_inny_niz_polecany_i_cofniecie(self, biblioteka):
        folder, lepszy, gorszy = biblioteka
        d = decyzje.wybierz(folder, gorszy, [lepszy])     # użytkownik woli MP3
        assert d["stan"] == "zatwierdzona"
        assert os.path.isfile(gorszy) and not os.path.exists(lepszy)
        assert all(os.path.isfile(p) for p in d["w_koszu"])
        decyzje.cofnij(d["id"])
        assert os.path.isfile(lepszy) and os.path.isfile(gorszy)

    def test_nie_wyrzuca_innego_utworu(self, biblioteka, lib_copy):
        folder, lepszy, _ = biblioteka
        obcy = os.path.join(folder, "Ktos - Inny.flac")
        shutil.copy2(os.path.join(lib_copy, GOOD_FLAC), obcy)
        audio = MutagenFile(obcy, easy=True)
        audio["artist"] = ["Ktos"]; audio["title"] = ["Inny"]; audio.save()
        with pytest.raises(ValueError, match="nie jest kopią"):
            decyzje.wybierz(folder, lepszy, [obcy])
        assert os.path.isfile(obcy)

    def test_zle_wybory_odrzucone(self, biblioteka):
        folder, lepszy, gorszy = biblioteka
        with pytest.raises(ValueError):
            decyzje.wybierz(folder, lepszy, [])
        with pytest.raises(ValueError):
            decyzje.wybierz(folder, lepszy, [lepszy, gorszy])
        assert os.path.isfile(lepszy) and os.path.isfile(gorszy)

    def test_czekajaca_propozycja_porzadkow_przestaje_czekac(self, biblioteka):
        folder, lepszy, gorszy = biblioteka
        assert decyzje.skanuj(folder)
        decyzje.wybierz(folder, gorszy, [lepszy])
        assert decyzje.czekajace() == []

    def test_api(self, biblioteka, lib_copy):
        from fastapi.testclient import TestClient
        from selekta import web
        folder, lepszy, gorszy = biblioteka
        web.set_folder(folder)
        client = TestClient(web.app)
        d = client.get("/api/wersje", params={"file": os.path.basename(gorszy)}).json()
        assert d["najlepsza"] == lepszy and len(d["kopie"]) == 2
        assert client.post("/api/wersje/wybierz", json={"zostaw": "Artysta - Utwor.flac",
                                                        "usun": "zle"}).status_code == 400
        r = client.post("/api/wersje/wybierz", json={"zostaw": d["kopie"][0]["rel"],
                                                     "usun": [d["kopie"][1]["rel"]]})
        assert r.status_code == 200 and r.json()["w_koszu"] == 1
        assert os.path.isfile(lepszy) and not os.path.exists(gorszy)


def test_program_pliku_rozpoznaje_foldery_rekordboxa_i_seratu():
    assert decyzje.program_pliku("/u/Music/PioneerDJ/Imported from Device/Contents/A/b.mp3") == "rekordbox"
    assert decyzje.program_pliku("/u/Music/_Serato_/x.mp3") == "Serato"
    assert decyzje.program_pliku("/u/Music/selekta/house/a.flac") == ""


def test_grupy_kopii_dla_playlisty(biblioteka):
    folder, lepszy, gorszy = biblioteka
    g = decyzje.grupy_kopii(folder, [gorszy, lepszy])
    assert len(g) == 1 and g[0]["plik"] == os.path.basename(gorszy)
    assert sorted(g[0]["kopie"]) == sorted(os.path.basename(p) for p in (lepszy, gorszy))
