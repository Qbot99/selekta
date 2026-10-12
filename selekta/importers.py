"""Playlist importers for non-Spotify sources — plain-HTML scraping, stdlib + requests only.

Every source ships as its own ``from_*(url)`` function returning ``list[Track]``;
``resolve_any(text)`` dispatches on the URL host (Spotify links are delegated to
:mod:`selekta.spotify`) and falls back to parsing pasted text as a tracklist.

Extraction strategy per source (all without a JS engine):
- Apple Music   → ``serialized-server-data`` JSON (title/artist/duration/id),
                  fallback: schema.org ``MusicPlaylist`` in ``application/ld+json``.
- YouTube       → ``ytInitialData`` JSON (new ``lockupViewModel`` and legacy
                  ``playlistVideoRenderer`` layouts), "Artist - Title" split from
                  the video title.
- 1001tracklists→ schema.org microdata ``<meta itemprop=...>`` blocks in the HTML.
- SoundCloud    → ``window.__sc_hydration`` JSON (note: playlist hydration embeds
                  full metadata only for the first few tracks; the rest are lazy
                  stubs and are skipped).
- Tidal         → tries embedded JSON, but tidal.com is a JS shell; raises
                  ``ImportError`` with a clear (Polish) message when nothing is found.

Errors are always raised as ``ImportError`` with a Polish, user-facing message.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
from urllib.parse import parse_qs, urlparse

import requests

from .spotify import Lista, Track, resolve as spotify_resolve

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
TIMEOUT = 15

_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
_SERIALIZED_RE = re.compile(
    r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', re.S
)
_ISO_DUR_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")
_CLOCK_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d{2})$")

# --- tracklist line parsing -------------------------------------------------

_TIMESTAMP_PREFIX_RE = re.compile(r"^[\[\(]?\d{1,2}:\d{2}(?::\d{2})?[\]\)]?\s+")
_ORDINAL_PREFIX_RE = re.compile(r"^\d{1,3}\s*[.)\]]\s+")
_SEP_RE = re.compile(r"\s+[-–—]\s+")
_BY_RE = re.compile(r"^(.+)\s+by\s+(.+)$", re.I)
# „Stand by Me" to tytuł, nie „Stand" w wykonaniu „Me"
_BY_NIE_ARTYSTA = {"me", "you", "us", "them", "him", "her", "it", "myself",
                   "yourself", "night", "day", "my side", "your side", "the sea",
                   "the river", "the way", "now", "design", "default", "chance"}

# "(Official Music Video)" / "[Official Audio]" style noise in YouTube titles
_YT_NOISE_RE = re.compile(
    r"\s*[\(\[](?:official\s*)?(?:music\s*|lyric\s*|lyrics\s*)?"
    r"(?:videos?|audio|visuali[sz]er|hd|4k|m/v)[\)\]]",
    re.I,
)
# Dopisek w nawiasie jest szumem, gdy składa się WYŁĄCZNIE z tych słów
# i ma choć jeden znacznik „to jest film" — „(Official 4K Video)",
# „[HD Remaster]", „(Official Video HD)". „(Remastered 2009)" zostaje,
# bo to informacja o wersji nagrania, nie o filmie.
_YT_SZUM_SLOWA = {
    "official", "oficial", "officiel", "offizielles", "music", "musik", "video",
    "videos", "videoclip", "clip", "audio", "lyric", "lyrics", "visualizer",
    "visualiser", "hd", "hq", "4k", "8k", "uhd", "1080p", "720p", "60fps",
    "remaster", "remastered", "m", "v", "mv", "full", "teledysk", "oficjalny",
    "with", "in", "the", "new", "version",
}
_YT_ZNACZNIKI = {"video", "videos", "videoclip", "clip", "audio", "lyric", "lyrics",
                 "visualizer", "visualiser", "hd", "hq", "4k", "8k", "uhd", "1080p",
                 "720p", "60fps", "mv", "v", "teledysk"}
_YT_FILM = {"video", "videos", "videoclip", "clip", "mv", "v", "teledysk", "visualizer",
            "visualiser", "4k", "8k", "uhd", "1080p", "720p", "60fps"}
_GRUPA_RE = re.compile(r"\s*[\(\[]([^\(\)\[\]]*)[\)\]]")


def _oczysc_tytul_yt(title: str) -> tuple[str, bool]:
    """Tytuł filmu bez szumu + czy to teledysk (wtedy czas filmu ≠ czas
    utworu: „Thriller" trwa na YouTube 822 s)."""
    teledysk = False

    def zamien(m: re.Match) -> str:
        nonlocal teledysk
        slowa = [w for w in re.split(r"[^a-z0-9]+", m.group(1).lower()) if w]
        if slowa and all(w in _YT_SZUM_SLOWA for w in slowa) and \
                any(w in _YT_ZNACZNIKI for w in slowa):
            if any(w in _YT_FILM for w in slowa):
                teledysk = True
            return ""
        return m.group(0)

    czysty = _GRUPA_RE.sub(zamien, title)
    czysty = re.sub(r"\s{2,}", " ", czysty).strip()
    return czysty, teledysk


def split_artist_title(line: str) -> tuple[str, str] | None:
    """Split one tracklist line into (artist, title), or None when it has no separator.

    Handles leading numbering ("01.", "1)", "3]"), leading timestamps
    ("[0:23:45]", "23:45") and the dash variants "-", "–", "—" (space-surrounded,
    so hyphenated names like "Jean-Michel Jarre" survive intact).
    """
    s = line.strip()
    while True:
        stripped = _TIMESTAMP_PREFIX_RE.sub("", s, count=1)
        stripped = _ORDINAL_PREFIX_RE.sub("", stripped, count=1)
        if stripped == s:
            break
        s = stripped.strip()
    parts = _SEP_RE.split(s)
    if len(parts) < 2 and "\t" in s:
        # „Madonna<TAB>Hung Up" — kolumny z arkusza
        parts = [p for p in (x.strip() for x in s.split("\t")) if p]
    if len(parts) < 2:
        # „Hung Up by Madonna"
        m = _BY_RE.match(s)
        if m and m.group(2).strip().lower() not in _BY_NIE_ARTYSTA \
                and len(m.group(2).split()) <= 5:
            return m.group(2).strip(), m.group(1).strip()
        # „Madonna-Hung Up": jeden myślnik bez spacji; „Blink-182" (same
        # cyfry po myślniku) i „Jean-Michel Jarre - …" (są spacje) to nie to
        if s.count("-") == 1:
            a, t = (x.strip() for x in s.split("-"))
            if a and t and not t.isdigit() and re.search(r"[^\W\d_]", a) \
                    and re.search(r"[^\W\d_]", t):
                return a, t
        return None
    # "01 - Artist - Title": a bare 1-3 digit first segment is a track number
    if parts[0].isdigit() and len(parts[0]) <= 3 and len(parts) >= 3:
        parts = parts[1:]
    artist = parts[0].strip()
    title = " - ".join(p.strip() for p in parts[1:]).strip()
    if not artist or not title:
        return None
    return artist, title


# --- shared helpers ---------------------------------------------------------


def _fetch(url: str, extra_headers: dict | None = None) -> str:
    """GET a page as a desktop browser; raise ImportError (Polish) on failure."""
    headers = dict(UA)
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ImportError(f"błąd sieci przy pobieraniu {url}: {e}") from e
    if r.status_code == 403:
        raise ImportError(
            "źródło blokuje automatyczne pobieranie (HTTP 403, zapewne Cloudflare) — "
            f"otwórz {url} w przeglądarce i wklej tracklistę jako tekst"
        )
    if not r.ok:
        raise ImportError(f"nie udało się pobrać strony (HTTP {r.status_code}): {url}")
    # requests falls back to latin-1 when the header carries no charset (e.g. Apple
    # Music), garbling UTF-8 names — these pages are UTF-8 in practice
    if "charset" not in (r.headers.get("Content-Type") or "").lower():
        r.encoding = "utf-8"
    return r.text


def _synth_id(source: str, artist: str, title: str) -> str:
    """Stable synthetic id for tracks that have no Spotify id."""
    key = f"{source}:{artist.lower().strip()}:{title.lower().strip()}"
    return source + ":" + hashlib.md5(key.encode()).hexdigest()[:12]


def _dedupe(tracks: list[Track]) -> list[Track]:
    seen: set[tuple[str, str]] = set()
    out = []
    for t in tracks:
        key = (t.artist.lower().strip(), t.title.lower().strip())
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _iso_duration_s(value: str | None) -> float | None:
    """'PT5M56S' → 356.0 (schema.org ISO-8601 durations)."""
    if not value:
        return None
    m = _ISO_DUR_RE.fullmatch(value.strip())
    if not m or not any(m.groups()):
        return None
    h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _clock_s(value: str | None) -> float | None:
    """'3:45' / '1:02:03' → seconds."""
    if not value:
        return None
    m = _CLOCK_RE.match(value.strip())
    if not m:
        return None
    h = float(m.group(1) or 0)
    return h * 3600 + float(m.group(2)) * 60 + float(m.group(3))


def _walk(obj, visit) -> None:
    """Depth-first walk over nested dict/list JSON, calling visit(dict) in order."""
    if isinstance(obj, dict):
        visit(obj)
        for v in obj.values():
            _walk(v, visit)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, visit)


