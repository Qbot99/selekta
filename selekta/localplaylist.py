"""Playlisty z dysku: M3U/M3U8, XML rekordboxa, NML Traktora, CSV, tekst.

DJ ma zwykle playlisty już na komputerze — wyeksportowane z rekordboxa,
Traktora, Serato albo zwykłe M3U. Ten moduł zamienia je na listę utworów
i, jeśli plik playlisty wskazuje na konkretne pliki audio, od razu podaje
ich ścieżki. Wtedy nie trzeba niczego zgadywać ani dociągać — utwór jest
już u użytkownika i można przejść prosto do analizy.
"""
from __future__ import annotations

import csv
import io
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from selekta.importers import split_artist_title
from selekta.matcher import AUDIO_EXT

PLAYLIST_EXT = (".m3u", ".m3u8", ".xml", ".nml", ".csv", ".txt", ".pls")


@dataclass
class Entry:
    """Jeden wiersz playlisty. `path` jest wypełniony tylko wtedy,
    gdy plik naprawdę leży na dysku pod wskazaną ścieżką."""
    artist: str = ""
    title: str = ""
    duration_s: float | None = None
    path: str | None = None


@dataclass
class Parsed:
    entries: list[Entry] = field(default_factory=list)
    kind: str = ""
    name: str = ""

    @property
    def found(self) -> list[Entry]:
        return [e for e in self.entries if e.path]


def _url_to_path(value: str) -> str:
    """'file://localhost/Users/a%20b.flac' → '/Users/a b.flac'."""
    if value.startswith("file:"):
        parsed = urllib.parse.urlparse(value)
        return urllib.parse.unquote(parsed.path)
    return urllib.parse.unquote(value)


def _traktor_paths(location: ET.Element) -> list[str]:
    """Traktor zapisuje ścieżki jako '/:Users/:dj/:Muzyka/:'.

    VOLUME bywa nazwą dysku systemowego („Macintosh HD"), a bywa nazwą
    pendrive'a. Zamiast zgadywać, który to przypadek, zwracamy obie
    możliwości — wygra ta, pod którą naprawdę leży plik.
    """
    directory = (location.get("DIR") or "").replace("/:", "/")
    name = location.get("FILE") or ""
    volume = (location.get("VOLUME") or "").strip()
    goly = os.path.join(directory, name)
    kandydaci = [goly]
    if volume and not volume.endswith(":"):
        kandydaci.append(os.path.join("/Volumes", volume, goly.lstrip("/")))
    return kandydaci


def _resolve(raw: str, base_dir: str) -> str | None:
    """Ścieżka z playlisty → istniejący plik audio albo None."""
    if not raw:
        return None
    p = _url_to_path(raw.strip())
    if not os.path.isabs(p):
        p = os.path.join(base_dir, p)
    p = os.path.abspath(p)
    if os.path.isfile(p) and p.lower().endswith(AUDIO_EXT):
        return p
    return None


def _from_m3u(text: str, base_dir: str) -> list[Entry]:
    out: list[Entry] = []
    pending_artist = pending_title = ""
    pending_dur: float | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF:"):
            info = line.split(":", 1)[1]
            secs, _, label = info.partition(",")
            try:
                d = float(secs.split()[0].strip())
                pending_dur = d if d > 0 else None
            except ValueError:
                pending_dur = None
            split = split_artist_title(label.strip())
            if split:
                pending_artist, pending_title = split
            else:
                pending_artist, pending_title = "", label.strip()
            continue
        if line.startswith("#"):
            continue
        path = _resolve(line, base_dir)
        artist, title = pending_artist, pending_title
        if not title:
            stem = os.path.splitext(os.path.basename(_url_to_path(line)))[0]
            split = split_artist_title(stem)
            artist, title = split if split else ("", stem)
        out.append(Entry(artist, title, pending_dur, path))
        pending_artist = pending_title = ""
        pending_dur = None
    return out


def _from_pls(text: str, base_dir: str) -> list[Entry]:
    files: dict[int, str] = {}
    titles: dict[int, str] = {}
    lengths: dict[int, float] = {}
    for line in text.splitlines():
        m = re.match(r"(File|Title|Length)(\d+)\s*=\s*(.*)", line.strip(), re.I)
        if not m:
            continue
        key, idx, val = m.group(1).lower(), int(m.group(2)), m.group(3).strip()
        if key == "file":
            files[idx] = val
        elif key == "title":
            titles[idx] = val
        else:
            try:
                lengths[idx] = float(val)
            except ValueError:
                pass
    out = []
    for i in sorted(set(files) | set(titles)):
        label = titles.get(i, "")
        split = split_artist_title(label)
        artist, title = split if split else ("", label)
        dur = lengths.get(i)
        out.append(Entry(artist, title, dur if dur and dur > 0 else None,
                         _resolve(files.get(i, ""), base_dir)))
    return out


