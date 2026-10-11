"""Przygotowanie USB pod CDJ — build a CDJ-ready USB folder.

Copies every audio file from a source folder (non-recursive) into a flat
destination folder with FAT32-safe, ASCII-only names (some CDJ firmwares
garble non-ASCII on the browse screen: Öwes -> Owes, Más -> Mas).

WAV files get special treatment: CDJs read WAV audio fine, but WAV
tags/artwork support is poor, so by default WAV is converted to AIFF
with ffmpeg (pcm_s16be / pcm_s24be, matching the source bit depth) and
re-tagged via mutagen.aiff — AIFF carries full ID3 (TIT2/TPE1/APIC), so
title, artist and the cover survive onto the player screen.
convert_wav="flac" converts to FLAC (compression level 5) instead;
convert_wav=None copies WAV as-is.

FLAC/MP3 (and AIFF/M4A/OGG) are copied byte-identical — content only
(shutil.copyfile). Name collisions get ' (2)', ' (3)', ...

Pliki „._*": na FAT32/exFAT macOS zapisuje rozszerzone atrybuty (np.
com.apple.provenance, nadawany każdemu nowemu plikowi) do osobnych plików
AppleDouble „._nazwa". Starsze CDJ pokazują je jako niegrywalne utwory,
więc po skopiowaniu usuwamy „._" każdego pliku, który sami zapisaliśmy.

Przed kopiowaniem sprawdzamy wolne miejsce (zatrzymujemy się, zanim
FAT32 się zapełni — przepełnienie kończyło się uszkodzonymi wpisami
katalogu), a po kopiowaniu porównujemy sumy kontrolne (`zweryfikuj`).

Czego tu NIE ma: bazy rekordboxa (PIONEER/rekordbox/export.pdb, ANLZ).
To zamknięty format Pioneera — pendrive z playlistami, siatką i hot cue
dla CDJ robi rekordbox („Eksportuj na urządzenie") z XML-a, który daje
selekta. Ten moduł robi płaski folder plików, który CDJ czyta w trybie
przeglądania folderów.

Requires ffmpeg on PATH for WAV conversion.
"""
from __future__ import annotations

import copy
import errno
import os
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from mutagen import File as MutagenFile
from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, TIT2, TPE1
from mutagen.wave import WAVE

CO_POWSTAJE = (
    "płaski folder plików audio — CDJ pokaże go w przeglądaniu folderów "
    "(USB → foldery). Bez bazy rekordboxa (PIONEER/export.pdb), więc bez "
    "playlist, siatki i hot cue: pendrive z nimi robi rekordbox — wczytaj "
    "set z selekty (panel „rekordbox xml”) i użyj „Eksportuj na urządzenie”."
)
ZAPAS_NA_PLIK = 64 * 1024          # zaokrąglenie do klastra FAT32/exFAT + wpisy katalogu
ZAPAS_STALY = 4 * 1024 * 1024      # margines, żeby nie zapisywać nośnika do ostatniego bajtu


class BrakMiejsca(OSError):
    """Na nośniku nie zmieści się to, co chcemy skopiować."""

from .covers import embedded_art
from .matcher import AUDIO_EXT
from .tagger import FORBIDDEN, safe_name
from .narzedzia import ffmpeg_path, ffprobe_path

MAX_NAME = 120  # full filename budget (stem + extension), CDJ-friendly

# Characters NFKD cannot decompose to ASCII — folded by hand.
_FOLD = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ı": "i",
})


def ascii_fold(text: str) -> str:
    """Diacritics -> plain ASCII (Öwes -> Owes, Más -> Mas, łza -> lza)."""
    text = text.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.encode("ascii", "ignore").decode("ascii")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

