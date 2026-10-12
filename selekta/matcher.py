"""Match Spotify tracks to local audio files.

Scoring combines token overlap (filename + existing tags), duration
agreement, and mix-version awareness (an Extended Mix must not match
a Radio Edit silently).

O tym, czy plik JEST utworem z playlisty, rozstrzyga porównanie
strukturalne (wykonawca, tytuł bez dopisków, wersja + czas) — patrz
sekcja „TOŻSAMOŚĆ UTWORU" i :func:`lane`.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

from mutagen import File as MutagenFile

from .spotify import Track

AUDIO_EXT = (".flac", ".mp3", ".wav", ".aiff", ".m4a", ".ogg")

MIX_WORDS = {
    "extended", "radio", "club", "dub", "vip", "remix", "rmx", "bootleg",
    "edit", "rework", "instrumental", "acapella",
}
NOISE = {
    "original", "mix", "feat", "ft", "featuring", "the", "and", "www", "pl",
    "com", "flac", "mp3", "wav",
}


def normalize(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in NOISE]


def mix_signature(tokens: list[str]) -> frozenset[str]:
    return frozenset(t for t in tokens if t in MIX_WORDS)


@dataclass
class Candidate:
    path: str
    score: float
    duration_delta: float | None
    reason: str
    identity: float = 0.0       # zgodność artysty+tytułu BEZ słów o wersji
    same_version: bool = True   # czy wersja miksu też się zgadza
    # Czy to TEN SAM UTWÓR (ten sam wykonawca i tytuł) — niezależnie od
    # wersji. Dopiero to wolno pokazać jako „masz" albo jako propozycję
    # „inna wersja"; cudzy utwór nigdy nie trafia do setu.
    same_track: bool = False
    file_duration: float | None = None   # czas pliku z biblioteki


def _tag(audio, keys: tuple[str, ...]) -> str:
    """Pierwsza niepusta wartość spośród kluczy tagów (FLAC/ID3/MP4)."""
    for key in keys:
        try:
            val = audio.get(key) if hasattr(audio, "get") else None
            if val is None and getattr(audio, "tags", None) is not None \
                    and hasattr(audio.tags, "get"):
                val = audio.tags.get(key)
        except Exception:  # noqa: BLE001 — egzotyczne tagi nie mogą wywalić indeksu
            val = None
        if val:
            if isinstance(val, list):
                val = val[0] if val else ""
            text = str(getattr(val, "text", [val])[0] if hasattr(val, "text") else val)
            if text.strip():
                return text.strip()
    return ""


_TITLE_KEYS = ("TITLE", "title", "TIT2", "\xa9nam")
_ARTIST_KEYS = ("ARTIST", "artist", "TPE1", "\xa9ART")


def _file_info(path: str) -> tuple[list[str], float | None, dict]:
    """Tokeny pliku (jak dawniej), czas trwania i osobno tagi tytułu/artysty.

    Osobne pola są potrzebne do rozstrzygnięcia TOŻSAMOŚCI: worek słów
    z nazwy i tagów nie odróżniał „Michael Jackson — Beat It" od
    „Linds — Kick It" (wspólne „it" + zgodny czas wystarczały).
    """
    tokens = normalize(os.path.splitext(os.path.basename(path))[0])
    duration = None
    info = {"title": "", "artist": ""}
    try:
        audio = MutagenFile(path)
        if audio is not None:
            duration = getattr(audio.info, "length", None)
            for key in ("TITLE", "ARTIST"):
                val = audio.get(key) if hasattr(audio, "get") else None
                if val:
                    tokens += normalize(str(val[0] if isinstance(val, list) else val))
            if getattr(audio, "tags", None) and hasattr(audio.tags, "get"):
                for key in ("TIT2", "TPE1"):
                    if audio.tags.get(key):
                        tokens += normalize(str(audio.tags[key]))
            info["title"] = _tag(audio, _TITLE_KEYS)
            info["artist"] = _tag(audio, _ARTIST_KEYS)
            if info["title"]:
                tokens += [t for t in normalize(info["title"]) if t not in tokens]
            if info["artist"]:
                tokens += [t for t in normalize(info["artist"]) if t not in tokens]
    except Exception:
        pass
    return tokens, duration, info


def _file_tokens(path: str) -> tuple[list[str], float | None]:
    tokens, duration, _info = _file_info(path)
    return tokens, duration


# ======================================================================
# TOŻSAMOŚĆ UTWORU: wykonawca + tytuł + wersja
# ======================================================================
# Dawniej o „masz to" decydował worek słów: wspólne „it", zgodny czas i brak
# dopisku wersji dawały „Michael Jackson — Beat It" → „Linds — Kick It.wav",
# a „Una Hora Menos" → „Una Hora Más". Teraz porównujemy osobno:
#   1. tytuł bez dopisków (wszystkie istotne słowa, żadnych cudzych),
#   2. wykonawcę (choć jeden z wymienionych musi się zgadzać w całości),
#   3. wersję: nazwane dopiski (remiks, „Techno Mix", „Escape Into Hyper
#      Space") muszą być te same, a o długości (radio/extended) rozstrzyga
#      czas trwania.
# Do „masz" i do setu trafia tylko ten sam utwór w tej samej wersji. Ten sam
# utwór w innej wersji to propozycja do decyzji użytkownika. Reszta — brak.

# Różnica czasu, ponad którą to już INNA wersja. Wydania tego samego nagrania
# różnią się ciszą na końcu o 1–3 s; remiks czy wersja radiowa o dziesiątki.
SAME_VERSION_MAX_DELTA_S = 5.0
# Tyle znaczy „ten sam czas": wtedy „Original Mix" = „Extended Mix" itp.
EQUAL_LENGTH_S = 3.0

# słowa, po których poznajemy dopisek o WERSJI (a nie część tytułu)
_VERSION_HINTS = MIX_WORDS | {
    "mix", "remix", "version", "remaster", "remastered", "live", "acoustic",
    "unplugged", "demo", "reprise", "karaoke", "original", "mono", "stereo",
    "edition", "intro", "outro", "flip", "mashup", "remake", "session",
    "sessions", "rerecorded", "mixed", "single", "album", "explicit", "clean",
    "deluxe", "anniversary", "vocal", "short", "rmx", "remixed", "version",
}
# słowa, które nic nie mówią o wersji (to samo nagranie)
_GENERIC_VER = {
    "original", "mix", "version", "album", "single", "remaster", "remastered",
    "mono", "stereo", "explicit", "clean", "digital", "edition", "deluxe",
    "bonus", "track", "anniversary", "expanded", "special", "re", "master",
    "mastered", "lp", "from", "the", "and", "of", "a", "with", "by", "in",
    "on", "official", "audio", "remasterd", "feat", "ft", "featuring",
}
# słowa o DŁUGOŚCI wersji — tu rozstrzyga czas trwania, nie nazwa
_LENGTH_VER = {"extended", "radio", "edit", "club", "short", "long", "full",
               "length", "cut", "inch"}
# dopiski, które są śmieciem z serwisu albo nazwy pliku
_JUNK_WORDS = {"www", "com", "org", "net", "official", "video", "audio",
               "lyrics", "lyric", "hd", "hq", "4k", "visualizer", "visualiser",
               "explicit", "clean", "mv", "m", "v"}
_JUNK_MARKERS = {"www", "com", "org", "net", "video", "lyrics", "lyric",
                 "visualizer", "visualiser"}
_SYNONYMS = {"rmx": "remix", "remixed": "remix", "accapella": "acapella",
             "acappella": "acapella", "instr": "instrumental", "ext": "extended"}
# słowa, które w końcówce tytułu bez nawiasu też oznaczają wersję
_TRAIL_VER = {"extended", "remix", "rmx", "radio", "edit", "club", "dub",
              "vip", "bootleg", "rework", "instrumental", "acapella", "mix",
              "original", "version"}
_ARTIST_NOISE = {"dj", "mc"}
# etykiety składanek w nazwach folderów — to nie wykonawca
_NOT_ARTISTS = {"va", "v.a.", "various", "various artists", "unknown",
                "unknown artist", "compilation", "soundtrack", "ost"}

_GROUP_RE = re.compile(r"[\(\[\{]([^\(\)\[\]\{\}]*)[\)\]\}]")
_DASH_RE = re.compile(r"\s+[-–—]\s+")
_FEAT_START_RE = re.compile(r"^\s*(?:feat\.?|ft\.?|featuring|with)\s+", re.I)
_FEAT_INLINE_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+", re.I)
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|;|&|/|\+|\bfeat\.?|\bft\.?|\bfeaturing\b|\bvs\.?|\bx\b|\bwith\b)\s*",
    re.I)
_TRACKNO_RE = re.compile(r"^\s*(?:\d{1,2}[-.]\d{1,3}|\d{1,4})(?:\s*[.\-_)]\s*|\s+)(?=\S)")
_CAMELOT_RE = re.compile(r"^\d{1,2}[ab]$")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    # „Can't" i „Cant" to to samo słowo — apostrof nie może go rozbijać
    return re.sub(r"['’`´]", "", s)


def _raw_words(s: str) -> list[str]:
    """Słowa bez diakrytyków i apostrofów, BEZ odsiewu szumu."""
    return [_SYNONYMS.get(t, t) for t in re.split(r"[^a-z0-9]+", _fold(s)) if t]


def _words(s: str) -> list[str]:
    """Istotne słowa (bez szumu: the/and/feat/original/mix…)."""
    return [t for t in _raw_words(s) if t not in NOISE]


def _artist_names(artist: str) -> list[frozenset[str]]:
    """„Madonna, Justin Timberlake & Timbaland" → [{madonna}, {justin,…}, …]."""
    out = []
    for part in _ARTIST_SPLIT_RE.split(artist or ""):
        toks = frozenset(t for t in _words(part)
                         if t not in _ARTIST_NOISE and not t.isdigit())
        if toks and toks not in out:
            out.append(toks)
    return out


