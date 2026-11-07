"""Hot cue postawione w selekcie — w trakcie odsłuchu, w miejscu odtwarzania.

Trzymane osobno od pamięci analiz (jak ręczne siatki w ``waveform``): to
praca człowieka i ma przetrwać przetagowanie pliku oraz nową analizę.
Czasy w osi selekty (ffmpeg); eksport do rekordboxa przelicza je na oś
rekordboxa (``rbczas``) tak samo jak resztę znaczników.

Sloty jak w rekordboxie i na CDJ: 0–7 = hot cue A–H. Hot cue z selekty
w danym slocie zastępuje ten z rekordboxa (to nowsza decyzja); pozostałe
sloty z rekordboxa zostają nietknięte.
"""
from __future__ import annotations

import json
import os
import unicodedata

from . import config

PLIK = os.path.join(config.STATE_DIR, "hotcue.json")
LITERY = "ABCDEFGH"
# kolory hot cue jak domyślnie w rekordboxie (A zielony, B…)
KOLORY = ("#28E214", "#FF127B", "#305AFF", "#FF8C00", "#E0D21E", "#A045FF",
          "#10B176", "#E62828")


def _klucz(path: str) -> str:
    return unicodedata.normalize("NFC", os.path.abspath(path))


def _wczytaj() -> dict:
    try:
        with open(PLIK, encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _zapisz(dane: dict) -> None:
    os.makedirs(os.path.dirname(PLIK), exist_ok=True)
    tmp = PLIK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dane, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, PLIK)


def dla_pliku(path: str) -> list[dict]:
    """Hot cue utworu, posortowane po slocie: [{num, start_s, nazwa, kolor}]."""
    return sorted(_wczytaj().get(_klucz(path), []), key=lambda z: z["num"])


def ustaw(path: str, num: int, start_s: float, nazwa: str = "") -> list[dict]:
    if not 0 <= int(num) <= 7:
        raise ValueError("hot cue to sloty A–H (0–7)")
    if not 0 <= float(start_s) < 6 * 3600:
        raise ValueError("czas cue poza utworem")
    num = int(num)
    dane = _wczytaj()
    lista = [z for z in dane.get(_klucz(path), []) if z["num"] != num]
    lista.append({"num": num, "start_s": round(float(start_s), 3),
                  "nazwa": str(nazwa or "")[:40], "kolor": KOLORY[num], "typ": "0"})
    dane[_klucz(path)] = sorted(lista, key=lambda z: z["num"])
    _zapisz(dane)
    return dane[_klucz(path)]


def usun(path: str, num: int) -> list[dict]:
    dane = _wczytaj()
    lista = [z for z in dane.get(_klucz(path), []) if z["num"] != int(num)]
    if lista:
        dane[_klucz(path)] = lista
    else:
        dane.pop(_klucz(path), None)
    _zapisz(dane)
    return lista


def scal(z_rekordboxa: list[dict], moje: list[dict]) -> list[dict]:
    """Znaczniki do eksportu: moje hot cue + z rekordboxa w wolnych slotach.

    Memory cue z rekordboxa (num −1) zostają zawsze.
    """
    zajete = {z["num"] for z in moje}
    return [z for z in z_rekordboxa
            if int(z.get("num", -1)) < 0 or int(z.get("num")) not in zajete] + list(moje)