@dataclass
class UsbReport:
    """Result of prepare(): what landed on the stick and what did not."""
    copied: list[str] = field(default_factory=list)       # dest paths, copied 1:1
    converted: list[str] = field(default_factory=list)    # dest paths, WAV->AIFF/FLAC
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (source name, reason)
    total_bytes: int = 0
    pary: list[tuple[str, str]] = field(default_factory=list)     # (źródło, cel) do weryfikacji
    przerwano: str = ""                                   # powód przerwania (np. brak miejsca)
    usuniete_appledouble: int = 0

    def format_report(self) -> str:
        """Polish, human-readable summary."""
        mb = self.total_bytes / (1024 * 1024)
        lines = [
            "Przygotowanie USB pod CDJ zakończone:",
            f"  skopiowane pliki: {len(self.copied)}",
            f"  skonwertowane z WAV: {len(self.converted)}",
            f"  pominięte: {len(self.skipped)}",
            f"  łącznie zapisano: {mb:.1f} MB ({self.total_bytes} B)",
        ]
        for name, reason in self.skipped:
            lines.append(f"    - {name}: {reason}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #

def _artist_title(path: str) -> tuple[str, str]:
    """(artist, title) from tags, falling back to the 'Artist - Title' filename."""
    stem = os.path.splitext(os.path.basename(path))[0]
    fn_artist, sep, fn_title = stem.partition(" - ")
    artist = fn_artist.strip() if sep else ""
    title = fn_title.strip() if sep else stem
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    tags = getattr(audio, "tags", None)
    if tags is not None:
        if hasattr(tags, "getall"):  # ID3 (MP3/WAV/AIFF)
            t = tags.get("TIT2")
            a = tags.get("TPE1")
            if t is not None and getattr(t, "text", None) and str(t.text[0]).strip():
                title = str(t.text[0]).strip()
            if a is not None and getattr(a, "text", None) and str(a.text[0]).strip():
                artist = str(a.text[0]).strip()
        else:  # Vorbis comments (FLAC/OGG)
            if tags.get("TITLE"):
                title = str(tags["TITLE"][0]).strip() or title
            if tags.get("ARTIST"):
                artist = str(tags["ARTIST"][0]).strip() or artist
    return artist, title


def _dest_stem(path: str, ext: str) -> str:
    """FAT32-safe, ASCII, length-capped stem for the destination file."""
    artist, title = _artist_title(path)
    if artist:
        stem = safe_name(artist, title)
    else:
        stem = FORBIDDEN.sub("", title).strip().rstrip(".")
    stem = ascii_fold(stem)
    stem = " ".join(stem.split())  # collapse whitespace left by folding
    stem = stem.strip().rstrip(".")
    if not stem:
        stem = "utwor"
    budget = MAX_NAME - len(ext) - 6  # leave room for ' (99)' dedupe suffix
    return stem[:budget].rstrip(" .")


def _unique_dest(dest_folder: str, stem: str, ext: str, taken: set[str]) -> str:
    """Collision-free path in dest_folder; FAT32 is case-insensitive."""
    name = stem + ext
    n = 2
    while name.lower() in taken or os.path.exists(os.path.join(dest_folder, name)):
        name = f"{stem} ({n}){ext}"
        n += 1
    taken.add(name.lower())
    return os.path.join(dest_folder, name)


# --------------------------------------------------------------------------- #
# WAV conversion
# --------------------------------------------------------------------------- #

def _convert_wav(src: str, dst: str) -> None:
    """ffmpeg WAV -> AIFF/FLAC, matching bit depth; tags handled separately."""
    ext = os.path.splitext(dst)[1].lower()
    try:
        bits = WAVE(src).info.bits_per_sample or 16
    except Exception:
        bits = 16
    cmd = [ffmpeg_path(), "-v", "error", "-y", "-i", src, "-vn", "-map_metadata", "-1"]
    if ext == ".aiff":
        cmd += ["-c:a", "pcm_s16be" if bits <= 16 else "pcm_s24be"]
    else:  # .flac
        cmd += ["-c:a", "flac", "-compression_level", "5"]
    proc = subprocess.run(cmd + [dst], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffmpeg zakończył się kodem {proc.returncode}")


# ID3 → Vorbis dla WAV→FLAC (to, co DJ-owi potrzebne w odtwarzaczu)
_ID3_NA_VORBIS = {"TBPM": "BPM", "TKEY": "INITIALKEY", "TCON": "GENRE",
                  "TALB": "ALBUM", "TPE2": "ALBUMARTIST", "TDRC": "DATE",
                  "TRCK": "TRACKNUMBER", "TPUB": "LABEL", "TSRC": "ISRC",
                  "TCOM": "COMPOSER"}


def _id3_zrodla(src_wav: str):
    try:
        return WAVE(src_wav).tags
    except Exception:  # noqa: BLE001
        return None


def _retag_converted(src_wav: str, dst: str, artist: str, title: str) -> None:
    """Przenieś tagi z WAV-a do pliku po konwersji.

    Wcześniej szły tylko TIT2/TPE1/APIC — BPM, tonacja (TKEY), gatunek,
    komentarz i dane Mixed In Key (GEOB) przepadały, a CDJ pokazywał
    utwór bez tempa i tonacji. AIFF ma pełne ID3, więc kopiujemy wszystkie
    ramki; do FLAC-a przepisujemy pola, które mają odpowiednik w Vorbis.
    """
    cover = None
    try:
        cover = embedded_art(src_wav)
    except Exception:
        pass
    zrodlo = _id3_zrodla(src_wav)
    ext = os.path.splitext(dst)[1].lower()
    if ext == ".aiff":
        audio = AIFF(dst)
        if audio.tags is None:
            audio.add_tags()
        for ramka in (zrodlo.values() if zrodlo is not None else []):
            audio.tags.add(copy.deepcopy(ramka))
        audio.tags.delall("TIT2")
        audio.tags.delall("TPE1")
        audio.tags.add(TIT2(encoding=3, text=title))
        if artist:
            audio.tags.add(TPE1(encoding=3, text=artist))
        if cover:
            audio.tags.delall("APIC")
            audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3,
                                desc="Cover", data=cover))
        audio.save()
    elif ext == ".flac":
        audio = FLAC(dst)
        for ramka in (zrodlo.values() if zrodlo is not None else []):
            nazwa = getattr(ramka, "FrameID", "")
            tekst = [str(t) for t in (getattr(ramka, "text", None) or []) if str(t).strip()]
            if not tekst:
                continue
            if nazwa in _ID3_NA_VORBIS:
                audio[_ID3_NA_VORBIS[nazwa]] = tekst
            elif nazwa == "COMM":
                audio["COMMENT"] = tekst
            elif nazwa == "TXXX" and getattr(ramka, "desc", ""):
                audio[ramka.desc.upper()] = tekst
        audio["TITLE"] = title
        if artist:
            audio["ARTIST"] = artist
        if cover:
            audio.clear_pictures()
            pic = Picture()
            pic.type, pic.mime, pic.desc = 3, "image/jpeg", "Cover"
            pic.data = cover
            audio.add_picture(pic)
        audio.save()


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #

