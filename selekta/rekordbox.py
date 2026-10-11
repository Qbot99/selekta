"""Wstawianie playlisty prosto do rekordboxa (macOS).

rekordbox potrafi trzymać w panelu bocznym „zaimportowaną bibliotekę" —
kolekcję z pliku XML wraz z playlistami. Ścieżka do tego pliku siedzi w
ustawieniach pod kluczem `bridgeImportedLibraryFile`. Ustawiając ją raz,
sprawiamy, że po każdym uruchomieniu rekordboxa nasz set po prostu tam
jest — bez ręcznego „File → Import Collection".

Ostrożność, bo dotykamy ustawień cudzej aplikacji:
- plik ustawień jest kopiowany do backupu przed pierwszą zmianą,
- podmieniamy WYŁĄCZNIE jeden klucz (chirurgiczne podstawienie, nie
  przepisywanie całego XML-a — rekordbox jest wrażliwy na format),
- gdy rekordbox działa, odmawiamy: zapisałby swoje ustawienia przy
  wyjściu i nadpisał naszą zmianę.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

# rekordbox 7 nadal używa katalogu "rekordbox6"
SETTINGS_DIRS = (
    "~/Library/Application Support/Pioneer/rekordbox6",
    "~/Library/Application Support/Pioneer/rekordbox7",
)
SETTINGS_NAME = "rekordbox3.settings"
KEY = "bridgeImportedLibraryFile"
BACKUP_SUFFIX = ".selekta-backup"


@dataclass
class InstallResult:
    ok: bool
    message: str            # komunikat po polsku dla użytkownika
    settings_path: str = ""
    previous: str = ""
    backup: str = ""


def settings_path() -> str | None:
    """Ścieżka do pliku ustawień rekordboxa albo None, gdy nie znaleziono."""
    for d in SETTINGS_DIRS:
        p = os.path.join(os.path.expanduser(d), SETTINGS_NAME)
        if os.path.isfile(p):
            return p
    return None


def is_running() -> bool:
    """Czy rekordbox jest uruchomiony (wtedy nadpisałby nasze zmiany)."""
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["pgrep", "-x", "rekordbox"],
                             capture_output=True, timeout=5)
        return out.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _read(path: str) -> str:
    # newline="" — bez tłumaczenia końców linii: plik rekordboxa ma CRLF
    # i ma go zachować co do bajtu (wcześniej każdy zapis robił z nich LF)
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _write_atomic(path: str, text: str) -> None:
    tmp = path + ".selekta-tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


_WZOR = re.compile(rf'(<VALUE name="{KEY}" val=")([^"]*)(")')


def imported_library() -> str | None:
    """Aktualnie podpięty plik XML (pusty string = żaden)."""
    p = settings_path()
    if not p:
        return None
    m = re.search(rf'<VALUE name="{KEY}" val="([^"]*)"', _read(p))
    if not m:
        return None
    return _xml_unescape(m.group(1))


def _xml_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _xml_unescape(value: str) -> str:
    return (value.replace("&quot;", '"').replace("&lt;", "<")
            .replace("&gt;", ">").replace("&amp;", "&"))


def install(xml_path: str) -> InstallResult:
    """Podepnij `xml_path` jako zaimportowaną bibliotekę rekordboxa."""
    if sys.platform != "darwin":
        return InstallResult(False, "automatyczne wstawianie działa na razie tylko na macOS")

    settings = settings_path()
    if not settings:
        return InstallResult(False, "nie znalazłem ustawień rekordboxa — czy jest zainstalowany?")

    if is_running():
        return InstallResult(
            False,
            "rekordbox jest uruchomiony — zamknij go i kliknij ponownie "
            "(przy wyjściu nadpisuje własne ustawienia)",
            settings_path=settings,
        )

    if not os.path.isfile(xml_path):
        return InstallResult(False, f"brak pliku playlisty: {xml_path}")

    text = _read(settings)
    pattern = re.compile(rf'(<VALUE name="{KEY}" val=")([^"]*)(")')
    m = pattern.search(text)
    if not m:
        return InstallResult(
            False, "ustawienia rekordboxa nie mają pola importowanej biblioteki "
                   "— wskaż plik ręcznie w Preferencjach",
            settings_path=settings)

    # porównujemy po odescapowaniu: wartość w pliku ma '&amp;', ścieżka '&'
    # — bez tego ponowny install ścieżki z '&' nie poznawał własnego wpisu
    previous = _xml_unescape(m.group(2))
    if previous == xml_path:
        return InstallResult(True, "playlista była już podpięta — odpal rekordbox",
                             settings_path=settings, previous=previous)

    backup = settings + BACKUP_SUFFIX
    if not os.path.exists(backup):          # backup tylko raz, oryginalny stan
        shutil.copy2(settings, backup)

    new_text = pattern.sub(
        lambda mm: mm.group(1) + _xml_escape(xml_path) + mm.group(3), text, count=1)
    _write_atomic(settings, new_text)

    return InstallResult(
        True,
        "playlista podpięta — odpal rekordbox, będzie w panelu bocznym "
        "pod „rekordbox xml”",
        settings_path=settings, previous=previous, backup=backup,
    )


def restore() -> InstallResult:
    """Odepnij playlistę selekty: przywróć TYLKO nasz klucz sprzed pierwszej zmiany.

    Wcześniej kopiowaliśmy cały plik z chwili pierwszej instalacji, co
    cofało też późniejsze zmiany użytkownika w rekordboksie (np. język
    przełączony po instalacji wracał na stary). Teraz reszta pliku zostaje
    taka, jaka jest dziś — zmieniamy wyłącznie bridgeImportedLibraryFile.
    """
    settings = settings_path()
    if not settings:
        return InstallResult(False, "nie znalazłem ustawień rekordboxa")
    backup = settings + BACKUP_SUFFIX
    if not os.path.isfile(backup):
        return InstallResult(False, "brak kopii zapasowej — nic do przywrócenia")
    if is_running():
        return InstallResult(False, "zamknij rekordbox przed przywracaniem ustawień")
    m_stary = _WZOR.search(_read(backup))
    if not m_stary:
        return InstallResult(False, "kopia zapasowa nie ma pola importowanej "
                                    "biblioteki — nic do przywrócenia")
    text = _read(settings)
    m = _WZOR.search(text)
    if not m:
        return InstallResult(False, "ustawienia rekordboxa nie mają już pola "
                                    "importowanej biblioteki — nic do przywrócenia",
                             settings_path=settings)
    if m.group(2) != m_stary.group(2):
        _write_atomic(settings, text[:m.start(2)] + m_stary.group(2) + text[m.end(2):])
    return InstallResult(True, "odpięto playlistę selekty — rekordbox wraca do "
                               "poprzedniego ustawienia (reszta ustawień bez zmian)",
                         settings_path=settings, backup=backup,
                         previous=_xml_unescape(m.group(2)))


# --------------------------------------------------------------------------
# wszystkie sety naraz
# --------------------------------------------------------------------------

def _rejestr_path() -> str:
    from . import config
    return os.path.join(config.STATE_DIR, "rekordbox-sety.json")


def polaczony_path() -> str:
    """Wspólny XML ze wszystkimi wysłanymi setami — to on jest podpinany."""
    from . import config
    return os.path.join(config.STATE_DIR, "rekordbox-sety.xml")


def _rejestr() -> dict[str, str]:
    import json
    try:
        with open(_rejestr_path(), encoding="utf-8") as fh:
            dane = json.load(fh)
        return dane if isinstance(dane, dict) else {}
    except (OSError, ValueError):
        return {}


def zbuduj_polaczony(rejestr: dict[str, str], out_path: str) -> list[str]:
    """Połącz XML-e setów w jeden: wspólna kolekcja + playlista na każdy set.

    Klucz rekordboxa wskazuje JEDEN plik, więc dotąd w panelu „rekordbox
    xml" widać było tylko ostatnio wysłany set. Utwór obecny w kilku
    setach trafia do kolekcji raz (po Location); dane z najnowszego
    eksportu wygrywają. Zwraca nazwy setów, które się znalazły.
    """
    import copy
    import xml.etree.ElementTree as ET

    from . import __version__

    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="selekta", Version=__version__, Company="selekta")
    kolekcja = ET.SubElement(root, "COLLECTION")
    po_lokacji: dict[str, ET.Element] = {}
    sety: list[tuple[str, list[str]]] = []
    for nazwa, xml_path in rejestr.items():
        try:
            src = ET.parse(xml_path).getroot()
        except (OSError, ET.ParseError):
            continue                         # set skasowany z dysku — pomijamy
        id_na_lok = {}
        for t in src.iterfind("COLLECTION/TRACK"):
            loc = t.get("Location")
            if not loc:
                continue
            id_na_lok[t.get("TrackID")] = loc
            nowy = copy.deepcopy(t)
            if loc in po_lokacji:            # nowszy eksport wygrywa
                kolekcja.remove(po_lokacji[loc])
            po_lokacji[loc] = nowy
            kolekcja.append(nowy)
        wezel = next((n for n in src.iter("NODE") if n.get("Type") == "1"), None)
        klucze = [t.get("Key") for t in wezel.findall("TRACK")] if wezel is not None else []
        sety.append((nazwa, [id_na_lok[k] for k in klucze if k in id_na_lok]))
    for i, t in enumerate(kolekcja.findall("TRACK"), start=1):
        t.set("TrackID", str(i))
    kolekcja.set("Entries", str(len(kolekcja.findall("TRACK"))))
    id_po_lok = {t.get("Location"): t.get("TrackID") for t in kolekcja.findall("TRACK")}
    pl = ET.SubElement(root, "PLAYLISTS")
    korzen = ET.SubElement(pl, "NODE", Type="0", Name="ROOT", Count=str(len(sety)))
    for nazwa, lokacje in sety:
        n = ET.SubElement(korzen, "NODE", Name=nazwa, Type="1", KeyType="0",
                          Entries=str(len(lokacje)))
        for loc in lokacje:
            ET.SubElement(n, "TRACK", Key=id_po_lok[loc])
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".tmp"
    tree.write(tmp, encoding="UTF-8", xml_declaration=True)
    os.replace(tmp, out_path)
    return [n for n, _ in sety]


def install_set(xml_path: str, nazwa: str) -> InstallResult:
    """Dopisz set do wspólnego XML-a wszystkich setów i podepnij go.

    Dzięki temu w rekordboksie widać naraz WSZYSTKIE wysłane sety, a nie
    tylko ostatni. Plik pojedynczego setu zostaje obok (File → Import).
    """
    import json

    rejestr = {k: v for k, v in _rejestr().items() if os.path.isfile(v) and k != nazwa}
    rejestr[nazwa] = os.path.abspath(xml_path)
    polaczony = polaczony_path()
    sety = zbuduj_polaczony(rejestr, polaczony)
    os.makedirs(os.path.dirname(_rejestr_path()), exist_ok=True)
    with open(_rejestr_path(), "w", encoding="utf-8") as fh:
        json.dump(rejestr, fh, ensure_ascii=False, indent=1)
    ile = f"{len(sety)} {_odmiana(len(sety), 'set', 'sety', 'setów')} selekty"
    if imported_library() == polaczony:
        # plik jest już podpięty — zmieniła się tylko jego treść, ustawień
        # rekordboxa nie ruszamy (więc nie trzeba go nawet zamykać)
        return InstallResult(True, f"wysłano „{nazwa}” — w rekordboksie odśwież panel "
                                   f"„rekordbox xml” (jest tam {ile})",
                             settings_path=settings_path() or "", previous=polaczony)
    res = install(polaczony)
    if res.ok:
        res.message = (f"wysłano „{nazwa}” — odpal rekordbox: w panelu bocznym "
                       f"„rekordbox xml” jest {ile}")
    return res


def _odmiana(n: int, jeden: str, kilka: str, wiele: str) -> str:
    if n == 1:
        return jeden
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return kilka
    return wiele
