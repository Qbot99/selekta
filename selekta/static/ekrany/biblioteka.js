/* ============================================================
   Ekran „Biblioteka" (projekt 2c) + arkusz „Szczegóły utworu" (3c).

   Tabela: render przez innerHTML (do ~1500 wierszy), zdarzenia przez
   delegację (S.on). Zaznaczenie trzymamy po NAZWIE PLIKU, nie po
   indeksie — tabela przerysowuje się po każdej analizie i filtrze.
   Arkusz: waveform 120 słupków wg projektu, pod nim rozwijana sekcja
   „siatka beatów" z ręczną korektą kotwicy (przeciąganie na canvasie,
   /api/siatka, /api/tempo, /api/tempo/przyjmij).
   Wystawia: S.otworzSzczegoly(file).
   ============================================================ */
(() => {
  const {esc, fmtTime, fmtMB, fmtLicz, CAM, K, api, on, $, $$} = S;
  const AUDIO_ACCEPT = '.flac,.mp3,.wav,.aiff,.aif,.m4a,.ogg,.opus';
  const JAKOSC = {ok:['✓ dobra', K.ok], warn:['? wątpliwa', K.warn], bad:['✕ zła', K.bad]};
  const RANGA_JAKOSCI = {ok:0, warn:1, bad:2};
  const FMT_ZNANE = new Set(['flac','wav','aiff','aif','mp3','m4a','ogg']);

  // ---------- stan ekranu ----------
  const st = {
    host:null, tracks:[], meta:{}, widoczne:[],
    filtr:{szukaj:'', format:'', jakosc:'', klucz:'', bpmOd:null, bpmDo:null},
    sort:{kolumna:'title', kierunek:1},
    // zaznaczenie jest współdzielone z innymi ekranami (Kolejność/Eksport czytają S.stan.wybrane)
    wybrane:(S.stan.wybrane = S.stan.wybrane instanceof Set ? S.stan.wybrane : new Set()), ostatniZazn:null, wyborPodpis:null,
    analizuje:null,           // {i, n, bledy} w trakcie analizy
    dodaje:null,              // tekst postępu dodawania
  };

  // ---------- drobiazgi ----------
  const nf = (v, dp=1) => (typeof v === 'number' && isFinite(v)) ? v.toFixed(dp).replace('.', ',').replace('-', '−') : '—';
  const nfZnak = (v, dp=1) => (typeof v === 'number' && isFinite(v) && v > 0) ? '+' + nf(v, dp) : nf(v, dp);
  const fmtBpm = b => b == null ? '—' : (Math.abs(b - Math.round(b)) < 0.05 ? String(Math.round(b)) : nf(b, 1));
  function fmtCs(s){ // 0:09.46
    if(!isFinite(s) || s == null) return '—';
    let cs = Math.round(s * 100); const m = Math.floor(cs / 6000); cs -= m * 6000; const sek = Math.floor(cs / 100); cs -= sek * 100;
    return `${m}:${String(sek).padStart(2,'0')}.${String(cs).padStart(2,'0')}`;
  }
  function lm(n, [j, m, w]){ n = Math.abs(n); const r10 = n % 10, r100 = n % 100; if(n === 1) return j; if(r10 >= 2 && r10 <= 4 && !(r100 >= 12 && r100 <= 14)) return m; return w; }
  const skrocDom = p => String(p || '').replace(/^\/Users\/[^/]+/, '~').replace(/^\/home\/[^/]+/, '~');
  const encF = f => encodeURIComponent(f);
  const doObejrzenia = t => t.uszkodzony || t.quality === 'warn' || t.quality === 'bad';
  const nieanalizowany = t => !t.uszkodzony && (!t.analyzed || t.quality == null);
  // klucz utworu: ścieżka względna (rozróżnia te same nazwy w podfolderach); inne ekrany podają samą nazwę
  const klucz = t => t.rel || t.file;
  const znajdz = file => st.tracks.find(t => t.rel === file) || st.tracks.find(t => t.file === file);
  const camRanga = c => { const m = /^(\d+)([AB])$/.exec(c || ''); return m ? Number(m[1]) * 2 + (m[2] === 'B' ? 1 : 0) : 99; };
  function fmtTag(ext, extra=''){
    const e = String(ext || '').toLowerCase();
    const inl = FMT_ZNANE.has(e) ? '' : 'background:#2a2521;color:#b0a69c;';
    return `<span class="fmt ${esc(e)}" style="${inl}${extra}">${esc(e.toUpperCase() || '?')}</span>`;
  }

  // ---------- style ekranu (kopiowane z projektu 2c/3c) ----------
  const STYLE = `
#ekran-biblioteka{padding-bottom:0}
#ekran-biblioteka .pasekF{display:flex;gap:8px;align-items:center}
#ekran-biblioteka .szukaj{flex:1;display:flex;align-items:center;gap:10px;background:#171412;border:1px solid #2a2522;border-radius:9px;padding:9px 14px;color:#5e5650;font-size:13.5px;min-width:0}
#ekran-biblioteka .szukaj:focus-within{border-color:#ff6a3d}
#ekran-biblioteka .szukaj input{flex:1;min-width:0;background:transparent;border:0;padding:0;color:#f2ece6;font-size:13.5px}
#ekran-biblioteka .szukaj input::placeholder{color:#5e5650}
#ekran-biblioteka .chip{position:relative;background:#171412;border:1px solid #2a2522;border-radius:9px;padding:9px 12px;font-size:13px;color:#8f857c;cursor:pointer;white-space:nowrap;user-select:none;flex-shrink:0}
#ekran-biblioteka .chip:hover{border-color:#3a3330}
#ekran-biblioteka .chip.on{border-color:#ff6a3d;color:#f2ece6}
#ekran-biblioteka .chip.mono{font:500 12px var(--mono)}
#ekran-biblioteka .chip select{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;margin:0}
#ekran-biblioteka .popover{position:absolute;top:calc(100% + 6px);right:0;z-index:6;background:#1e1a17;border:1px solid #2a2522;border-radius:10px;padding:12px;display:flex;gap:8px;align-items:center;box-shadow:0 10px 30px rgba(0,0,0,.5);cursor:default;font:400 13px var(--font);color:#c9c0b8}
#ekran-biblioteka .popover .pole{width:74px;padding:7px 10px;font:500 12.5px var(--mono);text-align:center}
#ekran-biblioteka .popover .pole.szeroki{width:360px;font:400 13px var(--font);text-align:left}
#ekran-biblioteka .tabela{background:#171412;border:1px solid #2a2522;border-radius:14px 14px 0 0;border-bottom:0;overflow:hidden;flex:1;display:flex;flex-direction:column;position:relative;min-height:0}
#ekran-biblioteka .tabela.upusc{border-color:#ff6a3d;box-shadow:inset 0 0 0 1px #ff6a3d}
#ekran-biblioteka .kol{display:grid;grid-template-columns:20px 40px 1fr 70px 130px 60px 60px 60px 40px;gap:14px;align-items:center;padding:12px 20px;border-bottom:1px solid #2a2522;font:500 10.5px var(--mono);letter-spacing:.1em;color:#5e5650;overflow:hidden;scrollbar-gutter:stable}
#ekran-biblioteka .kol .sort{cursor:pointer;user-select:none;white-space:nowrap}
#ekran-biblioteka .kol .sort:hover{color:#c9c0b8}
#ekran-biblioteka .kol .sort.on{color:#f2ece6}
#ekran-biblioteka .lista{scrollbar-gutter:stable}
#ekran-biblioteka .w{display:grid;grid-template-columns:20px 40px 1fr 70px 130px 60px 60px 60px 40px;gap:14px;align-items:center;padding:9px 20px;border-bottom:1px solid #1d1917;cursor:default}
#ekran-biblioteka .w:hover{background:#1a1613}
#ekran-biblioteka .w.zazn{background:rgba(255,106,61,.07)}
#ekran-biblioteka .chk{width:14px;height:14px;border:1px solid #3a3330;border-radius:4px;display:inline-block;cursor:pointer;position:relative;flex-shrink:0}
#ekran-biblioteka .chk:hover{border-color:#8f857c}
#ekran-biblioteka .chk.on{background:#ff6a3d;border-color:#ff6a3d}
#ekran-biblioteka .chk.on::after{content:"";position:absolute;left:4px;top:1px;width:4px;height:7px;border:solid #0f0d0c;border-width:0 2px 2px 0;transform:rotate(45deg)}
#ekran-biblioteka .chk.pol{border-color:#ff6a3d}
#ekran-biblioteka .chk.pol::after{content:"";position:absolute;left:3px;top:5px;width:6px;height:2px;background:#ff6a3d}
#ekran-biblioteka .okl{width:40px;height:40px;border-radius:7px;display:block}
#ekran-biblioteka .okl.pusta{background:#1e1a17}
#ekran-biblioteka .w .t{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#ekran-biblioteka .w .a{font-size:12.5px;color:#8f857c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#ekran-biblioteka .graj{width:28px;height:28px;border-radius:50%;border:1px solid #2a2522;display:grid;place-items:center;font-size:10px;color:#8f857c;cursor:pointer}
#ekran-biblioteka .graj:hover,#ekran-biblioteka .graj.gra{border-color:#ff6a3d;color:#ff6a3d}
#ekran-biblioteka .pasekAkcji{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);z-index:5;background:#1e1a17;border:1px solid #ff6a3d;border-radius:12px;padding:10px 12px 10px 18px;display:flex;align-items:center;gap:10px;box-shadow:0 16px 40px rgba(0,0,0,.55);animation:wjazd .15s ease-out;white-space:nowrap}
#ekran-biblioteka .pasekAkcji .licz{font:600 11px var(--mono);letter-spacing:.1em;color:#ff6a3d;text-transform:uppercase;margin-right:6px}
#ekran-biblioteka .pasekAkcji .pole{width:200px;padding:7px 12px;font-size:13px;background:#0f0d0c}
#ekran-biblioteka .btn .spin{margin-right:6px;border-color:rgba(15,13,12,.25);border-top-color:#0f0d0c}
#ekran-biblioteka .btn:not(.acc) .spin{border-color:#2a2522;border-top-color:#ff6a3d}
/* arkusz 3c */
#arkuszBody .szcz .cam2{font:700 14px var(--mono);padding:5px 10px;border-radius:6px;color:#0f0d0c}
#arkuszBody .szcz .kafel3{background:#0f0d0c;border:1px solid #2a2522;border-radius:12px;padding:16px 18px;min-width:0}
#arkuszBody .szcz .kafel3 .et{font:500 10.5px var(--mono);letter-spacing:.1em;color:#5e5650}
#arkuszBody .szcz .kafel3 .duza{font-size:30px;font-weight:700;letter-spacing:-.02em;line-height:1;margin-top:10px;white-space:nowrap}
#arkuszBody .szcz .kafel3 .duza small{font-size:13px;color:#8f857c;margin-left:4px;font-weight:400;letter-spacing:0}
#arkuszBody .szcz .kafel3 .pod{font-size:12px;color:#8f857c;margin-top:6px;line-height:1.4}
#arkuszBody .szcz .cue{display:flex;flex-direction:column;gap:4px;padding:0 4px;min-width:0}
#arkuszBody .szcz .cue .k{font:500 10.5px var(--mono);letter-spacing:.1em;color:#ff6a3d}
#arkuszBody .szcz .cue .v{font:500 15px var(--mono)}
#arkuszBody .szcz .cue .d{font-size:12px;color:#8f857c}
#arkuszBody .szcz .akcja{background:transparent;border:1px solid #2a2522;color:#f2ece6;border-radius:8px;padding:9px 14px;font-weight:600;font-size:12.5px;cursor:pointer;white-space:nowrap}
#arkuszBody .szcz .akcja:hover{border-color:#ff6a3d}
#arkuszBody .szcz .akcja:disabled{opacity:.5;cursor:default;border-color:#2a2522}
#arkuszBody .szcz .akcja.zla{margin-left:auto;background:transparent;border:0;color:#5e5650;padding:9px 10px}
#arkuszBody .szcz .akcja.zla:hover{color:#ff5a6a}
#arkuszBody .szcz .fala{display:flex;align-items:flex-end;gap:1px;height:72px;padding:0 2px}
#arkuszBody .szcz .fala span{flex:1;border-radius:1px;min-width:0}
#arkuszBody .szcz .fala.gra span{opacity:.55}
#arkuszBody .szcz .fala.gra span.zagrany{opacity:1}
#arkuszBody .szcz .zamknij{background:transparent;border:1px solid #2a2522;color:#8f857c;border-radius:8px;width:40px;height:40px;cursor:pointer;font-size:14px}
#arkuszBody .szcz .zamknij:hover{color:#f2ece6;border-color:#3a3330}
#arkuszBody .szcz .play{width:40px;height:40px;border-radius:50%;background:#ff6a3d;color:#0f0d0c;display:grid;place-items:center;font-size:12px;cursor:pointer;border:0;padding:0}
#arkuszBody .szcz .play:hover{background:#ff8a66}
#arkuszBody .szcz .link{background:transparent;border:0;padding:0;font:500 10.5px var(--mono);letter-spacing:.08em;color:#8f857c;cursor:pointer}
#arkuszBody .szcz .link:hover{color:#ff6a3d}
#arkuszBody .szcz .link.on{color:#ff6a3d}
#arkuszBody .szcz canvas{width:100%;display:block;border-radius:6px;background:#141110;cursor:crosshair;touch-action:none}
#arkuszBody .szcz .seg>button:hover{color:#f2ece6}
#arkuszBody .szcz .kand{display:grid;grid-template-columns:1.6fr .9fr .6fr .6fr 1fr auto;gap:14px;align-items:center;padding:12px 16px;border-bottom:1px solid #1d1917}
#arkuszBody .szcz .kand:last-child{border-bottom:0}
#arkuszBody .szcz .kand.naj{background:rgba(255,106,61,.06);border-left:2px solid #ff6a3d}
#arkuszBody .szcz .kand .m{font:500 12px var(--mono);color:#8f857c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
`;

  // ============================================================
  // TABELA — filtry, sortowanie, wiersze
  // ============================================================
  function pasujeDoFiltru(t){
    const f = st.filtr;
    if(f.szukaj){
      const stog = `${t.artist || ''} ${t.title || ''} ${t.file || ''}`.toLowerCase();
      if(!stog.includes(f.szukaj)) return false;
    }
    if(f.format && (t.ext || '').toLowerCase() !== f.format) return false;
    if(f.jakosc){
      if(f.jakosc === 'brak'){ if(!nieanalizowany(t)) return false; }
      else if(f.jakosc === 'obejrzec'){ if(!doObejrzenia(t)) return false; }
      else if(t.quality !== f.jakosc) return false;
    }
    if(f.klucz && t.camelot !== f.klucz) return false;
    if(f.bpmOd != null && !(t.bpm >= f.bpmOd)) return false;
    if(f.bpmDo != null && !(t.bpm <= f.bpmDo)) return false;
    return true;
  }
  function wartoscSortowania(t, k){
    if(k === 'title') return `${t.artist || ''} ${t.title || ''}`.toLowerCase();
    if(k === 'quality') return t.uszkodzony ? 3 : (RANGA_JAKOSCI[t.quality] ?? 9);
    if(k === 'camelot') return camRanga(t.camelot);
    if(k === 'ext') return (t.ext || '').toLowerCase();
    const v = t[k]; return v == null ? -1 : v;
  }
  function widoczne(){
    let lista = st.tracks.filter(pasujeDoFiltru);
    const {kolumna, kierunek} = st.sort;
    if(kolumna){
      lista = [...lista].sort((a, b) => {
        const x = wartoscSortowania(a, kolumna), y = wartoscSortowania(b, kolumna);
        if(x === y) return 0;
        return (x > y ? 1 : -1) * kierunek;
      });
    }
    return lista;
  }
  const filtrAktywny = () => { const f = st.filtr; return !!(f.szukaj || f.format || f.jakosc || f.klucz || f.bpmOd != null || f.bpmDo != null); };

  function okladkaHTML(t, kl='okl'){
    return t.has_cover
      ? `<img class="${kl}" loading="lazy" decoding="async" width="40" height="40" src="/api/cover?file=${encF(klucz(t))}" alt="">`
      : `<span class="${kl} pusta"></span>`;
  }
  function wierszHTML(t, i){
    const k = klucz(t);
    const zazn = st.wybrane.has(k);
    const gra = S.player.gra(k);
    let q, qk;
    if(t.uszkodzony){ q = '⚠ uszkodzony'; qk = K.bad; }
    else if(JAKOSC[t.quality]){ [q, qk] = JAKOSC[t.quality]; }
    else { q = '— nieanalizowane'; qk = K.dim; }
    const camBg = t.camelot ? (CAM[t.camelot] || K.dim) : 'transparent';
    const camSt = t.key_conf != null && t.key_conf < 0.4 ? 'opacity:.55' : '';
    const camTyt = t.camelot ? `${t.key || ''}${t.key_conf != null ? ' · pewność ' + nf(t.key_conf, 2) : ''}` : '';
    return `<div class="w${zazn ? ' zazn' : ''}" data-i="${i}">
      <span class="chk${zazn ? ' on' : ''}" data-akcja="zazn"></span>
      ${okladkaHTML(t)}
      <div style="min-width:0"><div class="t" title="${esc(k)}">${esc(t.title)}</div><div class="a">${esc(t.artist)}</div></div>
      ${fmtTag(t.ext)}
      <span style="font-size:12.5px;color:${qk};white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(t.quality_note || (t.uszkodzony ? 'pliku nie da się odczytać — prawdopodobnie przerwane pobieranie' : ''))}">${q}</span>
      <span style="font:500 13px var(--mono)">${fmtBpm(t.bpm)}</span>
      <span class="cam" style="background:${camBg};${camSt}" title="${esc(camTyt)}">${esc(t.camelot || '')}</span>
      <span style="font:500 12.5px var(--mono);color:#8f857c">${fmtTime(t.duration)}</span>
      <span class="graj${gra ? ' gra' : ''}" data-akcja="graj" title="${gra ? 'pauza' : 'odsłuchaj'}">${gra ? '❚❚' : '▶'}</span>
    </div>`;
  }

  function rysujTabele(){
    const host = st.host; if(!host) return;
    const lista = widoczne(); st.widoczne = lista;
    const box = $('#bibLista', host);
    if(!st.tracks.length){
      box.innerHTML = `<div class="pusto">biblioteka jest pusta — dodaj utwory przyciskiem „+ Dodaj utwory” albo upuść pliki tutaj</div>`;
    }else if(!lista.length){
      box.innerHTML = `<div class="pusto">nic nie pasuje do filtrów</div>`;
    }else{
      box.innerHTML = lista.map(wierszHTML).join('');
    }
    $$('#bibKol .sort', host).forEach(el => {
      const on = el.dataset.k === st.sort.kolumna;
      el.classList.toggle('on', on);
      el.textContent = el.dataset.n + (on ? (st.sort.kierunek > 0 ? ' ↓' : ' ↑') : '');
    });
    const licz = $('#bibLicznik', host);
    licz.textContent = filtrAktywny() ? `${fmtLicz(lista.length)} z ${fmtLicz(st.tracks.length)}` : '';
    $('#bibWyczysc', host).classList.toggle('hide', !filtrAktywny());
    odswiezWybor();
    odswiezNaglowek();
  }

  // ---------- nagłówek: liczby, przyciski ----------
  function odswiezNaglowek(){
    const host = st.host; if(!host) return;
    const n = st.tracks.length;
    const m = st.tracks.filter(t => t.analyzed && t.quality != null).length;
    const k = st.tracks.filter(doObejrzenia).length;
    const todo = st.tracks.filter(nieanalizowany).length;
    const sub = $('#bibSub', host);
    if(st.dodaje) sub.innerHTML = `<span class="spin"></span> ${esc(st.dodaje)}`;
    else sub.textContent = `${fmtLicz(n)} ${lm(n, ['utwór','utwory','utworów'])} · ${fmtLicz(m)} ${lm(m, ['przeanalizowany','przeanalizowane','przeanalizowanych'])} · ${fmtLicz(k)} do obejrzenia`;
    const btn = $('#bibAnalizuj', host);
    if(st.analizuje){
      const a = st.analizuje;
      btn.disabled = true;
      btn.innerHTML = `<span class="spin"></span>analizuję ${a.i}/${a.n}${a.bledy.length ? ` · ${a.bledy.length} nie wyszło` : ''}`;
    }else{
      btn.disabled = !todo;
      btn.textContent = todo ? `Analizuj resztę (${fmtLicz(todo)})` : 'Wszystko przeanalizowane';
    }
    $('#bibDodaj', host).disabled = !!st.dodaje;
  }
  function odswiezTytul(){
    if(S.biezacy() === 'biblioteka') S.tytul(tytul());
  }
  function tytul(){
    const m = st.meta || S.stan.tracksMeta || {};
    if(!m.count && !st.tracks.length) return 'Biblioteka';
    const n = m.count ?? st.tracks.length;
    return `${skrocDom(m.folder || S.stan.folder)} · ${fmtLicz(n)} ${lm(n, ['plik','pliki','plików'])} · ${fmtMB((m.total_mb || 0) * 1e6)}`;
  }

  // ---------- chipy filtrów ----------
  function wypelnijChipy(){
    const host = st.host;
    const formaty = [...new Set(st.tracks.map(t => (t.ext || '').toLowerCase()).filter(Boolean))].sort();
    const klucze = [...new Set(st.tracks.map(t => t.camelot).filter(Boolean))].sort((a, b) => camRanga(a) - camRanga(b));
    const sf = $('#fFormat', host), sk = $('#fKlucz', host);
    sf.innerHTML = '<option value="">format: każdy</option>' + formaty.map(f => `<option value="${esc(f)}">${esc(f.toUpperCase())}</option>`).join('');
    sk.innerHTML = '<option value="">klucz: każdy</option>' + klucze.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
    sf.value = st.filtr.format; sk.value = st.filtr.klucz;
    odswiezChipy();
  }
  function odswiezChipy(){
    const host = st.host, f = st.filtr;
    const sf = $('#fFormat', host), sj = $('#fJakosc', host), sk = $('#fKlucz', host);
    const txt = sel => { const o = sel.options[sel.selectedIndex]; return o ? o.textContent : ''; };
    $('#chipFormat .chipTxt', host).textContent = f.format ? 'format: ' + f.format.toUpperCase() : 'format: każdy';
    $('#chipJakosc .chipTxt', host).textContent = f.jakosc ? 'jakość: ' + txt(sj).replace(/^[✓?✕—] /, '') : 'jakość: każda';
    $('#chipKlucz .chipTxt', host).textContent = f.klucz ? 'klucz: ' + f.klucz : 'klucz: każdy';
    const bpm = f.bpmOd != null || f.bpmDo != null;
    $('#chipBpm .chipTxt', host).textContent = bpm ? `BPM ${f.bpmOd ?? '…'}–${f.bpmDo ?? '…'}` : 'BPM: każde';
    $('#chipFormat', host).classList.toggle('on', !!f.format);
    $('#chipJakosc', host).classList.toggle('on', !!f.jakosc);
    $('#chipKlucz', host).classList.toggle('on', !!f.klucz);
    $('#chipBpm', host).classList.toggle('on', bpm);
    sf.value = f.format; sj.value = f.jakosc; sk.value = f.klucz;
  }
  function zamknijPopovery(poza){
    $$('#ekran-biblioteka .popover').forEach(p => { if(p !== poza) p.remove(); });
    $$('#ekran-biblioteka .chip.otwarty').forEach(c => c.classList.remove('otwarty'));
  }
  function popoverBpm(chip){
    if(chip.querySelector('.popover')){ zamknijPopovery(); return; }
    zamknijPopovery();
    const f = st.filtr;
    const p = document.createElement('div'); p.className = 'popover';
    p.innerHTML = `<span class="etyk">BPM</span>
      <input class="pole" id="fBpmOd" type="number" inputmode="numeric" placeholder="od" value="${f.bpmOd ?? ''}">
      <span style="color:#5e5650">–</span>
      <input class="pole" id="fBpmDo" type="number" inputmode="numeric" placeholder="do" value="${f.bpmDo ?? ''}">
      <button class="btn mini cichy" id="fBpmWyczysc" type="button">wyczyść</button>`;
    chip.appendChild(p); chip.classList.add('otwarty');
    const licz = el => { const v = el.value.trim(); return v === '' ? null : Number(v); };
    const odswiez = () => { f.bpmOd = licz($('#fBpmOd', p)); f.bpmDo = licz($('#fBpmDo', p)); odswiezChipy(); rysujTabele(); };
    $('#fBpmOd', p).addEventListener('input', odswiez); $('#fBpmDo', p).addEventListener('input', odswiez);
    $('#fBpmWyczysc', p).onclick = () => { f.bpmOd = f.bpmDo = null; odswiezChipy(); rysujTabele(); zamknijPopovery(); };
    p.addEventListener('keydown', e => { if(e.key === 'Enter') zamknijPopovery(); });
    $('#fBpmOd', p).focus();
  }
  function popoverDodaj(btnBox){
    if(btnBox.querySelector('.popover')){ zamknijPopovery(); return; }
    zamknijPopovery();
    const p = document.createElement('div'); p.className = 'popover'; p.style.flexDirection = 'column'; p.style.alignItems = 'stretch'; p.style.gap = '10px';
    p.innerHTML = `<button class="btn sr" id="dodajZKomputera" type="button" style="text-align:left">Wybierz pliki z komputera…</button>
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#5e5650"><span style="flex:1;height:1px;background:#2a2522"></span>albo ścieżka do pliku lub folderu<span style="flex:1;height:1px;background:#2a2522"></span></div>
      <div style="display:flex;gap:8px"><input class="pole szeroki" id="dodajSciezka" placeholder="/Volumes/USB/nowe utwory"><button class="btn mini acc" id="dodajSciezkaBtn" type="button">Dodaj</button></div>
      <div style="font-size:12px;color:#5e5650">pliki są kopiowane do biblioteki — oryginały zostają na miejscu</div>`;
    btnBox.appendChild(p); btnBox.classList.add('otwarty');
    $('#dodajZKomputera', p).onclick = () => { zamknijPopovery(); $('#dodajPlik', st.host).click(); };
    const ze = async () => {
      const sciezka = $('#dodajSciezka', p).value.trim(); if(!sciezka) return;
      zamknijPopovery();
      st.dodaje = `kopiuję z ${sciezka}…`; odswiezNaglowek();
      try{
        const d = await api('/api/tracks/dodaj-sciezke', {method:'POST', body:{path:sciezka}});
        S.toast(d.count ? `dodano ${d.count} ${lm(d.count, ['utwór','utwory','utworów'])}` : 'nic nie dodano — te pliki już są w bibliotece', d.count ? 'ok' : 'warn');
      }catch(e){}
      st.dodaje = null; S.uniewaznTracks(); await load(st.host);
    };
    $('#dodajSciezkaBtn', p).onclick = ze;
    $('#dodajSciezka', p).addEventListener('keydown', e => { if(e.key === 'Enter') ze(); });
    $('#dodajSciezka', p).focus();
  }

  // ---------- zaznaczanie ----------
  function ogloszWybor(){
    const podpis = st.wybrane.size + '|' + [...st.wybrane].join('\n');
    if(podpis === st.wyborPodpis) return;
    st.wyborPodpis = podpis;
    document.dispatchEvent(new CustomEvent('selekta:wybor', {detail:{wybrane:[...st.wybrane]}}));
  }
  function odswiezWybor(){
    ogloszWybor();
    const host = st.host; if(!host) return;
    const n = st.wybrane.size, w = st.widoczne.length;
    const wszystkie = $('#chkAll', host);
    const wid = st.widoczne.filter(t => st.wybrane.has(klucz(t))).length;
    wszystkie.classList.toggle('on', w > 0 && wid === w);
    wszystkie.classList.toggle('pol', wid > 0 && wid < w);
    let pasek = $('#bibPasekAkcji', host);
    if(!n){ if(pasek) pasek.remove(); return; }
    if(!pasek){
      pasek = document.createElement('div'); pasek.id = 'bibPasekAkcji'; pasek.className = 'pasekAkcji';
      pasek.innerHTML = `<span class="licz" id="pasekLicz"></span>
        <input class="pole" id="nazwaPlaylisty" placeholder="nazwa nowej playlisty">
        <button class="btn sr acc" id="zrobPlayliste" type="button">Utwórz playlistę</button>
        <button class="btn sr" id="analizujZazn" type="button">Analizuj zaznaczone</button>
        <button class="btn sr goly zly" id="usunZazn" type="button">Usuń do kosza</button>
        <button class="btn sr goly" id="wyczyscWybor" type="button" title="wyczyść zaznaczenie">✕</button>`;
      $('#bibTabela', host).appendChild(pasek);
    }
    $('#pasekLicz', pasek).textContent = `${n} ${lm(n, ['zaznaczony','zaznaczone','zaznaczonych'])}`;
    const usun = $('#usunZazn', pasek);
    if(!usun.dataset.potwierdz){ usun.textContent = 'Usuń do kosza'; }
  }
  function ustawZazn(file, on){ on ? st.wybrane.add(file) : st.wybrane.delete(file); }
  function przelaczWiersz(el, t, shift){
    const i = Number(el.dataset.i);
    if(shift && st.ostatniZazn != null){
      const j = st.widoczne.findIndex(x => klucz(x) === st.ostatniZazn);
      if(j >= 0){
        const [a, b] = i < j ? [i, j] : [j, i];
        for(let k = a; k <= b; k++) ustawZazn(klucz(st.widoczne[k]), true);
        $$('.w', $('#bibLista', st.host)).forEach(w => { const n = Number(w.dataset.i); if(n >= a && n <= b){ w.classList.add('zazn'); w.querySelector('.chk').classList.add('on'); } });
        st.ostatniZazn = klucz(t); odswiezWybor(); return;
      }
    }
    const on = !st.wybrane.has(klucz(t));
    ustawZazn(klucz(t), on);
    el.classList.toggle('zazn', on); el.querySelector('.chk').classList.toggle('on', on);
    st.ostatniZazn = klucz(t);
    odswiezWybor();
  }
  function wyczyscWybor(){ st.wybrane.clear(); $$('.w.zazn', st.host).forEach(w => { w.classList.remove('zazn'); w.querySelector('.chk').classList.remove('on'); }); odswiezWybor(); }

  // ---------- odtwarzacz: podświetlanie wiersza ----------
  function grajUtwor(t){
    const k = klucz(t), d = SZCZ.file === k ? SZCZ.dane : null;
    S.player.graj({file:k, title:t.title, artist:t.artist, bpm:t.bpm, camelot:t.camelot, duration:t.duration,
                   lufs:d && d.loudness ? d.loudness.integrated_lufs : undefined,
                   intro:d && d.cues ? d.cues.intro_end_s : undefined,
                   drop:d && d.cues ? d.cues.drop_s : undefined});
  }
  function odswiezPrzyciskiGrania(){
    const host = st.host; if(!host) return;
    $$('.graj', $('#bibLista', host)).forEach(b => {
      const w = b.closest('.w'); const t = st.widoczne[Number(w.dataset.i)]; if(!t) return;
      const gra = S.player.gra(klucz(t));
      b.classList.toggle('gra', gra); b.textContent = gra ? '❚❚' : '▶'; b.title = gra ? 'pauza' : 'odsłuchaj';
    });
    const p = $('#szczPlay'); if(p && SZCZ.file){ const gra = S.player.gra(SZCZ.file); p.textContent = gra ? '❚❚' : '▶'; p.title = gra ? 'pauza' : 'odsłuchaj'; }
  }
  document.addEventListener('selekta:player', odswiezPrzyciskiGrania);

  // ---------- analiza (jeden plik naraz — tak jak stary UI) ----------
  async function analizuj(lista, opis){
    if(st.analizuje){ S.toast('analiza już trwa — poczekaj, aż skończy', 'warn'); return; }
    if(!lista.length){ S.toast('nie ma czego analizować', 'info'); return; }
    st.analizuje = {i:0, n:lista.length, bledy:[]}; odswiezNaglowek();
    let udane = 0;
    for(let i = 0; i < lista.length; i++){
      const t = lista[i];
      try{
        const r = await api('/api/analyze?file=' + encF(klucz(t)), {method:'POST', cicho:true});
        // wiersze są filtrowane i sortowane — szukamy po kluczu, nie po indeksie
        const idx = st.tracks.findIndex(x => klucz(x) === klucz(r));
        if(idx >= 0) st.tracks[idx] = r;
        udane++;
      }catch(e){ st.analizuje.bledy.push({plik:t.file, powod:e.message}); }
      st.analizuje.i = i + 1;
      if(i % 5 === 4) rysujTabele(); else odswiezNaglowek();
    }
    const bledy = st.analizuje.bledy; st.analizuje = null;
    rysujTabele(); wypelnijChipy();
    if(bledy.length) S.toast(`${opis}: ${udane} gotowych, ${bledy.length} nie wyszło (${bledy.slice(0, 2).map(b => b.plik).join(', ')}${bledy.length > 2 ? '…' : ''})`, 'warn', 8000);
    else S.toast(`${opis}: przeanalizowano ${udane} ${lm(udane, ['utwór','utwory','utworów'])}`, 'ok');
    if(SZCZ.file && lista.some(t => klucz(t) === SZCZ.file)) S.otworzSzczegoly(SZCZ.file);
  }

  // ---------- dodawanie plików ----------
  async function wgrajPliki(pliki){
    pliki = [...pliki].filter(p => AUDIO_ACCEPT.split(',').some(e => p.name.toLowerCase().endsWith(e)));
    if(!pliki.length){ S.toast('to nie są pliki audio', 'warn'); return; }
    let dodane = 0;
    for(let i = 0; i < pliki.length; i++){
      st.dodaje = `dodaję ${i + 1}/${pliki.length}: ${pliki[i].name}`; odswiezNaglowek();
      const fd = new FormData(); fd.append('file', pliki[i]);
      try{ await api('/api/tracks/dodaj', {method:'POST', formData:fd}); dodane++; }catch(e){}
    }
    st.dodaje = null;
    S.toast(dodane ? `dodano ${dodane} z ${pliki.length}` : 'nic nie dodano', dodane ? 'ok' : 'warn');
    S.uniewaznTracks(); await load(st.host);
  }

  // ---------- kosz ----------
  function toastCofnij(msg, wKoszu){
    const el = S.toast(msg, 'info', 12000);
    const b = document.createElement('button'); b.className = 'btn mini obrys'; b.style.marginLeft = '10px'; b.textContent = 'cofnij';
    b.onclick = async () => {
      b.disabled = true;
      let ok = 0;
      for(const w of wKoszu){ try{ await api('/api/tracks/przywroc', {method:'POST', body:{w_koszu:w}}); ok++; }catch(e){} }
      el.remove();
      if(ok) S.toast(ok === 1 ? 'przywrócono' : `przywrócono ${ok}`, 'ok');
      S.uniewaznTracks(); await load(st.host);
    };
    el.appendChild(b);
  }
  async function usunDoKosza(pliki){
    const wKoszu = [];
    for(const f of pliki){
      try{ const j = await api('/api/tracks/usun', {method:'POST', body:{file:f}}); wKoszu.push(j.w_koszu); st.wybrane.delete(f); }catch(e){}
    }
    if(wKoszu.length){
      const n = wKoszu.length;
      toastCofnij(n === 1 ? `${S.nazwaPliku(pliki[0])} w koszu` : `${n} ${lm(n, ['utwór','utwory','utworów'])} w koszu`, wKoszu);
    }
    S.uniewaznTracks(); await load(st.host);
  }

  // ============================================================
  // RENDER ekranu
  // ============================================================
  function render(host){
    st.host = host;
    host.innerHTML = `<style>${STYLE}</style>
      <div class="naglowek">
        <div><h1>Biblioteka</h1><div class="sub" id="bibSub">wczytuję…</div></div>
        <div class="akcje">
          <span style="position:relative" id="bibDodajBox"><button class="btn" id="bibDodaj" type="button">+ Dodaj utwory</button></span>
          <button class="btn acc" id="bibAnalizuj" type="button" disabled>Analizuj resztę</button>
        </div>
      </div>
      <input type="file" id="dodajPlik" accept="${AUDIO_ACCEPT}" multiple class="hide">
      <div class="pasekF">
        <label class="szukaj"><span class="mono" style="font-size:12px">⌕</span><input id="fSzukaj" placeholder="szukaj: artysta, tytuł, nazwa pliku…" autocomplete="off" spellcheck="false"></label>
        <label class="chip" id="chipFormat"><span class="chipTxt">format: każdy</span><select id="fFormat"></select></label>
        <label class="chip" id="chipJakosc"><span class="chipTxt">jakość: każda</span><select id="fJakosc">
          <option value="">jakość: każda</option>
          <option value="obejrzec">do obejrzenia</option>
          <option value="ok">✓ dobra</option>
          <option value="warn">? wątpliwa</option>
          <option value="bad">✕ zła</option>
          <option value="brak">— nieanalizowane</option></select></label>
        <label class="chip" id="chipKlucz"><span class="chipTxt">klucz: każdy</span><select id="fKlucz"></select></label>
        <span class="chip mono" id="chipBpm"><span class="chipTxt">BPM: każde</span></span>
        <button class="btn goly mini hide" id="bibWyczysc" type="button" title="wyczyść filtry">wyczyść ✕</button>
        <span class="mono" id="bibLicznik" style="font-size:11px;color:#5e5650;white-space:nowrap"></span>
      </div>
      <div class="tabela" id="bibTabela">
        <div class="kol" id="bibKol">
          <span class="chk" id="chkAll" title="zaznacz widoczne"></span><span></span>
          <span class="sort" data-k="title" data-n="UTWÓR">UTWÓR</span>
          <span class="sort" data-k="ext" data-n="FORMAT">FORMAT</span>
          <span class="sort" data-k="quality" data-n="JAKOŚĆ">JAKOŚĆ</span>
          <span class="sort" data-k="bpm" data-n="BPM">BPM</span>
          <span class="sort" data-k="camelot" data-n="KLUCZ">KLUCZ</span>
          <span class="sort" data-k="duration" data-n="CZAS">CZAS</span>
          <span></span>
        </div>
        <div class="lista" id="bibLista"><div class="pusto"><span class="spin"></span> wczytuję bibliotekę…</div></div>
      </div>`;

    // --- filtry ---
    let szukajT = null;
    $('#fSzukaj', host).addEventListener('input', e => {
      clearTimeout(szukajT);
      szukajT = setTimeout(() => { st.filtr.szukaj = e.target.value.trim().toLowerCase(); rysujTabele(); }, 120);
    });
    $('#fFormat', host).addEventListener('change', e => { st.filtr.format = e.target.value; odswiezChipy(); rysujTabele(); });
    $('#fJakosc', host).addEventListener('change', e => { st.filtr.jakosc = e.target.value; odswiezChipy(); rysujTabele(); });
    $('#fKlucz', host).addEventListener('change', e => { st.filtr.klucz = e.target.value; odswiezChipy(); rysujTabele(); });
    $('#chipBpm', host).addEventListener('click', e => { if(e.target.closest('.popover')) return; popoverBpm($('#chipBpm', host)); });
    $('#bibWyczysc', host).onclick = () => {
      Object.assign(st.filtr, {szukaj:'', format:'', jakosc:'', klucz:'', bpmOd:null, bpmDo:null});
      $('#fSzukaj', host).value = ''; odswiezChipy(); rysujTabele();
    };
    document.addEventListener('click', e => { if(!e.target.closest('.popover') && !e.target.closest('#chipBpm') && !e.target.closest('#bibDodajBox')) zamknijPopovery(); });
    document.addEventListener('keydown', e => { if(e.key === 'Escape') zamknijPopovery(); });

    // --- sortowanie ---
    on($('#bibKol', host), 'click', '.sort', (e, el) => {
      const k = el.dataset.k;
      st.sort = st.sort.kolumna === k ? {kolumna:k, kierunek:-st.sort.kierunek} : {kolumna:k, kierunek:1};
      rysujTabele();
    });
    $('#chkAll', host).onclick = () => {
      const wid = st.widoczne.filter(t => st.wybrane.has(klucz(t))).length;
      if(wid === st.widoczne.length && wid > 0) st.widoczne.forEach(t => st.wybrane.delete(klucz(t)));
      else st.widoczne.forEach(t => st.wybrane.add(klucz(t)));
      $$('.w', $('#bibLista', host)).forEach(w => { const t = st.widoczne[Number(w.dataset.i)]; const on = !!t && st.wybrane.has(klucz(t)); w.classList.toggle('zazn', on); w.querySelector('.chk').classList.toggle('on', on); });
      odswiezWybor();
    };

    // --- wiersze: zaznaczanie, odsłuch, szczegóły ---
    on($('#bibLista', host), 'click', '.w', (e, el) => {
      const t = st.widoczne[Number(el.dataset.i)]; if(!t) return;
      const akcja = e.target.closest('[data-akcja]');
      if(akcja && akcja.dataset.akcja === 'zazn'){ przelaczWiersz(el, t, e.shiftKey); return; }
      if(akcja && akcja.dataset.akcja === 'graj'){ grajUtwor(t); return; }
      if(e.shiftKey || e.metaKey || e.ctrlKey){ przelaczWiersz(el, t, e.shiftKey); return; }
      S.otworzSzczegoly(klucz(t));
    });
    // okładka, której nie da się odczytać → placeholder (error nie bąbelkuje, więc capture)
    host.addEventListener('error', e => {
      const img = e.target; if(!(img instanceof HTMLImageElement) || !img.classList.contains('okl')) return;
      const s = document.createElement('span'); s.className = 'okl pusta'; img.replaceWith(s);
    }, true);

    // --- pasek akcji zaznaczenia (delegacja — pasek powstaje dynamicznie) ---
    on($('#bibTabela', host), 'click', '#zrobPlayliste', async (e, btn) => {
      const nazwa = $('#nazwaPlaylisty', host).value.trim();
      if(!nazwa){ S.toast('podaj nazwę playlisty', 'warn'); $('#nazwaPlaylisty', host).focus(); return; }
      btn.disabled = true; btn.innerHTML = '<span class="spin"></span>tworzę…';
      try{
        const d = await api('/api/playlist/from-selection', {method:'POST', body:{name:nazwa, files:[...st.wybrane]}});
        S.toast(`playlista „${nazwa}” — ${d.count} ${lm(d.count, ['utwór','utwory','utworów'])}${d.pominietych ? `, ${d.pominietych} pominiętych` : ''}${d.folder ? ` · ${skrocDom(d.folder)}` : ''}`, 'ok', 7000);
        wyczyscWybor();
      }catch(err){ btn.disabled = false; btn.textContent = 'Utwórz playlistę'; }
    });
    on($('#bibTabela', host), 'keydown', '#nazwaPlaylisty', e => { if(e.key === 'Enter') $('#zrobPlayliste', host).click(); });
    on($('#bibTabela', host), 'click', '#analizujZazn', () => {
      const lista = st.tracks.filter(t => st.wybrane.has(klucz(t)) && !t.uszkodzony);
      analizuj(lista, 'zaznaczone');
    });
    on($('#bibTabela', host), 'click', '#wyczyscWybor', wyczyscWybor);
    on($('#bibTabela', host), 'click', '#usunZazn', async (e, btn) => {
      // dwa kliknięcia zamiast natywnego okienka: pierwsze uzbraja, drugie usuwa
      if(!btn.dataset.potwierdz){
        btn.dataset.potwierdz = '1'; btn.style.color = K.bad;
        btn.textContent = `Na pewno? Usuń ${st.wybrane.size} do kosza`;
        setTimeout(() => { delete btn.dataset.potwierdz; btn.style.color = ''; if(btn.isConnected) btn.textContent = 'Usuń do kosza'; }, 4000);
        return;
      }
      delete btn.dataset.potwierdz; btn.disabled = true; btn.innerHTML = '<span class="spin"></span>przenoszę…';
      await usunDoKosza([...st.wybrane]);
    });

    // --- nagłówek: dodawanie i analiza ---
    $('#bibDodaj', host).onclick = () => popoverDodaj($('#bibDodajBox', host));
    $('#dodajPlik', host).onchange = async e => { const pliki = [...e.target.files]; e.target.value = ''; if(pliki.length) await wgrajPliki(pliki); };
    $('#bibAnalizuj', host).onclick = () => analizuj(st.tracks.filter(nieanalizowany), 'reszta biblioteki');

    // --- upuszczanie plików na tabelę ---
    const tab = $('#bibTabela', host);
    ['dragenter', 'dragover'].forEach(ev => tab.addEventListener(ev, e => { if([...e.dataTransfer.types].includes('Files')){ e.preventDefault(); tab.classList.add('upusc'); } }));
    tab.addEventListener('dragleave', e => { if(!tab.contains(e.relatedTarget)) tab.classList.remove('upusc'); });
    tab.addEventListener('drop', e => { e.preventDefault(); tab.classList.remove('upusc'); if(e.dataTransfer.files.length) wgrajPliki(e.dataTransfer.files); });
  }

  async function load(host){
    st.host = host;
    if(st.analizuje){ rysujTabele(); return; }   // analiza trwa — nie nadpisuj świeżych wyników starym cache
    try{
      st.tracks = await S.tracks();
      st.meta = S.stan.tracksMeta || {};
    }catch(e){
      $('#bibLista', host).innerHTML = `<div class="pusto">nie udało się wczytać biblioteki: ${esc(e.message)}</div>`;
      return;
    }
    const istnieje = new Set(st.tracks.map(klucz));
    for(const f of [...st.wybrane]) if(!istnieje.has(f)) st.wybrane.delete(f);   // w miejscu — S.stan.wybrane to ten sam Set
    wypelnijChipy();
    rysujTabele();
    odswiezTytul();
  }

  S.ekran('biblioteka', {tytul, render, load});

  // ============================================================
  // ARKUSZ „Szczegóły utworu" (3c)
  // ============================================================
  const SZCZ = {file:null, dane:null, fala:null, tempo:null, edytor:false,
                kotwica:0, srodek:0, okno:4.0, bpm:0, battito:1, seq:0};

  function slupkiHTML(fala, cues){
    const N = 120, sz = (fala && fala.szczyt) || [], n = sz.length, czas = fala ? fala.czas_s : 0;
    const intro = cues && cues.intro_end_s, outro = cues && cues.outro_start_s;
    const out = [];
    for(let i = 0; i < N; i++){
      let h = 6;
      if(n){
        const a = Math.floor(i * n / N), b = Math.max(a + 1, Math.floor((i + 1) * n / N));
        let m = 0; for(let k = a; k < b && k < n; k++) m = Math.max(m, sz[k]);
        h = Math.max(6, Math.round(m * 100));
      }
      const t = (i + 0.5) / N * czas;
      const bg = !n ? '#1e1a17' : (intro != null && t < intro ? '#ff6a3d' : (outro != null && t >= outro ? '#5e5650' : '#f2ece6'));
      out.push(`<span style="height:${h}%;background:${bg}"></span>`);
    }
    return out.join('');
  }
  function etykietyCue(c){
    if(!c) return `<span>INTRO —</span><span style="color:#ff6a3d">DROP —</span><span>OUTRO —</span>`;
    return `<span>INTRO ${fmtTime(c.intro_end_s)}</span><span style="color:#ff6a3d">DROP ${c.drop_s != null ? fmtTime(c.drop_s) : '—'}</span><span>OUTRO ${fmtTime(c.outro_start_s)}</span>`;
  }

  function kafleHTML(d){
    const h = d.harmonic || {}, q = d.quality_full || {}, l = d.loudness || {}, ig = d.integrity || {};
    const bpm = (SZCZ.fala && SZCZ.fala.bpm) || h.bpm || d.bpm;
    const cam = h.camelot || d.camelot;
    const lossless = ['flac', 'wav', 'aiff', 'aif'].includes((d.ext || '').toLowerCase());
    const jak = {ok:[lossless ? '✓ prawdziwy lossless' : '✓ dobra jakość', K.ok], warn:['? wątpliwa jakość', K.warn], bad:['✕ zła jakość', K.bad]}[q.grade] || ['— nieanalizowane', K.dim];
    if(d.uszkodzony) { jak[0] = '⚠ uszkodzony plik'; jak[1] = K.bad; }
    const pasmo = q.cutoff_hz ? `pasmo do ${nf(q.cutoff_hz / 1000, 1)} kHz` : '';
    const integ = ig.ok == null ? '' : (ig.ok ? 'integralność OK' : `<span style="color:${K.bad}">integralność: ${esc(ig.detail || 'błąd')}</span>`);
    const jakPod = [pasmo, integ, q.verdict ? esc(q.verdict) : ''].filter(Boolean).join(' · ');
    return `
      <div class="kafel3"><div class="et">TEMPO</div><div class="duza">${fmtBpm(bpm)}<small>BPM</small></div><div class="pod" id="szczTempoPod">${tempoPod()}</div></div>
      <div class="kafel3"><div class="et">TONACJA</div>
        <div style="display:flex;align-items:center;gap:10px;margin-top:10px;min-width:0">${cam ? `<span class="cam2" style="background:${CAM[cam] || K.dim}">${esc(cam)}</span>` : `<span class="cam2" style="background:#1e1a17;color:#5e5650">—</span>`}<span style="font-size:20px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(h.key || d.key || '—')}</span></div>
        <div class="pod" style="margin-top:8px">${h.confidence_key != null ? `pewność ${nf(h.confidence_key, 2)}` : '—'}${h.confidence_bpm != null ? ` · BPM ${nf(h.confidence_bpm, 2)}` : ''}</div></div>
      <div class="kafel3"><div class="et">GŁOŚNOŚĆ</div><div class="duza">${nf(l.integrated_lufs, 1)}<small>LUFS</small></div><div class="pod">peak ${nfZnak(l.true_peak_dbtp, 1)} dBTP · RG ${nfZnak(l.gain_db, 1)} dB${l.loudness_range_lu != null ? ` · LRA ${nf(l.loudness_range_lu, 1)} LU` : ''}</div></div>
      <div class="kafel3" style="border-color:${jak[1]}"><div class="et">JAKOŚĆ</div><div style="font-size:20px;font-weight:700;color:${jak[1]};margin-top:12px;line-height:1.15">${jak[0]}</div><div class="pod">${jakPod || '—'}</div></div>`;
  }
  function tempoPod(){
    const t = SZCZ.tempo, f = SZCZ.fala;
    const siatka = f && f.first_beat_s != null ? `siatka od ${fmtCs(f.first_beat_s)}${f.reczna_korekta ? ' (ręcznie)' : ''}` : '';
    if(t === undefined) return [`<span class="spin" style="width:9px;height:9px"></span> sprawdzam stabilność`, siatka].filter(Boolean).join(' · ');
    if(!t) return siatka || '—';
    if(!t.stabilne) return `<span style="color:${K.warn}">tempo zmienne</span>${siatka ? ' · ' + siatka : ''}`;
    if(t.bpm_nietrafione && t.bpm_poprawione) return `<span style="color:${K.warn}">stałe, lepiej ${nf(t.bpm_poprawione, 2)} BPM</span>${siatka ? ' · ' + siatka : ''}`;
    return `stabilne${siatka ? ' · ' + siatka : ''}`;
  }
  function cueHTML(d){
    const c = d.cues, bpm = (SZCZ.fala && SZCZ.fala.bpm) || (d.harmonic && d.harmonic.bpm) || d.bpm;
    const pierwszy = SZCZ.fala && SZCZ.fala.first_beat_s != null ? SZCZ.fala.first_beat_s : (c && c.first_beat_s);
    if(!c) return ['INTRO', 'PIERWSZE UDERZENIE', 'DROP', 'OUTRO'].map(k => `<div class="cue"><span class="k">${k}</span><span class="v">—</span><span class="d">brak analizy</span></div>`).join('');
    const takty = bpm && pierwszy != null && c.intro_end_s != null ? Math.max(0, Math.round((c.intro_end_s - pierwszy) / (240 / bpm))) : null;
    const naMiks = c.duration_s && c.outro_start_s != null ? Math.max(0, Math.round(c.duration_s - c.outro_start_s)) : null;
    return `
      <div class="cue"><span class="k">INTRO</span><span class="v">0:00 – ${fmtTime(c.intro_end_s)}</span><span class="d">${takty == null ? '—' : (takty === 0 ? 'nie wykryto intra' : `${takty} ${lm(takty, ['takt','takty','taktów'])}`)}</span></div>
      <div class="cue"><span class="k">PIERWSZE UDERZENIE</span><span class="v">${fmtCs(pierwszy)}</span><span class="d">${SZCZ.fala && SZCZ.fala.reczna_korekta ? 'siatka poprawiona ręcznie' : 'siatka od tego punktu'}</span></div>
      <div class="cue"><span class="k">DROP</span><span class="v">${c.drop_s != null ? fmtTime(c.drop_s) : '—'}</span><span class="d">${c.drop_s != null ? 'wejście basu' : 'nie wykryto'}</span></div>
      <div class="cue"><span class="k">OUTRO</span><span class="v">${fmtTime(c.outro_start_s)} – ${fmtTime(c.duration_s)}</span><span class="d">${naMiks != null ? `${naMiks} s na miks` : '—'}</span></div>`;
  }

  function otworzSzczegoly(plik){
    const seq = ++SZCZ.seq;
    const t = znajdz(plik) || {file:S.nazwaPliku(plik), rel:plik, title:S.nazwaPliku(plik).replace(/\.[^.]+$/, ''), artist:'', ext:(plik.split('.').pop() || '')};
    const file = klucz(t);
    const wczesniej = SZCZ.file === file ? SZCZ : null;
    Object.assign(SZCZ, {file, dane:null, fala:wczesniej ? wczesniej.fala : null, tempo:undefined, edytor:false, kotwica:0, srodek:0, bpm:0});
    const meta = [t.sr ? `${(t.sr / 1000).toFixed(1).replace('.', ',')} kHz` : '', t.bits ? `${t.bits}-bit` : '', t.size_mb ? fmtMB(t.size_mb * 1e6) : '', t.duration ? fmtTime(t.duration) : ''].filter(Boolean).join(' · ');
    const gra = S.player.gra(file);
    const body = S.arkusz(`<div class="szcz" style="display:flex;flex-direction:column;gap:24px">
      <div style="display:flex;align-items:flex-start;gap:22px">
        ${t.has_cover ? `<img class="okl okladka" id="szczOkladka" src="/api/cover?file=${encF(file)}" alt="" style="width:96px;height:96px;border-radius:12px;object-fit:cover;flex-shrink:0">` : `<span class="okl" style="width:96px;height:96px;border-radius:12px;background:repeating-linear-gradient(135deg,#221d1a 0 5px,#1a1613 5px 10px);flex-shrink:0"></span>`}
        <div style="flex:1;display:flex;flex-direction:column;gap:6px;min-width:0">
          <div style="display:flex;align-items:center;gap:10px">${fmtTag(t.ext)}<span style="font:500 11.5px var(--mono);color:#8f857c" id="szczMeta">${esc(meta)}</span></div>
          <div style="font-size:32px;font-weight:700;letter-spacing:-.02em;line-height:1.05;overflow:hidden;text-overflow:ellipsis">${esc(t.title)}</div>
          <div style="font-size:16px;color:#8f857c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(file)}">${esc(t.artist)}${t.artist ? ' · ' : ''}${esc(file)}</div>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <button class="play" id="szczPlay" type="button" title="${gra ? 'pauza' : 'odsłuchaj'}">${gra ? '❚❚' : '▶'}</button>
          <button class="zamknij" id="szczZamknij" type="button" title="zamknij (Esc)">✕</button>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="fala" id="szczFala">${slupkiHTML(SZCZ.fala, null)}</div>
        <div style="display:flex;justify-content:space-between;align-items:center;font:500 10.5px var(--mono);letter-spacing:.08em;color:#5e5650" id="szczEtykiety">${etykietyCue(null)}</div>
        <div style="display:flex;align-items:center;gap:14px;font:500 10.5px var(--mono);letter-spacing:.08em;color:#5e5650;margin-top:2px">
          <span id="siatkaStan"><span class="spin" style="width:9px;height:9px"></span> rysuję przebieg…</span>
          <button class="link" id="siatkaPrzelacz" type="button" style="margin-left:auto">POPRAW SIATKĘ ▾</button>
        </div>
        <div id="siatkaBox" class="hide"></div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px" id="szczKafle">
        ${['TEMPO','TONACJA','GŁOŚNOŚĆ','JAKOŚĆ'].map(k => `<div class="kafel3"><div class="et">${k}</div><div class="duza" style="color:#5e5650">…</div><div class="pod"><span class="spin" style="width:9px;height:9px"></span> liczę</div></div>`).join('')}
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px" id="szczCue">
        ${['INTRO','PIERWSZE UDERZENIE','DROP','OUTRO'].map(k => `<div class="cue"><span class="k">${k}</span><span class="v">…</span><span class="d">&nbsp;</span></div>`).join('')}
      </div>
      <div style="display:flex;gap:8px;align-items:center;border-top:1px solid #2a2522;padding-top:18px">
        <button class="akcja" id="szczFinder" type="button">Pokaż w Finderze</button>
        <button class="akcja" id="szczPrzelicz" type="button">Przelicz analizę</button>
        <button class="akcja" id="szczLepsza" type="button">Szukaj lepszej wersji</button>
        <button class="akcja zla" id="szczUsun" type="button">Usuń do kosza</button>
      </div>
      <div id="szczLepsze" class="hide"></div>
    </div>`, {szer:900});

    // --- przyciski nagłówka ---
    $('#szczZamknij', body).onclick = S.zamknijArkusz;
    $('#szczPlay', body).onclick = () => grajUtwor(znajdz(file) || t);
    $('#szczFinder', body).onclick = async (e) => {
      try{ const j = await api('/api/tracks/pokaz', {method:'POST', body:{file}}); if(j.ok === false) S.toast(j.message || j.path, 'warn'); }catch(err){}
    };
    $('#szczPrzelicz', body).onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true; b.innerHTML = '<span class="spin"></span> liczę…';
      try{
        const r = await api('/api/analyze?file=' + encF(file), {method:'POST'});
        const idx = st.tracks.findIndex(x => klucz(x) === klucz(r)); if(idx >= 0) st.tracks[idx] = r;
        rysujTabele(); wypelnijChipy();
        S.toast('analiza przeliczona (BPM, tonacja, jakość)', 'ok');
        otworzSzczegoly(file);
      }catch(err){ b.disabled = false; b.textContent = 'Przelicz analizę'; }
    };
    $('#szczLepsza', body).onclick = e => szukajLepszej(znajdz(file) || t, e.currentTarget);
    $('#szczUsun', body).onclick = async (e) => {
      const b = e.currentTarget;
      if(!b.dataset.potwierdz){ b.dataset.potwierdz = '1'; b.style.color = K.bad; b.textContent = 'Na pewno? Usuń do kosza'; setTimeout(() => { delete b.dataset.potwierdz; b.style.color = ''; if(b.isConnected) b.textContent = 'Usuń do kosza'; }, 4000); return; }
      b.disabled = true; S.zamknijArkusz(); await usunDoKosza([file]);
    };
    $('#siatkaPrzelacz', body).onclick = () => przelaczEdytor();
    body.addEventListener('error', e => { const img = e.target; if(img instanceof HTMLImageElement && img.id === 'szczOkladka'){ const s = document.createElement('span'); s.className = 'okl'; s.style.cssText = 'width:96px;height:96px;border-radius:12px;background:repeating-linear-gradient(135deg,#221d1a 0 5px,#1a1613 5px 10px);flex-shrink:0'; img.replaceWith(s); } }, true);

    // --- dane: szczegóły, przebieg, stabilność tempa (równolegle) ---
    (async () => {
      let d;
      try{ d = await api('/api/track?file=' + encF(file)); }
      catch(e){ if(seq !== SZCZ.seq) return; $('#szczKafle', body).innerHTML = `<div class="pusto" style="grid-column:1/5;color:${K.bad}">nie udało się policzyć szczegółów: ${esc(e.message)}</div>`; $('#szczCue', body).innerHTML = ''; return; }
      if(seq !== SZCZ.seq) return;
      SZCZ.dane = d;
      const idx = st.tracks.findIndex(x => klucz(x) === klucz(d));
      if(idx >= 0 && !st.tracks[idx].analyzed){ const {harmonic, quality_full, loudness, cues, integrity, ...row} = d; st.tracks[idx] = row; rysujTabele(); wypelnijChipy(); }
      $('#szczMeta', body).textContent = [d.sr ? `${(d.sr / 1000).toFixed(1).replace('.', ',')} kHz` : '', d.bits ? `${d.bits}-bit` : '', d.size_mb ? fmtMB(d.size_mb * 1e6) : '', d.duration ? fmtTime(d.duration) : ''].filter(Boolean).join(' · ');
      odswiezKafle();
    })();
    (async () => {
      try{
        const f = await api('/api/waveform?file=' + encF(file), {cicho:true});
        if(seq !== SZCZ.seq) return;
        if(!f.punkty) throw new Error('nie udało się odczytać dźwięku z tego pliku');
        SZCZ.fala = f; SZCZ.bpm = f.bpm || 0; SZCZ.kotwica = f.first_beat_s || 0; SZCZ.battito = f.battito || 1; SZCZ.srodek = SZCZ.kotwica;
        $('#szczFala', body).innerHTML = slupkiHTML(f, {intro_end_s:f.cues && f.cues.intro, outro_start_s:f.cues && f.cues.outro});
        $('#szczEtykiety', body).innerHTML = etykietyCue({intro_end_s:f.cues && f.cues.intro, drop_s:f.cues && f.cues.drop, outro_start_s:f.cues && f.cues.outro});
        siatkaStan(); odswiezKafle();
      }catch(e){ if(seq !== SZCZ.seq) return; SZCZ.fala = null; const s = $('#siatkaStan', body); if(s){ s.style.color = K.bad; s.textContent = '✗ ' + e.message; } $('#siatkaPrzelacz', body).disabled = true; }
    })();
    (async () => {
      try{ const r = await api('/api/tempo', {method:'POST', body:{file}, cicho:true}); if(seq !== SZCZ.seq) return; SZCZ.tempo = (r.utwory && r.utwory[0]) || null; }
      catch(e){ if(seq !== SZCZ.seq) return; SZCZ.tempo = null; }
      odswiezKafle(); odswiezTempoInfo();
    })();
  }
  S.otworzSzczegoly = otworzSzczegoly;

  function odswiezKafle(){
    const d = SZCZ.dane; if(!d) { const p = $('#szczTempoPod'); if(p) p.innerHTML = tempoPod(); return; }
    const k = $('#szczKafle'), c = $('#szczCue'); if(!k || !c) return;
    k.innerHTML = kafleHTML(d); c.innerHTML = cueHTML(d);
  }
  function siatkaStan(msg, kolor){
    const s = $('#siatkaStan'); if(!s) return;
    s.style.color = kolor || '';
    if(msg){ s.innerHTML = msg; return; }
    const f = SZCZ.fala; if(!f) return;
    const pewn = f.pewnosc_siatki != null && !f.reczna_korekta ? ` · <span style="color:${f.pewnosc_siatki >= 0.25 ? K.ok : K.warn}">${f.pewnosc_siatki >= 0.25 ? 'NA STOPIE' : 'STOPA NIEWYRAŹNA — SPRAWDŹ UCHEM'}</span>` : '';
    s.innerHTML = `SIATKA · KOTWICA ${esc(fmtCs(SZCZ.kotwica))} = BIT ${SZCZ.battito}/4${SZCZ.bpm ? ` · ${esc(fmtBpm(SZCZ.bpm))} BPM` : ''} · ${f.reczna_korekta ? `<span style="color:${K.acc}">POPRAWIONA RĘCZNIE</span>` : 'WYLICZONA'}${pewn}`;
  }

  // ---------- edytor siatki: dwa canvasy, kotwica, zapis ----------
  function przelaczEdytor(){
    const box = $('#siatkaBox'), btn = $('#siatkaPrzelacz'); if(!box) return;
    SZCZ.edytor = !SZCZ.edytor;
    box.classList.toggle('hide', !SZCZ.edytor);
    btn.textContent = SZCZ.edytor ? 'ZWIŃ ▴' : 'POPRAW SIATKĘ ▾';
    btn.classList.toggle('on', SZCZ.edytor);
    if(SZCZ.edytor && !box.innerHTML){
      box.innerHTML = `<div style="background:#0f0d0c;border:1px solid #2a2522;border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:10px;margin-top:6px">
        <div style="display:flex;align-items:center;gap:10px"><span class="etyk">SIATKA BEATÓW</span><span style="font-size:12px;color:#8f857c">rekordbox dostanie tę kotwicę i to BPM — poprawiaj tylko, gdy wyliczona się rozjeżdża</span></div>
        <canvas id="falaCala" height="56"></canvas>
        <div style="font-size:11.5px;color:#5e5650;margin-top:-4px">cały utwór — kliknij albo przeciągnij, żeby przybliżyć to miejsce</div>
        <canvas id="falaZoom" height="96"></canvas>
        <div style="font-size:11.5px;color:#5e5650;margin-top:-4px">powiększenie — kliknij dokładnie na uderzeniu albo przeciągnij kotwicę; jasne kreski to jedynki taktów, ciemniejsze to bity. Przyciski „o bit ±1” przesuwają też numer bitu kotwicy</div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <span class="etyk">PRZESUŃ</span>
          <span class="seg mono ciemny"><button type="button" data-krok="-0.05">−50 ms</button><button type="button" data-krok="-0.005">−5 ms</button><button type="button" data-krok="0.005">+5 ms</button><button type="button" data-krok="0.05">+50 ms</button></span>
          <span class="etyk" style="margin-left:6px">O BIT</span>
          <span class="seg mono ciemny"><button type="button" data-bit="-1">−1</button><button type="button" data-bit="-0.5">−½</button><button type="button" data-bit="0.5">+½</button><button type="button" data-bit="1">+1</button></span>
          <span style="margin-left:auto;display:flex;gap:8px"><button class="btn mini acc" id="siatkaZapisz" type="button">Zapisz siatkę</button><button class="btn mini" id="siatkaReset" type="button">Przywróć wyliczoną</button></span>
        </div>
        <div id="tempoInfo" style="border-top:1px solid #1d1917;padding-top:10px;display:flex;align-items:center;gap:12px;font-size:12.5px;color:#8f857c;line-height:1.45"></div>
      </div>`;
      wireFala(box);
      odswiezTempoInfo();
    }
    if(SZCZ.edytor) requestAnimationFrame(przerysujFale);
  }
  function _rysujObwiednie(cv, szczyt, rms, od, do_){
    // bufor w pikselach URZĄDZENIA (Retina 2x), rysowanie w pikselach CSS
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || cv.parentElement.clientWidth || 800;
    const h = parseInt(cv.getAttribute('height'), 10) || 72;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.height = h + 'px';
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const n = szczyt.length, sr = n / SZCZ.fala.czas_s;
    const i0 = Math.max(0, Math.floor(od * sr)), i1 = Math.min(n, Math.ceil(do_ * sr));
    const ile = Math.max(1, i1 - i0), srodekY = h / 2;
    const rysuj = (tab, kolor) => {
      g.fillStyle = kolor;
      for(let x = 0; x < w; x++){
        const a = i0 + Math.floor(x * ile / w), b = i0 + Math.floor((x + 1) * ile / w);
        let m = 0; for(let i = a; i < Math.max(b, a + 1) && i < n; i++) m = Math.max(m, tab[i]);
        const hh = Math.max(1, m * (h / 2 - 2)); g.fillRect(x, srodekY - hh, 1, hh * 2);
      }
    };
    rysuj(szczyt, 'rgba(201,192,184,.22)'); rysuj(rms, 'rgba(201,192,184,.72)');
    return {w, h, g};
  }
  function przerysujFale(){
    const d = SZCZ.fala; if(!d || !SZCZ.edytor) return;
    const cala = $('#falaCala'), zoom = $('#falaZoom'); if(!cala || !zoom) return;
    {
      const {w, h, g} = _rysujObwiednie(cala, d.szczyt, d.rms, 0, d.czas_s);
      const x = t => (t / d.czas_s) * w;
      const cue = d.cues || {};
      [['intro', cue.intro, K.dim], ['drop', cue.drop, K.warn], ['outro', cue.outro, K.dim]].forEach(([nazwa, t, kolor]) => {
        if(t == null) return; g.fillStyle = kolor; g.fillRect(x(t), 0, 1, h);
        g.font = "500 9px 'DM Mono',monospace"; g.fillText(nazwa, Math.min(x(t) + 3, w - 30), 9);
      });
      g.fillStyle = 'rgba(242,236,230,.08)'; g.fillRect(x(SZCZ.srodek - SZCZ.okno / 2), 0, Math.max(2, x(SZCZ.okno)), h);
      g.fillStyle = K.acc; g.fillRect(x(SZCZ.kotwica), 0, 1.5, h);
    }
    {
      const od = Math.max(0, SZCZ.srodek - SZCZ.okno / 2), do_ = Math.min(d.czas_s, od + SZCZ.okno);
      const {w, h, g} = _rysujObwiednie(zoom, d.szczyt, d.rms, od, do_);
      const x = t => ((t - od) / (do_ - od)) * w;
      if(SZCZ.bpm > 0){
        const okres = 60 / SZCZ.bpm;
        let k = Math.ceil((od - SZCZ.kotwica) / okres);
        // kotwica ma numer bitu SZCZ.battito (1–4); jedynki taktu leżą co 4 bity od niej z tym przesunięciem
        const jedynka = ((1 - (SZCZ.battito || 1)) % 4 + 4) % 4;
        for(let t = SZCZ.kotwica + k * okres; t <= do_; t += okres, k++){
          if(t < od) continue;
          const takt = (((k - jedynka) % 4) + 4) % 4 === 0;
          g.fillStyle = takt ? 'rgba(242,236,230,.6)' : 'rgba(242,236,230,.2)';
          g.fillRect(x(t), takt ? 0 : h * 0.18, takt ? 1.5 : 1, takt ? h : h * 0.64);
        }
      }
      g.fillStyle = K.acc; g.fillRect(x(SZCZ.kotwica) - 1, 0, 2, h);
      g.font = "500 10px 'DM Mono',monospace"; g.fillStyle = K.acc; g.fillText('kotwica', Math.min(x(SZCZ.kotwica) + 5, w - 48), h - 5);
    }
    siatkaStan();
  }
  function wireFala(box){
    const cala = $('#falaCala', box), zoom = $('#falaZoom', box);
    const czasCala = (e) => { const r = cala.getBoundingClientRect(); return Math.min(SZCZ.fala.czas_s, Math.max(0, (e.clientX - r.left) / r.width * SZCZ.fala.czas_s)); };
    const czasZoom = (e) => { const r = zoom.getBoundingClientRect(); const od = Math.max(0, SZCZ.srodek - SZCZ.okno / 2), do_ = Math.min(SZCZ.fala.czas_s, od + SZCZ.okno); return Math.max(0, od + (e.clientX - r.left) / r.width * (do_ - od)); };
    // przeciąganie: na całości przesuwa okno, na powiększeniu kotwicę
    cala.addEventListener('pointerdown', e => { cala.setPointerCapture(e.pointerId); SZCZ.srodek = czasCala(e); przerysujFale(); });
    cala.addEventListener('pointermove', e => { if(e.buttons & 1){ SZCZ.srodek = czasCala(e); przerysujFale(); } });
    zoom.addEventListener('pointerdown', e => { zoom.setPointerCapture(e.pointerId); SZCZ.kotwica = czasZoom(e); przerysujFale(); });
    zoom.addEventListener('pointermove', e => { if(e.buttons & 1){ SZCZ.kotwica = czasZoom(e); przerysujFale(); } });
    zoom.addEventListener('wheel', e => { e.preventDefault(); SZCZ.okno = Math.min(30, Math.max(1, SZCZ.okno * (e.deltaY > 0 ? 1.15 : 0.87))); przerysujFale(); }, {passive:false});
    $$('[data-krok]', box).forEach(b => b.onclick = () => { SZCZ.kotwica = Math.max(0, SZCZ.kotwica + parseFloat(b.dataset.krok)); SZCZ.srodek = SZCZ.kotwica; przerysujFale(); });
    $$('[data-bit]', box).forEach(b => b.onclick = () => { if(!SZCZ.bpm) return; const ile = parseFloat(b.dataset.bit); SZCZ.kotwica = Math.max(0, SZCZ.kotwica + ile * (60 / SZCZ.bpm)); if(Number.isInteger(ile)) SZCZ.battito = (((SZCZ.battito - 1 + ile) % 4) + 4) % 4 + 1; SZCZ.srodek = SZCZ.kotwica; przerysujFale(); });
    $('#siatkaZapisz', box).onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true;
      try{
        await api('/api/siatka', {method:'POST', body:{file:SZCZ.file, first_beat_s:SZCZ.kotwica, bpm:SZCZ.bpm || null, battito:SZCZ.battito || 1}});
        SZCZ.fala.reczna_korekta = true; SZCZ.fala.first_beat_s = SZCZ.kotwica; SZCZ.fala.battito = SZCZ.battito;
        S.toast('siatka zapisana — eksport użyje tej kotwicy', 'ok');
        przerysujFale(); odswiezKafle();
      }catch(err){}
      b.disabled = false;
    };
    $('#siatkaReset', box).onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true;
      try{
        const j = await api('/api/siatka', {method:'POST', body:{file:SZCZ.file, reset:true}});
        SZCZ.kotwica = j.first_beat_s || 0; SZCZ.srodek = SZCZ.kotwica;
        SZCZ.fala.reczna_korekta = false; SZCZ.fala.first_beat_s = SZCZ.kotwica;
        // po resecie BPM i numer bitu kotwicy wracają do wyliczonych
        try{ const f = await api('/api/waveform?file=' + encF(SZCZ.file), {cicho:true}); SZCZ.bpm = f.bpm || SZCZ.bpm; SZCZ.fala.bpm = f.bpm; SZCZ.battito = f.battito || 1; SZCZ.fala.battito = SZCZ.battito; SZCZ.fala.pewnosc_siatki = f.pewnosc_siatki; }catch(e2){}
        S.toast('przywrócono siatkę wyliczoną', 'info');
        przerysujFale(); odswiezKafle();
      }catch(err){}
      b.disabled = false;
    };
    window.addEventListener('resize', () => { if(SZCZ.edytor && $('#falaZoom')) przerysujFale(); });
  }
  function odswiezTempoInfo(){
    const box = $('#tempoInfo'); if(!box) return;
    const t = SZCZ.tempo;
    if(t === undefined){ box.innerHTML = `<span class="spin"></span> sprawdzam, czy tempo trzyma się do końca…`; return; }
    if(!t){ box.innerHTML = `<span>nie udało się sprawdzić stabilności tempa</span>`; return; }
    const kolor = !t.stabilne ? K.warn : (t.bpm_nietrafione ? K.warn : K.ok);
    const znak = !t.stabilne ? '⚠ tempo zmienne' : (t.bpm_nietrafione ? '! BPM lekko nietrafione' : '✓ tempo stabilne');
    box.innerHTML = `<span style="color:${kolor};font-weight:600;white-space:nowrap">${znak}</span><span style="flex:1">${esc(t.opis || '')}</span>
      ${t.stabilne && t.bpm_nietrafione && t.bpm_poprawione ? `<button class="btn mini obrys" id="tempoPrzyjmij" type="button" style="white-space:nowrap">Przyjmij ${esc(nf(t.bpm_poprawione, 2))} BPM</button>` : ''}`;
    const b = $('#tempoPrzyjmij', box);
    if(b) b.onclick = async () => {
      b.disabled = true; b.innerHTML = '<span class="spin"></span> zapisuję…';
      try{
        const j = await api('/api/tempo/przyjmij', {method:'POST', body:{file:SZCZ.file}});
        SZCZ.bpm = j.bpm || t.bpm_poprawione; SZCZ.fala.bpm = SZCZ.bpm; SZCZ.fala.reczna_korekta = true;
        if(j.first_beat_s != null){ SZCZ.kotwica = j.first_beat_s; SZCZ.fala.first_beat_s = j.first_beat_s; }
        SZCZ.tempo = {...t, bpm_nietrafione:false, opis:`przyjęto ${nf(SZCZ.bpm, 2)} BPM — siatka zapisana jako ręczna korekta`};
        S.toast(`przyjęto ${nf(SZCZ.bpm, 2)} BPM`, 'ok');
        przerysujFale(); odswiezKafle(); odswiezTempoInfo();
      }catch(err){ b.disabled = false; b.textContent = `Przyjmij ${nf(t.bpm_poprawione, 2)} BPM`; }
    };
  }

  // ---------- lepsza wersja z Soulseeka ----------
  async function szukajLepszej(t, btn){
    const box = $('#szczLepsze'); if(!box) return;
    box.classList.remove('hide');
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> szukam…';
    box.innerHTML = `<div style="display:flex;align-items:center;gap:10px;font-size:13px;color:#8f857c"><span class="spin"></span> przeszukuję Soulseeka — to trwa około minuty…</div>`;
    const lossless = ['flac', 'wav', 'aiff', 'aif'].includes((t.ext || '').toLowerCase());
    let d;
    try{
      d = await api('/api/upgrade/find', {method:'POST', body:{artist:t.artist, title:t.title, duration:t.duration, lossless, bitrate:0, grade:t.quality}});
    }catch(e){ box.innerHTML = `<div style="font-size:13px;color:${K.bad}">✗ ${esc(e.message)}</div>`; btn.disabled = false; btn.textContent = 'Szukaj lepszej wersji'; return; }
    btn.disabled = false; btn.textContent = 'Szukaj lepszej wersji';
    if(!d.count){
      box.innerHTML = `<div style="display:flex;align-items:center;gap:12px;font-size:13px;color:#8f857c"><span>nic lepszego nie znalazłem — sprawdziłem ${d.sprawdzonych} ${lm(d.sprawdzonych, ['wynik','wyniki','wyników'])} dla „${esc(d.searched_as || t.artist)}”</span><button class="btn mini" id="lepszaZyczenie" type="button" style="margin-left:auto;white-space:nowrap">Dodaj do życzeń</button></div>`;
      $('#lepszaZyczenie', box).onclick = async (e) => { const b = e.currentTarget; b.disabled = true; try{ await api('/api/redownload', {method:'POST', body:{file:t.file}}); b.textContent = '✓ na liście życzeń'; }catch(err){ b.disabled = false; } };
      return;
    }
    box.innerHTML = `<div style="display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;align-items:center;gap:10px"><span class="kicker">LEPSZE WERSJE · ${d.count}</span><span style="font-size:12.5px;color:#8f857c">sprawdziłem ${d.sprawdzonych} ${lm(d.sprawdzonych, ['wynik','wyniki','wyników'])} · po pobraniu: weryfikacja odsłuchem + jakość</span></div>
      <div style="display:grid;grid-template-columns:1.6fr .9fr .6fr .6fr 1fr auto;gap:14px;padding:0 16px;font:500 10.5px var(--mono);letter-spacing:.1em;color:#5e5650"><span>PLIK / UŻYTKOWNIK</span><span>FORMAT</span><span>ROZMIAR</span><span>CZAS</span><span>DLACZEGO</span><span></span></div>
      <div style="border:1px solid #2a2522;border-radius:12px;overflow:hidden">${d.candidates.slice(0, 8).map((c, i) => `
        <div class="kand${i === 0 ? ' naj' : ''}">
          <div style="min-width:0"><div style="font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(c.path)}">${esc(c.filename)}</div><div style="font-size:12px;color:#8f857c;margin-top:2px">${esc(c.user)}${c.free_slot === false ? ' · kolejka' : ''}</div></div>
          <span class="m" style="color:${c.lossless ? K.ok : '#b0a69c'}">${esc(c.format)}${c.bitrate ? ' ' + c.bitrate : ''}</span>
          <span class="m">${esc(String(c.size_mb))} MB</span>
          <span class="m" style="color:${c.duration_ok ? K.ok : (c.duration_delta == null ? K.dim : K.warn)}">${c.length_s ? fmtTime(c.length_s) : '—'}</span>
          <span class="m" title="${esc(c.pewnosc || '')}">${esc(c.dlaczego || '')}${c.pewnosc && c.pewnosc !== 'pewne' ? ` <span style="color:${K.warn}">?</span>` : ''}</span>
          <button class="btn mini${i === 0 ? ' acc' : ''} bierz" type="button" data-i="${i}">${i === 0 ? 'POBIERZ' : 'Pobierz'}</button>
        </div>`).join('')}</div>
    </div>`;
    $$('.bierz', box).forEach(b => b.onclick = async () => {
      const c = d.candidates[Number(b.dataset.i)]; b.disabled = true; b.innerHTML = '<span class="spin"></span>';
      try{ await api('/api/download', {method:'POST', body:{artist:t.artist, title:t.title, path:c.path, user:c.user, size:c.size}}); b.textContent = '✓ w kolejce'; S.pollLiczniki(); }
      catch(e){ b.disabled = false; b.textContent = 'Pobierz'; }
    });
  }
})();
