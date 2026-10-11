/* ============================================================
   kreator.js — trzy ekrany z projektu graficznego (docs/design):
     • „tryb"    (2a)  — wybór trybu po starcie: AUTOMATYCZNY / RĘCZNY
     • „kreator" (tura 1) — kreator 5 kroków z własnym bocznym paskiem
     • arkusz „Wybór wyniku Soulseek" (2b) — S.wybierzWynik(utwor, opts)
   Vanilla JS, bez bundlera. Wygląd 1:1 z projektu; dane z endpointów.
   ============================================================ */
(() => {
  const {esc, fmtTime, fmtMB, fmtLicz, CAM, $, $$, on, api, toast} = S;
  const K = S.K;

  /* ---------- słownik z projektu (1:1) + kilka kluczy na stany, których
     makieta nie pokazywała (komunikaty postępu i błędów interfejsu) ---------- */
  const I18N = {
    pl: {
      windowTitle:'SELEKTA — PRZYGOTOWANIE SETU', stepsHead:'KROKI', slsk:'Soulseek połączony',
      steps:[['Wklej playlistę','Spotify, Apple, YouTube, plik'],['Masz / do ściągnięcia','porównanie z biblioteką'],['Nazwa setu','tak zobaczysz go w rekordboksie'],['Sprawdzam','BPM, tonacja, jakość, okładki'],['Sprawdź przed graniem','poprawki i eksport']],
      s1kicker:'KROK 1 / 5', s1title:'Wklej playlistę', s1sub:'Spotify, Apple Music, YouTube, Tidal, SoundCloud, 1001Tracklists — albo zwykła lista tekstem.', s1hint:'Enter = szukaj u mnie', s1cta:'SZUKAJ U MNIE', s1or:'albo weź playlistę z komputera', s1drop:'Przeciągnij tu plik playlisty', s1folder:'Wybierz folder z muzyką…', s1folderSub:'Posprzątamy go w miejscu — pliki zostają tam, gdzie są.',
      s2kicker:'KROK 2 / 5', s2title:'Co już masz, a czego brakuje', s2sub:'Każdy pobrany utwór od razu wskakuje do „masz u siebie”.', have:'MASZ', toGet:'BRAKUJE', haveTitle:'Masz u siebie', poolTitle:'Do ściągnięcia', dlAll:'Pobierz wszystko', dl:'Pobierz', pick:'Wybierz…', s2foot:'Możesz iść dalej — pobierania dokończą się w tle.', next:'DALEJ',
      s3kicker:'KROK 3 / 5', s3title:'Jak nazwiemy set?', s3sub:'Pod tą nazwą znajdziesz playlistę w rekordboksie.', s3foot:'Nazwę zmienisz później w rekordboksie.',
      s4kicker:'KROK 4 / 5', s4title:'Sprawdzam playlistę', s4sub:'Zbieram pliki, liczę BPM i tonację, sprawdzam jakość, okładki i tagi.', stages:['Zbieram pliki','BPM i tonacja','Jakość i integralność','Okładki i tagi'], stStates:['gotowe','w toku','czeka','czeka'], analyzing:'analizuję',
      s5kicker:'KROK 5 / 5', s5title:'Sprawdź przed graniem', s5sub:'Ostatni moment na poprawki — potem playlista idzie do rekordboxa.', tracks:'UTWORÓW', toReview:'DO OBEJRZENIA', median:'MEDIANA', fixAll:'Napraw wszystko (2)', betterAll:'Szukaj lepszych wersji (1)', betterNote:'ok. minuty na utwór', fix:'Napraw', better:'Szukaj lepszej', remove:'Usuń z setu', s5note:'Zamknij rekordbox przed kliknięciem — inaczej nadpisze ustawienia przy wyjściu.', play:'ZACZNIJ GRAĆ',
      doneTitle:'Set czeka w rekordboksie', doneSub:'„{name}” (12 utworów) — odpal rekordbox i graj.', again:'Nowy set',
      prob:{tagi:'NAZWA',okladka:'OKŁADKA',jakosc:'JAKOŚĆ',integralnosc:'PRZESKOKI',tempo:'TEMPO',duplikat:'DUBEL'},
      st:{searching:'szukam…',queued:'w kolejce',downloading:'pobieram',failed:'brak wyniku'},
      notes:{other:'inna wersja',similar:'podobne',ok:'✓'},
      propTitle:'Masz inną wersję — zdecyduj', propUse:'Użyj mojej', propGet:'Pobierz właściwą', propHas:'masz: {file}', propLen:'{mine} zamiast {want}',
      propWait:'{n} {utw} z inną wersją czeka na Twoją decyzję — bez niej nie trafią do setu.', buy:'kup', importNote:'Uwaga',
      // --- stany spoza makiety ---
      manual:'TRYB RĘCZNY', slskAmber:'Soulseek: rozłączony', slskRed:'slskd nie działa', slskOff:'brak połączenia z apką',
      justGot:'właśnie pobrane', noneHave:'nic z tej playlisty', allGot:'wszystko ściągnięte',
      emptyPaste:'Najpierw wklej link albo wgraj plik.', checking:'sprawdzam, co już masz…', reading:'czytam {name}…', readingDisk:'czytam z dysku…',
      loaded:'wczytano {n} utworów', fromFile:' — {n} wskazuje wprost na pliki na dysku',
      pickerOpen:'otwieram okno wyboru — sprawdź, czy nie schowało się za przeglądarką',
      tidy:'POSPRZĄTAJ TEN FOLDER', tidySub:'analiza i naprawa w Twoich plikach — nic nie kopiuję', makeSet:'ZRÓB Z TEGO SET', makeSetSub:'kopia do nowej playlisty, gotowa na pendrive',
      pathManual:'Wolisz wpisać ścieżkę ręcznie?', pathPh:'~/Music/moj-set  albo  ~/Desktop/set.m3u', load:'Wczytaj', pathNote:'Przeglądarka nie podaje nam, gdzie leżał wgrany plik, więc ścieżki względne w M3U da się rozwiązać tylko tą drogą.',
      queuedAll:'w kolejce: {n} — pobieram po kolei, gotowe przeskakują w lewo', adding:'DODAJĘ DO KOLEJKI…',
      collecting:'zbieram pliki…', collected:'playlista: {n} utworów', late:' (w tym {n} dociągniętych po drodze)', reviewing:'sprawdzam jakość, okładki i tagi…', reviewed:'gotowe — {n} utworów, {m} do obejrzenia',
      tidyTitle:'Sprzątam {name}', tidySub4:'{n} plików — liczę BPM i tonację, sprawdzam jakość, okładki i tagi. Pliki zostają tam, gdzie są.', retry:'Spróbuj ponownie',
      stop:'Przerwij', allOk:'Nazwy, okładki, jakość i tempo sprawdzone.', decide:'Napraw, usuń z setu albo zostaw — decyzja należy do Ciebie.',
      missingFiles:'Nie znalazłem {n} {pliki}', missingFilesSub:'{list} — nie ma ich w folderze playlisty, więc nie trafią do rekordboxa', restOk:'Reszta ({n}) jest w porządku',
      fixed:'naprawione: {ok}', fixedFail:' · nie dało się: {n}', fixAllNote:'uzupełni tagi i okładki po kolei',
      nothingBetter:'nic lepszego nie znalazłem (sprawdziłem {n} wyników dla „{q}”)', searchingSlsk:'przeszukuję Soulseeka (to trwa ok. minuty)…', betterN:'lepsze: {n}', inQueue:'✓ w kolejce', lossless:'bezstratny',
      betterDone:'gotowe — lepsze wersje dla {n} z {m}. Kliknij „Pobierz” przy tych, które chcesz.', interrupted:' (przerwane)',
      waitSlsk:'⏸ Soulseek rozłączony — czekam na powrót ({s}s)', slskGone:'✗ Soulseek nie wrócił — przerywam. Zrobione {i} z {n}.', totalMin:'{n} min łącznie',
      exporting:'wysyłam do rekordboxa…', exportFail:'nie udało się wysłać do rekordboxa',
      sheet:{kicker:'WYBIERZ WERSJĘ', results:['WYNIK','WYNIKI','WYNIKÓW'], inList:'w playliście', cols:['PLIK / UŻYTKOWNIK','FORMAT','ROZMIAR','CZAS','PRĘDKOŚĆ',''], best:'najlepszy wynik: bezstratny, czas się zgadza, szybkie źródło', after:'po pobraniu: weryfikacja odsłuchem + jakość', dl:'POBIERZ', dlOther:'Pobierz', searching:'szukam na Soulseeku…', searchedAs:'szukano po: {q}', none:'Nic nie znaleziono. Dodaj utwór do listy życzeń — apka sprawdzi ponownie później.', wish:'Dodaj do życzeń', wished:'✓ na liście życzeń', free:'wolny slot', busy:'zajęty', queued:'✓ pobieram {file} od {user}'},
      utw:['utwór','utwory','utworów'], plk:['pliku','plików','plików'],
    },
    en: {
      windowTitle:'SELEKTA — SET PREP', stepsHead:'STEPS', slsk:'Soulseek connected',
      steps:[['Paste a playlist','Spotify, Apple, YouTube, file'],['Have / to fetch','matched against your library'],['Name the set','how it shows up in rekordbox'],['Checking','BPM, key, quality, covers'],['Review before playing','fixes and export']],
      s1kicker:'STEP 1 / 5', s1title:'Paste a playlist', s1sub:'Spotify, Apple Music, YouTube, Tidal, SoundCloud, 1001Tracklists — or a plain text tracklist.', s1hint:'Enter = search my library', s1cta:'SEARCH MY LIBRARY', s1or:'or take a playlist from this computer', s1drop:'Drop a playlist file here', s1folder:'Pick a music folder…', s1folderSub:'We tidy it in place — files stay where they are.',
      s2kicker:'STEP 2 / 5', s2title:'What you have, what is missing', s2sub:'Every finished download jumps straight into “you have it”.', have:'HAVE', toGet:'MISSING', haveTitle:'You have it', poolTitle:'To fetch', dlAll:'Fetch all', dl:'Fetch', pick:'Choose…', s2foot:'You can move on — downloads finish in the background.', next:'NEXT',
      s3kicker:'STEP 3 / 5', s3title:'What do we call the set?', s3sub:'This is the playlist name you will see in rekordbox.', s3foot:'You can rename it later in rekordbox.',
      s4kicker:'STEP 4 / 5', s4title:'Checking the playlist', s4sub:'Collecting files, computing BPM and key, checking quality, covers and tags.', stages:['Collecting files','BPM and key','Quality and integrity','Covers and tags'], stStates:['done','running','waiting','waiting'], analyzing:'analyzing',
      s5kicker:'STEP 5 / 5', s5title:'Review before playing', s5sub:'Last chance for fixes — then the playlist goes to rekordbox.', tracks:'TRACKS', toReview:'TO REVIEW', median:'MEDIAN', fixAll:'Fix all (2)', betterAll:'Find better versions (1)', betterNote:'about a minute per track', fix:'Fix', better:'Find better', remove:'Drop from set', s5note:'Close rekordbox before clicking — otherwise it overwrites settings on exit.', play:'START PLAYING',
      doneTitle:'Your set is waiting in rekordbox', doneSub:'“{name}” (12 tracks) — open rekordbox and play.', again:'New set',
      prob:{tagi:'NAME',okladka:'COVER',jakosc:'QUALITY',integralnosc:'DROPOUTS',tempo:'TEMPO',duplikat:'DUPE'},
      st:{searching:'searching…',queued:'queued',downloading:'downloading',failed:'no result'},
      notes:{other:'other version',similar:'similar',ok:'✓'},
      propTitle:'You have another version — decide', propUse:'Use mine', propGet:'Fetch the right one', propHas:'you have: {file}', propLen:'{mine} instead of {want}',
      propWait:'{n} {utw} with another version wait for your decision — without it they stay out of the set.', buy:'buy', importNote:'Note',
      manual:'MANUAL MODE', slskAmber:'Soulseek: disconnected', slskRed:'slskd is not running', slskOff:'app not reachable',
      justGot:'just downloaded', noneHave:'nothing from this playlist', allGot:'everything fetched',
      emptyPaste:'Paste a link or upload a file first.', checking:'checking what you already have…', reading:'reading {name}…', readingDisk:'reading from disk…',
      loaded:'loaded {n} tracks', fromFile:' — {n} point straight at files on disk',
      pickerOpen:'opening the file dialog — check whether it hid behind the browser',
      tidy:'TIDY THIS FOLDER', tidySub:'analysis and fixes in your files — nothing gets copied', makeSet:'MAKE A SET OUT OF IT', makeSetSub:'copy into a new playlist, ready for a USB stick',
      pathManual:'Prefer to type the path?', pathPh:'~/Music/my-set  or  ~/Desktop/set.m3u', load:'Load', pathNote:'The browser does not tell us where an uploaded file lived, so relative M3U paths can only be resolved this way.',
      queuedAll:'queued: {n} — fetching one by one, finished ones jump left', adding:'ADDING TO QUEUE…',
      collecting:'collecting files…', collected:'playlist: {n} tracks', late:' (incl. {n} that arrived on the way)', reviewing:'checking quality, covers and tags…', reviewed:'done — {n} tracks, {m} to review',
      tidyTitle:'Tidying {name}', tidySub4:'{n} files — computing BPM and key, checking quality, covers and tags. Files stay where they are.', retry:'Try again',
      stop:'Stop', allOk:'Names, covers, quality and tempo checked.', decide:'Fix, drop from the set or leave it — your call.',
      missingFiles:'Could not find {n} {pliki}', missingFilesSub:'{list} — not in the playlist folder, so they will not reach rekordbox', restOk:'The rest ({n}) is fine',
      fixed:'fixed: {ok}', fixedFail:' · failed: {n}', fixAllNote:'fills in tags and covers one by one',
      nothingBetter:'nothing better found (checked {n} results for “{q}”)', searchingSlsk:'searching Soulseek (takes about a minute)…', betterN:'better: {n}', inQueue:'✓ queued', lossless:'lossless',
      betterDone:'done — better versions for {n} of {m}. Click “Fetch” next to the ones you want.', interrupted:' (stopped)',
      waitSlsk:'⏸ Soulseek disconnected — waiting for it to come back ({s}s)', slskGone:'✗ Soulseek did not come back — stopping. Done {i} of {n}.', totalMin:'{n} min total',
      exporting:'sending to rekordbox…', exportFail:'could not send to rekordbox',
      sheet:{kicker:'PICK A VERSION', results:['RESULT','RESULTS','RESULTS'], inList:'in playlist', cols:['FILE / USER','FORMAT','SIZE','LENGTH','SPEED',''], best:'best result: lossless, length matches, fast source', after:'after download: listening check + quality', dl:'FETCH', dlOther:'Fetch', searching:'searching Soulseek…', searchedAs:'searched as: {q}', none:'Nothing found. Add the track to the wishlist — the app will check again later.', wish:'Add to wishlist', wished:'✓ on the wishlist', free:'free slot', busy:'busy', queued:'✓ fetching {file} from {user}'},
      utw:['track','tracks','tracks'], plk:['file','files','files'],
    },
  };
  const T = () => I18N[S.jezyk.get()] || I18N.pl;
  const fmt = (s, o) => String(s).replace(/\{(\w+)\}/g, (_, k) => (o && o[k] != null) ? o[k] : '');
  // liczebnik: 1 utwór · 2–4 utwory · 5+ utworów (z wyjątkiem 12–14)
  const lm = (n, f) => { n = Math.abs(n|0); const r = n % 10, rr = n % 100; return f[n === 1 ? 0 : (r >= 2 && r <= 4 && !(rr >= 12 && rr <= 14)) ? 1 : 2]; };
  const utworow = n => `${n} ${lm(n, T().utw)}`;
  const HEAVY = typ => typ === 'jakosc' || typ === 'integralnosc';
  const PROB_TYP = typ => typ === 'tempo-zmienne' ? 'tempo' : typ;

  /* ---------- style z projektu (stany :hover nie dają się zapisać inline) ---------- */
  const CSS = `
.kr{height:100vh;display:grid;grid-template-columns:264px 1fr;grid-template-rows:44px 1fr;overflow:hidden;position:relative;background:var(--bg)}
.tb-pelny{display:flex;align-items:center;padding:0 16px;gap:8px;height:44px;border-bottom:1px solid var(--line2);user-select:none;-webkit-app-region:drag}
.kr .tb-pelny{grid-column:1/3;height:auto}
.tb-pelny .kropka{width:12px;height:12px;border-radius:50%;background:var(--line3);flex-shrink:0}
.tb-pelny .tyt{margin-left:auto;margin-right:auto;font:500 11px var(--mono);letter-spacing:.12em;color:var(--dim2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tb-pelny .prawy{min-width:52px;display:flex;justify-content:flex-end;-webkit-app-region:no-drag}
.tb-pelny .prawy button{background:transparent;border:0;color:var(--dim2);font:500 11px var(--mono);letter-spacing:.1em;padding:6px 8px;border-radius:6px;white-space:nowrap}
.tb-pelny .prawy button:hover{color:var(--acc)}
.kr aside{border-right:1px solid var(--line2);display:flex;flex-direction:column;padding:28px 24px 24px;gap:0;overflow:auto;min-height:0}
.kr .logo{display:flex;align-items:center;gap:10px;margin-bottom:44px;cursor:pointer}
.kr .logo img{width:34px;height:34px;object-fit:contain;filter:drop-shadow(0 0 10px rgba(255,106,61,.45))}
.kr .logo span{font-weight:800;font-size:19px;letter-spacing:.06em}
.kr .kroki-head{font:500 10.5px var(--mono);letter-spacing:.14em;color:var(--dim2);margin-bottom:14px}
.kr .kroki{display:grid;grid-template-columns:18px 1fr;column-gap:16px;flex:1}
.kr .krok{display:contents}
.kr .krok .kol{display:flex;flex-direction:column;align-items:center}
.kr .krok .kropa{width:18px;height:18px;border-radius:50%;display:grid;place-items:center;font:600 10px var(--mono);border:1px solid var(--line);color:var(--dim);background:transparent;flex-shrink:0}
.kr .krok.on .kropa{background:var(--acc);color:#0f0d0c;border-color:var(--acc)}
.kr .krok.done .kropa{color:var(--acc);border-color:var(--acc)}
.kr .krok .szyna{width:1px;flex:1;margin:4px 0;background:var(--line);min-height:36px}
.kr .krok.done .szyna{background:var(--acc)}
.kr .krok .tekst{cursor:pointer;padding-bottom:22px;opacity:.7}
.kr .krok.on .tekst,.kr .krok.done .tekst{opacity:1}
.kr .krok.dalej .tekst{cursor:default}
.kr .krok .tekst .l{font-weight:600;font-size:14.5px;line-height:18px;color:var(--dim)}
.kr .krok.on .tekst .l{color:var(--txt)} .kr .krok.done .tekst .l{color:var(--muted)}
.kr .krok .tekst .s{font-size:12px;color:var(--dim);margin-top:2px;line-height:1.35}
.kr .stopka{display:flex;flex-direction:column;gap:14px;margin-top:8px}
.kr .stopka .slsk{display:flex;align-items:center;gap:9px;font-size:12.5px;color:var(--dim)}
.kr .stopka .slsk .dot{width:7px;height:7px}
.kr .jez{display:flex;gap:2px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:3px;width:max-content}
.kr .jez button{border:0;cursor:pointer;padding:4px 10px;border-radius:6px;font:600 11px var(--mono);background:transparent;color:var(--dim)}
.kr .jez button.on{background:var(--acc);color:#0f0d0c}
.kr main{padding:52px 72px 40px;overflow:auto;display:flex;flex-direction:column;min-width:0;min-height:0;position:relative}
.kr .kicker{margin-bottom:12px;display:block}
.kr h1{margin:0;font-size:44px;font-weight:700;letter-spacing:-.02em;line-height:1.05}
.kr .sub{margin:12px 0 0;font-size:16px;color:var(--dim);line-height:1.5}
.kr .cta{background:var(--acc);color:#0f0d0c;border:0;border-radius:10px;padding:13px 22px;font-weight:800;font-size:14px;letter-spacing:.04em;cursor:pointer;display:flex;align-items:center;gap:8px;white-space:nowrap}
.kr .cta:hover{background:var(--acc-h)} .kr .cta:disabled{opacity:.5;cursor:default}
.kr .postep{font-size:13px;color:var(--dim);display:flex;align-items:center;gap:8px;min-height:18px;line-height:1.4}
.kr .postep.bad{color:var(--bad)} .kr .postep.warn{color:var(--warn)}
.kr .postep b{color:var(--txt)}
/* krok 1 */
.kr .s1{display:flex;flex-direction:column;gap:28px;max-width:760px}
.kr .wklej{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:6px;display:flex;flex-direction:column;gap:6px}
.kr .wklej:focus-within{border-color:var(--acc)}
.kr .wklej textarea{width:100%;background:transparent;border:0;color:var(--txt);font-size:17px;padding:16px 18px;resize:none;line-height:1.45;display:block}
.kr .wklej textarea::placeholder{color:var(--dim2)}
.kr .wklej .dol{display:flex;align-items:center;gap:12px;padding:6px 8px 8px 18px}
.kr .wklej .hint{font-size:12.5px;color:var(--dim2)}
.kr .wklej .cta{margin-left:auto}
.kr .albo{display:flex;align-items:center;gap:14px;color:var(--dim2);font-size:12.5px}
.kr .albo i{flex:1;height:1px;background:var(--line)}
.kr .karty2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.kr .drop{border:1px dashed var(--line3);border-radius:14px;padding:24px 22px;cursor:pointer;display:flex;flex-direction:column;gap:6px}
.kr .drop:hover,.kr .drop.over{border-color:var(--acc);background:var(--panel-ciemny)}
.kr .folder{border:1px solid var(--line);border-radius:14px;padding:24px 22px;cursor:pointer;display:flex;flex-direction:column;gap:6px;background:var(--panel-ciemny)}
.kr .folder:hover{border-color:var(--acc)}
.kr .karta-t{font-weight:600;font-size:15px}
.kr .karta-s{font-size:12.5px;color:var(--dim);line-height:1.45}
.kr .wybor-folderu{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;display:flex;flex-direction:column;gap:14px}
.kr .wybor-folderu .sc{font:500 12px var(--mono);color:var(--dim);word-break:break-all}
.kr .wybor-folderu .dwa{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.kr .wybor-folderu .dwa button{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;white-space:normal;padding:14px 16px}
.kr .wybor-folderu .dwa button small{font-size:11.5px;font-weight:500;opacity:.8;letter-spacing:0}
.kr .sciezka{display:flex;flex-direction:column;gap:8px}
.kr .sciezka summary{cursor:pointer;font-size:12.5px;color:var(--dim)}
.kr .sciezka .rzad{display:flex;gap:8px}
.kr .sciezka .pole{flex:1}
/* krok 2 i 5 — nagłówek z licznikami */
.kr .s2{display:flex;flex-direction:column;gap:28px;height:100%;min-height:0}
.kr .nag{display:flex;align-items:flex-end;gap:24px}
.kr .nag>div:first-child{flex:1;min-width:0}
.kr .liczniki{display:flex;gap:28px;padding-bottom:6px;flex-shrink:0}
.kr .licznik .n{font-size:34px;font-weight:700;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums}
.kr .licznik .n small{font-size:14px;color:var(--dim);margin-left:3px;font-weight:700}
.kr .licznik .e{font:500 10.5px var(--mono);letter-spacing:.1em;color:var(--dim);margin-top:6px}
.kr .kolumny{display:grid;grid-template-columns:1fr 1fr;gap:20px;flex:1;min-height:0}
.kr .kol-panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.kr .kol-panel .kh{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;font-weight:600;font-size:14px}
.kr .kol-panel .kl{overflow:auto;display:flex;flex-direction:column;min-height:0}
.kr .poz2{display:flex;align-items:center;gap:14px;padding:12px 20px;border-bottom:1px solid var(--line2)}
.kr .okl{position:relative;overflow:hidden;flex-shrink:0}
.kr .okl img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.kr .poz2 .okl{width:38px;height:38px}
.kr .poz2 .kto{flex:1;min-width:0}
.kr .poz2 .t{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kr .poz2 .a{font-size:12.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kr .poz2 .nota{font:500 11px var(--mono);white-space:nowrap}
.kr .poz2 .bar{height:2px;background:var(--line);border-radius:1px;margin-top:8px;overflow:hidden}
.kr .poz2 .bar i{display:block;height:100%;background:var(--acc);transition:width .3s}
.kr .akcje{display:flex;gap:6px;flex-shrink:0}
.kr .b-dl{background:var(--acc);color:#0f0d0c;border:0;border-radius:7px;padding:6px 12px;font-weight:700;font-size:12px;cursor:pointer;white-space:nowrap}
.kr .b-dl:hover{background:var(--acc-h)} .kr .b-dl:disabled{opacity:.5;cursor:default}
.kr .b-pick{background:transparent;color:var(--dim);border:1px solid var(--line);border-radius:7px;padding:6px 12px;font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap}
.kr .b-pick:hover{color:var(--txt);border-color:var(--line3)}
.kr .b-all{margin-left:auto;background:transparent;border:1px solid var(--acc);color:var(--acc);border-radius:8px;padding:6px 12px;font-weight:700;font-size:12px;cursor:pointer;white-space:nowrap}
.kr .b-all:hover{background:var(--acc);color:#0f0d0c} .kr .b-all:disabled{opacity:.5;cursor:default}
.kr .stopa{display:flex;align-items:center;gap:16px;flex-shrink:0}
.kr .stopa .info{font-size:13px;color:var(--dim);min-width:0}
.kr .stopa .info.warn{color:var(--warn)} .kr .stopa .info.bad{color:var(--bad)}
.kr .stopa .info b{color:var(--txt)}
.kr .stopa .cta{margin-left:auto}
.kr .pusto2{padding:22px 20px;color:var(--dim2);font-size:13px}
.kr .podnag{padding:10px 20px;font:500 10.5px var(--mono);letter-spacing:.1em;border-bottom:1px solid var(--line2);background:var(--bg)}
.kr .poz2 .a a{color:var(--dim2);text-decoration:none;border-bottom:1px dotted var(--line3)}
.kr .poz2 .a a:hover{color:var(--acc);border-color:var(--acc)}
.kr .uwaga-imp{font-size:12.5px;line-height:1.45;padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--panel)}
/* krok 3 */
.kr .s3{display:flex;flex-direction:column;gap:28px;max-width:760px;margin:auto 0}
.kr .nazwa{width:100%;background:transparent;border:0;border-bottom:2px solid var(--acc);color:var(--txt);font-size:40px;font-weight:600;letter-spacing:-.02em;padding:8px 0 14px;border-radius:0}
.kr .chipy{display:flex;gap:8px;flex-wrap:wrap}
.kr .chip{background:var(--panel);border:1px solid var(--line);color:var(--dim);border-radius:20px;padding:7px 14px;font-size:12.5px;cursor:pointer}
.kr .chip:hover{border-color:var(--acc);color:var(--txt)}
.kr .s3 .stopa{margin-top:8px}
/* krok 4 */
.kr .s4{display:flex;flex-direction:column;gap:36px;max-width:760px;margin:auto 0}
.kr .proc{display:flex;align-items:baseline;gap:12px;margin-bottom:14px}
.kr .proc .duzy{font-size:56px;font-weight:700;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.kr .proc .duzy span{font-size:24px;color:var(--dim)}
.kr .proc .idx{font:500 12px var(--mono);color:var(--dim);margin-left:auto}
.kr .biez{margin-top:14px;font-size:14px;color:var(--dim);display:flex;gap:10px;align-items:center;min-height:20px}
.kr .biez.bad{color:var(--bad)}
.kr .biez .spin{flex-shrink:0}
.kr .etapy{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.kr .etap{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 16px 14px;display:flex;flex-direction:column;gap:10px}
.kr .etap.run{border-color:var(--acc)}
.kr .etap .dot{background:var(--line)} .kr .etap.run .dot{background:var(--acc)} .kr .etap.done .dot{background:var(--ok)}
.kr .etap .l{font-weight:600;font-size:14px;color:var(--dim)}
.kr .etap.run .l,.kr .etap.done .l{color:var(--txt)}
.kr .etap .st{font:500 11px var(--mono);color:var(--dim)}
/* krok 5 */
.kr .s5{display:flex;flex-direction:column;gap:24px;height:100%;min-height:0}
.kr .narz{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.kr .narz .btn{padding:9px 14px}
.kr .narz .nota{font-size:12.5px;color:var(--dim2);margin-left:6px}
.kr .narz .postep{margin-left:auto;font-size:12.5px;text-align:right}
.kr .lista5{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:auto;flex:1;min-height:0}
.kr .poz5{display:grid;grid-template-columns:22px 40px 1fr auto auto;gap:16px;align-items:center;padding:13px 20px;border-bottom:1px solid var(--line2)}
.kr .poz5.czysty{opacity:.78}
.kr .poz5 .znak{font-weight:800;font-size:16px;text-align:center}
.kr .poz5 .okl{width:40px;height:40px}
.kr .poz5 .kto{min-width:0}
.kr .poz5 .t{font-weight:600;font-size:14.5px}
.kr .poz5 .a{font-size:12.5px;color:var(--dim);display:flex;gap:10px;align-items:center;margin-top:2px;flex-wrap:wrap}
.kr .poz5 .bpm{font:500 11px var(--mono)}
.kr .poz5 .cam{font:600 10.5px var(--mono);padding:1px 7px;border-radius:4px;color:#0f0d0c}
.kr .probl{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.kr .prob{display:flex;align-items:center;gap:7px;font-size:12px}
.kr .prob .tag{font:600 10px var(--mono);letter-spacing:.08em;padding:2px 6px;border-radius:4px;color:#0f0d0c;text-transform:uppercase;flex-shrink:0}
.kr .b-lepsza{background:transparent;color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:6px 12px;font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap}
.kr .b-lepsza:hover{border-color:var(--acc)} .kr .b-lepsza:disabled{opacity:.6;cursor:default}
.kr .b-usun{background:transparent;color:var(--dim2);border:0;padding:6px 8px;font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap}
.kr .b-usun:hover{color:var(--bad)}
.kr .lepsze{margin-top:8px;font-size:12px;display:flex;flex-direction:column;gap:2px;color:var(--dim)}
.kr .lepsze .w{display:flex;gap:10px;align-items:center;padding:3px 0}
.kr .lepsze .w .f{color:var(--acc);min-width:52px;font:500 11px var(--mono)}
.kr .lepsze .w .m{min-width:70px;font:500 11px var(--mono)}
.kr .lepsze .w .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt)}
.kr .fixmsg{margin-top:4px;font-size:11.5px;color:var(--warn)} .kr .fixmsg.bad{color:var(--bad)}
.kr .rozdz{padding:8px 20px;font-size:12px;color:var(--dim);border-bottom:1px solid var(--line2)}
.kr .uwaga5{margin:12px 20px 4px;}
.kr .s5 .stopa .nota{font-size:12.5px;color:var(--dim2);min-width:0}
.kr .s5 .stopa .glow{margin-left:auto;display:flex;align-items:center;gap:10px}
.kr .s5 .stopa .glow>span:first-child{font-size:12px}
/* Nakładka końcowa — klasa .gotowe, NIE .done.
   Kroki paska i kafle etapów mają klasy krok.done / etap.done. Reguła
   .kr .done łapała je również (ta sama waga, a stała później w arkuszu),
   więc ukończony krok dostawał position:absolute tej nakładki, rozlewał się
   na całą treść i przechwytywał kliknięcia — nie dało się przejść dalej
   z kroku 3. Nie wracaj do ogólnej nazwy. */
.kr .gotowe{position:absolute;inset:44px 0 0 264px;background:rgba(15,13,12,.92);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);z-index:5;animation:wjazd .2s ease-out}
.kr .gotowe .box{text-align:center;display:flex;flex-direction:column;align-items:center;gap:18px;max-width:520px;padding:0 24px}
.kr .gotowe img{width:120px;height:120px;object-fit:contain;filter:drop-shadow(0 0 40px rgba(255,106,61,.5))}
.kr .gotowe h2{margin:0;font-size:36px;font-weight:700;letter-spacing:-.02em}
.kr .gotowe p{margin:0;font-size:15px;color:var(--dim);line-height:1.5}
.kr .gotowe button{margin-top:8px;background:transparent;border:1px solid var(--line);color:var(--dim);border-radius:9px;padding:9px 16px;font-weight:600;font-size:13px;cursor:pointer}
.kr .gotowe button:hover{border-color:var(--acc);color:var(--txt)}
/* ---- 2a: wybór trybu ---- */
.tryb{height:100vh;display:flex;flex-direction:column;overflow:hidden;position:relative;background:var(--bg)}
.tryb .poswiata{position:absolute;left:50%;top:60%;width:900px;height:900px;transform:translate(-50%,-50%);border-radius:50%;background:radial-gradient(circle,rgba(255,106,61,.10),transparent 60%);pointer-events:none}
.tryb .srodek{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px;padding:40px;position:relative;overflow:auto;min-height:0}
.tryb .glowa{display:flex;flex-direction:column;align-items:center;gap:18px;text-align:center;flex-shrink:0}
.tryb .glowa img{width:300px;max-width:60vw;height:auto;margin-bottom:-6px;filter:drop-shadow(0 0 30px rgba(255,106,61,.3))}
.tryb h1{margin:0;font-size:44px;font-weight:700;letter-spacing:-.025em;line-height:1}
.tryb .glowa .p{font-size:16px;color:var(--dim)}
.tryb .karty{display:grid;grid-template-columns:1fr 1fr;gap:20px;width:860px;max-width:100%;flex-shrink:0}
.tryb .karta{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:34px 32px;display:flex;flex-direction:column;gap:14px;cursor:pointer;transition:transform .15s,border-color .15s;user-select:none}
.tryb .karta.auto{border-color:var(--acc);box-shadow:0 0 60px rgba(255,106,61,.18)}
.tryb .karta.auto:hover{transform:translateY(-2px)}
.tryb .karta.reczny:hover{border-color:var(--dim)}
.tryb .karta .ikona{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;font-size:16px}
.tryb .karta.auto .ikona{background:var(--acc);color:#0f0d0c}
.tryb .karta.reczny .ikona{background:var(--panel2);border:1px solid var(--line);color:var(--txt)}
.tryb .karta .k{font:600 11px var(--mono);letter-spacing:.14em;margin-top:10px}
.tryb .karta.auto .k{color:var(--acc)} .tryb .karta.reczny .k{color:var(--dim)}
.tryb .karta .t{font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.15}
.tryb .karta .o{font-size:14px;color:var(--dim);line-height:1.5}
.tryb .karta .cta{margin-top:auto;padding-top:14px;font-weight:700;font-size:13px;letter-spacing:.04em}
.tryb .karta.auto .cta{color:var(--acc)} .tryb .karta.reczny .cta{color:var(--dim)}
.tryb .stopka{display:flex;gap:28px;font-size:12.5px;color:var(--dim);align-items:center;flex-wrap:wrap;justify-content:center;flex-shrink:0}
.tryb .stopka .poz{display:flex;align-items:center;gap:8px;white-space:nowrap}
.tryb .stopka .dot{width:7px;height:7px}
.tryb .stopka .mono{font:500 11px var(--mono)}
.tryb .niepytaj{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;color:var(--dim2)}
.tryb .niepytaj:hover{color:var(--dim)}
.tryb .niepytaj .box{width:14px;height:14px;border:1px solid var(--line3);border-radius:4px;display:grid;place-items:center;font-size:10px;color:#0f0d0c;flex-shrink:0}
.tryb .niepytaj.on .box{background:var(--acc);border-color:var(--acc)}
/* ---- 2b: arkusz wyboru wyniku ---- */
.ark2b{display:flex;flex-direction:column;gap:22px;min-width:0}
.ark2b .glowa{display:flex;align-items:flex-start;gap:20px}
.ark2b .okl{width:64px;height:64px;border-radius:10px;flex-shrink:0;position:relative;overflow:hidden}
.ark2b .okl img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.ark2b .glowa .kto{flex:1;min-width:0}
.ark2b .kicker{margin-bottom:8px;display:block}
.ark2b .t{font-size:28px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.ark2b .a{font-size:15px;color:var(--dim);margin-top:4px}
.ark2b .a b{font:500 12px var(--mono);color:var(--txt)}
.ark2b .x{background:transparent;border:1px solid var(--line);color:var(--dim);border-radius:8px;width:34px;height:34px;cursor:pointer;font-size:14px;flex-shrink:0}
.ark2b .x:hover{color:var(--txt);border-color:var(--line3)}
.ark2b .naglowki,.ark2b .w{display:grid;grid-template-columns:1.6fr 1fr .7fr .6fr .8fr auto;gap:14px;align-items:center}
.ark2b .naglowki{padding:0 16px;font:500 10.5px var(--mono);letter-spacing:.1em;color:var(--dim2)}
.ark2b .wyniki{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:12px;overflow:hidden;max-height:52vh;overflow-y:auto}
.ark2b .w{padding:14px 16px;border-bottom:1px solid var(--line2);border-left:2px solid var(--line2);min-width:0}
.ark2b .w:last-child{border-bottom:0}
.ark2b .w.best{background:rgba(255,106,61,.06);border-left-color:var(--acc)}
.ark2b .w .kto{min-width:0}
.ark2b .w .f{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ark2b .w .u{font-size:12px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ark2b .w .m{font:500 12px var(--mono);color:var(--dim);white-space:nowrap}
.ark2b .b-best{background:var(--acc);color:#0f0d0c;border:0;border-radius:8px;padding:8px 14px;font-weight:800;font-size:12px;letter-spacing:.04em;cursor:pointer;white-space:nowrap}
.ark2b .b-best:hover{background:var(--acc-h)}
.ark2b .b-inny{background:transparent;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap}
.ark2b .b-inny:hover{color:var(--txt);border-color:var(--line3)}
.ark2b button:disabled{opacity:.6;cursor:default}
.ark2b .stan{padding:18px 16px;font-size:13px;color:var(--dim);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ark2b .stan.bad{color:var(--bad)}
.ark2b .stopa{display:flex;align-items:center;gap:14px;font-size:12.5px;color:var(--dim);flex-wrap:wrap}
.ark2b .stopa .kr2{display:flex;align-items:center;gap:7px}
.ark2b .stopa .dot{width:6px;height:6px;background:var(--acc)}
.ark2b .stopa .mono{margin-left:auto;font:500 11px var(--mono)}
.ark2b .stopa .mono.ok{color:var(--ok)}
`;
  function wstrzyknijCSS(){
    if($('#kreator-css')) return;
    const st = document.createElement('style'); st.id = 'kreator-css'; st.textContent = CSS;
    document.head.appendChild(st);
  }

  /* ---------- drobiazgi wspólne ---------- */
  const spin = () => '<span class="spin"></span>';
  // okładka: wzór z projektu jako tło, prawdziwa grafika z /api/cover, gdy jest
  const okladka = (file, kl) => file
    ? `<span class="okl okladka ${kl||''}"><img alt="" src="/api/cover?file=${encodeURIComponent(S.nazwaPliku(file))}"></span>`
    : `<span class="okl okladka ${kl||''}"></span>`;
  function podepnijOkladki(root){ $$('.okl img', root).forEach(img => { img.onerror = () => img.remove(); }); }
  const czekaj = ms => new Promise(r => setTimeout(r, ms));
  function stanSlsk(d){
    const t = T();
    const lvl = d && d.level;
    const kl = {green:'ok swieci', amber:'warn', red:'bad'}[lvl] || '';
    let txt;
    if(!d) txt = S.jezyk.get() === 'pl' ? 'sprawdzam Soulseek…' : 'checking Soulseek…';
    else if(!lvl) txt = t.slskOff;
    else if(lvl === 'green') txt = t.slsk;
    else if(lvl === 'amber') txt = S.jezyk.get() === 'pl' ? (d.label || t.slskAmber) : t.slskAmber;
    else txt = S.jezyk.get() === 'pl' ? (d.label || t.slskRed) : t.slskRed;
    return {kl, txt, hint: d && d.hint || ''};
  }

  /* ============================================================
     2b — arkusz „Wybór wyniku Soulseek"
     S.wybierzWynik({artist,title,duration,file?}, {poZleceniu(queued, kandydat)})
     → Promise<{queued, kandydat} | null>
     ============================================================ */
  let ARK = null;   // {resolve, obserwator}
  function zamknijWybor(wynik){
    if(ARK){ const a = ARK; ARK = null; a.obs && a.obs.disconnect(); a.resolve(wynik || null); }
    S.zamknijArkusz();
  }
  function wybierzWynik(utwor, opts={}){
    wstrzyknijCSS();
    const t = T().sheet;
    utwor = utwor || {};
    const {artist='', title='', duration=null} = utwor;
    const naglowek = (kicker) => `
      <div class="glowa">
        ${okladka(utwor.file)}
        <div class="kto">
          <span class="kicker">${esc(kicker)}</span>
          <div class="t">${esc(title || S.nazwaPliku(utwor.file) || '—')}</div>
          <div class="a">${esc(artist)}${duration ? ` · ${esc(t.inList)} <b>${fmtTime(duration)}</b>` : ''}</div>
        </div>
        <button class="x" data-zamknij title="Esc">✕</button>
      </div>`;
    const body = S.arkusz(`<div class="ark2b">${naglowek(t.kicker)}
      <div class="wyniki"><div class="stan">${spin()}${esc(t.searching)}</div></div></div>`);
    podepnijOkladki(body);
    if(ARK) { ARK.obs && ARK.obs.disconnect(); ARK.resolve(null); }
    const p = new Promise(resolve => { ARK = {resolve, obs:null}; });
    const moj = ARK;
    // zamknięcie przez Esc / kliknięcie w tło (obsługuje powłoka) → null
    const obs = new MutationObserver(() => { if($('#arkusz').classList.contains('hide')) zamknijWybor(null); });
    obs.observe($('#arkusz'), {attributes:true, attributeFilter:['class']});
    ARK.obs = obs;
    body.querySelector('[data-zamknij]').onclick = () => zamknijWybor(null);

    (async () => {
      let d;
      try{ d = await api('/api/search', {method:'POST', body:{artist, title, duration}, cicho:true}); }
      catch(e){
        if(ARK !== moj) return;
        const w = body.querySelector('.wyniki'); if(w) w.innerHTML = `<div class="stan bad">✗ ${esc(e.message)}</div>`;
        return;
      }
      if(ARK !== moj) return;                              // zamknięto (albo otwarto inny) w trakcie szukania
      const kand = d.candidates || [];
      const kicker = `${t.kicker} · ${d.count} ${lm(d.count, t.results)}`;
      const fmtKolor = c => c.lossless ? K.ok : (c.format === 'MP3' ? '#b0a69c' : K.warn);
      const czasKolor = c => c.duration_delta == null ? K.dim : (c.duration_ok ? K.ok : K.warn);
      const rzad = (c, i) => `
        <div class="w ${i===0?'best':''}" data-i="${i}">
          <div class="kto"><div class="f" title="${esc(c.folder||'')}/${esc(c.filename)}">${esc(c.filename)}</div><div class="u">${esc(c.user)}</div></div>
          <span class="m" style="color:${fmtKolor(c)}">${esc(c.format)}${c.bitrate ? ' '+c.bitrate : ''}</span>
          <span class="m">${fmtMB(c.size) || (c.size_mb+' MB')}</span>
          <span class="m" style="color:${czasKolor(c)}">${c.length_s ? fmtTime(c.length_s) : '—'}</span>
          <span class="m" style="color:${c.free_slot ? K.ok : K.dim}" title="${c.queue ? esc(String(c.queue)) + ' w kolejce' : ''}">${c.speed ? esc(c.speed) + ' · ' : ''}${c.free_slot ? esc(t.free) : esc(t.busy)}</span>
          <button class="${i===0?'b-best':'b-inny'}" data-pobierz="${i}">${i===0 ? esc(t.dl) : esc(t.dlOther)}</button>
        </div>`;
      body.innerHTML = `<div class="ark2b">${naglowek(kicker)}
        ${kand.length ? `<div class="naglowki">${t.cols.map(c=>`<span>${esc(c)}</span>`).join('')}</div>` : ''}
        <div class="wyniki">${kand.length ? kand.map(rzad).join('')
          : `<div class="stan">${esc(t.none)} <button class="btn mini" data-zyczenie>${esc(t.wish)}</button></div>`}</div>
        <div class="stopa">
          <span class="kr2"><span class="dot"></span>${kand.length ? esc(t.best) : esc(fmt(t.searchedAs, {q:d.searched_as || artist}))}</span>
          <span class="mono" data-stopa>${esc(t.after)}</span>
        </div></div>`;
      podepnijOkladki(body);
      body.querySelector('[data-zamknij]').onclick = () => zamknijWybor(null);
      const zyc = body.querySelector('[data-zyczenie]');
      if(zyc) zyc.onclick = async () => {
        zyc.disabled = true;
        try{ await api('/api/wishlist', {method:'POST', body:{artist, title, duration}}); zyc.textContent = t.wished; }
        catch(e){ zyc.disabled = false; }
      };
      $$('[data-pobierz]', body).forEach(b => b.onclick = async () => {
        const c = kand[+b.dataset.pobierz];
        const stopa = body.querySelector('[data-stopa]');
        b.disabled = true; b.textContent = '…';
        try{
          const j = await api('/api/download', {method:'POST', body:{artist, title, path:c.path, user:c.user, size:c.size}, cicho:true});
          b.textContent = T().inQueue;
          if(stopa){ stopa.textContent = fmt(t.queued, {file:j.queued, user:c.user}); stopa.classList.add('ok'); }
          toast(fmt(t.queued, {file:j.queued, user:c.user}), 'ok');
          if(typeof opts.poZleceniu === 'function') opts.poZleceniu(j.queued, c);
          await czekaj(700);
          zamknijWybor({queued:j.queued, kandydat:c});
        }catch(e){
          b.textContent = '✗'; b.disabled = false;
          if(stopa){ stopa.textContent = '✗ '+e.message; stopa.style.color = K.bad; }
        }
      });
    })();
    return p;
  }
  S.wybierzWynik = wybierzWynik;

  /* ============================================================
     2a — wybór trybu
     ============================================================ */
  S.ekran('tryb', {
    tytul:'selekta', pelny:true,
    render(host){
      wstrzyknijCSS();
      host.innerHTML = `<div class="tryb">
        <div class="tb-pelny"><span class="kropka"></span><span class="kropka"></span><span class="kropka"></span></div>
        <div class="poswiata"></div>
        <div class="srodek">
          <div class="glowa">
            <img src="/static/assets/selekta-logo.png" alt="Selekta DJ">
            <h1>Jak chcesz dziś pracować?</h1>
            <div class="p">przygotowanie setu</div>
          </div>
          <div class="karty">
            <div class="karta auto" data-tryb="auto">
              <span class="ikona">▶</span>
              <div class="k">AUTOMATYCZNY</div>
              <div class="t">Wklejasz playlistę, klikasz dalej, na końcu grasz.</div>
              <div class="o">Wszystko robi się samo — pobieranie, analiza, poprawki, eksport do rekordboxa.</div>
              <div class="cta">ZACZNIJ →</div>
            </div>
            <div class="karta reczny" data-tryb="reczny">
              <span class="ikona">⚙</span>
              <div class="k">RĘCZNY</div>
              <div class="t">Pełna kontrola nad biblioteką.</div>
              <div class="o">Biblioteka, analiza, zdrowie, kolejność setu, eksport i ustawienia — każde osobno.</div>
              <div class="cta">OTWÓRZ →</div>
            </div>
          </div>
          <div class="stopka">
            <span class="poz"><span class="dot" data-slsk></span><span data-slsk-txt>sprawdzam Soulseek…</span></span>
            <span class="mono" data-folder>…</span>
            <span class="poz"><span class="dot" data-rb></span><span data-rb-txt>rekordbox</span></span>
            <span class="niepytaj" data-niepytaj title="Zapamiętaj wybór — zmienisz go w Ustawieniach"><span class="box"></span>nie pytaj więcej</span>
          </div>
        </div></div>`;
      const nie = host.querySelector('[data-niepytaj]');
      nie.onclick = () => { nie.classList.toggle('on'); nie.querySelector('.box').textContent = nie.classList.contains('on') ? '✓' : ''; };
      on(host, 'click', '.karta', (e, el) => {
        const tryb = el.dataset.tryb;
        if(nie.classList.contains('on')) S.pref.set('startTryb', tryb);
        S.pokaz(tryb === 'auto' ? 'kreator' : 'biblioteka');
      });
      document.addEventListener('selekta:status', e => { if(!host.classList.contains('hide')) rysujSlsk(host, e.detail); });
    },
    async load(host){
      const nie = host.querySelector('[data-niepytaj]');
      nie.classList.remove('on'); nie.querySelector('.box').textContent = '';
      rysujSlsk(host, await S.status());
      const fold = host.querySelector('[data-folder]');
      const rbDot = host.querySelector('[data-rb]'), rbTxt = host.querySelector('[data-rb-txt]');
      // folder od razu z konfiguracji, liczby dopiero gdy /api/tracks odpowie
      try{
        const c = await api('/api/config', {cicho:true});
        const f = c.folder || '';
        fold.textContent = skrocDom(f);
        fold.title = f;
        const rb = c.rekordbox || {};
        rbDot.className = 'dot ' + (rb.installed ? (rb.running ? 'warn' : 'ok') : '');
        rbTxt.textContent = rb.installed ? (rb.running ? 'rekordbox działa — zamknij przed eksportem' : 'rekordbox') : 'rekordbox nie znaleziony';
        rbTxt.title = rb.linked ? 'podpięta biblioteka: '+rb.linked : '';
      }catch(e){ fold.textContent = '—'; }
      try{
        const rs = await api('/api/rekordbox/stan', {cicho:true});
        if(rs.utworow && !rbTxt.textContent.includes('nie znaleziono')) rbTxt.textContent += ` · ${utworow(rs.utworow)} z pracą`;
      }catch(e){}
      try{
        await S.tracks();
        const m = S.stan.tracksMeta || {};
        if(m.folder) fold.textContent = `${skrocDom(m.folder)} · ${fmtLicz(m.count)} ${lm(m.count, ['plik','pliki','plików'])} · ${fmtMB((m.total_mb||0)*1e6)}`;
      }catch(e){}
    },
  });
  const skrocDom = p => String(p||'').replace(/^\/Users\/[^/]+/, '~');
  function rysujSlsk(host, d){
    const s = stanSlsk(d);
    const dot = host.querySelector('[data-slsk]'), tx = host.querySelector('[data-slsk-txt]');
    if(dot){ dot.className = 'dot '+s.kl; tx.textContent = s.txt; tx.title = s.hint; }
  }

  /* ============================================================
     KREATOR — 5 kroków
     ============================================================ */
  const WIZ = {krok:1, maks:1, tekst:'', imp:null, nazwa:'', pliki:[], pool:[], have:[], prop:[], folder:'', review:null,
               fixMsg:{}, wMiejscu:false, done:false, eksport:null, postep:null, analizaTrwa:false, poll:null, host:null,
               sugestie:[], narz:{fixTrwa:false, wymTrwa:false, przerwij:false, prog:'', progKl:''}};
  const HOST = () => WIZ.host;
  const MAIN = () => WIZ.host && WIZ.host.querySelector('main');

  function reset(){
    Object.assign(WIZ, {krok:1, maks:1, tekst:'', imp:null, nazwa:'', pliki:[], pool:[], have:[], prop:[], folder:'', review:null,
                        fixMsg:{}, wMiejscu:false, done:false, eksport:null, postep:null, analizaTrwa:false, sugestie:[],
                        narz:{fixTrwa:false, wymTrwa:false, przerwij:false, prog:'', progKl:''}});
  }
  function idz(n){
    if(WIZ.analizaTrwa && n !== 4) return;
    if(WIZ.wMiejscu && (n === 2 || n === 3)) return;
    WIZ.krok = n; WIZ.maks = Math.max(WIZ.maks, n); WIZ.done = false;
    rysujKroki(); rysujKrok();
  }

  S.ekran('kreator', {
    tytul: () => T().windowTitle, pelny:true,
    render(host){
      wstrzyknijCSS();
      WIZ.host = host;
      host.innerHTML = `<div class="kr">
        <div class="tb-pelny"><span class="kropka"></span><span class="kropka"></span><span class="kropka"></span>
          <span class="tyt" data-tytul></span>
          <span class="prawy"><button data-reczny title="Biblioteka i narzędzia — każde osobno"></button></span></div>
        <aside>
          <div class="logo" data-logo><img src="/static/assets/selekta-mark.png" alt=""><span>selekta</span></div>
          <div class="kroki-head" data-kroki-head></div>
          <div class="kroki" data-kroki></div>
          <div class="stopka">
            <div class="slsk"><span class="dot" data-slsk></span><span data-slsk-txt></span></div>
            <div class="jez"><button data-jezyk="pl">PL</button><button data-jezyk="en">EN</button></div>
          </div>
        </aside>
        <main data-main></main>
      </div>`;
      host.querySelector('[data-reczny]').onclick = () => S.pokaz('biblioteka');
      host.querySelector('[data-logo]').onclick = () => S.pokaz('tryb');
      on(host, 'click', '[data-jezyk]', (e, el) => S.jezyk.set(el.dataset.jezyk));
      on(host, 'click', '[data-krok]', (e, el) => { const n = +el.dataset.krok; if(n <= WIZ.maks) idz(n); });
      document.addEventListener('selekta:jezyk', () => { rysujRamy(); rysujKroki(); rysujKrok(); });
      document.addEventListener('selekta:status', e => rysujSlskKr(e.detail));
      rysujRamy(); rysujKroki();
    },
    async load(host, arg){
      if(arg && arg.nowy) { reset(); rysujKroki(); }
      rysujRamy(); rysujKrok();
      rysujSlskKr(await S.status());
      startPoll();
    },
  });

  function rysujRamy(){
    const h = HOST(); if(!h) return;
    const t = T(), j = S.jezyk.get();
    h.querySelector('[data-tytul]').textContent = t.windowTitle;
    h.querySelector('[data-reczny]').textContent = t.manual;
    h.querySelector('[data-kroki-head]').textContent = t.stepsHead;
    $$('[data-jezyk]', h).forEach(b => b.classList.toggle('on', b.dataset.jezyk === j));
    rysujSlskKr(S.stan.status);
  }
  function rysujSlskKr(d){
    const h = HOST(); if(!h) return;
    const s = stanSlsk(d);
    const dot = h.querySelector('[data-slsk]'), tx = h.querySelector('[data-slsk-txt]');
    dot.className = 'dot '+s.kl; tx.textContent = s.txt; tx.title = s.hint;
  }
  function rysujKroki(){
    const h = HOST(); if(!h) return;
    const t = T(), biez = WIZ.krok;
    h.querySelector('[data-kroki]').innerHTML = t.steps.map(([label, sub], i) => {
      const n = i+1, done = n < biez, cur = n === biez;
      const kl = cur ? 'on' : (done ? 'done' : (n <= WIZ.maks ? '' : 'dalej'));
      return `<div class="krok ${kl}">
        <div class="kol"><span class="kropa">${done ? '✓' : n}</span>${n < 5 ? '<span class="szyna"></span>' : ''}</div>
        <div class="tekst" data-krok="${n}"><div class="l">${esc(label)}</div><div class="s">${esc(sub)}</div></div>
      </div>`;
    }).join('');
  }
  function rysujKrok(){
    const m = MAIN(); if(!m) return;
    m.scrollTop = 0;
    if(WIZ.krok === 1) krok1(m);
    else if(WIZ.krok === 2) krok2(m);
    else if(WIZ.krok === 3) krok3(m);
    else if(WIZ.krok === 4) krok4(m);
    else if(WIZ.krok === 5) krok5(m);
    rysujDone();
  }
  const naglowekKroku = (kicker, tytul, sub) => `<div><span class="kicker">${esc(kicker)}</span><h1>${esc(tytul)}</h1><p class="sub">${esc(sub)}</p></div>`;
  function pokazPostep(el, html, kl){ if(!el) return; el.className = 'postep '+(kl||''); el.innerHTML = html; }

  /* ---------- 1. wklej playlistę ---------- */
  const PLIKI_PLAYLIST = '.m3u,.m3u8,.pls,.xml,.nml,.csv,.txt';

  function poImporcie(d, nazwa){
    WIZ.imp = d; WIZ.have = []; WIZ.pool = []; WIZ.prop = []; WIZ.review = null; WIZ.pliki = []; WIZ.wMiejscu = false; WIZ.fixMsg = {};
    WIZ.nazwa = nazwa || WIZ.nazwa || '';
    WIZ.sugestie = sugestieNazw(d, nazwa);
    if(!WIZ.nazwa) WIZ.nazwa = WIZ.sugestie[0];
    WIZ.maks = 2;
    idz(2);
  }
  function sugestieNazw(d, nazwa){
    const pl = S.jezyk.get() === 'pl';
    const dz = new Date();
    const data = dz.toLocaleDateString(pl ? 'pl-PL' : 'en-GB', {day:'numeric', month:'short'});
    const dzien = dz.toLocaleDateString(pl ? 'pl-PL' : 'en-GB', {weekday:'long'});
    const zrodlo = String((d && d.origin) || '').split(':')[0];
    const ladny = {spotify:'Spotify', 'apple-music':'Apple Music', youtube:'YouTube', tidal:'Tidal', soundcloud:'SoundCloud', '1001tracklists':'1001Tracklists', plik:pl?'z pliku':'from file', dysk:pl?'z dysku':'from disk', tekst:pl?'lista':'list'}[zrodlo.toLowerCase()] || zrodlo;
    const s = [];
    if(nazwa) s.push(nazwa);
    if(ladny) s.push(`${ladny} · ${data}`);
    s.push(`${dzien.charAt(0).toUpperCase()+dzien.slice(1)} · ${data}`);
    s.push(`set ${dz.toLocaleDateString(pl ? 'pl-PL' : 'en-GB')}`);
    return [...new Set(s)];
  }

  // Pełny XML rekordboxa ma wiele playlist — użytkownik wybiera jedną
  function pokazWyborPlaylisty(prog, d, wybierz){
    prog.className = 'postep';
    prog.innerHTML = `${esc(d.komunikat || '')}<div class="chipy" style="margin-top:10px">${(d.wybor_playlisty||[]).map((p, i) =>
      `<button class="chip" data-pl="${i}">${esc(p.name)} · ${p.count}</button>`).join('')}</div>`;
    prog.querySelectorAll('[data-pl]').forEach(b => b.onclick = () => wybierz(d.wybor_playlisty[+b.dataset.pl].name));
  }
  async function wgrajPlik(f, prog, playlista){
    if(!f) return;
    const t = T();
    pokazPostep(prog, spin()+esc(fmt(t.reading, {name:f.name})));
    const fd = new FormData(); fd.append('file', f);
    try{
      const url = '/api/playlist/upload' + (playlista ? '?playlista='+encodeURIComponent(playlista) : '');
      const d = await api(url, {method:'POST', formData:fd, cicho:true});
      if(d.wybor_playlisty){ pokazWyborPlaylisty(prog, d, nazwa => wgrajPlik(f, prog, nazwa)); return; }
      const zPliku = (d.auto||[]).filter(x => x.from_file).length;
      pokazPostep(prog, esc(fmt(t.loaded, {n:d.counts.total})) + (zPliku ? esc(fmt(t.fromFile, {n:zPliku})) : ''));
      poImporcie(d, d.name);
    }catch(e){ pokazPostep(prog, '✗ '+esc(e.message), 'bad'); }
  }
  async function wczytajZeSciezki(sciezka, prog, playlista){
    pokazPostep(prog, spin()+esc(T().readingDisk));
    try{
      const d = await api('/api/playlist/local', {method:'POST', body:{path:sciezka, playlista:playlista||''}, cicho:true});
      if(d.wybor_playlisty){ pokazWyborPlaylisty(prog, d, nazwa => wczytajZeSciezki(sciezka, prog, nazwa)); return; }
      poImporcie(d, d.name);
    }catch(e){ pokazPostep(prog, '✗ '+esc(e.message), 'bad'); }
  }
  // „Posprzątaj": analizujemy i naprawiamy pliki TAM, GDZIE LEŻĄ — bez kopii
  async function posprzataj(sciezka, nazwa, prog){
    pokazPostep(prog, spin()+esc(T().readingDisk));
    let pliki = [];
    try{
      const d = await api('/api/playlist/local', {method:'POST', body:{path:sciezka}, cicho:true});
      pliki = (d.auto||[]).map(x => x.file).filter(Boolean);
      if(!pliki.length) throw new Error(S.jezyk.get()==='pl' ? 'nie znalazłem w tym folderze plików audio' : 'no audio files found in this folder');
    }catch(e){ pokazPostep(prog, '✗ '+esc(e.message), 'bad'); return; }
    WIZ.nazwa = nazwa; WIZ.pliki = pliki; WIZ.folder = sciezka; WIZ.wMiejscu = true;
    WIZ.imp = null; WIZ.have = []; WIZ.pool = []; WIZ.prop = []; WIZ.review = null; WIZ.fixMsg = {};
    WIZ.maks = 4; idz(4);
  }
  function pokazWyborFolderu(host, sciezka, nazwa){
    const t = T();
    const box = host.querySelector('[data-folder-wybor]');
    box.innerHTML = `<div class="wybor-folderu">
      <div><div class="karta-t">📁 ${esc(nazwa)}</div><div class="sc">${esc(sciezka)}</div></div>
      <div class="dwa">
        <button class="btn acc duzy" data-sprzataj>${esc(t.tidy)}<small>${esc(t.tidySub)}</small></button>
        <button class="btn obrys" data-set>${esc(t.makeSet)}<small>${esc(t.makeSetSub)}</small></button>
      </div>
      <div class="postep" data-folder-prog></div></div>`;
    const prog = box.querySelector('[data-folder-prog]');
    box.querySelector('[data-sprzataj]').onclick = () => posprzataj(sciezka, nazwa, prog);
    box.querySelector('[data-set]').onclick = () => wczytajZeSciezki(sciezka, prog);
    box.scrollIntoView({block:'nearest', behavior:'smooth'});
  }

  function krok1(m){
    const t = T();
    m.innerHTML = `<div class="s1">
      ${naglowekKroku(t.s1kicker, t.s1title, t.s1sub)}
      <div class="wklej">
        <textarea rows="3" placeholder="https://open.spotify.com/playlist/…" data-tekst>${esc(WIZ.tekst)}</textarea>
        <div class="dol"><span class="hint">${esc(t.s1hint)}</span>
          <button class="cta" data-szukaj>${esc(t.s1cta)} <span style="font-size:16px">→</span></button></div>
      </div>
      <div class="postep" data-prog></div>
      <div class="albo"><i></i>${esc(t.s1or)}<i></i></div>
      <div class="karty2">
        <div class="drop" data-drop>
          <div class="karta-t">${esc(t.s1drop)}</div>
          <div class="karta-s">M3U · rekordbox XML · Traktor NML · Serato CSV</div>
          <input type="file" accept="${PLIKI_PLAYLIST}" class="hide" data-plik>
        </div>
        <div class="folder" data-folder>
          <div class="karta-t">${esc(t.s1folder)}</div>
          <div class="karta-s">${esc(t.s1folderSub)}</div>
        </div>
      </div>
      <div data-folder-wybor></div>
      <details class="sciezka" data-sciezka>
        <summary>${esc(t.pathManual)}</summary>
        <div class="rzad"><input class="pole" placeholder="${esc(t.pathPh)}" data-path><button class="btn" data-path-go>${esc(t.load)}</button></div>
        <div class="karta-s">${esc(t.pathNote)}</div>
      </details>
    </div>`;
    const root = m.firstElementChild;
    const prog = m.querySelector('[data-prog]');
    const ta = m.querySelector('[data-tekst]');
    const szukaj = async () => {
      const txt = ta.value.trim();
      if(!txt){ pokazPostep(prog, esc(t.emptyPaste), 'warn'); return; }
      WIZ.tekst = txt;
      const b = m.querySelector('[data-szukaj]'); b.disabled = true;
      pokazPostep(prog, spin()+esc(t.checking));
      try{
        const d = await api('/api/import', {method:'POST', body:{text:txt}, cicho:true});
        poImporcie(d);
      }catch(e){ pokazPostep(prog, '✗ '+esc(e.message), 'bad'); b.disabled = false; }
    };
    m.querySelector('[data-szukaj]').onclick = szukaj;
    ta.addEventListener('keydown', e => { if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); szukaj(); } });
    ta.addEventListener('input', () => { WIZ.tekst = ta.value; });
    setTimeout(() => ta.focus(), 50);

    const drop = m.querySelector('[data-drop]'), input = m.querySelector('[data-plik]');
    drop.onclick = () => input.click();
    input.onchange = () => wgrajPlik(input.files[0], prog);
    ['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => { const f = e.dataTransfer.files && e.dataTransfer.files[0]; if(f) wgrajPlik(f, prog); });
    // upuszczenie pliku gdziekolwiek na ekranie kroku 1 też działa
    root.addEventListener('dragover', e => e.preventDefault());
    root.addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer.files && e.dataTransfer.files[0]; if(f && !drop.contains(e.target)) wgrajPlik(f, prog); });

    m.querySelector('[data-folder]').onclick = async () => {
      pokazPostep(prog, spin()+esc(t.pickerOpen));
      try{
        const j = await api('/api/pick', {method:'POST', body:{what:'folder', prompt:'Wskaż folder z muzyką'}, cicho:true});
        pokazPostep(prog, '');
        if(j.cancelled) return;
        pokazWyborFolderu(m, j.path, j.name);
      }catch(e){
        pokazPostep(prog, '✗ '+esc(e.message), 'bad');
        const det = m.querySelector('[data-sciezka]'); det.open = true; det.querySelector('[data-path]').focus();
      }
    };
    const pathGo = () => { const v = m.querySelector('[data-path]').value.trim(); if(v) wczytajZeSciezki(v, prog); };
    m.querySelector('[data-path-go]').onclick = pathGo;
    m.querySelector('[data-path]').addEventListener('keydown', e => { if(e.key === 'Enter') pathGo(); });
  }

  /* ---------- 2. masz / do ściągnięcia ---------- */
  const ST_KOLOR = {wait:K.dim, searching:K.info, queued:K.warn, downloading:K.acc, done:K.ok, failed:K.bad};

  function krok2(m){
    const t = T(), d = WIZ.imp;
    if(!d){ idz(1); return; }
    if(!WIZ.have.length && !WIZ.pool.length && !(WIZ.prop||[]).length){
      // Do „masz" trafia tylko TEN SAM utwór w tej samej wersji. Inna wersja
      // to propozycja do decyzji (osobny blok), a nie „podobne" w „masz" —
      // dawniej cudzy plik z tego pasa zastępował brakujący utwór w secie.
      WIZ.have = (d.auto||[]).map(x => ({...x, _nota:'ok'}));
      WIZ.prop = (d.resolve||[]).map(x => ({...x, _nota:'other'}));
      WIZ.pool = (d.missing||[]).map(x => ({...x, st:'wait', file:null, pct:null}));
    }
    if(!WIZ.prop) WIZ.prop = [];
    const uwagi = (d.uwagi||[]).map(u => `<div class="uwaga-imp" style="border-color:${K.warn}"><b style="color:${K.warn}">${esc(t.importNote)}:</b> ${esc(u)}</div>`).join('');
    m.innerHTML = `<div class="s2">
      <div class="nag">
        ${naglowekKroku(t.s2kicker, t.s2title, t.s2sub)}
        <div class="liczniki">
          <div class="licznik"><div class="n" style="color:${K.ok}" data-n-have></div><div class="e">${esc(t.have)}</div></div>
          <div class="licznik"><div class="n" style="color:${K.acc}" data-n-pool></div><div class="e">${esc(t.toGet)}</div></div>
        </div>
      </div>
      ${uwagi}
      <div class="kolumny">
        <div class="kol-panel"><div class="kh"><span class="dot ok"></span>${esc(t.haveTitle)}</div><div class="kl" data-have></div></div>
        <div class="kol-panel"><div class="kh"><span class="dot acc"></span>${esc(t.poolTitle)}<button class="b-all" data-all>${esc(t.dlAll)}</button></div><div class="kl" data-pool></div></div>
      </div>
      <div class="stopa"><span class="info" data-info>${esc(t.s2foot)}</span><button class="cta" data-dalej>${esc(t.next)} →</button></div>
    </div>`;
    const root = m.firstElementChild;
    m.querySelector('[data-dalej]').onclick = () => idz(3);
    m.querySelector('[data-all]').onclick = pobierzWszystko;
    on(root, 'click', '[data-dl]', (e, el) => pobierzJeden(WIZ.pool[+el.dataset.dl]));
    on(root, 'click', '[data-pick]', (e, el) => {
      const u = WIZ.pool[+el.dataset.pick];
      wybierzWynik(u, {poZleceniu:(queued) => { u.st = 'queued'; u.file = queued; rysujKolumny(); }});
    });
    // propozycja „inna wersja": weź moją albo pobierz właściwą
    on(root, 'click', '[data-prop-use]', (e, el) => {
      const u = WIZ.prop.splice(+el.dataset.propUse, 1)[0]; if(!u) return;
      WIZ.have.push(u); rysujKolumny();
    });
    on(root, 'click', '[data-prop-get]', (e, el) => {
      const u = WIZ.prop.splice(+el.dataset.propGet, 1)[0]; if(!u) return;
      const w = {...u, file:null, _nota:null, st:'wait', pct:null};
      WIZ.pool.unshift(w); pobierzJeden(w);
    });
    rysujKolumny();
    startPoll();
  }
  function rysujKolumny(){
    const m = MAIN(); if(!m || WIZ.krok !== 2) return;
    const t = T();
    const haveEl = m.querySelector('[data-have]'), poolEl = m.querySelector('[data-pool]');
    if(!haveEl) return;
    const prop = WIZ.prop || [];
    m.querySelector('[data-n-have]').textContent = WIZ.have.length;
    m.querySelector('[data-n-pool]').textContent = WIZ.pool.length + prop.length;
    const notaHave = u => {
      if(u._justGot) return `<span class="nota" style="color:${K.acc}">${esc(t.justGot)}</span>`;
      const k = u._nota || 'ok';
      const tip = (k !== 'ok' && u.file) ? ` title="${esc(S.nazwaPliku(u.file))}"` : '';
      return `<span class="nota" style="color:${k==='ok'?K.ok:K.warn}"${tip}>${esc(t.notes[k])}</span>`;
    };
    haveEl.innerHTML = WIZ.have.length ? WIZ.have.map(u => `
      <div class="poz2">${okladka(u.file)}
        <div class="kto"><div class="t">${esc(u.title)}</div><div class="a">${esc(u.artist)}</div></div>
        ${notaHave(u)}</div>`).join('') : `<div class="pusto2">${esc(t.noneHave)}</div>`;
    const kup = u => (u.sklepy||[]).slice(0, 2).map(x => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(t.buy)}: ${esc(x.name)} ↗</a>`).join(' · ');
    const czas = s => s ? fmtTime(s) : '?';
    const propHtml = prop.length ? `<div class="podnag" style="color:${K.warn}">${esc(t.propTitle)}</div>` + prop.map((u, i) => `
      <div class="poz2">
        <span class="dot" style="background:${K.warn}"></span>
        <div class="kto"><div class="t">${esc(u.title)}</div>
          <div class="a">${esc(u.artist)} · <span title="${esc(S.nazwaPliku(u.file||''))}">${esc(fmt(t.propHas, {file:S.nazwaPliku(u.file||'')}))}</span>${(u.file_duration && u.duration) ? ' · '+esc(fmt(t.propLen, {mine:czas(u.file_duration), want:czas(u.duration)})) : ''}</div></div>
        <div class="akcje"><button class="b-pick" data-prop-use="${i}">${esc(t.propUse)}</button><button class="b-dl" data-prop-get="${i}">${esc(t.propGet)}</button></div>
      </div>`).join('') + (WIZ.pool.length ? `<div class="podnag" style="color:${K.acc}">${esc(t.poolTitle)}</div>` : '') : '';
    poolEl.innerHTML = propHtml + (WIZ.pool.length ? WIZ.pool.map((u, i) => {
      const st = u.st || 'wait', kol = ST_KOLOR[st] || K.dim;
      const czeka = st === 'wait' || st === 'failed';
      const puls = (st === 'searching' || st === 'downloading') ? 'pulsuje' : '';
      const pct = st === 'downloading' && u.pct != null ? ` ${u.pct}%` : '';
      const linki = czeka && (u.sklepy||[]).length ? ' · '+kup(u) : '';
      return `<div class="poz2">
        <span class="dot ${puls}" style="background:${kol}"></span>
        <div class="kto"><div class="t">${esc(u.title)}</div><div class="a">${esc(u.artist)}${linki}</div>
          ${st === 'downloading' ? `<div class="bar"><i style="width:${u.pct||0}%"></i></div>` : ''}</div>
        ${st === 'failed' ? `<span class="nota" style="color:${kol}" title="${esc(u.detail||'')}">${esc(t.st.failed)}</span>` : ''}
        ${czeka
          ? `<div class="akcje"><button class="b-dl" data-dl="${i}">${esc(t.dl)}</button><button class="b-pick" data-pick="${i}">${esc(t.pick)}</button></div>`
          : `<span class="nota" style="color:${kol}">${esc(t.st[st] || st)}${pct}</span>`}
      </div>`;
    }).join('') : (prop.length ? '' : `<div class="pusto2">${esc(t.allGot)} 🎉</div>`));
    podepnijOkladki(haveEl);
    const info = m.querySelector('[data-info]');
    if(info && !info.classList.contains('warn') && !info.classList.contains('bad')){
      info.textContent = prop.length ? fmt(t.propWait, {n:prop.length, utw:lm(prop.length, t.utw)}) : t.s2foot;
    }
    const all = m.querySelector('[data-all]');
    const doPobrania = WIZ.pool.filter(u => u.st === 'wait' || u.st === 'failed').length;
    all.classList.toggle('hide', !doPobrania);
  }
  async function pobierzJeden(u){
    if(!u) return;
    u.st = 'searching'; rysujKolumny();
    try{
      const j = await api('/api/download', {method:'POST', body:{artist:u.artist, title:u.title, duration:u.duration}, cicho:true});
      u.st = 'queued'; u.file = j.queued;
    }catch(e){ u.st = 'failed'; u.detail = e.message; toast(e.message, 'bad'); }
    rysujKolumny();
  }
  async function pobierzWszystko(){
    const m = MAIN(); const t = T();
    const btn = m.querySelector('[data-all]'), info = m.querySelector('[data-info]');
    const items = WIZ.pool.filter(u => u.st === 'wait' || u.st === 'failed').map(u => ({artist:u.artist, title:u.title, duration:u.duration}));
    if(!items.length) return;
    btn.disabled = true; btn.textContent = t.adding;
    try{
      const d = await api('/api/queue', {method:'POST', body:{items}, cicho:true});
      WIZ.pool.forEach(u => { if(u.st === 'wait' || u.st === 'failed') u.st = 'searching'; });
      info.className = 'info'; info.innerHTML = esc(fmt(t.queuedAll, {n:d.added}));
    }catch(e){ info.className = 'info bad'; info.textContent = '✗ '+e.message; }
    btn.disabled = false; btn.textContent = t.dlAll;
    rysujKolumny();
  }
  function przeniesGotowy(u){
    const i = WIZ.pool.indexOf(u); if(i < 0) return;
    WIZ.pool.splice(i, 1);
    u._justGot = true; u.st = 'done';
    WIZ.have.push(u);
  }
  // Kolejka + transfery: co apka robi i co się już pobrało. Odpytujemy,
  // dopóki kreator jest na ekranie i są utwory w puli.
  function startPoll(){
    if(WIZ.poll) return;
    WIZ.poll = setInterval(pollTransfery, 2500);
    pollTransfery();
  }
  async function pollTransfery(){
    const h = HOST();
    if(!h || h.classList.contains('hide') || S.biezacy() !== 'kreator'){ clearInterval(WIZ.poll); WIZ.poll = null; return; }
    if(!WIZ.pool.length || WIZ.krok > 3) return;
    try{
      const q = await api('/api/queue', {cicho:true});
      const byKey = {};
      (q.jobs||[]).forEach(j => { byKey[(j.artist+'|'+j.title).toLowerCase()] = j; });
      let zmiana = false;
      for(const u of [...WIZ.pool]){
        const j = byKey[(u.artist+'|'+u.title).toLowerCase()];
        if(!j) continue;
        if(j.status === 'done'){ przeniesGotowy(u); zmiana = true; continue; }
        if(j.status === 'failed' && u.st !== 'failed'){ u.st = 'failed'; u.detail = j.detail; zmiana = true; }
        else if(j.status === 'searching' && u.st !== 'searching'){ u.st = 'searching'; zmiana = true; }
        else if(j.status === 'queued' && !u.file){ u.st = 'queued'; u.file = j.file; zmiana = true; }
      }
      const info = MAIN() && MAIN().querySelector('[data-info]');
      if(info && WIZ.krok === 2){
        if(q.paused_for_s > 0 && q.note){ info.className = 'info warn'; info.textContent = `⏸ ${q.note} (${q.paused_for_s}s)`; }
        else if(info.classList.contains('warn')){ info.className = 'info'; info.textContent = T().s2foot; }
      }
      const d = await api('/api/transfers', {cicho:true});
      const byName = {}; (d.items||[]).forEach(x => { byName[x.name] = x; });
      for(const u of [...WIZ.pool]){
        if(!u.file) continue;
        const tr = byName[u.file]; if(!tr) continue;
        if(tr.status === 'done'){ przeniesGotowy(u); zmiana = true; }
        else if(tr.status === 'failed'){ u.st = 'failed'; zmiana = true; }
        else if(tr.status === 'active'){ u.st = 'downloading'; u.pct = Math.round(tr.percent); zmiana = true; }
      }
      if(zmiana) rysujKolumny();
    }catch(e){}
  }

  /* ---------- 3. nazwa setu ---------- */
  function krok3(m){
    const t = T();
    if(!WIZ.sugestie.length) WIZ.sugestie = sugestieNazw(WIZ.imp, WIZ.nazwa);
    m.innerHTML = `<div class="s3">
      ${naglowekKroku(t.s3kicker, t.s3title, t.s3sub)}
      <input class="nazwa" value="${esc(WIZ.nazwa)}" data-nazwa spellcheck="false">
      <div class="chipy">${WIZ.sugestie.map(s => `<button class="chip" data-chip="${esc(s)}">${esc(s)}</button>`).join('')}</div>
      <div class="stopa"><span class="info">${esc(t.s3foot)}</span><button class="cta" data-dalej>${esc(t.next)} →</button></div>
    </div>`;
    const inp = m.querySelector('[data-nazwa]');
    setTimeout(() => { inp.focus(); inp.select(); }, 50);
    const dalej = () => { WIZ.nazwa = inp.value.trim() || 'selekta-set'; WIZ.review = null; idz(4); };
    m.querySelector('[data-dalej]').onclick = dalej;
    inp.onkeydown = e => { if(e.key === 'Enter') dalej(); };
    inp.oninput = () => { WIZ.nazwa = inp.value; };
    on(m.firstElementChild, 'click', '[data-chip]', (e, el) => { inp.value = el.dataset.chip; WIZ.nazwa = el.dataset.chip; inp.focus(); });
  }

  /* ---------- 4. zbieranie + analiza + bramka jakości ---------- */
  function krok4(m){
    const t = T();
    const wm = WIZ.wMiejscu;
    const tytul = wm ? fmt(t.tidyTitle, {name:WIZ.nazwa}) : t.s4title;
    const sub = wm ? fmt(t.tidySub4, {n:WIZ.pliki.length}) : t.s4sub;
    m.innerHTML = `<div class="s4">
      ${naglowekKroku(t.s4kicker, tytul, sub)}
      <div>
        <div class="proc"><span class="duzy"><b data-pct>0</b><span>%</span></span><span class="idx" data-idx></span></div>
        <div class="pasek-post"><i data-bar style="width:0%"></i></div>
        <div class="biez" data-biez></div>
      </div>
      <div class="etapy" data-etapy></div>
    </div>`;
    if(!WIZ.postep || (!WIZ.analizaTrwa && !WIZ.review)) uruchomAnalize();
    else rysujPostep();
  }
  function rysujPostep(){
    const m = MAIN(); if(!m || WIZ.krok !== 4) return;
    const t = T(), p = WIZ.postep || {pct:0, idx:'', biez:'', etapy:['wait','wait','wait','wait'], blad:null};
    const pctEl = m.querySelector('[data-pct]'); if(!pctEl) return;
    pctEl.textContent = Math.round(p.pct);
    m.querySelector('[data-idx]').textContent = p.idx || '';
    m.querySelector('[data-bar]').style.width = p.pct+'%';
    const biez = m.querySelector('[data-biez]');
    if(p.blad){
      biez.className = 'biez bad';
      biez.innerHTML = `✗ ${esc(p.blad)} <button class="btn mini" data-retry style="margin-left:6px">${esc(t.retry)}</button>`;
      biez.querySelector('[data-retry]').onclick = () => uruchomAnalize();
    }else{
      biez.className = 'biez';
      biez.innerHTML = (p.pct < 100 ? spin() : '') + esc(p.biez || '');
    }
    const stTxt = {done:t.stStates[0], run:t.stStates[1], wait:t.stStates[2]};
    m.querySelector('[data-etapy]').innerHTML = t.stages.map((label, i) => {
      const st = p.etapy[i] || 'wait';
      return `<div class="etap ${st}"><span class="dot"></span><div class="l">${esc(label)}</div><div class="st">${esc(stTxt[st])}</div></div>`;
    }).join('');
  }
  async function uruchomAnalize(){
    if(WIZ.analizaTrwa) return;
    const t = T();
    const p = WIZ.postep = {pct:0, idx:'', biez:'', etapy:['wait','wait','wait','wait'], blad:null};
    const ust = (zm) => { Object.assign(p, zm); rysujPostep(); };
    WIZ.analizaTrwa = true; rysujKroki();
    try{
      // 1) zbierz — razem z utworami, których pobieranie skończyło się później
      if(WIZ.wMiejscu){
        ust({etapy:['done','wait','wait','wait'], pct:2, biez:fmt(t.collected, {n:WIZ.pliki.length})});
      }else{
        ust({etapy:['run','wait','wait','wait'], biez:t.collecting});
        const files = WIZ.have.map(u => u.file).filter(Boolean);
        const tracks = [...WIZ.have, ...WIZ.pool, ...(WIZ.prop||[])].map(u => ({artist:u.artist, title:u.title, duration:u.duration}));
        const d = await api('/api/playlist/collect', {method:'POST', body:{name:WIZ.nazwa, files, tracks}, cicho:true});
        WIZ.pliki = d.files; WIZ.folder = d.folder;
        ust({etapy:['done','wait','wait','wait'], pct:5, biez:fmt(t.collected, {n:d.count}) + (d.late && d.late.length ? fmt(t.late, {n:d.late.length}) : '')});
      }
      // 2) analiza każdego pliku (BPM, tonacja, jakość)
      const n = WIZ.pliki.length;
      for(let i = 0; i < n; i++){
        if(WIZ.postep !== p) return;                  // „Nowy set" w trakcie
        const pct = 5 + Math.round(85 * i / Math.max(n, 1));
        ust({etapy:['done','run','run','wait'], pct, idx:`${i+1} / ${n}`, biez:`${t.analyzing} ${i+1}/${n}: ${S.nazwaPliku(WIZ.pliki[i])}`});
        try{ await api('/api/playlist/analyze', {method:'POST', body:{name:WIZ.nazwa, path:WIZ.pliki[i]}, cicho:true}); }catch(e){}
      }
      // 3) bramka jakości: integralność, okładki, tagi, tempo, duble
      ust({etapy:['done','done','run','run'], pct:92, idx:`${n} / ${n}`, biez:t.reviewing});
      const rv = await api('/api/playlist/review', {method:'POST', body:{name:WIZ.nazwa, files:WIZ.pliki}, cicho:true});
      if(WIZ.postep !== p) return;
      WIZ.review = rv;
      ust({etapy:['done','done','done','done'], pct:100, biez:fmt(t.reviewed, {n:rv.count, m:rv.z_problemami})});
      WIZ.analizaTrwa = false; WIZ.maks = 5; rysujKroki();
      await czekaj(800);
      if(WIZ.postep === p && WIZ.krok === 4) idz(5);
    }catch(e){
      WIZ.analizaTrwa = false; rysujKroki();
      ust({blad:e.message});
    }
  }

  /* ---------- 5. rewizja i eksport ---------- */
  // Pasek narzędzi ma własny stan (trwające „napraw wszystko" / „szukaj
  // lepszych"), bo lista odświeża się po każdym utworze i zgubiłaby postęp.
  function krok5(m){
    const t = T(), rv = WIZ.review;
    if(!rv){ idz(4); return; }
    m.innerHTML = `<div class="s5">
      <div class="nag">
        ${naglowekKroku(t.s5kicker, t.s5title, t.s5sub)}
        <div class="liczniki">
          <div class="licznik"><div class="n" data-n-count></div><div class="e">${esc(t.tracks)}</div></div>
          <div class="licznik"><div class="n" style="color:${K.warn}" data-n-problem></div><div class="e">${esc(t.toReview)}</div></div>
          <div class="licznik"><div class="n" data-n-median></div><div class="e">${esc(t.median)}</div></div>
        </div>
      </div>
      <div class="narz" data-narz></div>
      <div class="lista5" data-lista></div>
      <div class="stopa"><span class="nota" data-nota>${esc(t.s5note)}</span>
        <button class="btn acc glow" data-play><span>▶</span><span data-play-txt></span></button></div>
    </div>`;
    const root = m.firstElementChild;
    m.querySelector('[data-play]').onclick = eksportuj;
    on(root, 'click', '[data-fix-all]', () => naprawWszystko());
    on(root, 'click', '[data-better-all]', () => szukajWszystkich());
    on(root, 'click', '[data-stop]', (e, el) => { WIZ.narz.przerwij = true; el.textContent = '…'; });
    on(root, 'click', '[data-fix]', (e, el) => naprawJeden(WIZ.review.tracks[+el.dataset.fix]));
    on(root, 'click', '[data-lepsza]', (e, el) => szukajLepszej(WIZ.review.tracks[+el.dataset.lepsza]));
    on(root, 'click', '[data-usun]', async (e, el) => {
      const u = WIZ.review.tracks[+el.dataset.usun];
      WIZ.pliki = WIZ.pliki.filter(f => f !== u.path);
      await odswiezReview();
    });
    on(root, 'click', '[data-bierz]', async (e, el) => {
      const [ti, ci] = el.dataset.bierz.split(':').map(Number);
      const u = WIZ.review.tracks[ti], c = (u._lepsze || [])[ci]; if(!c) return;
      el.disabled = true; el.textContent = '…';
      try{
        await api('/api/download', {method:'POST', body:{artist:u.artist, title:u.title, path:c.path, user:c.user, size:c.size}, cicho:true});
        el.textContent = t.inQueue; c._wKolejce = true;
      }catch(err){ el.textContent = '✗'; el.disabled = false; toast(err.message, 'bad'); }
    });
    rysujReview();
  }
  const doNaprawy = rv => rv.tracks.filter(u => u.problems.some(p => p.naprawialne));
  const doWymiany = rv => rv.tracks.filter(u => u.problems.some(p => p.typ === 'jakosc'));
  function rysujNarz(){
    const m = MAIN(); if(!m || WIZ.krok !== 5) return;
    const t = T(), rv = WIZ.review, n = WIZ.narz;
    const narz = m.querySelector('[data-narz]'); if(!narz || !rv) return;
    const napr = doNaprawy(rv), wym = doWymiany(rv);
    const zLiczba = (s, k) => s.replace(/\(\d+\)/, `(${k})`);
    const zajety = n.fixTrwa || n.wymTrwa;
    narz.innerHTML = `
      ${napr.length ? `<button class="btn" data-fix-all ${zajety ? 'disabled' : ''}>${esc(zLiczba(t.fixAll, napr.length))}</button>` : ''}
      ${wym.length ? `<button class="btn" data-better-all ${zajety ? 'disabled' : ''}>${esc(zLiczba(t.betterAll, wym.length))}</button>` : ''}
      ${n.wymTrwa ? `<button class="btn mini" data-stop>${esc(n.przerwij ? '…' : t.stop)}</button>` : ''}
      <span class="nota">${wym.length ? esc(t.betterNote) + ' — ' + esc(fmt(t.totalMin, {n:Math.ceil(wym.length*55/60)})) : (napr.length ? esc(t.fixAllNote) : (rv.z_problemami ? esc(t.decide) : esc(t.allOk)))}</span>
      <span class="postep ${n.progKl||''}">${n.prog || ''}</span>`;
  }
  function narzProg(html, kl){ WIZ.narz.prog = html; WIZ.narz.progKl = kl || ''; rysujNarz(); }
  function rysujReview(){
    const m = MAIN(); if(!m || WIZ.krok !== 5) return;
    const t = T(), rv = WIZ.review; if(!rv) return;
    const pl = S.jezyk.get() === 'pl';
    m.querySelector('[data-n-count]').textContent = rv.count;
    m.querySelector('[data-n-problem]').textContent = rv.z_problemami;
    m.querySelector('[data-n-median]').innerHTML = rv.mediana_bpm ? `${Math.round(rv.mediana_bpm)}<small>BPM</small>` : '—';
    m.querySelector('[data-play-txt]').textContent = `${t.play} · ${rv.count}`;
    m.querySelector('[data-play]').disabled = !rv.count;
    rysujNarz();

    rv.tracks.forEach((u, i) => { u._i = i; });
    // najpierw to, co wymaga decyzji — DJ nie ma szukać problemów przez przewijanie
    const waga = u => u.problems.some(p => HEAVY(p.typ)) ? 0 : (u.problems.length ? 1 : 2);
    const uwaga = rv.tracks.filter(u => u.problems.length).sort((a, b) => waga(a) - waga(b));
    const reszta = rv.tracks.filter(u => !u.problems.length);

    const wiersz = u => {
      const probs = u.problems || [];
      const ciezki = probs.some(p => HEAVY(p.typ));
      const znak = ciezki ? '✕' : (probs.length ? '!' : '✓');
      const kol = ciezki ? K.bad : (probs.length ? K.warn : K.ok);
      const fixable = probs.some(p => p.naprawialne);
      const slaba = probs.some(p => p.typ === 'jakosc');
      const msg = WIZ.fixMsg[u.path];
      const lepsze = u._lepsze ? `<div class="lepsze">${u._lepsze.slice(0,5).map((c, ci) => `
          <div class="w"><span class="f">${esc(c.format)}</span><span class="m">${c.bitrate ? c.bitrate+' kbps' : esc(t.lossless)}</span><span class="m">${c.size_mb} MB</span>
          <span class="n" title="${esc(c.filename)}">${esc(c.filename)}${c.dlaczego ? ` <span style="color:${K.dim}">· ${esc(c.dlaczego)}</span>` : ''}</span>
          <button class="b-dl" data-bierz="${u._i}:${ci}" ${c._wKolejce ? 'disabled' : ''}>${c._wKolejce ? esc(t.inQueue) : esc(t.dl)}</button></div>`).join('')}</div>`
        : (u._lepszeInfo ? `<div class="lepsze"><span>${u._szukam ? spin()+' ' : ''}${esc(u._lepszeInfo)}</span></div>` : '');
      const lepszaTxt = u._szukam ? t.st.searching : (u._lepsze ? fmt(t.betterN, {n:u._lepsze.length}) : t.better);
      return `<div class="poz5 ${probs.length ? '' : 'czysty'}">
        <span class="znak" style="color:${kol}">${znak}</span>
        ${okladka(u.file)}
        <div class="kto">
          <div class="t">${esc(u.title)}</div>
          <div class="a">${esc(u.artist)}<span class="bpm">${u.bpm ? Math.round(u.bpm)+' BPM' : '—'}</span>${u.camelot ? `<span class="cam" style="background:${CAM[u.camelot] || K.dim}">${esc(u.camelot)}</span>` : ''}</div>
          ${probs.length ? `<div class="probl">${probs.map(p => { const c = HEAVY(p.typ) ? K.bad : K.warn; return `<span class="prob" style="color:${c}"><span class="tag" style="background:${c}">${esc(t.prob[PROB_TYP(p.typ)] || (pl ? 'UWAGA' : 'NOTE'))}</span>${esc(p.opis)}</span>`; }).join('')}</div>` : ''}
          ${msg ? `<div class="fixmsg ${msg.zle ? 'bad' : ''}">${esc(msg.txt)}</div>` : ''}
          ${lepsze}
        </div>
        <div class="akcje">
          ${fixable ? `<button class="b-dl" data-fix="${u._i}" ${u._naprawiam ? 'disabled' : ''}>${u._naprawiam ? '…' : esc(t.fix)}</button>` : ''}
          ${slaba ? `<button class="b-lepsza" data-lepsza="${u._i}" ${u._szukam ? 'disabled' : ''}>${esc(lepszaTxt)}</button>` : ''}
        </div>
        <button class="b-usun" data-usun="${u._i}">${esc(t.remove)}</button>
      </div>`;
    };
    const brak = (rv.pominiete||[]).length ? `<div class="uwaga uwaga5"><b>${esc(fmt(t.missingFiles, {n:rv.pominiete.length, pliki:lm(rv.pominiete.length, t.plk)}))}</b><br>${esc(fmt(t.missingFilesSub, {list:rv.pominiete.join(', ')}))}</div>` : '';
    const lista = m.querySelector('[data-lista]');
    lista.innerHTML = brak + uwaga.map(wiersz).join('')
      + (uwaga.length && reszta.length ? `<div class="rozdz">${esc(fmt(t.restOk, {n:reszta.length}))}</div>` : '')
      + reszta.map(wiersz).join('')
      + (!rv.tracks.length ? `<div class="pusto">${esc(pl ? 'set jest pusty' : 'the set is empty')}</div>` : '');
    podepnijOkladki(lista);
  }
  async function odswiezReview(){
    const stare = WIZ.review;
    try{
      const rv = await api('/api/playlist/review', {method:'POST', body:{name:WIZ.nazwa, files:WIZ.pliki}, cicho:true});
      // zachowaj wyniki „szukaj lepszej" dla tych samych plików
      if(stare) rv.tracks.forEach(u => { const s = stare.tracks.find(x => x.path === u.path); if(s){ u._lepsze = s._lepsze; u._lepszeInfo = s._lepszeInfo; } });
      WIZ.review = rv;
    }catch(e){
      if(e.status === 400 && /pust/i.test(e.message)){ WIZ.review = {...stare, count:0, z_problemami:0, tracks:[], pominiete:[]}; }
      else toast(e.message, 'bad');
    }
    rysujReview();
  }
  async function naprawJeden(u){
    if(u._naprawiam) return;
    u._naprawiam = true; rysujReview();
    const powiedz = (txt, zle) => { WIZ.fixMsg[u.path] = {txt, zle}; };
    try{
      const j = await api('/api/playlist/fix', {method:'POST', body:{path:u.path}, cicho:true});
      if(j.ok){
        if((j.nieudane||[]).length) powiedz(j.nieudane.join(' · '), false); else delete WIZ.fixMsg[u.path];
        u._naprawiam = false;
        await odswiezReview();
        return;
      }
      powiedz(j.message || 'nie udało się naprawić', false);
    }catch(e){ powiedz(String(e.message), true); }
    u._naprawiam = false; rysujReview();
  }
  async function naprawWszystko(){
    const t = T(), n = WIZ.narz;
    if(n.fixTrwa || n.wymTrwa) return;
    const lista = doNaprawy(WIZ.review);
    n.fixTrwa = true;
    let ok = 0, nie = 0;
    for(let i = 0; i < lista.length; i++){
      const u = lista[i];
      if(WIZ.krok !== 5 || WIZ.review === null) break;
      narzProg(`${spin()} ${i+1}/${lista.length}: ${esc(u.title.slice(0, 40))}`);
      try{
        const j = await api('/api/playlist/fix', {method:'POST', body:{path:u.path}, cicho:true});
        if(j.ok){ ok++; if((j.nieudane||[]).length) WIZ.fixMsg[u.path] = {txt:j.nieudane.join(' · '), zle:false}; else delete WIZ.fixMsg[u.path]; }
        else { nie++; WIZ.fixMsg[u.path] = {txt:j.message || 'nie udało się', zle:false}; }
      }catch(e){ nie++; WIZ.fixMsg[u.path] = {txt:String(e.message), zle:true}; }
    }
    n.fixTrwa = false;
    narzProg(esc(fmt(t.fixed, {ok})) + (nie ? esc(fmt(t.fixedFail, {n:nie})) : ''));
    await odswiezReview();
  }
  // Stratnej kompresji nie da się odkręcić — jedyne, co ma sens, to lepsze źródło.
  async function szukajLepszej(u){
    const t = T();
    if(u._szukam) return false;
    u._szukam = true; u._lepszeInfo = t.searchingSlsk; u._lepsze = null; rysujReview();
    try{
      const d = await api('/api/upgrade/find', {method:'POST', body:{artist:u.artist, title:u.title, duration:u.duration, lossless:u.lossless, bitrate:u.bitrate, grade:u.quality}, cicho:true});
      if(!d.count){ u._lepszeInfo = fmt(t.nothingBetter, {n:d.sprawdzonych, q:d.searched_as || u.artist}); u._lepsze = null; }
      else { u._lepszeInfo = ''; u._lepsze = d.candidates; }
    }catch(e){ u._lepszeInfo = '✗ '+e.message; u._lepsze = null; }
    u._szukam = false; rysujReview();
    return !!(u._lepsze && u._lepsze.length);
  }
  async function szukajWszystkich(){
    const t = T(), n = WIZ.narz;
    if(n.fixTrwa || n.wymTrwa) return;
    const lista = doWymiany(WIZ.review);
    n.wymTrwa = true; n.przerwij = false; rysujNarz();
    // Soulseek potrafi zerwać połączenie w trakcie długiej serii — czekamy
    // na powrót zamiast przepalać resztę listy na błędach.
    const czekajNaPolaczenie = async () => {
      for(let s = 0; s < 40 && !n.przerwij; s++){
        const st = await S.status(true);
        if(st && st.level === 'green') return true;
        narzProg(esc(fmt(t.waitSlsk, {s:s*15})), 'warn');
        await czekaj(15000);
      }
      return false;
    };
    let znalezione = 0, zle = false;
    for(let i = 0; i < lista.length && !n.przerwij; i++){
      const u = lista[i];
      if(WIZ.krok !== 5 || !WIZ.review || !WIZ.review.tracks.includes(u)) break;
      const st = await S.status(true);
      if(!st || st.level !== 'green'){
        if(!await czekajNaPolaczenie()){ narzProg(esc(fmt(t.slskGone, {i, n:lista.length})), 'bad'); zle = true; break; }
      }
      narzProg(`${spin()} ${i+1}/${lista.length}: ${esc(u.title.slice(0, 34))}`);
      if(await szukajLepszej(u)) znalezione++;
      if(i < lista.length - 1) await czekaj(4000);   // oddech między utworami
    }
    n.wymTrwa = false;
    if(!zle) narzProg(esc(fmt(t.betterDone, {n:znalezione, m:lista.length})) + (n.przerwij ? esc(t.interrupted) : ''));
    else rysujNarz();
  }
  async function eksportuj(){
    const t = T(), m = MAIN();
    const btn = m.querySelector('[data-play]'), nota = m.querySelector('[data-nota]');
    btn.disabled = true; nota.innerHTML = spin()+' '+esc(t.exporting);
    try{
      const j = await api('/api/playlist/export', {method:'POST', body:{name:WIZ.nazwa, files:WIZ.pliki}, cicho:true});
      if(j.ok){
        WIZ.eksport = j; WIZ.done = true; nota.textContent = t.s5note; rysujDone();
      }else{
        nota.innerHTML = `<span style="color:${K.warn}">⚠ ${esc(j.message || t.exportFail)}</span>`;
        toast(j.message || t.exportFail, 'warn', 6000);
      }
    }catch(e){ nota.innerHTML = `<span style="color:${K.bad}">✗ ${esc(e.message)}</span>`; }
    btn.disabled = false;
  }

  /* ---------- nakładka DONE ---------- */
  function rysujDone(){
    const h = HOST(); if(!h) return;
    const stara = h.querySelector('.gotowe'); if(stara) stara.remove();
    if(!WIZ.done) return;
    const t = T(), j = WIZ.eksport || {};
    const n = j.count != null ? j.count : (WIZ.review ? WIZ.review.count : 0);
    const sub = t.doneSub.replace('{name}', j.playlist || WIZ.nazwa).replace(/\(12 [^)]*\)/, `(${utworow(n)})`);
    const el = document.createElement('div'); el.className = 'gotowe';
    el.innerHTML = `<div class="box">
      <img src="/static/assets/selekta-mark.png" alt="">
      <h2>${esc(t.doneTitle)}</h2>
      <p>${esc(sub)}</p>
      <button data-nowy>${esc(t.again)}</button>
    </div>`;
    el.querySelector('[data-nowy]').onclick = () => { reset(); rysujKroki(); rysujKrok(); };
    h.querySelector('.kr').appendChild(el);
  }
})();
