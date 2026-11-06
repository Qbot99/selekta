"""Lista życzeń szukana w tle — w aplikacji, nie tylko w terminalu.

Po co: interfejs obiecywał „apka poszuka go w Soulseeku”, a w serwerze nic
nie wołało wyszukiwania — pozycje wisiały jako „szukam” na zawsze, a
„Pobierz ponownie” uszkodzonego pliku tylko dopisywało go do listy.

Jak, z szacunkiem dla limitu Soulseeka (serwer ignoruje zbyt częste
zapytania i wtedy wszystko wygląda na „brak wyników”):
- jeden wątek, kilka pozycji na cykl, cykl co kilkanaście minut; ta sama
  pozycja najwcześniej po kilku godzinach;
- odstęp między zapytaniami wymusza klient (MIN_SEARCH_GAP_S), wspólny
  z kolejką pobierania; gdy kolejka pracuje, lista życzeń czeka;
- seria pustek przy żywym połączeniu = przerwa wg PUSTKI_BACKOFF_S
  (jak w kolejce), rozłączenie = przerwa wg OFFLINE_BACKOFF_S.

Pobieramy SAMI tylko plik o potwierdzonej tożsamości: cały tytuł w nazwie
pliku, zgodny artysta, brak obcych słów, ta sama wersja ORAZ zgodny czas
(±3 s). Pozycja bez znanego czasu (np. wydanie z radaru) z dobrym
kandydatem czeka na decyzję użytkownika („do potwierdzenia” + Pobierz) —
zły utwór w secie boli bardziej niż kliknięcie.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import requests

from . import dlqueue, matcher, wishlist
from .slskd_client import SearchHit, SlskdClient, SoulseekOffline

ODSTEP_CYKLU_S = 10 * 60      # co ile zaglądamy, czy jest coś do zrobienia
START_PO_S = 90               # po starcie apki: niech kolejka najpierw wznowi swoje
PONOW_PO_S = 6 * 3600         # ta sama pozycja najwcześniej po tylu sekundach
NA_CYKL = 4                   # pozycji na cykl (każda to drabina 1–8 zapytań)
ILE_KANDYDATOW = 25           # ilu najlepszych wyników sprawdzamy dokładnie

_WERSJE = matcher.MIX_WORDS | {"short", "live", "acoustic", "unplugged", "demo",
                               "reprise", "karaoke"}
_NEUTRALNE = {"extended"}     # „Extended/Original Mix” to dla DJ-a ta sama wersja


# ---------------------------------------------------------------- tożsamość

def _sygnatura(tokeny: list[str]) -> frozenset[str]:
    return frozenset(t for t in tokeny if t in _WERSJE) - _NEUTRALNE


def ocena(opis: dict, artist: str, title: str, duration_s: float | None) -> str:
    """„pewne” | „do-potwierdzenia” | „" (to nie ten utwór).

    `opis` to wynik SlskdClient.describe(). Warunki jak przy wymianie na
    lepszą wersję (zob. /api/upgrade/find), tylko ostrzejsze, bo nikt nie
    patrzy: cały tytuł w NAZWIE PLIKU (nie w folderach), co najmniej połowa
    słów artysty w ścieżce, najwyżej jedno obce słowo, ta sama wersja.
    „pewne” dodatkowo wymaga zgodnego czasu (±3 s).
    """
    if not str(opis.get("path", "")).lower().endswith(
            (".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg", ".opus")):
        return ""
    want = matcher.normalize(title or "")
    core_want = {t for t in want if t not in _WERSJE}
    if not core_want:
        return ""
    nazwa = os.path.splitext(str(opis.get("filename") or ""))[0]
    cand = matcher.normalize(nazwa)
    core_cand = {t for t in cand if t not in _WERSJE}
    if not core_want <= core_cand:
        return ""                                  # brakuje słów tytułu
    artysta = set(matcher.normalize(artist or ""))
    if artysta and (opis.get("artist_match") or 0) < 0.5:
        return ""                                  # ten sam tytuł, inny wykonawca
    obce = {t for t in core_cand - core_want - artysta if not t.isdigit() and len(t) > 1}
    if len(obce) >= 2:
        return ""                                  # „United” ≠ „United in Unhallowed Grace”
    if _sygnatura(want) != _sygnatura(cand):
        return ""                                  # remiks zamiast oryginału itp.
    delta = opis.get("duration_delta")
    if duration_s:
        if delta is None or delta > 3:
            return "" if (delta is not None and delta > 5) else "do-potwierdzenia"
        return "pewne"
    return "do-potwierdzenia"


def najlepszy(client: SlskdClient, hits: list[SearchHit], artist: str, title: str,
              duration_s: float | None) -> tuple[SearchHit | None, dict | None, str]:
    """Pierwszy (wg rankingu klienta) kandydat, który JEST tym utworem w tej wersji.

    Tożsamość sprawdza `client.pewny_wynik` — to samo porównanie co dopasowanie
    do biblioteki (wykonawca, tytuł, wersja miksu, czas). Sam automat pobiera
    tylko przy zgodnym czasie trwania; bez znanego czasu wynik czeka
    na potwierdzenie użytkownika.
    """
    pewny = client.pewny_wynik(hits[:ILE_KANDYDATOW], artist, title, duration_s)
    if pewny is not None:
        opis = client.describe(pewny, artist, title, duration_s)
        o = ocena(opis, artist, title, duration_s)
        return pewny, opis, (o or "do-potwierdzenia")
    # Bez czasu nie da się potwierdzić wersji („Extended Mix" przy wpisie bez
    # długości), ale użytkownik wciąż może zdecydować: nic nie pobieramy sami.
    for h in hits[:ILE_KANDYDATOW]:
        opis = client.describe(h, artist, title, duration_s)
        if ocena(opis, artist, title, duration_s):
            return h, opis, "do-potwierdzenia"
    return None, None, ""


# ---------------------------------------------------------------- pamięć listy

_ZAPIS = threading.Lock()


def aktualizuj(ident: str, **pola) -> dict | None:
    """Zmień pola jednej pozycji listy życzeń (wczytaj → zmień → zapisz).

    Wczytujemy na świeżo tuż przed zapisem: wyszukiwanie trwa minutę, a w tym
    czasie użytkownik mógł dopisać coś do listy — nie wolno tego nadpisać.
    """
    with _ZAPIS:
        wpisy = wishlist._load()
        for w in wpisy:
            if w.get("id") == ident:
                w.update(pola)
                wishlist._save(wpisy)
                return w
    return None


def _teraz() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _do_sprawdzenia(teraz: float) -> list[dict]:
    """Nieznalezione pozycje, których pora — najdłużej nieszukane najpierw."""
    gotowe = []
    for w in wishlist.items():
        if w.get("found") or w.get("kandydat") or not (w.get("artist") or w.get("title")):
            continue
        ostatnio = w.get("szukano_ts") or 0
        if teraz - ostatnio >= PONOW_PO_S:
            gotowe.append(w)
    return sorted(gotowe, key=lambda w: w.get("szukano_ts") or 0)


def _hit_dict(h: SearchHit) -> dict:
    return {"username": h.username, "filename": h.filename, "size": h.size,
            "bitrate": h.bitrate, "length_s": h.length_s, "is_lossless": h.is_lossless}


def pobierz_kandydata(ident: str, client: SlskdClient | None = None) -> dict:
    """Użytkownik potwierdził kandydata „do potwierdzenia” — zleć pobranie."""
    wpis = next((w for w in wishlist.items() if w.get("id") == ident), None)
    if not wpis or not wpis.get("kandydat"):
        raise LookupError("nie ma takiej pozycji albo kandydata do pobrania")
    k = wpis["kandydat"]
    client = client or SlskdClient()
    client.download(SearchHit(username=k["username"], filename=k["filename"],
                              size=int(k.get("size") or 0), bitrate=k.get("bitrate"),
                              length_s=k.get("length_s"),
                              is_lossless=bool(k.get("is_lossless")), free_slot=True))
    return aktualizuj(ident, found=True, found_at=_teraz(), found_hit=k, kandydat=None,
                      stan="zlecone", opis="pobranie zlecone po Twoim potwierdzeniu") or {}


# ---------------------------------------------------------------- wątek

class Poszukiwacz:
    """Wątek w tle: co ODSTEP_CYKLU_S sprawdza kilka pozycji listy życzeń."""

    def __init__(self) -> None:
        self._watek: threading.Thread | None = None
        self._stop = threading.Event()
        self._budzik = threading.Event()
        self.ostatni_cykl = 0.0
        self.nastepny_cykl = 0.0
        self.pauza_do = 0.0
        self.notka = ""
        self.w_toku = ""
        self.sprawdzonych = 0
        self.zleconych = 0
        self._pustki = 0
        self._offline = 0

    def start(self) -> None:
        if self._watek and self._watek.is_alive():
            return
        self._stop.clear()
        self.nastepny_cykl = time.time() + START_PO_S
        self._watek = threading.Thread(target=self._petla, daemon=True,
                                       name="lista-zyczen")
        self._watek.start()

    def stop(self) -> None:
        self._stop.set()
        self._budzik.set()

    def obudz(self) -> None:
        """„Szukaj teraz” — następny cykl od razu (limity tempa nadal obowiązują)."""
        self.nastepny_cykl = time.time()
        self._budzik.set()

    def stan(self) -> dict:
        teraz = time.time()
        return {
            "dziala": bool(self._watek and self._watek.is_alive()),
            "w_toku": self.w_toku,
            "notka": self.notka,
            "ostatni_cykl_s_temu": round(teraz - self.ostatni_cykl) if self.ostatni_cykl else None,
            "nastepny_za_s": max(0, round(max(self.nastepny_cykl, self.pauza_do) - teraz))
            if (self.nastepny_cykl or self.pauza_do) else None,
            "sprawdzonych": self.sprawdzonych,
            "zleconych": self.zleconych,
        }

    def _petla(self) -> None:
        while not self._stop.is_set():
            czekaj = max(self.nastepny_cykl, self.pauza_do) - time.time()
            if czekaj > 0:
                self._budzik.wait(min(czekaj, 60))
                self._budzik.clear()
                continue
            try:
                self.cykl()
            except Exception as exc:  # noqa: BLE001 — wątek tła nie może umrzeć
                self.notka = f"błąd: {type(exc).__name__}"
            self.nastepny_cykl = time.time() + ODSTEP_CYKLU_S

    def _przerwa(self, drabina: tuple[int, ...], licznik: str, notka: str) -> None:
        n = getattr(self, licznik)
        setattr(self, licznik, n + 1)
        self.pauza_do = time.time() + drabina[min(n, len(drabina) - 1)]
        self.notka = notka

    def cykl(self, client: SlskdClient | None = None) -> dict:
        """Jedno przejście: kilka pozycji, z pełnym poszanowaniem limitów."""
        wynik = {"sprawdzone": 0, "zlecone": 0, "do_potwierdzenia": 0, "pominiety": ""}
        self.ostatni_cykl = time.time()
        if time.time() < self.pauza_do:
            wynik["pominiety"] = "przerwa"
            return wynik
        kolejka = dlqueue.QUEUE.state().get("counts", {})
        if kolejka.get("waiting") or kolejka.get("searching"):
            # kolejka ma pierwszeństwo — oba źródła zapytań dzielą limit Soulseeka
            self.notka = "czekam, aż kolejka pobierania skończy"
            wynik["pominiety"] = "kolejka"
            return wynik
        do_zrobienia = _do_sprawdzenia(time.time())
        if not do_zrobienia:
            self.notka = ""
            wynik["pominiety"] = "nic"
            return wynik
        client = client or SlskdClient()
        if client.stan_api() != "ok" or not client.logged_in():
            self.notka = "czekam na połączenie z Soulseekiem"
            wynik["pominiety"] = "offline"
            return wynik
        self.notka = ""
        for wpis in do_zrobienia[:NA_CYKL]:
            if self._stop.is_set():
                break
            if client.network_down():
                # zalogowani, a serwer oddaje pustki — to on, nie utwory
                client.reset_empty_streak()
                self._przerwa(dlqueue.PUSTKI_BACKOFF_S, "_pustki",
                              "Soulseek nie oddaje wyników — odpoczywam")
                break
            artist, title = wpis.get("artist", ""), wpis.get("title", "")
            dur = wpis.get("duration_s")
            self.w_toku = f"{artist} — {title}"
            try:
                hits = client.search_track(artist, title, dur)
            except SoulseekOffline:
                self._przerwa(dlqueue.OFFLINE_BACKOFF_S, "_offline",
                              "Soulseek odciął połączenie — zwalniam")
                break
            except requests.RequestException:
                continue                       # spróbujemy w następnym cyklu
            finally:
                self.w_toku = ""
            self._offline = 0
            if hits:
                self._pustki = 0
            wynik["sprawdzone"] += 1
            self.sprawdzonych += 1
            pola = {"szukano_at": _teraz(), "szukano_ts": time.time(),
                    "proby": int(wpis.get("proby") or 0) + 1}
            hit, opis, o = najlepszy(client, hits, artist, title, dur)
            if o == "pewne":
                try:
                    client.download(hit)
                except requests.RequestException:
                    aktualizuj(wpis["id"], **pola, stan="szukam",
                               opis="znalezione, ale slskd nie przyjął pobrania — spróbuję później")
                    continue
                aktualizuj(wpis["id"], **pola, found=True, found_at=_teraz(),
                           found_hit=_hit_dict(hit), kandydat=None, stan="zlecone",
                           opis=f"pobieranie zlecone: {opis['filename']}")
                wynik["zlecone"] += 1
                self.zleconych += 1
            elif o == "do-potwierdzenia":
                aktualizuj(wpis["id"], **pola, kandydat=_hit_dict(hit),
                           stan="do-potwierdzenia",
                           opis=(f"jest „{opis['filename']}” ({opis['format']}"
                                 f"{' ' + str(opis['bitrate']) if opis.get('bitrate') else ''})"
                                 " — sprawdź i kliknij Pobierz"))
                wynik["do_potwierdzenia"] += 1
            else:
                aktualizuj(wpis["id"], **pola, stan="szukam",
                           opis=(f"jeszcze nie ma — {len(hits)} wyników, żaden pewny"
                                 if hits else "jeszcze nie ma na Soulseeku"))
        return wynik


POSZUKIWACZ = Poszukiwacz()