def _szacuj_rozmiar(src: str, convert_wav: str | None) -> int:
    """Ile bajtów zajmie plik na nośniku (z zapasem na klaster)."""
    rozmiar = os.path.getsize(src)
    if src.lower().endswith(".wav") and convert_wav == "flac":
        rozmiar = int(rozmiar * 0.75)       # FLAC zwykle 50–70% WAV; bierzemy ostrożnie
    return rozmiar + ZAPAS_NA_PLIK


def plan(zrodla: list[str], dest_folder: str, convert_wav: str | None = "aiff") -> dict:
    """Policz, ile miejsca potrzeba i ile jest na nośniku (bez kopiowania)."""
    audio = [p for p in zrodla if p.lower().endswith(AUDIO_EXT)]
    potrzeba = sum(_szacuj_rozmiar(p, convert_wav) for p in audio if os.path.isfile(p))
    potrzeba += ZAPAS_STALY if audio else 0
    wolne = None
    cel = dest_folder
    while cel and not os.path.exists(cel):          # nośnik może nie mieć jeszcze folderu
        nadrzedny = os.path.dirname(cel)
        if nadrzedny == cel:
            break
        cel = nadrzedny
    try:
        wolne = shutil.disk_usage(cel).free if cel else None
    except OSError:
        wolne = None
    return {"utworow": len(audio), "potrzeba_bajtow": potrzeba, "wolne_bajtow": wolne,
            "miesci_sie": wolne is None or potrzeba <= wolne}