@dataclass
class _Title:
    core: list[str]            # tytuł bez dopisków
    extra: list[str]           # dopiski w nawiasie, które nie mówią o wersji
    ver: list[str]             # dopiski o wersji
    feat: list[str]            # goście z „(feat. …)"


def _parse_title(title: str) -> _Title:
    feat: list[str] = []
    ver: list[str] = []
    extra: list[str] = []

    def klasyfikuj(inner: str) -> None:
        inner = inner.strip()
        if not inner:
            return
        if _FEAT_START_RE.match(inner):
            feat.append(_FEAT_START_RE.sub("", inner))
            return
        raw = _raw_words(inner)
        if not raw:
            return
        istotne = [t for t in raw if t not in NOISE and not t.isdigit()]
        if (set(raw) & _JUNK_MARKERS) or (
                istotne and all(t in _JUNK_WORDS for t in istotne)):
            return                     # „[www.dj-promo.org]", „(Official Video)"
        if set(raw) & _VERSION_HINTS:
            ver.extend(raw)
        elif all(t.isdigit() for t in raw):
            ver.extend(raw)            # „(2025)" — rok wydania
        else:
            extra.extend(t for t in raw if t not in NOISE)

    s = title or ""
    # zagnieżdżone nawiasy: zdejmujemy od środka
    for _ in range(3):
        nowe = _GROUP_RE.sub(lambda m: (klasyfikuj(m.group(1)), " ")[1], s)
        if nowe == s:
            break
        s = nowe
    # „Tytuł - Radio Edit", „Tytuł - Remastered 1996", „Tytuł - X Remix"
    parts = _DASH_RE.split(s)
    while len(parts) > 1 and (set(_raw_words(parts[-1])) & _VERSION_HINTS
                              or _FEAT_START_RE.match(parts[-1])):
        klasyfikuj(parts.pop())
    s = " - ".join(parts)
    # „Tytuł feat. Gość" bez nawiasu
    bits = _FEAT_INLINE_RE.split(s, maxsplit=1)
    if len(bits) == 2:
        s, gosc = bits
        feat.append(gosc)
    core = _words(s)
    # „On The Beat Extended Mix" — wersja dopisana bez nawiasu
    raw = _raw_words(s)
    tail = []
    while len(raw) > 1 and raw[-1] in _TRAIL_VER:
        tail.insert(0, raw.pop())
    if tail:
        ver = tail + ver
        core = [t for t in raw if t not in NOISE]
    return _Title(core=core, extra=extra, ver=ver, feat=feat)


