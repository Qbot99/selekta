"""Doktor — kontrola integracji, które psują się po cichu.

Spotify, Beatport, Bandcamp, YouTube i iTunes nie mają dla nas API: apka
czyta ich strony, a każda z nich może w dowolnym dniu zmienić strukturę.
Kod wtedy nie wywala się — po prostu zwraca pustkę, którą łatwo wziąć za
„nic nowego" albo „brak okładki". Ten moduł robi jedno: odpala prawdziwą
sondę każdej integracji na znanym, stałym celu i mówi wprost, która padła.

Wynik zapisujemy w ``~/.selekta/doktor.json`` z datą — dashboard pokazuje
„ostatnio sprawdzone: …", a ``selekta doctor`` w terminalu kończy się
niezerowym kodem, gdy coś nie działa.

Sondy są celowo wolne od siebie i każda ma własny limit czasu: jedna
zawieszona integracja nie może zablokować oceny pozostałych.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from . import config

PLIK_WYNIKU = os.path.join(config.STATE_DIR, "doktor.json")
LIMIT_S = 25.0

# stałe, publiczne cele sond — te same, których używają testy @network
SPOTIFY_TRACK = "6JkQb1qCCJDBV7kW5vJUAH"       # Hardwell, Maddix, Luciana - ACID
YOUTUBE_PLAYLIST = ("https://www.youtube.com/playlist"
                    "?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj")
ITUNES_PROBA = ("Daft Punk", "One More Time")
BEATPORT_ARTYSTA = "Charlotte de Witte"
BANDCAMP_ARTYSTA = "Aphex Twin"


@dataclass
class Sonda:
    nazwa: str
    ok: bool
    opis: str          # po ludzku: co sprawdzono i co wyszło
    ms: int = 0
    krytyczna: bool = True   # False = apka działa bez tego (np. radar)


# ---------------------------------------------------------------- sondy

def _ffmpeg() -> Sonda:
    from .narzedzia import ffmpeg_path, ffprobe_path
    brak = [n for n, f in (("ffmpeg", ffmpeg_path()), ("ffprobe", ffprobe_path()))
            if not (f and (os.path.isfile(f) or shutil.which(f)))]
    if brak:
        return Sonda("ffmpeg", False,
                     f"brak: {', '.join(brak)} — bez tego nie ma analizy audio")
    try:
        r = subprocess.run([ffmpeg_path(), "-version"], capture_output=True,
                           text=True, timeout=10)
        wersja = (r.stdout.splitlines() or ["?"])[0].split(" Copyright")[0]
    except (OSError, subprocess.SubprocessError) as e:
        return Sonda("ffmpeg", False, f"ffmpeg nie odpowiada: {e}")
    return Sonda("ffmpeg", True, wersja)


def _slskd() -> Sonda:
    from . import slskd_ctl
    s = slskd_ctl.status()
    # Najpierw to, co odpowiada API: slskd uruchomiony spoza znanych folderów
    # (Docker, inny HOME) działa, choć binarki nie znamy — wcześniej dostawał
    # „nie zainstalowany”.
    if s.reachable and not s.authorized:
        return Sonda("slskd", False, "działa, ale odrzuca klucz API selekty — "
                     "Ustawienia → Soulseek → „Wykryj automatycznie”", krytyczna=False)
    if not s.reachable:
        if not s.binary and not s.running:
            return Sonda("slskd", False, "nie zainstalowany — pobieranie z Soulseeka "
                         "nie zadziała (Ustawienia → krok 1)", krytyczna=False)
        if not s.running:
            return Sonda("slskd", False, "zainstalowany, ale nie uruchomiony",
                         krytyczna=False)
        return Sonda("slskd", False, "proces działa, ale nie odpowiada "
                     "(sprawdź adres w Ustawieniach)", krytyczna=False)
    if not s.logged_in:
        return Sonda("slskd", False, "działa, ale nie jest zalogowany do sieci "
                     "Soulseek", krytyczna=False)
    return Sonda("slskd", True, f"działa i jest zalogowany"
                 + (f" jako {s.username}" if s.username else ""))


def _spotify() -> Sonda:
    from . import spotify
    t = spotify.track(SPOTIFY_TRACK)
    if not t or not t.title or not t.artist:
        return Sonda("Spotify", False, "strona embed nie oddała metadanych — "
                     "Spotify zmienił strukturę, import playlist nie działa")
    return Sonda("Spotify", True, f'odczytano „{t.artist} — {t.title}”')


def _itunes() -> Sonda:
    from . import covers
    hit = covers.from_itunes(*ITUNES_PROBA)
    if not hit or not hit.data:
        return Sonda("iTunes (okładki)", False, "wyszukiwarka okładek nie "
                     "oddała znanego albumu — dociąganie okładek nie działa",
                     krytyczna=False)
    return Sonda("iTunes (okładki)", True,
                 f"okładka {len(hit.data) // 1024} kB dla {ITUNES_PROBA[0]}")


# Sondy radaru pytają o PEŁNY katalog (fetch_*), nie o nowości (check_*):
# pamięć „już widziane” dawała przy każdym kolejnym sprawdzeniu 0 wydań,
# czyli fałszywy alarm „strona mogła się zmienić”, a do tego dopisywała
# artystów sond do radaru użytkownika.
def _beatport() -> Sonda:
    from . import radar
    w = radar.fetch_beatport(BEATPORT_ARTYSTA)
    if not w:
        return Sonda("Beatport (radar)", False, f"0 wydań dla {BEATPORT_ARTYSTA} "
                     "— strona mogła się zmienić, radar milczy", krytyczna=False)
    return Sonda("Beatport (radar)", True, f"{len(w)} wydań dla {BEATPORT_ARTYSTA}",
                 krytyczna=False)


def _bandcamp() -> Sonda:
    from . import radar
    w = radar.fetch_bandcamp(BANDCAMP_ARTYSTA)
    if not w:
        return Sonda("Bandcamp (radar)", False, f"0 wydań dla {BANDCAMP_ARTYSTA} "
                     "— strona mogła się zmienić, radar milczy", krytyczna=False)
    return Sonda("Bandcamp (radar)", True, f"{len(w)} wydań dla {BANDCAMP_ARTYSTA}",
                 krytyczna=False)


def _youtube() -> Sonda:
    from . import importers
    t = importers.from_youtube(YOUTUBE_PLAYLIST)
    if not t:
        return Sonda("YouTube (playlisty)", False, "publiczna playlista dała 0 "
                     "utworów — import z YouTube nie działa", krytyczna=False)
    return Sonda("YouTube (playlisty)", True, f"{len(t)} utworów z playlisty",
                 krytyczna=False)


SONDY = [("ffmpeg", _ffmpeg), ("slskd", _slskd), ("Spotify", _spotify),
         ("iTunes (okładki)", _itunes), ("YouTube (playlisty)", _youtube),
         ("Beatport (radar)", _beatport), ("Bandcamp (radar)", _bandcamp)]

# sondy sieciowe pomijamy w trybie offline; lokalne (ffmpeg, slskd) zawsze
LOKALNE = {"ffmpeg", "slskd"}


def _odpal(nazwa: str, fn) -> Sonda:
    """Jedna sonda w wątku-demonie z limitem czasu.

    Celowo NIE ThreadPoolExecutor: jego wątki są dołączane przy wyjściu
    z interpretera, więc zawieszona sonda (np. martwe połączenie bez
    timeoutu) trzymałaby `selekta doctor` przy życiu długo po wydruku.
    Demon po prostu umiera razem z procesem.
    """
    wynik: list[Sonda] = []
    blad: list[BaseException] = []

    def praca():
        try:
            wynik.append(fn())
        except BaseException as e:  # noqa: BLE001 — każda sonda ma zawieść czysto
            blad.append(e)

    start = time.time()
    t = threading.Thread(target=praca, daemon=True, name=f"doktor:{nazwa}")
    t.start()
    t.join(LIMIT_S)
    if t.is_alive():
        s = Sonda(nazwa, False, f"brak odpowiedzi w {LIMIT_S:.0f} s")
    elif blad:
        e = blad[0]
        s = Sonda(nazwa, False, f"błąd: {type(e).__name__}: {e}")
    else:
        s = wynik[0]
    s.ms = int((time.time() - start) * 1000)
    return s


def zbadaj(tylko_lokalne: bool = False) -> dict:
    """Odpal wszystkie sondy równolegle i zapisz wynik."""
    wybrane = [(n, f) for n, f in SONDY if not tylko_lokalne or n in LOKALNE]
    wyniki: list[Sonda | None] = [None] * len(wybrane)

    def slot(i, n, f):
        wyniki[i] = _odpal(n, f)

    watki = [threading.Thread(target=slot, args=(i, n, f), daemon=True)
             for i, (n, f) in enumerate(wybrane)]
    for w in watki:
        w.start()
    for w in watki:
        w.join(LIMIT_S + 2)
    wyniki = [w or Sonda(n, False, "brak wyniku") for w, (n, _) in zip(wyniki, wybrane)]
    raport = {
        "kiedy": datetime.now().isoformat(timespec="seconds"),
        "wyniki": [asdict(s) for s in wyniki],
        "wszystko_ok": all(s.ok for s in wyniki),
        "krytyczne_ok": all(s.ok for s in wyniki if s.krytyczna),
    }
    try:
        os.makedirs(config.STATE_DIR, exist_ok=True)
        with open(PLIK_WYNIKU, "w", encoding="utf-8") as fh:
            json.dump(raport, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass                      # brak zapisu nie unieważnia diagnozy
    return raport


def ostatni() -> dict | None:
    """Ostatni zapisany wynik albo None."""
    try:
        with open(PLIK_WYNIKU, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def format_report(raport: dict) -> str:
    linie = [f"doktor — {raport['kiedy']}"]
    for s in raport["wyniki"]:
        ikona = "✅" if s["ok"] else ("❌" if s["krytyczna"] else "⚠️")
        linie.append(f"  {ikona} {s['nazwa']:20} {s['opis']}  ({s['ms']} ms)")
    if raport["wszystko_ok"]:
        linie.append("wszystkie integracje działają")
    elif raport["krytyczne_ok"]:
        linie.append("rdzeń działa; część integracji sieciowych milczy (patrz wyżej)")
    else:
        linie.append("brakuje czegoś, bez czego apka nie działa — patrz ❌")
    return "\n".join(linie)
