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

from .spotify import Track, resolve as spotify_resolve

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

# "(Official Music Video)" / "[Official Audio]" style noise in YouTube titles
_YT_NOISE_RE = re.compile(
    r"\s*[\(\[](?:official\s*)?(?:music\s*|lyric\s*|lyrics\s*)?"
    r"(?:videos?|audio|visuali[sz]er|hd|4k|m/v)[\)\]]",
    re.I,
)


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
    if len(parts) < 2:
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
    """Parse pasted plain-text tracklist lines into Tracks (unparseable lines are skipped)."""
    tracks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pair = split_artist_title(line)
        if not pair:
            continue
        artist, title = pair
        tracks.append(Track(id=_synth_id("text", artist, title), artist=artist, title=title))
    return _dedupe(tracks)


def from_apple_music(url: str) -> list[Track]:
    """Tracks from a public music.apple.com playlist/album page.

    Primary source: the `serialized-server-data` JSON (has artist + duration + id);
    fallback: the schema.org MusicPlaylist ld+json (titles + durations only).
    """
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


def from_youtube(url: str) -> list[Track]:
    """Tracks from a public youtube.com / music.youtube.com playlist.

    Parses `ytInitialData` (both the current lockupViewModel layout and the older
    playlistVideoRenderer one). Video titles like "Artist - Title (Extended Mix)"
    are split with split_artist_title; otherwise the channel name becomes the artist.
    """
    parsed = urlparse(url)
    playlist_id = (parse_qs(parsed.query).get("list") or [None])[0]
    if playlist_id:
        # canonical desktop page; music.youtube.com is a pure JS shell
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
    elif "music.youtube.com" in (parsed.netloc or ""):
        raise ImportError("link YouTube nie zawiera playlisty (brak parametru list=)")

    # EU consent cookies, otherwise the request bounces to consent.youtube.com
    page = _fetch(url, {"Cookie": "SOCS=CAI; CONSENT=YES+cb.20210328-17-p0.en+FX+419"})
    data = _json_after(page, "ytInitialData")
    if data is None:
        raise ImportError(
            "nie znaleziono danych ytInitialData na stronie YouTube — "
            "sprawdź, czy playlista jest publiczna"
        )

    raw: list[tuple[str, str, float | None]] = []  # (video title, channel, duration_s)

    def visit(d: dict) -> None:
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

    tracks = []
    for title, channel, dur in raw:
        clean = re.sub(r"\s{2,}", " ", _YT_NOISE_RE.sub("", title)).strip()
        pair = split_artist_title(clean)
        if pair:
            artist, name = pair
        else:
            artist = re.sub(r"\s*-\s*Topic$", "", channel).strip()
            name = clean.strip()
        if not name:
            continue
        tracks.append(
            Track(
                id=_synth_id("yt", artist, name),
                artist=artist,
                title=name,
                duration_s=dur,
            )
        )
    if not tracks:
        raise ImportError(
            "playlista YouTube nie zawiera pozycji (prywatna, usunięta lub pusta?)"
        )
    return _dedupe(tracks)


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


def from_soundcloud(url: str) -> list[Track]:
    """Tracks from a public soundcloud.com playlist (set) or single track page.

    Reads window.__sc_hydration. Caveat: playlist hydration embeds full metadata
    only for the first few tracks (the rest are lazy id-only stubs, loaded by JS),
    so long sets come back truncated. Likes pages carry no embedded list at all.
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
        artist = (t.get("publisher_metadata") or {}).get("artist") or ""
        if not artist:
            pair = split_artist_title(title)
            if pair:
                artist, title = pair
            else:
                artist = (t.get("user") or {}).get("username", "")
        dur_ms = t.get("full_duration") or t.get("duration")
        return Track(
            id=_synth_id("sc", artist, title),
            artist=artist,
            title=title,
            duration_s=float(dur_ms) / 1000 if dur_ms else None,
        )

    tracks: list[Track] = []
    found_kind = False
    for h in hyd if isinstance(hyd, list) else []:
        kind, data = h.get("hydratable"), h.get("data") or {}
        if kind == "playlist":
            found_kind = True
            for t in data.get("tracks") or []:
                tr = to_track(t)
                if tr:
                    tracks.append(tr)
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
    return _dedupe(tracks)


def from_tidal(url: str) -> list[Track]:
    """Tracks from a tidal.com / listen.tidal.com playlist — when the page embeds any.

    tidal.com is currently a JavaScript shell (no server-rendered tracklist), so in
    practice this raises ImportError; the embedded-JSON paths are kept in case Tidal
    starts server-rendering again.
    """
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
            "Tidal renderuje playlisty w przeglądarce (JavaScript) i nie osadza "
            "listy utworów w HTML — otwórz playlistę w przeglądarce i wklej "
            "tracklistę jako tekst"
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