class WyborPlaylisty(Exception):
    """XML rekordboxa ma kilka playlist — trzeba wskazać, którą wziąć.

    Typowy eksport „Export Collection in xml format" to CAŁA kolekcja plus
    drzewo playlist; dawniej wciągaliśmy całą kolekcję jako jedną playlistę
    w kolejności kolekcji, a węzeł PLAYLISTS był ignorowany.
    """

    def __init__(self, playlisty: list[dict]):
        super().__init__("wybierz playlistę z pliku rekordboxa")
        self.playlisty = playlisty


def _rb_entry(t: ET.Element, base_dir: str) -> Entry:
    total = t.get("TotalTime")
    try:
        dur = float(total) if total else None
    except ValueError:
        dur = None
    return Entry(t.get("Artist", "") or "", t.get("Name", "") or "",
                 dur, _resolve(t.get("Location") or "", base_dir))


def _rb_playlists(root: ET.Element) -> list[tuple[str, list[ET.Element]]]:
    """(ścieżka „Folder / Nazwa", wpisy TRACK) dla każdej playlisty."""
    out = []
    pl = root.find("PLAYLISTS")
    if pl is None:
        return out

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node.findall("NODE"):
            name = child.get("Name") or ""
            sciezka = f"{prefix} / {name}" if prefix else name
            if child.get("Type") == "1":
                out.append((sciezka, child.findall("TRACK")))
            else:
                walk(child, sciezka if name and name.upper() != "ROOT" else prefix)

    walk(pl, "")
    return out


def rekordbox_playlists(text: str) -> list[dict]:
    """Playlisty w XML rekordboxa: [{name, count}] (puste pomijamy)."""
    root = ET.fromstring(text)
    return [{"name": n, "count": len(t)} for n, t in _rb_playlists(root) if t]


def _from_rekordbox_xml(text: str, base_dir: str,
                        playlista: str | None = None) -> list[Entry]:
    root = ET.fromstring(text)
    kolekcja: dict[str, ET.Element] = {}
    po_lokacji: dict[str, ET.Element] = {}
    lista = []
    col = root.find("COLLECTION")
    zrodlo = col.iter("TRACK") if col is not None else root.iter("TRACK")
    for t in zrodlo:
        loc = t.get("Location")
        if loc is None and t.get("Key") is not None:
            continue                      # wpis playlisty, nie definicja utworu
        lista.append(t)
        if t.get("TrackID"):
            kolekcja[t.get("TrackID")] = t
        if loc:
            po_lokacji[loc] = t

    playlisty = [(n, tr) for n, tr in _rb_playlists(root) if tr]
    if playlista:
        wybrane = [tr for n, tr in playlisty if n == playlista]
        if not wybrane:
            raise ValueError(f"w pliku nie ma playlisty „{playlista}”")
    elif len(playlisty) == 1:
        wybrane = [playlisty[0][1]]           # eksport jednej playlisty
    elif len(playlisty) > 1:
        raise WyborPlaylisty([{"name": n, "count": len(tr)} for n, tr in playlisty])
    else:
        wybrane = []
    if not wybrane:
        return [_rb_entry(t, base_dir) for t in lista]   # sama kolekcja

    out = []
    for wpis in wybrane[0]:
        key = wpis.get("Key") or ""
        t = po_lokacji.get(key) if wpis.get("KeyType") == "1" else kolekcja.get(key)
        if t is not None:
            out.append(_rb_entry(t, base_dir))
    return out


def _from_traktor_nml(text: str, base_dir: str) -> list[Entry]:
    root = ET.fromstring(text)
    out = []
    for e in root.iter("ENTRY"):
        loc = e.find("LOCATION")
        path = None
        if loc is not None:
            for kandydat in _traktor_paths(loc):
                path = _resolve(kandydat, base_dir)
                if path:
                    break
        info = e.find("INFO")
        dur = None
        if info is not None and info.get("PLAYTIME"):
            try:
                dur = float(info.get("PLAYTIME"))
            except ValueError:
                dur = None
        out.append(Entry(e.get("ARTIST", "") or "", e.get("TITLE", "") or "", dur, path))
    return out


_ARTIST_COLS = ("artist", "artysta", "author", "wykonawca", "artist name")
_TITLE_COLS = ("title", "name", "tytuł", "tytul", "track", "track name", "song",
               "track title")             # eksport .txt z rekordboxa
_TIME_COLS = ("time", "duration", "length", "czas", "total time")


