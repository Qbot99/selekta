"""selekta — playlista (Spotify / Apple Music / YouTube / Tidal / SoundCloud /
1001Tracklists / tekst) → czysta, zweryfikowana biblioteka DJ-ska.

Komendy:
  organize   dopasuj pliki do playlisty, otaguj, dodaj okładki, zmień nazwy
  verify     raport jakości audio (detektor fałszywych FLAC-ów)
  check      pełna weryfikacja pobrań: integralność + tożsamość + jakość
  match      weryfikacja przez odsłuch: plik vs próbka (Spotify, a bez niej iTunes)
  covers     audyt okładek; --fill dociąga brakujące z iTunes
  icons      pokaż okładki FLAC/WAV w Finderze (macOS)
  analyze    wykryj BPM i tonację, zapisz tagi; --order = kolejność harmoniczna
  health     dashboard biblioteki: duplikaty, braki, uszkodzenia, jakość
  export     eksport do rekordbox (XML), Serato (.crate) lub M3U8
  usb        przygotuj płaski folder pod CDJ (nazwy FAT32, WAV→AIFF/FLAC)
  radar      nowe wydania Twoich artystów na Beatport/Bandcamp
  wishlist   lista życzeń + cykliczne szukanie na Soulseeku
  hunt       szukaj brakujących utworów na Soulseeku + linki zakupowe
  loudness   głośność LUFS + tagi ReplayGain (spójny poziom setu)
  cues       wykryj intro/outro/drop/pierwsze uderzenie
  tagfix     napraw uszkodzone tagi (mojibake)
  dedupe     znajdź duplikaty i przenieś słabsze kopie do kosza selekty
  uchem      co warto sprawdzić uchem, zanim trafi do setu
  doctor     sprawdź integracje (Spotify, Beatport, iTunes…) i narzędzia
  serve      uruchom dashboard w przeglądarce
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict

from . import (
    cache,
    doktor,
    uchem,
    covers,
    cues,
    dedupe,
    dj_export,
    harmonic,
    finder_icons,
    health,
    importers,
    keysource,
    loudness,
    matcher,
    pipeline,
    poszukiwacz,
    radar,
    spotify,
    stores,
    tagfix,
    usb,
    verify_match,
    wishlist,
)
from .quality import analyze as analyze_quality
from .slskd_client import SlskdClient
from .tagger import rename_file, tag_file

GRADE_ICON = {"ok": "✅", "warn": "⚠️", "bad": "❌"}
VERDICT_ICON = {"match": "✅", "uncertain": "⚠️", "mismatch": "❌"}


def _load_tracks(source: str) -> list[spotify.Track]:
    """Accept a URL from any supported source, a file of links, or pasted text."""
    text = open(source).read() if os.path.exists(source) else source
    tracks, origin = importers.resolve_any(text)
    if not tracks:
        sys.exit("nie znalazłem żadnych utworów w podanym źródle")
    total = getattr(tracks, "zrodlo_total", None)
    z = f" (z {total} w źródle)" if total and total > len(tracks) else ""
    print(f"źródło: {origin} — {len(tracks)} utworów{z}")
    for uwaga in getattr(tracks, "uwagi", []) or []:
        print(f"⚠️ {uwaga}")
    print()
    return tracks


def _audio_paths(folder: str) -> list[str]:
    files = matcher.audio_files(folder)
    if not files:
        raise FileNotFoundError(
            f"folder nie zawiera plików audio: {folder}")
    return files


# --------------------------------------------------------------------------

def cmd_organize(args) -> None:
    from . import tagger
    if getattr(args, "cofnij", False):
        wynik = tagger.cofnij_porzadkowanie()
        if not wynik:
            print("nie ma czego cofać")
        for w in wynik:
            znak = "↺" if w.get("cofniete") else "⚠"
            print(f"{znak} {os.path.basename(w['do'])} → {os.path.basename(w['z'])}"
                  + ("" if w.get("cofniete") else f"  ({w.get('powod', '')})"))
        return
    if not args.source:
        sys.exit("podaj playlistę (link, plik albo tekst) albo --cofnij")
    tracks = _load_tracks(args.source)
    # Przemianowujemy i tagujemy WYŁĄCZNIE ten sam utwór w tej samej wersji.
    # Dawniej best_match brał najwyższy wynik ≥ 0,6: „✓ Frozen ← Like a
    # Prayer", a --apply przepisałby cudzy plik na „Madonna - Frozen".
    index = matcher.library_index(args.folder)
    matched, missing, inne = [], [], {}
    for t in tracks:
        cand = matcher.classify_track(t, index)
        pas = matcher.lane(cand)
        if pas == "auto":
            matched.append((t, cand))
        else:
            missing.append(t)
            if pas == "version":
                inne[id(t)] = cand

    import time as _time
    partia = _time.strftime("%Y-%m-%dT%H:%M:%S")
    for t, cand in matched:
        print(f"✓ {t.artist} — {t.title}")
        print(f"    ← {os.path.basename(cand.path)} (score {cand.score})")
        if args.apply:
            cover = spotify.cover_bytes(t) if t.id else None
            # dopisek wersji zostaje, stare wartości idą do dziennika (--cofnij),
            # a błąd jednego pliku nie przerywa całej operacji
            w = tagger.uporzadkuj(cand.path, t.artist, t.title, cover, partia=partia)
            if w.get("blad"):
                print(f"    ⚠ pominięto: {w['blad']}")
                continue
            if w.get("uwaga"):
                print(f"    · {w['uwaga']}")
            if w["do"] != w["z"]:
                print("    · nowa nazwa: analizy, ręczna siatka i historia idą za plikiem; "
                      "playlisty wysłane wcześniej do rekordboxa wskażą starą nazwę — "
                      "wyślij je ponownie")
            print(f"    → {os.path.basename(w['do'])}")

    if missing:
        print(f"\nBrakuje {len(missing)} utworów:")
        for t in missing:
            print(f"  ✗ {t.artist} — {t.title}")
            if id(t) in inne:
                print(f"    ≈ masz inną wersję: {os.path.basename(inne[id(t)].path)}"
                      " (nie ruszam jej)")
            sk = stores.sklepy(t)[:2]
            print("    kup: " + " · ".join(f"{x['name']} {x['url']}" for x in sk))
    print(f"\n{len(matched)} dopasowanych, {len(missing)} brakujących"
          + ("  (cofnięcie: selekta organize --folder … --cofnij)" if args.apply
             else "  (dry-run — dodaj --apply)"))


def cmd_verify(args) -> None:
    files = _audio_paths(args.folder)[: args.limit or None]
    bad = 0
    for p in files:
        try:
            rep = analyze_quality(p)
        except Exception as e:
            bad += 1
            print(f"❌ {os.path.basename(p)}")
            print(f"    nie da się odczytać: {e}")
            continue
        bad += rep.grade != "ok"
        kbps = f" · {rep.bitrate_kbps} kbps" if rep.bitrate_kbps else ""
        print(f"{GRADE_ICON[rep.grade]} {os.path.basename(p)}")
        print(f"    cutoff {rep.cutoff_hz/1000:.1f} kHz{kbps} — {rep.verdict}")
    print(f"\n{len(files) - bad}/{len(files)} plików bez zastrzeżeń")


def cmd_check(args) -> None:
    """Pełna weryfikacja pobrań: integralność + tożsamość + jakość."""
    by_id = {}
    if args.source:
        for t in _load_tracks(args.source):
            c = matcher.best_match(t, args.folder)
            if c:
                by_id[os.path.abspath(c.path)] = t
    files = _audio_paths(args.folder)[: args.limit or None]
    bad = 0
    for p in files:
        try:
            res = pipeline.verify_download(p, by_id.get(os.path.abspath(p)))
        except Exception as e:
            bad += 1
            print(f"❌ {os.path.basename(p)}: nie da się odczytać: {e}")
            continue
        bad += not res.ok
        print(res.format())
    print(f"\n{len(files) - bad}/{len(files)} plików przeszło weryfikację")
    if bad:
        print("odrzucone pliki pobierz ponownie (np. `selekta hunt` z playlisty)")


def cmd_match(args) -> None:
    """Fingerprint each matched file against its Spotify 30 s preview."""
    tracks = _load_tracks(args.source)
    checked = ok = 0
    for t in tracks:
        cand = matcher.best_match(t, args.folder)
        if not cand:
            continue
        res = verify_match.verify_track(cand.path, t)
        zrodlo = ""
        if res is None:
            # Spotify coraz częściej nie daje próbki, a listy tekstowe, Apple
            # i YouTube nie mają jej wcale — apka ma już próbki z iTunes
            po_nazwie = verify_match.verify_by_name(cand.path, t.artist, t.title)
            if po_nazwie:
                res, zrodlo = po_nazwie
                # wyszukiwarka iTunes potrafi oddać ten sam tytuł innego wykonawcy
                # („El Diablo” Franko zamiast Fuego) — taka próbka niczego nie dowodzi
                wykonawca = set(matcher.normalize(zrodlo.split(" — ")[0]))
                if not (wykonawca & set(matcher.normalize(t.artist))):
                    print(f"— {t.artist} — {t.title}: próbka z iTunes jest innego "
                          f"wykonawcy ({zrodlo}) — nie porównuję")
                    continue
        if res is None:
            print(f"— {t.artist} — {t.title}: brak próbki do porównania (Spotify ani iTunes)")
            continue
        checked += 1
        ok += res.verdict == "match"
        print(f"{VERDICT_ICON[res.verdict]} {t.artist} — {t.title}")
        print(f"    {os.path.basename(cand.path)} — podobieństwo {res.score:.2f} "
              f"@ {res.offset_s:.0f}s {('· ' + res.note) if res.note else ''}"
              f"{(' · próbka: ' + zrodlo) if zrodlo else ''}")
    print(f"\n{ok}/{checked} plików potwierdzonych jako właściwy utwór")


def cmd_covers(args) -> None:
    have, missing = covers.audit(_audio_paths(args.folder))
    print(f"{len(have)}/{len(have) + len(missing)} plików ma okładkę")
    for p in missing:
        name = os.path.basename(p)
        print(f"  ✗ {name}")
        if not args.fill:
            continue
        # artysta/tytuł z tagów, tylko okładka do pliku, błąd jednego pliku
        # nie przerywa pętli (wcześniej pierwszy M4A kończył całą komendę)
        w = covers.uzupelnij(p)
        znak = {"dodano": "✓", "brak": "—", "jest": "·"}.get(w["status"], "⚠")
        print(f"    {znak} {w['opis']}")


def cmd_icons(args) -> None:
    if not finder_icons.available():
        sys.exit("ta komenda działa tylko na macOS")
    # wszystkie podfoldery (pobrania z Soulseeka leżą w katalogach albumów),
    # łącznie z kopiami w setach — Finder pokazuje i te foldery
    paths = [p for p in matcher.audio_files(args.folder, kopie_w_setach=True)
             if p.lower().endswith(finder_icons.FINDER_BLIND)]
    if args.clear:
        print(f"usunięto ikony postawione przez selektę z {finder_icons.clear(paths)} plików")
        return
    done, skipped = finder_icons.apply(paths)
    print(f"ustawiono ikonę Findera dla {done} plików FLAC/WAV")
    for p in skipped:
        print(f"  — pominięto (brak okładki): {os.path.basename(p)}")


def _cached_harmonic(path: str, refresh: bool = False) -> harmonic.TrackAnalysis:
    if not refresh:
        hit = cache.get(path, "harmonic")
        if hit:
            return harmonic.TrackAnalysis(**hit)
    ta = harmonic.analyze(path)
    cache.put(path, "harmonic", asdict(ta))
    return ta


def cmd_analyze(args) -> None:
    paths = _audio_paths(args.folder)[: args.limit or None]
    rows = []
    pominiete = 0
    for p in paths:
        try:
            ta = _cached_harmonic(p, refresh=args.refresh)
        except Exception as e:
            pominiete += 1
            print(f"❌ {os.path.basename(p)}: nie da się odczytać: {e}")
            continue
        if ta.bpm == 0 and ta.camelot == "?":
            # dekoder nie oddał sygnału — to nie jest wynik, tylko brak pliku
            # do analizy (śmieć udający audio albo czysta cisza)
            pominiete += 1
            print(f"❌ {os.path.basename(p)}: brak sygnału do analizy "
                  f"(uszkodzony albo nie-audio)")
            continue
        flag = "" if ta.confidence_key >= 0.4 else "  (niepewna tonacja)"
        if args.beatport and ta.confidence_key < 0.5:
            official = cache.get(p, "beatport")
            if official is None:
                name = os.path.splitext(os.path.basename(p))[0]
                artist, _, title = name.partition(" - ")
                official = keysource.lookup(artist, title) or {}
                cache.put(p, "beatport", official)
            cam, bpm, note = keysource.reconcile(
                ta.camelot, ta.bpm, ta.confidence_key, official or None)
            if cam != ta.camelot or bpm != ta.bpm:
                ta = harmonic.TrackAnalysis(bpm, official.get("key_name", ta.key),
                                            cam, ta.confidence_bpm, 0.95)
                flag = f"  ← {note}"
        rows.append((os.path.basename(p), ta))
        if args.apply:
            harmonic.write_tags(p, ta)
            # zapis tagów zmienia mtime, a mtime jest częścią klucza cache —
            # bez ponownego put następne uruchomienie liczyłoby wszystko od zera
            cache.put(p, "harmonic", asdict(ta))
        print(f"{ta.bpm:>5.1f} BPM  {ta.camelot:>3}  {ta.key:<8} {os.path.basename(p)}{flag}")

    if args.order:
        print("\n— kolejność harmoniczna (koło Camelot, energia rosnąco) —")
        for pos, (name, ta, note) in enumerate(harmonic.order_set(rows), 1):
            print(f"  {pos:>2}. {ta.camelot:>3}  {ta.bpm:>5.1f}  {name}   [{note}]")
    if args.apply:
        print(f"\nzapisano tagi BPM/tonacja w {len(rows)} plikach")
    if pominiete:
        print(f"\n⚠️ pominięto {pominiete} plików nie do odczytania "
              f"— sprawdź je przez `selekta check`")


def cmd_health(args) -> None:
    report = health.scan(args.folder, deep=args.deep)
    health.print_report(report)


def cmd_export(args) -> None:
    if args.source:  # order by the playlist, keeping only matched files
        pl = _load_tracks(args.source)
        paths = [c.path for t in pl if (c := matcher.best_match(t, args.folder))]
        tracks = [dj_export.track_from_file(p) for p in paths] or dj_export.collect(args.folder)
    else:
        tracks = dj_export.collect(args.folder)
    name = args.name or os.path.basename(os.path.normpath(args.folder))
    if args.target == "rekordbox":
        # to samo wzbogacenie co eksport z aplikacji: siatka, cue i ręczna
        # praca z rekordboxa — XML z terminala był bez TEMPO/POSITION_MARK
        tracks = dj_export.wzbogac_o_siatke(tracks)
        out = args.out or os.path.join(args.folder, f"{name}.xml")
        print("zapisano rekordbox XML:", dj_export.to_rekordbox_xml(tracks, name, out))
    elif args.target == "m3u8":
        out = args.out or os.path.join(args.folder, f"{name}.m3u8")
        print("zapisano playlistę M3U8:", dj_export.to_m3u8(tracks, out))
    else:
        root = args.out or os.path.expanduser("~/Music")
        print("zapisano crate Serato:", dj_export.install_serato_crate(tracks, root, name))


def cmd_usb(args) -> None:
    conv = None if args.convert_wav == "keep" else args.convert_wav
    rep = usb.prepare(args.folder, args.dest, convert_wav=conv)
    print(rep.format_report())


def cmd_radar(args) -> None:
    radar.check_all(args.folder, notify_new=not args.no_notify)


def cmd_wishlist(args) -> None:
    if args.add:
        para = importers.split_artist_title(args.add)
        if not para:
            sys.exit('podaj utwór jako "Artysta - Tytuł" (z myślnikiem otoczonym spacjami)')
        it = wishlist.add(*para)
        print(f"dodano do listy życzeń: {it['artist']} — {it['title']}")
    elif args.remove:
        # lista pokazuje numery od 1 (i id) — tak samo liczymy przy usuwaniu;
        # dawniej numeracja szła od 0 i nigdzie jej nie było widać
        cel: str | int = args.remove.strip()
        if isinstance(cel, str) and cel.isdigit() and len(cel) < 6:
            cel = int(cel) - 1
            if cel < 0:
                sys.exit("numer pozycji zaczyna się od 1 (patrz `selekta wishlist`)")
        removed = wishlist.remove(cel)
        print(f"usunięto: {removed['artist']} — {removed['title']}" if removed
              else "nie znaleziono — sprawdź numer albo id w `selekta wishlist`")
    elif args.check:
        found, nieudane = wishlist.check(SlskdClient())
        if found:
            print(f"{len(found)} pozycji z listy życzeń pojawiło się na Soulseeku")
            for it in found:
                print(f"  ★ {it['artist']} — {it['title']}")
        elif nieudane:
            sys.exit(f"nie udało się sprawdzić {nieudane} pozycji — slskd "
                     f"nie odpowiada (uruchom go w aplikacji albo `selekta serve`)")
        else:
            print("nic nowego z listy życzeń")
        if found and nieudane:
            print(f"⚠️ {nieudane} pozycji nie udało się sprawdzić — slskd przerywał")
    elif args.daemon:
        print(f"wishlist daemon: sprawdzam co {args.interval//60} min (Ctrl+C przerywa)")
        wishlist.daemon(interval_s=args.interval, client=SlskdClient())
    else:
        wpisy = wishlist.items()
        if not wpisy:
            print("lista życzeń jest pusta")
        for i, it in enumerate(wpisy, 1):
            znak = "★" if it.get("found") else "·"
            print(f"  {i:>2}. {znak} {it['artist']} — {it['title']}  [id {it['id']}]")
        if wpisy:
            print("\nusuń: selekta wishlist --remove NUMER (albo id)")


def cmd_hunt(args) -> None:
    tracks = _load_tracks(args.source)
    # „mam" tylko gdy biblioteka ma TEN SAM utwór w tej samej wersji —
    # dawniej best_match brał Like a Prayer za Frozen i hunt go pomijał
    index = matcher.library_index(args.folder) if args.folder else None
    slskd = SlskdClient()
    online = slskd.available()
    if not online:
        print("(slskd niedostępny — pokazuję tylko linki zakupowe)\n")
    for t in tracks:
        if index is not None and matcher.lane(matcher.classify_track(t, index)) == "auto":
            continue
        print(f"♪ {t.artist} — {t.title}")
        if online:
            # ta sama drabina zapytań i ranking z tożsamością co w aplikacji
            hits = slskd.search_track(t.artist, t.title, t.duration_s)
            pewny = slskd.pewny_wynik(hits, t.artist, t.title, t.duration_s) if hits else None
            for h in hits[:3]:
                kind = "lossless" if h.is_lossless else f"{h.bitrate or '?'} kbps"
                znak = "✓" if h is pewny else " "
                print(f"   {znak} slsk: {os.path.basename(h.filename.replace(chr(92), '/'))}"
                      f" [{kind}, {h.size//1_000_000} MB]")
            if pewny and args.download:
                slskd.download(pewny)
                print(f"    ⬇ zlecono pobieranie: {os.path.basename(pewny.filename.replace(chr(92), '/'))}")
            elif hits and not pewny:
                print("    slsk: żaden wynik nie jest na pewno tym utworem w tej wersji "
                      "— wybierz ręcznie w aplikacji (nic nie pobieram)")
            elif not hits:
                print("    slsk: brak wyników — dodaję do listy życzeń")
                wishlist.add(t.artist, t.title, t.duration_s)
        sk = stores.sklepy(t)[:3]
        print("    kup: " + " · ".join(f"{x['name']} {x['url']}" for x in sk))


# --------------------------------------------------------------------------

def cmd_loudness(args) -> None:
    for p in _audio_paths(args.folder)[: args.limit or None]:
        l = loudness.analyze(p)
        if args.apply:
            loudness.write_tags(p, l)
        print(f"{os.path.basename(p)}\n    {loudness.format_report(l)}")
    if args.apply:
        print("\nzapisano tagi ReplayGain")


def cmd_cues(args) -> None:
    for p in _audio_paths(args.folder)[: args.limit or None]:
        ta = cache.get(p, "harmonic")
        bpm = ta["bpm"] if ta else None
        c = cues.analyze(p, bpm=bpm)
        print(f"{os.path.basename(p)}\n    {cues.format_report(c)}")


def cmd_tagfix(args) -> None:
    hits = tagfix.scan(args.folder)
    if not hits:
        print("nie znaleziono uszkodzonych tagów (mojibake)")
        return
    seen = set()
    for path, field, cur, sug in hits:
        print(f"{os.path.basename(path)}\n    {field}: {cur!r} → {sug!r}")
        if args.apply and path not in seen:
            tagfix.fix_file(path, dry_run=False)
            seen.add(path)
    print(f"\n{len(hits)} pól do naprawy w {len({h[0] for h in hits})} plikach"
          + ("  — naprawione" if args.apply else "  (podgląd — dodaj --apply)"))


def cmd_dedupe(args) -> None:
    actions = dedupe.plan(args.folder, include_suspect=args.suspect)
    print(dedupe.format_plan(actions))
    if args.apply and actions:
        # domyślnie kosz obok każdego pliku — przywrócenie wraca na miejsce
        # także z podfolderów; pliki z folderów setów nigdy nie są ruszane
        res = dedupe.apply(actions, args.trash or None, korzen=args.folder)
        gdzie = args.trash or "_selekta_kosz obok każdego pliku"
        print(f"\nprzeniesiono {len(res['przeniesione'])} plików do {gdzie} "
              f"(odzyskane {res['odzyskane_MB']:.0f} MB)")


def cmd_uchem(args) -> None:
    """Co warto sprawdzić uchem, zanim trafi do setu."""
    w = uchem.sprawdz(args.folder)
    print(uchem.format_report(w))


def cmd_doctor(args) -> None:
    """Czy integracje (Spotify, Beatport, iTunes…) i narzędzia działają."""
    raport = doktor.zbadaj(tylko_lokalne=args.offline)
    print(doktor.format_report(raport))
    if not raport["krytyczne_ok"]:
        sys.exit(1)


def cmd_serve(args) -> None:
    from . import web
    web.serve(args.folder, port=args.port)


def main() -> None:
    p = argparse.ArgumentParser(prog="selekta", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--debug", action="store_true",
                   help="pokaż pełny traceback zamiast krótkiego komunikatu")
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("organize", help="dopasuj pliki do playlisty, otaguj, okładki")
    o.add_argument("source", nargs="?", default=""); o.add_argument("--folder", required=True)
    o.add_argument("--apply", action="store_true", help="bez tej flagi tylko podgląd")
    o.add_argument("--cofnij", action="store_true",
                   help="przywróć tagi i nazwy sprzed ostatniego --apply")
    o.set_defaults(fn=cmd_organize)

    v = sub.add_parser("verify", help="raport jakości (detektor fałszywych FLAC-ów)")
    v.add_argument("--folder", required=True); v.add_argument("--limit", type=int, default=0)
    v.set_defaults(fn=cmd_verify)

    ch = sub.add_parser("check", help="pełna weryfikacja pobrań (integralność+tożsamość+jakość)")
    ch.add_argument("source", nargs="?", default="", help="opcjonalna playlista dla kontroli tożsamości")
    ch.add_argument("--folder", required=True); ch.add_argument("--limit", type=int, default=0)
    ch.set_defaults(fn=cmd_check)

    m = sub.add_parser("match", help="weryfikacja przez odsłuch (fingerprint vs preview)")
    m.add_argument("source"); m.add_argument("--folder", required=True)
    m.set_defaults(fn=cmd_match)

    c = sub.add_parser("covers", help="audyt okładek; --fill dociąga z iTunes")
    c.add_argument("--folder", required=True); c.add_argument("--fill", action="store_true")
    c.set_defaults(fn=cmd_covers)

    i = sub.add_parser("icons", help="pokaż okładki FLAC/WAV w Finderze (macOS)")
    i.add_argument("--folder", required=True)
    i.add_argument("--clear", action="store_true", help="usuń własne ikony")
    i.set_defaults(fn=cmd_icons)

    a = sub.add_parser("analyze", help="wykryj BPM i tonację; --order = sort harmoniczny")
    a.add_argument("--folder", required=True); a.add_argument("--limit", type=int, default=0)
    a.add_argument("--apply", action="store_true", help="zapisz tagi BPM/tonacja")
    a.add_argument("--order", action="store_true", help="pokaż kolejność harmoniczną setu")
    a.add_argument("--refresh", action="store_true", help="przelicz od nowa (pomiń cache)")
    a.add_argument("--beatport", action="store_true",
                   help="rozstrzygaj niepewną tonację oficjalnym kluczem z Beatport")
    a.set_defaults(fn=cmd_analyze)

    he = sub.add_parser("health", help="dashboard: duplikaty, braki, uszkodzenia")
    he.add_argument("--folder", required=True)
    he.add_argument("--deep", action="store_true", help="dodaj analizę jakości audio")
    he.set_defaults(fn=cmd_health)

    e = sub.add_parser("export", help="eksport do rekordbox (XML) lub Serato (.crate)")
    e.add_argument("--folder", required=True)
    e.add_argument("--target", choices=["rekordbox", "serato", "m3u8"], default="rekordbox")
    e.add_argument("--source", default="", help="playlista → kolejność eksportu")
    e.add_argument("--name", default=""); e.add_argument("--out", default="")
    e.set_defaults(fn=cmd_export)

    u = sub.add_parser("usb", help="przygotuj płaski folder pod CDJ")
    u.add_argument("--folder", required=True); u.add_argument("--dest", required=True)
    u.add_argument("--convert-wav", dest="convert_wav", choices=["aiff", "flac", "keep"],
                   default="aiff", help="format docelowy dla WAV (keep = bez konwersji)")
    u.set_defaults(fn=cmd_usb)

    r = sub.add_parser("radar", help="nowe wydania Twoich artystów (Beatport/Bandcamp)")
    r.add_argument("--folder", required=True)
    r.add_argument("--no-notify", action="store_true")
    r.set_defaults(fn=cmd_radar)

    w = sub.add_parser("wishlist", help="lista życzeń + cykliczne szukanie na Soulseeku")
    w.add_argument("--add", metavar='"Artysta - Tytuł"')
    w.add_argument("--remove", metavar="NUMER|ID", help="numer z listy (od 1) albo id wpisu")
    w.add_argument("--check", action="store_true", help="sprawdź teraz na Soulseeku")
    w.add_argument("--daemon", action="store_true", help="pętla w tle")
    w.add_argument("--interval", type=int, default=3600)
    w.set_defaults(fn=cmd_wishlist)

    h = sub.add_parser("hunt", help="szukaj brakujących na Soulseeku + linki zakupowe")
    h.add_argument("source"); h.add_argument("--folder", default="")
    h.add_argument("--download", action="store_true")
    h.set_defaults(fn=cmd_hunt)

    ld = sub.add_parser("loudness", help="głośność LUFS + ReplayGain (spójny poziom setu)")
    ld.add_argument("--folder", required=True); ld.add_argument("--limit", type=int, default=0)
    ld.add_argument("--apply", action="store_true", help="zapisz tagi ReplayGain")
    ld.set_defaults(fn=cmd_loudness)

    cu = sub.add_parser("cues", help="wykryj intro/outro/drop/pierwsze uderzenie")
    cu.add_argument("--folder", required=True); cu.add_argument("--limit", type=int, default=0)
    cu.set_defaults(fn=cmd_cues)

    tf = sub.add_parser("tagfix", help="napraw uszkodzone tagi (mojibake)")
    tf.add_argument("--folder", required=True); tf.add_argument("--apply", action="store_true")
    tf.set_defaults(fn=cmd_tagfix)

    dd = sub.add_parser("dedupe", help="usuń duplikaty (najlepsza kopia zostaje)")
    dd.add_argument("--folder", required=True)
    dd.add_argument("--suspect", action="store_true", help="dołącz podejrzane (różny czas)")
    dd.add_argument("--trash", default="", help="folder na przeniesione kopie")
    dd.add_argument("--apply", action="store_true")
    dd.set_defaults(fn=cmd_dedupe)

    uc = sub.add_parser("uchem", help="co sprawdzić uchem: niepewne tempo/tonacja, niestabilna siatka, podejrzana jakość")
    uc.add_argument("--folder", required=True)
    uc.set_defaults(fn=cmd_uchem)

    dr = sub.add_parser("doctor", help="sprawdź integracje (Spotify, Beatport, iTunes, YouTube) i narzędzia (ffmpeg, slskd)")
    dr.add_argument("--offline", action="store_true", help="tylko sondy lokalne, bez sieci")
    dr.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("serve", help="uruchom dashboard w przeglądarce")
    s.add_argument("--folder", required=True)
    s.add_argument("--port", type=int, default=8756)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(1)
    except Exception as e:
        # moduły rzucają wyjątki z gotowymi polskimi komunikatami — użytkownik
        # ma dostać sam komunikat, nie ścianę tracebacku (pełny stos: --debug)
        if args.debug:
            raise
        sys.exit(f"błąd: {e}")


if __name__ == "__main__":
    main()
