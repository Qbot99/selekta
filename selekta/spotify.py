"""Spotify metadata via public embed pages — no API key required.

For production/App Store distribution switch to the official Web API
(this module keeps the same Track interface, so only the fetch layer changes).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
# /intl-xx/ to prefiks lokalizacyjny z paska adresu przeglądarki (np. intl-pl)
_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[A-Za-z-]+/)?(?:embed/)?(track|playlist|album)/([A-Za-z0-9]+)"
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


@dataclass
class Track:
    id: str
    artist: str
    title: str
    duration_s: float | None = None
    cover_url: str = ""
    preview_url: str = ""
    artists: list[str] = field(default_factory=list)

    @property
    def query(self) -> str:
        return f"{self.artist} {self.title}"


def parse_input(text: str) -> list[tuple[str, str]]:
    """Extract (kind, id) pairs from any text containing Spotify URLs."""
    seen, out = set(), []
    for kind, sid in _URL_RE.findall(text):
        if sid not in seen:
            seen.add(sid)
            out.append((kind, sid))
    return out


def _entity(kind: str, sid: str) -> dict:
    r = requests.get(f"https://open.spotify.com/embed/{kind}/{sid}", headers=UA, timeout=20)
    r.raise_for_status()
    m = _NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"brak danych embed dla {kind}/{sid}")
    data = json.loads(m.group(1))
    entity = (data.get("props", {}).get("pageProps", {})
              .get("state", {}).get("data", {}).get("entity"))
    if not isinstance(entity, dict):
        raise RuntimeError(f"nierozpoznany utwór {kind}/{sid} (usunięty albo błędny link)")
    return entity


def _best_image(entity: dict) -> str:
    imgs = (entity.get("visualIdentity") or {}).get("image") or []
    if not imgs:
        return ""
    url = max(imgs, key=lambda i: i.get("maxWidth", 0))["url"]
    # upgrade to the 640px CDN variant when possible
    m = re.search(r"image/ab67616d00001e02([a-f0-9]+)", url)
    return f"https://i.scdn.co/image/ab67616d0000b273{m.group(1)}" if m else url


def track(sid: str) -> Track:
    e = _entity("track", sid)
    names = [a["name"] for a in e.get("artists", [])]
    return Track(
        id=sid,
        artist=", ".join(names),
        title=e.get("name", ""),
        duration_s=(e.get("duration") or 0) / 1000 or None,
        cover_url=_best_image(e),
        preview_url=(e.get("audioPreview") or {}).get("url", ""),
        artists=names,
    )


def playlist_tracks(sid: str, kind: str = "playlist") -> list[Track]:
    """Track list from a playlist/album embed (embed caps very long playlists).

    ``kind`` musi zgadzać się z linkiem: album pytany przez endpoint playlist
    („playlist" if True else „album" — pozostałość z debugowania) zwracał
    pustkę, którą resolve() po cichu połykał — link do albumu dawał 0 utworów.
    """
    e = _entity(kind, sid)
    out = []
    for t in e.get("trackList", []):
        tid = t["uri"].rsplit(":", 1)[-1]
        out.append(
            Track(
                id=tid,
                artist=t.get("subtitle", ""),
                title=t.get("title", ""),
                duration_s=(t.get("duration") or 0) / 1000 or None,
                preview_url=(t.get("audioPreview") or {}).get("url", ""),
                artists=[a.strip() for a in t.get("subtitle", "").split(",")],
            )
        )
    return out


def resolve(text: str) -> list[Track]:
    """Turn pasted text (track links and/or playlist links) into Tracks.

    A single dead link is skipped, not fatal — a 50-track paste survives
    one removed track.
    """
    tracks: list[Track] = []
    for kind, sid in parse_input(text):
        try:
            if kind == "track":
                tracks.append(track(sid))
            else:
                tracks.extend(playlist_tracks(sid, kind))
        except Exception:  # noqa: BLE001 — skip this item, keep the rest
            continue
    return tracks


def cover_bytes(t: Track) -> bytes | None:
    """Okładka jest best-effort: każdy błąd (syntetyczne id z tracklisty
    tekstowej, martwy link, brak sieci) daje None, nigdy wyjątek."""
    try:
        if not t.cover_url:  # playlist items carry no cover — fetch the track embed
            t.cover_url = track(t.id).cover_url
        if not t.cover_url:
            return None
        r = requests.get(t.cover_url, headers=UA, timeout=20)
        if r.ok and r.content[:3] == b"\xff\xd8\xff":
            return r.content
    except Exception:  # noqa: BLE001
        pass
    return None
