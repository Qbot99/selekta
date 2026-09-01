"""Kolejka propozycji zmian w bibliotece — nic bez zgody użytkownika.

Apka potrafi sama wykryć, że ten sam utwór leży w dwóch kopiach albo że
świeżo pobrany FLAC jest lepszy od posiadanego MP3 128 kbps. NIE wolno jej
jednak nic z tym zrobić samodzielnie: dopasowanie bywa mylne (ten sam tytuł
u innego wykonawcy, bootleg zamiast oryginału), a skasowany utwór, którego
brakuje na parkiecie, jest gorszy niż zmarnowane miejsce na dysku.

Dlatego każda wykryta zmiana ląduje tutaj jako PROPOZYCJA. Użytkownik ją
zatwierdza albo odrzuca. Zatwierdzenie nie kasuje pliku — przenosi go do
kosza, więc każdą decyzję da się cofnąć.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field

from . import config, matcher, quality
from .cache import get as cache_get, put as cache_put

PLIK = os.path.join(config.STATE_DIR, "decyzje.json")
KOSZ = "_selekta_kosz"


@dataclass
class Decyzja:
    id: str
    rodzaj: str                  # "duplikat" | "podmiana"
    zostaw: str                  # ścieżka, która ma zostać
    usun: list[str]              # ścieżki do przeniesienia do kosza
    powod: str
    dowody: dict = field(default_factory=dict)
    stan: str = "czeka"          # "czeka" | "zatwierdzona" | "odrzucona"
    w_koszu: list[str] = field(default_factory=list)
    kiedy: float = 0.0


def _wczytaj() -> list[dict]:
    try:
        with open(PLIK, encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _zapisz(dane: list[dict]) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = PLIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK)


def wszystkie() -> list[dict]:
    return _wczytaj()


def czekajace() -> list[dict]:
    return [d for d in _wczytaj() if d.get("stan") == "czeka"]


def _klucz(path: str) -> str:
    """Identyfikator decyzji stabilny między skanami."""
    import hashlib
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def _opis_pliku(path: str) -> dict:
    """Dane, na podstawie których użytkownik ma zdecydować."""
    try:
        rozmiar = os.path.getsize(path)
    except OSError:
        rozmiar = 0
    _tok, czas = matcher._file_tokens(path)
    q = cache_get(path, "quality")
    if q is None or "cutoff_hz" not in q:
        try:
            rep = quality.analyze(path)
            q = {"grade": rep.grade, "verdict": rep.verdict,
                 "cutoff_hz": rep.cutoff_hz, "sample_rate": rep.sample_rate,
                 "effective_bits": rep.effective_bits}
            cache_put(path, "quality", q)
        except Exception:                     # noqa: BLE001
            q = {}
    # bezstratność bierzemy z rozszerzenia — QualityReport jej nie podaje,
    # a to ono decyduje, czy plik w ogóle może być bezstratny
    lossless = path.lower().endswith((".flac", ".wav", ".aiff", ".aif", ".alac", ".ape"))
    return {
        "path": path,
        "nazwa": os.path.basename(path),
        "folder": os.path.dirname(path),
        "mb": round(rozmiar / 1_000_000, 1),
        "format": os.path.splitext(path)[1].lstrip(".").upper(),
        "jakosc": q.get("grade"),
        "opis_jakosci": q.get("verdict"),
        "pasmo_khz": (round(q["cutoff_hz"] / 1000, 1) if q.get("cutoff_hz") else None),
        "bitrate": (round(rozmiar * 8 / 1000 / czas) if czas else None),
        "lossless": lossless,
    }


def _lepszy(a: dict, b: dict) -> bool:
    """Czy `a` jest lepszą kopią niż `b`."""
    if bool(a.get("lossless")) != bool(b.get("lossless")):
        return bool(a.get("lossless"))
    porzadek = {"ok": 0, "warn": 1, "bad": 2, None: 3}
    ga, gb = porzadek.get(a.get("jakosc"), 3), porzadek.get(b.get("jakosc"), 3)
    if ga != gb:
        return ga < gb
    if (a.get("bitrate") or 0) != (b.get("bitrate") or 0):
        return (a.get("bitrate") or 0) > (b.get("bitrate") or 0)
    return a.get("mb", 0) > b.get("mb", 0)


def _tagi(path: str) -> tuple[str, str]:
    """Artysta i tytuł z metadanych pliku (puste, gdy ich nie ma)."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path, easy=True)
        if not audio:
            return "", ""
        artysta = (audio.get("artist") or [""])[0]
        tytul = (audio.get("title") or [""])[0]
        return str(artysta or ""), str(tytul or "")
    except Exception:                          # noqa: BLE001
        return "", ""


