# Selekta

Porządek w bibliotece DJ-skiej — za darmo, na Maca.

Wklejasz playlistę (Spotify, Apple Music, YouTube, Tidal, SoundCloud,
1001Tracklists albo zwykły tekst), a Selekta znajduje utwory na Soulseeku
przez Twój własny slskd, pokazuje gdzie je kupić legalnie (Beatport,
Bandcamp), **sprawdza, czy pobrany plik to naprawdę ten utwór i naprawdę
ta jakość**, taguje, dociąga okładki, wykrywa BPM i tonację, układa set
harmonicznie i wypuszcza wszystko do rekordboxa, Serato albo na pendrive
pod CDJ.

## Pobierz i uruchom

1. Wejdź w [Wydania](https://github.com/Qbot99/selekta/releases) i pobierz zip
   dla swojego Maca: **arm64** (Apple Silicon: M1/M2/M3/M4) albo
   **x86_64** (Intel).
2. Rozpakuj i przenieś `Selekta.app` do Aplikacji.
3. Apka nie jest podpisana certyfikatem Apple (to kosztuje 99 $ rocznie),
   więc macOS przy pierwszym otwarciu powie, że nie może jej sprawdzić.
   Na **macOS 15 i nowszych**: zamknij ten komunikat, wejdź w Ustawienia
   systemowe → Prywatność i bezpieczeństwo, przewiń na dół i kliknij
   **„Otwórz mimo to"** przy Selekcie. Na starszych systemach wystarczy
   kliknąć ikonę prawym przyciskiem → Otwórz. Pytanie pojawia się raz.
   (Dla wprawionych: `xattr -d com.apple.quarantine /Applications/Selekta.app`
   robi to samo bez klikania.)
4. Otworzy się ekran powitalny, a po nim dashboard w przeglądarce.
   Kreator **„Zanim zaczniesz"** przeprowadzi Cię przez resztę: wskazanie
   folderu z muzyką, instalację slskd (klient Soulseeka) i logowanie.

Nic więcej nie trzeba instalować — ffmpeg do analizy audio i czcionki są
w środku; apka działa bez internetu (Soulseek, Spotify i sklepy oczywiście
go potrzebują).

## Co robi

| Zakładka | Do czego |
|---|---|
| **Biblioteka** | wszystkie utwory z okładkami, jakością, BPM i tonacją (kolory koła Camelot); odsłuch, szczegóły, ręczna korekta siatki beatów |
| **Import** | wklej playlistę — Selekta powie, co masz, czego brakuje, i znajdzie braki na Soulseeku albo da link do sklepu |
| **Kolejność setu** | ułożenie harmoniczne + łuk energii: gdzie wejść, gdzie jest kulminacja |
| **Zdrowie** | uszkodzone pliki, duplikaty (zostaje najlepsza kopia), krzaczki w tagach, brak okładek |
| **Sprawdź uchem** | utwory, przy których Selekta **nie jest pewna** tempa lub tonacji, siatka pływa albo plik wygląda na przerobiony z MP3 — do odsłuchania przed graniem |
| **Eksport** | rekordbox XML (z siatką, cue i Twoją ręczną pracą), Serato, M3U8, pendrive pod CDJ |
| **Radar** | nowe wydania artystów, których masz w bibliotece |
| **Pobierania** | kolejka Soulseeka — przeżywa zamknięcie apki i wznawia się sama |
| **Ustawienia** | kreator slskd, folder, klucz API, **doktor** integracji (czy Spotify, Beatport, iTunes, YouTube jeszcze działają) |

### Weryfikacja pobrań — dlaczego to ważne

Na Soulseeku łatwo dostać „FLAC", który jest przerobionym MP3 128 kbps,
albo plik o właściwej nazwie i cudzej zawartości. Selekta sprawdza każde
pobranie trzema bramkami: **integralność** (czy plik nie jest ucięty),
**tożsamość** (odsłuch: odcisk dźwięku vs 30-sekundowy fragment
z serwisu) i **jakość** (analiza widma: transkod ma nad cięciem ścianę
i cyfrową ciszę, prawdziwy master — łagodne zbocze). Przy wyborze pliku
do pobrania jakość stoi przed popularnością: rzadki FLAC wygrywa
z rozpowszechnioną 128-tką.

### Siatka beatów — na stopie, nie na hi-hacie

Kotwica siatki jest liczona z uderzeń, które mają jednocześnie ostry
atak i skok basu 40–160 Hz — czyli ze stopy. Sam „najostrzejszy transjent"
w hard techno bywa otwartym hi-hatem na „i", i wtedy siatka ląduje między
kopnięciami (tak było do wersji 0.4.1). Do XML rekordboxa trafia też numer
bitu kotwicy w takcie (`Battito`), wyznaczony z crashy i granic sekcji.
Utwory, przy których stopa jest niewyraźna albo jedynka taktu niepewna,
lądują w zakładce **Sprawdź uchem**.

Rekordbox **nie nadpisuje** siatki utworów, które już ma w kolekcji. Żeby
wczytać poprawioną: Preferencje → Zaawansowane → Baza danych → wskaż XML
ponownie, usuń te utwory z kolekcji (pliki zostają), a potem w drzewie
„rekordbox xml" → Playlists → prawy przycisk → „Importuj playlistę".

## Terminal (dla wprawionych)

Ta sama aplikacja działa też z linii poleceń — przydatne do skryptów
i dużych bibliotek.

```
pip install "selekta[web] @ git+https://github.com/Qbot99/selekta"
selekta serve --folder ~/Music/dj        # dashboard
selekta uchem --folder ~/Music/dj        # co sprawdzić uchem przed graniem
selekta doctor                           # czy integracje jeszcze działają
```

```
organize   dopasuj pliki do playlisty, otaguj, okładki, nazwy
check      pełna weryfikacja pobrań: integralność + tożsamość + jakość
match      weryfikacja przez odsłuch (fingerprint vs preview)
verify     raport jakości (detektor fałszywych FLAC-ów, bitrate)
analyze    BPM + tonacja + kolejność harmoniczna (--order); cache
loudness   głośność LUFS + ReplayGain (spójny poziom setu)
cues       intro / outro / drop / pierwsze uderzenie
covers     audyt okładek; --fill dociąga z iTunes
icons      pokaż okładki FLAC/WAV w Finderze
tagfix     napraw uszkodzone tagi (mojibake, także cp1250)
dedupe     usuń duplikaty (najlepsza kopia zostaje)
health     stan biblioteki: duplikaty, uszkodzenia, braki
uchem      niepewne tempo/tonacja, pływająca siatka, podejrzana jakość
export     rekordbox (XML z siatką i cue) / Serato (.crate) / M3U8
usb        płaski folder pod CDJ (nazwy FAT32, WAV→AIFF/FLAC, ASCII)
radar      nowe wydania Twoich artystów (Beatport/Bandcamp)
wishlist   lista życzeń + cykliczne szukanie na Soulseeku
hunt       szukaj brakujących na Soulseeku + linki zakupowe
doctor     sprawdź integracje i narzędzia (ffmpeg, slskd, Spotify…)
serve      dashboard w przeglądarce
```

Wymagania w tym trybie: Python 3.11+, `ffmpeg`/`ffprobe` w PATH
(`brew install ffmpeg`). Soulseek zawsze jako *własny slskd* — Selekta
jest menedżerem biblioteki i wyszukiwarką, nie rozpowszechnia nagrań.

## Dashboard — jak jest zbudowany

Interfejs to projekt graficzny z 3.09.2026 (`docs/design/`): ciemny,
jeden akcent `#ff6a3d`, Urbanist + DM Mono, boczna nawigacja w trzech
grupach (Set · Biblioteka · Więcej), dolny player. Kod bez bundlera:
`selekta/static/index.html` to powłoka (układ, tokeny CSS, `S` — router,
zapytania, arkusze, player), a `selekta/static/ekrany/*.js` to ekrany,
każdy rejestruje się przez `S.ekran(id, {render, load})`. Poprzedni
dashboard został pod `/stary` na czas przesiadki.

## Dla programistów

```
git clone https://github.com/Qbot99/selekta && cd selekta
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,macos]" pytest
pytest -q -m "not network"          # ~5 min; testy sieciowe: pytest -m network
packaging/build_mac.sh              # Selekta.app do dist/
```

Wydanie: tag `vX.Y.Z` na `main` — GitHub Actions buduje `Selekta.app` na
Apple Silicon i Intel i dołącza zipy do wydania.

### Jak są pilnowane wyniki

Zestaw ma dwie warstwy, które sprawdzają różne rzeczy.

**Testy zachowania** (większość) pilnują, czy kod nie rzuca wyjątkiem
i czy przepływ ma sens.

**Testy regresyjne** pilnują LICZB. Bez nich przestawienie progu
w detekcji fałszywego lossless albo zmiana okna przy liczeniu BPM
przechodzi przez cały zestaw, a wyniki cicho się przesuwają — i człowiek
dowiaduje się o tym, ufając złej liczbie w klubie.

* `tests/test_regresja_dsp.py` — sygnały o ZNANYCH właściwościach,
  generowane kodem (`tests/probka.py`): metronom o zadanym tempie, szum
  z pasmem uciętym dokładnie na 16 kHz, kadencja w zadanej tonacji.
  Odpowiadają na pytanie „czy wynik jest POPRAWNY", bo prawdę znamy
  z fizyki sygnału. Tonacja sprawdzana we wszystkich 24 tonacjach,
  tempo w przemiataniu 70–182 BPM.

* `tests/test_regresja_biblioteka.py` — migawka wyników dla stałego
  zestawu prawdziwych plików (własnych, wskazanych przez
  `SELEKTA_LIBRARY_FOLDER`). Odpowiada na inne pytanie: „czy moja zmiana
  ruszyła coś, czego nie zamierzałem ruszyć". Pomija się sam, gdy nie ma
  biblioteki albo migawki. Odświeżenie po ZAMIERZONEJ zmianie algorytmu:
  `python -m tests.test_regresja_biblioteka --zapisz`.

**Pułapka przy ręcznym badaniu progów:** podmiana stałej na wartość o tej
samej długości (`0.3` → `1.0`) nie zmienia rozmiaru pliku, więc Python
potrafi wczytać zbuforowany bajtkod i pokazać stary wynik. Bez `-B` albo
skasowania `__pycache__` wychodzi fałszywy wniosek, że stała nic nie robi.

## Licencja

MIT — rób z tym, co chcesz, tylko zostaw notkę o autorze.
