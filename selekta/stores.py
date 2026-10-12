"""Legalne miejsca zakupu — głębokie linki do wyszukiwarek sklepów.

Świadomie tylko linki wyszukiwania: zero scrapowania, zero ryzyka z
regulaminami. Dobór sklepów nie jest przypadkowy — każdy pokrywa inny
kawałek repertuaru DJ-skiego:

* Beatport — bieżące wydawnictwa taneczne, standard DJ-ski (WAV/AIFF/FLAC)
* Bandcamp — undergroundowe i niezależne wydawnictwa, FLAC prosto od twórcy
* Qobuz — pop, rock i starsze single komercyjne w FLAC, także hi-res
* Apple Music / iTunes — najszerszy katalog popu (tam jest Madonna, której
  Beatport nie ma: wyszukiwanie „Madonna Hung Up" daje tam tylko
  „The Blessed Madonna")

Junodownload zniknął 1.06.2026 (domena nie ma już rekordu A) — usunięty.

Kolejność zależy od utworu: przy nazwach wersji klubowych (Extended Mix,
Remix, Dub…) najpierw sklepy taneczne, przy zwykłym tytule — popowe.

Bootlegów i nieoficjalnych remiksów NIE MA w żadnym z nich — te wychodzą
wyłącznie jako MP3 na SoundCloudzie czy Hypeddit, więc dla nich pokazujemy
osobny trop zamiast udawać, że da się je kupić.
"""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

from .spotify import Track

# słowa, po których poznajemy wydawnictwo nieoficjalne
# „edit" bez „radio " przed sobą: Radio Edit to oficjalna wersja sklepowa,
# a trafiała na SoundCloud jako rzekomy bootleg. To samo z „Extended Edit"
# i „Club Edit" — Beatport tak nazywa oficjalne wersje (np. „Samba De
# Janeiro (Dimitri Vegas & Like Mike Extended Edit)")
_NIEOFICJALNE = ("bootleg", "mashup", "mash-up",
                 r"(?<!radio )(?<!extended )(?<!club )(?<!single )(?<!album )edit",
                 "flip", "rework")
# po tych słowach poznajemy wydanie klubowe — wtedy sklepy taneczne przodem
_TANECZNE = (r"\bextended\b", r"\boriginal mix\b", r"\bremix\b", r"\bclub mix\b",
             r"\bdub\b", r"\bvip\b", r"\brework\b", r"\btechno\b", r"\bhouse\b",
             r"\btrance\b", r"\bhardstyle\b", r"\bbootleg\b",
             r"(?<!radio )\bedit\b", r"\bmix\)")


def beatport_search(track: Track) -> str:
    return f"https://www.beatport.com/search?q={quote_plus(track.query)}"


def bandcamp_search(track: Track) -> str:
    return f"https://bandcamp.com/search?q={quote_plus(track.query)}&item_type=t"


def qobuz_search(track: Track) -> str:
    # Bezpośrednio wyniki utworów: „/search?q=" przekierowywał raz na albumy,
    # raz na „/search/?q=", który oddawał 502 (sprawdzone 11.10.2026)
    return f"https://www.qobuz.com/us-en/search/tracks/{quote(track.query.strip(), safe='')}"


def apple_search(track: Track) -> str:
    return f"https://music.apple.com/search?term={quote_plus(track.query)}"


def soundcloud_search(track: Track) -> str:
    return f"https://soundcloud.com/search?q={quote_plus(track.query)}"


def is_unofficial(track: Track) -> bool:
    """Czy to bootleg/mashup — czyli coś, czego nie kupisz w sklepie."""
    tekst = f"{track.artist} {track.title}".lower()
    return any(re.search(rf"\b{w}\b", tekst) for w in _NIEOFICJALNE)


def is_dance(track: Track) -> bool:
    """Czy tytuł wygląda na wydanie klubowe (Extended Mix, Remix, Dub…)."""
    tekst = f"{track.artist} {track.title}".lower()
    return any(re.search(w, tekst) for w in _TANECZNE)


_NAZWY = {"beatport": "Beatport", "bandcamp": "Bandcamp", "qobuz": "Qobuz",
          "apple": "Apple Music", "soundcloud": "SoundCloud"}


def buy_links(track: Track) -> dict[str, str]:
    """Sklepy dla tego utworu, od najbardziej prawdopodobnego."""
    if is_dance(track):
        kolejnosc = ("beatport", "bandcamp", "qobuz", "apple")
    else:
        kolejnosc = ("qobuz", "apple", "beatport", "bandcamp")
    linki = {"beatport": beatport_search(track), "bandcamp": bandcamp_search(track),
             "qobuz": qobuz_search(track), "apple": apple_search(track)}
    links = {k: linki[k] for k in kolejnosc}
    if is_unofficial(track):
        # tu zakup odpada — jedyny trop to profil producenta
        links = {"soundcloud": soundcloud_search(track), **links}
    return links


def sklepy(track: Track) -> list[dict[str, str]]:
    """Te same linki jako lista dla interfejsu: [{name, url}], od
    najbardziej prawdopodobnego sklepu."""
    return [{"id": k, "name": _NAZWY[k], "url": u}
            for k, u in buy_links(track).items()]


def gdzie_szukac(track: Track) -> str:
    """Krótka podpowiedź dla użytkownika, od czego zacząć."""
    if is_unofficial(track):
        return ("bootleg — nie ma go w sklepach; szukaj darmowego pliku "
                "u producenta (SoundCloud/Hypeddit), zwykle 320 kbps")
    if is_dance(track):
        return "sklepy: Beatport i Bandcamp (dance), Qobuz (FLAC)"
    return "sklepy: Qobuz (FLAC) i Apple Music (pop), Beatport (dance)"
