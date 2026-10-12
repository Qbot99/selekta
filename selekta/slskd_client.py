"""Thin client for a locally running slskd daemon (Soulseek engine).

selekta does not ship or embed a Soulseek client — it talks to the
user's own slskd instance (https://github.com/slskd/slskd), exactly the
way DJ tools integrate with the user's own accounts. Configure with:

    export SELEKTA_SLSKD_URL=http://localhost:5030
    export SELEKTA_SLSKD_API_KEY=...
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass

import requests

# słowa, które nic nie mówią o tożsamości utworu
_NOISE = {"the", "a", "an", "feat", "ft", "featuring", "and", "vs", "original",
          "mix", "edit", "remix", "extended", "version", "radio", "vip", "dub"}
# ścieżka wygląda na godzinny set, nie pojedynczy utwór
_MIX_HINTS = ("live set", "dj set", "liveset", "mixtape", "podcast", "essential mix")


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    """Znaczące słowa: bez diakrytyków, bez szumu, min. 2 znaki."""
    words = re.split(r"[^a-z0-9]+", _strip_accents(text or ""))
    return [w for w in words if len(w) > 1 and w not in _NOISE]


# etykiety składanek — to nie są nazwy wykonawców i szukanie ich daje zero
_NOT_ARTISTS = {
    "various artists", "various", "va", "unknown artist", "unknown",
    "artist", "verschiedene", "diverse", "compilation", "soundtrack", "ost",
}


def primary_artist(artist: str) -> str:
    """Pierwszy PRAWDZIWY artysta z listy — Soulseek nie zna pełnych składów.

    „Nicolas Julian, STORM, AENJAY" → „Nicolas Julian". Pliki nazywają się
    nazwiskiem głównego wykonawcy, więc szukanie pełnej listy zwraca zero.

    Pomijamy przy tym etykiety składanek: playlisty potrafią podać
    „Various Artists, Dimitri Vegas & Like Mike, …, Da Hool" — szukanie
    „Various Artists" nie zwróci nic, więc bierzemy kolejnego z listy.
    """
    if not artist:
        return ""
    parts = re.split(r"\s*(?:,|&|/|\bfeat\.?\b|\bft\.?\b|\bvs\.?\b|\bx\b)\s*",
                     artist, flags=re.IGNORECASE)
    for part in parts:
        name = part.strip()
        if name and name.lower() not in _NOT_ARTISTS:
            return name
    return (parts[0].strip() if parts else "")


def core_title(title: str) -> str:
    """Tytuł bez nawiasowych dopisków — „Call Me (Extended Mix)" → „Call Me".

    Wersję miksu zostawiamy do oceniania trafności, ale do samego
    wyszukiwania szkodzi: zawęża wyniki do plików nazwanych identycznie.
    """
    return re.sub(r"[\(\[].*?[\)\]]", " ", title or "").strip() or (title or "")


def relevance(path: str, artist_tokens: list[str], title_tokens: list[str]) -> float:
    """Na ile ścieżka (plik + foldery) pasuje do artysty i tytułu: 0..1.

    Patrzymy na CAŁĄ ścieżkę, bo artysta bardzo często siedzi w nazwie
    folderu, a sam plik nazywa się „03 - tytul.flac".
    """
    hay = set(_tokens(path.replace("\\", "/")))
    if not hay:
        return 0.0
    scores = []
    for toks in (artist_tokens, title_tokens):
        if toks:
            scores.append(sum(1 for t in toks if t in hay) / len(toks))
    return sum(scores) / len(scores) if scores else 0.0


def _plausible(hit: SearchHit, want_duration_s: float | None) -> bool:
    """Odrzuć to, co na pewno nie jest szukanym utworem."""
    low = hit.filename.lower()
    if any(h in low for h in _MIX_HINTS):
        return False
    if hit.length_s and want_duration_s:
        # godzinny miks zawierający utwór albo urwana próbka
        if hit.length_s > want_duration_s * 2.2 or hit.length_s < want_duration_s * 0.5:
            return False
    elif hit.length_s and hit.length_s > 20 * 60:
        return False
    return True




class SoulseekOffline(RuntimeError):
    """slskd nie jest zalogowany do sieci Soulseek — szukanie nie ma sensu."""


# Soulseek zrywa połączenie klientom, którzy zasypują go zapytaniami
# ("Connection reset by peer"). Po takim odcięciu KAŻDE kolejne wyszukiwanie
# zwraca zero — i wygląda to, jakby algorytm nic nie znajdował. Dlatego
# odstęp między zapytaniami jest wymuszony, a stan połączenia sprawdzany.
PATH_ONLY_PENALTY = 0.8    # tytuł tylko w nazwie folderu — słabszy dowód
EMPTY_STREAK_LIMIT = 5     # po tylu pustkach z rzędu uznajemy sieć za padniętą
SEARCH_TIMEOUT_S = 8       # limit przekazywany slskd
SEARCH_WAIT_MIN_S = 45     # ile czekamy na stan „Completed" (patrz search())
# Serwer Soulseeka zaczyna IGNOROWAĆ zapytania klienta, który pyta za często:
# zmierzone 27.09.2026 — przy 2,5 s odstępu i ponowieniach każde kolejne
# zapytanie wracało puste (nawet „Madonna Hung Up"), a to samo zapytanie
# z osobnego procesu minutę później dawało 600 wyników. Sześć zapytań na
# minutę serwer toleruje.
MIN_SEARCH_GAP_S = 10.0
# ile razy ponowić zapytanie, które wróciło puste (serwer bywa chwiejny)
EMPTY_RETRIES = 1            # ile DODATKOWYCH przejść po całej drabinie, gdy wszystkie szczeble były puste
_last_search_at = 0.0



# --- strategia „scalająca drabina" -------------------------------------
# Dane z biblioteki użytkownika pokazały, że ŻADEN pojedynczy wariant
# zapytania nie pokrywa więcej niż 68% utworów. Kaskada z wczesnym
# wyjściem strukturalnie nie ma więc szans. Dlatego: scalamy wyniki
# kolejnych szczebli do wspólnej puli i schodzimy z drabiny dopiero,
# gdy mamy DOWÓD tożsamości (pełny tytuł w ścieżce + zgodny czas),
# a nie gdy cokolwiek się znalazło.
_AUDIO_EXT_HIT = (".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a",
                  ".ogg", ".opus", ".wma", ".alac", ".ape")
# kolejność kryteriów rankingu (malejąco)
# Kolejność kryteriów wyboru pliku. Najpierw tożsamość utworu (żeby nie
# ściągnąć nie tego), potem JAKOŚĆ, a dopiero na końcu popularność kopii.
# Zmierzone na 23 prawdziwych wyszukiwaniach: przesunięcie „loss"/„br"
# przed „nvar"/„copies" podniosło udział plików bezstratnych z 10/21 do
# 16/21 przy niezmienionej trafności 95%. Wcześniej rzadki FLAC przegrywał
# z rozpowszechnionym MP3 128 kbps — stąd biblioteka pełna 128-tek.
# „br" przed „free": 320 kbps z zajętym slotem ma wygrywać ze 128 kbps
# z wolnym — wolny slot przyspiesza pobranie, ale nie ratuje jakości
_RANK_ORDER = ("ok", "tcov", "d15", "acov", "d3",
               "loss", "br", "free", "nvar", "copies", "speed", "size")


def _fmt_speed(bps: int | None) -> str:
    """Prędkość wysyłania użytkownika po ludzku: „2,4 MB/s", „610 kB/s"."""
    if not bps or bps <= 0:
        return ""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f}".replace(".", ",") + " MB/s"
    return f"{round(bps / 1000)} kB/s"


def build_ladder(artist: str, title: str) -> list[str]:
    """Szczeble zapytań, od najwęższego do najszerszego.

    Ostatni szczebel to SAM ARTYSTA — dokładnie metoda, której DJ używa
    ręcznie w Nicotine+: wyszukać artystę, a tytuł dobrać z listy. Bywa
    jedyną, która trafia, bo długie zapytania Soulseek dopasowuje
    dosłownie i wiele poprawnych plików odpada przez inną pisownię.
    Sięgamy po niego dopiero, gdy węższe szczeble nic nie dały — jest
    najdroższy (setki wyników do przesiania lokalnie).
    """
    a, core, full = primary_artist(artist), core_title(title), (title or "").strip()
    seen, out = set(), []
    for q in (f"{a} {core}".strip(), f"{a} {full}".strip(), core, a):
        low = q.lower()
        if q and low not in seen:
            seen.add(low)
            out.append(q)
    return out


def _hit_features(hit: SearchHit, nvar: int, copies: int,
                  want_duration_s: float | None,
                  a_tok: list[str], t_tok: list[str]) -> dict:
    path = hit.filename.replace("\\", "/")
    hay = set(_tokens(path))
    # Tytuł liczymy przede wszystkim z NAZWY PLIKU. Po całej ścieżce nazwa
    # albumu udaje tytuł: przy szukaniu „Captain Jack" utwór „Sir Yes Sir"
    # z płyty tego zespołu wychodził jako trafienie w 100% — a tcov równe
    # 1.0 uznaje tożsamość za dowiedzioną i KOŃCZY wyszukiwanie.
    hay_plik = set(_tokens(os.path.basename(path)))
    if t_tok:
        z_pliku = sum(1 for t in t_tok if t in hay_plik) / len(t_tok)
        # Bywają pliki nazwane samym numerem, z tytułem tylko w folderze —
        # takie wolno znaleźć, ale z karą, żeby nigdy nie „dowiodły" tożsamości.
        z_calej = sum(1 for t in t_tok if t in hay) / len(t_tok)
        tcov = max(z_pliku, z_calej * PATH_ONLY_PENALTY)
    else:
        tcov = 0.0
    acov = sum(1 for t in a_tok if t in hay) / len(a_tok) if a_tok else 0.0
    length = hit.length_s
    delta = abs(length - want_duration_s) if (length and want_duration_s) else None
    low = path.lower()
    junk = (not low.endswith(_AUDIO_EXT_HIT)          # .lrc/.cue/.mp4 to nie utwór
            or any(h in low for h in _MIX_HINTS)      # godzinny set, nie singiel
            or bool(length and want_duration_s
                    and (length > want_duration_s * 2.2
                         or length < want_duration_s * 0.5)))
    return {"ok": 0 if junk else 1, "tcov": round(tcov, 2),
            "d15": bool(delta is not None and delta <= 15), "acov": round(acov, 2),
            "d3": bool(delta is not None and delta <= 3), "nvar": nvar,
            "copies": copies, "loss": bool(hit.is_lossless),
            "free": bool(hit.free_slot), "br": hit.bitrate or 0,
            "speed": hit.upload_speed or 0, "size": hit.size}


def _name_key(path: str) -> str:
    base = os.path.basename(path.replace("\\", "/"))
    return " ".join(_tokens(os.path.splitext(base)[0]))


def _identity_proven(feat: dict | None) -> bool:
    """Dowód tożsamości: cały tytuł w ścieżce, czas ±3 s, plik audio."""
    return bool(feat and feat["ok"] and feat["tcov"] >= 1.0 and feat["d3"])


@dataclass
class SearchHit:
    username: str
    filename: str
    size: int
    bitrate: int | None
    length_s: int | None
    is_lossless: bool
    free_slot: bool
    upload_speed: int | None = None    # B/s wg slskd (uploadSpeed użytkownika)
    queue_length: int | None = None    # ilu czeka w kolejce u tego użytkownika


class SlskdClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        from . import config  # import lokalny: unika cyklu przy starcie

        self.base = (base_url or config.get("slskd_url")
                     or "http://localhost:5030").rstrip("/")
        key = api_key or config.get("slskd_api_key") or ""
        self.headers = {"X-API-Key": key} if key else {}

    def _note_result(self, hits: list) -> None:
        """Zlicz puste odpowiedzi z rzędu — to miara kondycji połączenia."""
        if hits:
            self._empty_streak = 0
        else:
            self._empty_streak = getattr(self, "_empty_streak", 0) + 1

    def reset_empty_streak(self) -> None:
        """Zacznij liczyć pustki od nowa — po przerwie, którą dała kolejka.

        Bez tego licznik był lepki: raz przekroczony próg zostawał na zawsze
        w kliencie wątku roboczego i każde kolejne zadanie kończyło się
        natychmiast pustą listą, którą kolejka brała za „brak wyników".
        """
        self._empty_streak = 0

    def network_down(self) -> bool:
        """Czy dalsze zapytania są bez sensu (i szkodliwe).

        Seria pustych odpowiedzi to zwykle nie „nie ma tego utworu", tylko
        urwane połączenie z siecią Soulseek. Dalsze dobijanie serwera
        pogłębia problem: przy 4 szczeblach i 2 ponowieniach jeden utwór
        potrafi wysłać 12 zapytań, a masowa operacja — setki. Tak właśnie
        wyleciało skanowanie całej playlisty.
        """
        return getattr(self, "_empty_streak", 0) >= EMPTY_STREAK_LIMIT

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.base}/api/v0/session", headers=self.headers, timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    def stan_api(self) -> str:
        """Dlaczego API (nie) działa: "ok" | "klucz" | "brak" | "blad".

        available() zlewa w jedno „nie działa” dwie różne sytuacje: slskd
        wyłączony i slskd działający, ale odrzucający nasz klucz (401/403).
        Użytkownik dostawał wtedy „Uruchom slskd” i szukał problemu w złym
        miejscu — dokładnie po nadpisaniu slskd.yml innym kluczem.
        """
        try:
            r = requests.get(f"{self.base}/api/v0/session", headers=self.headers, timeout=5)
        except requests.RequestException:
            return "brak"
        if r.ok:
            return "ok"
        if r.status_code in (401, 403):
            return "klucz"
        return "blad"

    def logged_in(self) -> bool:
        """Czy slskd jest zalogowany do sieci Soulseek."""
        try:
            r = requests.get(f"{self.base}/api/v0/server",
                             headers=self.headers, timeout=5)
            return bool(r.ok and r.json().get("isLoggedIn"))
        except (requests.RequestException, ValueError):
            return False

    def _pace(self) -> None:
        """Nie wysyłaj zapytań szybciej, niż serwer toleruje."""
        global _last_search_at
        wait = MIN_SEARCH_GAP_S - (time.time() - _last_search_at)
        if wait > 0:
            time.sleep(wait)
        _last_search_at = time.time()

    def search(self, query: str, timeout_s: int = SEARCH_TIMEOUT_S) -> list[SearchHit]:
        """Jedno zapytanie do sieci Soulseek.

        UWAGA na sposób odbioru wyników: slskd oddaje je przez
        /searches/{id}/responses DOPIERO po zakończeniu wyszukiwania —
        w trakcie zwraca pustą listę. Zakończenie następuje zauważalnie
        później niż zadany `searchTimeout` (zmierzone: 8 s limitu →
        ok. 30 s do stanu „Completed"), bo demon czeka jeszcze na
        odpowiedzi rozproszone po sieci. Czytanie po samym `searchTimeout`
        dawało puste wyniki w 5 na 6 prób przy zapytaniach, które
        realnie zwracały ponad tysiąc plików.
        """
        self._pace()
        r = requests.post(
            f"{self.base}/api/v0/searches",
            json={"searchText": query, "searchTimeout": timeout_s * 1000},
            headers=self.headers,
            timeout=10,
        )
        if r.status_code == 409:
            raise SoulseekOffline(
                "slskd stracił połączenie z siecią Soulseek — poczekaj chwilę "
                "(serwer odcina za zbyt częste wyszukiwania) i spróbuj ponownie")
        r.raise_for_status()
        sid = r.json()["id"]
        deadline = time.time() + max(SEARCH_WAIT_MIN_S, timeout_s * 5)
        while time.time() < deadline:
            state = requests.get(
                f"{self.base}/api/v0/searches/{sid}", headers=self.headers, timeout=10
            ).json()
            if str(state.get("state", "")).startswith("Completed"):
                break
            time.sleep(0.7)
        resp = requests.get(
            f"{self.base}/api/v0/searches/{sid}/responses", headers=self.headers, timeout=20
        ).json()
        # slskd trzyma każde wyszukiwanie razem z pełnymi wynikami w pamięci.
        # Bez sprzątania kilkaset zapytań (np. duża playlista) doprowadza go
        # do "Out of memory" i demon pada w trakcie pobierania.
        try:
            requests.delete(f"{self.base}/api/v0/searches/{sid}",
                            headers=self.headers, timeout=10)
        except requests.RequestException:
            pass
        hits: list[SearchHit] = []
        for user in resp:
            for f in user.get("files", []):
                name = f.get("filename", "")
                hits.append(
                    SearchHit(
                        username=user.get("username", ""),
                        filename=name,
                        size=f.get("size", 0),
                        bitrate=f.get("bitRate"),
                        length_s=f.get("length"),
                        is_lossless=name.lower().endswith((".flac", ".wav", ".aiff")),
                        free_slot=user.get("hasFreeUploadSlot", False),
                        upload_speed=user.get("uploadSpeed"),
                        queue_length=user.get("queueLength"),
                    )
                )
        self._note_result(hits)
        return hits

    def rank(self, hits: list[SearchHit], want_duration_s: float | None,
             artist: str = "", title: str = "") -> list[SearchHit]:
        """Uszereguj wyniki od najbardziej prawdopodobnego.

        Kolejność kryteriów wynika z tego, co realnie dowodzi TOŻSAMOŚCI
        utworu, a nie z tego, co ładniej wygląda:

        1. trafność nazwy (czy ścieżka zawiera artystę i tytuł),
        2. zgodny czas trwania (±3 s) — najmocniejszy dowód,
        3. bezstratność, 4. bitrate, 5. wolny slot, 6. rozmiar.

        Format jest NIŻEJ niż czas i nazwa: FLAC innego utworu jest gorszy
        niż MP3 tego właściwego. Bitrate stoi PRZED wolnym slotem — slot
        przyspiesza pobranie, ale nie ratuje jakości, a popularna 128-tka
        z wolnym slotem ogrywała tu 320-tkę z kolejką. Rozmiar rozstrzyga
        na końcu, bo największy plik to zwykle godzinny miks zawierający
        utwór, a nie utwór.
        """
        a_tok, t_tok = _tokens(primary_artist(artist)), _tokens(title)

        def key(h: SearchHit):
            rel = relevance(h.filename, a_tok, t_tok)
            dur_ok = (
                want_duration_s and h.length_s
                and abs(h.length_s - want_duration_s) <= 3
            )
            return (round(rel, 2), bool(dur_ok), h.is_lossless,
                    h.bitrate or 0, h.free_slot, h.upload_speed or 0, h.size)

        return sorted(hits, key=key, reverse=True)

    def describe(self, hit: SearchHit, artist: str, title: str,
                 duration_s: float | None = None) -> dict:
        """Opis kandydata dla użytkownika — dane, na podstawie których wybiera.

        Zwraca też rozbicie dopasowania (tytuł / artysta / czas), żeby było
        widać, DLACZEGO coś jest wysoko, a nie tylko że jest.
        """
        a_tok, t_tok = _tokens(primary_artist(artist)), _tokens(title)
        sciezka = hit.filename.replace("\\", "/")
        # Tytuł liczymy z SAMEJ NAZWY PLIKU. Po całej ścieżce „Captain Jack"
        # trafiał w nazwę albumu i utwór „Sir Yes Sir" z tej samej płyty
        # wychodził na dopasowany w 100%.
        hay_plik = set(_tokens(os.path.basename(sciezka)))
        hay_cala = set(_tokens(sciezka))
        title_hits = [t for t in t_tok if t in hay_plik]
        ext = os.path.splitext(hit.filename)[1].lower().lstrip(".")
        delta = (abs(hit.length_s - duration_s)
                 if hit.length_s and duration_s else None)
        return {
            "path": hit.filename,
            "filename": os.path.basename(hit.filename.replace("\\", "/")),
            "folder": os.path.dirname(hit.filename.replace("\\", "/")),
            "user": hit.username,
            "size": hit.size,
            "size_mb": round(hit.size / 1_000_000, 1),
            "bitrate": hit.bitrate,
            "length_s": hit.length_s,
            "format": ext.upper() or "?",
            "lossless": hit.is_lossless,
            "free_slot": hit.free_slot,
            "speed_kbs": round(hit.upload_speed / 1000) if hit.upload_speed else None,
            "speed": _fmt_speed(hit.upload_speed),
            "queue": hit.queue_length,
            "title_match": round(len(title_hits) / len(t_tok), 2) if t_tok else 0.0,
            # artystę wolno brać z całej ścieżki — często jest tylko w folderze
            "artist_match": round(
                sum(1 for t in a_tok if t in hay_cala) / len(a_tok), 2) if a_tok else 0.0,
            "duration_delta": delta,
            "duration_ok": bool(delta is not None and delta <= 3),
        }

    def search_candidates(self, artist: str, title: str,
                          duration_s: float | None = None,
                          limit: int = 30, timeout_s: int = 15) -> list[dict]:
        """Wszystkie sensowne trafienia, uszeregowane — do wyboru przez człowieka."""
        hits = self.search_track(artist, title, duration_s, timeout_s=timeout_s)
        return [self.describe(h, artist, title, duration_s) for h in hits[:limit]]

    def search_track(self, artist: str, title: str,
                     duration_s: float | None = None,
                     timeout_s: int = 15) -> list[SearchHit]:
        """Znajdź utwór metodą „scalającej drabiny".

        Zamiast brać pierwszy wariant zapytania, który cokolwiek zwróci,
        SCALAMY wyniki kolejnych szczebli w jedną pulę i przerywamy dopiero
        po dowodzie tożsamości. Zmierzone na bibliotece użytkownika:
        87% trafień (sufit danych) wobec 74% starej kaskady, przy MNIEJSZEJ
        liczbie zapytań (~1,5 zamiast ~1,8 na utwór).
        """
        from collections import Counter

        a_tok, t_tok = _tokens(primary_artist(artist)), _tokens(title)
        pool: dict[tuple[str, str], list] = {}
        productive: set[str] = set()
        ranked: list[SearchHit] = []

        # Serwer Soulseeka bywa chwiejny: TO SAMO zapytanie zwraca raz
        # pustkę, raz komplet wyników. Dawniej ponawialiśmy każde puste
        # zapytanie od razu (3 próby na szczebel), ale seria szybkich zapytań
        # sama wywołuje ciszę serwera — i tak drabina zjadała limit pustek
        # na JEDNYM utworze. Teraz: jedno przejście po szczeblach, a dopiero
        # gdy wszystkie były puste, jedno ponowne przejście (EMPTY_RETRIES).
        szczeble = build_ladder(artist, title)
        dowiedzione = False
        for przejscie in range(EMPTY_RETRIES + 1):
            if przejscie and (pool or self.network_down()):
                break
            for query in szczeble:
                low = query.lower()
                if low in productive:
                    continue          # ten tekst już coś dał — nie marnuj zapytania
                if self.network_down():
                    # nie eskalujemy drabiny w martwą sieć — to ona dobija połączenie
                    if not self.logged_in():
                        raise SoulseekOffline(
                            "slskd wypadł z sieci Soulseek podczas wyszukiwania "
                            "— poczekaj chwilę i spróbuj ponownie")
                    break
                try:
                    hits = self.search(query, timeout_s=timeout_s)
                except SoulseekOffline:
                    raise
                except requests.RequestException:
                    hits = []
                for h in hits:
                    key = (h.username, h.filename)
                    if key in pool:
                        pool[key][1] += 1
                    else:
                        pool[key] = [h, 1]
                if hits:
                    productive.add(low)   # pustych wolno spróbować ponownie

                copies = Counter(_name_key(h.filename) for h, _ in pool.values())
                scored = [
                    (h, _hit_features(h, nvar, copies[_name_key(h.filename)],
                                      duration_s, a_tok, t_tok))
                    for h, nvar in pool.values()
                ]
                scored.sort(key=lambda x: tuple(x[1][f] for f in _RANK_ORDER),
                            reverse=True)
                ranked = [h for h, _ in scored]
                best_feat = scored[0][1] if scored else None
                if _identity_proven(best_feat):
                    dowiedzione = True
                    break
            if dowiedzione:
                break

        # Odsiew: kandydat bez ANI JEDNEGO słowa tytułu w całej ścieżce
        # nie jest tym utworem. Sam zgodny czas nie wystarcza — mnóstwo
        # utworów trwa podobnie, a kolejka bierze pierwszy wynik automatycznie
        # i pobrałaby przypadkowy plik. Tytuł liczymy z CAŁEJ ścieżki, więc
        # „Artysta - Tytuł/03 - x.flac" nadal przechodzi.
        keep = []
        copies = Counter(_name_key(h.filename) for h, _ in pool.values())
        for h in ranked:
            f = _hit_features(h, pool[(h.username, h.filename)][1],
                              copies[_name_key(h.filename)],
                              duration_s, a_tok, t_tok)
            if f["ok"] and f["tcov"] > 0:
                keep.append(h)
        return keep

    def download(self, hit: SearchHit) -> None:
        r = requests.post(
            f"{self.base}/api/v0/transfers/downloads/{hit.username}",
            json=[{"filename": hit.filename, "size": hit.size}],
            headers=self.headers,
            timeout=10,
        )
        r.raise_for_status()

    def downloads(self) -> list[dict]:
        """Wszystkie transfery pobierania, spłaszczone do wierszy dla UI.

        slskd grupuje je użytkownik -> katalog -> plik; kreator chce
        płaskiej listy, żeby dopasować plik do utworu z playlisty.
        """
        try:
            r = requests.get(f"{self.base}/api/v0/transfers/downloads",
                             headers=self.headers, timeout=10)
            r.raise_for_status()
            users = r.json()
        except (requests.RequestException, ValueError):
            return []
        rows: list[dict] = []
        for user in users or []:
            for directory in (user.get("directories") or []):
                for f in (directory.get("files") or []):
                    row = _transfer_row(f)
                    row["user"] = row["user"] or user.get("username", "")
                    rows.append(row)
        rows.sort(key=lambda x: (x["status"] != "active",
                                 _neg_iso(str(x.get("requested_at") or ""))))
        return rows

    def cancel_download(self, username: str, file_id: str) -> bool:
        """Przerwij jedno pobieranie (i usuń je z listy slskd)."""
        try:
            # Soulseek dopuszcza ?, #, / i spacje w nazwach użytkowników
            from urllib.parse import quote
            r = requests.delete(
                f"{self.base}/api/v0/transfers/downloads/"
                f"{quote(str(username), safe='')}/{quote(str(file_id), safe='')}",
                headers=self.headers, timeout=10)
            return r.status_code < 400
        except requests.RequestException:
            return False


def _neg_iso(value: str) -> tuple:
    """Klucz sortowania malejąco po dacie ISO (nowsze najpierw)."""
    return tuple(-ord(c) for c in value)


def _transfer_row(f: dict) -> dict:
    """Jeden plik z API transferów slskd -> wiersz dla interfejsu."""
    raw = str(f.get("state") or "")
    low = raw.lower()
    if "succeeded" in low:
        status = "done"
    elif "completed" in low:            # cancelled / errored / rejected
        status = "failed"
    elif "inprogress" in low:
        status = "active"
    else:                                # requested / queued
        status = "queued"
    name = os.path.basename(str(f.get("filename", "")).replace("\\", "/"))
    size = f.get("size") or 0
    return {
        "id": f.get("id", ""),
        "user": f.get("username", ""),
        "name": name,
        "path": f.get("filename", ""),
        "status": status,
        "state_raw": raw,
        "percent": round(float(f.get("percentComplete") or 0), 1),
        "size_mb": round(size / 1_000_000, 1),
        "done_mb": round((f.get("bytesTransferred") or 0) / 1_000_000, 1),
        "speed_kbs": round((f.get("averageSpeed") or 0) / 1000),
        "remaining": str(f.get("remainingTime") or "").split(".")[0],
        "requested_at": f.get("requestedAt") or "",
    }
