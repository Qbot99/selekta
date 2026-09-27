"""Lokalny dashboard selekta — FastAPI + samodzielny frontend (bez npm).

`selekta serve --folder DIR` uruchamia serwer na localhost. Strona
pokazuje bibliotekę z okładkami, jakością, BPM/tonacją i statusem
weryfikacji, pozwala policzyć analizę i zobaczyć kolejność setu.

Endpointy trzymają się zasady: `/api/tracks` jest szybkie (tagi + cache),
a ciężka analiza dzieje się na żądanie w `/api/analyze`.
"""
from __future__ import annotations

import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import time
from dataclasses import asdict

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response
from mutagen import File as MutagenFile

from . import (
    doktor,
    uchem,
    cache, config, covers, cues, decyzje, dedupe, dj_export, harmonic, health,
    instalator, obserwator,
    importers, loudness, matcher, pipeline, quality, siatka, radar, rekordbox,
    dlqueue, folderpick, localplaylist, playlists, slskd_client, slskd_ctl,
    spotify,
    stores, tagfix,
    energia, historia, rbimport, statystyki, tagger, tempo, usb, waveform,
    wishlist,
)
from .slskd_client import SearchHit, SlskdClient
from .slskd_client import primary_artist as slskd_primary

EXPORT_TARGETS = ("rekordbox", "serato", "m3u8")


def _field(payload: dict | None, key: str) -> str:
    """Pole z body: None/null/brak → pusty string (nigdy AttributeError)."""
    val = (payload or {}).get(key)
    return str(val).strip() if val is not None else ""


def _clean(obj):
    """Zamień NaN/Infinity na None — inaczej JSON.parse w przeglądarce pęka."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

app = FastAPI(title="selekta")
_STATE: dict[str, str] = {"folder": "."}

HERE = os.path.dirname(__file__)


def set_folder(folder: str) -> None:
    _STATE["folder"] = os.path.abspath(os.path.expanduser(folder))


def _folder() -> str:
    return _STATE["folder"]


# Foldery, które użytkownik sam wskazał w oknie Findera. Traktujemy je jak
# bibliotekę: skoro świadomie je wybrał, może w nich analizować i naprawiać
# pliki. Żyją tylko do restartu serwera — nic nie zapisujemy na stałe.
_EXTRA_ROOTS: set[str] = set()


def _allowed_roots() -> list[str]:
    roots = [_folder(), playlists.root(), *_EXTRA_ROOTS]
    return [os.path.abspath(r) for r in roots if r]


def _within_allowed(path: str) -> bool:
    path = os.path.abspath(path)
    return any(os.path.commonpath([path, r]) == r for r in _allowed_roots())


LOSSLESS_EXT = (".flac", ".wav", ".aiff", ".aif")


def _paths() -> list[str]:
    """Biblioteka wraz z podfolderami — tam lądują pobrania z Soulseeka."""
    return matcher.audio_files(_folder())


def _safe(path: str) -> str:
    """Odrzuć pusty parametr, wyjście poza folder i nie-pliki."""
    if not path or not path.strip():
        raise HTTPException(400, "brak nazwy pliku")
    full = os.path.abspath(os.path.join(_folder(), path))
    if not os.path.isfile(full):
        # utwór może leżeć w podfolderze — tam trafiają pobrania z Soulseeka
        found = matcher.resolve_in_library(_folder(), os.path.basename(path))
        if found:
            full = os.path.abspath(found)
    # sprawdzenie granic ZAWSZE po rozwiązaniu ścieżki
    if os.path.commonpath([full, _folder()]) != _folder():
        raise HTTPException(400, "ścieżka poza biblioteką")
    if not os.path.isfile(full):
        raise HTTPException(404, "nie ma takiego pliku")
    return full


def _tags(path: str) -> tuple[str, str]:
    """Artysta i tytuł z pliku; przy uszkodzonym pliku puste zamiast wyjątku."""
    try:
        a = MutagenFile(path)
        if a is None:
            return ("", "")
        if path.lower().endswith(".flac"):
            return (str(a.get("ARTIST", [""])[0]), str(a.get("TITLE", [""])[0]))
        t = getattr(a, "tags", None)
        if t:
            return (str(t.get("TPE1", "")), str(t.get("TIT2", "")))
    except Exception:                          # noqa: BLE001
        pass
    return ("", "")


def _track_row(path: str) -> dict:
    # Uszkodzony plik (np. przerwane pobieranie) nie może wywalić CAŁEGO
    # listowania biblioteki — pokazujemy go z adnotacją, żeby użytkownik
    # mógł go zobaczyć i usunąć, zamiast patrzeć na pustą apkę.
    try:
        a = MutagenFile(path)
    except Exception:                          # noqa: BLE001
        a = None
    name = os.path.basename(path)
    artist, title = _tags(path)
    if not artist and " - " in name:
        artist, _, title = os.path.splitext(name)[0].partition(" - ")
    row = {
        "file": name,
        "rel": os.path.relpath(path, _folder()),
        "artist": artist or "?",
        "title": title or os.path.splitext(name)[0],
        "ext": os.path.splitext(name)[1].lower().lstrip("."),
        "sr": getattr(getattr(a, "info", None), "sample_rate", 0),
        "bits": getattr(getattr(a, "info", None), "bits_per_sample", None),
        "duration": round(getattr(getattr(a, "info", None), "length", 0) or 0),
        "uszkodzony": a is None,
        "size_mb": round(os.path.getsize(path) / 1_000_000, 1),
        "has_cover": covers.embedded_art(path) is not None,
        "bpm": None, "camelot": None, "key": None, "key_conf": None,
        "quality": None, "quality_note": None, "analyzed": False,
    }
    h = cache.get(path, "harmonic")
    if h:
        row.update(bpm=h["bpm"], camelot=h["camelot"], key=h["key"],
                   key_conf=h["confidence_key"], analyzed=True)
    q = cache.get(path, "quality")
    if q:
        row.update(quality=q["grade"], quality_note=q["verdict"],
                   bitrate_kbps=q.get("bitrate_kbps"))
    return row


# zasoby nowego dashboardu (projekt graficzny 3.09.2026): logo, znak,
# skrypty ekranów — tylko katalog static, nic spoza niego
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


def _wersja_pakietu() -> str:
    from . import __version__
    return __version__


def _wersja_statykow() -> str:
    """Stempel do ?v= przy skryptach: wersja pakietu + czas ostatniej zmiany.

    Bez tego przeglądarka po aktualizacji apki potrafi trzymać stare
    ekrany z pamięci podręcznej i pokazywać błędy, których w kodzie już nie ma.
    """
    w = _wersja_pakietu()
    katalog = os.path.join(HERE, "static", "ekrany")
    try:
        mt = max(os.path.getmtime(os.path.join(katalog, f)) for f in os.listdir(katalog))
    except (OSError, ValueError):
        mt = 0
    return f"{w}-{int(mt)}"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as fh:
        return fh.read().replace("__WERSJA__", _wersja_statykow())


@app.get("/stary", response_class=HTMLResponse)
def stary_dashboard() -> str:
    """Poprzedni dashboard — siatka bezpieczeństwa na czas przesiadki."""
    with open(os.path.join(HERE, "static", "stary.html"), encoding="utf-8") as fh:
        return fh.read()


@app.get("/api/tracks")
def api_tracks() -> JSONResponse:
    rows = [_track_row(p) for p in _paths()]
    total_mb = round(sum(r["size_mb"] for r in rows), 1)
    return JSONResponse({
        "folder": _folder(),
        "count": len(rows),
        "total_mb": total_mb,
        "tracks": rows,
    })


@app.get("/api/cover")
def api_cover(file: str = Query(...)) -> Response:
    data = covers.embedded_art(_safe(file))
    if not data:
        raise HTTPException(404, "brak okładki")
    return Response(content=data, media_type="image/jpeg")


@app.post("/api/analyze")
def api_analyze(file: str = Query(...)) -> JSONResponse:
    path = _safe(file)
    ta = harmonic.analyze(path)
    cache.put(path, "harmonic", asdict(ta))
    rep = quality.analyze(path)
    cache.put(path, "quality", {"grade": rep.grade, "verdict": rep.verdict,
                                "cutoff_hz": rep.cutoff_hz,
                                "bitrate_kbps": rep.bitrate_kbps})
    # „Przelicz analizę" ma przeliczyć WSZYSTKO: głośność i cue też —
    # wcześniej zostawały z cache i arkusz pokazywał stare wartości
    try:
        cache.put(path, "loudness", asdict(loudness.analyze(path)))
        cache.put(path, "cues", asdict(cues.analyze(path, bpm=ta.bpm)))
    except Exception:  # noqa: BLE001 — brak głośności nie unieważnia BPM/tonacji
        pass
    return JSONResponse(_track_row(path))


@app.post("/api/import")
def api_import(payload: dict) -> JSONResponse:
    """Rozpoznaj playlistę (dowolne źródło) i dopasuj do biblioteki.

    Trzy pasy: auto (>=0.85), do rozstrzygnięcia (0.5–0.85), nie znaleziono.
    """
    text = _field(payload, "text")
    if not text:
        raise HTTPException(400, "wklej link playlisty albo tracklistę")
    try:
        tracks, origin = importers.resolve_any(text)
    except Exception as exc:  # noqa: BLE001 — surface importer message to UI
        raise HTTPException(400, f"nie udało się rozpoznać źródła: {exc}")
    if not tracks:
        raise HTTPException(400, "nie znalazłem utworów w podanym źródle")

    index = matcher.library_index(_folder())
    auto, resolve, missing = [], [], []
    for t in tracks:
        best = matcher.classify_track(t, index)
        row = {"artist": t.artist, "title": t.title,
               "duration": round(t.duration_s) if t.duration_s else None}
        if best and best.score >= 0.85 and best.same_version:
            row["file"] = os.path.basename(best.path); row["score"] = best.score
            auto.append(row)
        elif best and (best.score >= 0.5 or best.identity >= 0.75):
            # ten sam utwór, ale inna wersja miksu albo słabsze dopasowanie
            row["file"] = os.path.basename(best.path); row["score"] = best.score
            row["other_version"] = not best.same_version
            resolve.append(row)
        else:
            row["buy"] = stores.buy_links(t)["beatport"]
            missing.append(row)
    return JSONResponse({
        "origin": origin,
        "counts": {"auto": len(auto), "resolve": len(resolve), "missing": len(missing),
                   "total": len(tracks)},
        "auto": auto, "resolve": resolve, "missing": missing,
    })


def _harmonic_items() -> list[tuple[str, harmonic.TrackAnalysis]]:
    """(nazwa, analiza) dla przeanalizowanych plików — jedno źródło prawdy
    dla ekranu „Kolejność setu" i dla eksportu, żeby dawały ten sam set."""
    items = []
    for p in _paths():
        h = cache.get(p, "harmonic")
        if h:
            items.append((os.path.basename(p), harmonic.TrackAnalysis(**h)))
    return items


@app.get("/api/order")
def api_order() -> JSONResponse:
    ordered = harmonic.order_set(_harmonic_items())
    return JSONResponse({"order": [
        {"pos": i + 1, "file": name, "camelot": ta.camelot,
         "bpm": ta.bpm, "note": note}
        for i, (name, ta, note) in enumerate(ordered)
    ]})


_HEALTH_CACHE: dict = {"sig": None, "report": None}