@dataclass
class _Want:
    names: list[frozenset[str]]      # główni wykonawcy
    all_artist: set[str]             # wszystkie słowa wykonawców (z gośćmi)
    title: _Title
    duration: float | None


def _want(track: Track) -> _Want:
    names = _artist_names(track.artist)
    title = _parse_title(track.title)
    all_artist = {t for n in names for t in n}
    for g in title.feat:
        for n in _artist_names(g):
            all_artist |= n
    return _Want(names=names, all_artist=all_artist, title=title,
                 duration=track.duration_s or None)


@dataclass
class _View:
    artist: set[str]                 # słowa wykonawcy (tag / nazwa pliku)
    evidence: set[str]               # wszystko, co może potwierdzić wykonawcę
    title: _Title
    folder: set[str]                 # słowa nazwy folderu (tylko na „tak")
    named: bool                      # czy plik w ogóle podaje wykonawcę


def _split_stem(stem: str) -> tuple[str, str]:
    """„03. Laherte - Speeding (Original Mix)" → („Laherte", „Speeding (…)")."""
    s = _TRACKNO_RE.sub("", stem, count=1).strip()
    s = s.replace("_", " ")
    parts = _DASH_RE.split(s)
    if len(parts) >= 3 and parts[0].isdigit():
        parts = parts[1:]
    if len(parts) >= 2:
        return parts[0].strip(), " - ".join(p.strip() for p in parts[1:])
    return "", s


