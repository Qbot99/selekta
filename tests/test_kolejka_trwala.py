"""Kolejka pobierania musi przeżyć zamknięcie apki.

Sedno: wklejasz playlistę, zamykasz laptopa, wracasz — ściąganie idzie
dalej. Do tego dłuższa awaria łącza NIE może skasować playlisty: za
rozłączenie winę ponosi serwer, nie utwór.
"""
from __future__ import annotations

import json
import os

import pytest

from selekta import dlqueue


@pytest.fixture
def kolejka(tmp_path, monkeypatch):
    monkeypatch.setattr(dlqueue, "PLIK_KOLEJKI", str(tmp_path / "kolejka.json"))
    monkeypatch.setattr(dlqueue.config, "STATE_DIR", str(tmp_path))
    # bez wątku roboczego — testujemy stan, nie sieć
    monkeypatch.setattr(dlqueue.Queue, "_ensure_worker", lambda self: None)
    return dlqueue.Queue()


class TestTrwalosc:
    def test_dodane_zadania_ladują_na_dysku(self, kolejka, tmp_path):
        kolejka.add([{"artist": "A", "title": "Jeden"},
                     {"artist": "B", "title": "Dwa"}])
        zapis = json.load(open(tmp_path / "kolejka.json", encoding="utf-8"))
        assert [z["title"] for z in zapis] == ["Jeden", "Dwa"]

    def test_wczytanie_wraca_do_kolejki(self, kolejka, tmp_path, monkeypatch):
        kolejka.add([{"artist": "A", "title": "Jeden"}])
        druga = dlqueue.Queue()
        monkeypatch.setattr(dlqueue.Queue, "_ensure_worker", lambda self: None)
        assert druga.wczytaj() == 1
        assert [j["title"] for j in druga.state()["jobs"]] == ["Jeden"]

    def test_przerwane_szukanie_jest_ponawiane(self, kolejka, tmp_path):
        """Po restarcie nie wiadomo, czy zapytanie doszło — powtarzamy."""
        json.dump([{"artist": "A", "title": "W trakcie", "status": "searching"}],
                  open(tmp_path / "kolejka.json", "w", encoding="utf-8"))
        assert kolejka.wczytaj() == 1
        job = kolejka.state()["jobs"][0]
        assert job["status"] == "waiting"
        assert "restarcie" in job["detail"]

    def test_zakonczone_nie_sa_ponawiane(self, kolejka, tmp_path):
        json.dump([{"artist": "A", "title": "Zrobione", "status": "queued"},
                   {"artist": "B", "title": "Nieudane", "status": "failed"}],
                  open(tmp_path / "kolejka.json", "w", encoding="utf-8"))
        assert kolejka.wczytaj() == 0, "nic nie czeka, więc nic nie wznawiamy"
        assert len(kolejka.state()["jobs"]) == 2, "ale historia zostaje"

    def test_brak_pliku_to_nie_blad(self, kolejka):
        assert kolejka.wczytaj() == 0

    def test_uszkodzony_plik_nie_wywala_apki(self, kolejka, tmp_path):
        (tmp_path / "kolejka.json").write_text("{to nie jest json")
        assert kolejka.wczytaj() == 0

    def test_wyczyszczenie_zakonczonych_zapisuje_stan(self, kolejka, tmp_path):
        json.dump([{"artist": "A", "title": "Zrobione", "status": "done"},
                   {"artist": "B", "title": "Czeka", "status": "waiting"}],
                  open(tmp_path / "kolejka.json", "w", encoding="utf-8"))
        kolejka.wczytaj()
        assert kolejka.clear_finished() == 1
        zapis = json.load(open(tmp_path / "kolejka.json", encoding="utf-8"))
        assert [z["title"] for z in zapis] == ["Czeka"]


class TestOdpornoscNaRozlaczenia:
    def test_backoff_rosnie_i_ma_sufit(self):
        """Dłuższa awaria ma czekać dłużej, ale nie w nieskończoność."""
        assert dlqueue.OFFLINE_BACKOFF_S == tuple(sorted(dlqueue.OFFLINE_BACKOFF_S))
        assert dlqueue.OFFLINE_BACKOFF_S[-1] >= 300

    def test_rozlaczenie_nie_zzera_prob_utworu(self, kolejka, monkeypatch):
        """Godzinna awaria łącza nie może skasować całej playlisty."""
        from selekta.slskd_client import SoulseekOffline

        kolejka.add([{"artist": "A", "title": "Jeden"}])

        class FalszywyKlient:
            def logged_in(self):
                return True

            def search_track(self, *a, **kw):
                raise SoulseekOffline("zerwane")

        monkeypatch.setattr(dlqueue, "SlskdClient", lambda: FalszywyKlient())
        # jeden obrót pętli: symulujemy to, co robi wątek roboczy
        job = kolejka._next_job()
        assert job is not None
        for _ in range(dlqueue.MAX_ATTEMPTS + 2):
            try:
                FalszywyKlient().search_track()
            except SoulseekOffline:
                job.status, job.detail = "waiting", "wrócę, gdy połączenie wróci"
        assert job.status == "waiting", "utwór ma czekać, nie zostać spalony"
        assert job.attempts == 0, "rozłączenie nie liczy się jako próba utworu"