def _json_after(text: str, marker: str):
    """Decode the JSON object/array that follows the first `marker` in text."""
    idx = text.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    while start < len(text) and text[start] not in "[{":
        if text[start] not in " \t\r\n=:":
            return None
        start += 1
    if start >= len(text):
        return None
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except ValueError:
        return None


# --- sources ----------------------------------------------------------------


def from_text(text: str) -> list[Track]:
    """Parse pasted plain-text tracklist lines into Tracks.

    Linie, których nie rozumiemy, są pomijane — ale NIE po cichu: trafiają
    do uwag, żeby użytkownik wiedział, że część listy przepadła.
    """
    tracks = []
    pominiete: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        pair = split_artist_title(line)
        if not pair:
            pominiete.append(line)
            continue
        artist, title = pair
        tracks.append(Track(id=_synth_id("text", artist, title), artist=artist, title=title))
    out = Lista(_dedupe(tracks))
    if pominiete:
        pokaz = ", ".join(f"„{p[:60]}”" for p in pominiete[:5])
        reszta = f" i {len(pominiete) - 5} innych" if len(pominiete) > 5 else ""
        out.uwagi.append(f"Pominięto {len(pominiete)} linii, których nie rozumiem: "
                         f"{pokaz}{reszta}. Użyj formatu „Artysta - Tytuł”.")
    if len(out) < len(tracks):
        out.uwagi.append(f"Pominięto {len(tracks) - len(out)} powtórzonych utworów.")
    return out