def _views(path: str, info: dict) -> list[_View]:
    """Sposoby odczytania pliku: z tagów i z nazwy (bierzemy najlepszy)."""
    out: list[_View] = []
    stem = os.path.splitext(os.path.basename(path))[0]
    f_artist, f_title = _split_stem(stem)
    t_artist, t_title = info.get("artist", ""), info.get("title", "")
    folder = os.path.basename(os.path.dirname(path))

    zrodla = ({x for n in _artist_names(t_artist) for x in n}
              | {x for n in _artist_names(f_artist) for x in n})
    # „Madonna - Confessions/01 - Hung Up.flac" bez tagów: nazwa folderu może
    # POTWIERDZIĆ wykonawcę, ale sama obecność słów niczego nie wyklucza —
    # chyba że folder ma postać „Wykonawca - Album" (wtedy to deklaracja)
    folder_words = {x for x in _words(folder) if not x.isdigit()}
    folder_artist, _album = _split_stem(folder)
    if folder_artist.strip().lower() in _NOT_ARTISTS:
        folder_artist = ""
    folder_claim = {x for n in _artist_names(folder_artist) for x in n}

    def view(artist: str, title: str) -> _View:
        t = _parse_title(title)
        a = {x for n in _artist_names(artist) for x in n}
        for g in t.feat:
            a |= {x for n in _artist_names(g) for x in n}
        # artysta bywa w obu źródłach — tag „Maddix", plik „Maddix; Feles";
        # remikser i „Jimmy Sax version" też potwierdzają wykonawcę
        ev = set(a) | set(t.ver) | set(t.extra) | zrodla
        return _View(artist=a, evidence=ev, title=t, folder=folder_words,
                     named=bool(a or zrodla or folder_claim))

    if t_title:
        out.append(view(t_artist, t_title))
        # tytuł w tagu bywa „Wykonawca - Tytuł" (zgrania z YouTube/SoundCloud)
        a2, t2 = _split_stem(t_title)
        if a2 and t2:
            out.append(view(a2, t2))
    out.append(view(f_artist, f_title))
    return out


def _title_variants(t: _Title) -> list[tuple[set[str], list[str]]]:
    """(rdzeń tytułu, dopiski do porównania wersji) — z dopiskiem w nawiasie
    potraktowanym raz jako opis wersji, raz jako część tytułu."""
    core = set(t.core)
    out = [(core, t.ver + t.extra)]
    if t.extra:
        out.append((core | set(t.extra), list(t.ver)))
    return out


def _same_title(cw: set[str], ch: set[str], artist_words: set[str]) -> bool:
    if not cw:
        return False
    # numer ścieżki, rok, tonacja z nazwy pliku („Gucci - 8A - 146")
    ch = {t for t in ch if t in cw or not (t.isdigit() or _CAMELOT_RE.match(t))}
    brak = cw - ch
    nadmiar = ch - cw
    # słowa wykonawcy wplecione w tytuł („Remon Verhoeve - I Wanna Feel")
    return not (brak - artist_words) and not (nadmiar - artist_words) \
        and bool(cw - artist_words)


