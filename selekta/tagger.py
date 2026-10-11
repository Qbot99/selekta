"""Write clean tags, embed cover art, rename to 'Artist - Title.ext'.

Każdy zapis do pliku zmienia jego mtime, a mtime jest częścią klucza pamięci
analiz (BPM, tonacja, siatka, głośność…). Dźwięk się przy tym nie zmienia,
więc ``zachowaj_analizy`` przenosi policzone wyniki na nowy odcisk pliku —
inaczej każda poprawka tagu albo okładki kasowała ~minutę analizy na utwór.
"""
from __future__ import annotations

import contextlib
import json
import os
import re

from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TIT2, TPE1
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE

# Znaki zakazane w exFAT/FAT plus ZNAKI STERUJĄCE (0x00-0x1F). Te drugie
# przechodzą przez system plików, ale potrafią zawiesić parser nazw
# w CDJ-u — a to znaczy przerwany set, nie brzydką nazwę.
FORBIDDEN = re.compile("[" + re.escape('/\\:?"<>|*') + "\u0000-\u001f]")


def safe_name(artist: str, title: str) -> str:
    # rstrip('. ') zdejmuje też przeplot "b. ." — końcowa spacja/kropka
    # jest niedozwolona na FAT32/Windows
    return FORBIDDEN.sub("", f"{artist} - {title}").strip().rstrip(". ")


def _mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def _tag_id3(tags, artist: str | None, title: str | None, cover: bytes | None) -> None:
    if title is not None:
        tags.delall("TIT2")
        tags.add(TIT2(encoding=3, text=title))
    if artist is not None:
        tags.delall("TPE1")
        tags.add(TPE1(encoding=3, text=artist))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=_mime(cover), type=3, desc="Cover", data=cover))


