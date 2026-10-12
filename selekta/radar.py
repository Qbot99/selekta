"""New-release radar for artists already in your library.

Reads artist names from local file tags (mutagen), then polls public
Bandcamp and Beatport pages for releases we have not seen before.
State lives in ~/.selekta/radar.json as {artist: {last_check, seen}}.

Transport note: bandcamp.com sits behind a Fastly JS challenge that
blocks the TLS fingerprint of `requests` (any User-Agent). System curl
passes, so every fetch tries requests first and falls back to curl —
still zero pip dependencies. Artist discovery uses the HTML search page
when readable and otherwise Bandcamp's own public autocomplete JSON API.

Scraping is strictly best-effort: every network or parsing problem is
logged and swallowed — a page redesign must degrade to "no news",
never to a crash.

Pierwsze sprawdzenie artysty w danym sklepie tylko ZAPAMIĘTUJE jego katalog
(zgłasza wyłącznie wydania z datą z ostatnich NOWE_DNI dni) — wcześniej
zgłaszało cały katalog jako „nowości” (ABBA z 1997, „424 nowości”). Kolejne
sprawdzenia zgłaszają to, czego jeszcze nie widziano.

Bandcamp: stronę artysty bierzemy TYLKO przy dokładnej i jednoznacznej
zgodności nazwy — wcześniej przy braku trafienia brana była pierwsza
podpowiedź wyszukiwarki i radar meldował cudzą dyskografię jako nowości.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import subprocess
import time
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import requests
from mutagen import File as MutagenFile

from .wishlist import notify  # noqa: F401  (re-exported for callers)

log = logging.getLogger(__name__)

STATE_DIR = os.path.expanduser("~/.selekta")
STATE_PATH = os.path.join(STATE_DIR, "radar.json")
WYNIKI_PATH = os.path.join(STATE_DIR, "radar-wyniki.json")   # ostatnie znaleziska dla dashboardu
MAX_WYNIKOW = 500
NOWE_DNI = 90      # przy pierwszym sprawdzeniu: tylko wydania młodsze niż tyle dni

UA_STRING = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
UA = {"User-Agent": UA_STRING}
AUDIO_EXT = (".flac", ".mp3", ".wav", ".aiff", ".m4a", ".ogg")
TIMEOUT = 15
MIN_GAP_S = 1.0  # polite rate-limit between HTTP requests

_last_request = 0.0


# ---------------------------------------------------------------- library

def artists_from_library(folder: str) -> set[str]:
    """Collect artist names from audio tags under `folder` (recursive).

    Reads ARTIST/TPE1 via mutagen easy tags; multi-artist values are
    split on commas and whitespace is normalized.
    """
    artists: set[str] = set()
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if not name.lower().endswith(AUDIO_EXT):
                continue
            try:
                audio = MutagenFile(os.path.join(root, name), easy=True)
            except Exception:
                continue
            if audio is None:
                continue
            for value in audio.get("artist") or []:  # ARTIST / TPE1 alike
                for part in str(value).split(","):
                    cleaned = " ".join(part.split())
                    if cleaned:
                        artists.add(cleaned)
    return artists


# ---------------------------------------------------------------- state

def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def _load_results() -> dict:
    try:
        with open(WYNIKI_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_results(d: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = WYNIKI_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, WYNIKI_PATH)


def wyniki() -> dict:
    """Ostatnie znaleziska bez sieci — to pokazuje dashboard po wejściu."""
    d = _load_results()
    return {"items": d.get("items", []), "checked_at": d.get("checked_at"),
            "last": d.get("last") or {}}


def _zapamietaj(nowe: list[dict], kiedy: str, sprawdzonych: int, offset: int,
                artystow: int) -> None:
    """Dopisz znaleziska do radar-wyniki.json — to czyta ekran Radar."""
    stare = _load_results().get("items", [])
    klucze = {x.get("id") or x.get("url") for x in nowe}
    polaczone = nowe + [x for x in stare if (x.get("id") or x.get("url")) not in klucze]
    _save_results({"checked_at": kiedy, "items": polaczone[:MAX_WYNIKOW],
                   "last": {"checked": sprawdzonych, "offset": offset, "new": len(nowe),
                            "total_artists": artystow,
                            "next_offset": offset + sprawdzonych if offset + sprawdzonych < artystow else None}})


def _sprawdz_artyste(artist: str, kiedy: str) -> list[dict]:
    return [{**it, "artist": artist, "store": it.get("source"), "znalezione": kiedy}
            for it in check_bandcamp(artist) + check_beatport(artist)]


def sprawdz(folder: str, limit: int = 10, offset: int = 0,
            notify_new: bool = False) -> dict:
    """Sprawdź wycinek artystów w OBU sklepach i dopisz nowości do pamięci.

    `check_all` pisze na konsolę i sprawdza wszystkich naraz (minuty) —
    dashboard potrzebuje porcji: `limit` artystów od `offset`, wynik
    zapamiętany w radar-wyniki.json razem z datą, żeby kolejne wejście
    pokazywało listę bez czekania na sieć.
    """
    artists = sorted(artists_from_library(folder))
    porcja = artists[offset:offset + limit]
    kiedy = time.strftime("%Y-%m-%dT%H:%M:%S")
    nowe: list[dict] = []
    for artist in porcja:
        nowe += _sprawdz_artyste(artist, kiedy)
    _zapamietaj(nowe, kiedy, len(porcja), offset, len(artists))
    if nowe and notify_new:
        notify(f"{len(nowe)} nowości u {len({x['artist'] for x in nowe})} artystów",
               title="selekta radar")
    return {"new": nowe, "checked": len(porcja), "offset": offset,
            "total_artists": len(artists), "checked_at": kiedy,
            "next_offset": offset + len(porcja) if offset + len(porcja) < len(artists) else None}


def _swieze(item: dict, granica: str) -> bool:
    d = item.get("date")
    return bool(d) and str(d)[:10] >= granica


def _register(artist: str, found: list[dict], zrodlo: str | None = None) -> list[dict]:
    """Porównaj `found` z pamięcią artysty; zapisz i zwróć NOWOŚCI.

    Pierwsze sprawdzenie w danym sklepie tylko zapamiętuje katalog (zgłasza
    jedynie wydania z datą z ostatnich NOWE_DNI dni). Później: wszystko,
    czego nie widziano — poza wydaniami ze starą datą, które wyszukiwarka
    sklepu po prostu podsunęła dopiero teraz.
    """
    zrodlo = zrodlo or next((f.get("source") for f in found if f.get("source")), "")
    state = _load_state()
    rec = state.setdefault(artist, {"last_check": None, "seen": []})
    seen = set(rec.get("seen") or [])
    znane = set(rec.get("zrodla") or [])
    if "zrodla" not in rec and seen:       # pamięć sprzed tej zmiany
        if any(str(x).startswith("beatport:") for x in seen):
            znane.add("beatport")
        if any("bandcamp.com" in str(x) for x in seen):
            znane.add("bandcamp")
    granica = (date.today() - timedelta(days=NOWE_DNI)).isoformat()
    niewidziane = [f for f in found if f["id"] not in seen]
    if zrodlo not in znane:
        new = [f for f in niewidziane if _swieze(f, granica)]
    else:
        new = [f for f in niewidziane if not f.get("date") or _swieze(f, granica)]
    rec["seen"] = sorted(seen | {f["id"] for f in found})
    if found and zrodlo:
        znane.add(zrodlo)                  # pusta odpowiedź (awaria, brak strony) nie zasiewa
    rec["zrodla"] = sorted(znane)
    rec["last_check"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)
    return new


# ---------------------------------------------------------------- http

def _throttle() -> None:
    global _last_request
    wait = MIN_GAP_S - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _challenged(text: str) -> bool:
    """Detect the Fastly 'Client Challenge' bot-wall page."""
    head = text[:4000]
    return "Client Challenge" in head or "/_fs-ch-" in head


def _curl(url: str, post_json: str | None = None) -> str | None:
    """Fetch via system curl (its TLS fingerprint passes the bot-wall).

    Honoruje proxy ze środowiska: ścieżka requests je respektuje, a goły
    curl je omijał — radaru nie dało się odciąć od sieci ani przepuścić
    przez proxy, bo fallback i tak szedł prosto w internet.
    """
    cmd = ["curl", "-sL", "--max-time", str(TIMEOUT), "-A", UA_STRING]
    proxy = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
             or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy"))
    if proxy:
        cmd += ["--proxy", proxy]
    if post_json is not None:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json",
                "-d", post_json]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 5)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _get(url: str) -> str | None:
    """Rate-limited GET: requests first, curl fallback; None on failure."""
    _throttle()
    text = None
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.text
    except requests.RequestException as exc:
        log.debug("radar: requests nie dały rady dla %s (%s)", url, exc)
    if text is None or _challenged(text):
        text = _curl(url)
    if text is None or _challenged(text):
        log.warning("radar: nie udało się pobrać %s", url)
        return None
    return text


def _post_json(url: str, payload: dict) -> dict | None:
    """Rate-limited JSON POST with the same requests→curl fallback."""
    _throttle()
    body = json.dumps(payload)
    try:
        r = requests.post(url, data=body, timeout=TIMEOUT,
                          headers={**UA, "Content-Type": "application/json"})
        r.raise_for_status()
        if not _challenged(r.text):
            return r.json()
    except (requests.RequestException, json.JSONDecodeError):
        pass
    text = _curl(url, post_json=body)
    if text and not _challenged(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    log.warning("radar: nie udało się odpytać %s", url)
    return None


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def _strip_tags(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


# ---------------------------------------------------------------- bandcamp

_BC_RESULT_RE = re.compile(
    r'<div class="itemurl">\s*<a href="(https?://[^"/]+\.bandcamp\.com)[^"]*"'
)
_BC_HEADING_RE = re.compile(r'<div class="heading">\s*<a[^>]*>(.*?)</a>', re.S)
_BC_RELEASE_HREF_RE = re.compile(
    r'href="(?:https?://[^"/]+\.bandcamp\.com)?(/(?:album|track)/[^"?#]+)"'
)
_BC_TITLE_RE = re.compile(r'<p class="title">\s*(.*?)\s*</p>', re.S)
_BC_CLIENT_ITEMS_RE = re.compile(r'data-client-items="([^"]*)"')
_BC_IMG_RE = re.compile(r'<img[^>]+(?:data-original|src)="(https://f\d\.bcbits\.com/img/[^"]+)"')


def _norm_nazwa(s: str) -> str:
    """Nazwa artysty do porównań: bez wielkości liter, akcentów i interpunkcji.

    Granice słów zostają: „Boney M.” → „boney m”, a „boneyM” → „boneym”,
    więc podróbka z doklejonymi literami nie przechodzi.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"[\W_]+", " ", s)
    return " ".join(s.split())