def _version_words(words: list[str], artist_words: set[str]) -> tuple[frozenset, frozenset]:
    """Dopisek wersji → (nazwane słowa, słowa o długości)."""
    named, length = set(), set()
    for t in words:
        t = _SYNONYMS.get(t, t)
        if t in artist_words or t in _GENERIC_VER or t.isdigit():
            continue
        (length if t in _LENGTH_VER else named).add(t)
    return frozenset(named), frozenset(length)


def _compare(want: _Want, view: _View, duration: float | None) -> tuple[int, float]:
    """Werdykt dla jednego odczytu pliku: 2 = ten sam utwór i wersja,
    1 = ten sam utwór w innej wersji, 0 = inny utwór. Drugi element to
    pewność tytułu (do rozstrzygania remisów)."""
    artist_words = want.all_artist | view.artist
    dopasowanie = None
    for cw, dw in _title_variants(want.title):
        for ch, dh in _title_variants(view.title):
            if _same_title(cw, ch, artist_words):
                dopasowanie = (dw, dh)
                break
        if dopasowanie:
            break
    if not dopasowanie:
        return 0, 0.0
    dw, dh = dopasowanie

    names = want.names or ([frozenset(want.all_artist)] if want.all_artist else [])
    if not names:
        artist_known = False           # źródło nie podało wykonawcy
    elif any(n <= (view.evidence | view.folder) for n in names):
        artist_known = True
    elif view.named:
        return 0, 0.0                  # ten sam tytuł, ale cudzy wykonawca
    else:
        artist_known = False           # plik nie mówi, czyj jest

    nw, lw = _version_words(dw, artist_words)
    nh, lh = _version_words(dh, artist_words)
    delta = (abs(duration - want.duration)
             if (duration and want.duration) else None)
    if nw != nh:
        same_version = False           # remiks, „Techno Mix", inna sesja…
    elif delta is not None:
        if delta > SAME_VERSION_MAX_DELTA_S:
            same_version = False       # inna długość = inna wersja
        else:
            same_version = lw == lh or delta <= EQUAL_LENGTH_S
    else:
        same_version = lw == lh

    if not artist_known:
        # Plik bez żadnej informacji o wykonawcy: wolno go uznać tylko przy
        # zgodnym tytule, wersji i czasie co do sekund. Propozycji „inna
        # wersja" z anonimowego pliku nie robimy — to mógłby być cudzy utwór.
        if same_version and delta is not None and delta <= EQUAL_LENGTH_S:
            return 2, 1.0
        return 0, 0.0
    return (2 if same_version else 1), 1.0


def _judge(want: _Want, path: str, info: dict, duration: float | None) -> int:
    best = 0
    for v in _views(path, info):
        verdict, _ = _compare(want, v, duration)
        best = max(best, verdict)
        if best == 2:
            break
    return best


def verdict_for_name(track: Track, path: str, duration: float | None) -> int:
    """Werdykt tożsamości dla pliku znanego tylko z nazwy i ścieżki
    (wynik z Soulseeka): 2 = ten sam utwór i wersja, 1 = ten sam utwór
    w innej wersji, 0 = inny utwór.

    Artysta bywa w dowolnym folderze ścieżki („Madonna/Confessions on
    a Dance Floor/1-01 Hung Up.flac"), więc wszystkie foldery mogą go
    POTWIERDZIĆ — ten sam ranking tożsamości co dopasowanie do biblioteki.
    """
    path = (path or "").replace("\\", "/")
    chce = _want(track)
    foldery = {x for part in path.split("/")[:-1] for x in _words(part)
               if not x.isdigit()}
    best = 0
    for v in _views(path, {"title": "", "artist": ""}):
        v.folder |= foldery
        best = max(best, _compare(chce, v, duration)[0])
        if best == 2:
            break
    return best