def _folder_sig() -> str:
    """Odcisk zawartości folderu (nazwa+mtime+rozmiar plików audio) —
    zmienia się dokładnie wtedy, gdy trzeba przeskanować od nowa."""
    parts = []
    for root, _dirs, files in os.walk(_folder()):
        for f in files:
            if f.lower().endswith(matcher.AUDIO_EXT):
                try:
                    st = os.stat(os.path.join(root, f))
                    parts.append((f, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
    return hashlib.md5(repr(sorted(parts)).encode()).hexdigest()


@app.get("/api/health")
def api_health() -> JSONResponse:
    sig = _folder_sig()
    if _HEALTH_CACHE["sig"] == sig and _HEALTH_CACHE["report"] is not None:
        return JSONResponse(_HEALTH_CACHE["report"])
    rep = health.scan(_folder(), deep=False)
    result = {
        "files": len(rep.files),
        "problems": rep.problem_count,
        "duplicates": [{"keep": os.path.basename(g.files[0].path),
                        "n": len(g.files)} for g in rep.duplicates],
        "corrupt": [os.path.basename(p) for p, _ in rep.corrupt],
        "missing_covers": [os.path.basename(p) for p in rep.missing_covers],
        "cached": False,
    }
    _HEALTH_CACHE.update(sig=sig, report={**result, "cached": True})
    return JSONResponse(result)


# --------------------------------------------------------------------------
# szczegóły utworu — jakość, BPM/tonacja, głośność, cue (z cache)
# --------------------------------------------------------------------------

@app.get("/api/track")
def api_track(file: str = Query(...)) -> JSONResponse:
    p = _safe(file)
    h = cache.get(p, "harmonic")
    if h is None:
        ta = harmonic.analyze(p); h = asdict(ta); cache.put(p, "harmonic", h)
    q = cache.get(p, "quality")
    if q is None:
        rep = quality.analyze(p)
        q = {"grade": rep.grade, "verdict": rep.verdict, "cutoff_hz": rep.cutoff_hz}
        cache.put(p, "quality", q)
    l = cache.get(p, "loudness")
    if l is None:
        l = asdict(loudness.analyze(p)); cache.put(p, "loudness", l)
    c = cache.get(p, "cues")
    if c is None:
        c = asdict(cues.analyze(p, bpm=h.get("bpm"))); cache.put(p, "cues", c)
    integ = cache.get(p, "integrity")
    if integ is None:
        ch = pipeline.integrity(p)
        integ = {"ok": ch.passed, "detail": ch.detail}; cache.put(p, "integrity", integ)
    row = _track_row(p)
    row.update(harmonic=h, quality_full=q, loudness=l, cues=c, integrity=integ)
    return JSONResponse(_clean(row))


# --------------------------------------------------------------------------
# zdrowie — akcje naprawcze
# --------------------------------------------------------------------------

@app.get("/api/dedupe")
def api_dedupe() -> JSONResponse:
    actions = dedupe.plan(_folder())
    return JSONResponse({"actions": [
        {"keep": os.path.basename(a.keep),
         "remove": [os.path.basename(x) for x in a.remove],
         "reason": a.reason,
         "reclaim_mb": round(getattr(a, "reclaim_bytes", 0) / 1_000_000, 1)}
        for a in actions]})


@app.post("/api/dedupe/apply")
def api_dedupe_apply() -> JSONResponse:
    actions = dedupe.plan(_folder())
    res = dedupe.apply(actions, os.path.join(_folder(), "_selekta_kosz"))
    return JSONResponse({"moved": len(res.get("przeniesione", [])),
                         "reclaimed_mb": round(res.get("odzyskane_MB", 0), 1)})


@app.get("/api/tagfix")
def api_tagfix() -> JSONResponse:
    hits = tagfix.scan(_folder())
    return JSONResponse({"hits": [
        {"file": os.path.basename(p), "field": f, "current": c, "suggested": s}
        for p, f, c, s in hits]})


@app.post("/api/tagfix/apply")
def api_tagfix_apply() -> JSONResponse:
    seen = set()
    for p, *_ in tagfix.scan(_folder()):
        if p not in seen:
            tagfix.fix_file(p, dry_run=False); seen.add(p)
    return JSONResponse({"fixed": len(seen)})


@app.post("/api/covers/fill")
def api_covers_fill(file: str = Query(...)) -> JSONResponse:
    p = _safe(file)
    artist, _, title = os.path.splitext(os.path.basename(p))[0].partition(" - ")
    hit = covers.from_itunes(artist, title or artist)
    if not hit:
        raise HTTPException(404, "nie znaleziono okładki w iTunes")
    tagger.tag_file(p, artist, title or artist, hit.data)
    return JSONResponse({"ok": True, "desc": hit.description})


@app.post("/api/redownload")
def api_redownload(payload: dict) -> JSONResponse:
    name = os.path.splitext(_field(payload, "file"))[0]
    artist, _, title = name.partition(" - ")
    wishlist.add(artist.strip(), (title or name).strip())
    return JSONResponse({"queued": name})


# --------------------------------------------------------------------------
# eksport / USB
# --------------------------------------------------------------------------

def _in_set_order(tracks: list[dict]) -> list[dict]:
    """Ułóż utwory w kolejności harmonicznej (koło Camelot, energia rosnąco).

    Bez tego rekordbox dostaje playlistę alfabetyczną — czyli kolekcję,
    a nie set do zagrania. Utwory bez policzonej analizy lądują na końcu.
    """
    by_name = {os.path.basename(t["path"]): t for t in tracks}
    # Wejście budujemy dokładnie tak jak /api/order — przy remisach kosztu
    # kolejność wejścia rozstrzyga wybór, więc inne sortowanie dałoby inny
    # (też poprawny) set niż ten pokazany na ekranie.
    items = _harmonic_items()
    if not items:
        return tracks
    ordered = [by_name[name] for name, _ta, _note in harmonic.order_set(items)
               if name in by_name]
    seen = {id(t) for t in ordered}
    return ordered + [t for t in tracks if id(t) not in seen]


@app.post("/api/export")
def api_export(payload: dict) -> JSONResponse:
    target = _field(payload, "target") or "rekordbox"
    if target not in EXPORT_TARGETS:
        raise HTTPException(400, f"nieznany cel eksportu: {target}")
    name = _field(payload, "name") or os.path.basename(os.path.normpath(_folder()))
    tracks = dj_export.collect(_folder())
    if not tracks:
        raise HTTPException(400, "biblioteka jest pusta — nie ma czego eksportować")
    if _field(payload, "order") == "set":
        tracks = _in_set_order(tracks)
    if target == "rekordbox":
        out = dj_export.to_rekordbox_xml(dj_export.wzbogac_o_siatke(tracks), name,
                                         os.path.join(_folder(), f"{name}.xml"))
    elif target == "m3u8":
        out = dj_export.to_m3u8(tracks, os.path.join(_folder(), f"{name}.m3u8"))
    else:
        out = dj_export.install_serato_crate(tracks, os.path.expanduser("~/Music"), name)
    return JSONResponse({"path": out, "count": len(tracks)})


@app.post("/api/queue")
def api_queue_add(payload: dict) -> JSONResponse:
    """Dodaj utwory do kolejki pobierania (jeden naraz, z odstępami)."""
    items = (payload or {}).get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "brak utworów do dodania")
    added = dlqueue.QUEUE.add([i for i in items if isinstance(i, dict)])
    return JSONResponse({"added": added, **dlqueue.QUEUE.state()})


@app.get("/api/queue")
def api_queue_state() -> JSONResponse:
    return JSONResponse(dlqueue.QUEUE.state())


@app.post("/api/queue/clear")
def api_queue_clear() -> JSONResponse:
    return JSONResponse({"removed": dlqueue.QUEUE.clear_finished(),
                         **dlqueue.QUEUE.state()})


@app.post("/api/queue/cancel")
def api_queue_cancel() -> JSONResponse:
    return JSONResponse({"cancelled": dlqueue.QUEUE.cancel_pending(),
                         **dlqueue.QUEUE.state()})


@app.get("/api/status")
def api_status() -> JSONResponse:
    """Lekki stan połączenia — pod kropkę w rogu, odpytywany co kilka sekund."""
    client = SlskdClient()
    if not client.available():
        return JSONResponse({"level": "red", "label": "slskd nie działa",
                             "hint": "Uruchom slskd w zakładce Ustawienia.",
                             "wersja": _wersja_pakietu()})
    if not client.logged_in():
        return JSONResponse({"level": "amber", "label": "Soulseek: rozłączony",
                             "hint": "slskd działa, ale nie jest zalogowany do sieci "
                                     "Soulseek. Zwykle wraca samo po chwili.",
                             "wersja": _wersja_pakietu()})
    return JSONResponse({"level": "green", "label": "Soulseek: połączony", "hint": "",
                         "wersja": _wersja_pakietu()})


@app.get("/api/config")
def api_config() -> JSONResponse:
    """Ustawienia (klucz zamaskowany) + pełny stan slskd i rekordboxa."""
    st = slskd_ctl.status()
    return JSONResponse({
        "config": config.masked(),
        "folder": _folder(),
        "slskd": {
            "binary": st.binary, "running": st.running,
            "reachable": st.reachable, "authorized": st.authorized,
            "logged_in": st.logged_in, "detail": st.detail,
            "config_file": slskd_ctl.find_config(),
            "url": config.get("slskd_url"),
        },
        "rekordbox": {
            "installed": rekordbox.settings_path() is not None,
            "running": rekordbox.is_running(),
            "linked": rekordbox.imported_library() or "",
        },
    })


@app.post("/api/config")
def api_config_save(payload: dict) -> JSONResponse:
    """Zapisz ustawienia. Pusty klucz API nie kasuje zapisanego."""
    values = {}
    for key in ("slskd_url", "slskd_api_key", "slskd_binary"):
        val = _field(payload, key)
        if val:
            values[key] = val
    folder = _field(payload, "folder")
    if folder:
        expanded = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(expanded):
            raise HTTPException(400, f"nie ma takiego folderu: {expanded}")
        set_folder(expanded)
        values["library_folder"] = expanded
        _HEALTH_CACHE.update(sig=None, report=None)
    config.save(values)
    return api_config()


@app.post("/api/config/autodetect")
def api_config_autodetect() -> JSONResponse:
    """Znajdź klucz API w konfiguracji slskd — bez ręcznego przeklejania."""
    key = slskd_ctl.api_key_from_slskd_config()
    if not key:
        raise HTTPException(
            404, "nie znalazłem klucza API w konfiguracji slskd — "
                 "dodaj go tam albo wklej ręcznie")
    config.save({"slskd_api_key": key})
    return api_config()


@app.post("/api/slskd/start")
def api_slskd_start() -> JSONResponse:
    ok, message = slskd_ctl.start()
    return JSONResponse({"ok": ok, "message": message})


@app.post("/api/slskd/stop")
def api_slskd_stop() -> JSONResponse:
    ok, message = slskd_ctl.stop()
    return JSONResponse({"ok": ok, "message": message})


def _harmonic_for(paths: list[str]) -> list[tuple[str, harmonic.TrackAnalysis]]:
    """Analiza dla konkretnej listy plików (nie całej biblioteki).

    Brakujące liczymy w locie — playlista może zawierać świeżo pobrane
    utwory, których nikt jeszcze nie analizował.
    """
    items = []
    for p in paths:
        if not os.path.isfile(p):
            continue
        h = cache.get(p, "harmonic")
        if h is None:
            h = asdict(harmonic.analyze(p))
            cache.put(p, "harmonic", h)
        items.append((p, harmonic.TrackAnalysis(**h)))
    return items


@app.post("/api/playlist/collect")
def api_playlist_collect(payload: dict) -> JSONResponse:
    """Zbierz utwory playlisty do jej własnego folderu (kopie z biblioteki).

    Oprócz plików wskazanych przez interfejs DOPASOWUJEMY PONOWNIE całą
    playlistę do biblioteki. Bez tego utwory, których pobieranie skończyło
    się już po kliknięciu „dalej", wypadały z eksportu — a to najczęstszy
    przypadek przy większych playlistach.
    """
    name = _field(payload, "name") or "set"
    wanted = [str(x) for x in ((payload or {}).get("files") or [])]
    tracks = (payload or {}).get("tracks") or []      # [{artist,title,duration}]

    paths, seen = [], set()
    for f in wanted:
        p = matcher.resolve_in_library(_folder(), f)
        # playlista z dysku może wskazywać poza bibliotekę (pendrive, inny
        # folder z muzyką) — bierzemy to, ale wyłącznie pliki audio
        if p and not p.lower().endswith(matcher.AUDIO_EXT):
            p = None
        if p and p not in seen:
            seen.add(p); paths.append(p)

    # dociągnij to, co doszło do biblioteki w międzyczasie
    late = []
    if tracks:
        index = matcher.library_index(_folder())
        for t in tracks:
            if not isinstance(t, dict):
                continue
            trk = spotify.Track(id="", artist=str(t.get("artist", "")),
                                title=str(t.get("title", "")),
                                duration_s=t.get("duration"))
            # Czy ten utwór już jest na playliście — choćby jako INNA kopia?
            # Bez tego playlista z pliku M3U dostawała ten sam kawałek dwa
            # razy: raz ze wskazanej ścieżki, raz z dopasowania biblioteki.
            juz = matcher.classify_track(trk, matcher.index_paths(paths))
            if juz and (juz.score >= 0.5 or juz.identity >= 0.75):
                continue
            best = matcher.classify_track(trk, index)
            if best and (best.score >= 0.5 or best.identity >= 0.75):
                if best.path not in seen:
                    seen.add(best.path); paths.append(best.path); late.append(best.path)

    if not paths:
        raise HTTPException(400, "brak utworów do zebrania")

    res = playlists.collect(name, paths)
    playlists.save_manifest(name, res["files"])
    return JSONResponse({
        "name": name, "folder": res["folder"], "count": len(res["files"]),
        "copied": len(res["copied"]), "reused": len(res["reused"]),
        "late": [os.path.basename(p) for p in late],
        "missing": res["missing"], "files": res["files"],
    })


@app.post("/api/playlist/analyze")
def api_playlist_analyze(payload: dict) -> JSONResponse:
    """Przeanalizuj JEDEN plik playlisty (może leżeć poza biblioteką).

    Ścieżka musi mieścić się w bibliotece, w katalogu playlist albo w
    folderze, który użytkownik sam wskazał w oknie Findera.
    """
    path = os.path.abspath(_field(payload, "path"))
    if not _within_allowed(path):
        raise HTTPException(400, "ścieżka poza biblioteką i katalogiem playlist")
    if not os.path.isfile(path):
        raise HTTPException(404, "nie ma takiego pliku")
    h = cache.get(path, "harmonic")
    if h is None:
        h = asdict(harmonic.analyze(path))
        cache.put(path, "harmonic", h)
    q = cache.get(path, "quality")
    if q is None:
        rep = quality.analyze(path)
        q = {"grade": rep.grade, "verdict": rep.verdict, "cutoff_hz": rep.cutoff_hz}
        cache.put(path, "quality", q)
    return JSONResponse(_clean({"file": os.path.basename(path),
                                "bpm": h.get("bpm"), "camelot": h.get("camelot"),
                                "quality": q.get("grade")}))


MAX_PLAYLIST_BYTES = 8 * 1024 * 1024      # największe XML-e rekordboxa to ~2 MB


def _lanes_from_entries(entries: list, origin: str, name: str) -> dict:
    """Wpisy playlisty z dysku → te same trzy pasy, co import z sieci.

    Wpis, który wskazuje na istniejący plik, trafia od razu do „mam" —
    nie ma czego zgadywać ani dociągać. Resztę dopasowujemy do biblioteki
    normalną drogą, żeby playlista z Serato czy CSV też coś znalazła.
    """
    auto, resolve, missing = [], [], []
    index = None
    for e in entries:
        row = {"artist": e.artist, "title": e.title,
               "duration": round(e.duration_s) if e.duration_s else None}
        if e.path:
            row["file"] = e.path
            row["score"] = 1.0
            row["from_file"] = True
            auto.append(row)
            continue
        if index is None:
            index = matcher.library_index(_folder())
        trk = spotify.Track(id="", artist=e.artist, title=e.title,
                            duration_s=e.duration_s)
        best = matcher.classify_track(trk, index)
        if best and best.score >= 0.85 and best.same_version:
            row["file"] = os.path.basename(best.path); row["score"] = best.score
            auto.append(row)
        elif best and (best.score >= 0.5 or best.identity >= 0.75):
            row["file"] = os.path.basename(best.path); row["score"] = best.score
            row["other_version"] = not best.same_version
            resolve.append(row)
        else:
            row["buy"] = stores.buy_links(trk)["beatport"]
            missing.append(row)
    return {
        "origin": origin, "name": name,
        "counts": {"auto": len(auto), "resolve": len(resolve),
                   "missing": len(missing), "total": len(entries)},
        "auto": auto, "resolve": resolve, "missing": missing,
    }


def _obecna_jakosc(path: str) -> dict:
    """Co użytkownik ma teraz: format, bitrate i werdykt analizy pasma."""
    q = cache.get(path, "quality")
    if q is None:
        rep = quality.analyze(path)
        q = {"grade": rep.grade, "verdict": rep.verdict, "cutoff_hz": rep.cutoff_hz}
        cache.put(path, "quality", q)
    a = MutagenFile(path)
    ext = os.path.splitext(path)[1].lower()
    return {
        "grade": q.get("grade"), "verdict": q.get("verdict"),
        "cutoff_hz": q.get("cutoff_hz"),
        "format": ext.lstrip(".").upper(),
        "lossless": ext in LOSSLESS_EXT,
        "bitrate": int(getattr(a.info, "bitrate", 0) or 0) // 1000 if a else 0,
    }


@app.post("/api/upgrade/list")
def api_upgrade_list(payload: dict) -> JSONResponse:
    """Utwory warte poszukania w lepszej jakości.

    Stratnej kompresji NIE DA SIĘ odkręcić — górnego pasma po prostu nie ma
    w pliku. Jedyne, co ma sens, to znaleźć lepsze źródło, więc tu tylko
    wskazujemy, co jest kandydatem do wymiany.
    """
    files = [str(x) for x in ((payload or {}).get("files") or [])]
    if not files:
        folder = _field(payload, "folder") or _folder()
        if not _within_allowed(folder):
            raise HTTPException(400, "folder poza dozwolonym katalogiem")
        files = matcher.audio_files(folder)
    rows = []
    for path in files:
        if not os.path.isfile(path) or not _within_allowed(path):
            continue
        info = _obecna_jakosc(path)
        if info["grade"] == "ok":
            continue
        artist, title = _tags(path)
        if not (artist and title):
            kand = tagfix.name_candidates(os.path.splitext(os.path.basename(path))[0])
            if kand:
                artist, title = kand[0]
        rows.append({"path": path, "file": os.path.basename(path),
                     "artist": artist or "?", "title": title or os.path.basename(path),
                     "duration": round(getattr(MutagenFile(path).info, "length", 0) or 0),
                     **info})
    rows.sort(key=lambda r: (r["grade"] != "bad", r.get("cutoff_hz") or 0))
    return JSONResponse(_clean({"count": len(rows), "tracks": rows}))


def _basename(c: dict) -> str:
    """Nazwa pliku kandydata. Soulseek podaje ścieżki w stylu Windows,
    a os.path.basename na macOS nie dzieli po backslashu."""
    nazwa = str(c.get("filename") or "")
    if nazwa:
        return nazwa
    return os.path.basename(str(c.get("path") or "").replace("\\", "/"))


# Przy PODMIANIE pliku próg jest wyższy niż przy zwykłym szukaniu: zły
# utwór w secie boli bardziej niż przegapione ulepszenie. Dlatego lokalnie
# rozszerzamy listę określeń wersji o te, których matcher nie zna.
_WERSJE = matcher.MIX_WORDS | {"short", "live", "acoustic", "unplugged",
                               "demo", "reprise", "karaoke"}


def _mix_sig(tokens: list[str]) -> frozenset[str]:
    """Sygnatura wersji, odporna na sklejone zapisy.

    „Clubmix" czy „radioedit" to jeden token, więc samo sprawdzenie
    przynależności do MIX_WORDS ich nie widzi — a to właśnie one odróżniają
    bootleg od club mixu.
    """
    znane = _WERSJE | matcher.NOISE | {""}
    sig = {t for t in tokens if t in _WERSJE}
    for t in tokens:
        for w in _WERSJE:
            if len(w) < 4 or t == w:
                continue
            # reszta po odcięciu musi też być znanym słowem — inaczej
            # „editor" udawałby „edit", a „clubmix" ma zostać rozpoznane
            if t.startswith(w) and t[len(w):] in znane:
                sig.add(w)
            elif t.endswith(w) and t[:-len(w)] in znane:
                sig.add(w)
    return frozenset(sig)


@app.post("/api/upgrade/find")
def api_upgrade_find(payload: dict) -> JSONResponse:
    """Znajdź na Soulseeku wersje LEPSZE od tej, którą użytkownik ma."""
    client = SlskdClient()
    if not client.available():
        raise HTTPException(503, "slskd niepodłączony — sprawdź Ustawienia")
    artist, title = _field(payload, "artist"), _field(payload, "title")
    if not (artist or title):
        raise HTTPException(400, "podaj artystę albo tytuł")
    duration = (payload or {}).get("duration")
    mam_lossless = bool((payload or {}).get("lossless"))
    mam_bitrate = int((payload or {}).get("bitrate") or 0)
    # Nagłówek MP3 potrafi kłamać: plik przekodowany ze 128 kbps do 320
    # deklaruje 320, choć pasmo urywa się na 16 kHz. Gdy analiza uznała
    # jakość za złą, nie ufamy tej liczbie — inaczej odrzucalibyśmy
    # uczciwe 320 kbps jako „nie lepsze".
    if (_field(payload, "grade") or "") == "bad":
        mam_bitrate = 0
    try:
        kandydaci = client.search_candidates(artist, title, duration)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"wyszukiwanie nie powiodło się: {exc}")

    # Sam pokrywający się tytuł to za mało: „Is Not Sweet" trafiało w
    # „sweet dreams & goodnight", a bootleg podmieniano na club mix.
    # Wymagamy więc, żeby zgadzały się ISTOTNE słowa tytułu (bez określeń
    # wersji) ORAZ sama wersja — inaczej DJ dostaje w secie inny utwór.
    want_tok = matcher.normalize(title)
    core_want = {t for t in want_tok if t not in matcher.MIX_WORDS}
    want_mix = _mix_sig(want_tok)
    artysta_tok = set(matcher.normalize(artist))

    lepsze = []
    for c in kandydaci:
        # TYLKO nazwa pliku. Po całej ścieżce nazwy folderów dorzucają słowa,
        # których w utworze nie ma: „Is Not Sweet" pokrywało się w 100%
        # z folderem „It's Not What You Think It Is" + plikiem „Sweet Dreams".
        cand_tok = matcher.normalize(_basename(c))
        core_cand = {t for t in cand_tok if t not in matcher.MIX_WORDS}
        if core_want:
            pokrycie = len(core_want & core_cand) / len(core_want)
            if pokrycie < 0.75:
                continue                   # brakuje istotnych słów tytułu
        elif c["title_match"] < 0.6:
            continue

        # Samo ZAWIERANIE tytułu nie wystarcza: „United" mieści się w
        # „United in Unhallowed Grace", a „Icarus" w „Icarus & Pegasus".
        # Słowa nadmiarowe — poza tytułem, artystą i numerem ścieżki —
        # zdradzają, że to inny utwór.
        nadmiar = {t for t in core_cand
                   if t not in core_want and t not in artysta_tok
                   and not t.isdigit()}
        if len(nadmiar) >= 2:
            continue

        # Ten sam tytuł bywa u różnych wykonawców („Cherry Blossom”
        # Marcela Woodsa vs Harry'ego Kaze) — artysta musi się zgadzać.
        if artysta_tok and (c.get("artist_match") or 0) < 0.5:
            continue
        cand_mix = _mix_sig(cand_tok)
        if want_mix and cand_mix and want_mix != cand_mix:
            continue                       # remix zamiast bootlegu itp.
        if c["duration_delta"] is not None and c["duration_delta"] > 5:
            continue                       # inna wersja/długość

        if c["duration_delta"] is None:
            c["pewnosc"] = "serwer nie podał długości — sprawdź przed graniem"
        elif want_mix != cand_mix:
            c["pewnosc"] = "wersja niepotwierdzona nazwą"
        else:
            c["pewnosc"] = "pewne"

        if c["lossless"] and not mam_lossless:
            c["dlaczego"] = "bezstratny zamiast stratnego"
        elif (c.get("bitrate") or 0) >= max(320, mam_bitrate + 64):
            c["dlaczego"] = (f"{c['bitrate']} kbps"
                             + (f" zamiast {mam_bitrate}" if mam_bitrate else
                                " z pełnym pasmem"))
        else:
            continue
        lepsze.append(c)
    lepsze.sort(key=lambda c: (c.get("pewnosc") != "pewne", not c["lossless"],
                               -(c.get("bitrate") or 0), not c["duration_ok"],
                               -c["title_match"]))
    return JSONResponse(_clean({
        "artist": artist, "title": title,
        "sprawdzonych": len(kandydaci), "count": len(lepsze),
        "candidates": lepsze[:20],
        "searched_as": slskd_primary(artist),
    }))