def _jedyna_zgodna(artist: str, kandydaci: list[tuple[str, str]]) -> str | None:
    """Adres strony, gdy DOKŁADNIE jedna pozycja ma dokładnie tę nazwę.

    Dwie strony o tej samej nazwie (np. „Asia” z Włoch i „ASIA” z Francji,
    dwie różne „ABBA”) to niejednoznaczność — nie zgadujemy.
    """
    cel = _norm_nazwa(artist)
    zgodne = {url.rstrip("/") for name, url in kandydaci
              if url and _norm_nazwa(name) == cel}
    if len(zgodne) == 1:
        return zgodne.pop()
    if len(zgodne) > 1:
        log.info("radar: kilka stron Bandcamp o nazwie '%s' — pomijam", artist)
    return None


def _bandcamp_artist_page(artist: str) -> str | None:
    """Resolve an artist name to their bandcamp.com subdomain URL.

    Plan A parses the HTML search page; when that page is bot-walled or
    redesigned, plan B asks the site's own public autocomplete API.
    Bez dokładnej, jednoznacznej zgodności nazwy — brak strony (None).
    """
    if not _norm_nazwa(artist):
        return None
    page = _get(f"https://bandcamp.com/search?q={quote_plus(artist)}&item_type=b")
    if page:
        urls = _BC_RESULT_RE.findall(page)
        names = [_strip_tags(h) for h in _BC_HEADING_RE.findall(page)]
        pary = list(zip(names, urls))
        trafienie = _jedyna_zgodna(artist, pary)
        if trafienie or any(_norm_nazwa(n) == _norm_nazwa(artist) for n, _ in pary):
            return trafienie                  # jedna zgodna albo niejednoznaczność

    data = _post_json(
        "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic",
        {"search_text": artist, "search_filter": "b",
         "full_page": False, "fan_id": None},
    )
    results = ((data or {}).get("auto") or {}).get("results") or []
    return _jedyna_zgodna(artist, [(it.get("name", ""), it.get("item_url_root", ""))
                                   for it in results if it.get("type") == "b"])