def _score_tokens(track: Track, want: list[str], have: list[str],
                  duration: float | None, path: str) -> Candidate:
    overlap = len(set(want) & set(have)) / len(set(want))
    score = overlap

    # Tożsamość liczona BEZ słów opisujących wersję ("extended", "radio"...).
    # Dzięki temu „Flashback (Radio Edit)" rozpoznaje posiadany
    # „Flashback (Extended Mix)" jako TEN SAM utwór w innej wersji,
    # zamiast raportować go jako brakujący.
    core_want = {t for t in want if t not in MIX_WORDS}
    core_have = {t for t in have if t not in MIX_WORDS}
    identity = (len(core_want & core_have) / len(core_want)) if core_want else 0.0

    delta = None
    if track.duration_s and duration:
        delta = abs(duration - track.duration_s)
        if delta <= 3:
            score += 0.25          # same edit, near-certain confirmation
        elif delta > 45:
            score -= 0.15          # probably a different mix/version

    want_mix, have_mix = mix_signature(want), mix_signature(have)
    if want_mix == have_mix:
        score += 0.1
    elif want_mix and have_mix and not (want_mix & have_mix):
        score -= 0.3               # e.g. asked for remix, file is radio edit

    return Candidate(path, round(score, 3), delta, f"overlap={overlap:.2f}",
                     identity=round(identity, 3),
                     same_version=(want_mix == have_mix),
                     file_duration=duration)


def _with_identity(c: Candidate, verdict: int) -> Candidate:
    c.same_track = verdict >= 1
    c.same_version = verdict == 2
    return c


def score_file(track: Track, path: str) -> Candidate:
    want = normalize(track.artist) + normalize(track.title)
    have, duration, info = _file_info(path)
    if not want or not have:
        return Candidate(path, 0.0, None, "no tokens", same_version=False)
    c = _score_tokens(track, want, have, duration, path)
    return _with_identity(c, _judge(_want(track), path, info, duration))


def lane(c: Candidate | None) -> str:
    """Pas importu: „auto" (masz — ten sam utwór i wersja), „version" (masz
    ten utwór, ale w innej wersji — decyzja użytkownika) albo „missing"."""
    if c is None or not c.same_track:
        return "missing"
    return "auto" if c.same_version else "version"


SKIP_DIRS = {"_selekta_kosz"}


def format_rank(path: str) -> int:
    """Im mniej, tym lepiej — kolejność przydatności dla DJ-a.

    Rozstrzyga remisy, gdy ten sam utwór leży w bibliotece w kilku
    formatach. FLAC przed WAV, bo niesie tagi i okładkę; bezstratne
    przed stratnym.
    """
    ext = os.path.splitext(path)[1].lower()
    return {".flac": 0, ".aiff": 1, ".aif": 1, ".wav": 2,
            ".m4a": 3, ".mp3": 4}.get(ext, 5)


def audio_files(folder: str, kopie_w_setach: bool = False) -> list[str]:
    """Utwory biblioteki — RÓWNIEŻ w podfolderach, ale bez kopii z setów.

    Soulseek i Nicotine+ zapisują pobrania do katalogów albumów
    (``downloads/Nazwa albumu/01 utwor.flac``), więc płaskie listowanie
    gubiło większość świeżo pobranych utworów: nie było ich ani w
    bibliotece, ani w dopasowaniu, ani w eksporcie. Pomijamy katalogi
    ukryte i kosz.

    Foldery setów (katalog z ``_selekta.json``) trzymają KOPIE utworów
    z biblioteki. Liczone osobno zawyżały bibliotekę (277 plików przy
    ~79 utworach), dublowały listę i kolejność, a „Usuń duplikaty” chciało
    je wyrzucić do kosza. Każdy utwór występuje tu raz; utwór, który leży
    tylko w setach, reprezentuje jedna jego kopia (szczegóły: ``uklad``).
    ``kopie_w_setach=True`` zwraca wszystkie pliki, łącznie z kopiami.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"nie ma folderu: {folder}")
    from .uklad import wczytaj
    u = wczytaj(folder)
    return list(u.wszystkie if kopie_w_setach else u.utwory)


def resolve_in_library(folder: str, name: str) -> str | None:
    """Znajdź plik po samej nazwie — gdziekolwiek w bibliotece leży."""
    if os.path.isabs(name) and os.path.isfile(name):
        return name
    base = os.path.basename(name)
    direct = os.path.join(folder, base)
    if os.path.isfile(direct):
        return direct
    for p in audio_files(folder):
        if os.path.basename(p) == base:
            return p
    for p in audio_files(folder, kopie_w_setach=True):   # kopia w secie
        if os.path.basename(p) == base:
            return p
    return None


def best_match(track: Track, folder: str, threshold: float = 0.6,
               allow_version: bool = False) -> Candidate | None:
    """Plik z biblioteki, który JEST tym utworem — albo None.

    Używane przez CLI (organize/match/hunt/check/export). Dawniej brało
    najwyższy wynik ≥ 0,6 bez sprawdzenia wersji i wykonawcy: `organize`
    oznaczał „✓ Frozen ← Like a Prayer", a z --apply przemianowałby cudzy
    plik. Teraz ten sam utwór w tej samej wersji (albo, gdy wołający
    wyraźnie pozwoli, w innej wersji tego samego utworu).
    """
    c = classify_track(track, library_index(folder))
    if c is None or c.score < threshold:
        return None
    pas = lane(c)
    if pas == "auto" or (allow_version and pas == "version"):
        return c
    return None


class IndexEntry(tuple):
    """Wpis indeksu: (ścieżka, tokeny, czas) jak dawniej, plus tagi w .info."""

    def __new__(cls, path: str, tokens: list[str], duration: float | None,
                info: dict | None = None):
        obj = super().__new__(cls, (path, tokens, duration))
        obj.info = info or {}
        return obj

    def __reduce__(self):
        return (IndexEntry, (self[0], self[1], self[2], self.info))


def _entry(p: str) -> IndexEntry:
    have, dur, info = _file_info(p)
    return IndexEntry(p, have, dur, info)


def index_paths(paths: list[str]) -> list[IndexEntry]:
    """Indeks ograniczony do podanych plików — do sprawdzania, czy utwór
    JUŻ jest na playliście, bez przeszukiwania całej biblioteki."""
    return [_entry(p) for p in paths]


def library_index(folder: str) -> list[IndexEntry]:
    """Precompute (path, tokens, duration) once so a whole playlist can be
    scored without re-reading every file's tags per track."""
    return [_entry(p) for p in audio_files(folder)]