def _usun_appledouble(dest_folder: str, nazwy: list[str]) -> int:
    """Usuń „._nazwa" dla plików zapisanych w tym przebiegu.

    Na FAT32/exFAT macOS trzyma w nich rozszerzone atrybuty (każdy nowy
    plik dostaje com.apple.provenance). Najpierw zdejmujemy atrybuty z
    samego pliku (system wtedy sam sprząta), potem kasujemy to, co zostało.
    """
    usuniete = 0
    for nazwa in nazwy:
        path = os.path.join(dest_folder, nazwa)
        try:
            for atr in os.listxattr(path):
                try:
                    os.removexattr(path, atr)
                except OSError:
                    pass
        except (OSError, AttributeError):
            pass
        kropka = os.path.join(dest_folder, "._" + nazwa)
        if os.path.lexists(kropka):
            try:
                os.remove(kropka)
                usuniete += 1
            except OSError:
                pass
    return usuniete


def prepare(
    src_folder: str | None,
    dest_folder: str,
    convert_wav: str | None = "aiff",
    on_progress: Callable[[int, int, str], None] | None = None,
    pliki: list[str] | None = None,
    numeruj: bool = False,
) -> UsbReport:
    """Copy/convert audio into a flat, CDJ-ready dest_folder.

    Źródło: `pliki` (lista ścieżek — set, playlista, cała biblioteka
    z podfolderami) albo, gdy jej brak, pliki leżące bezpośrednio
    w src_folder (dotfiles '._*', '.DS_Store' są pomijane).
    `numeruj=True` dodaje numer pozycji („01 Artysta - Tytuł") — CDJ
    sortuje folder po nazwie, więc tylko tak zostaje kolejność setu.

    convert_wav: "aiff" (default) or "flac" — target for WAV files;
    None copies WAV unchanged. on_progress, when given, is called after
    each source file as on_progress(done, total, source_name).

    Rzuca BrakMiejsca, ZANIM cokolwiek skopiuje, gdy całość się nie
    zmieści; gdy miejsce skończy się w trakcie (ENOSPC), przerywa —
    reszta trafia do pominiętych z powodem.
    """
    if convert_wav is not None:
        convert_wav = convert_wav.lower().lstrip(".")
        if convert_wav not in ("aiff", "flac"):
            raise ValueError(
                f"convert_wav musi być 'aiff', 'flac' albo None, nie {convert_wav!r}"
            )

    if pliki is None:
        entries = [
            os.path.join(src_folder, name)
            for name in sorted(os.listdir(src_folder), key=str.lower)
            if not name.startswith(".")  # no ._ forks, no .DS_Store
            and os.path.isfile(os.path.join(src_folder, name))
        ]
    else:
        entries = [p for p in pliki if os.path.isfile(p)
                   and not os.path.basename(p).startswith(".")]

    os.makedirs(dest_folder, exist_ok=True)
    p = plan(entries, dest_folder, convert_wav)
    if not p["miesci_sie"]:
        mb = 1024 * 1024
        raise BrakMiejsca(
            errno.ENOSPC,
            f"na nośniku jest {p['wolne_bajtow'] / mb:.0f} MB wolnego, a te utwory "
            f"potrzebują ok. {p['potrzeba_bajtow'] / mb:.0f} MB — nic nie skopiowałem. "
            "Zwolnij miejsce albo wybierz mniejszy set.")

    report = UsbReport()
    taken: set[str] = set()
    zapisane: list[str] = []
    szer = max(2, len(str(len(entries))))

    for done, src in enumerate(entries, start=1):
        name = os.path.basename(src)
        ext = os.path.splitext(name)[1].lower()
        try:
            if report.przerwano:
                report.skipped.append((name, report.przerwano))
                continue
            if ext not in AUDIO_EXT:
                report.skipped.append((name, "to nie plik audio"))
                continue

            stem = _dest_stem(src, ext)
            if numeruj:
                stem = f"{done:0{szer}d} {stem}"
            converting = ext == ".wav" and convert_wav is not None
            dst = _unique_dest(dest_folder, stem,
                               "." + convert_wav if converting else ext, taken)
            try:
                if converting:
                    artist, title = _artist_title(src)
                    _convert_wav(src, dst)
                    _retag_converted(src, dst, artist, title)
                else:
                    # copyfile = data fork only; copy2 could drag metadata along
                    shutil.copyfile(src, dst)
            except (RuntimeError, OSError) as exc:
                if os.path.exists(dst):
                    os.remove(dst)
                kropka = os.path.join(dest_folder, "._" + os.path.basename(dst))
                if os.path.lexists(kropka):
                    os.remove(kropka)
                brak_miejsca = (getattr(exc, "errno", None) == errno.ENOSPC
                                or "No space left" in str(exc))
                if brak_miejsca:
                    # dalsze zapisy na pełny FAT32 kończyły się uszkodzonymi
                    # wpisami katalogu — przerywamy od razu
                    report.przerwano = "brak miejsca na nośniku — przerwano kopiowanie"
                    report.skipped.append((name, report.przerwano))
                else:
                    report.skipped.append((name, f"{'konwersja' if converting else 'kopiowanie'} nieudane: {exc}"))
                continue
            (report.converted if converting else report.copied).append(dst)
            report.pary.append((src, dst))
            zapisane.append(os.path.basename(dst))
            report.total_bytes += os.path.getsize(dst)
        finally:
            if on_progress is not None:
                on_progress(done, len(entries), name)

    report.usuniete_appledouble = _usun_appledouble(dest_folder, zapisane)
    return report