@app.post("/api/pick")
def api_pick(payload: dict) -> JSONResponse:
    """Pokaż natywne okno Findera i oddaj wybraną ścieżkę.

    Bez tego użytkownik musiałby przepisywać ścieżkę ręcznie — a folder
    z muzyką bywa na dysku zewnętrznym o długiej nazwie.
    """
    czego = (_field(payload, "what") or "folder").lower()
    prompt = _field(payload, "prompt") or (
        "Wskaż folder z muzyką" if czego == "folder" else "Wskaż plik playlisty")
    try:
        path = (folderpick.choose_folder(prompt) if czego == "folder"
                else folderpick.choose_file(prompt))
    except folderpick.PickCancelled as exc:
        return JSONResponse({"ok": False, "cancelled": True, "message": str(exc)})
    except folderpick.PickUnavailable as exc:
        raise HTTPException(400, str(exc))
    path = os.path.normpath(path)
    root = path if os.path.isdir(path) else os.path.dirname(path)
    _EXTRA_ROOTS.add(os.path.abspath(root))
    return JSONResponse({"ok": True, "path": path,
                         "name": os.path.basename(path)})


@app.post("/api/playlist/upload")
async def api_playlist_upload(file: UploadFile = File(...)) -> JSONResponse:
    """Playlista wgrana z komputera: M3U/M3U8, PLS, XML rekordboxa,
    NML Traktora, CSV z Serato albo zwykła tracklista."""
    raw = await file.read(MAX_PLAYLIST_BYTES + 1)
    if len(raw) > MAX_PLAYLIST_BYTES:
        raise HTTPException(400, "plik playlisty jest za duży (limit 8 MB)")
    if not raw.strip():
        raise HTTPException(400, "plik playlisty jest pusty")
    text = raw.decode("utf-8", errors="replace")
    nazwa = os.path.splitext(os.path.basename(file.filename or "playlista"))[0]
    kind = localplaylist.sniff(text, file.filename or "")
    try:
        entries = localplaylist.parse_text(text, kind)
    except Exception as exc:  # noqa: BLE001 — komunikat trafia do interfejsu
        raise HTTPException(400, f"nie udało się odczytać playlisty ({kind}): {exc}")
    if not entries:
        raise HTTPException(400, "nie znalazłem utworów w tym pliku")
    return JSONResponse(_clean(_lanes_from_entries(entries, f"plik:{kind}", nazwa)))


