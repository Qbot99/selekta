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
from selekta.slskd_client import SearchHit, SlskdClient


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
        if hits == "trafienie":           # wynik pasujący do szukanego utworu
            hits = [_hit(f"X\\Y\\{artist} - {title}.flac")]
        self._empty_streak = 0 if hits else self._empty_streak + 1
        return hits

    # prawdziwa bramka tożsamości (nie używa sieci ani stanu klienta)
    pewny_wynik = SlskdClient.pewny_wynik

    def download(self, hit):
        self.pobrane.append(hit.filename)


def _hit(sciezka, dlugosc=None, user="u"):
    return SearchHit(user, sciezka, 30_000_000, None, dlugosc, True, True)


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
        # 5 pustek (serwer chwilowo głuchy), potem wszystko wraca do normy
        klient = _KlientPustek([[], [], [], [], []] + ["trafienie"] * 6)
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
        # pierwszy utwór: pustka, drugi: trafienie, potem pierwszy jeszcze raz: trafienie
        klient = _KlientPustek([[], "trafienie", "trafienie"])
        q = self._kolejka_z_klientem(kolejka, monkeypatch, klient)
        q.add([{"artist": "A", "title": "pierwszy"}, {"artist": "B", "title": "drugi"}])
        q._run()
        assert [j.title for j in q._jobs] == ["drugi", "pierwszy"], "pustka wędruje na koniec"
        assert all(j.status == "queued" for j in q._jobs)


class TestBramkaTozsamosci:
    """Automat kolejki pobiera tylko plik, który JEST tym utworem."""

    def test_cudzy_plik_nie_jest_pobierany(self, kolejka, monkeypatch):
        cudzy = _hit("Muzyka\\Rick Astley - Never Gonna Give You Up.flac", 213)
        wlasciwy = _hit("Muzyka\\Madonna - Hung Up.mp3", 337, user="v")
        klient = _KlientPustek([[cudzy, wlasciwy]])
        monkeypatch.setattr(dlqueue, "SlskdClient", lambda: klient)
        kolejka.add([{"artist": "Madonna", "title": "Hung Up", "duration": 337.7}])
        kolejka._run()
        job = kolejka._jobs[0]
        assert klient.pobrane == ["Muzyka\\Madonna - Hung Up.mp3"]
        assert (job.status, job.user, job.path) == ("queued", "v", "Muzyka\\Madonna - Hung Up.mp3")

    def test_same_cudze_wyniki_to_nieudane_z_powodem(self, kolejka, monkeypatch):
        klient = _KlientPustek([[_hit("x\\Linds - Kick It.wav", 258)]])
        monkeypatch.setattr(dlqueue, "SlskdClient", lambda: klient)
        kolejka.add([{"artist": "Michael Jackson", "title": "Beat It", "duration": 258}])
        kolejka._run()
        job = kolejka._jobs[0]
        assert klient.pobrane == []
        assert job.status == "failed" and "ręcznie" in job.detail


class TestZleconeDostajaKoniec:
    """Regresja z przeglądu 0.4.2: „zlecone" nigdy nie przechodziło w
    „done" — nie dało się dodać utworu ponownie ani wyczyścić kolejki."""

    def _zlecone(self, kolejka, **kw):
        kolejka.add([{"artist": "Madonna", "title": "Hung Up"}])
        job = kolejka._jobs[0]
        job.status, job.file = "queued", "Hung Up.flac"
        job.user, job.path = kw.get("user", "u"), kw.get("path", "M\\Hung Up.flac")
        job.queued_at = kw.get("queued_at", 1.0)
        return job

    def test_udany_transfer_konczy_zadanie(self, kolejka):
        job = self._zlecone(kolejka)
        assert kolejka.uzgodnij([{"user": "u", "path": "M\\Hung Up.flac",
                                  "name": "Hung Up.flac", "status": "done"}]) == 1
        assert job.status == "done"
        assert kolejka.clear_finished() == 1 and kolejka._jobs == []

    def test_nieudany_transfer_pozwala_dodac_ponownie(self, kolejka):
        job = self._zlecone(kolejka)
        assert kolejka.add([{"artist": "Madonna", "title": "Hung Up"}]) == 0
        kolejka.uzgodnij([{"user": "u", "path": "M\\Hung Up.flac", "name": "Hung Up.flac",
                           "status": "failed", "state_raw": "Completed, Rejected"}])
        assert job.status == "failed" and "Rejected" in job.detail
        assert kolejka.add([{"artist": "Madonna", "title": "Hung Up"}]) == 1

    def test_trwajacy_transfer_zostaje_zlecony(self, kolejka):
        job = self._zlecone(kolejka)
        kolejka.uzgodnij([{"user": "u", "path": "M\\Hung Up.flac", "name": "Hung Up.flac",
                           "status": "active", "percent": 42.0}])
        assert job.status == "queued" and "42" in job.detail

    def test_plik_na_dysku_konczy_zadanie(self, kolejka, tmp_path):
        job = self._zlecone(kolejka)
        (tmp_path / "Madonna").mkdir()
        (tmp_path / "Madonna" / "Hung Up.flac").write_bytes(b"x")
        kolejka.uzgodnij([], [str(tmp_path)])
        assert job.status == "done"

    def test_zagubiony_transfer_po_czasie_to_nieudane(self, kolejka):
        import time as _t
        job = self._zlecone(kolejka, queued_at=_t.time())
        kolejka.uzgodnij([])
        assert job.status == "queued", "świeże zlecenie — slskd mógł jeszcze nie pokazać"
        job.queued_at = _t.time() - dlqueue.ZNIKNIETE_PO_S - 1
        kolejka.uzgodnij([])
        assert job.status == "failed"

    def test_slskd_nie_odpowiada_nic_nie_przesadza(self, kolejka):
        job = self._zlecone(kolejka, queued_at=1.0)
        kolejka.uzgodnij(None)
        assert job.status == "queued"

    def test_api_queue_uzgadnia_ze_slskd(self, kolejka, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        from selekta import web
        job = self._zlecone(kolejka)
        monkeypatch.setattr(dlqueue, "QUEUE", kolejka)

        class Klient:
            def available(self):
                return True

            def downloads_or_none(self):
                return [{"user": "u", "path": "M\\Hung Up.flac", "name": "Hung Up.flac",
                         "status": "done"}]

        monkeypatch.setattr(web, "SlskdClient", lambda: Klient())
        web.set_folder(str(tmp_path))
        d = TestClient(web.app).get("/api/queue").json()
        assert d["jobs"][0]["status"] == "done"
        assert job.status == "done"