def check_bandcamp(artist: str) -> list[dict]:
    """Return the artist's Bandcamp releases not seen before (pamięć radaru)."""
    return _register(artist, fetch_bandcamp(artist), "bandcamp")


def fetch_bandcamp(artist: str) -> list[dict]:
    """WSZYSTKIE wydania artysty z Bandcampu — bez pamięci radaru.

    Scans the /music page for /album/ and /track/ release links (many
    electronic artists publish singles as /track/), including overflow
    items hidden in the data-client-items JSON attribute. Each item:
    {id, title, url, source}. Empty list on any failure.
    Doktor używa tej funkcji, bo sprawdza działanie integracji, a nie
    „czy jest coś nowego” — z pamięcią każde kolejne sprawdzenie dawało 0.
    """
    base = _bandcamp_artist_page(artist)
    if not base:
        log.warning("radar: brak strony Bandcamp dla '%s'", artist)
        return []
    base = base.rstrip("/")
    page = _get(f"{base}/music")
    if not page:
        return []

    found: list[dict] = []
    seen_paths: set[str] = set()

    def add(path: str, title: str | None, cover: str | None = None) -> None:
        if path in seen_paths:
            return
        seen_paths.add(path)
        # bez tytułu: czytelna nazwa ze ścieżki („/track/body-beat” → „Body Beat”),
        # a nie surowe „/track/…”, które trafiało na listę życzeń
        tytul = title or path.rsplit("/", 1)[-1].replace("-", " ").strip().title()
        item = {"id": base + path, "title": tytul, "url": base + path,
                "source": "bandcamp"}
        if cover:
            item["cover"] = cover
        found.append(item)

    # walk <li> chunks so each release href pairs with its own title
    for chunk in page.split("<li")[1:]:
        m = _BC_RELEASE_HREF_RE.search(chunk)
        if not m:
            continue
        t = _BC_TITLE_RE.search(chunk)
        img = _BC_IMG_RE.search(chunk)
        add(m.group(1), _strip_tags(t.group(1)) if t else None,
            img.group(1) if img else None)

    # overflow releases not rendered in the grid
    m = _BC_CLIENT_ITEMS_RE.search(page)
    if m:
        try:
            for it in json.loads(html.unescape(m.group(1))):
                path = it.get("page_url")
                if path and path.startswith(("/album/", "/track/")):
                    art = it.get("art_id")
                    add(path, it.get("title"),
                        f"https://f4.bcbits.com/img/a{art}_2.jpg" if art else None)
        except (json.JSONDecodeError, AttributeError, TypeError):
            log.warning("radar: nieczytelne data-client-items dla '%s'", artist)

    # fallback: layouts without an <li> grid (e.g. single-release pages)
    for path in _BC_RELEASE_HREF_RE.findall(page):
        add(path, None)

    return found