@app.post("/api/playlist/local")
def api_playlist_local(payload: dict) -> JSONResponse:
    """Playlista albo folder wskazany ścieżką na dysku.

    Przydaje się, gdy M3U ma ścieżki WZGLĘDNE — przy wgrywaniu przez
    przeglądarkę nie wiemy, gdzie ten plik leżał, więc nie da się ich
    rozwiązać; przy ścieżce wiemy.
    """
    path = os.path.expanduser(_field(payload, "path"))
    if not path:
        raise HTTPException(400, "podaj ścieżkę do playlisty albo folderu")
    path = os.path.abspath(path)
    try:
        if os.path.isdir(path):
            parsed = localplaylist.from_folder(path)
        elif os.path.isfile(path):
            if os.path.getsize(path) > MAX_PLAYLIST_BYTES:
                raise HTTPException(400, "plik playlisty jest za duży (limit 8 MB)")
            parsed = localplaylist.from_file(path)
        else:
            raise HTTPException(404, f"nie ma takiej ścieżki: {path}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"nie udało się odczytać playlisty: {exc}")
    if not parsed.entries:
        raise HTTPException(400, "nie znalazłem utworów pod tą ścieżką")
    return JSONResponse(_clean(
        _lanes_from_entries(parsed.entries, f"dysk:{parsed.kind}", parsed.name)))


_MIME_AUDIO = {
    ".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
    ".aiff": "audio/aiff", ".aif": "audio/aiff", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".opus": "audio/opus", ".alac": "audio/mp4",
}


@app.get("/api/audio")
def api_audio(file: str = Query(...), request: Request = None) -> Response:
    """Odtwarzanie utworu w przeglądarce, z obsługą przewijania.

    Bez nagłówka Range przeglądarka musi pobrać cały plik, zanim pozwoli
    przeskoczyć w środek — przy 40 MB FLAC-u odsłuch byłby bezużyteczny.
    """
    path = _safe(file)
    rozmiar = os.path.getsize(path)
    mime = _MIME_AUDIO.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    naglowki = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}

    zakres = (request.headers.get("range") or "") if request else ""
    m = re.match(r"bytes=(\d*)-(\d*)", zakres)
    if not m:
        with open(path, "rb") as fh:
            return Response(fh.read(), media_type=mime,
                            headers={**naglowki, "Content-Length": str(rozmiar)})

    poczatek = int(m.group(1)) if m.group(1) else 0
    koniec = int(m.group(2)) if m.group(2) else rozmiar - 1
    koniec = min(koniec, rozmiar - 1)
    if poczatek > koniec or poczatek >= rozmiar:
        return Response(status_code=416,
                        headers={"Content-Range": f"bytes */{rozmiar}"})
    with open(path, "rb") as fh:
        fh.seek(poczatek)
        dane = fh.read(koniec - poczatek + 1)
    return Response(dane, status_code=206, media_type=mime,
                    headers={**naglowki,
                             "Content-Range": f"bytes {poczatek}-{koniec}/{rozmiar}",
                             "Content-Length": str(len(dane))})


@app.post("/api/playlist/from-selection")
def api_playlist_from_selection(payload: dict) -> JSONResponse:
    """Zrób playlistę z utworów zaznaczonych ręcznie w bibliotece."""
    name = _field(payload, "name")
    if not name:
        raise HTTPException(400, "podaj nazwę playlisty")
    files = [str(x) for x in ((payload or {}).get("files") or [])]
    if not files:
        raise HTTPException(400, "nie zaznaczono żadnego utworu")
    paths, seen = [], set()
    for f in files:
        p = matcher.resolve_in_library(_folder(), f)
        if p and p.lower().endswith(matcher.AUDIO_EXT) and p not in seen:
            seen.add(p); paths.append(p)
    if not paths:
        raise HTTPException(404, "żaden z zaznaczonych plików się nie odnalazł")
    wynik = playlists.collect(name, paths)
    playlists.save_manifest(name, wynik["files"])
    return JSONResponse(_clean({**wynik, "name": name,
                                "count": len(wynik["files"]),
                                "pominietych": len(wynik["missing"])}))


@app.get("/api/setup/stan")
def api_setup_stan() -> JSONResponse:
    """Czego brakuje, żeby apka działała — lista kroków dla nowego użytkownika.

    Świadomie NIE dotykamy hasła do Soulseeka: wpisuje je użytkownik
    bezpośrednio w panelu slskd. Selekta nie ma powodu go widzieć ani
    przechowywać.
    """
    folder = _folder()
    ma_folder = bool(folder and os.path.isdir(folder))
    utworow = len(matcher.audio_files(folder)) if ma_folder else 0

    binarka = slskd_ctl.find_binary()
    dziala = slskd_ctl.is_running()
    klucz = bool(config.get("slskd_api_key"))
    yml = slskd_ctl.find_config()
    konto = instalator.konto_ustawione(yml) if yml else False
    client = SlskdClient()
    polaczony = client.logged_in() if (dziala and klucz) else False

    kroki = [
        {"id": "folder", "tytul": "Folder z muzyką",
         "gotowe": ma_folder and utworow > 0,
         "opis": (f"{utworow} utworów w {folder}" if ma_folder and utworow
                  else "wskaż katalog, w którym trzymasz muzykę"),
         "akcja": "wybierz-folder"},
        {"id": "slskd", "tytul": "Program do pobierania (slskd)",
         "gotowe": bool(binarka),
         "opis": (f"zainstalowany" if binarka
                  else "pobiorę go automatycznie, ok. 55 MB"),
         "akcja": None if binarka else "instaluj-slskd"},
        {"id": "konfiguracja", "tytul": "Konfiguracja i klucz dostępu",
         "gotowe": klucz,
         "opis": ("gotowa" if klucz
                  else "wygeneruję klucz i ustawię katalogi pobierania"),
         "akcja": None if klucz else "konfiguruj"},
        {"id": "konto", "tytul": "Konto Soulseek",
         "gotowe": konto and polaczony,
         "opis": ("połączony z siecią Soulseek" if polaczony
                  else "zapisane, ale bez połączenia — sprawdź dane"
                  if konto else
                  "podaj swój login i hasło; nie ma rejestracji — konto "
                  "powstaje przy pierwszym logowaniu"),
         "akcja": None if (konto and polaczony) else "podaj-konto"},
        {"id": "uruchomiony", "tytul": "Wszystko działa",
         "gotowe": dziala and polaczony,
         "opis": ("slskd działa i jest połączony" if (dziala and polaczony)
                  else "uruchomię i sprawdzę połączenie"),
         "akcja": None if (dziala and polaczony) else "uruchom-slskd"},
    ]
    zostalo = [k for k in kroki if not k["gotowe"]]
    return JSONResponse(_clean({
        "gotowe": not zostalo,
        "krokow": len(kroki), "zrobionych": len(kroki) - len(zostalo),
        "nastepny": zostalo[0]["id"] if zostalo else None,
        "kroki": kroki,
    }))


@app.post("/api/setup/instaluj")
def api_setup_instaluj() -> JSONResponse:
    """Pobierz i zainstaluj slskd — bez terminala i bez Homebrew."""
    if slskd_ctl.find_binary():
        return JSONResponse({"ok": True, "message": "slskd jest już zainstalowany",
                             "sciezka": slskd_ctl.find_binary()})
    udane, komunikat, sciezka = instalator.zainstaluj()
    if not udane:
        raise HTTPException(500, komunikat)
    config.save({"slskd_binary": sciezka})
    return JSONResponse({"ok": True, "message": komunikat, "sciezka": sciezka})


@app.post("/api/setup/konfiguruj")
def api_setup_konfiguruj(payload: dict | None = None) -> JSONResponse:
    """Wygeneruj konfigurację slskd: klucz API i katalogi pobierania.

    Klucz API to sekret między selektą a slskd na tej maszynie — nie ma
    nic wspólnego z hasłem do Soulseeka i nigdzie nie wychodzi.
    """
    yml = slskd_ctl.config_write_path()
    klucz = config.get("slskd_api_key") or instalator.wygeneruj_klucz()
    udostepniane = None
    if (payload or {}).get("udostepniaj"):
        udostepniane = [_folder()]
    try:
        instalator.zapisz_konfiguracje(
            yml, klucz_api=klucz, katalog_pobran=_folder(),
            katalog_niepelnych=os.path.join(os.path.dirname(yml), "incomplete"),
            udostepniane=udostepniane)
    except OSError as exc:
        raise HTTPException(500, f"nie udało się zapisać konfiguracji: {exc}")
    config.save({"slskd_api_key": klucz})
    return JSONResponse({"ok": True, "plik": yml,
                         "udostepnianie": bool(udostepniane),
                         "message": "konfiguracja zapisana"})


@app.post("/api/setup/konto")
def api_setup_konto(payload: dict) -> JSONResponse:
    """Zapisz dane logowania do Soulseeka podane przez użytkownika.

    Hasło trafia WYŁĄCZNIE do konfiguracji slskd na tym komputerze
    (prawa 0600). Nie zapisujemy go w ustawieniach selekty, nie zwracamy
    w żadnej odpowiedzi i nie logujemy — apka nie ma powodu go znać.
    """
    login = str((payload or {}).get("login") or "").strip()
    haslo = str((payload or {}).get("haslo") or "")
    if not login or not haslo:
        raise HTTPException(400, "podaj login i hasło do Soulseeka")
    if len(login) > 64 or len(haslo) > 256:
        raise HTTPException(400, "login lub hasło są nieprawdopodobnie długie")

    yml = slskd_ctl.config_write_path()
    klucz = config.get("slskd_api_key") or instalator.wygeneruj_klucz()
    try:
        instalator.zapisz_konfiguracje(
            yml, klucz_api=klucz, katalog_pobran=_folder(),
            katalog_niepelnych=os.path.join(os.path.dirname(yml), "incomplete"),
            login=login, haslo=haslo)
    except OSError as exc:
        raise HTTPException(500, f"nie udało się zapisać konfiguracji: {exc}")
    config.save({"slskd_api_key": klucz})

    # slskd czyta konfigurację przy starcie — bez restartu nic się nie zmieni
    slskd_ctl.stop()
    time.sleep(1.5)
    uruchomione, komunikat = slskd_ctl.start()
    if not uruchomione:
        raise HTTPException(500, f"zapisano, ale slskd nie wstał: {komunikat}")
    return JSONResponse({"ok": True, "login": login,
                         "message": "zapisano — sprawdzam połączenie"})


