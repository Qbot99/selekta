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
    # integralność: ucięty FLAC ma „prawdziwe” pasmo i jakość „ok”, ale gra
    # pół utworu — bez tej kontroli Porządki proponowały zamianę zdrowego MP3
    # na uszkodzony FLAC (ta sama kontrola co na ekranie Zdrowie)
    try:
        from . import health
        integ = health.integralnosc(path)
    except Exception:                         # noqa: BLE001
        integ = {"ok": True, "opis": ""}
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
        "uszkodzony": not integ.get("ok", True),
        "integralnosc": integ.get("opis", ""),
    }


def _ranga(o: dict) -> tuple:
    """Klucz sortowania kopii (mniejszy = lepsza). Uszkodzona zawsze na końcu."""
    return (bool(o.get("uszkodzony")),
            not o.get("lossless"),
            {"ok": 0, "warn": 1, "bad": 2}.get(o.get("jakosc"), 3),
            -(o.get("bitrate") or 0), -o.get("mb", 0),
            _nazwa_kopii(o.get("path", "")), o.get("path", ""))


def _nazwa_kopii(path: str) -> bool:
    from .health import nazwa_kopii
    return nazwa_kopii(path)


def _lepszy(a: dict, b: dict) -> bool:
    """Czy `a` jest lepszą kopią niż `b`."""
    return _ranga(a) < _ranga(b)


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
    gdy tagów brak. Reguła jest wspólna ze Zdrowiem (``health.klucz_utworu``):
    wersję czytamy z tagów I z nazwy pliku, a dwie wersje są tą samą tylko
    wtedy, gdy są równe — „Original Mix” nie jest kopią „Extended Mix”.

    Pliki w folderach setów nie biorą udziału — to zawartość setów, nie
    zbędne kopie; zatwierdzenie propozycji rozbiłoby set.
    """
    from .health import klucz_utworu
    from .uklad import wczytaj
    uklad = wczytaj(folder)
    grupy: dict[tuple, list[str]] = {}
    for path in matcher.audio_files(folder):
        if os.sep + KOSZ + os.sep in path or os.path.basename(
                os.path.dirname(path)) == KOSZ:
            continue                          # kosza nie skanujemy
        if uklad.w_secie(path):
            continue                          # kopie w setach są nietykalne
        artysta, tytul = _tagi(path)
        klucz = klucz_utworu(path, artysta, tytul)
        if klucz is None:
            continue
        grupy.setdefault(klucz, []).append(path)
    return _rozdziel_po_czasie(grupy)


#: ta sama tolerancja co na ekranie Zdrowie (health.DUP_MAX_DELTA_S)
TOLERANCJA_CZASU_S = 2.0


def _rozdziel_po_czasie(grupy: dict[tuple, list[str]]) -> dict[tuple, list[str]]:
    """Rozbij grupę, jeśli pliki mają wyraźnie różny czas trwania.

    Ten sam tytuł u tego samego wykonawcy potrafi oznaczać dwie rzeczy:
    wersję radiową i klubową. Kopia to kopia dopiero wtedy, gdy trwa tyle
    samo (do 2 s, jak w Zdrowiu — wcześniej 15 s łączyło różne edycje
    i ucięte kopie). Plik bez znanego czasu nie jest z niczym łączony.
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
        for p in sorted(pliki, key=lambda x: (czasy[x] is None, czasy[x] or 0, x)):
            for kubelek in kubelki:
                wzorzec = czasy[kubelek[0]]
                if (czasy[p] is not None and wzorzec is not None
                        and abs(czasy[p] - wzorzec) <= TOLERANCJA_CZASU_S):
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
        opisy.sort(key=_ranga)
        najlepszy, reszta = opisy[0], opisy[1:]
        if najlepszy.get("uszkodzony"):
            continue                          # wszystkie kopie uszkodzone — nie ma czego zostawić
        ident = _klucz(najlepszy["path"])
        if ident in znane:
            continue
        rodzaj = ("podmiana" if any(bool(najlepszy.get("lossless")) !=
                                    bool(o.get("lossless")) for o in reszta
                                    if not o.get("uszkodzony"))
                  else "duplikat")
        if rodzaj == "podmiana":
            powod = (f"{najlepszy['format']} jest lepszy niż "
                     f"{', '.join(sorted({o['format'] for o in reszta}))}")
        else:
            powod = f"{len(reszta)+1} kopie tego samego utworu"
        uszkodzone = [o for o in reszta if o.get("uszkodzony")]
        if uszkodzone:
            powod += (f" — {len(uszkodzone)} z nich "
                      f"{'jest uszkodzona' if len(uszkodzone) == 1 else 'są uszkodzone'}"
                      f" ({uszkodzone[0].get('integralnosc', '')})")
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
    """Wykonaj decyzję: przenieś odrzucone kopie do kosza (odwracalne).

    Zapamiętujemy PARY (skąd → dokąd). Dawniej cofnięcie parowało listę
    plików w koszu z listą „do usunięcia” po pozycji — gdy jeden plik zniknął
    przed zatwierdzeniem, pozostałe wracały pod cudze nazwy.
    """
    from . import kosz
    dane = _wczytaj()
    for d in dane:
        if d["id"] != ident:
            continue
        if d["stan"] != "czeka":
            raise ValueError(f"ta decyzja jest już {d['stan']}")
        zostaw = d.get("zostaw")
        if zostaw and not os.path.isfile(zostaw):
            raise ValueError("kopia, która miała zostać, zniknęła — przeskanuj ponownie")
        przeniesione, pary = [], []
        for src in d["usun"]:
            if not os.path.isfile(src):
                continue
            cel = kosz.do_kosza(src)
            przeniesione.append(cel)
            pary.append({"z": src, "do": cel})
        d["stan"] = "zatwierdzona"
        d["w_koszu"] = przeniesione
        d["przeniesienia"] = pary
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
    """Przywróć pliki z kosza tam, skąd zostały wzięte — albo pominiętą
    decyzję z powrotem do kolejki."""
    from . import kosz
    dane = _wczytaj()
    for d in dane:
        if d["id"] != ident:
            continue
        if d["stan"] == "odrzucona":
            d["stan"] = "czeka"               # pominięta wraca do rozpatrzenia
            _zapisz(dane)
            return d
        if d["stan"] != "zatwierdzona":
            raise ValueError("cofnąć można tylko zatwierdzoną albo pominiętą decyzję")
        pary = d.get("przeniesienia")
        if pary is None:                      # decyzje zapisane przed poprawką
            pary = [{"z": kosz.skad(c), "do": c} for c in d.get("w_koszu", [])]
        nie_wrocily = []
        for para in pary:
            src, cel = para["do"], para["z"]
            if os.path.isfile(src) and not os.path.exists(cel):
                os.makedirs(os.path.dirname(cel), exist_ok=True)
                try:
                    if kosz.w_koszu(src) and os.path.abspath(kosz.skad(src)) == os.path.abspath(cel):
                        kosz.przywroc(src)
                    else:
                        shutil.move(src, cel)
                except (OSError, ValueError):
                    nie_wrocily.append(cel)
            elif not os.path.exists(cel):
                nie_wrocily.append(cel)
        d["stan"] = "czeka"
        d["w_koszu"] = []
        d["przeniesienia"] = []
        d["nie_wrocily"] = nie_wrocily
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
