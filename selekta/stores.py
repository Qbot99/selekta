"""Legalne miejsca zakupu — głębokie linki do wyszukiwarek sklepów.

Świadomie tylko linki wyszukiwania: zero scrapowania, zero ryzyka z
regulaminami. Dobór sklepów nie jest przypadkowy — każdy pokrywa inny
kawałek repertuaru DJ-skiego:

* Beatport — bieżące wydawnictwa taneczne, standard DJ-ski (WAV/AIFF/FLAC)
* Qobuz — starsze single komercyjne i pop w FLAC, także hi-res
* Junodownload — głęboki katalog starszego dance'u i hard dance'u
* Bandcamp — undergroundowe i niezależne wydawnictwa, FLAC prosto od twórcy

Bootlegów i nieoficjalnych remiksów NIE MA w żadnym z nich — te wychodzą
wyłącznie jako MP3 na SoundCloudzie czy Hypeddit, więc dla nich pokazujemy
osobny trop zamiast udawać, że da się je kupić.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

from .spotify import Track

# słowa, po których poznajemy wydawnictwo nieoficjalne
_NIEOFICJALNE = ("bootleg", "mashup", "mash-up", "edit", "flip", "rework")


def beatport_search(track: Track) -> str:
    return f"https://www.beatport.com/search?q={quote_plus(track.query)}"


def bandcamp_search(track: Track) -> str:
    return f"https://bandcamp.com/search?q={quote_plus(track.query)}&item_type=t"


def qobuz_search(track: Track) -> str:
    return f"https://www.qobuz.com/us-en/search?q={quote_plus(track.query)}"


def juno_search(track: Track) -> str:
    return ("https://www.junodownload.com/search/?q%5Ball%5D%5B%5D="
            f"{quote_plus(track.query)}")


def soundcloud_search(track: Track) -> str:
    return f"https://soundcloud.com/search?q={quote_plus(track.query)}"


def is_unofficial(track: Track) -> bool:
    """Czy to bootleg/mashup — czyli coś, czego nie kupisz w sklepie."""
    tekst = f"{track.artist} {track.title}".lower()
    return any(re.search(rf"\b{w}\b", tekst) for w in _NIEOFICJALNE)


def buy_links(track: Track) -> dict[str, str]:
    """Sklepy dla tego utworu, od najbardziej prawdopodobnego."""
    links = {
        "beatport": beatport_search(track),
        "qobuz": qobuz_search(track),
        "juno": juno_search(track),
        "bandcamp": bandcamp_search(track),
    }
    if is_unofficial(track):
        # tu zakup odpada — jedyny trop to profil producenta
        links["soundcloud"] = soundcloud_search(track)
    return links


def gdzie_szukac(track: Track) -> str:
    """Krótka podpowiedź dla użytkownika, od czego zacząć."""
    if is_unofficial(track):
        return ("bootleg — nie ma go w sklepach; szukaj darmowego pliku "
                "u producenta (SoundCloud/Hypeddit), zwykle 320 kbps")
    return "sklepy: Beatport (dance), Qobuz (starszy pop), Juno (stary dance)"