def _grupuj(folder: str) -> dict[tuple, list[str]]:
    """Pogrupuj bibliotekę po utworze: artysta + tytuł + wersja miksu.

    Klucz budujemy z TAGÓW, nie z nazwy pliku. Ten sam utwór bywa zapisany
    jako „01 - Tytul.flac" i „Artysta - Tytul [www.dj-promo.org].mp3" —
    gdyby liczyła się nazwa, żaden z tych duplikatów by się nie połączył,
    a to właśnie one są sensem tej funkcji. Nazwy używamy tylko wtedy,
    gdy tagów brak.
    """
    grupy: dict[tuple, list[str]] = {}
    for path in matcher.audio_files(folder):
        if os.sep + KOSZ + os.sep in path or os.path.basename(
                os.path.dirname(path)) == KOSZ:
            continue                          # kosza nie skanujemy
        artysta, tytul = _tagi(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        if artysta and tytul:
            tokeny = matcher.normalize(artysta) + matcher.normalize(tytul)
        else:
            tokeny = matcher.normalize(stem)
        rdzen = frozenset(t for t in tokeny if t not in matcher.MIX_WORDS)
        if not rdzen:
            continue
        # WERSJĘ czytamy z tagów I z nazwy pliku naraz. Dopisek „(Club Mix)"
        # albo „(Oski & Citos Bootleg)" bywa wyłącznie w nazwie, a tag
        # zawiera goły tytuł — samo poleganie na tagach kazałoby uznać
        # bootleg za kopię oryginału i zaproponować skasowanie jednego z nich.
        wersja = (matcher.mix_signature(tokeny)
                  | matcher.mix_signature(matcher.normalize(stem)))
        grupy.setdefault((rdzen, frozenset(wersja)), []).append(path)
    return _rozdziel_po_czasie(grupy)


def _rozdziel_po_czasie(grupy: dict[tuple, list[str]]) -> dict[tuple, list[str]]:
    """Rozbij grupę, jeśli pliki mają wyraźnie różny czas trwania.

    Ten sam tytuł u tego samego wykonawcy potrafi oznaczać dwie rzeczy:
    wersję radiową i klubową. Kopia to kopia dopiero wtedy, gdy trwa tyle
    samo — inaczej zaproponowalibyśmy skasowanie innego miksu.
    """
    wynik: dict[tuple, list[str]] = {}
    for klucz, pliki in grupy.items():
        if len(pliki) < 2:
            wynik[klucz] = pliki
            continue
        czasy = {}
        for p in pliki:
            _tok, czas = matcher._file_tokens(p)
            czasy[p] = czas
        kubelki: list[list[str]] = []
        for p in sorted(pliki, key=lambda x: czasy[x] or 0):
            for kubelek in kubelki:
                wzorzec = czasy[kubelek[0]]
                if (czasy[p] is None or wzorzec is None
                        or abs((czasy[p] or 0) - (wzorzec or 0)) <= 15):
                    kubelek.append(p)
                    break
            else:
                kubelki.append([p])
        for i, kubelek in enumerate(kubelki):
            wynik[klucz + (i,)] = kubelek
    return wynik


def skanuj(folder: str) -> list[dict]:
    """Znajdź kopie tego samego utworu i zaproponuj, którą zostawić.

    Nic nie zmienia na dysku — tylko dopisuje propozycje do kolejki.
    Utwory już rozpatrzone (zatwierdzone albo odrzucone) pomijamy, żeby
    odrzucona propozycja nie wracała przy każdym skanie.
    """
    dane = _wczytaj()
    znane = {d["id"] for d in dane}
    nowe = []
    for pliki in _grupuj(folder).values():
        if len(pliki) < 2:
            continue
        opisy = [_opis_pliku(p) for p in pliki]
        opisy.sort(key=lambda o: (not o.get("lossless"),
                                  {"ok": 0, "warn": 1, "bad": 2}.get(o.get("jakosc"), 3),
                                  -(o.get("bitrate") or 0), -o.get("mb", 0)))
        najlepszy, reszta = opisy[0], opisy[1:]
        ident = _klucz(najlepszy["path"])
        if ident in znane:
            continue
        rodzaj = ("podmiana" if any(bool(najlepszy.get("lossless")) !=
                                    bool(o.get("lossless")) for o in reszta)
                  else "duplikat")
        if rodzaj == "podmiana":
            powod = (f"{najlepszy['format']} jest lepszy niż "
                     f"{', '.join(sorted({o['format'] for o in reszta}))}")
        else:
            powod = f"{len(reszta)+1} kopie tego samego utworu"
        nowe.append(asdict(Decyzja(
            id=ident, rodzaj=rodzaj, zostaw=najlepszy["path"],
            usun=[o["path"] for o in reszta], powod=powod,
            dowody={"zostaw": najlepszy, "usun": reszta},
            kiedy=time.time())))
    if nowe:
        _zapisz(dane + nowe)
    return nowe


def _kosz_dla(path: str) -> str:
    return os.path.join(os.path.dirname(path), KOSZ)


def _wolna_nazwa(katalog: str, nazwa: str) -> str:
    cel = os.path.join(katalog, nazwa)
    stem, ext = os.path.splitext(cel)
    n = 2
    while os.path.exists(cel):
        cel = f"{stem} ({n}){ext}"
        n += 1
    return cel


def zatwierdz(ident: str) -> dict:
    """Wykonaj decyzję: przenieś odrzucone kopie do kosza (odwracalne)."""
    dane = _wczytaj()
    for d in dane:
        if d["id"] != ident:
            continue
        if d["stan"] != "czeka":
            raise ValueError(f"ta decyzja jest już {d['stan']}")
        przeniesione = []
        for src in d["usun"]:
            if not os.path.isfile(src):
                continue
            katalog = _kosz_dla(src)
            os.makedirs(katalog, exist_ok=True)
            cel = _wolna_nazwa(katalog, os.path.basename(src))
            shutil.move(src, cel)
            przeniesione.append(cel)
        d["stan"] = "zatwierdzona"
        d["w_koszu"] = przeniesione
        _zapisz(dane)
        return d
    raise KeyError("nie ma takiej decyzji")


def odrzuc(ident: str) -> dict:
    """Zostaw wszystko tak, jak jest — i nie pytaj o to ponownie."""
    dane = _wczytaj()
    for d in dane:
        if d["id"] == ident:
            d["stan"] = "odrzucona"
            _zapisz(dane)
            return d
    raise KeyError("nie ma takiej decyzji")


def cofnij(ident: str) -> dict:
    """Przywróć pliki z kosza tam, skąd zostały wzięte."""
    dane = _wczytaj()
    for d in dane:
        if d["id"] != ident:
            continue
        if d["stan"] != "zatwierdzona":
            raise ValueError("cofnąć można tylko zatwierdzoną decyzję")
        for src, cel in zip(d.get("w_koszu", []), d["usun"]):
            if os.path.isfile(src) and not os.path.exists(cel):
                os.makedirs(os.path.dirname(cel), exist_ok=True)
                shutil.move(src, cel)
        d["stan"] = "czeka"
        d["w_koszu"] = []
        _zapisz(dane)
        return d
    raise KeyError("nie ma takiej decyzji")


def _powody_niezgodnosci(sciezka: str, artysta: str, tytul: str,
                         czas_oczekiwany: float | None) -> list[str]:
    """Dlaczego pobrany plik NIE wygląda na zamówiony utwór.

    Nazwa na Soulseeku bywa myląca, a metadane w pliku mówią prawdę —
    dlatego sprawdzamy plik po pobraniu, a nie tylko wynik wyszukiwania.
    """
    powody = []
    tokeny, czas = matcher._file_tokens(sciezka)
    if not tokeny:
        tokeny = matcher.normalize(os.path.splitext(os.path.basename(sciezka))[0])
    rdzen_pliku = {t for t in tokeny if t not in matcher.MIX_WORDS}

    chciane = matcher.normalize(tytul)
    rdzen_chciany = {t for t in chciane if t not in matcher.MIX_WORDS}
    if rdzen_chciany:
        pokrycie = len(rdzen_chciany & rdzen_pliku) / len(rdzen_chciany)
        if pokrycie < 0.75:
            brak = sorted(rdzen_chciany - rdzen_pliku)[:4]
            powody.append(f"w pliku brakuje słów z tytułu: {', '.join(brak)}")

    a_tok = set(matcher.normalize(artysta))
    if a_tok and not (a_tok & rdzen_pliku):
        powody.append(f"nigdzie nie ma artysty „{artysta}”")

    if czas_oczekiwany and czas:
        roznica = abs(czas - czas_oczekiwany)
        if roznica > 15:
            powody.append(f"czas {int(czas)}s zamiast {int(czas_oczekiwany)}s "
                          f"(różnica {int(roznica)}s)")

    chciana_wersja = matcher.mix_signature(chciane)
    wersja_pliku = matcher.mix_signature(tokeny)
    if chciana_wersja != wersja_pliku:
        opis_a = ", ".join(sorted(chciana_wersja)) or "bez dopisku"
        opis_b = ", ".join(sorted(wersja_pliku)) or "bez dopisku"
        powody.append(f"inna wersja: zamówiono „{opis_a}”, jest „{opis_b}”")
    return powody


def sprawdz_pobrane(folder: str, zadania: list[dict],
                    odcisk: bool = True) -> list[dict]:
    """Zweryfikuj świeżo pobrane pliki i zgłoś podejrzane do decyzji.

    Nie usuwa niczego — dopisuje propozycję, żeby użytkownik obejrzał
    dowody i sam zdecydował. Pomyłka w drugą stronę (skasowany dobry
    utwór) jest znacznie kosztowniejsza niż plik do przejrzenia.
    """
    dane = _wczytaj()
    znane = {d["id"] for d in dane}
    nowe = []
    for z in zadania:
        nazwa = (z.get("file") or "").strip()
        if not nazwa or z.get("status") not in ("done", "queued"):
            continue
        sciezka = matcher.resolve_in_library(folder, os.path.basename(nazwa))
        if not sciezka or not os.path.isfile(sciezka):
            continue
        ident = _klucz("pobrane:" + sciezka)
        if ident in znane:
            continue
        powody = _powody_niezgodnosci(sciezka, z.get("artist", ""),
                                      z.get("title", ""), z.get("duration"))

        # Odcisk akustyczny rozstrzyga to, czego nazwy i tagi nie potrafią:
        # porównuje SAM DŹWIĘK z 30-sekundową próbką z iTunes. Działa w obie
        # strony — potrafi zdemaskować podmieniony plik, ale też uniewinnić
        # dobrze pobrany utwór o bałaganiarskiej nazwie.
        dowod = None
        if odcisk:
            try:
                from . import verify_match
                wynik = verify_match.verify_by_name(
                    sciezka, z.get("artist", ""), z.get("title", ""))
            except Exception:                  # noqa: BLE001
                wynik = None
            if wynik:
                res, opis = wynik
                dowod = {"werdykt": res.verdict, "zgodnosc": round(res.score, 3),
                         "zrodlo": opis}
                if res.verdict == "match":
                    continue                   # dźwięk się zgadza — koniec sprawy
                if res.verdict == "mismatch":
                    powody = [f"odcisk akustyczny mówi, że to INNY utwór "
                              f"(zgodność {res.score:.0%}, porównano z „{opis}”)"] + powody

        if not powody:
            continue
        nowe.append(asdict(Decyzja(
            id=ident, rodzaj="podejrzany", zostaw="", usun=[sciezka],
            powod=f"pobrano jako „{z.get('artist','')} — {z.get('title','')}”, "
                  f"ale plik się nie zgadza",
            dowody={"zostaw": None, "usun": [_opis_pliku(sciezka)],
                    "zastrzezenia": powody, "odcisk": dowod,
                    "zamowiono": {"artysta": z.get("artist", ""),
                                  "tytul": z.get("title", ""),
                                  "czas": z.get("duration")}},
            kiedy=time.time())))
    if nowe:
        _zapisz(dane + nowe)
    return nowe