# ---------------------------------------------------------------- beatport

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _walk_releases(node, out: list[dict]) -> None:
    """Recursively collect dicts that look like Beatport releases."""
    if isinstance(node, dict):
        name = node.get("release_name") or node.get("name")
        rid = node.get("release_id") or node.get("id")
        has_date = any(
            k in node for k in ("release_date", "new_release_date", "publish_date")
        )
        if name and rid and has_date and "artists" in node:
            out.append(node)
        for v in node.values():
            _walk_releases(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_releases(v, out)


def _release_artists(rel: dict) -> list[str]:
    names = []
    for a in rel.get("artists") or []:
        if isinstance(a, dict):
            n = a.get("artist_name") or a.get("name")
            if n:
                names.append(str(n))
    return names


def _beatport_okladka(rel: dict) -> str | None:
    """Adres okładki wydania z rekordu Beatportu (różne kształty JSON-a)."""
    for klucz in ("release_image_uri", "image_uri", "image", "release_image"):
        v = rel.get(klucz)
        if isinstance(v, dict):
            v = v.get("uri") or v.get("dynamic_uri")
        if isinstance(v, str) and v.startswith("http"):
            return v.replace("{w}x{h}", "500x500")
    return None


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return s or "release"


def check_beatport(artist: str) -> list[dict]:
    """Return unseen Beatport releases for `artist` (pamięć radaru)."""
    return _register(artist, fetch_beatport(artist), "beatport")


def fetch_beatport(artist: str) -> list[dict]:
    """WSZYSTKIE wydania artysty z wyszukiwarki Beatportu — bez pamięci radaru.

    Reads the embedded __NEXT_DATA__ JSON and walks it for release-shaped
    records, so minor reshuffles of the query tree still work. When the
    structure is unreadable this logs a warning and returns [] — the
    scraper degrades, it never raises.
    """
    page = _get(f"https://www.beatport.com/search?q={quote_plus(artist)}")
    if not page:
        return []
    m = _NEXT_DATA_RE.search(page)
    if not m:
        log.warning("radar: Beatport bez __NEXT_DATA__ — pomijam '%s'", artist)
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("radar: nieczytelny JSON Beatportu dla '%s'", artist)
        return []

    releases: list[dict] = []
    _walk_releases(data, releases)
    found, ids = [], set()
    for rel in releases:
        if not any(_norm(n) == _norm(artist) for n in _release_artists(rel)):
            continue
        rid = rel.get("release_id") or rel.get("id")
        key = f"beatport:{rid}"
        if key in ids:
            continue
        ids.add(key)
        title = str(rel.get("release_name") or rel.get("name"))
        date = (
            rel.get("release_date")
            or rel.get("new_release_date")
            or rel.get("publish_date")
        )
        item = {
            "id": key,
            "title": title,
            "url": f"https://www.beatport.com/release/{_slug(title)}/{rid}",
            "date": str(date)[:10] if date else None,
            "source": "beatport",
        }
        # okładka i wytwórnia — ekran Radar czyta it.cover i it.label, a
        # dotąd ich nie było (każda karta miała zaślepkę „okładka wydania”)
        okl = _beatport_okladka(rel)
        if okl:
            item["cover"] = okl
        lab = rel.get("label")
        nazwa_lab = (lab.get("label_name") or lab.get("name")) if isinstance(lab, dict) else lab
        if nazwa_lab:
            item["label"] = str(nazwa_lab)
        found.append(item)
    if not releases:
        log.warning(
            "radar: struktura wyników Beatportu nieczytelna dla '%s'", artist
        )
    return found


# ---------------------------------------------------------------- all

def check_all(folder: str, notify_new: bool = True) -> dict[str, list[dict]]:
    """Check every library artist on both stores; return {artist: new_items}.

    Only artists with something new appear in the result. Sends one
    summary macOS notification when `notify_new` and anything turned up.
    """
    news: dict[str, list[dict]] = {}
    artists = sorted(artists_from_library(folder))
    kiedy = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"radar: {len(artists)} artystów w bibliotece")
    wszystkie: list[dict] = []
    for artist in artists:
        print(f"· sprawdzam {artist}")
        fresh = _sprawdz_artyste(artist, kiedy)
        if fresh:
            news[artist] = fresh
            wszystkie += fresh
            for item in fresh:
                print(f"    ★ {item['title']}  {item['url']}")
    # te same znaleziska ma zobaczyć ekran Radar — wcześniej terminal
    # oznaczał je jako widziane, a dashboard nigdy ich nie pokazywał
    _zapamietaj(wszystkie, kiedy, len(artists), 0, len(artists))
    total = sum(len(v) for v in news.values())
    if news and notify_new:
        first = next(iter(news))
        notify(
            f"{total} nowości od {len(news)} artystów (m.in. {first})",
            title="selekta radar",
        )
    print(f"radar: {total} nowości u {len(news)} artystów")
    return news