@app.get("/api/setup/polaczenie")
def api_setup_polaczenie() -> JSONResponse:
    """Czy slskd zalogował się do sieci Soulseek."""
    client = SlskdClient()
    if not client.available():
        return JSONResponse({"stan": "brak-slskd",
                             "opis": "slskd nie odpowiada"})
    if client.logged_in():
        return JSONResponse({"stan": "polaczony",
                             "opis": "zalogowany do sieci Soulseek"})
    return JSONResponse({"stan": "niezalogowany",
                         "opis": "slskd działa, ale nie jest zalogowany — "
                                 "sprawdź login i hasło (nazwa mogła być zajęta)"})


@app.post("/api/setup/folder")
def api_setup_folder() -> JSONResponse:
    """Pokaż okno Findera i ustaw wskazany katalog jako bibliotekę."""
    try:
        path = folderpick.choose_folder("Wskaż folder z muzyką")
    except folderpick.PickCancelled:
        return JSONResponse({"ok": False, "cancelled": True})
    except folderpick.PickUnavailable as exc:
        raise HTTPException(400, str(exc))
    path = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(path):
        raise HTTPException(400, "to nie jest katalog")
    set_folder(path)
    config.save({"library_folder": path})
    return JSONResponse({"ok": True, "folder": path,
                         "utworow": len(matcher.audio_files(path))})


@app.get("/api/uchem")
def api_uchem() -> JSONResponse:
    """Utwory, których wyników apka nie jest pewna — do sprawdzenia uchem.

    Tylko z pamięci podręcznej, więc odpowiada natychmiast; szczegóły
    utworu dokładamy z tagów, żeby lista czytała się po ludzku.
    """
    w = uchem.sprawdz(_folder())
    for u in w["utwory"]:
        try:
            row = _track_row(u["file"])
            u["title"], u["artist"] = row.get("title"), row.get("artist")
            u["ext"] = row.get("ext")
        except Exception:  # noqa: BLE001 — brak tagów nie psuje listy
            u["title"], u["artist"] = os.path.basename(u["file"]), ""
    return JSONResponse(w)


@app.get("/api/doktor")
def api_doktor_ostatni() -> JSONResponse:
    return JSONResponse(doktor.ostatni() or {"kiedy": None, "wyniki": []})


@app.post("/api/doktor")
def api_doktor_zbadaj(payload: dict | None = None) -> JSONResponse:
    """Odpal sondy integracji (kilkanaście sekund — sieć)."""
    return JSONResponse(doktor.zbadaj(
        tylko_lokalne=bool((payload or {}).get("tylko_lokalne"))))


@app.get("/api/obserwator")
def api_obserwator() -> JSONResponse:
    """Stan folderu obserwowanego."""
    return JSONResponse(_clean(obserwator.OBSERWATOR.stan()))


@app.post("/api/obserwator")
def api_obserwator_ustaw(payload: dict) -> JSONResponse:
    """Włącz albo wyłącz automatyczną analizę nowych plików."""
    wlaczony = bool((payload or {}).get("wlaczony", True))
    obserwator.OBSERWATOR.wlaczony = wlaczony
    if wlaczony:
        obserwator.OBSERWATOR.start(_folder())
    return JSONResponse(_clean(obserwator.OBSERWATOR.stan()))


