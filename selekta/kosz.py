"""Kosz selekty: przenoszenie plików do ``_selekta_kosz`` i z powrotem.

Jedno miejsce dla wszystkich ekranów, które „usuwają” (Biblioteka → Usuń,
Zdrowie → Usuń duplikaty, Porządki → Zatwierdź). Wcześniej każdy robił to
po swojemu: duplikaty z podfolderów lądowały w jednym koszu w katalogu
głównym i traciły informację, skąd przyszły (przywrócenie kończyło się
409 albo plikiem w złym miejscu), a plik z dopiskiem „ (2)” wracał pod
tą zmienioną nazwą.

Zasady:

* kosz leży OBOK pliku: ``<folder pliku>/_selekta_kosz/`` — przywrócenie
  zawsze trafia tam, skąd plik wziął;
* w koszu zapisujemy notkę ``.selekta_kosz.json`` (nazwa w koszu →
  oryginalna ścieżka), więc plik wraca pod SWOJĄ nazwą, nawet gdy w koszu
  musiał dostać dopisek „ (2)”;
* przywracać można wyłącznie pliki leżące w katalogu ``_selekta_kosz`` —
  zwykły plik biblioteki nie zostanie „przywrócony” poza bibliotekę.
"""
from __future__ import annotations

import json
import os
import shutil
import threading

KOSZ = "_selekta_kosz"
NOTKA = ".selekta_kosz.json"

_lock = threading.Lock()


def katalog_kosza(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(path)), KOSZ)


def w_koszu(path: str) -> bool:
    return os.path.basename(os.path.dirname(os.path.abspath(path))) == KOSZ


def _wolna_nazwa(katalog: str, nazwa: str) -> str:
    cel = os.path.join(katalog, nazwa)
    stem, ext = os.path.splitext(cel)
    n = 2
    while os.path.exists(cel):
        cel = f"{stem} ({n}){ext}"
        n += 1
    return cel


def _czytaj_notke(katalog: str) -> dict:
    try:
        with open(os.path.join(katalog, NOTKA), encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _zapisz_notke(katalog: str, dane: dict) -> None:
    sciezka = os.path.join(katalog, NOTKA)
    if not dane:
        try:
            os.remove(sciezka)
        except OSError:
            pass
        return
    tmp = sciezka + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, sciezka)


def do_kosza(path: str, katalog: str | None = None) -> str:
    """Przenieś plik do kosza obok niego; zwróć ścieżkę w koszu."""
    src = os.path.abspath(path)
    katalog = os.path.abspath(katalog) if katalog else katalog_kosza(src)
    with _lock:
        os.makedirs(katalog, exist_ok=True)
        cel = _wolna_nazwa(katalog, os.path.basename(src))
        shutil.move(src, cel)
        notka = _czytaj_notke(katalog)
        notka[os.path.basename(cel)] = src
        _zapisz_notke(katalog, notka)
    return cel


def skad(sciezka_w_koszu: str) -> str:
    """Oryginalna ścieżka pliku z kosza (z notki; bez notki — folder nad koszem)."""
    p = os.path.abspath(sciezka_w_koszu)
    katalog = os.path.dirname(p)
    zapisana = _czytaj_notke(katalog).get(os.path.basename(p))
    if zapisana:
        return zapisana
    return os.path.join(os.path.dirname(katalog), os.path.basename(p))


def przywroc(sciezka_w_koszu: str, korzen: str | None = None) -> str:
    """Przywróć plik z kosza na jego miejsce; zwróć ścieżkę docelową.

    Rzuca ValueError (plik nie leży w koszu / cel poza ``korzen``),
    FileNotFoundError (nie ma go w koszu) i FileExistsError (na miejscu
    leży już plik o tej nazwie — nic nie nadpisujemy).
    """
    src = os.path.abspath(sciezka_w_koszu)
    if not w_koszu(src):
        raise ValueError("to nie jest plik z kosza selekty")
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    cel = os.path.abspath(skad(src))
    if korzen:
        k = os.path.abspath(korzen)
        if os.path.commonpath([cel, k]) != k or os.path.commonpath([src, k]) != k:
            raise ValueError("ścieżka poza biblioteką")
    if os.path.exists(cel):
        raise FileExistsError(cel)
    with _lock:
        os.makedirs(os.path.dirname(cel), exist_ok=True)
        shutil.move(src, cel)
        katalog = os.path.dirname(src)
        notka = _czytaj_notke(katalog)
        notka.pop(os.path.basename(src), None)
        _zapisz_notke(katalog, notka)
        try:
            if not [n for n in os.listdir(katalog) if not n.startswith(".")]:
                os.rmdir(katalog)              # pusty kosz nie zostaje w bibliotece
        except OSError:
            pass
    return cel


def zawartosc(korzen: str) -> list[dict]:
    """Wszystkie pliki w koszach selekty pod ``korzen`` (do przywrócenia)."""
    out = []
    for katalog, dirs, names in os.walk(korzen):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if os.path.basename(katalog) != KOSZ:
            continue
        dirs[:] = []
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = os.path.join(katalog, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"w_koszu": p, "skad": skad(p), "mb": round(st.st_size / 1e6, 1),
                        "kiedy": st.st_ctime})
    return sorted(out, key=lambda x: -x["kiedy"])