def _zapisz(path: str, artist: str | None, title: str | None,
            cover: bytes | None) -> None:
    """Zapis tagów; ``None`` = tego pola nie ruszaj."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        audio = FLAC(path)
        if title is not None:
            audio["TITLE"] = title
        if artist is not None:
            audio["ARTIST"] = artist
        if cover:
            audio.clear_pictures()
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, _mime(cover), "Cover"
            pic.data = cover
            audio.add_picture(pic)
        audio.save()
    elif ext == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        _tag_id3(tags, artist, title, cover)
        # wersję ID3 zostawiamy taką, jaka była (2.3 zostaje 2.3) — po cichu
        # podniesione v2.4 nie czytają starsze odtwarzacze i część CDJ-ów
        tags.save(path, v2_version=4 if getattr(tags, "version", (2, 4, 0))[1] >= 4 else 3)
    elif ext in (".wav", ".aiff", ".aif"):
        audio = WAVE(path) if ext == ".wav" else AIFF(path)
        if audio.tags is None:
            audio.add_tags()
        _tag_id3(audio.tags, artist, title, cover)
        audio.save()
    elif ext in (".m4a", ".mp4", ".aac"):
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        if title is not None:
            audio["\xa9nam"] = [title]
        if artist is not None:
            audio["\xa9ART"] = [artist]
        if cover:
            fmt = MP4Cover.FORMAT_PNG if _mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(cover, imageformat=fmt)]
        audio.save()
    else:
        raise ValueError(f"unsupported format: {ext}")


def tag_file(path: str, artist: str, title: str, cover: bytes | None) -> None:
    """Zapisz artystę, tytuł i (opcjonalnie) okładkę; analizy zostają."""
    with zachowaj_analizy(path):
        _zapisz(path, artist, title, cover)


def zapisz_okladke(path: str, cover: bytes) -> None:
    """Wstaw okładkę i NIC więcej — artysta i tytuł w pliku zostają nietknięte.

    „Dociągnij okładkę” wołało dawniej ``tag_file`` z artystą i tytułem
    wyciętymi z nazwy pliku, więc przy okazji psuło poprawne tagi
    („Linds” → „Kick It”, wielkie litery → małe).
    """
    with zachowaj_analizy(path):
        _zapisz(path, None, None, cover)


def _rodzaje_cache() -> list[str]:
    """Nazwy rodzajów analiz w pamięci podręcznej (harmonic, quality, cues…)."""
    from . import cache
    out = []
    try:
        nazwy = os.listdir(cache.CACHE_DIR)
    except OSError:
        return out
    for n in nazwy:
        if not n.endswith(".json"):
            continue
        if n.startswith("k_"):                 # nazwa z kodem — rodzaj jest w środku
            try:
                with open(os.path.join(cache.CACHE_DIR, n), encoding="utf-8") as fh:
                    k = json.load(fh).get("kind")
            except (OSError, ValueError, AttributeError):
                continue
            if k:
                out.append(k)
        else:
            out.append(n[:-5])
    return out


@contextlib.contextmanager
def zachowaj_analizy(path: str, nowa_sciezka: str | None = None):
    """Przenieś policzone analizy pliku przez zapis tagów (i zmianę nazwy).

    Zapamiętujemy tylko wpisy AKTUALNE (``cache.get`` pilnuje wersji
    algorytmu i odcisku), więc nic przestarzałego nie odżywa. Działa także
    dla ręcznej korekty siatki trzymanej po ścieżce (``waveform``), gdy plik
    zmienia nazwę.
    """
    from . import cache
    stare: dict[str, dict] = {}
    for kind in _rodzaje_cache():
        try:
            d = cache.get(path, kind)
        except Exception:                      # noqa: BLE001
            d = None
        if d is not None:
            stare[kind] = d
    yield
    cel = nowa_sciezka or path
    if not os.path.isfile(cel):
        return
    for kind, d in stare.items():
        try:
            cache.put(cel, kind, d)
        except Exception:                      # noqa: BLE001
            pass
    if nowa_sciezka and os.path.abspath(nowa_sciezka) != os.path.abspath(path):
        _przenies_reczna_prace(os.path.abspath(path), os.path.abspath(nowa_sciezka))


def _przenies_reczna_prace(stara: str, nowa: str) -> None:
    """Po zmianie nazwy: ręczna siatka, dane z rekordboxa i historia setów
    idą za plikiem (wszystkie trzy są zapisane po ścieżce)."""
    try:
        from . import waveform
        w = waveform.wczytaj_siatke(stara)
        if w and w.get("first_beat_s") is not None:
            waveform.zapisz_siatke(nowa, w["first_beat_s"], w.get("bpm"), w.get("battito"))
            waveform.skasuj_siatke(stara)
    except Exception:                          # noqa: BLE001
        pass
    try:
        from . import rbimport
        stan = rbimport._wczytaj_stan()
        if stara in stan:
            stan[nowa] = stan.pop(stara)
            rbimport._zapisz_stan(stan)
    except Exception:                          # noqa: BLE001
        pass
    try:
        from . import historia
        sesje = historia._wczytaj()
        zmiana = False
        for sesja in sesje:
            sc = sesja.get("sciezki") or []
            if stara in sc:
                sesja["sciezki"] = [nowa if x == stara else x for x in sc]
                zmiana = True
        if zmiana:
            historia._zapisz(sesje)
    except Exception:                          # noqa: BLE001
        pass


def rename_file(path: str, artist: str, title: str) -> str:
    folder, old = os.path.split(path)
    ext = os.path.splitext(old)[1]
    new = safe_name(artist, title) + ext
    dst = os.path.join(folder, new)
    if os.path.abspath(dst) == os.path.abspath(path):
        return path
    if os.path.exists(dst) and old.lower() != new.lower():
        raise FileExistsError(dst)
    if old.lower() == new.lower() and old != new:  # case-only rename (APFS)
        tmp = os.path.join(folder, new + ".renaming")
        os.rename(path, tmp)
        os.rename(tmp, dst)
    else:
        os.rename(path, dst)
    return dst


# --------------------------------------------------------------------------
# porządkowanie wg playlisty (CLI `selekta organize`)
# --------------------------------------------------------------------------

def _plik_dziennika() -> str:
    from . import config
    return os.path.join(config.STATE_DIR, "porzadkowanie.json")


def _dopisek_wersji(tekst: str) -> str:
    """Dopisek wersji z tytułu albo nazwy pliku: „(Extended Mix)”, „[Club Mix]”.

    Tylko nawias, w którym są słowa o wersji (extended, radio, remix…,
    także „Original Mix”) — „(feat. X)” czy „(2025)” wersją nie są.
    """
    from .matcher import MIX_WORDS
    for m in re.finditer(r"[\(\[]([^\)\]]+)[\)\]]", tekst or ""):
        slowa = set(re.split(r"[^a-z0-9]+", m.group(1).lower()))
        if slowa & (MIX_WORDS | {"original"}):
            return f"({m.group(1).strip()})"
    return ""


def tytul_z_wersja(nowy_tytul: str, stary_tytul: str, stem: str) -> str:
    """Tytuł z playlisty, ale z zachowanym dopiskiem wersji z pliku.

    Playlisty (Spotify, tekst) często podają goły tytuł „Call Me”, a plik to
    „Call Me (Extended Mix)”. Bez tego `organize --apply` kasowało informację
    o wersji z tagu i z nazwy — a dla DJ-a Extended i Radio Edit to dwa różne
    utwory.
    """
    if _dopisek_wersji(nowy_tytul):
        return nowy_tytul
    dopisek = _dopisek_wersji(stary_tytul) or _dopisek_wersji(stem)
    return f"{nowy_tytul} {dopisek}".strip() if dopisek else nowy_tytul


def uporzadkuj(path: str, artist: str, title: str, cover: bytes | None = None,
               partia: str | None = None) -> dict:
    """Otaguj i nazwij plik wg playlisty — odwracalnie i bez utraty wersji.

    * dopisek wersji (Extended/Original Mix…) z pliku zostaje w tytule;
    * istniejąca okładka zostaje (okładka z playlisty tylko gdy brak);
    * stare tagi i nazwa trafiają do dziennika — ``cofnij_porzadkowanie``;
    * analizy, ręczna siatka, dane z rekordboxa i historia idą za plikiem;
    * błąd jednego pliku (np. nietypowy format) nie przerywa całej operacji —
      wołający dostaje ``{"blad": ...}`` i jedzie dalej.
    """
    from . import covers, health
    import time as _time
    try:
        stary_a, stary_t = health.czytaj_tagi(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        tytul = tytul_z_wersja(title, stary_t, stem)
        okladka = cover if (cover and not covers.embedded_art(path)) else None
        cel = os.path.join(os.path.dirname(path),
                           safe_name(artist, tytul) + os.path.splitext(path)[1])
        uwaga = ""
        if (os.path.exists(cel) and os.path.abspath(cel) != os.path.abspath(path)
                and os.path.basename(cel).lower() != os.path.basename(path).lower()):
            cel, uwaga = path, "nazwa bez zmian — plik o docelowej nazwie już istnieje"
        with zachowaj_analizy(path, nowa_sciezka=cel):
            _zapisz(path, artist, tytul, okladka)
            nowa = rename_file(path, artist, tytul) if cel != path else path
    except (ValueError, OSError) as exc:
        return {"blad": str(exc), "z": path}
    wpis = {"partia": partia or _time.strftime("%Y-%m-%dT%H:%M:%S"), "z": path, "do": nowa,
            "artist_przed": stary_a, "title_przed": stary_t,
            "artist": artist, "title": tytul, "okladka_dodana": bool(okladka),
            "uwaga": uwaga}
    _dopisz_do_dziennika(wpis)
    return wpis


def _dopisz_do_dziennika(wpis: dict) -> None:
    sciezka = _plik_dziennika()
    try:
        with open(sciezka, encoding="utf-8") as fh:
            dane = json.load(fh)
    except (OSError, ValueError):
        dane = []
    dane.append(wpis)
    os.makedirs(os.path.dirname(sciezka), exist_ok=True)
    tmp = sciezka + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane[-2000:], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, sciezka)


def cofnij_porzadkowanie() -> list[dict]:
    """Cofnij ostatnie `organize --apply`: stare tagi i stare nazwy plików."""
    sciezka = _plik_dziennika()
    try:
        with open(sciezka, encoding="utf-8") as fh:
            dane = json.load(fh)
    except (OSError, ValueError):
        return []
    if not dane:
        return []
    partia = dane[-1].get("partia")
    ostatnie = [w for w in dane if w.get("partia") == partia]
    wynik = []
    for w in reversed(ostatnie):
        teraz = w["do"]
        if not os.path.isfile(teraz):
            wynik.append({**w, "cofniete": False, "powod": "pliku już nie ma"})
            continue
        try:
            with zachowaj_analizy(teraz, nowa_sciezka=w["z"]):
                _zapisz(teraz, w.get("artist_przed") or None, w.get("title_przed") or None, None)
                if os.path.abspath(teraz) != os.path.abspath(w["z"]):
                    if os.path.exists(w["z"]):
                        raise FileExistsError(w["z"])
                    os.rename(teraz, w["z"])
            wynik.append({**w, "cofniete": True})
        except (ValueError, OSError) as exc:
            wynik.append({**w, "cofniete": False, "powod": str(exc)})
    reszta = [w for w in dane if w.get("partia") != partia]
    tmp = sciezka + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(reszta, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, sciezka)
    return wynik
