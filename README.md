# selekta

Playlista → czysta, zweryfikowana biblioteka DJ-ska. Terminal **i** dashboard w przeglądarce.

Wklejasz playlistę (Spotify, Apple Music, YouTube, Tidal, SoundCloud,
1001Tracklists albo tekst), a selekta znajduje utwory na Soulseeku
(przez Twój slskd), pokazuje legalne alternatywy zakupu (Beatport /
Bandcamp), taguje, robi okładki, wykrywa BPM i tonację, układa set
harmonicznie, **weryfikuje jakość i tożsamość** każdego pliku i pilnuje
zdrowia całej biblioteki.

## Dashboard

```
selekta serve --folder ~/Music/dj
```

Otwiera http://localhost:8756 — biblioteka z okładkami, jakością,
BPM/tonacją (kolory koła Camelot), zakładki **Kolejność setu** i
**Zdrowie** (uszkodzone pliki, duplikaty, braki okładek).

## Komendy (18, wszystkie przetestowane na żywej bibliotece)

```
organize   dopasuj pliki do playlisty, otaguj, okładki, nazwy
check      pełna weryfikacja pobrań: integralność + tożsamość + jakość
match      weryfikacja przez odsłuch (fingerprint vs preview Spotify)
verify     raport jakości (detektor fałszywych FLAC-ów)
analyze    BPM + tonacja + kolejność harmoniczna (--order); cache
loudness   głośność LUFS + ReplayGain (spójny poziom setu)
cues       intro / outro / drop / pierwsze uderzenie
covers     audyt okładek; --fill dociąga z iTunes
icons      pokaż okładki FLAC/WAV w Finderze (macOS)
tagfix     napraw uszkodzone tagi (mojibake)
dedupe     usuń duplikaty (najlepsza kopia zostaje)
health     dashboard tekstowy: duplikaty, uszkodzenia, braki
export     rekordbox (XML) / Serato (.crate) / M3U8
usb        płaski folder pod CDJ (nazwy FAT32, WAV→AIFF/FLAC, ASCII)
radar      nowe wydania Twoich artystów (Beatport/Bandcamp)
wishlist   lista życzeń + cykliczne szukanie na Soulseeku
hunt       szukaj brakujących na Soulseeku + linki zakupowe
serve      dashboard w przeglądarce
```

## Funkcje → moduły

| Funkcja | Moduł | Stan (walidacja na Twojej bibliotece) |
|---|---|---|
| Weryfikacja przez odsłuch | `verify_match.py` | ✅ pozytyw 0.81–0.93, negatyw 0.05–0.22 |
| Auto-weryfikacja po pobraniu | `pipeline.py` | ✅ złapał ucięty transfer (Heaven & Hell), którego widmo w środku nie widziało |
| Detektor fałszywej jakości | `quality.py` | ✅ złapał 24-bit FLAC ze źródła 128 kbps |
| Świadomość wersji miksu | `matcher.py` | ✅ czas trwania + sygnatura miksu |
| BPM + tonacja + harmonic | `harmonic.py` | ✅ klucz 4/4, BPM 4/4 vs ground truth |
| Głośność / ReplayGain | `loudness.py` | ✅ mastery klubowe -6..-10 LUFS, bez przesteru |
| Intro/outro/drop | `cues.py` | ✅ 42/42 sanity, 0.30 s/plik |
| Naprawa mojibake | `tagfix.py` | ✅ Ã…MRTÃœM→ÅMRTÜM, 0 fałszywych alarmów |
| Deduplikacja | `dedupe.py` | ✅ zostawia FLAC nad WAV (nie „większy plik”) |
| Zdrowie biblioteki | `health.py` | ✅ 2 uszkodzone, duplikaty, braki okładek |
| Cache analiz | `cache.py` | ✅ 3.0 s → 0.16 s (19×) na powtórce |
| Import z wielu źródeł | `importers.py` | ✅ Spotify/Apple/YT/1001TL/SC/tekst |
| Eksport DJ | `dj_export.py` | ✅ rekordbox XML + Serato + M3U8 |
| USB pod CDJ | `usb.py` | ✅ WAV→AIFF, folduje diakrytyki |
| Radar nowości | `radar.py` | ✅ 59 artystów, Beatport OK |
| Dashboard | `web.py` + `static/` | ✅ 3 zakładki, żywe dane |
| Oficjalny klucz/BPM (Beatport) | `keysource.py` | ⏳ w walidacji |

## Wymagania

Python 3.11+, ffmpeg/ffprobe. `pip install -e ".[web]"` (dashboard).
Opcjonalnie: slskd (Soulseek), `.[macos]` (ikony Findera).

## Do produktu na sprzedaż

1. Dashboard → opakowanie w Tauri (sprzedawalna binarka; licencje przez
   Gumroad/Lemon Squeezy).
2. Soulseek zawsze jako *bring-your-own slskd* — apka jest menedżerem
   biblioteki i wyszukiwarką zakupową; nie dystrybuuje cudzych nagrań.
3. Spotify przez oficjalne Web API przed publikacją.
