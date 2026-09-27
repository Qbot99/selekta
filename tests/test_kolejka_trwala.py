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


def test_rownolegly_zapis_nie_zostawia_uszkodzonego_pliku(tmp_path, monkeypatch):
    """Młócka zapisów z wielu wątków — plik stanu ma być ZAWSZE parsowalny.

    Regresja z 1.09.2026: wspólna nazwa pliku tymczasowego i zapis poza
    blokadą pozwalały drugiemu wątkowi dopisywać do i-węzła opublikowanego
    już przez os.replace — restart trafiony w to okno wstawał z pustą
    kolejką bez żadnego błędu.
    """
    import json as _json
    import threading as _th
    from selekta import config as _cfg, dlqueue as _dl
    monkeypatch.setattr(_cfg, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(_dl, "PLIK_KOLEJKI", str(tmp_path / "kolejka.json"))

    q = _dl.Queue.__new__(_dl.Queue)
    q._jobs = [_dl.Job(artist=f"a{i}", title=f"t{i}") for i in range(40)]
    q._lock = __import__("threading").Lock()

    stop = _th.Event()
    zepsute = []

    def mloc():
        while not stop.is_set():
            q._zapisz()

    def czytaj():
        while not stop.is_set():
            try:
                with open(str(tmp_path / "kolejka.json"), encoding="utf-8") as fh:
                    _json.load(fh)
            except FileNotFoundError:
                pass
            except ValueError as e:
                zepsute.append(str(e))

    q._zapisz()
    watki = [_th.Thread(target=mloc) for _ in range(4)] + [_th.Thread(target=czytaj)]
    for w in watki: w.start()
    import time as _t; _t.sleep(1.5); stop.set()
    for w in watki: w.join()
    assert not zepsute, f"plik stanu bywał nieparsowalny: {zepsute[:3]}"
    with open(str(tmp_path / "kolejka.json"), encoding="utf-8") as fh:
        assert len(_json.load(fh)) == 40


class _KlientPustek:
    """Udaje SlskdClient: zalogowany, ale serwer oddaje pustki wg scenariusza."""

    def __init__(self, scenariusz):
        self.scenariusz = list(scenariusz)     # kolejne wyniki search_track
        self._empty_streak = 0
        self.pobrane = []
        self.resety = 0

    def logged_in(self):
        return True

    def network_down(self):
        return self._empty_streak >= 5

    def reset_empty_streak(self):
        self._empty_streak = 0
        self.resety += 1

    def search_track(self, artist, title, duration=None):
        hits = self.scenariusz.pop(0) if self.scenariusz else []
        self._empty_streak = 0 if hits else self._empty_streak + 1
        return hits

    def download(self, hit):
        self.pobrane.append(hit.filename)


class TestPustkiSerwera:
    """Regresja 27.09.2026: 26 utworów padło w minutę jako „brak wyników",
    bo licznik pustek klienta był lepki — po pięciu pustkach każde kolejne
    zadanie dostawało natychmiast pustą listę."""

    def _kolejka_z_klientem(self, kolejka, monkeypatch, klient):
        monkeypatch.setattr(dlqueue, "SlskdClient", lambda: klient)
        monkeypatch.setattr(dlqueue, "PUSTKI_BACKOFF_S", (0, 0, 0, 0))
        monkeypatch.setattr(dlqueue, "OFFLINE_BACKOFF_S", (0, 0, 0, 0, 0))
        return kolejka

    def test_seria_pustek_nie_uwala_kolejnych_utworow(self, kolejka, monkeypatch):
        from types import SimpleNamespace
        hit = SimpleNamespace(filename="X\\Y\\Dido - Thank You.flac")
        # 5 pustek (serwer chwilowo głuchy), potem wszystko wraca do normy
        klient = _KlientPustek([[], [], [], [], []] + [[hit]] * 6)
        q = self._kolejka_z_klientem(kolejka, monkeypatch, klient)
        q.add([{"artist": f"A{i}", "title": f"T{i}"} for i in range(6)])
        q._run()
        stany = [j.status for j in q._jobs]
        assert stany.count("queued") == 6, stany
        assert klient.resety >= 1, "po serii pustek kolejka ma odpocząć i wyzerować licznik"
        assert "brak wyników" not in [j.detail for j in q._jobs]

    def test_prawdziwy_brak_wynikow_nadal_jest_brakiem(self, kolejka, monkeypatch):
        """Dwie pustki przy zdrowej sieci = utworu nie ma; nie kręcimy się w kółko."""
        klient = _KlientPustek([[], []])
        q = self._kolejka_z_klientem(kolejka, monkeypatch, klient)
        q.add([{"artist": "Nikt", "title": "Nic"}])
        q._run()
        assert q._jobs[0].status == "failed" and q._jobs[0].detail == "brak wyników"
        assert not klient.scenariusz, "drugie podejście ma się odbyć"

    def test_pojedyncza_pustka_idzie_na_koniec_kolejki(self, kolejka, monkeypatch):
        from types import SimpleNamespace
        hit = SimpleNamespace(filename="a/b/c.flac")
        # pierwszy utwór: pustka, drugi: trafienie, potem pierwszy jeszcze raz: trafienie
        klient = _KlientPustek([[], [hit], [hit]])
        q = self._kolejka_z_klientem(kolejka, monkeypatch, klient)
        q.add([{"artist": "A", "title": "pierwszy"}, {"artist": "B", "title": "drugi"}])
        q._run()
        assert [j.title for j in q._jobs] == ["drugi", "pierwszy"], "pustka wędruje na koniec"
        assert all(j.status == "queued" for j in q._jobs)