@app.post("/api/rekordbox/wczytaj")
async def api_rekordbox_wczytaj(file: UploadFile = File(...)) -> JSONResponse:
    """Wciągnij XML wyeksportowany z rekordboxa i zapamiętaj ręczną pracę."""
    raw = await file.read(64 * 1024 * 1024)
    if not raw.strip():
        raise HTTPException(400, "plik jest pusty")
    tmp = os.path.join(config.STATE_DIR, "_rb_import.xml")
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(tmp, "wb") as fh:
        fh.write(raw)
    try:
        wynik = rbimport.scal(tmp, _folder())
    except ET.ParseError as exc:
        raise HTTPException(400, f"to nie jest poprawny XML rekordboxa: {exc}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return JSONResponse(_clean(wynik))


@app.post("/api/rekordbox/wczytaj-sciezke")
def api_rekordbox_wczytaj_sciezke(payload: dict) -> JSONResponse:
    """To samo, ale ze ścieżki na dysku."""
    sciezka = os.path.expanduser(_field(payload, "path"))
    if not sciezka or not os.path.isfile(sciezka):
        raise HTTPException(404, f"nie ma takiego pliku: {sciezka}")
    try:
        return JSONResponse(_clean(rbimport.scal(sciezka, _folder())))
    except ET.ParseError as exc:
        raise HTTPException(400, f"to nie jest poprawny XML rekordboxa: {exc}")


@app.get("/api/rekordbox/stan")
def api_rekordbox_stan() -> JSONResponse:
    """Ile utworów ma zapamiętaną pracę z rekordboxa i jaką."""
    stan = rbimport._wczytaj_stan()
    utworow, hot, kolorow, ocen = 0, 0, 0, 0
    rozbieznosci = []
    for path, dane in stan.items():
        if not os.path.isfile(path):
            continue
        utworow += 1
        hot += sum(1 for z in (dane.get("znaczniki") or []) if z.get("num", -1) >= 0)
        if dane.get("kolor"):
            kolorow += 1
        if dane.get("ocena"):
            ocen += 1
        # rozbieżności między naszą analizą a rekordboxem — informacyjnie,
        # niczego nie poprawiamy automatycznie
        h = cache.get(path, "harmonic") or {}
        nasze_bpm, ich_bpm = h.get("bpm"), dane.get("bpm")
        if nasze_bpm and ich_bpm and abs(nasze_bpm - ich_bpm) > 1.0:
            podwojone = (abs(nasze_bpm - 2 * ich_bpm) < 2
                         or abs(2 * nasze_bpm - ich_bpm) < 2)
            rozbieznosci.append({
                "file": os.path.basename(path), "pole": "BPM",
                "nasze": round(nasze_bpm, 1), "rekordbox": round(ich_bpm, 1),
                "polowa_lub_podwojenie": podwojone})
        if (h.get("camelot") and dane.get("tonality")
                and h["camelot"] != dane["tonality"]):
            rozbieznosci.append({
                "file": os.path.basename(path), "pole": "tonacja",
                "nasze": h["camelot"], "rekordbox": dane["tonality"],
                "polowa_lub_podwojenie": False})
    return JSONResponse(_clean({
        "utworow": utworow, "hot_cue": hot, "z_kolorem": kolorow,
        "z_ocena": ocen, "rozbieznosci": rozbieznosci[:40],
        "rozbieznosci_razem": len(rozbieznosci),
    }))


@app.post("/api/rekordbox/zapomnij")
def api_rekordbox_zapomnij(payload: dict | None = None) -> JSONResponse:
    """Skasuj zapamiętane dane z rekordboxa."""
    plik = _field(payload or {}, "file")
    ile = rbimport.wyczysc(_safe(plik) if plik else None)
    return JSONResponse({"ok": True, "usunietych": ile})


def _zakres(payload: dict | None) -> tuple[list[str], str]:
    """Pliki do analizy: zaznaczenie, playlista albo cała biblioteka.

    Analiza całej biblioteki rzadko odpowiada na pytanie DJ-a. Pytanie
    brzmi „czy TEN set się klei", a set to garść zaznaczonych utworów
    albo konkretna playlista — nie wszystko, co leży na dysku.
    """
    dane = payload or {}
    pliki = [str(x) for x in (dane.get("files") or [])]
    if pliki:
        sciezki, widziane = [], set()
        for f in pliki:
            p = matcher.resolve_in_library(_folder(), f)
            if p and p not in widziane and p.lower().endswith(matcher.AUDIO_EXT):
                widziane.add(p); sciezki.append(p)
        return sciezki, "zaznaczenie"

    nazwa = _field(dane, "name")
    if nazwa:
        z_manifestu = [f for f in playlists.load_manifest(nazwa)
                       if os.path.isfile(f)]
        if not z_manifestu:
            raise HTTPException(404, f"nie znam playlisty „{nazwa}”")
        return z_manifestu, f"playlista „{nazwa}”"

    return matcher.audio_files(_folder()), "cała biblioteka"


def _struktura_dla(path: str) -> dict:
    """Kształt utworu z pamięci podręcznej; policz, gdy go nie ma."""
    dane = cache.get(path, "energia")
    if dane is not None:
        return dane
    h = cache.get(path, "harmonic")
    if h is None:
        h = asdict(harmonic.analyze(path)); cache.put(path, "harmonic", h)
    c = cache.get(path, "cues")
    if c is None:
        c = asdict(cues.analyze(path, bpm=h.get("bpm"))); cache.put(path, "cues", c)
    kotwica = ((waveform.wczytaj_siatke(path) or {}).get("first_beat_s")
               or c.get("first_beat_s") or 0.0)
    dane = asdict(energia.analizuj(path, bpm=h.get("bpm"), kotwica=kotwica))
    cache.put(path, "energia", dane)
    return dane


@app.post("/api/historia/wczytaj")
async def api_historia_wczytaj(file: UploadFile = File(...),
                               wszystkie: bool = Query(False)) -> JSONResponse:
    """Wciągnij historię grania z XML-a rekordboxa."""
    raw = await file.read(64 * 1024 * 1024)
    if not raw.strip():
        raise HTTPException(400, "plik jest pusty")
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = os.path.join(config.STATE_DIR, "_historia.xml")
    with open(tmp, "wb") as fh:
        fh.write(raw)
    try:
        sesje = historia.wczytaj_sesje(tmp, _folder(), wszystkie_playlisty=wszystkie)
    except ET.ParseError as exc:
        raise HTTPException(400, f"to nie jest poprawny XML rekordboxa: {exc}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if not sesje:
        raise HTTPException(400, "nie znalazłem sesji — rekordbox nazywa je datą "
                                 "albo trzyma w folderze History. Spróbuj opcji "
                                 "„weź wszystkie playlisty”.")
    return JSONResponse(_clean(historia.dopisz(sesje)))


@app.get("/api/historia")
def api_historia() -> JSONResponse:
    """Co grasz, czego nie grasz i co po czym idzie."""
    d = historia.podsumowanie(_folder())
    d["lista_sesji"] = [{"nazwa": s.get("nazwa"), "data": s.get("data"),
                         "utworow": len(s.get("sciezki") or []),
                         "sciezki": list(s.get("sciezki") or []),
                         **_metryki_sesji(s.get("sciezki") or [])}
                        for s in historia.sesje()]
    return JSONResponse(_clean(d))


def _metryki_sesji(sciezki: list[str]) -> dict:
    """Czas, mediana BPM i tonacje sesji z cache analiz (bez liczenia audio)."""
    czas = 0.0
    bpmy: list[float] = []
    tonacje: list[str] = []
    for p in sciezki:
        h = cache.get(p, "harmonic") or {}
        if h.get("bpm"):
            bpmy.append(float(h["bpm"]))
        if h.get("camelot"):
            tonacje.append(h["camelot"])
        try:
            a = MutagenFile(p)
            czas += float(getattr(getattr(a, "info", None), "length", 0) or 0)
        except Exception:  # noqa: BLE001 — plik mógł zniknąć
            pass
    bpmy.sort()
    mediana = bpmy[len(bpmy) // 2] if bpmy else None
    return {"czas_s": round(czas), "bpm_mediana": round(mediana, 1) if mediana else None,
            "tonacje": tonacje, "tonacje_opis": (f"{tonacje[0]} → {tonacje[-1]}" if tonacje else "")}


@app.post("/api/historia/wyczysc")
def api_historia_wyczysc() -> JSONResponse:
    return JSONResponse({"ok": True, "usunietych": historia.wyczysc()})


@app.post("/api/historia/martwe-do-decyzji")
def api_historia_martwe(payload: dict | None = None) -> JSONResponse:
    """Zgłoś nigdy niegrane utwory jako propozycje do przejrzenia.

    Nie usuwamy niczego — martwy balast to podpowiedź, nie wyrok.
    Utwór mógł zostać kupiony na przyszły set albo po prostu czekać
    na swój moment.
    """
    limit = int((payload or {}).get("limit") or 30)
    d = historia.podsumowanie(_folder())
    if d["sesji"] == 0:
        raise HTTPException(400, "najpierw wczytaj historię grania")
    return JSONResponse(_clean({
        "martwych": d["martwy_balast"],
        "propozycje": d["martwe"][:limit],
        "uwaga": "nic nie zostało usunięte — to lista do Twojej oceny",
    }))


@app.get("/api/playlisty")
def api_playlisty() -> JSONResponse:
    """Playlisty utworzone w apce — do wyboru zakresu analizy."""
    return JSONResponse(_clean({"playlisty": playlists.wszystkie()}))


def _tempo_dla(path: str) -> dict:
    """Stabilność tempa z pamięci podręcznej; policz, gdy jej nie ma."""
    dane = cache.get(path, "tempo")
    if dane is not None:
        return dane
    h = cache.get(path, "harmonic")
    if h is None:
        h = asdict(harmonic.analyze(path)); cache.put(path, "harmonic", h)
    dane = asdict(tempo.zbadaj(path, h.get("bpm")))
    cache.put(path, "tempo", dane)
    return dane


@app.post("/api/tempo")
def api_tempo(payload: dict | None = None) -> JSONResponse:
    """Czy siatka utrzyma się do końca — dla zaznaczenia, playlisty albo pliku."""
    plik = _field(payload or {}, "file")
    if plik:
        sciezki, opis = [_safe(plik)], "utwór"
    else:
        sciezki, opis = _zakres(payload)
    if not sciezki:
        raise HTTPException(400, "nie ma czego sprawdzać")
    if len(sciezki) > 300:
        raise HTTPException(400, "za dużo naraz — zaznacz set albo playlistę")

    wyniki, zmiennych, do_poprawy = [], 0, 0
    for path in sciezki:
        t = _tempo_dla(path)
        h = cache.get(path, "harmonic") or {}
        if not t.get("stabilne"):
            zmiennych += 1
        elif t.get("bpm_nietrafione"):
            do_poprawy += 1
        wyniki.append({**t, "file": os.path.basename(path), "path": path,
                       "bpm": h.get("bpm")})
    return JSONResponse(_clean({
        "zakres": opis, "sprawdzonych": len(wyniki),
        "zmiennych": zmiennych, "bpm_do_poprawy": do_poprawy,
        "utwory": wyniki,
    }))


@app.post("/api/tempo/przyjmij")
def api_tempo_przyjmij(payload: dict) -> JSONResponse:
    """Zapisz poprawione BPM jako ręczną korektę siatki.

    Dotyczy tylko utworów o STAŁYM tempie, gdzie nasze oszacowanie było
    lekko nietrafione. Przy tempie falującym żadna pojedyncza liczba nie
    pomoże, więc odmawiamy zamiast udawać, że naprawiliśmy.
    """
    path = _safe(_field(payload, "file"))
    t = _tempo_dla(path)
    if not t.get("bpm_nietrafione") or not t.get("bpm_poprawione"):
        raise HTTPException(400, "dla tego utworu nie ma poprawki BPM "
                                 "— tempo jest stałe albo faluje")
    c = cache.get(path, "cues") or {}
    reczna = waveform.wczytaj_siatke(path) or {}
    kotwica = reczna.get("first_beat_s") or c.get("first_beat_s") or 0.0
    battito = reczna.get("battito") if reczna else c.get("battito")
    wpis = waveform.zapisz_siatke(path, kotwica, t["bpm_poprawione"], battito or 1)
    return JSONResponse({"ok": True, **wpis})


@app.post("/api/energia")
def api_energia(payload: dict | None = None) -> JSONResponse:
    """Energia i struktura — dla zaznaczenia, playlisty albo biblioteki.

    Kolejność liczy się: przy playliście i zaznaczeniu układamy set
    harmonicznie i oceniamy łuk energii w tej właśnie kolejności.
    """
    sciezki, opis = _zakres(payload)
    if not sciezki:
        raise HTTPException(400, "nie ma czego analizować")
    if len(sciezki) > 400:
        raise HTTPException(400, f"{len(sciezki)} utworów to za dużo naraz — "
                                 "zaznacz set albo wskaż playlistę")

    kolejnosc = sciezki
    if len(sciezki) > 1:
        # ta sama kolejność, którą dostaniesz przy eksporcie
        items = _harmonic_for(sciezki)
        kolejnosc = [p for p, _ta, _n in harmonic.order_set(items)]

    utwory = []
    for path in kolejnosc:
        s = _struktura_dla(path)
        h = cache.get(path, "harmonic") or {}
        artysta, tytul = _tags(path)
        utwory.append({**s, "file": os.path.basename(path), "path": path,
                       "artist": artysta, "title": tytul,
                       "bpm": h.get("bpm"), "camelot": h.get("camelot")})

    luk = energia.luk_setu(utwory)
    return JSONResponse(_clean({
        "zakres": opis, "utworow": len(utwory),
        "utwory": utwory, **luk,
    }))


@app.post("/api/statystyki")
def api_statystyki_zakres(payload: dict | None = None) -> JSONResponse:
    """Rozkład i luki — dla zaznaczenia, playlisty albo biblioteki."""
    sciezki, opis = _zakres(payload)
    utwory = []
    for path in sciezki:
        h = cache.get(path, "harmonic")
        if not h:
            continue
        artysta, tytul = _tags(path)
        utwory.append({"bpm": h.get("bpm"), "camelot": h.get("camelot"),
                       "key": h.get("key"), "file": os.path.basename(path),
                       "artist": artysta, "title": tytul})
    d = statystyki.policz(utwory)
    d.update(_glosnosc_zbiorcza(sciezki))
    d["bez_analizy"] = len(sciezki) - d["przeanalizowanych"]
    d["zakres"] = opis
    return JSONResponse(_clean(d))


def _glosnosc_zbiorcza(sciezki: list[str]) -> dict:
    """Średnia (i skrajne) zintegrowana głośność z cache loudness — dashboard
    pokazuje ją w kaflu ŚREDNIA GŁOŚNOŚĆ; wcześniej stało tam „—"."""
    wartosci = []
    for p in sciezki:
        l = cache.get(p, "loudness")
        v = l.get("integrated_lufs") if l else None
        if isinstance(v, (int, float)):
            wartosci.append(float(v))
    if not wartosci:
        return {"srednia_lufs": None, "lufs_min": None, "lufs_max": None, "z_glosnoscia": 0}
    return {"srednia_lufs": round(sum(wartosci) / len(wartosci), 1),
            "lufs_min": round(min(wartosci), 1), "lufs_max": round(max(wartosci), 1),
            "z_glosnoscia": len(wartosci)}


@app.get("/api/statystyki")
def api_statystyki() -> JSONResponse:
    """Rozkład BPM i tonacji plus luki w możliwych przejściach."""
    utwory = []
    for path in matcher.audio_files(_folder()):
        h = cache.get(path, "harmonic")
        if not h:
            continue
        artysta, tytul = _tags(path)
        utwory.append({"bpm": h.get("bpm"), "camelot": h.get("camelot"),
                       "key": h.get("key"), "file": os.path.basename(path),
                       "artist": artysta, "title": tytul})
    d = statystyki.policz(utwory)
    d["bez_analizy"] = len(matcher.audio_files(_folder())) - d["przeanalizowanych"]
    d.update(_glosnosc_zbiorcza(matcher.audio_files(_folder())))
    return JSONResponse(_clean(d))


@app.get("/api/decyzje")
def api_decyzje(wszystkie: bool = Query(False)) -> JSONResponse:
    """Propozycje zmian czekające na zatwierdzenie."""
    lista = decyzje.wszystkie() if wszystkie else decyzje.czekajace()
    return JSONResponse(_clean({"count": len(lista), "decyzje": lista}))


@app.post("/api/tracks/pokaz")
def api_tracks_pokaz(payload: dict) -> JSONResponse:
    """Pokaż plik w Finderze (zaznaczony w swoim katalogu)."""
    path = _safe(_field(payload, "file"))
    if sys.platform != "darwin":
        return JSONResponse({"ok": False, "path": path,
                             "message": "podgląd w Finderze działa tylko na macOS"})
    try:
        subprocess.run(["open", "-R", path], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(500, f"nie udało się otworzyć Findera: {exc}")
    return JSONResponse({"ok": True, "path": path})


@app.post("/api/tracks/dodaj")
async def api_tracks_dodaj(file: UploadFile = File(...)) -> JSONResponse:
    """Dodaj utwór do biblioteki (wgrany z komputera)."""
    nazwa = os.path.basename(file.filename or "")
    if not nazwa.lower().endswith(matcher.AUDIO_EXT):
        raise HTTPException(400, f"to nie jest plik audio: {nazwa or '(bez nazwy)'}")
    cel = os.path.join(_folder(), nazwa)
    stem, ext = os.path.splitext(cel)
    n = 2
    while os.path.exists(cel):
        cel = f"{stem} ({n}){ext}"
        n += 1
    zapisano = 0
    try:
        with open(cel, "wb") as fh:
            while True:
                kawalek = await file.read(1024 * 1024)
                if not kawalek:
                    break
                zapisano += len(kawalek)
                fh.write(kawalek)
    except OSError as exc:
        if os.path.exists(cel):
            os.remove(cel)
        raise HTTPException(500, f"nie udało się zapisać: {exc}")
    if not zapisano:
        os.remove(cel)
        raise HTTPException(400, "plik jest pusty")
    return JSONResponse({"ok": True, "file": os.path.basename(cel),
                         "mb": round(zapisano / 1_000_000, 1)})


@app.post("/api/tracks/dodaj-sciezke")
def api_tracks_dodaj_sciezke(payload: dict) -> JSONResponse:
    """Dodaj utwór wskazany ścieżką — plik ALBO cały folder."""
    zrodlo = os.path.abspath(os.path.expanduser(_field(payload, "path")))
    if not os.path.exists(zrodlo):
        raise HTTPException(404, f"nie ma takiej ścieżki: {zrodlo}")
    pliki = (matcher.audio_files(zrodlo) if os.path.isdir(zrodlo)
             else ([zrodlo] if zrodlo.lower().endswith(matcher.AUDIO_EXT) else []))
    if not pliki:
        raise HTTPException(400, "nie znalazłem tam plików audio")
    dodane = []
    for src in pliki:
        cel = os.path.join(_folder(), os.path.basename(src))
        if os.path.abspath(src) == os.path.abspath(cel):
            continue                       # już jest w bibliotece
        stem, ext = os.path.splitext(cel)
        n = 2
        while os.path.exists(cel):
            cel = f"{stem} ({n}){ext}"
            n += 1
        try:
            playlists.fast_copy(src, cel)
            dodane.append(os.path.basename(cel))
        except OSError:
            continue
    return JSONResponse({"ok": bool(dodane), "dodane": dodane,
                         "count": len(dodane)})


@app.post("/api/tracks/usun")
def api_tracks_usun(payload: dict) -> JSONResponse:
    """Usuń utwór z biblioteki — do kosza, nie na zawsze.

    Twarde kasowanie odpada: pomyłka w bibliotece DJ-a jest nieodwracalna,
    a plik w koszu kosztuje tylko miejsce na dysku.
    """
    path = _safe(_field(payload, "file"))
    katalog = os.path.join(os.path.dirname(path), decyzje.KOSZ)
    os.makedirs(katalog, exist_ok=True)
    cel = os.path.join(katalog, os.path.basename(path))
    stem, ext = os.path.splitext(cel)
    n = 2
    while os.path.exists(cel):
        cel = f"{stem} ({n}){ext}"
        n += 1
    try:
        shutil.move(path, cel)
    except OSError as exc:
        raise HTTPException(500, f"nie udało się przenieść do kosza: {exc}")
    return JSONResponse({"ok": True, "w_koszu": cel,
                         "nazwa": os.path.basename(path)})


@app.post("/api/tracks/przywroc")
def api_tracks_przywroc(payload: dict) -> JSONResponse:
    """Cofnij usunięcie — przywróć plik z kosza."""
    zrodlo = os.path.abspath(_field(payload, "w_koszu"))
    if os.path.commonpath([zrodlo, _folder()]) != _folder():
        raise HTTPException(400, "ścieżka poza biblioteką")
    if not os.path.isfile(zrodlo):
        raise HTTPException(404, "nie ma takiego pliku w koszu")
    cel = os.path.join(os.path.dirname(os.path.dirname(zrodlo)),
                       os.path.basename(zrodlo))
    if os.path.exists(cel):
        raise HTTPException(409, "plik o tej nazwie już wrócił na miejsce")
    shutil.move(zrodlo, cel)
    return JSONResponse({"ok": True, "file": os.path.basename(cel)})


@app.post("/api/decyzje/skanuj")
def api_decyzje_skanuj() -> JSONResponse:
    """Poszukaj kopii tego samego utworu. NIC nie zmienia na dysku."""
    nowe = decyzje.skanuj(_folder())
    czeka = decyzje.czekajace()
    return JSONResponse(_clean({"nowych": len(nowe), "czeka": len(czeka),
                                "decyzje": czeka}))


@app.post("/api/pobrania/sprawdz")
def api_pobrania_sprawdz() -> JSONResponse:
    """Zweryfikuj świeżo pobrane pliki — czy to na pewno zamówione utwory."""
    zadania = dlqueue.QUEUE.state().get("jobs") or []
    nowe = decyzje.sprawdz_pobrane(_folder(), zadania)
    return JSONResponse(_clean({"sprawdzonych": len(zadania),
                                "podejrzanych": len(nowe),
                                "decyzje": nowe}))


@app.post("/api/decyzje/{ident}/zatwierdz")
def api_decyzje_zatwierdz(ident: str) -> JSONResponse:
    """Przenieś odrzucone kopie do kosza — operacja odwracalna."""
    try:
        d = decyzje.zatwierdz(ident)
    except KeyError:
        raise HTTPException(404, "nie ma takiej decyzji")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(_clean({"ok": True, "decyzja": d,
                                "w_koszu": len(d.get("w_koszu", []))}))


@app.post("/api/decyzje/{ident}/odrzuc")
def api_decyzje_odrzuc(ident: str) -> JSONResponse:
    try:
        d = decyzje.odrzuc(ident)
    except KeyError:
        raise HTTPException(404, "nie ma takiej decyzji")
    return JSONResponse(_clean({"ok": True, "decyzja": d}))


@app.post("/api/decyzje/{ident}/cofnij")
def api_decyzje_cofnij(ident: str) -> JSONResponse:
    """Przywróć pliki z kosza — decyzja wraca do kolejki."""
    try:
        d = decyzje.cofnij(ident)
    except KeyError:
        raise HTTPException(404, "nie ma takiej decyzji")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(_clean({"ok": True, "decyzja": d}))


@app.get("/api/waveform")
def api_waveform(file: str = Query(...)) -> JSONResponse:
    """Przebieg fali plus siatka beatów i punkty cue — do podglądu i korekty."""
    path = _safe(file)
    dane = cache.get(path, "waveform")
    if dane is None:
        dane = waveform.oblicz(path)
        if dane["punkty"]:
            cache.put(path, "waveform", dane)

    h = cache.get(path, "harmonic")
    if h is None:
        h = asdict(harmonic.analyze(path)); cache.put(path, "harmonic", h)
    c = cache.get(path, "cues")
    if c is None:
        c = asdict(cues.analyze(path, bpm=h.get("bpm"))); cache.put(path, "cues", c)

    reczna = waveform.wczytaj_siatke(path)
    # BPM siatki: ręczne > dostrojone do stopy (gdy pewne) > z analizy tempa
    bpm = ((reczna or {}).get("bpm")
           or (c.get("bpm_siatki")
               if (c.get("pewnosc_siatki") or 0) >= siatka.PROG_PEWNOSCI else None)
           or h.get("bpm"))
    pierwszy = ((reczna or {}).get("first_beat_s")
                if reczna else c.get("first_beat_s"))
    battito = ((reczna or {}).get("battito") or 1) if reczna else (c.get("battito") or 1)
    return JSONResponse(_clean({
        **dane,
        "file": os.path.basename(path),
        "bpm": bpm,
        "first_beat_s": pierwszy,
        "battito": battito,
        "pewnosc_siatki": c.get("pewnosc_siatki"),
        "pewnosc_taktu": c.get("pewnosc_taktu"),
        "wyliczony_first_beat_s": c.get("first_beat_s"),
        "reczna_korekta": bool(reczna),
        "cues": {"intro": c.get("intro_end_s"), "drop": c.get("drop_s"),
                 "outro": c.get("outro_start_s")},
    }))


@app.post("/api/siatka")
def api_siatka(payload: dict) -> JSONResponse:
    """Zapisz ręcznie poprawioną siatkę beatów dla utworu."""
    path = _safe(_field(payload, "file"))
    dane = payload or {}
    if dane.get("reset"):
        waveform.skasuj_siatke(path)
        c = cache.get(path, "cues") or {}
        return JSONResponse({"ok": True, "reczna_korekta": False,
                             "first_beat_s": c.get("first_beat_s")})
    try:
        first_beat = float(dane.get("first_beat_s"))
    except (TypeError, ValueError):
        raise HTTPException(400, "podaj first_beat_s w sekundach")
    if not (0 <= first_beat < 3600):
        raise HTTPException(400, "kotwica poza sensownym zakresem")
    bpm = dane.get("bpm")
    try:
        bpm = float(bpm) if bpm else None
    except (TypeError, ValueError):
        bpm = None
    if bpm is not None and not (40 <= bpm <= 250):
        raise HTTPException(400, "BPM poza sensownym zakresem")
    try:
        battito = int(dane.get("battito") or 1)
    except (TypeError, ValueError):
        battito = 1
    if not 1 <= battito <= 4:
        raise HTTPException(400, "numer bitu kotwicy musi być od 1 do 4")
    wpis = waveform.zapisz_siatke(path, first_beat, bpm, battito)
    return JSONResponse({"ok": True, "reczna_korekta": True, **wpis})


@app.post("/api/playlist/review")
def api_playlist_review(payload: dict) -> JSONResponse:
    """Bramka jakości: sprawdź KAŻDY utwór playlisty i wskaż problemy.

    Kontrolujemy cztery rzeczy, o które prosi DJ przed graniem:
    nazwa/tagi, okładka, jakość dźwięku (fałszywy lossless) oraz
    integralność pliku (przeskoki i ucięcia). Do tego oznaczamy utwory,
    które nie pasują tempem do reszty setu.
    """
    name = _field(payload, "name") or "set"
    files = [str(x) for x in ((payload or {}).get("files") or [])]
    if not files:
        files = playlists.load_manifest(name)

    # nazwa pliku zamiast ścieżki: szukamy w folderze playlisty, potem w bibliotece
    resolved, pominiete = [], []
    for f in files:
        if os.path.isfile(f):
            if not _within_allowed(f):
                raise HTTPException(400, f"ścieżka poza dozwolonym katalogiem: {f}")
            resolved.append(f); continue
        base = os.path.basename(f)
        cand = os.path.join(playlists.folder_for(name), base)
        if not os.path.isfile(cand):
            cand = matcher.resolve_in_library(_folder(), base)
        if cand:
            resolved.append(cand)
        else:
            pominiete.append(base)
    files = resolved
    if not files:
        raise HTTPException(400, "playlista jest pusta")

    rows, bpms = [], []
    for path in files:
        h = cache.get(path, "harmonic")
        if h is None:
            h = asdict(harmonic.analyze(path)); cache.put(path, "harmonic", h)
        q = cache.get(path, "quality")
        if q is None:
            rep = quality.analyze(path)
            q = {"grade": rep.grade, "verdict": rep.verdict}
            cache.put(path, "quality", q)
        ig = cache.get(path, "integrity")
        if ig is None:
            ch = pipeline.integrity(path)
            ig = {"ok": ch.passed, "detail": ch.detail}
            cache.put(path, "integrity", ig)

        artist, title = _tags(path)
        problems = []
        if not artist or not title:
            problems.append({"typ": "tagi", "opis": "brak artysty lub tytułu",
                             "naprawialne": True})
        elif tagfix.looks_mojibake(artist) or tagfix.looks_mojibake(title):
            problems.append({"typ": "tagi", "opis": "uszkodzone znaki w tagach",
                             "naprawialne": True})
        if covers.embedded_art(path) is None:
            problems.append({"typ": "okladka", "opis": "brak okładki",
                             "naprawialne": True})
        if q.get("grade") == "bad":
            problems.append({"typ": "jakosc", "opis": q.get("verdict", "słabe źródło"),
                             "naprawialne": False})
        if not ig.get("ok"):
            problems.append({"typ": "integralnosc",
                             "opis": ig.get("detail", "plik uszkodzony"),
                             "naprawialne": False})

        # Tempo falujące psuje siatkę w drugiej połowie utworu — o tym DJ
        # musi wiedzieć PRZED graniem. Samo doprecyzowanie BPM o ułamek
        # procenta CELOWO tu nie trafia: to poprawka, nie usterka, a gdyby
        # migało przy każdym utworze, przestałbyś czytać tę listę. Widać
        # je w zakładce tempa i można je przyjąć jednym kliknięciem.
        t = _tempo_dla(path)
        if not t.get("stabilne") and t.get("opis") and "za mało" not in t["opis"]:
            problems.append({"typ": "tempo-zmienne", "opis": t["opis"],
                             "naprawialne": False})

        bpm = h.get("bpm") or 0
        if bpm:
            bpms.append(bpm)
        info = MutagenFile(path)
        ext = os.path.splitext(path)[1].lower()
        rows.append({
            "path": path, "file": os.path.basename(path),
            "artist": artist or "?", "title": title or os.path.basename(path),
            "bpm": bpm, "camelot": h.get("camelot"), "key": h.get("key"),
            "quality": q.get("grade"), "quality_note": q.get("verdict"),
            "has_cover": covers.embedded_art(path) is not None,
            "integrity_ok": bool(ig.get("ok")),
            # potrzebne, by ocenić, czy znaleziony plik jest LEPSZY od tego
            "format": ext.lstrip(".").upper(),
            "lossless": ext in LOSSLESS_EXT,
            "bitrate": (int(getattr(info.info, "bitrate", 0) or 0) // 1000
                        if info else 0),
            "duration": round(getattr(info.info, "length", 0) or 0) if info else None,
            "problems": problems,
        })

    # utwory odstające tempem — mediana setu jako punkt odniesienia
    if bpms:
        srt = sorted(bpms)
        median = srt[len(srt) // 2]
        for r in rows:
            if not r["bpm"]:
                continue
            odchylenie = abs(r["bpm"] - median) / median
            r["bpm_odchylenie"] = round(100 * odchylenie)
            if odchylenie > 0.12:      # poza zakresem pitcha CDJ (~±6%) z zapasem
                r["problems"].append({
                    "typ": "tempo",
                    "opis": f"{r['bpm']:.0f} BPM przy medianie setu {median:.0f} "
                            f"— odstaje o {round(100*odchylenie)}%",
                    "naprawialne": False})

    # ten sam utwór dwa razy w secie — łatwo o to, gdy biblioteka ma
    # kilka kopii tego samego kawałka z różnych źródeł
    grupy: dict[str, list[dict]] = {}
    for r in rows:
        klucz = " ".join(matcher.normalize(r["artist"])
                         + matcher.normalize(slskd_client.core_title(r["title"])))
        if klucz.strip():
            grupy.setdefault(klucz, []).append(r)
    for kopie in grupy.values():
        if len(kopie) < 2:
            continue
        for r in kopie:
            inne = [x["file"] for x in kopie if x is not r]
            r["problems"].append({
                "typ": "duplikat",
                "opis": f"ten sam utwór jest w secie {len(kopie)} razy "
                        f"(także jako: {', '.join(inne)[:70]})",
                "naprawialne": False})

    problemowe = sum(1 for r in rows if r["problems"])
    return JSONResponse(_clean({
        "name": name, "count": len(rows), "z_problemami": problemowe,
        "pominiete": pominiete,
        "mediana_bpm": (sorted(bpms)[len(bpms)//2] if bpms else None),
        "tracks": rows,
    }))


@app.post("/api/playlist/fix")
def api_playlist_fix(payload: dict) -> JSONResponse:
    """Napraw to, co da się naprawić automatycznie: tagi i okładkę.

    Zwraca też to, czego naprawić się NIE udało — DJ ma wiedzieć, że
    okładki nadal brakuje, zamiast zobaczyć ptaszek i miłe złudzenie.
    """
    path = os.path.abspath(_field(payload, "path"))
    if not _within_allowed(path):
        raise HTTPException(400, "ścieżka poza dozwolonym katalogiem")
    if not os.path.isfile(path):
        raise HTTPException(404, "nie ma takiego pliku")

    zrobione: list[str] = []
    nieudane: list[str] = []
    if tagfix.fix_file(path, dry_run=False):
        zrobione.append("naprawiono tagi")

    artist, title = _tags(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    z_nazwy = tagfix.name_candidates(stem)

    # brak tagów — uzupełniamy je z OCZYSZCZONEJ nazwy pliku, bo to ona
    # trafia potem do rekordboxa jako artysta i tytuł
    if not (artist and title) and z_nazwy:
        artist, title = z_nazwy[0]
        tagger.tag_file(path, artist, title, covers.embedded_art(path))
        zrobione.append(f"uzupełniono nazwę: {artist} — {title}"[:60])

    if covers.embedded_art(path) is None:
        proby: list[tuple[str, str]] = []
        for a, t in ((artist, title), *z_nazwy):
            a, t = (a or "").strip(), (t or "").strip()
            if not (a and t) or (a, t) in proby:
                continue
            proby.append((a, t))
            goly = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", t).strip()
            if goly and goly != t and (a, goly) not in proby:
                proby.append((a, goly))
        hit = None
        for a, t in proby:
            hit = covers.from_itunes(a, t)
            if hit:
                artist, title = a, t
                break
        if hit:
            tagger.tag_file(path, artist, title, hit.data)
            zrobione.append(f"dodano okładkę ({hit.description[:40]})")
        else:
            nieudane.append("nie znaleziono okładki w sieci — wgraj ją ręcznie")

    if not zrobione:
        return JSONResponse({"ok": False,
                             "message": nieudane[0] if nieudane
                             else "nie było czego naprawić automatycznie"})
    return JSONResponse({"ok": True, "message": " · ".join(zrobione),
                         "nieudane": nieudane})


@app.post("/api/playlist/export")
def api_playlist_export(payload: dict) -> JSONResponse:
    """Zbuduj i podepnij do rekordboxa WYŁĄCZNIE tę playlistę."""
    name = _field(payload, "name") or "set"
    files = [str(x) for x in (payload or {}).get("files") or []]
    if not files:
        files = playlists.load_manifest(name)
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise HTTPException(400, "playlista jest pusta — nie ma czego eksportować")

    items = _harmonic_for(files)
    ordered = harmonic.order_set(items)
    tracks = dj_export.wzbogac_o_siatke(
        [dj_export.track_from_file(path) for path, _ta, _n in ordered])
    out = os.path.join(playlists.folder_for(name), f"{playlists.safe_name(name)}.xml")
    dj_export.to_rekordbox_xml(tracks, playlists.safe_name(name), out)
    res = rekordbox.install(out)
    return JSONResponse({
        "ok": res.ok, "message": res.message, "path": out,
        "count": len(tracks), "playlist": playlists.safe_name(name),
        "order": [{"pos": i + 1, "file": os.path.basename(p),
                   "camelot": ta.camelot, "bpm": ta.bpm, "note": n}
                  for i, (p, ta, n) in enumerate(ordered)],
    })


@app.get("/api/rekordbox")
def api_rekordbox_status() -> JSONResponse:
    """Stan integracji: czy rekordbox jest, czy działa, co ma podpięte."""
    settings = rekordbox.settings_path()
    return JSONResponse({
        "installed": settings is not None,
        "running": rekordbox.is_running(),
        "linked": rekordbox.imported_library() or "",
    })


@app.post("/api/rekordbox/install")
def api_rekordbox_install(payload: dict | None = None) -> JSONResponse:
    """Zbuduj playlistę w kolejności setu i podepnij ją do rekordboxa."""
    name = _field(payload, "name") or "selekta-set"
    tracks = _in_set_order(dj_export.collect(_folder()))
    if not tracks:
        raise HTTPException(400, "biblioteka jest pusta — nie ma czego wysłać")
    xml_path = dj_export.to_rekordbox_xml(
        tracks, name, os.path.join(_folder(), f"{name}.xml"))
    res = rekordbox.install(xml_path)
    return JSONResponse({
        "ok": res.ok, "message": res.message, "path": xml_path,
        "count": len(tracks), "playlist": name,
        "previous": res.previous, "running": rekordbox.is_running(),
    })


@app.post("/api/rekordbox/restore")
def api_rekordbox_restore() -> JSONResponse:
    res = rekordbox.restore()
    return JSONResponse({"ok": res.ok, "message": res.message})


@app.post("/api/usb")
def api_usb(payload: dict) -> JSONResponse:
    dest = os.path.expanduser(_field(payload, "dest"))
    if not dest:
        raise HTTPException(400, "podaj folder docelowy albo pendrive")
    conv = (payload or {}).get("convert", "aiff")
    rep = usb.prepare(_folder(), dest, convert_wav=(None if conv == "keep" else conv))
    return JSONResponse({"copied": len(rep.copied), "converted": len(rep.converted),
                         "skipped": len(rep.skipped),
                         "mb": round(rep.total_bytes / 1_000_000)})


# --------------------------------------------------------------------------
# radar / lista życzeń / Soulseek
# --------------------------------------------------------------------------

@app.get("/api/radar")
def api_radar() -> JSONResponse:
    """Zapamiętane znaleziska — bez sieci, natychmiast po wejściu."""
    d = radar.wyniki()
    d["total_artists"] = len(radar.artists_from_library(_folder()))
    return JSONResponse(_clean(d))


@app.post("/api/radar/sprawdz")
def api_radar_sprawdz(payload: dict | None = None) -> JSONResponse:
    """Sprawdź porcję artystów w Beatporcie i Bandcampie (sieć, sekundy–minuty)."""
    p = payload or {}
    limit = max(1, min(int(p.get("limit") or 10), 200))
    offset = max(0, int(p.get("offset") or 0))
    try:
        return JSONResponse(_clean(radar.sprawdz(_folder(), limit=limit, offset=offset)))
    except Exception as exc:  # noqa: BLE001 — sklepy nie mogą wywalić UI
        raise HTTPException(502, f"radar nie dał rady: {exc}")


@app.get("/api/cache")
def api_cache() -> JSONResponse:
    return JSONResponse(cache.stats())


@app.post("/api/cache/wyczysc")
def api_cache_wyczysc(payload: dict | None = None) -> JSONResponse:
    """Skasuj cache analiz (cały albo jeden rodzaj) — utwory policzą się od nowa."""
    kind = (payload or {}).get("kind") or None
    if kind is not None and not re.fullmatch(r"[a-z_]{1,32}", str(kind)):
        raise HTTPException(400, "nieznany rodzaj cache")
    usuniete = cache.clear(kind)
    return JSONResponse({"removed": usuniete, **cache.stats()})


@app.get("/api/wishlist")
def api_wishlist() -> JSONResponse:
    return JSONResponse({"items": wishlist.items()})


@app.post("/api/wishlist")
def api_wishlist_add(payload: dict) -> JSONResponse:
    a = _field(payload, "artist"); t = _field(payload, "title")
    if a or t:
        wishlist.add(a.strip(), t.strip())
    return JSONResponse({"items": wishlist.items()})


@app.get("/api/slskd")
def api_slskd() -> JSONResponse:
    return JSONResponse({"available": SlskdClient().available()})


@app.get("/api/transfers")
def api_transfers() -> JSONResponse:
    """Stan pobrań ze slskd — żeby zawsze było widać, co się dzieje."""
    client = SlskdClient()
    if not client.available():
        return JSONResponse({"available": False, "items": [], "counts": {}})
    items = client.downloads()
    counts = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return JSONResponse({"available": True, "items": items, "counts": counts})


@app.post("/api/transfers/cancel")
def api_transfers_cancel(payload: dict) -> JSONResponse:
    client = SlskdClient()
    user, fid = _field(payload, "user"), _field(payload, "id")
    if not (user and fid):
        raise HTTPException(400, "brak wskazania pobrania")
    try:
        client.cancel_download(user, fid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"nie udało się anulować: {exc}")
    return JSONResponse({"ok": True})


@app.post("/api/search")
def api_search(payload: dict) -> JSONResponse:
    """Szukaj utworu na Soulseeku i ZWRÓĆ listę kandydatów do wyboru.

    Nic nie pobiera — decyzję podejmuje użytkownik na podstawie danych
    (czas, format, bitrate, rozmiar, dopasowanie tytułu i artysty).
    """
    client = SlskdClient()
    if not client.available():
        raise HTTPException(503, "slskd niepodłączony — sprawdź Ustawienia")
    artist, title = _field(payload, "artist"), _field(payload, "title")
    if not (artist or title):
        raise HTTPException(400, "podaj artystę albo tytuł")
    duration = (payload or {}).get("duration")
    try:
        candidates = client.search_candidates(artist, title, duration)
    except Exception as exc:  # noqa: BLE001 — sieć/slskd nie mogą wywalić UI
        raise HTTPException(502, f"wyszukiwanie nie powiodło się: {exc}")
    return JSONResponse({
        "artist": artist, "title": title, "duration": duration,
        "count": len(candidates), "candidates": candidates,
        "searched_as": slskd_primary(artist),
    })


@app.post("/api/download")
def api_download(payload: dict) -> JSONResponse:
    """Pobierz KONKRETNY plik wskazany przez użytkownika.

    Bez wskazania (brak `path`) zachowuje się jak dawniej: bierze najlepiej
    dopasowany wynik — przydatne dla masowych operacji.
    """
    client = SlskdClient()
    if not client.available():
        raise HTTPException(503, "slskd niepodłączony — sprawdź Ustawienia")
    artist, title = _field(payload, "artist"), _field(payload, "title")
    path, user = _field(payload, "path"), _field(payload, "user")

    if path and user:                      # wybór użytkownika
        hit = SearchHit(username=user, filename=path,
                        size=int((payload or {}).get("size") or 0),
                        bitrate=None, length_s=None,
                        is_lossless=path.lower().endswith((".flac", ".wav", ".aiff")),
                        free_slot=True)
    else:                                  # automat
        hits = client.search_track(artist, title, (payload or {}).get("duration"))
        if not hits:
            wishlist.add(artist, title)
            raise HTTPException(404, "brak wyników na Soulseeku — dodano do życzeń")
        hit = hits[0]
    try:
        client.download(hit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"nie udało się zlecić pobierania: {exc}")
    return JSONResponse({"queued": os.path.basename(hit.filename.replace("\\", "/"))})


def serve(folder: str, host: str = "127.0.0.1", port: int = 8756) -> None:
    import uvicorn
    set_folder(folder)
    # Kolejka pobierania przeżywa zamknięcie apki: wklejasz playlistę,
    # zamykasz laptopa, po ponownym uruchomieniu ściąganie idzie dalej.
    wznowione = dlqueue.QUEUE.wczytaj()
    # nowe pliki mają analizować się same — po pobraniu w tle nie ma sensu
    # wymagać, żeby użytkownik wracał i klikał „Analizuj wszystko"
    obserwator.OBSERWATOR.start(folder)
    print(f"selekta — dashboard: http://{host}:{port}  (folder: {_folder()})")
    if wznowione:
        print(f"  wznawiam pobieranie: {wznowione} utworów czeka w kolejce")
    uvicorn.run(app, host=host, port=port, log_level="warning")