_APPLE_SONG_RE = re.compile(r"music\.apple\.com/(?:([a-z]{2})/)?song/(?:[^/?#]+/)?(\d+)")
_APPLE_CC_RE = re.compile(r"music\.apple\.com/([a-z]{2})/")


def _apple_track_id(url: str) -> tuple[str | None, str]:
    """Id utworu z linku „Udostępnij utwór": /album/…/ID?i=UTWÓR albo /song/…/ID."""
    cc = (_APPLE_CC_RE.search(url) or [None, "us"])[1]
    i = (parse_qs(urlparse(url).query).get("i") or [None])[0]
    if i and i.isdigit():
        return i, cc
    m = _APPLE_SONG_RE.search(url)
    if m:
        return m.group(2), m.group(1) or cc
    return None, cc


def _apple_single(track_id: str, cc: str) -> list[Track]:
    """Jeden utwór przez publiczne iTunes Lookup API (bez klucza)."""
    try:
        r = requests.get("https://itunes.apple.com/lookup",
                         params={"id": track_id, "country": cc}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        wyniki = r.json().get("results") or []
    except (requests.RequestException, ValueError) as e:
        raise ImportError(f"nie udało się odczytać utworu z Apple Music: {e}") from e
    for it in wyniki:
        if it.get("wrapperType") == "track" and it.get("trackName"):
            artist = it.get("artistName", "")
            return [Track(id=str(it.get("trackId") or track_id), artist=artist,
                          title=it["trackName"],
                          duration_s=(it.get("trackTimeMillis") or 0) / 1000 or None,
                          preview_url=it.get("previewUrl", ""),
                          artists=[a.strip() for a in artist.split(",") if a.strip()])]
    raise ImportError("Apple Music nie zna tego utworu (usunięty albo niedostępny "
                      "w tym kraju)")


def from_apple_music(url: str) -> list[Track]:
    """Tracks from a public music.apple.com playlist/album page — albo jeden
    utwór z linku „Udostępnij utwór" (dawniej ?i= ignorowane: 58 utworów
    całego albumu zamiast 1, a /song/ kończył się błędem).

    Primary source: the `serialized-server-data` JSON (has artist + duration + id);
    fallback: the schema.org MusicPlaylist ld+json (titles + durations only).
    """
    track_id, cc = _apple_track_id(url)
    if track_id:
        return _apple_single(track_id, cc)
    page = _fetch(url)
    tracks: list[Track] = []

    # album/playlist-level artist, useful when per-item artistName is missing
    header_artist = ""
    for m in _LDJSON_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        by = data.get("byArtist")
        if isinstance(by, dict):
            header_artist = by.get("name", "")
        elif isinstance(by, list) and by:
            header_artist = ", ".join(a.get("name", "") for a in by if isinstance(a, dict))

    m = _SERIALIZED_RE.search(page)
    if m:
        try:
            sd = json.loads(m.group(1))
        except ValueError:
            sd = None
        if sd is not None:
            items: list[dict] = []

            def visit(d: dict) -> None:
                # track rows carry title + trackNumber + duration (ms)
                if (
                    isinstance(d.get("title"), str)
                    and "trackNumber" in d
                    and isinstance(d.get("duration"), (int, float))
                ):
                    items.append(d)

            _walk(sd, visit)
            for it in items:
                artist = it.get("artistName") or header_artist
                title = it["title"]
                ident = (
                    ((it.get("contentDescriptor") or {}).get("identifiers") or {}).get(
                        "storeAdamID"
                    )
                    or _synth_id("apple", artist, title)
                )
                tracks.append(
                    Track(
                        id=str(ident),
                        artist=artist,
                        title=title,
                        duration_s=float(it["duration"]) / 1000 or None,
                        artists=[a.strip() for a in artist.split(",") if a.strip()],
                    )
                )

    if not tracks:  # fallback: schema.org ld+json (no per-track artist)
        for m in _LDJSON_RE.finditer(page):
            try:
                data = json.loads(m.group(1))
            except ValueError:
                continue
            if data.get("@type") not in ("MusicPlaylist", "MusicAlbum"):
                continue
            for entry in data.get("track") or data.get("tracks") or []:
                title = entry.get("name", "")
                if not title:
                    continue
                by = entry.get("byArtist") or (entry.get("audio") or {}).get("byArtist")
                artist = (by or {}).get("name", "") if isinstance(by, dict) else header_artist
                tracks.append(
                    Track(
                        id=_synth_id("apple", artist, title),
                        artist=artist,
                        title=title,
                        duration_s=_iso_duration_s(entry.get("duration")),
                    )
                )

    if not tracks:
        raise ImportError(
            "nie znaleziono osadzonej listy utworów na stronie Apple Music — "
            "sprawdź, czy link prowadzi do publicznej playlisty lub albumu"
        )
    return _dedupe(tracks)


_YT_COOKIE = {"Cookie": "SOCS=CAI; CONSENT=YES+cb.20210328-17-p0.en+FX+419"}
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_MAX_STRON = 60          # 60 stron kontynuacji ≈ 6000 filmów — bezpiecznik


def _yt_track(title: str, channel: str, dur: float | None) -> Track | None:
    clean, teledysk = _oczysc_tytul_yt(title)
    clean = re.sub(r"\s{2,}", " ", _YT_NOISE_RE.sub("", clean)).strip()
    pair = split_artist_title(clean)
    if pair:
        artist, name = pair
    else:
        artist = re.sub(r"\s*-\s*Topic$", "", channel or "").strip()
        name = clean.strip()
    if not name:
        return None
    return Track(id=_synth_id("yt", artist, name), artist=artist, title=name,
                 # czas teledysku to nie czas utworu — nie mylmy nim dopasowania
                 duration_s=None if teledysk else dur)


def _yt_video_id(url: str) -> str | None:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if host.endswith("youtu.be"):
        vid = p.path.strip("/").split("/")[0]
    elif p.path.startswith(("/shorts/", "/live/", "/embed/")):
        vid = p.path.split("/")[2] if len(p.path.split("/")) > 2 else ""
    else:
        vid = (parse_qs(p.query).get("v") or [""])[0]
    return vid if _YT_ID_RE.match(vid or "") else None


def _yt_single(video_id: str) -> list[Track]:
    """Jeden film = jeden utwór (dawniej: 19–20 „utworów" z panelu polecanych,
    m.in. odcinek „Świata według Kiepskich")."""
    page = _fetch(f"https://www.youtube.com/watch?v={video_id}", _YT_COOKIE)
    pr = _json_after(page, "ytInitialPlayerResponse") or {}
    vd = pr.get("videoDetails") or {}
    title, author = vd.get("title") or "", vd.get("author") or ""
    secs = vd.get("lengthSeconds")
    if not title:
        try:  # oEmbed: tytuł i kanał, bez czasu
            r = requests.get("https://www.youtube.com/oembed",
                             params={"url": f"https://www.youtube.com/watch?v={video_id}",
                                     "format": "json"}, headers=UA, timeout=TIMEOUT)
            if r.ok:
                d = r.json()
                title, author = d.get("title") or "", d.get("author_name") or ""
        except (requests.RequestException, ValueError):
            pass
    if not title:
        raise ImportError("nie udało się odczytać tytułu filmu YouTube — "
                          "sprawdź, czy film jest publiczny")
    t = _yt_track(title, author, float(secs) if secs else None)
    return [t] if t else []


def _yt_raw_items(data) -> tuple[list[tuple[str, str, float | None]], list[str]]:
    """(tytuł, kanał, czas) pozycji playlisty + tokeny kontynuacji."""
    raw: list[tuple[str, str, float | None]] = []
    tokens: list[str] = []

    def visit(d: dict) -> None:
        cc = d.get("continuationCommand")
        if isinstance(cc, dict) and isinstance(cc.get("token"), str):
            tokens.append(cc["token"])
        if "lockupViewModel" in d:
            lv = d["lockupViewModel"]
            if not isinstance(lv, dict):
                return
            if lv.get("contentType") not in (None, "LOCKUP_CONTENT_TYPE_VIDEO"):
                return
            md = (lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}
            title = (md.get("title") or {}).get("content") or ""
            channel = ""
            rows = ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get(
                "metadataRows"
            ) or []
            for row in rows:
                for part in row.get("metadataParts") or []:
                    channel = (part.get("text") or {}).get("content") or ""
                    if channel:
                        break
                if channel:
                    break
            badge = re.search(
                r'"text":\s*"(\d+:\d{2}(?::\d{2})?)"', json.dumps(lv.get("contentImage") or {})
            )
            if title:
                raw.append((title, channel, _clock_s(badge.group(1)) if badge else None))
        elif "playlistVideoRenderer" in d:
            pv = d["playlistVideoRenderer"]
            if not isinstance(pv, dict):
                return
            t = pv.get("title") or {}
            title = t.get("simpleText") or "".join(
                r.get("text", "") for r in t.get("runs") or []
            )
            by = pv.get("shortBylineText") or {}
            channel = (by.get("runs") or [{}])[0].get("text", "")
            secs = pv.get("lengthSeconds")
            if title:
                raw.append((title, channel, float(secs) if secs else None))

    _walk(data, visit)
    return raw, tokens


def _yt_total(data) -> int | None:
    """Liczba filmów z nagłówka playlisty („186 filmów")."""
    found: list[int] = []

    def visit(d: dict) -> None:
        for key in ("stats", "numVideosText", "videoCountText"):
            v = d.get(key)
            if v and not found:
                m = re.search(r"(\d[\d\s\u00a0.,]*)", json.dumps(v, ensure_ascii=False))
                if m:
                    n = re.sub(r"\D", "", m.group(1))
                    if n:
                        found.append(int(n))

    _walk(data, visit)
    return found[0] if found else None


def _yt_kontynuacje(page: str, tokens: list[str]) -> tuple[list, bool]:
    """Dociągnij kolejne strony playlisty (YouTube ładuje je po 100)."""
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
    ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
    if not (key and ver and tokens):
        return [], bool(tokens)
    raw: list = []
    token, uzyte = tokens[0], set()
    for _ in range(YT_MAX_STRON):
        uzyte.add(token)
        try:
            r = requests.post(
                f"https://www.youtube.com/youtubei/v1/browse?key={key.group(1)}&prettyPrint=false",
                json={"context": {"client": {"clientName": "WEB",
                                             "clientVersion": ver.group(1),
                                             "hl": "en", "gl": "US"}},
                      "continuation": token},
                headers={**UA, **_YT_COOKIE, "Content-Type": "application/json"},
                timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return raw, True                  # przerwane — wiemy, że czegoś brakuje
        nowe, dalej = _yt_raw_items(data)
        raw.extend(nowe)
        dalej = [t for t in dalej if t not in uzyte]
        if not dalej or not nowe:
            return raw, False
        token = dalej[0]
    return raw, True


def from_youtube(url: str) -> list[Track]:
    """Tracks from a public youtube.com / music.youtube.com playlist — albo
    jeden utwór z linku do pojedynczego filmu.

    Parses `ytInitialData` (both the current lockupViewModel layout and the older
    playlistVideoRenderer one). Video titles like "Artist - Title (Extended Mix)"
    are split with split_artist_title; otherwise the channel name becomes the artist.
    Playlisty dłuższe niż 100 dociągamy stronami kontynuacji (jak przeglądarka);
    gdy się nie uda, uwaga mówi „zaimportowano X z Y".
    """
    parsed = urlparse(url)
    playlist_id = (parse_qs(parsed.query).get("list") or [None])[0]
    if not playlist_id:
        vid = _yt_video_id(url)
        if vid:
            return _yt_single(vid)
        raise ImportError("link YouTube nie prowadzi ani do playlisty (brak list=), "
                          "ani do filmu")
    # canonical desktop page; music.youtube.com is a pure JS shell
    url = f"https://www.youtube.com/playlist?list={playlist_id}"

    # EU consent cookies, otherwise the request bounces to consent.youtube.com
    page = _fetch(url, _YT_COOKIE)
    data = _json_after(page, "ytInitialData")
    if data is None:
        raise ImportError(
            "nie znaleziono danych ytInitialData na stronie YouTube — "
            "sprawdź, czy playlista jest publiczna"
        )

    raw, tokens = _yt_raw_items(data)
    total = _yt_total(data)
    przerwane = False
    if tokens and raw:
        dalsze, przerwane = _yt_kontynuacje(page, tokens)
        raw.extend(dalsze)

    tracks = []
    for title, channel, dur in raw:
        t = _yt_track(title, channel, dur)
        if t:
            tracks.append(t)
    if not tracks:
        raise ImportError(
            "playlista YouTube nie zawiera pozycji (prywatna, usunięta lub pusta?)"
        )
    out = Lista(_dedupe(tracks), zrodlo_total=total)
    if przerwane:
        out.uwagi.append(
            f"YouTube oddał {len(raw)} z {total or 'wielu'} filmów playlisty — "
            "reszty nie udało się pobrać (spróbuj ponownie albo wklej resztę jako tekst).")
    elif total and len(raw) < total:
        out.uwagi.append(
            f"Zaimportowano {len(raw)} z {total} filmów — pozostałe są prywatne, "
            "usunięte albo niedostępne w Polsce.")
    if len(out) < len(raw):
        out.uwagi.append(f"Pominięto {len(raw) - len(out)} powtórzonych filmów.")
    return out


def from_1001tracklists(url: str) -> list[Track]:
    """Tracks from a 1001tracklists.com tracklist page (schema.org microdata metas).

    The site sits behind Cloudflare — an HTTP 403 surfaces as ImportError telling
    the user to open the page in a browser instead.
    """
    page = _fetch(url)

    def meta(chunk: str, prop: str) -> str:
        m = re.search(r'<meta itemprop="%s" content="([^"]*)"' % prop, chunk)
        return htmllib.unescape(m.group(1)).strip() if m else ""

    tracks = []
    for chunk in page.split('itemprop="tracks"')[1:]:
        chunk = chunk[:6000]  # metas sit right at the top of each itemscope block
        name = meta(chunk, "name")
        artist = meta(chunk, "byArtist")
        dur = _iso_duration_s(meta(chunk, "duration"))
        if not name:
            continue
        if artist and name.lower().startswith(artist.lower() + " - "):
            title = name[len(artist) + 3 :].strip()
        else:
            pair = split_artist_title(name)
            if pair and not artist:
                artist, title = pair
            elif pair:
                title = pair[1]
                # „Artysta ft. Gość - Tytuł": byArtist podaje samego artystę,
                # gość ginął — bierzemy pełny zapis z nazwy pozycji
                if pair[0].lower().startswith(artist.lower()) and len(pair[0]) > len(artist):
                    artist = pair[0]
            else:
                title = name
        if artist.upper() == "ID" and title.upper() == "ID":
            continue  # unreleased/unidentified placeholder
        tracks.append(
            Track(
                id=_synth_id("1001", artist, title),
                artist=artist,
                title=title,
                duration_s=dur,
            )
        )
    if not tracks:
        raise ImportError(
            "nie znaleziono utworów na stronie 1001tracklists — strona mogła zmienić "
            "format albo wymaga otwarcia w przeglądarce"
        )
    return _dedupe(tracks)


_SC_WERSJA = {"mix", "remix", "edit", "extended", "original", "radio", "club", "dub",
              "vip", "bootleg", "rework", "version", "instrumental", "acapella",
              "flip", "mashup", "remaster", "remastered", "live", "rmx"}


def _sc_artist_title(title: str, publisher_artist: str, username: str) -> tuple[str, str]:
    """Wykonawca i tytuł z utworu SoundCloud.

    Wytwórnie wrzucają „Stan Christ - Lucid Dreams", a w publisher_metadata
    wpisują siebie („Revised Records") — dawniej artystą była wytwórnia,
    a tytuł zostawał z nazwiskiem. Gdy tytuł ma postać „Wykonawca - Tytuł",
    to ona rozstrzyga; wyjątkiem jest „Tytuł - Extended Mix" (sama wersja
    po myślniku).
    """
    pair = split_artist_title(title)
    if pair:
        prawa = {w for w in re.split(r"[^a-z0-9]+", pair[1].lower()) if w}
        if not (prawa and prawa <= _SC_WERSJA):
            return pair
    if publisher_artist:
        return publisher_artist, title
    return username, title


def _sc_client_id(page: str) -> str | None:
    """Publiczny client_id aplikacji webowej SoundCloud (ten, którego używa
    przeglądarka do doczytania listy) — szukany w skryptach strony."""
    for src in reversed(re.findall(
            r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', page)):
        try:
            js = requests.get(src, headers=UA, timeout=TIMEOUT).text
        except requests.RequestException:
            continue
        m = re.search(r'client_id\s*[:=]\s*"([a-zA-Z0-9]{32})"', js)
        if m:
            return m.group(1)
    return None


def _sc_doczytaj(ids: list[int], client_id: str) -> dict[int, dict]:
    """Pełne dane utworów po id (api-v2, po 50 naraz)."""
    out: dict[int, dict] = {}
    for i in range(0, len(ids), 50):
        part = ids[i:i + 50]
        r = requests.get("https://api-v2.soundcloud.com/tracks",
                         params={"ids": ",".join(map(str, part)), "client_id": client_id},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        for t in r.json() or []:
            if isinstance(t, dict) and t.get("id") is not None:
                out[t["id"]] = t
    return out


def from_soundcloud(url: str) -> list[Track]:
    """Tracks from a public soundcloud.com playlist (set) or single track page.

    Reads window.__sc_hydration. Playlist hydration embeds full metadata only
    for the first few tracks (the rest are id-only stubs) — dawniej reszta
    znikała bez słowa (5 z 335). Teraz doczytujemy je po id tak jak strona
    (api-v2 z publicznym client_id), a gdy się nie da — uwaga „X z Y".
    Likes pages carry no embedded list at all.
    """
    page = _fetch(url)
    hyd = _json_after(page, "window.__sc_hydration")
    if hyd is None:
        raise ImportError(
            "nie znaleziono danych __sc_hydration na stronie SoundCloud — "
            "sprawdź, czy link prowadzi do publicznej playlisty lub utworu"
        )

    def to_track(t: dict) -> Track | None:
        title = t.get("title") or ""
        if not title:
            return None
        artist, title = _sc_artist_title(
            title, (t.get("publisher_metadata") or {}).get("artist") or "",
            (t.get("user") or {}).get("username", ""))
        dur_ms = t.get("full_duration") or t.get("duration")
        return Track(
            id=_synth_id("sc", artist, title),
            artist=artist,
            title=title,
            duration_s=float(dur_ms) / 1000 if dur_ms else None,
        )

    tracks = Lista()
    found_kind = False
    for h in hyd if isinstance(hyd, list) else []:
        kind, data = h.get("hydratable"), h.get("data") or {}
        if kind == "playlist":
            found_kind = True
            pozycje = [t for t in (data.get("tracks") or []) if isinstance(t, dict)]
            total = data.get("track_count") or len(pozycje)
            tracks.zrodlo_total = total
            brakujace = [t["id"] for t in pozycje if not t.get("title") and t.get("id")]
            pelne: dict = {}
            if brakujace:
                try:
                    cid = _sc_client_id(page)
                    if cid:
                        pelne = _sc_doczytaj(brakujace, cid)
                except (requests.RequestException, ValueError):
                    pelne = {}
            for t in pozycje:
                tr = to_track(t if t.get("title") else pelne.get(t.get("id"), {}))
                if tr:
                    tracks.append(tr)
            if total and len(tracks) < total:
                tracks.uwagi.append(
                    f"SoundCloud oddał {len(tracks)} z {total} utworów tej playlisty "
                    "(reszta niedostępna albo nie dała się doczytać) — brakujące "
                    "wklej jako tekst.")
        elif kind == "sound":
            found_kind = True
            tr = to_track(data)
            if tr:
                tracks.append(tr)
    if not tracks:
        if found_kind:
            raise ImportError("playlista SoundCloud nie zawiera osadzonych utworów")
        raise ImportError(
            "ta strona SoundCloud nie osadza listy utworów (polubienia i strefy "
            "odkrywania są ładowane dynamicznie przez JavaScript) — otwórz stronę "
            "w przeglądarce i wklej listę jako tekst"
        )
    out = Lista(_dedupe(tracks), tracks.uwagi, tracks.zrodlo_total)
    return out


_TIDAL_RE = re.compile(
    r"(?:tidal\.com/(?:browse/)?|embed\.tidal\.com/)"
    r"(playlist|album|track|mix)s?/([A-Za-z0-9-]+)", re.I)
TIDAL_EMBED_LIMIT = 50
_LI_RE = re.compile(r'<list-item[^>]*product-type="track"[^>]*>(.*?)</list-item>', re.S)


def _bez_tagow(fragment: str) -> list[str]:
    """Teksty kolejnych elementów (np. linków wykonawców) w kawałku HTML."""
    out = []
    for m in re.finditer(r">([^<>]+)<", fragment):
        t = htmllib.unescape(m.group(1)).strip()
        if t:
            out.append(t)
    return out


def _tidal_embed(kind: str, ident: str) -> list[Track]:
    """Lista z publicznego odtwarzacza do osadzania (embed.tidal.com).

    Strona tidal.com to sama powłoka JavaScript, ale odtwarzacz, który Tidal
    daje do wklejania na strony, ma listę utworów w HTML (tytuł, wykonawcy,
    czas). Pokazuje najwyżej 50 pozycji — wtedy liczbę wszystkich bierzemy
    z opisu strony („155 items") i mówimy uczciwie, ile zaimportowano.
    """
    page = _fetch(f"https://embed.tidal.com/{kind}s/{ident}")
    out = Lista()
    for blok in _LI_RE.findall(page):
        tyt = re.search(r'slot="title"[^>]*>(.*?)</span>', blok, re.S)
        art = re.search(r'slot="artist"[^>]*>(.*?)</span>', blok, re.S)
        dur = re.search(r'slot="duration"[^>]*>([^<]+)<', blok)
        title = " ".join(_bez_tagow(">" + tyt.group(1) + "<")) if tyt else ""
        artists = _bez_tagow(">" + art.group(1) + "<") if art else []
        if title:
            artist = ", ".join(artists)
            out.append(Track(id=_synth_id("tidal", artist, title), artist=artist,
                             title=title, duration_s=_clock_s(dur.group(1)) if dur else None,
                             artists=artists))
    if not out and kind == "track":
        tyt = re.search(r'class="media-title"[^>]*>([^<]+)<', page)
        art = re.search(r'class="media-artist"[^>]*>(.*?)</span>', page, re.S)
        if tyt:
            artists = _bez_tagow(">" + art.group(1) + "<") if art else []
            title = htmllib.unescape(tyt.group(1)).strip()
            out.append(Track(id=_synth_id("tidal", ", ".join(artists), title),
                             artist=", ".join(artists), title=title, artists=artists))
    if len(out) >= TIDAL_EMBED_LIMIT:
        try:
            opis = _fetch(f"https://tidal.com/{kind}/{ident}")
            m = re.search(r'content="[^"]*?(\d+)\s+(?:items|tracks)"', opis)
            total = int(m.group(1)) if m else None
        except ImportError:
            total = None
        if total and total > len(out):
            out.zrodlo_total = total
            out.uwagi.append(
                f"Tidal bez logowania pokazuje tylko {len(out)} pierwszych utworów — "
                f"zaimportowano {len(out)} z {total}. Resztę wklej jako tekst.")
    return out


def from_tidal(url: str) -> list[Track]:
    """Tracks from a tidal.com / listen.tidal.com playlist, album or track.

    Główna droga: publiczny odtwarzacz embed.tidal.com (lista w HTML).
    Awaryjnie: dane osadzone w stronie (ld+json / __NEXT_DATA__), gdyby
    Tidal kiedyś zaczął je renderować po stronie serwera.
    """
    m = _TIDAL_RE.search(url)
    if m:
        try:
            got = _tidal_embed(m.group(1).lower(), m.group(2))
        except ImportError:
            got = []
        if got:
            return got
    page = _fetch(url)
    tracks: list[Track] = []
    for m in _LDJSON_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if data.get("@type") not in ("MusicPlaylist", "MusicAlbum"):
            continue
        for entry in data.get("track") or data.get("tracks") or []:
            title = entry.get("name", "")
            by = entry.get("byArtist")
            artist = (by or {}).get("name", "") if isinstance(by, dict) else ""
            if title:
                tracks.append(
                    Track(
                        id=_synth_id("tidal", artist, title),
                        artist=artist,
                        title=title,
                        duration_s=_iso_duration_s(entry.get("duration")),
                    )
                )
    if not tracks:
        data = _json_after(page, "__NEXT_DATA__\" type=\"application/json\">")
        if data is not None:
            def visit(d: dict) -> None:
                if isinstance(d.get("title"), str) and isinstance(d.get("artists"), list):
                    names = [a.get("name", "") for a in d["artists"] if isinstance(a, dict)]
                    dur = d.get("duration")
                    tracks.append(
                        Track(
                            id=_synth_id("tidal", ", ".join(names), d["title"]),
                            artist=", ".join(n for n in names if n),
                            title=d["title"],
                            duration_s=float(dur) if isinstance(dur, (int, float)) else None,
                        )
                    )
            _walk(data, visit)
    if not tracks:
        raise ImportError(
            "Tidal nie oddał listy utworów dla tego linku (prywatna playlista "
            "albo nieobsługiwany rodzaj strony) — otwórz ją w przeglądarce "
            "i wklej tracklistę jako tekst"
        )
    return _dedupe(tracks)


# --- dispatcher -------------------------------------------------------------

_HTTP_URL_RE = re.compile(r"https?://\S+")
_KNOWN_HOSTS = (
    "open.spotify.com",
    "music.apple.com",
    "tidal.com",
    "youtube.com",
    "youtu.be",
    "1001tracklists.com",
    "soundcloud.com",
)


def resolve_any(text: str) -> tuple[list[Track], str]:
    """Resolve pasted text into (tracks, source name).

    Recognizes Spotify / Apple Music / Tidal / YouTube / 1001tracklists /
    SoundCloud URLs; anything without a URL is parsed as a plain-text tracklist.
    Raises ImportError (Polish message) when the source yields nothing usable.
    """
    stripped = text.strip()
    if re.search(r"\bspotify:(?:track|playlist|album):[A-Za-z0-9]+", stripped):
        # „Kopiuj URI" z aplikacji Spotify — nie ma w tym http://
        return spotify_resolve(stripped), "spotify"
    urls = _HTTP_URL_RE.findall(stripped)
    if not urls and "\n" not in stripped and "/" in stripped:
        # bare "music.apple.com/..." pasted without a scheme
        if any(h in stripped.lower() for h in _KNOWN_HOSTS):
            urls = ["https://" + stripped.split()[0]]

    if urls:
        def host(u: str) -> str:
            return (urlparse(u).netloc or "").lower()

        for u in urls:
            h = host(u)
            if "open.spotify.com" in h:
                return spotify_resolve(stripped), "spotify"
            if "music.apple.com" in h:
                return from_apple_music(u), "apple-music"
            if h.endswith("tidal.com"):
                return from_tidal(u), "tidal"
            if "youtube.com" in h or "youtu.be" in h:
                return from_youtube(u), "youtube"
            if "1001tracklists.com" in h:
                return from_1001tracklists(u), "1001tracklists"
            if "soundcloud.com" in h:
                return from_soundcloud(u), "soundcloud"
        raise ImportError(
            f"nieznane źródło: {host(urls[0])} — obsługiwane: Spotify, Apple Music, "
            "Tidal, YouTube, 1001tracklists, SoundCloud, albo wklej tracklistę jako tekst"
        )

    tracks = from_text(stripped)
    if not tracks:
        raise ImportError(
            "nie rozpoznano żadnych utworów w tekście — oczekiwany format: "
            "'Artysta - Tytuł' w osobnych liniach (numeracja i znaczniki czasu dozwolone)"
        )
    return tracks, "tekst"
