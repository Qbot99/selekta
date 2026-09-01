"""Folder obserwowany — nowe pliki analizują się same.

Po co: dziś po pobraniu utworu trzeba kliknąć „Analizuj wszystko", żeby
zobaczyć BPM, tonację i jakość. Przy pobieraniu w tle to bez sensu —
zanim wrócisz do apki, wszystko powinno być policzone.

Świadomie POLLING, nie FSEvents: przy kilkuset plikach przejście po
katalogu kosztuje milisekundy, a rozwiązanie działa tak samo na macOS,
Linuksie i Windowsie, bez dodatkowych zależności. Pliki wciąż pobierane
pomijamy — rosnący plik przeanalizowany w połowie dałby bzdurny wynik.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict

from . import cache, cues, harmonic, matcher, quality

ODSTEP_S = 12.0            # jak często zaglądamy do katalogu
SPOKOJ_S = 20.0            # plik musi być niezmieniony tyle czasu


class Obserwator:
    """Wątek w tle: znajduje nowe pliki i liczy dla nich analizy."""

    def __init__(self) -> None:
        self._folder = ""
        self._watek: threading.Thread | None = None
        self._stop = threading.Event()
        self._rozmiary: dict[str, tuple[int, float]] = {}
        self.wlaczony = True
        self.przeanalizowane = 0
        self.ostatni = ""
        self.ostatni_skan = 0.0
        self.w_toku = ""

    # ------------------------------------------------------------- sterowanie
    def start(self, folder: str) -> None:
        self._folder = folder
        if self._watek and self._watek.is_alive():
            return
        self._stop.clear()
        self._watek = threading.Thread(target=self._petla, daemon=True)
        self._watek.start()

    def stop(self) -> None:
        self._stop.set()

    def stan(self) -> dict:
        return {
            "wlaczony": self.wlaczony,
            "dziala": bool(self._watek and self._watek.is_alive()),
            "folder": self._folder,
            "przeanalizowane": self.przeanalizowane,
            "ostatni": self.ostatni,
            "w_toku": self.w_toku,
            "ostatni_skan_s_temu": (round(time.time() - self.ostatni_skan)
                                    if self.ostatni_skan else None),
        }

    # ------------------------------------------------------------------ praca
    def _ustabilizowany(self, path: str) -> bool:
        """Czy plik skończył się pobierać (rozmiar nie rośnie)."""
        try:
            st = os.stat(path)
        except OSError:
            return False
        teraz = time.time()
        poprzedni = self._rozmiary.get(path)
        self._rozmiary[path] = (st.st_size, teraz)
        if poprzedni is None:
            return False                     # pierwszy raz widzimy — poczekaj
        rozmiar, kiedy = poprzedni
        if rozmiar != st.st_size:
            return False                     # nadal rośnie
        return (teraz - kiedy) >= SPOKOJ_S

    def _do_zrobienia(self) -> list[str]:
        """Pliki bez kompletu analiz."""
        czekaja = []
        for path in matcher.audio_files(self._folder):
            if any(cache.get(path, k) is None
                   for k in ("harmonic", "quality", "cues")):
                czekaja.append(path)
        return czekaja

    def przeanalizuj(self, path: str) -> bool:
        """Policz brakujące analizy dla jednego pliku."""
        try:
            h = cache.get(path, "harmonic")
            if h is None:
                h = asdict(harmonic.analyze(path))
                cache.put(path, "harmonic", h)
            if cache.get(path, "quality") is None:
                rep = quality.analyze(path)
                cache.put(path, "quality", {"grade": rep.grade,
                                            "verdict": rep.verdict,
                                            "cutoff_hz": rep.cutoff_hz,
                                            "sample_rate": rep.sample_rate,
                                            "effective_bits": rep.effective_bits})
            if cache.get(path, "cues") is None:
                cache.put(path, "cues",
                          asdict(cues.analyze(path, bpm=h.get("bpm"))))
            return True
        except Exception:                      # noqa: BLE001
            return False                       # uszkodzony plik nie może zabić wątku

    def _petla(self) -> None:
        while not self._stop.is_set():
            if self.wlaczony and self._folder and os.path.isdir(self._folder):
                self.ostatni_skan = time.time()
                for path in self._do_zrobienia():
                    if self._stop.is_set() or not self.wlaczony:
                        break
                    if not self._ustabilizowany(path):
                        continue               # jeszcze się pobiera
                    self.w_toku = os.path.basename(path)
                    if self.przeanalizuj(path):
                        self.przeanalizowane += 1
                        self.ostatni = os.path.basename(path)
                    self.w_toku = ""
            self._stop.wait(ODSTEP_S)


OBSERWATOR = Obserwator()
