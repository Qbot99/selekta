"""Sprawdź uchem — lista wyników, których aplikacja nie jest pewna.

Aplikacja liczy pewność tempa i tonacji, bada stabilność siatki i ocenia
jakość, ale do tej pory wynik pewny i niepewny wyglądały w tabeli tak samo.
Weryfikacja z 1.09.2026 pokazała, czym to grozi: metronom 87 BPM dostał
pewność 0,04 — decyzja o podwojeniu tempa na styku — i siedział w tabeli
obok pewnego 128 bez żadnego znaku. Dla DJ-a siatka to rzecz, na której
gra na żywo; ten moduł zbiera wszystko, co warto sprawdzić uchem, zanim
utwór trafi do setu.

Czyta WYŁĄCZNIE pamięć podręczną analiz — niczego nie liczy, więc jest
natychmiastowy i nie obciąża maszyny. Utwory bez analizy raportuje osobno.

Progi z pomiarów na prawdziwej bibliotece (wrzesień 2026):
* pewność tempa realnych utworów klubowych 0,32-0,62; syntetyczne pułapki
  podwojenia dają 0,04-0,16 — próg 0,25 leży w przerwie z zapasem;
* pewność tonacji 0,47-1,00; próg 0,4 jest spójny ze znakiem „(?)"
  w tabeli biblioteki.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import cache, matcher

PROG_TEMPA = 0.25
PROG_TONACJI = 0.4

# waga: 3 = nie graj bez sprawdzenia, 2 = sprawdź przy okazji, 1 = drobiazg
WAGI = {"tempo_niepewne": 3, "transkod": 3, "bpm_inne_niz_w_tagu": 3, "tempo_zmienne": 2,
        "bpm_nietrafione": 2, "siatka_niepewna": 2, "takt_niepewny": 1,
        "tonacja_niepewna": 1, "jakosc_do_oceny": 1}
PROG_SIATKI = 0.25       # spójność kicków z siatką (siatka.PROG_PEWNOSCI)
PROG_TAKTU = 0.3         # przewaga jedynki taktu nad drugą kandydatką


@dataclass
class Powod:
    kod: str
    opis: str
    waga: int


@dataclass
class DoSprawdzenia:
    file: str
    bpm: float | None = None
    camelot: str | None = None
    key: str | None = None
    powody: list[Powod] = field(default_factory=list)

    @property
    def waga(self) -> int:
        return max((p.waga for p in self.powody), default=0)


def bpm_z_tagu(path: str) -> float | None:
    """BPM zapisany w pliku przez sklep/rekordbox (TBPM, BPM, tmpo) — albo None."""
    try:
        from mutagen import File as MutagenFile
        a = MutagenFile(path)
        tags = getattr(a, "tags", None)
        if tags is None:
            return None
        for klucz in ("TBPM", "BPM", "bpm", "tmpo"):
            try:
                v = tags.get(klucz)
            except Exception:                  # noqa: BLE001
                v = None
            if not v:
                continue
            v = getattr(v, "text", v)
            v = v[0] if isinstance(v, (list, tuple)) else v
            liczba = float(str(v).replace(",", "."))
            if 40 <= liczba <= 250:
                return liczba
    except Exception:                          # noqa: BLE001
        return None
    return None


def _ta_sama_oktawa(a: float, b: float) -> bool:
    return any(abs(a * k - b) <= 2.0 for k in (1.0, 0.5, 2.0))


def _powody(h: dict, tempo: dict | None, q: dict | None,
            c: dict | None = None, bpm_tag: float | None = None) -> list[Powod]:
    out: list[Powod] = []
    bpm = h.get("bpm")
    conf_bpm = h.get("confidence_bpm")
    if bpm and bpm_tag and not _ta_sama_oktawa(bpm, bpm_tag):
        # tag ze sklepu (Beatport) to najlepsza podpowiedź, jaką mamy —
        # pomyłka nie musi być podwojeniem: Asia ma 98, a apka liczyła 139
        out.append(Powod(
            "bpm_inne_niz_w_tagu",
            f"apka liczy {bpm:.0f} BPM, a w tagu pliku jest {bpm_tag:.0f} — "
            f"posłuchaj, które jest prawdziwe", WAGI["bpm_inne_niz_w_tagu"]))
    if bpm and conf_bpm is not None and conf_bpm < PROG_TEMPA:
        out.append(Powod(
            "tempo_niepewne",
            f"tempo {bpm:.0f} BPM z pewnością {conf_bpm:.2f} — apka nie jest "
            f"go pewna; najczęstsza pomyłka to podwojenie albo połowienie "
            f"({bpm / 2:.0f} / {bpm * 2:.0f}), ale bywa też zupełnie inne tempo — "
            f"posłuchaj", WAGI["tempo_niepewne"]))
    conf_key = h.get("confidence_key")
    if h.get("key") and conf_key is not None and conf_key < PROG_TONACJI:
        out.append(Powod(
            "tonacja_niepewna",
            f"tonacja {h['key']} z pewnością {conf_key:.2f} — sąsiednia "
            f"na kole Camelota jest równie prawdopodobna",
            WAGI["tonacja_niepewna"]))
    if tempo:
        if not tempo.get("stabilne", True):
            out.append(Powod(
                "tempo_zmienne",
                tempo.get("opis") or "tempo nie trzyma się przez cały utwór "
                "— jedna siatka go nie obejmie", WAGI["tempo_zmienne"]))
        elif tempo.get("bpm_nietrafione") and tempo.get("bpm_poprawione"):
            out.append(Powod(
                "bpm_nietrafione",
                f"siatka rozjeżdża się przez BPM nietrafione o ułamek — "
                f"proponowana poprawka {tempo['bpm_poprawione']:.1f}",
                WAGI["bpm_nietrafione"]))
    if c and c.get("pewnosc_siatki") is not None:
        # siatka liczona na stopie (siatka.py): niska spójność znaczy, że
        # stopa jest niewyraźna albo tempo pływa — siatka może leżeć obok
        if c["pewnosc_siatki"] < PROG_SIATKI:
            out.append(Powod(
                "siatka_niepewna",
                f"siatka beatów z pewnością {c['pewnosc_siatki']:.2f} — stopa "
                f"niewyraźna, kotwica może leżeć obok uderzenia",
                WAGI["siatka_niepewna"]))
        elif (c.get("pewnosc_taktu") is not None
              and c["pewnosc_taktu"] < PROG_TAKTU):
            out.append(Powod(
                "takt_niepewny",
                f"jedynka taktu z pewnością {c['pewnosc_taktu']:.2f} — "
                f"rekordbox może liczyć takty od bitu {c.get('battito', 1)}, "
                f"sprawdź, czy frazy zaczynają się na jedynce",
                WAGI["takt_niepewny"]))
    if q:
        if q.get("grade") == "bad":
            out.append(Powod("transkod", f"jakość: {q.get('verdict', '')}",
                             WAGI["transkod"]))
        elif q.get("grade") == "warn":
            out.append(Powod("jakosc_do_oceny",
                             f"jakość do oceny: {q.get('verdict', '')}",
                             WAGI["jakosc_do_oceny"]))
    return out


def sprawdz(folder: str) -> dict:
    """Przejrzyj bibliotekę i zbierz utwory warte sprawdzenia uchem.

    Zwraca słownik gotowy do wysłania jako JSON: listę utworów (najpilniejsze
    najpierw), liczbę sprawdzonych i liczbę bez analizy.
    """
    from .uklad import odcisk_pliku
    pliki = matcher.audio_files(folder)
    utwory: list[DoSprawdzenia] = []
    bez_analizy = bez_tempa = 0
    widziane: dict[str, DoSprawdzenia] = {}
    kopie: dict[str, int] = {}
    for p in pliki:
        h = cache.get(p, "harmonic")
        if h is None:
            bez_analizy += 1
            continue
        # ten sam plik w dwóch miejscach biblioteki to JEDEN utwór do odsłuchu
        odc = odcisk_pliku(p)
        if odc in widziane:
            kopie[odc] = kopie.get(odc, 1) + 1
            continue
        t = cache.get(p, "tempo")
        if t is None:
            bez_tempa += 1
        powody = _powody(h, t, cache.get(p, "quality"),
                         cache.get(p, "cues"), bpm_tag=bpm_z_tagu(p))
        u = DoSprawdzenia(p, h.get("bpm"), h.get("camelot"), h.get("key"), powody)
        widziane[odc] = u
        if powody:
            powody.sort(key=lambda x: -x.waga)
            utwory.append(u)
    utwory.sort(key=lambda u: (-u.waga, u.file.lower()))
    kopii_dla = {id(u): kopie.get(o, 1) for o, u in widziane.items()}
    return {
        "utwory": [{
            "file": u.file, "bpm": u.bpm, "camelot": u.camelot, "key": u.key,
            "waga": u.waga, "kopii": kopii_dla.get(id(u), 1),
            "powody": [{"kod": p.kod, "opis": p.opis, "waga": p.waga}
                       for p in u.powody],
        } for u in utwory],
        "sprawdzonych": len(widziane),
        "bez_analizy": bez_analizy,
        # stabilność tempa liczy się osobno (POST /api/tempo) — bez niej
        # powody „tempo zmienne” i „BPM nietrafione” nie mają skąd się wziąć
        "bez_sprawdzenia_tempa": bez_tempa,
        "progi": {"tempo": PROG_TEMPA, "tonacja": PROG_TONACJI},
    }


def format_report(wynik: dict) -> str:
    """Wersja dla terminala."""
    linie = []
    u = wynik["utwory"]
    if not u:
        linie.append(f"nic do sprawdzania uchem — {wynik['sprawdzonych']} "
                     f"utworów z pewnymi wynikami")
    else:
        linie.append(f"{len(u)} utworów do sprawdzenia uchem "
                     f"(z {wynik['sprawdzonych']} przeanalizowanych):")
        ikona = {3: "‼", 2: "!", 1: "·"}
        for t in u:
            linie.append(f"  {ikona[t['waga']]} {os.path.basename(t['file'])}")
            for p in t["powody"]:
                linie.append(f"      – {p['opis']}")
    if wynik["bez_analizy"]:
        linie.append(f"{wynik['bez_analizy']} utworów bez analizy — "
                     f"uruchom „Analizuj”, żeby je ocenić")
    if wynik.get("bez_sprawdzenia_tempa"):
        linie.append(f"{wynik['bez_sprawdzenia_tempa']} utworów bez sprawdzenia "
                     f"stabilności tempa — zmienne tempo i nietrafione BPM wyjdą "
                     f"dopiero po „Sprawdź tempo” w aplikacji")
    return "\n".join(linie)
