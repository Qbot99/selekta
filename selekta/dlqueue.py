"""Kolejka pobierania — jeden utwór naraz, z szacunkiem dla serwera.

Sedno problemu, który to naprawia: klikając „ściągnij wszystkie" przy 68
utworach apka wysyłała ~200 zapytań jedno po drugim. Soulseek zrywa wtedy
połączenie („Connection reset by peer"), a każde kolejne wyszukiwanie
zwraca zero — wygląda to, jakby nic nie dało się znaleźć.

Dlatego:
- pracuje JEDEN wątek, utwór po utworze (klient wymusza odstęp między
  zapytaniami),
- gdy slskd traci połączenie, kolejka CZEKA i wraca do utworu później,
  zamiast marnować go na pusty wynik,
- stan przeżywa zamknięcie okna — kolejka żyje w serwerze, nie w kartcie.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict

from . import config
from .slskd_client import SlskdClient, SoulseekOffline

# ile razy wracamy do utworu, zanim uznamy go za nieudany
MAX_ATTEMPTS = 3
PUSTE_PROBY = 2            # pusta odpowiedź: drugie podejście po reszcie kolejki, dopiero potem „brak wyników"
# przerwa, gdy Soulseek nas odciął — rośnie, ale NIE zżera prób utworu:
# godzinna awaria łącza nie może skasować całej playlisty
OFFLINE_BACKOFF_S = (20, 60, 150, 300, 600)
# Osobna drabina dla „połączenie żyje, ale serwer oddaje same pustki":
# zmierzone 27.09.2026 — tuż po starcie slskd pięć zapytań z rzędu wróciło
# puste, klient uznał sieć za martwą i 26 utworów z rzędu padło jako „brak
# wyników" w minutę, choć ręczne wyszukanie każdego z nich dawało setki plików.
PUSTKI_BACKOFF_S = (30, 90, 180, 300)
PLIK_KOLEJKI = os.path.join(config.STATE_DIR, "kolejka.json")


@dataclass
class Job:
    artist: str
    title: str
    duration: float | None = None
    status: str = "waiting"      # waiting | searching | queued | done | failed
    file: str = ""               # nazwa pliku zleconego do pobrania
    detail: str = ""
    attempts: int = 0


class Queue:
    """Kolejka zadań pobierania obsługiwana przez jeden wątek roboczy."""

    def __init__(self) -> None:
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._paused_until = 0.0
        self._note = ""
        self._offline_streak = 0
        self._pustki_streak = 0

    # ------------------------------------------------------------ trwałość
    def _zapisz(self) -> None:
        """Zrzuć kolejkę na dysk, żeby przeżyła zamknięcie apki."""
        try:
            os.makedirs(config.STATE_DIR, exist_ok=True)
            # cały zapis pod blokadą i z unikalną nazwą tymczasową: wspólny
            # ".tmp" poza blokadą pozwalał drugiemu wątkowi dopisywać do
            # i-węzła już opublikowanego przez os.replace — restart trafiony
            # w to okno wstawał z pustą kolejką
            with self._lock:
                dane = [asdict(j) for j in self._jobs]
                fd, tmp = tempfile.mkstemp(dir=config.STATE_DIR,
                                           prefix="kolejka.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(dane, fh, ensure_ascii=False)
                    os.replace(tmp, PLIK_KOLEJKI)
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp)
                    raise
        except OSError:
            pass                              # zapis stanu nie może wywalić apki

    def wczytaj(self) -> int:
        """Wczytaj kolejkę z dysku i wznów pobieranie.

        Zadania przerwane w połowie („searching") wracają do „waiting" —
        po restarcie nie wiadomo, czy zapytanie doszło, więc powtarzamy.
        """
        try:
            with open(PLIK_KOLEJKI, encoding="utf-8") as fh:
                dane = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return 0
        if not isinstance(dane, list):
            return 0
        wznowione = 0
        with self._lock:
            self._jobs = []
            for d in dane:
                if not isinstance(d, dict):
                    continue
                job = Job(artist=str(d.get("artist", "")),
                          title=str(d.get("title", "")),
                          duration=d.get("duration"),
                          status=str(d.get("status", "waiting")),
                          file=str(d.get("file", "")),
                          detail=str(d.get("detail", "")),
                          attempts=int(d.get("attempts", 0)))
                if job.status == "searching":
                    job.status, job.detail = "waiting", "wznowione po restarcie"
                if job.status == "waiting":
                    wznowione += 1
                self._jobs.append(job)
        if wznowione:
            self._ensure_worker()
        return wznowione

    # ---------------------------------------------------------------- API
    def add(self, items: list[dict]) -> int:
        added = 0
        with self._lock:
            have = {(j.artist.lower(), j.title.lower()) for j in self._jobs
                    if j.status in ("waiting", "searching", "queued")}
            for it in items:
                key = (str(it.get("artist", "")).lower(), str(it.get("title", "")).lower())
                if key in have or not any(key):
                    continue
                self._jobs.append(Job(artist=str(it.get("artist", "")),
                                      title=str(it.get("title", "")),
                                      duration=it.get("duration")))
                have.add(key)
                added += 1
        self._zapisz()
        self._ensure_worker()
        return added

    def state(self) -> dict:
        with self._lock:
            jobs = [asdict(j) for j in self._jobs]
        counts: dict[str, int] = {}
        for j in jobs:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        waiting = time.time() < self._paused_until
        return {
            "jobs": jobs, "counts": counts,
            "running": bool(self._worker and self._worker.is_alive()),
            "paused_for_s": max(0, round(self._paused_until - time.time())) if waiting else 0,
            "note": self._note,
        }

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.status not in ("done", "failed")]
            usuniete = before - len(self._jobs)
        self._zapisz()
        return usuniete

    def cancel_pending(self) -> int:
        with self._lock:
            n = 0
            for j in self._jobs:
                if j.status == "waiting":
                    j.status, j.detail, n = "failed", "anulowane", n + 1
        self._zapisz()
        return n

    # ------------------------------------------------------------- worker
    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _next_job(self) -> Job | None:
        with self._lock:
            for j in self._jobs:
                if j.status == "waiting":
                    return j
        return None

    def _run(self) -> None:
        client = SlskdClient()
        while True:
            job = self._next_job()
            if job is None:
                self._note = ""
                return                       # nic do roboty — wątek kończy się

            if time.time() < self._paused_until:
                time.sleep(1)
                continue

            if not client.logged_in():
                # rozłączenie to nie wina utworu — czekamy dłużej, ale nie
                # odliczamy prób, żeby dłuższa awaria nie skasowała playlisty
                idx = min(self._offline_streak, len(OFFLINE_BACKOFF_S) - 1)
                self._offline_streak += 1
                self._pause(OFFLINE_BACKOFF_S[idx],
                            "Soulseek rozłączony — czekam i wrócę do kolejki")
                continue
            self._offline_streak = 0

            if client.network_down():
                # Zalogowani, a mimo to seria pustek: to serwer nie oddaje
                # wyników (chwiejność po starcie, dławienie częstych zapytań),
                # nie utwory. Odpoczywamy i liczymy pustki od nowa — inaczej
                # każde kolejne zadanie padałoby natychmiast jako „brak wyników".
                idx = min(self._pustki_streak, len(PUSTKI_BACKOFF_S) - 1)
                self._pustki_streak += 1
                client.reset_empty_streak()
                self._pause(PUSTKI_BACKOFF_S[idx],
                            "Soulseek nie oddaje wyników — odpoczywam i wracam do kolejki")
                continue

            job.status, job.detail = "searching", ""
            self._zapisz()
            try:
                hits = client.search_track(job.artist, job.title, job.duration)
                if hits:
                    self._pustki_streak = 0
                    client.download(hits[0])
                    job.file = hits[0].filename.replace("\\", "/").split("/")[-1]
                    job.status, job.detail = "queued", "zlecone"
                elif client.network_down():
                    # Pustka zbiegła się z padnięciem serii — to nie dowód, że
                    # utworu nie ma; wraca do kolejki bez odliczania próby, ale
                    # NA KONIEC: serwer Soulseeka blokuje powtarzany tekst
                    # zapytania (zmierzone: „Bryan Adams" 0 wyników, gdy „Dire
                    # Straits" chwilę później daje 250 odpowiedzi), więc ten sam
                    # utwór odpytywany w kółko nigdy by nie wyszedł z pętli.
                    job.status, job.detail = "waiting", "serwer nie oddał wyników — wrócę po reszcie kolejki"
                    self._na_koniec(job)
                else:
                    # Pojedyncza pustka bywa chwilową głuchotą serwera (patrz
                    # PUSTKI_BACKOFF_S), więc utwór dostaje drugą szansę —
                    # ale na KOŃCU kolejki, żeby brakujący naprawdę utwór nie
                    # blokował reszty i kosztował tylko jedną dodatkową drabinę.
                    job.attempts += 1
                    if job.attempts >= PUSTE_PROBY:
                        job.status, job.detail = "failed", "brak wyników"
                    else:
                        job.status, job.detail = "waiting", "brak wyników — spróbuję jeszcze raz po reszcie kolejki"
                        self._na_koniec(job)
            except SoulseekOffline:
                # utwór wraca do kolejki BEZ odliczenia próby — zawinił serwer
                job.status, job.detail = "waiting", "wrócę, gdy połączenie wróci"
                idx = min(self._offline_streak, len(OFFLINE_BACKOFF_S) - 1)
                self._offline_streak += 1
                self._pause(OFFLINE_BACKOFF_S[idx],
                            "Soulseek odciął połączenie — zwalniam tempo")
            except Exception as exc:  # noqa: BLE001
                job.attempts += 1
                if job.attempts >= MAX_ATTEMPTS:
                    job.status, job.detail = "failed", f"błąd: {type(exc).__name__}"
                else:
                    job.status = "waiting"
            self._zapisz()

    def _na_koniec(self, job: Job) -> None:
        with self._lock:
            if job in self._jobs:
                self._jobs.remove(job)
                self._jobs.append(job)

    def _pause(self, seconds: int, note: str) -> None:
        self._paused_until = time.time() + seconds
        self._note = note


QUEUE = Queue()