# --------------------------------------------------------------------------- #
# weryfikacja po skopiowaniu
# --------------------------------------------------------------------------- #

def _suma(path: str, blok: int = 1024 * 1024, z_nosnika: bool = False) -> str:
    """SHA-1 zawartości pliku. Szybsze niż SHA-256, a do wykrycia
    przekłamanego kopiowania w zupełności wystarczy.

    `z_nosnika` — dla pliku na pendrivie: najpierw fsync (dane naprawdę
    zapisane), potem odczyt z wyłączonym buforowaniem (F_NOCACHE na macOS),
    żeby jak najmniej czytać z pamięci podręcznej zamiast z nośnika.
    """
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        if z_nosnika:
            try:
                os.fsync(fh.fileno())
                import fcntl
                fcntl.fcntl(fh.fileno(), getattr(fcntl, "F_NOCACHE", 48), 1)
            except (OSError, ImportError, ValueError):
                pass
        while True:
            kawalek = fh.read(blok)
            if not kawalek:
                break
            h.update(kawalek)
    return h.hexdigest()


def zweryfikuj(pary: list[tuple[str, str]],
               on_progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Sprawdź, czy pliki na pendrive są identyczne ze źródłem.

    Pendrive'y potrafią zapisać plik po cichu uszkodzony — zwłaszcza gdy
    wyjmie się go bez odmontowania. Ucięty albo przekłamany plik na CDJ-u
    kończy się przerwaniem odtwarzania w środku setu, więc lepiej
    dowiedzieć się o tym w domu.

    `pary` to lista (źródło, cel). Kopie WAV→AIFF/FLAC mają z założenia
    inną zawartość — porównujemy wtedy długość nagrania (±0,1 s); gdy
    źródła nie da się odczytać, wystarcza niepusty cel.
    """
    zgodne, rozne, brakujace = [], [], []
    for i, (src, dst) in enumerate(pary, start=1):
        if on_progress:
            on_progress(i, len(pary), os.path.basename(dst))
        if not os.path.isfile(dst):
            brakujace.append(dst)
            continue
        try:
            if os.path.splitext(src)[1].lower() != os.path.splitext(dst)[1].lower():
                # plik przekonwertowany — porównanie bajt w bajt nie ma sensu
                (zgodne if _ta_sama_dlugosc(src, dst) else rozne).append(dst)
                continue
            if os.path.getsize(src) != os.path.getsize(dst):
                rozne.append(dst)
                continue
            (zgodne if _suma(src) == _suma(dst, z_nosnika=True) else rozne).append(dst)
        except OSError:
            rozne.append(dst)
    return {"sprawdzonych": len(pary), "zgodne": len(zgodne),
            "rozne": rozne, "brakujace": brakujace,
            "ok": not rozne and not brakujace}


def _dlugosc(path: str) -> float | None:
    try:
        a = MutagenFile(path)
        return float(a.info.length) if a is not None and a.info.length else None
    except Exception:  # noqa: BLE001
        return None


def _ta_sama_dlugosc(src: str, dst: str) -> bool:
    if os.path.getsize(dst) <= 0:
        return False
    d_src = _dlugosc(src)
    if d_src is None:
        return True                         # źródła nie umiemy zmierzyć
    d_dst = _dlugosc(dst)
    return d_dst is not None and abs(d_src - d_dst) <= 0.1
