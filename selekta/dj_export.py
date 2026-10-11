"""Export a track list to DJ software: rekordbox XML, M3U8, Serato crate.

Works on plain track dicts so every writer shares one input shape:

    {"path": str, "artist": str, "title": str, "duration_s": float,
     "bpm": float | None, "key": str | None}   # bpm/key optional

`collect(folder)` builds that list from an audio folder, preferring
mutagen tags (TITLE/ARTIST or TIT2/TPE1) and falling back to the
"Artist - Title" filename convention used across the library.

Formats
-------
rekordbox: DJ_PLAYLISTS 1.0.0 XML (File > Import Collection) — a
COLLECTION of TRACK entries plus a PLAYLISTS/NODE tree whose playlist
references tracks by TrackID, preserving input order.

M3U8: extended M3U, UTF-8, absolute paths.

Serato: binary .crate — big-endian chunks '<4s tag><uint32 len><payload>'
with UTF-16-BE strings. Header chunk 'vrsn' ("1.0/Serato ScratchLive
Crate"); one 'otrk' per track wrapping a 'ptrk' whose payload is the
track path relative to its volume root, without a leading slash.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote

from mutagen import File as MutagenFile
from mutagen.id3 import ID3

from .matcher import AUDIO_EXT
from .tagger import FORBIDDEN

CRATE_VERSION = "1.0/Serato ScratchLive Crate"

KIND = {
    ".mp3": "MP3 File",
    ".flac": "FLAC File",
    ".wav": "WAV File",
    ".aiff": "AIFF File",
    ".aif": "AIFF File",
    ".m4a": "M4A File",
    ".ogg": "OGG File",
}


# --------------------------------------------------------------------------- #
# building track dicts from a folder
# --------------------------------------------------------------------------- #

def _tag_text(audio, id3_frames: tuple[str, ...], vorbis_names: tuple[str, ...]) -> str | None:
    """First non-empty value among ID3 frames / Vorbis comment names."""
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None
    if isinstance(tags, ID3):
        for name in id3_frames:
            frame = tags.get(name)
            if frame is not None and getattr(frame, "text", None):
                val = str(frame.text[0]).strip()
                if val:
                    return val
        return None
    for name in vorbis_names:  # VCommentDict lookups are case-insensitive
        try:
            val = tags.get(name)
        except Exception:
            val = None
        if val:
            val = str(val[0] if isinstance(val, list) else val).strip()
            if val:
                return val
    return None


def _float_or_none(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        val = float(str(raw).replace(",", "."))
    except ValueError:
        return None
    return val if val > 0 else None


def _czas_lub_none(raw) -> float | None:
    """Czas w sekundach. W odróżnieniu od BPM, ZERO jest poprawne —
    utwór może zaczynać się dokładnie na uderzeniu."""
    if raw is None:
        return None
    try:
        val = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None


def track_from_file(path: str) -> dict:
    """One track dict for `path`; tags first, filename parse as fallback."""
    path = os.path.abspath(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    fn_artist, sep, fn_title = stem.partition(" - ")
    track = {
        "path": path,
        "artist": fn_artist.strip() if sep else "",
        "title": fn_title.strip() if sep else stem,
        "duration_s": 0.0,
        "bpm": None,
        "key": None,
    }
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    if audio is None:
        return track
    length = getattr(audio.info, "length", None)
    if length:
        track["duration_s"] = float(length)
    title = _tag_text(audio, ("TIT2",), ("TITLE",))
    artist = _tag_text(audio, ("TPE1",), ("ARTIST",))
    if title:
        track["title"] = title
    if artist:
        track["artist"] = artist
    track["bpm"] = _float_or_none(_tag_text(audio, ("TBPM",), ("BPM", "TEMPO")))
    # Tonacja z tagu tylko po przetłumaczeniu na Camelot — w plikach siedzą
    # „F", „C Minor", „10m" (Open Key) i zakodowany JSON Mixed In Key.
    for surowa in _tag_values(audio, ("TKEY", "TXXX:INITIALKEY", "TXXX:KEY"),
                              ("INITIALKEY", "KEY", "INITIAL_KEY")):
        cam = tonacja_camelot(surowa)
        if cam:
            track["key"] = cam
            break
    _fill_from_cache(path, track)
    return track


def _tag_values(audio, id3_frames: tuple[str, ...], vorbis_names: tuple[str, ...]):
    """Wszystkie niepuste wartości z podanych pól, w kolejności ważności."""
    tags = getattr(audio, "tags", None)
    if tags is None:
        return
    if isinstance(tags, ID3):
        for name in id3_frames:
            frame = tags.get(name)
            for val in (getattr(frame, "text", None) or []):
                if str(val).strip():
                    yield str(val).strip()
        return
    for name in vorbis_names:
        try:
            val = tags.get(name)
        except Exception:  # noqa: BLE001
            val = None
        for v in (val if isinstance(val, list) else [val] if val else []):
            if str(v).strip():
                yield str(v).strip()


def _fill_from_cache(path: str, track: dict) -> None:
    """BPM/tonacja z policzonej analizy selekty.

    BPM — tylko gdy plik nie ma tagu (to obszar siatki).
    Tonacja — ZAWSZE, gdy analiza istnieje: to ta sama wartość, którą apka
    pokazuje w Bibliotece i z której układa kolejność setu (notatki przejść
    „8A->9A"). Gdyby rekordbox dostał tag z pliku, DJ widziałby w nim inną
    tonację niż w apce. Tag (po normalizacji) zostaje tylko wtedy, gdy
    analizy jeszcze nie ma.
    """
    try:
        from . import cache

        data = cache.get(path, "harmonic")
    except Exception:  # noqa: BLE001 — brak cache nie może psuć eksportu
        return
    if not data:
        return
    if not track["bpm"] and data.get("bpm"):
        track["bpm"] = float(data["bpm"])
    cam = tonacja_camelot(data.get("camelot"))
    if cam:
        track["key"] = cam


# --------------------------------------------------------------------------- #
# tonacja: jeden zapis w całym eksporcie
# --------------------------------------------------------------------------- #

# Camelot → nuta (krzyżykami, jak harmonic.NOTE_NAMES i tag TKEY z write_tags)
_DUR = {1: "B", 2: "F#", 3: "C#", 4: "G#", 5: "D#", 6: "A#", 7: "F", 8: "C",
        9: "G", 10: "D", 11: "A", 12: "E"}
_MOL = {1: "G#", 2: "D#", 3: "A#", 4: "F", 5: "C", 6: "G", 7: "D", 8: "A",
        9: "E", 10: "B", 11: "F#", 12: "C#"}
_DUR_NR = {v: k for k, v in _DUR.items()}
_MOL_NR = {v: k for k, v in _MOL.items()}
_ENHARMONIA = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
               "CB": "B", "FB": "E", "E#": "F", "B#": "C"}

_RE_CAMELOT = re.compile(r"^0?([1-9]|1[0-2])\s*([AB])$", re.I)
_RE_OPENKEY = re.compile(r"^0?([1-9]|1[0-2])\s*([DM])$", re.I)
_RE_NAZWA = re.compile(
    r"^([A-G])\s*([#♯B♭]?)\s*(M|MIN|MINOR|MOLL|MAJ|MAJOR|DUR)?$", re.I)


def tonacja_camelot(surowa) -> str | None:
    """Dowolny zapis tonacji → kod Camelot („8A"); None dla śmieci.

    Rozumie: Camelot („8A", „08a"), Open Key („10m" = 5A, „1d" = 8B),
    nazwy („Am", „A minor", „C Minor", „F#m", „Bbm", „F", „C major")
    i zakodowany JSON Mixed In Key z pola KEY (base64 '{"key":"8B",...}').
    """
    if surowa is None:
        return None
    tekst = " ".join(str(surowa).strip().split())
    if not tekst or len(tekst) > 400:
        return None
    if tekst.startswith("eyJ"):                       # base64 z '{"' na początku
        try:
            dane = json.loads(base64.b64decode(tekst + "=" * (-len(tekst) % 4)))
        except (ValueError, binascii.Error):
            return None
        return tonacja_camelot(dane.get("key")) if isinstance(dane, dict) else None
    m = _RE_CAMELOT.match(tekst)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    m = _RE_OPENKEY.match(tekst)
    if m:
        nr = (int(m.group(1)) + 6) % 12 + 1
        return f"{nr}{'A' if m.group(2).lower() == 'm' else 'B'}"
    m = _RE_NAZWA.match(tekst)
    if m:
        nuta = m.group(1).upper()
        znak = m.group(2).replace("♯", "#").replace("♭", "b")
        if znak in ("b", "B"):
            nuta = _ENHARMONIA.get(nuta + "B", nuta)
        elif znak == "#":
            nuta = _ENHARMONIA.get(nuta + "#", nuta + "#")
        tryb = (m.group(3) or "").lower()
        mol = tryb in ("m", "min", "minor", "moll")
        nr = (_MOL_NR if mol else _DUR_NR).get(nuta)
        return f"{nr}{'A' if mol else 'B'}" if nr else None
    for czesc in re.split(r"\s*[/|,;]\s*|\s+-\s+", tekst):   # „8A/Am", „Am - 8A"
        if czesc and czesc != tekst:
            cam = tonacja_camelot(czesc)
            if cam:
                return cam
    return None


def tonacja_rekordbox(surowa) -> str | None:
    """Zapis tonacji do atrybutu Tonality: nazwa muzyczna („Am", „F#m", „C").

    Dlaczego nie Camelot: rekordbox sam zapisuje Tonality w notacji
    zależnej od ustawienia „Key display format" (klasyczna „Am"/„C#m" albo
    alfanumeryczna „1A"–„12B"), a nazwa muzyczna to standard tagu TKEY —
    tę samą wartość selekta wpisuje do plików (harmonic.write_tags), więc
    XML i tagi pliku mówią rekordboxowi to samo. Krzyżyki, nie bemole —
    jak w analizie selekty.
    """
    cam = tonacja_camelot(surowa)
    if not cam:
        return None
    nr, litera = int(cam[:-1]), cam[-1]
    return f"{_MOL[nr]}m" if litera == "A" else _DUR[nr]


MANIFEST_SETU = "_selekta.json"     # ten sam plik co playlists.MANIFEST


def _w_folderze_setu(path: str, korzen: str) -> bool:
    """Czy plik leży w folderze setu (katalog z _selekta.json) POD korzeniem.

    Sam korzeń się nie liczy: eksport folderu setu wskazanego wprost
    (``selekta export --folder speeding``) to eksport tego setu.
    """
    katalog = os.path.dirname(os.path.abspath(path))
    korzen = os.path.abspath(korzen)
    while katalog != korzen and katalog.startswith(korzen + os.sep):
        if os.path.isfile(os.path.join(katalog, MANIFEST_SETU)):
            return True
        katalog = os.path.dirname(katalog)
    return False


def pliki_biblioteki(folder: str) -> list[str]:
    """Utwory biblioteki do eksportu — z podfolderami, każdy utwór RAZ.

    Ten sam indeks co reszta apki (``matcher.audio_files``): pobrania z
    Soulseeka lądują w katalogach albumów, więc czytanie samego folderu
    głównego widziało bibliotekę jako pustą („0 plików w głównym, 277 w
    podfolderach").

    Foldery setów (katalog z ``_selekta.json``) trzymają KOPIE utworów
    z biblioteki — kopia nie jest osobnym utworem, więc w eksporcie całej
    biblioteki zostaje oryginał spoza setu. Utwór, który istnieje tylko
    w folderze setu (pobranie prosto do playlisty), zostaje — raz.
    Kopię poznajemy po tej samej nazwie pliku i tym samym rozmiarze
    (tak kopiuje ``playlists.collect``).

    Zależność: obszar „porządki” uczy tego samego ``matcher.audio_files``.
    Ta funkcja jest wtedy po prostu no-opem na już odfiltrowanej liście.
    """
    from .matcher import audio_files

    pliki = audio_files(folder)
    poza, w_setach = [], []
    for p in pliki:
        (w_setach if _w_folderze_setu(p, folder) else poza).append(p)

    def podpis(p: str) -> tuple[str, int]:
        try:
            return (os.path.basename(p).casefold(), os.path.getsize(p))
        except OSError:
            return (os.path.basename(p).casefold(), -1)

    znane = {podpis(p) for p in poza}
    wynik = list(poza)
    for p in w_setach:
        s = podpis(p)
        if s in znane:
            continue
        znane.add(s)
        wynik.append(p)
    return sorted(wynik, key=lambda p: (os.path.basename(p).lower(), p))


def w_kolejnosci_setu(tracks: list[dict]) -> list[dict]:
    """Ułóż utwory harmonicznie (to samo `harmonic.order_set` co ekran
    „Kolejność setu"); utwory bez policzonej analizy idą na koniec."""
    from . import cache, harmonic

    items, reszta = [], []
    for t in tracks:
        try:
            h = cache.get(t["path"], "harmonic")
        except OSError:
            h = None
        if h:
            items.append((t["path"], harmonic.TrackAnalysis(**h)))
        else:
            reszta.append(t)
    po_sciezce = {t["path"]: t for t in tracks}
    return [po_sciezce[p] for p, _ta, _n in harmonic.order_set(items)] + reszta


def collect(folder: str) -> list[dict]:
    """Track dicts for every track of the library (with subfolders, set
    copies counted once — see `pliki_biblioteki`), sorted by file name."""
    return [track_from_file(p) for p in pliki_biblioteki(folder)]


# --------------------------------------------------------------------------- #
# rekordbox XML
# --------------------------------------------------------------------------- #

def _location_url(path: str) -> str:
    """rekordbox-style file URL: file://localhost/<percent-encoded abs path>."""
    return "file://localhost" + quote(os.path.abspath(path), safe="/")


def to_rekordbox_xml(tracks: list[dict], playlist_name: str, out_path: str) -> str:
    """Write a rekordbox DJ_PLAYLISTS 1.0.0 XML with one playlist; return out_path.

    Track order in COLLECTION and in the playlist NODE follows `tracks`.
    AverageBpm/Tonality are emitted only when the dict provides bpm/key.
    """
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="6.0.0", Company="AlphaTheta")

    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks)))
    for i, track in enumerate(tracks, start=1):
        path = track["path"]
        attrs = {
            "TrackID": str(i),
            "Name": str(track.get("title") or ""),
            "Artist": str(track.get("artist") or ""),
            "Kind": KIND.get(os.path.splitext(path)[1].lower(), "Unknown File"),
            "TotalTime": str(int(round(float(track.get("duration_s") or 0)))),
            "Location": _location_url(path),
        }
        if os.path.exists(path):
            attrs["Size"] = str(os.path.getsize(path))
        bpm = _float_or_none(track.get("bpm"))
        if bpm:
            attrs["AverageBpm"] = f"{bpm:.2f}"
        tonacja = tonacja_rekordbox(track.get("key"))
        if tonacja:
            attrs["Tonality"] = tonacja
        # Dane, których apka NIE potrafi wyliczyć — istnieją tylko dlatego,
        # że użytkownik je ustawił. Zawsze przepisujemy je bez zmian.
        for pole, klucz in (("Colour", "kolor"), ("Rating", "ocena"),
                            ("PlayCount", "odtworzen"), ("Comments", "komentarz")):
            wartosc = track.get(klucz)
            if wartosc not in (None, "", 0):
                attrs[pole] = str(wartosc)
        el = ET.SubElement(collection, "TRACK", attrs)

        # Siatka beatów. Bez elementu TEMPO rekordbox analizuje utwór po
        # swojemu i sam ustawia kotwicę — a wtedy nasze wyliczenie pierwszego
        # uderzenia przepada. Inizio to moment pierwszego bitu w sekundach,
        # Battito=1 oznacza „to jest pierwsza miara taktu".
        first_beat = _czas_lub_none(track.get("first_beat_s"))
        if bpm and first_beat is not None:
            try:
                battito = int(track.get("battito") or 1)
            except (TypeError, ValueError):
                battito = 1
            if not 1 <= battito <= 4:
                battito = 1
            ET.SubElement(el, "TEMPO", Inizio=f"{first_beat:.3f}",
                          Bpm=f"{bpm:.2f}", Metro="4/4", Battito=str(battito))

        # Punkty cue. RĘCZNA PRACA WYGRYWA: jeśli utwór wrócił z rekordboxa
        # z własnymi hot cue'ami, oddajemy dokładnie je. Własne wyliczenie
        # intro/drop/outro dokładamy tylko tam, gdzie użytkownik nie postawił
        # nic — nadpisanie cudzego cue widać dopiero na parkiecie.
        reczne = track.get("znaczniki") or []
        if reczne:
            for z in reczne:
                czas = _czas_lub_none(z.get("start_s"))
                if czas is None:
                    continue
                attrs_m = {"Name": str(z.get("nazwa") or ""),
                           "Type": str(z.get("typ") or "0"),
                           "Start": f"{czas:.3f}",
                           "Num": str(z.get("num", -1))}
                koniec = _czas_lub_none(z.get("koniec_s"))
                if koniec is not None:
                    attrs_m["End"] = f"{koniec:.3f}"
                kolor = str(z.get("kolor") or "")
                if kolor.startswith("#") and len(kolor) == 7:
                    attrs_m.update(Red=str(int(kolor[1:3], 16)),
                                   Green=str(int(kolor[3:5], 16)),
                                   Blue=str(int(kolor[5:7], 16)))
                ET.SubElement(el, "POSITION_MARK", attrs_m)
        else:
            for nazwa, sekundy, numer in (
                    ("intro", track.get("intro_end_s"), 0),
                    ("drop", track.get("drop_s"), 1),
                    ("outro", track.get("outro_start_s"), 2)):
                czas = _czas_lub_none(sekundy)
                if czas is None:
                    continue
                ET.SubElement(el, "POSITION_MARK", Name=nazwa, Type="0",
                              Start=f"{czas:.3f}", Num=str(numer))

    playlists = ET.SubElement(root, "PLAYLISTS")
    node_root = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(
        node_root, "NODE",
        Name=playlist_name, Type="1", KeyType="0", Entries=str(len(tracks)),
    )
    for i in range(1, len(tracks) + 1):  # playlist order == input order
        ET.SubElement(node, "TRACK", Key=str(i))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return out_path


# --------------------------------------------------------------------------- #
# M3U8
# --------------------------------------------------------------------------- #

def to_m3u8(tracks: list[dict], out_path: str) -> str:
    """Write an extended M3U8 (UTF-8, absolute paths); return out_path."""
    lines = ["#EXTM3U"]
    for track in tracks:
        seconds = int(round(float(track.get("duration_s") or 0)))
        artist = str(track.get("artist") or "").strip()
        title = str(track.get("title") or "").strip()
        label = f"{artist} - {title}" if artist else title
        lines.append(f"#EXTINF:{seconds},{label}")
        lines.append(os.path.abspath(track["path"]))
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path


# --------------------------------------------------------------------------- #
# Serato crate
# --------------------------------------------------------------------------- #

def _chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack(">I", len(payload)) + payload


def _volume_relative(path: str) -> str:
    """Path relative to its volume root, forward slashes, no leading slash.

    Serato resolves 'ptrk' against the root of the volume that holds the
    _Serato_ folder: '/Volumes/USB/Music/a.mp3' -> 'Music/a.mp3'; files on
    the boot volume keep their full path minus the leading '/'.
    """
    p = os.path.abspath(path)
    if sys.platform == "darwin" and p.startswith("/Volumes/"):
        parts = p.split("/", 3)  # ['', 'Volumes', '<name>', '<rest>']
        return parts[3] if len(parts) > 3 else ""
    return p.replace(os.sep, "/").lstrip("/")


def to_serato_crate(tracks: list[dict], crate_path: str) -> str:
    """Write a Serato .crate for `tracks` at crate_path; return crate_path.

    Layout: 'vrsn' header chunk (UTF-16-BE version string), then one
    'otrk' chunk per track wrapping a 'ptrk' chunk whose payload is the
    volume-relative path in UTF-16-BE. Input order is preserved.
    """
    blob = _chunk(b"vrsn", CRATE_VERSION.encode("utf-16-be"))
    for track in tracks:
        ptrk = _chunk(b"ptrk", _volume_relative(track["path"]).encode("utf-16-be"))
        blob += _chunk(b"otrk", ptrk)
    parent = os.path.dirname(os.path.abspath(crate_path))
    os.makedirs(parent, exist_ok=True)
    with open(crate_path, "wb") as fh:
        fh.write(blob)
    return crate_path


def install_serato_crate(tracks: list[dict], library_root: str,
                         crate_name: str = "selekta") -> str:
    """Write <library_root>/_Serato_/Subcrates/<crate_name>.crate; return its path."""
    safe = FORBIDDEN.sub("", crate_name).strip().rstrip(".") or "crate"
    crate_path = os.path.join(library_root, "_Serato_", "Subcrates", safe + ".crate")
    return to_serato_crate(tracks, crate_path)

def wzbogac_o_siatke(tracks: list[dict], licz_brakujace: bool = True) -> list[dict]:
    """Dołóż do eksportu siatkę beatów i punkty cue.

    Bez tego rekordbox analizuje utwór po swojemu i sam ustawia kotwicę —
    nasze wyliczenie pierwszego uderzenia przepada, a razem z nim intro,
    drop i outro. Dane bierzemy z pamięci podręcznej; liczymy tylko to,
    czego jeszcze nie ma.

    `licz_brakujace=False` — tylko to, co już policzone (eksport CAŁEJ
    biblioteki: liczenie cue to ~40 s na utwór, więc setki niepoliczonych
    utworów zawiesiłyby jedno zapytanie na godziny). Utwór bez analizy
    dostaje wtedy `bez_analizy=True` i rekordbox policzy mu siatkę sam;
    ręczna praca z rekordboxa i tak przechodzi.
    """
    from dataclasses import asdict

    from . import cache, cues, harmonic, rbimport, siatka, waveform

    for t in tracks:
        path = t.get("path")
        if not path or not os.path.isfile(path):
            continue
        h = cache.get(path, "harmonic")
        if h is None and licz_brakujace:
            h = asdict(harmonic.analyze(path)); cache.put(path, "harmonic", h)
        if h is None:
            h = {}
            t["bez_analizy"] = True
        if not t.get("bpm") and h.get("bpm"):
            t["bpm"] = h["bpm"]
        # tonacja: analiza selekty — ta sama, którą pokazuje apka
        if tonacja_camelot(h.get("camelot")):
            t["key"] = tonacja_camelot(h.get("camelot"))
        elif not tonacja_camelot(t.get("key")) and tonacja_camelot(h.get("key")):
            t["key"] = tonacja_camelot(h.get("key"))
        c = cache.get(path, "cues")
        if c is None and licz_brakujace:
            c = asdict(cues.analyze(path, bpm=h.get("bpm")))
            cache.put(path, "cues", c)
        if c is None:
            c = {}
            t["bez_analizy"] = True
        # Kolejność ważności kotwicy: poprawka zrobiona w selekcie (ostatnia
        # świadoma decyzja w tej apce) > to, co przyszło z rekordboxa >
        # nasze wyliczenie.
        rb = rbimport.dla_pliku(path) or {}
        reczna = waveform.wczytaj_siatke(path) or {}
        t["first_beat_s"] = (reczna.get("first_beat_s")
                             or rb.get("first_beat_s")
                             or c.get("first_beat_s"))
        # Jedynka taktu idzie w parze z kotwicą, z którą ją policzono.
        if reczna.get("first_beat_s") is not None:
            t["battito"] = reczna.get("battito") or 1
        elif rb.get("first_beat_s") is not None:
            t["battito"] = rb.get("battito") or 1
        else:
            t["battito"] = c.get("battito") or 1
        # BPM siatki: to, co dostroiło się do stopy w całym utworze, nie tag
        # z pliku. Tag „137.81" przy realnych 138.00 rozjeżdża siatkę o pół
        # bitu do końca utworu, a nikt nie wie, skąd ten tag się wziął.
        if reczna.get("bpm"):
            t["bpm"] = reczna["bpm"]
        elif rb.get("first_beat_s") is not None and rb.get("bpm"):
            t["bpm"] = rb["bpm"]
        elif (c.get("bpm_siatki")
              and (c.get("pewnosc_siatki") or 0) >= siatka.PROG_PEWNOSCI):
            t["bpm"] = c["bpm_siatki"]
        # Ręczna praca z rekordboxa przechodzi dalej nietknięta.
        if rb:
            t["znaczniki"] = rb.get("znaczniki") or []
            for klucz in ("kolor", "ocena", "odtworzen", "komentarz"):
                if rb.get(klucz):
                    t[klucz] = rb[klucz]
        t["intro_end_s"] = c.get("intro_end_s")
        t["drop_s"] = c.get("drop_s")
        t["outro_start_s"] = c.get("outro_start_s")
    return tracks