def _entry_info(entry) -> dict:
    info = getattr(entry, "info", None)
    if info is None:                 # indeks złożony ręcznie z krotek
        _t, _d, info = _file_info(entry[0])
    return info


def _entry_views(entry) -> list:
    info = _entry_info(entry)
    if "_views" not in info:
        info["_views"] = _views(entry[0], info)
    return info["_views"]


def _pick_key(c: "Candidate") -> tuple:
    """Klucz wyboru kandydata: najpierw TOŻSAMOŚĆ (ten sam utwór w tej
    samej wersji > ten sam w innej > reszta), potem zgodność czasu.
    Przy remisie decyduje format, a na końcu ścieżka — żeby wybór był
    powtarzalny, a nie zależny od kolejności listowania katalogów."""
    verdict = (2 if c.same_version else 1) if c.same_track else 0
    delta = c.duration_delta if c.duration_delta is not None else 999.0
    # w granicach „tego samego czasu" różnice ułamków sekundy nie rozstrzygają
    # — wtedy decyduje format (FLAC przed WAV tego samego nagrania)
    if delta <= EQUAL_LENGTH_S:
        delta = 0.0
    return (verdict, c.identity, c.score, -delta, -format_rank(c.path), c.path)


def classify_track(track: Track, index) -> Candidate | None:
    """Najlepszy kandydat z gotowego indeksu biblioteki (bez progu).

    Wyboru dokonujemy po TOŻSAMOŚCI (artysta + tytuł bez słów o wersji),
    a dopiero potem po wyniku. Inaczej kara za inną wersję miksu spycha
    właściwy plik poniżej przypadkowego utworu — „Flashback (Radio Edit)"
    dopasowywał się do zupełnie obcego kawałka zamiast do posiadanego
    „Flashback (Extended Mix)".

    Kandydat ma ustawione ``same_track`` i ``same_version``; o pasie
    importu decyduje :func:`lane` — sam wynik liczbowy już nie.
    """
    want = normalize(track.artist) + normalize(track.title)
    if not want:
        return None
    chce = _want(track)
    best = None
    for entry in index:
        path, have, duration = entry[0], entry[1], entry[2]
        if not have:
            continue
        c = _score_tokens(track, want, have, duration, path)
        verdict = 0
        for v in _entry_views(entry):
            verdict = max(verdict, _compare(chce, v, duration)[0])
            if verdict == 2:
                break
        _with_identity(c, verdict)
        if best is None or _pick_key(c) > _pick_key(best):
            best = c
    return best