def _from_csv(text: str) -> list[Entry]:
    """CSV/TSV z eksportu Serato, rekordboxa albo arkusza."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]
    def find(names):
        for i, h in enumerate(header):
            if h in names:
                return i
        return None
    ai, ti, di = find(_ARTIST_COLS), find(_TITLE_COLS), find(_TIME_COLS)
    if ti is None:
        # bez nagłówka — potraktuj jak listę wierszy "Artysta - Tytuł"
        out = []
        for r in rows:
            split = split_artist_title(" ".join(c for c in r if c.strip())[:200])
            if split:
                out.append(Entry(split[0], split[1]))
        return out

    out = []
    for r in rows[1:]:
        def cell(i):
            return r[i].strip() if i is not None and i < len(r) else ""
        title = cell(ti)
        if not title:
            continue
        out.append(Entry(cell(ai), title, _clock(cell(di))))
    return out


def _clock(value: str) -> float | None:
    """'3:45' albo '225' → sekundy."""
    value = (value or "").strip()
    if not value:
        return None
    if ":" in value:
        parts = value.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        secs = 0.0
        for n in nums:
            secs = secs * 60 + n
        return secs or None
    try:
        return float(value) or None
    except ValueError:
        return None


def decode(raw: bytes) -> str:
    """Bajty pliku playlisty → tekst.

    rekordbox zapisuje eksport .txt w UTF-16 (z BOM) — dekodowanie jako
    UTF-8 dawało krzaki i „nie znalazłem utworów". Obsługujemy BOM-y UTF-8,
    UTF-16 LE/BE i UTF-16 bez BOM (dużo bajtów zerowych).
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    probka = raw[:2000]
    if probka and probka.count(b"\x00") > len(probka) // 4:
        parzyste = probka[0::2].count(b"\x00")
        return raw.decode("utf-16-be" if parzyste > len(probka) // 4 else "utf-16-le",
                          errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1250", errors="replace")


def _wyglada_na_tabele(text: str) -> bool:
    """Czy pierwszy wiersz to nagłówek kolumn (rekordbox .txt, arkusz)."""
    pierwsza = text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""
    if "\t" not in pierwsza and "," not in pierwsza and ";" not in pierwsza:
        return False
    kolumny = {c.strip().strip('"').lower() for c in re.split(r"[\t,;|]", pierwsza)}
    return bool(kolumny & set(_TITLE_COLS)) and bool(kolumny & set(_ARTIST_COLS))


def parse_text(text: str, kind: str, base_dir: str = "",
               playlista: str | None = None) -> list[Entry]:
    """Rozbierz zawartość playlisty znanego typu."""
    kind = kind.lower().lstrip(".")
    text = text.lstrip("\ufeff")
    if kind in ("m3u", "m3u8"):
        return _from_m3u(text, base_dir)
    if kind == "pls":
        return _from_pls(text, base_dir)
    if kind == "xml":
        return _from_rekordbox_xml(text, base_dir, playlista)
    if kind == "nml":
        return _from_traktor_nml(text, base_dir)
    if kind == "csv" or (kind == "txt" and _wyglada_na_tabele(text)):
        # eksport playlisty z rekordboxa to .txt z tabulatorami i nagłówkiem
        # „#  Artwork  Track Title  Artist …" — dawniej szedł do parsera
        # „Artysta - Tytuł" i kończył się 400
        return _from_csv(text)
    from selekta.importers import from_text
    return [Entry(t.artist, t.title, t.duration_s) for t in from_text(text)]


def sniff(text: str, filename: str = "") -> str:
    """Rozpoznaj typ playlisty po nazwie, a jak się nie da — po treści."""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ("m3u", "m3u8", "pls", "xml", "nml", "csv", "txt"):
        return ext
    head = text.lstrip()[:400].lower()
    if head.startswith("#extm3u") or "#extinf:" in head:
        return "m3u"
    if head.startswith("[playlist]"):
        return "pls"
    if "<nml" in head or "<traktor" in head:
        return "nml"
    if head.startswith("<?xml") or "<dj_playlists" in head:
        return "xml"
    if "\t" in head or head.count(",") >= 2:
        return "csv"
    return "txt"


def from_file(path: str, playlista: str | None = None) -> Parsed:
    """Wczytaj playlistę z pliku na dysku."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = decode(raw)
    kind = sniff(text, path)
    entries = parse_text(text, kind, base_dir=os.path.dirname(os.path.abspath(path)),
                         playlista=playlista)
    return Parsed(entries, kind, os.path.splitext(os.path.basename(path))[0])


def from_folder(folder: str) -> Parsed:
    """Potraktuj folder z muzyką jak playlistę (pliki po kolei, alfabetycznie)."""
    from selekta.matcher import audio_files
    entries = []
    for p in audio_files(folder):
        stem = os.path.splitext(os.path.basename(p))[0]
        split = split_artist_title(stem)
        artist, title = split if split else ("", stem)
        entries.append(Entry(artist, title, None, p))
    return Parsed(entries, "folder", os.path.basename(os.path.normpath(folder)))
