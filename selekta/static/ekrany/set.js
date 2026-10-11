/* ============================================================
   Ekrany grupy „Set”: Kolejność setu (3a), Import (4a),
   Eksport (4b), Pobierania (4c).
   Projekt: docs/design/selekta-auto.dc.html — style inline 1:1,
   kolory z tokenów powłoki (S.K, S.CAM). Dane wyłącznie z /api/*
   (kształty odpowiedzi wg selekta/web.py).
   ============================================================ */
(() => {
const {K, CAM, esc, fmtTime, fmtLicz, $, $$, on, nazwaPliku, api, toast} = S;
const FAZA = {rozgrzewka:K.info, 'środek':K.ok, kulminacja:K.warn};
const ETYK = `font:500 10.5px var(--mono);letter-spacing:.12em;color:${K.dim2}`;
const PANEL = `background:${K.panel};border:1px solid ${K.line};border-radius:14px`;
const ELIP = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';

// ---------- drobiazgi wspólne ----------
const fmtPL = (x, d=2) => (x==null || !isFinite(x)) ? '—' : Number(x).toFixed(d).replace('.', ',');
const mediana = arr => { const a = arr.filter(x => x!=null && isFinite(x)).sort((p,q)=>p-q); if(!a.length) return null; const m = a.length>>1; return a.length%2 ? a[m] : (a[m-1]+a[m])/2; };
const czasSetu = s => { const m = Math.round(s/60), h = Math.floor(m/60); return h ? `${h} h ${String(m%60).padStart(2,'0')} min` : `${m} min`; };
const rozbijNazwe = name => { const base = String(name||'').replace(/\.[a-z0-9]{2,5}$/i, ''); const i = base.indexOf(' - '); return i>0 ? {artist:base.slice(0,i), title:base.slice(i+3)} : {artist:'', title:base}; };
const camNr = c => parseInt(String(c||''), 10) || 0;
const camDist = (a, b) => { const x = camNr(a), y = camNr(b); if(!x || !y) return 0; const d = Math.abs(x-y); return Math.min(d, 12-d); };
const kafel = (n, etyk, kolor) => `<div class="kafel poziomy"><span class="liczba" style="color:${kolor}">${n}</span><span style="font:500 10.5px var(--mono);letter-spacing:.1em;color:${K.dim}">${etyk}</span></div>`;
const kropka = (kolor, extra='') => `<span style="width:8px;height:8px;border-radius:50%;background:${kolor};flex-shrink:0;${extra}"></span>`;
const dzis = () => { const d = new Date(); return `${String(d.getDate()).padStart(2,'0')}.${String(d.getMonth()+1).padStart(2,'0')}`; };
const lm = (n, j, m, w) => n===1 ? j : (n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? m : w);   // liczba mnoga
const wybrane = () => { const w = S.stan.wybrane; return !w ? [] : (w instanceof Set ? [...w] : (Array.isArray(w) ? w : [])); };
const mapaTracks = lista => { const m = {}; (lista||[]).forEach(t => { m[t.file] = t; }); return m; };
if(!S.stan.set) S.stan.set = {tryb:'biblioteka', playlista:''};   // zakres setu wspólny dla Kolejności i Eksportu

// style, których nie da się zrobić inline (hover, placeholder, opcje selecta)
if(!$('#setStyl')){
  const st = document.createElement('style'); st.id = 'setStyl';
  st.textContent = `
    .setCel:not(.on):hover{border-color:${K.line3}!important}
    .setWiersz:hover{background:${K.hover}}
    .setWiersz[data-klik]{cursor:pointer}
    .setTekst::placeholder{color:${K.dim2}}
    .setSeg option{background:${K.panel};color:${K.txt}}
    .setSeg:disabled{opacity:.45;cursor:default}
    .setPole{background:${K.panel};border:1px solid ${K.line};border-radius:9px;padding:9px 14px;color:${K.txt};font-size:13.5px;width:100%}
    .setPole:focus{border-color:${K.acc}}
    .setLink{color:${K.dim};font:500 11px var(--mono);cursor:pointer}.setLink:hover{color:${K.txt}}`;
  document.head.appendChild(st);
}

// ---------- odwołania do innych ekranów (z prostym zapasem) ----------
function szczegoly(u){
  if(S.otworzSzczegoly) return S.otworzSzczegoly(u.file);
  S.player.graj({file:u.file, title:u.title, artist:u.artist, bpm:u.bpm, camelot:u.camelot, duration:u.duration});
}
// zwraca obietnicę nazwy zakolejkowanego pliku (albo null, gdy nic nie wybrano)
async function szukajNaSoulseeku(utwor){
  if(S.wybierzWynik){
    const r = await Promise.resolve(S.wybierzWynik(utwor));
    return typeof r === 'string' ? r : (r && (r.queued || r.file)) || null;
  }
  return pickerZapas(utwor);
}
function pasekDopasowania(v, etyk){
  const pct = Math.round((v||0)*100), kolor = pct>=80 ? K.ok : (pct>=50 ? K.warn : K.bad);
  return `<div style="display:flex;align-items:center;gap:6px;font:500 10.5px var(--mono);color:${K.dim}" title="${etyk} ${pct}%"><span style="width:44px">${etyk}</span><span style="width:60px;height:4px;background:${K.line};border-radius:2px;overflow:hidden;display:inline-block"><span style="display:block;height:100%;width:${pct}%;background:${kolor}"></span></span></div>`;
}
function kandydat(c, i){
  const dl = c.length_s ? fmtTime(c.length_s) : '—';
  const delta = c.duration_delta!=null
    ? (c.duration_ok ? `<span class="ok">✓ czas</span>` : `<span class="dim">${c.duration_delta>0?'+':''}${Math.round(c.duration_delta)} s</span>`)
    : `<span class="dim">?</span>`;
  const klasa = c.lossless ? 'flac' : (String(c.format).toLowerCase()==='wav' ? 'wav' : 'mp3');
  return `<div style="display:grid;grid-template-columns:minmax(0,1fr) 120px 64px 96px auto;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid ${K.line2}">
    <div style="min-width:0"><div style="font-weight:600;font-size:13px;${ELIP}">${esc(c.filename)}</div><div style="font:500 11px var(--mono);color:${K.dim};${ELIP}">${esc(c.folder||'')}</div><div style="font-size:11.5px;color:${K.dim};margin-top:2px">${esc(c.user)}${c.free_slot ? ' · <span class="ok">wolny slot</span>' : ' · zajęty'}</div></div>
    <div style="display:flex;flex-direction:column;gap:3px">${pasekDopasowania(c.title_match,'tytuł')}${pasekDopasowania(c.artist_match,'artysta')}</div>
    <div style="text-align:right"><div style="font:500 12px var(--mono)">${dl}</div><div style="font-size:11px">${delta}</div></div>
    <div style="text-align:right"><span class="fmt ${klasa}" style="margin-left:auto">${esc(c.format)}${c.bitrate ? ' '+c.bitrate+'k' : ''}</span><div style="font-size:11px;color:${K.dim};margin-top:3px">${fmtPL(c.size_mb,1)} MB</div></div>
    <button class="btn mini acc" data-i="${i}">Pobierz</button>
  </div>`;
}
// arkusz wyboru wyniku z Soulseeka — używany tylko, gdy kreator.js nie wystawia S.wybierzWynik
function pickerZapas(u){
  return new Promise(resolve => {
    const body = S.arkusz(`
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
        <div><div class="kicker">Soulseek · wybierz plik</div><div style="font-size:22px;font-weight:700;margin-top:6px">${esc(u.title)}</div><div style="font-size:13px;color:${K.dim};margin-top:2px">${esc(u.artist)}${u.duration ? ' · '+fmtTime(u.duration) : ''}</div></div>
        <button class="btn goly" data-zamknij>✕ zamknij</button></div>
      <div id="pickBody" style="font-size:13px;color:${K.dim}"><span class="spin"></span> szukam na Soulseeku…</div>`, {szer:860});
    body.querySelector('[data-zamknij]').onclick = () => { S.zamknijArkusz(); resolve(null); };
    api('/api/search', {method:'POST', body:{artist:u.artist, title:u.title, duration:u.duration}, cicho:true}).then(d => {
      const pb = body.querySelector('#pickBody'); if(!pb) return;
      if(!d.count){
        pb.innerHTML = `Nic nie znaleziono. <button class="btn mini" data-zyczenie style="margin-left:8px">Dodaj do listy życzeń</button> <span class="dim2">— apka sprawdzi ponownie później</span>`;
        pb.querySelector('[data-zyczenie]').onclick = async e => { e.target.disabled = true; try{ await api('/api/wishlist', {method:'POST', body:{artist:u.artist, title:u.title}}); e.target.textContent = '✓ na liście życzeń'; }catch(err){ e.target.disabled = false; } };
        return;
      }
      pb.innerHTML = `<div style="font:500 11px var(--mono);color:${K.dim2};margin-bottom:4px">szukano po: ${esc(d.searched_as||u.artist)} · znaleziono ${d.count} — wybierz, który pobrać</div><div>${d.candidates.map(kandydat).join('')}</div><div id="pickProg" style="margin-top:10px;font-size:12.5px"></div>`;
      on(pb, 'click', 'button[data-i]', async (e, b) => {
        const c = d.candidates[+b.dataset.i]; b.disabled = true; b.textContent = '…';
        try{
          const j = await api('/api/download', {method:'POST', body:{artist:u.artist, title:u.title, path:c.path, user:c.user, size:c.size}, cicho:true});
          b.textContent = '✓ w kolejce'; pb.querySelector('#pickProg').innerHTML = `✓ pobieram <b>${esc(j.queued)}</b> od ${esc(c.user)}`;
          S.pollLiczniki(); resolve(j.queued);
        }catch(err){ b.textContent = '✗'; b.disabled = false; pb.querySelector('#pickProg').innerHTML = `<span class="bad">✗ ${esc(err.message)}</span>`; }
      });
    }).catch(e => { const pb = body.querySelector('#pickBody'); if(pb) pb.innerHTML = `<span class="bad">✗ ${esc(e.message)}</span>`; });
  });
}
// arkusz z jednym polem tekstowym — nazwa playlisty, ścieżka pliku
function zapytaj({kicker, tytul, opis, wartosc='', placeholder='', cta='OK'}){
  return new Promise(resolve => {
    const body = S.arkusz(`
      <div><div class="kicker">${esc(kicker)}</div><div style="font-size:22px;font-weight:700;margin-top:6px">${esc(tytul)}</div>${opis ? `<div style="font-size:13px;color:${K.dim};margin-top:4px;line-height:1.5">${opis}</div>` : ''}</div>
      <input class="setPole" id="zapPole" value="${esc(wartosc)}" placeholder="${esc(placeholder)}">
      <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn cichy" data-nie>Anuluj</button><button class="btn acc" data-tak>${esc(cta)}</button></div>`, {szer:560});
    const pole = body.querySelector('#zapPole'); pole.focus(); pole.select();
    const koniec = v => { S.zamknijArkusz(); resolve(v); };
    body.querySelector('[data-nie]').onclick = () => koniec(null);
    body.querySelector('[data-tak]').onclick = () => koniec(pole.value.trim() || null);
    pole.onkeydown = e => { if(e.key==='Enter') koniec(pole.value.trim() || null); };
  });
}
// wspólny komunikat po wysyłce do rekordboxa (install / playlist/export)
function pokazWynikRekordboxa(j){
  const bez = j.bez_analizy ? ` ${j.bez_analizy} ${lm(j.bez_analizy,'utwór nie ma','utwory nie mają','utworów nie ma')} policzonej analizy — rekordbox ustawi im siatkę sam („Analizuj wszystko” w Bibliotece to naprawi).` : '';
  if(j.ok) toast(`✓ ${j.count} ${lm(j.count,'utwór','utwory','utworów')} jako playlista „${j.playlist}” — ${j.message || 'odpal rekordbox, będzie w panelu bocznym pod „rekordbox xml”'}.${bez}`, 'ok', 9000);
  else{
    toast(`⚠ playlista zapisana (${j.count} utworów), ale nie podpięta: ${j.message||'—'}. Ręcznie: File → Import Collection → ${j.path}`, 'warn', 12000);
    if(j.running) toast('rekordbox jest uruchomiony — zamknij go i kliknij ponownie, inaczej nadpisze ustawienia przy wyjściu.', 'warn', 8000);
  }
}

/* ============================================================
   3a · KOLEJNOŚĆ SETU
   ============================================================ */
const KOL = {faza:'wszystko', playlisty:[], dane:null, order:null, tracks:{}, nr:0, model:null};

function kolNota(us, i, peak){
  const u = us[i], p = us[i-1];
  if(i===0) return {tekst:'start', kolor:K.dim};
  if(i===peak) return {tekst:'szczyt setu', kolor:K.acc};
  const cz = [];
  if(peak!=null && i===peak+1) cz.push('zejście');
  if(u.camelot && p.camelot) cz.push(u.camelot===p.camelot ? 'ten sam klucz' : `${p.camelot} → ${u.camelot}`);
  const db = (u.bpm!=null && p.bpm!=null) ? Math.round(u.bpm - p.bpm) : 0;
  if(db) cz.push(`${db>0?'+':'−'}${Math.abs(db)} BPM`);
  if(u.energia!=null && p.energia!=null){ const de = u.energia - p.energia; if(Math.abs(de) >= 0.05) cz.push(`${de>0?'+':'−'}${fmtPL(Math.abs(de))} energia`); }
  const zle = camDist(u.camelot, p.camelot) > 1 || Math.abs(db) >= 4;
  return {tekst: cz.join(' · ') || 'płynne przejście', kolor: zle ? K.warn : K.dim};
}
// ten sam plik potrafi leżeć w kilku folderach playlist (kopie z playlists.collect) —
// /api/order i /api/energia oddają go wtedy kilka razy; w secie zostaje pierwsze wystąpienie
function bezKopii(lista, peak){
  const widziane = new Set(), us = []; let nowyPeak = peak, pominiete = 0;
  lista.forEach((u, i) => {
    if(widziane.has(u.file)){ pominiete++; if(peak!=null && i < peak) nowyPeak--; if(i===peak) nowyPeak = null; return; }
    widziane.add(u.file); us.push(u);
  });
  return {us, peak:nowyPeak, pominiete};
}
// te same reguły co energia.luk_setu — używane tylko, gdy po odrzuceniu kopii
// pozycje z serwera przestają się zgadzać z listą
function lukUwagi(us, peak){
  const e = us.map(u => u.energia||0), n = e.length, uw = [];
  if(n >= 5 && peak < n*0.4) uw.push({typ:'wczesna-kulminacja', opis:`najmocniejszy utwór jest na pozycji ${peak+1} z ${n} — po nim zostaje długi zjazd`});
  for(let i=1;i<n-1;i++){ const spadek = e[i-1]-e[i]; if(spadek > 0.22 && e[i+1] > e[i]+0.15) uw.push({typ:'dziura', opis:`„${us[i].title||us[i].file}” siada o ${Math.round(spadek*100)}% względem poprzedniego i zaraz wracasz w górę`}); }
  if(n >= 6 && (Math.max(...e)-Math.min(...e)) < 0.18) uw.push({typ:'plaski', opis:'energia prawie się nie zmienia przez cały set — brakuje narastania'});
  return uw;
}
// jeden model dla obu źródeł: /api/energia (pełny) albo /api/order (tylko kolejność)
function kolModel(){
  const d = KOL.dane;
  if(d){
    let {us, peak, pominiete} = bezKopii((d.utwory||[]).map(u => ({file:u.file, path:u.path, title:u.title || rozbijNazwe(u.file).title, artist:u.artist || rozbijNazwe(u.file).artist,
      bpm:u.bpm, camelot:u.camelot, faza:u.faza||'', energia:u.srednia, duration:u.czas_s, intro:u.intro_typ})), d.kulminacja);
    let uwagi = d.uwagi||[];
    if(pominiete && us.length){ peak = us.reduce((b,u,i,a) => (u.energia||0) > (a[b].energia||0) ? i : b, 0); uwagi = lukUwagi(us, peak); }
    return {us, peak, pominiete, opis:d.zakres, uwagi, pelny:true};
  }
  if(KOL.order){
    const {us, pominiete} = bezKopii(KOL.order.map(o => { const t = KOL.tracks[o.file] || {}; const r = rozbijNazwe(o.file);
      return {file:o.file, title:t.title || r.title, artist:t.artist || r.artist, bpm:o.bpm, camelot:o.camelot, faza:'', energia:null, duration:t.duration}; }), null);
    return {us, peak:null, pominiete, opis:'cała biblioteka', uwagi:[], pelny:false};
  }
  return null;
}
function kolRysuj(host){
  const m = KOL.model = kolModel(); if(!m) return;
  const {us, peak} = m, n = us.length;
  const med = mediana(us.map(u=>u.bpm));
  $('#kolSub', host).innerHTML = `Koło Camelot, energia rosnąco${peak!=null ? ` · kulminacja na pozycji <b style="color:${K.txt}">${peak+1}</b>` : ''}${med!=null ? ` · mediana ${Math.round(med)} BPM` : ''}`;
  const czas = us.reduce((s,u)=>s+(u.duration||0), 0);
  if(S.biezacy()==='kolejnosc') S.tytul(`${m.opis} · ${n} ${lm(n,'utwór','utwory','utworów')}${czas ? ' · '+czasSetu(czas) : ''}`);

  // łuk energii
  const luk = $('#kolLuk', host);
  if(m.pelny){
    const maks = Math.max(...us.map(u=>u.energia||0), 0.01);
    luk.style.gap = (n>60 ? 2 : (n>28 ? 4 : 6))+'px';
    luk.innerHTML = us.map((u,i) => { const szczyt = i===peak, poza = KOL.faza!=='wszystko' && u.faza!==KOL.faza;
      return `<span data-i="${i}" title="${i+1}. ${esc(u.title)} — energia ${fmtPL(u.energia)}, ${esc(u.faza||'—')}" style="flex:1;border-radius:3px 3px 0 0;height:${Math.max(4, Math.round(100*(u.energia||0)/maks))}%;background:${szczyt ? K.acc : (FAZA[u.faza]||K.line3)};opacity:${poza ? .18 : (szczyt ? 1 : .75)};box-shadow:${szczyt ? '0 0 14px '+K.acc : 'none'};min-width:2px"></span>`; }).join('');
  }
  // lista
  const lista = $('#kolLista', host);
  const wiersze = us.map((u,i) => ({u,i})).filter(({u}) => KOL.faza==='wszystko' || u.faza===KOL.faza);
  lista.innerHTML = wiersze.length ? wiersze.map(({u,i}) => { const nota = kolNota(us, i, peak); const fk = FAZA[u.faza];
    return `<div class="setWiersz" data-klik data-i="${i}" style="display:grid;grid-template-columns:28px minmax(0,1fr) 36px 40px auto;gap:12px;align-items:center;padding:10px 18px;border-bottom:1px solid ${K.line2};border-left:2px solid ${i===peak ? K.acc : 'transparent'}">
      <span style="font:500 12px var(--mono);color:${K.dim2}">${String(i+1).padStart(2,'0')}</span>
      <div style="min-width:0"><div style="font-weight:600;font-size:14px;${ELIP}">${esc(u.title)}<span style="font-weight:400;font-size:12.5px;color:${K.dim};margin-left:8px">${esc(u.artist)}</span></div>
        <div style="font:500 11px var(--mono);color:${nota.kolor};margin-top:2px;${ELIP}">${esc(nota.tekst)}</div></div>
      <span style="font:500 12.5px var(--mono);color:${K.dim}">${u.bpm ? Math.round(u.bpm) : '—'}</span>
      <span class="cam" style="background:${CAM[u.camelot]||K.line3}">${esc(u.camelot||'—')}</span>
      ${fk ? `<span style="font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid ${fk};color:${fk};white-space:nowrap">${esc(u.faza)}</span>`
           : `<span style="font:500 11px var(--mono);color:${K.dim2};white-space:nowrap">${m.pelny ? '—' : '<span class="spin"></span>'}</span>`}
    </div>`; }).join('')
    : `<div class="pusto">W tym zakresie nie ma utworów z fazą „${esc(KOL.faza)}”.</div>`;

  // koło Camelot
  const uzyte = {}; us.forEach(u => { if(u.camelot) uzyte[u.camelot] = (uzyte[u.camelot]||0)+1; });
  const pole = (k, r) => { const ile = uzyte[k]||0; return `<span title="${k} · ${ile} ${lm(ile,'utwór','utwory','utworów')}" style="font:600 10.5px var(--mono);text-align:center;padding:7px 0;border-radius:${r};background:${ile ? CAM[k] : K.panel2};color:${ile ? K.bg : K.line3}">${k}</span>`; };
  $('#kolKolo', host).innerHTML = Array.from({length:12}, (_,i) => `<div style="display:flex;flex-direction:column;gap:3px">${pole((i+1)+'B','6px 6px 2px 2px')}${pole((i+1)+'A','2px 2px 6px 6px')}</div>`).join('');
  const nry = us.map(u=>camNr(u.camelot)).filter(Boolean);
  let opis = 'Brak tonacji — najpierw „Analizuj wszystko” w Bibliotece.';
  if(nry.length){
    const a = nry[0], b = nry[nry.length-1];
    let skoki = 0; for(let i=1;i<n;i++) if(camDist(us[i-1].camelot, us[i].camelot) > 1) skoki++;
    const ruch = a===b ? `Set zostaje przy ${a}` : `Set porusza się ${a} → ${b} ${((b-a+12)%12) <= ((a-b+12)%12) ? 'zgodnie z ruchem wskazówek' : 'przeciwnie do ruchu wskazówek'}`;
    opis = `${ruch}, ${skoki ? `${skoki} ${lm(skoki,'skok','skoki','skoków')} o więcej niż jedno pole` : 'bez skoków o więcej niż jedno pole'}. Użyte tonacje: ${Object.keys(uzyte).length} z 24.`;
  }
  $('#kolKoloOpis', host).textContent = opis;

  // uwagi
  const uw = [];
  m.uwagi.forEach(w => uw.push({k:K.warn, html: esc(w.opis).replace(/„([^”]+)”/g, '<b>„$1”</b>')}));
  let bpmUw = 0, camUw = 0;
  for(let i=1;i<n-1 && bpmUw<3;i++){
    const u = us[i], p = us[i-1], q = us[i+1]; if(!(u.bpm && p.bpm && q.bpm)) continue;
    const d1 = p.bpm-u.bpm, d2 = q.bpm-u.bpm;
    if(d1>=2 && d2>=2){ const d = Math.min(d1,d2); bpmUw++; uw.push({k:K.warn, html:`<b>${esc(u.title)}</b> jest o ${Math.round(d)} BPM wolniejszy od sąsiadów — pitch +${fmtPL(100*d/u.bpm,1)} % albo zamień z sąsiadem.`}); }
  }
  for(let i=1;i<n && camUw<3;i++){ const u = us[i], p = us[i-1]; if(camDist(p.camelot, u.camelot) > 1){ camUw++; uw.push({k:K.warn, html:`<b>${esc(u.title)}</b> skacze z ${esc(p.camelot)} na ${esc(u.camelot)} — więcej niż jedno pole na kole.`}); } }
  if(m.pominiete) uw.push({k:K.dim2, html:`${m.pominiete} ${lm(m.pominiete,'kopia tego samego pliku','kopie tych samych plików','kopii tych samych plików')} (foldery playlist) — w secie każdy utwór raz.`});
  if(!m.pelny) uw.push({k:K.dim2, html:'Łuk energii i fazy dociągają się w tle.'});
  else if(!m.uwagi.length) uw.push({k:K.ok, html: uw.length ? 'Energia: bez dziur i bez przedwczesnej kulminacji.' : 'Łuk wygląda dobrze — bez dziur, kulminacja we właściwym miejscu, sąsiedzi w tempie.'});
  $('#kolUwagi', host).innerHTML = uw.map(w => `<div style="display:flex;gap:12px;align-items:flex-start;font-size:13px;line-height:1.45">${kropka(w.k,'margin-top:6px')}<span>${w.html}</span></div>`).join('');
}
function kolOdswiezZakres(host){
  const z = S.stan.set;
  $$('#kolZakres [data-z]', host).forEach(el => el.classList.toggle('on', el.dataset.z===z.tryb));
  const n = wybrane().length;
  $('#kolZakres [data-z="zaznaczenie"]', host).textContent = n ? `Zaznaczenie (${n})` : 'Zaznaczenie';
  const sel = $('#kolPlaylista', host);
  const dost = KOL.playlisty.filter(p => p.utworow>0);
  sel.innerHTML = `<option value="">Playlista…</option>` + dost.map(p => `<option value="${esc(p.name)}" ${z.tryb==='playlista' && z.playlista===p.name ? 'selected' : ''}>${esc(p.name)} · ${p.utworow}</option>`).join('');
  sel.disabled = !dost.length; sel.title = dost.length ? 'set = playlista utworzona w apce' : 'nie ma jeszcze żadnej playlisty — utwórz ją w Imporcie';
  if(z.tryb==='playlista' && !dost.some(p=>p.name===z.playlista)) { z.tryb = 'biblioteka'; z.playlista = ''; $$('#kolZakres [data-z]', host).forEach(el => el.classList.toggle('on', el.dataset.z==='biblioteka')); }
}
async function kolLaduj(host){
  const nr = ++KOL.nr, z = S.stan.set;
  try{ KOL.playlisty = (await api('/api/playlisty', {cicho:true})).playlisty || []; }catch(e){ KOL.playlisty = []; }
  KOL.tracks = mapaTracks(await S.tracks().catch(()=>[]));
  if(nr!==KOL.nr) return;
  kolOdswiezZakres(host);
  const lista = $('#kolLista', host), luk = $('#kolLuk', host);
  KOL.dane = null; KOL.order = null; KOL.model = null;
  lista.innerHTML = `<div class="pusto"><span class="spin"></span> układam set…</div>`;
  luk.innerHTML = ''; $('#kolKolo', host).innerHTML = ''; $('#kolKoloOpis', host).textContent = ''; $('#kolUwagi', host).innerHTML = '';
  let body = {};
  if(z.tryb==='zaznaczenie'){
    const w = wybrane();
    if(!w.length){ lista.innerHTML = `<div class="pusto">Najpierw zaznacz utwory w Bibliotece.</div>`; $('#kolSub', host).textContent = 'Koło Camelot, energia rosnąco'; return; }
    body = {files:w};
  }else if(z.tryb==='playlista' && z.playlista){
    body = {name:z.playlista};
  }else{
    // cała biblioteka: kolejność od razu z /api/order, energia dociąga się w tle
    try{
      const d = await api('/api/order', {cicho:true}); if(nr!==KOL.nr) return;
      KOL.order = d.order || [];
      if(!KOL.order.length){ lista.innerHTML = `<div class="pusto">Najpierw „Analizuj wszystko” w Bibliotece — bez BPM i tonacji nie ma czego układać.</div>`; return; }
      kolRysuj(host);
    }catch(e){ lista.innerHTML = `<div class="pusto">✗ ${esc(e.message)}</div>`; return; }
    luk.innerHTML = `<span style="font:500 11px var(--mono);color:${K.dim2};align-self:center"><span class="spin"></span> liczę energię i strukturę…</span>`;
  }
  try{
    const d = await api('/api/energia', {method:'POST', body, cicho:true}); if(nr!==KOL.nr) return;
    KOL.dane = d; kolRysuj(host);
  }catch(e){
    if(nr!==KOL.nr) return;
    if(KOL.order) luk.innerHTML = `<span style="font:500 11px var(--mono);color:${K.warn};align-self:center">łuk energii: ${esc(e.message)}</span>`;
    else lista.innerHTML = `<div class="pusto">✗ ${esc(e.message)}</div>`;
  }
}
async function kolWyslij(host, btn){
  const z = S.stan.set, stary = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> buduję playlistę…';
  try{
    let j;
    if(z.tryb==='playlista' && z.playlista) j = await api('/api/playlist/export', {method:'POST', body:{name:z.playlista}});
    else if(z.tryb==='zaznaczenie'){
      const w = wybrane(); if(!w.length) throw new Error('Najpierw zaznacz utwory w Bibliotece.');
      const name = await zapytaj({kicker:'Wyślij do rekordboxa', tytul:'Jak nazwać playlistę?', opis:`${w.length} zaznaczonych utworów w kolejności harmonicznej.`, wartosc:'selekta-set', cta:'▶ Wyślij'});
      if(!name) return;
      j = await api('/api/playlist/export', {method:'POST', body:{name, files:w}});
    }else j = await api('/api/rekordbox/install', {method:'POST', body:{name:'selekta-set'}});
    pokazWynikRekordboxa(j);
  }catch(e){ if(!e.status) toast(e.message, 'bad'); }
  finally{ btn.disabled = false; btn.textContent = stary; }
}

S.ekran('kolejnosc', {
  tytul: () => 'Kolejność setu',
  render(host){
    host.style.cssText = 'display:grid;grid-template-columns:minmax(0,1fr) 320px;grid-template-rows:auto minmax(0,1fr);gap:20px 24px';
    host.innerHTML = `
      <div style="grid-column:1/3;display:flex;align-items:flex-end;gap:16px">
        <div><h1 class="h1">Kolejność setu</h1><div class="sub" id="kolSub">Koło Camelot, energia rosnąco</div></div>
        <div class="seg" id="kolZakres" style="margin-left:auto" title="Zakres setu: cała biblioteka, zaznaczenie z Biblioteki albo playlista z apki">
          <span data-z="biblioteka" class="on">Cała biblioteka</span><span data-z="zaznaczenie">Zaznaczenie</span>
          <select id="kolPlaylista" class="setSeg" data-z="playlista" style="appearance:none;-webkit-appearance:none;background:transparent;border:0;padding:6px 12px;border-radius:7px;font-weight:600;font-size:12.5px;color:${K.dim};cursor:pointer;font-family:inherit"></select>
        </div>
        <div class="seg" id="kolFaza"><span data-f="wszystko" class="on">Cały set</span><span data-f="rozgrzewka">Warm-up</span><span data-f="kulminacja">Peak</span></div>
        <button class="btn acc" id="kolWyslij">▶ Wyślij do rekordboxa</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px;min-height:0">
        <div style="${PANEL};padding:18px 20px 14px">
          <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px;${ETYK}">ŁUK ENERGII
            <span style="display:flex;align-items:center;gap:6px;color:${K.info};margin-left:auto"><span style="width:8px;height:8px;border-radius:2px;background:${K.info}"></span>ROZGRZEWKA</span>
            <span style="display:flex;align-items:center;gap:6px;color:${K.ok}"><span style="width:8px;height:8px;border-radius:2px;background:${K.ok}"></span>ŚRODEK</span>
            <span style="display:flex;align-items:center;gap:6px;color:${K.warn}"><span style="width:8px;height:8px;border-radius:2px;background:${K.warn}"></span>KULMINACJA</span></div>
          <div id="kolLuk" style="display:flex;align-items:flex-end;justify-content:center;gap:6px;height:110px"></div>
        </div>
        <div id="kolLista" style="${PANEL};overflow:auto;flex:1;min-height:0"></div>
      </div>
      <div style="display:flex;flex-direction:column;gap:14px;min-height:0;overflow:auto">
        <div style="${PANEL};padding:18px 20px;flex-shrink:0">
          <div style="${ETYK};margin-bottom:14px">KOŁO CAMELOT · UŻYTE TONACJE</div>
          <div id="kolKolo" style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px"></div>
          <div id="kolKoloOpis" style="font-size:12.5px;color:${K.dim};margin-top:14px;line-height:1.5"></div>
        </div>
        <div style="${PANEL};padding:18px 20px;display:flex;flex-direction:column;gap:12px;flex-shrink:0">
          <div style="${ETYK}">UWAGI</div>
          <div id="kolUwagi" style="display:flex;flex-direction:column;gap:12px"></div>
        </div>
      </div>`;
    on(host, 'click', '#kolZakres span[data-z]', (e, el) => {
      if(el.dataset.z==='zaznaczenie' && !wybrane().length){ toast('Najpierw zaznacz utwory w Bibliotece.', 'warn'); return; }
      S.stan.set = {tryb:el.dataset.z, playlista:''}; $('#kolPlaylista', host).value = ''; kolLaduj(host);
    });
    $('#kolPlaylista', host).onchange = e => { if(!e.target.value) return; S.stan.set = {tryb:'playlista', playlista:e.target.value}; kolLaduj(host); };
    on(host, 'click', '#kolFaza span', (e, el) => { KOL.faza = el.dataset.f; $$('#kolFaza span', host).forEach(s => s.classList.toggle('on', s===el)); if(KOL.model) kolRysuj(host); });
    on(host, 'click', '#kolLista [data-i]', (e, el) => { const u = KOL.model && KOL.model.us[+el.dataset.i]; if(u) szczegoly(u); });
    on(host, 'click', '#kolLuk [data-i]', (e, el) => { const w = $(`#kolLista [data-i="${el.dataset.i}"]`, host); if(w) w.scrollIntoView({block:'center', behavior:'smooth'}); });
    $('#kolWyslij', host).onclick = e => kolWyslij(host, e.currentTarget);
  },
  load(host){ return kolLaduj(host); },
});

/* ============================================================
   4a · IMPORT
   ============================================================ */
const IMP = {dane:null, nazwa:'', mapa:{}, utworzona:null};
const ORIGIN = o => ({spotify:'SPOTIFY', 'apple-music':'APPLE MUSIC', tidal:'TIDAL', youtube:'YOUTUBE', '1001tracklists':'1001TRACKLISTS', soundcloud:'SOUNDCLOUD', tekst:'TEKST'}[o] || String(o||'').replace(/^plik:/, 'PLIK ').toUpperCase());
function wykryjZrodlo(text){
  const t = text.trim(); if(!t) return null;
  const m = t.match(/(?:https?:\/\/)?(?:[a-z0-9-]+\.)*(open\.spotify\.com|music\.apple\.com|tidal\.com|youtube\.com|youtu\.be|1001tracklists\.com|soundcloud\.com)\/\S*/i);
  if(m) return {'open.spotify.com':'SPOTIFY', 'music.apple.com':'APPLE MUSIC', 'tidal.com':'TIDAL', 'youtube.com':'YOUTUBE', 'youtu.be':'YOUTUBE', '1001tracklists.com':'1001TRACKLISTS', 'soundcloud.com':'SOUNDCLOUD'}[m[1].toLowerCase()];
  if(/^https?:\/\//i.test(t)) return 'LINK';
  const linie = t.split(/\n/).filter(l => l.trim()).length;
  return `TEKST · ${linie}`;
}
function impZrodlo(host, tekst, kolor=K.ok){
  const el = $('#impZrodlo', host);
  el.style.display = tekst ? 'flex' : 'none'; el.style.color = kolor;
  el.children[0].style.background = kolor; el.children[1].textContent = tekst || '';
}
function impPasy(){
  const r = IMP.dane ? IMP.dane.wiersze : [];
  return {auto: r.filter(x => x.pas==='auto' || x.wziete), resolve: r.filter(x => x.pas==='resolve' && !x.wziete), missing: r.filter(x => x.pas==='missing')};
}
function impWiersz(r, i){
  const stan = r.wziete ? 'auto' : r.pas;
  let kolor = {auto:K.ok, resolve:K.warn, missing:K.bad}[stan];
  const t = r.file ? IMP.mapa[nazwaPliku(r.file)] : null;
  const plik = r.file ? `<div style="font:500 12px var(--mono);color:${K.muted};${ELIP}">${esc(nazwaPliku(r.file))}</div>` : '';
  let nota, akcje;
  if(stan==='auto'){
    nota = r.wziete ? `${fmtPL(r.score)} · wybrane ręcznie` : (r.from_file ? 'wskazany w pliku playlisty' : fmtPL(r.score));
    akcje = `<span style="font:500 11px var(--mono);color:${K.dim2};padding:6px 0">w playliście ✓</span>`;
  }else if(stan==='resolve'){
    const roz = r.other_version ? ((t && t.duration && r.duration) ? `inna wersja: ${fmtTime(t.duration)} vs ${fmtTime(r.duration)}` : 'inna wersja miksu') : 'tytuł albo artysta różnią się';
    nota = `${fmtPL(r.score)} · ${roz}`;
    const gra = S.player.gra(r.file);
    akcje = `<button class="btn mini acc" data-akcja="wez">Weź tę</button><button class="btn mini cichy" data-akcja="odsluchaj" style="${gra ? 'color:'+K.acc+';border-color:'+K.acc : ''}">${gra ? '❚❚ Gra' : 'Odsłuchaj'}</button><button class="btn mini cichy" data-akcja="szukaj">Szukaj innej</button>`;
  }else if(r.zakolejkowane){
    kolor = K.info;
    nota = r.zakolejkowane===true ? 'w kolejce — apka sama szuka i pobiera' : `w kolejce pobierania · ${r.zakolejkowane}`;
    akcje = `<button class="btn mini cichy" data-akcja="pobierania">Pobierania →</button>`;
  }else{
    nota = r.buy ? 'nie ma w bibliotece · Beatport' : 'nie ma w bibliotece';
    akcje = `<button class="btn mini acc" data-akcja="szukaj">Szukaj na Soulseeku</button>${r.buy ? `<a class="btn mini cichy" href="${esc(r.buy)}" target="_blank" rel="noopener" style="display:inline-flex;align-items:center">Kup ↗</a>` : ''}`;
  }
  return `<div class="setWiersz" data-i="${i}" style="display:grid;grid-template-columns:8px minmax(0,1fr) minmax(0,1.3fr) auto;gap:16px;align-items:center;padding:12px 20px;border-bottom:1px solid ${K.line2}">
    ${kropka(kolor)}
    <div style="min-width:0"><div style="font-weight:600;font-size:14px;${ELIP}">${esc(r.title)}</div><div style="font-size:12.5px;color:${K.dim};${ELIP}">${esc(r.artist)}${r.duration ? ` <span style="color:${K.dim2}">· ${fmtTime(r.duration)}</span>` : ''}</div></div>
    <div style="min-width:0">${plik}<div style="font:500 11px var(--mono);margin-top:3px;color:${kolor};${ELIP}">${esc(nota)}</div></div>
    <div style="display:flex;gap:6px">${akcje}</div>
  </div>`;
}
function impRysuj(host){
  const d = IMP.dane, p = impPasy();
  $('#impKafle', host).innerHTML = kafel(p.auto.length, 'DOPASOWANE ≥ 0,85', K.ok) + kafel(p.resolve.length, 'DO ROZSTRZYGNIĘCIA', K.warn) + kafel(p.missing.length, 'NIE ZNALEZIONO', K.bad);
  $('#impLista', host).innerHTML = d.wiersze.length ? d.wiersze.map(impWiersz).join('') : `<div class="pusto">Nie znalazłem utworów w tym źródle.</div>`;
  const stopka = $('#impStopka', host);
  if(IMP.utworzona){
    const u = IMP.utworzona;
    stopka.innerHTML = `<span style="font-size:12.5px;color:${K.ok}">✓ playlista „${esc(u.name)}” · ${u.count} ${lm(u.count,'utwór','utwory','utworów')}${u.pominietych ? ` · <span style="color:${K.warn}">${u.pominietych} pominiętych</span>` : ''}</span>
      <button class="btn" id="impKolejnosc" style="margin-left:auto">Kolejność setu →</button><button class="btn acc" id="impEksport">▶ Eksport</button>`;
    $('#impKolejnosc', host).onclick = () => S.pokaz('kolejnosc');
    $('#impEksport', host).onclick = () => S.pokaz('eksport');
    return;
  }
  const brak = p.missing.filter(r => !r.zakolejkowane).length, total = d.counts.total || d.wiersze.length;
  stopka.innerHTML = `<span style="font-size:12.5px;color:${K.dim}">${p.auto.length} z ${total} gotowych do playlisty${p.missing.length ? ' · brakujące dojdą po pobraniu' : ''}${p.resolve.length ? ` · ${p.resolve.length} do rozstrzygnięcia` : ''}</span>
    <button class="btn" id="impSciagnij" style="margin-left:auto" ${brak ? '' : 'disabled'}>Ściągnij brakujące (${brak})</button>
    <button class="btn acc" id="impUtworz" ${p.auto.length ? '' : 'disabled'}>Utwórz playlistę „${esc(IMP.nazwa)}”</button>`;
  $('#impSciagnij', host).onclick = async e => {
    const b = e.currentTarget, items = p.missing.filter(r => !r.zakolejkowane).map(r => ({artist:r.artist, title:r.title, duration:r.duration}));
    b.disabled = true; b.innerHTML = '<span class="spin"></span> dodaję…';
    try{ const j = await api('/api/queue', {method:'POST', body:{items}}); p.missing.forEach(r => { if(!r.zakolejkowane) r.zakolejkowane = true; });
      toast(`✓ ${j.added} ${lm(j.added,'utwór','utwory','utworów')} w kolejce — apka szuka i pobiera po kolei, śledź w Pobieraniach`, 'ok', 6000); S.pollLiczniki(); impRysuj(host); }
    catch(err){ b.disabled = false; b.textContent = `Ściągnij brakujące (${brak})`; }
  };
  $('#impUtworz', host).onclick = async () => {
    const name = await zapytaj({kicker:'Nowa playlista', tytul:'Jak nazwać playlistę?', opis:`${p.auto.length} ${lm(p.auto.length,'utwór','utwory','utworów')} z biblioteki trafi do osobnego folderu playlisty. Pod tą nazwą znajdziesz ją w rekordboksie.`, wartosc:IMP.nazwa, placeholder:'np. Piątek · Smolna', cta:'Utwórz'});
    if(!name) return;
    IMP.nazwa = name;
    const b = $('#impUtworz', host); b.disabled = true; b.innerHTML = '<span class="spin"></span> kopiuję…';
    try{
      const j = await api('/api/playlist/from-selection', {method:'POST', body:{name, files:p.auto.map(r => r.file)}});
      IMP.utworzona = {name:j.name || name, count:j.count, pominietych:j.pominietych||0};
      S.stan.set = {tryb:'playlista', playlista:IMP.utworzona.name}; S.uniewaznTracks();
      toast(`✓ playlista „${IMP.utworzona.name}” · ${j.count} ${lm(j.count,'utwór','utwory','utworów')}`, 'ok'); impRysuj(host);
    }catch(err){ b.disabled = false; b.textContent = `Utwórz playlistę „${IMP.nazwa}”`; }
  };
}
function impPrzygotuj(d){
  const w = [];
  (d.auto||[]).forEach(r => w.push({...r, pas:'auto'}));
  (d.resolve||[]).forEach(r => w.push({...r, pas:'resolve'}));
  (d.missing||[]).forEach(r => w.push({...r, pas:'missing'}));
  return {...d, wiersze:w, counts:d.counts || {total:w.length}};
}
async function impWykonaj(host, zapytanie, etykieta){
  const btn = $('#impGo', host), lista = $('#impLista', host);
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> ROZPOZNAJĘ…';
  lista.innerHTML = `<div class="pusto"><span class="spin"></span> rozpoznaję źródło i dopasowuję do biblioteki po czasie trwania i fingerprincie…</div>`;
  $('#impKafle', host).innerHTML = kafel('—','DOPASOWANE ≥ 0,85',K.dim2) + kafel('—','DO ROZSTRZYGNIĘCIA',K.dim2) + kafel('—','NIE ZNALEZIONO',K.dim2);
  $('#impStopka', host).innerHTML = '';
  IMP.utworzona = null;
  try{
    IMP.mapa = mapaTracks(await S.tracks().catch(()=>[]));
    const d = await zapytanie();
    IMP.dane = impPrzygotuj(d);
    IMP.nazwa = d.name || `${(ORIGIN(d.origin)||'import').toLowerCase()} ${dzis()}`;
    impZrodlo(host, `${ORIGIN(d.origin)} · ${IMP.dane.counts.total}`);
    if(S.biezacy()==='import') S.tytul(`Import · ${ORIGIN(d.origin)} · „${IMP.nazwa}” · ${IMP.dane.counts.total} ${lm(IMP.dane.counts.total,'utwór','utwory','utworów')}`);
    impRysuj(host);
  }catch(e){
    IMP.dane = null; impZrodlo(host, etykieta, K.bad);
    lista.innerHTML = `<div class="pusto" style="color:${K.bad}">✗ ${esc(e.message)}</div>`;
  }finally{ btn.disabled = false; btn.textContent = 'ROZPOZNAJ I DOPASUJ'; }
}
function impRozpoznaj(host){
  const ta = $('#impTekst', host), text = ta.value.trim();
  if(!text){ toast('Najpierw wklej link playlisty albo tracklistę.', 'warn'); ta.focus(); return; }
  return impWykonaj(host, () => api('/api/import', {method:'POST', body:{text}, cicho:true}), wykryjZrodlo(text));
}
function impZPliku(host, f){
  if(!f) return;
  const fd = new FormData(); fd.append('file', f);
  $('#impTekst', host).value = f.name;
  return impWykonaj(host, () => api('/api/playlist/upload', {method:'POST', formData:fd, cicho:true}), `PLIK · ${f.name.split('.').pop().toUpperCase()}`);
}

S.ekran('import', {
  tytul: () => 'Import',
  render(host){
    host.innerHTML = `
      <div class="naglowek"><div><h1>Import</h1><div class="sub">Wklej playlistę — dopasujemy ją do biblioteki po czasie trwania i fingerprincie.</div></div></div>
      <div id="impPanel" style="${PANEL};padding:6px;display:flex;align-items:center;gap:10px">
        <textarea id="impTekst" class="setTekst" rows="1" spellcheck="false" placeholder="https://open.spotify.com/playlist/… — Spotify, Apple Music, Tidal, YouTube, SoundCloud, 1001tracklists albo tracklista tekstem" style="flex:1;padding:12px 16px;font-size:15px;color:${K.muted};background:transparent;border:0;resize:none;line-height:1.35;max-height:150px;font-family:inherit;min-width:0"></textarea>
        <span id="impZrodlo" style="font:500 11px var(--mono);color:${K.ok};display:none;align-items:center;gap:7px;white-space:nowrap"><span style="width:6px;height:6px;border-radius:50%;background:${K.ok}"></span><span></span></span>
        <input type="file" id="impPlik" class="hide" accept=".m3u,.m3u8,.pls,.xml,.nml,.csv,.txt">
        <button class="btn goly" id="impZPliku" title="Playlista z komputera: M3U/M3U8, PLS, XML rekordboxa, NML Traktora, CSV z Serato albo tekst">z pliku…</button>
        <button class="btn acc" id="impGo" style="border-radius:10px;padding:12px 20px;letter-spacing:.04em">ROZPOZNAJ I DOPASUJ</button>
      </div>
      <div class="kafle c3" id="impKafle">${kafel('—','DOPASOWANE ≥ 0,85',K.dim2)}${kafel('—','DO ROZSTRZYGNIĘCIA',K.dim2)}${kafel('—','NIE ZNALEZIONO',K.dim2)}</div>
      <div id="impLista" style="${PANEL};overflow:auto;flex:1;min-height:0"><div class="pusto">Trzy pasy: dopasowane automatycznie (≥ 0,85), do rozstrzygnięcia (inna wersja miksu albo słabsze dopasowanie) i nie znalezione — te ściągniesz z Soulseeka albo kupisz.</div></div>
      <div id="impStopka" style="display:flex;align-items:center;gap:14px;min-height:20px"></div>`;
    const ta = $('#impTekst', host);
    const rosnij = () => { ta.style.height = 'auto'; ta.style.height = Math.min(150, ta.scrollHeight) + 'px'; };
    ta.oninput = () => { rosnij(); const z = wykryjZrodlo(ta.value); impZrodlo(host, z, z && z.startsWith('TEKST') ? K.dim : K.ok); };
    ta.onkeydown = e => { if(e.key==='Enter' && !e.shiftKey && !/\n/.test(ta.value)){ e.preventDefault(); impRozpoznaj(host); } };
    $('#impGo', host).onclick = () => impRozpoznaj(host);
    $('#impZPliku', host).onclick = () => $('#impPlik', host).click();
    $('#impPlik', host).onchange = e => { impZPliku(host, e.target.files[0]); e.target.value = ''; };
    const panel = $('#impPanel', host);
    panel.ondragover = e => { e.preventDefault(); panel.style.borderColor = K.acc; };
    panel.ondragleave = () => { panel.style.borderColor = K.line; };
    panel.ondrop = e => { e.preventDefault(); panel.style.borderColor = K.line; const f = e.dataTransfer.files && e.dataTransfer.files[0]; if(f) impZPliku(host, f); else { const t = e.dataTransfer.getData('text'); if(t){ ta.value = t; ta.oninput(); impRozpoznaj(host); } } };
    on(host, 'click', '#impLista [data-akcja]', async (e, el) => {
      const w = el.closest('[data-i]'), r = IMP.dane && IMP.dane.wiersze[+w.dataset.i]; if(!r) return;
      const akcja = el.dataset.akcja;
      if(akcja==='wez'){ r.wziete = true; impRysuj(host); }
      else if(akcja==='odsluchaj'){ const t = IMP.mapa[nazwaPliku(r.file)] || {}; S.player.graj({file:r.file, title:t.title||r.title, artist:t.artist||r.artist, bpm:t.bpm, camelot:t.camelot, duration:t.duration}); }
      else if(akcja==='szukaj'){ el.disabled = true; try{ const nazwa = await szukajNaSoulseeku({artist:r.artist, title:r.title, duration:r.duration}); if(nazwa){ if(r.pas==='missing') r.zakolejkowane = nazwa; else toast(`✓ pobieram ${nazwa} — po pobraniu podmień w Porządkach`, 'ok'); impRysuj(host); S.pollLiczniki(); } } finally{ el.disabled = false; } }
      else if(akcja==='pobierania') S.pokaz('pobierania');
    });
    document.addEventListener('selekta:player', () => { if(IMP.dane && S.biezacy()==='import') impRysuj(host); });
  },
  load(host){ if(IMP.dane) impRysuj(host); else $('#impTekst', host).focus(); },
});

/* ============================================================
   4b · EKSPORT
   ============================================================ */
const EXP = {cel:'rekordbox', zakres:'set', playlista:'', konw:S.pref.get('usbKonw','aiff'), playlisty:[], rb:null, stan:null, tracks:[], meta:{}};
const CELE = [['rekordbox','rekordbox','XML · hot cue, kolory i oceny zachowane'], ['serato','Serato','.crate w folderze _Serato_'], ['m3u8','M3U8','Traktor, VLC, wszystko inne']];
const CTA = {rekordbox:'▶ WYŚLIJ DO REKORDBOXA', serato:'▶ ZAPISZ CRATE SERATO', m3u8:'▶ ZAPISZ M3U8'};
const zwinDiakrytyki = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ł/g,'l').replace(/Ł/g,'L').replace(/[^\x20-\x7e]/g, '_');
const segItem = (on, extra='') => `padding:5px 11px;border-radius:6px;font-weight:600;font-size:12px;cursor:pointer;${on ? `background:${K.panel2};color:${K.txt}` : `color:${K.dim}`};${extra}`;

function expRysujCel(host){
  const tylkoBiblioteka = EXP.cel!=='rekordbox';
  $('#expCele', host).innerHTML = CELE.map(([id, n, d]) => { const onn = id===EXP.cel;
    return `<div class="setCel ${onn ? 'on' : ''}" data-cel="${id}" style="border:1px solid ${onn ? K.acc : K.line};background:${onn ? 'rgba(255,106,61,.06)' : 'transparent'};border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:6px;cursor:pointer"><span style="font-weight:700;font-size:15px">${n}</span><span style="font-size:12px;color:${K.dim}">${d}</span></div>`; }).join('');
  const dost = EXP.playlisty.filter(p => p.utworow>0);
  if(EXP.zakres==='set' && (tylkoBiblioteka || !dost.length)) EXP.zakres = 'biblioteka';
  if(EXP.zakres==='set' && !dost.some(p => p.name===EXP.playlista)) EXP.playlista = dost[0].name;
  const setOn = EXP.zakres==='set';
  $('#expZakres', host).innerHTML = `<span style="display:flex;gap:2px;background:${K.bg};border:1px solid ${K.line};border-radius:8px;padding:2px">
    <select id="expSet" class="setSeg" ${dost.length && !tylkoBiblioteka ? '' : 'disabled'} title="${dost.length ? 'playlisty utworzone w apce' : 'nie ma jeszcze żadnej playlisty — utwórz ją w Imporcie'}" style="appearance:none;-webkit-appearance:none;border:0;font-family:inherit;${segItem(setOn)}">
      ${dost.length ? dost.map(p => `<option value="${esc(p.name)}" ${p.name===EXP.playlista ? 'selected' : ''}>Set „${esc(p.name)}” · ${p.utworow}</option>`).join('') : '<option>Set — brak playlist</option>'}</select>
    <span data-zakres="biblioteka" style="${segItem(!setOn)}">Cała biblioteka${EXP.meta.count ? ' · '+EXP.meta.count : ''}</span></span>`;
  const uwaga = $('#expUwaga', host);
  const rbGra = EXP.rb && EXP.rb.running && EXP.cel==='rekordbox';
  uwaga.classList.toggle('hide', !(tylkoBiblioteka || rbGra));
  uwaga.innerHTML = [tylkoBiblioteka ? 'Serato i M3U8 zapisują <b>całą bibliotekę</b> w kolejności setu — eksport pojedynczego setu działa dziś tylko do rekordboxa.' : '',
                     rbGra ? '<b>rekordbox jest uruchomiony</b> — zamknij go przed wysłaniem, inaczej nadpisze ustawienia przy wyjściu.' : ''].filter(Boolean).join('<br>');
  $('#expGo', host).textContent = CTA[EXP.cel];
  $('#expCue', host).textContent = (EXP.stan && EXP.stan.utworow) ? 'intro · drop · outro → hot cue A B C · Twoje hot cue mają pierwszeństwo' : 'intro · drop · outro → hot cue A B C';
}
async function expWyslij(host, btn){
  const wynik = $('#expWynik', host), stary = btn.textContent;
  btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${EXP.cel==='rekordbox' ? 'BUDUJĘ PLAYLISTĘ I WSTAWIAM DO REKORDBOXA…' : 'EKSPORTUJĘ…'}`;
  wynik.classList.remove('hide'); wynik.style.color = K.dim; wynik.textContent = '';
  try{
    if(EXP.cel==='rekordbox'){
      const j = EXP.zakres==='set' && EXP.playlista
        ? await api('/api/playlist/export', {method:'POST', body:{name:EXP.playlista}})
        : await api('/api/rekordbox/install', {method:'POST', body:{name:'selekta-set'}});
      pokazWynikRekordboxa(j);
      wynik.style.color = j.ok ? K.ok : K.warn;
      wynik.textContent = j.ok ? `✓ ${j.count} utworów · playlista „${j.playlist}” · ${j.path}` : `⚠ zapisano ${j.path} (${j.count} utworów), ale nie podpięto: ${j.message||'—'}`;
    }else{
      const j = await api('/api/export', {method:'POST', body:{target:EXP.cel, order:'set'}});
      wynik.style.color = K.ok; wynik.textContent = `✓ zapisano ${j.path} (${j.count} utworów)`;
    }
    expRb(host);
  }catch(e){ wynik.style.color = K.bad; wynik.textContent = `✗ ${e.message}`; }
  finally{ btn.disabled = false; btn.textContent = stary; }
}
async function rbPokazStan(host){
  const box = $('#rbStan', host), pill = $('#rbPill', host);
  try{
    const d = EXP.stan = await api('/api/rekordbox/stan', {cicho:true});
    $('#rbZapomnij', host).classList.toggle('hide', !d.utworow);
    if(!d.utworow){
      pill.style.color = K.dim2; pill.textContent = 'NIC NIE WCZYTANO';
      box.innerHTML = `<div style="font-size:12.5px;color:${K.dim}">Nic jeszcze nie wczytano — eksport użyje własnych punktów cue. W rekordboksie: File → Export Collection in xml format.</div>`;
    }else{
      pill.style.color = K.ok; pill.textContent = `${fmtLicz(d.utworow)} ${lm(d.utworow,'UTWÓR','UTWORY','UTWORÓW')} · ${d.hot_cue} HOT CUE`;
      const roz = d.rozbieznosci.length ? `<div style="margin-top:10px;display:flex;flex-direction:column;gap:4px">
          <div style="font-size:12.5px;color:${K.warn}">⚠ ${d.rozbieznosci_razem} ${lm(d.rozbieznosci_razem,'rozbieżność','rozbieżności','rozbieżności')} między naszą analizą a rekordboxem <span class="dim">— pokazuję, nie poprawiam</span></div>
          ${d.rozbieznosci.slice(0,8).map(r => `<div style="font:500 11px var(--mono);color:${K.dim};${ELIP}" title="${esc(r.file)}">${esc(r.file)} — ${esc(r.pole)}: my <b style="color:${K.txt}">${esc(r.nasze)}</b>, rekordbox <b style="color:${K.txt}">${esc(r.rekordbox)}</b>${r.polowa_lub_podwojenie ? ` <span class="warn">(połowa/podwojenie tempa)</span>` : ''}</div>`).join('')}</div>` : '';
      box.innerHTML = `<div style="display:flex;gap:18px;font-size:12.5px;color:${K.dim}"><span><b style="color:${K.txt}">${d.utworow}</b> utworów</span><span><b style="color:${K.ok}">${d.hot_cue}</b> hot cue</span><span><b style="color:${K.txt}">${d.z_kolorem}</b> z kolorem</span><span><b style="color:${K.txt}">${d.z_ocena}</b> z oceną</span></div>
        <div style="font-size:12px;color:${K.dim2};margin-top:4px">Ta praca ma pierwszeństwo przed wyliczeniami apki.</div>${d.zmienne_tempo ? `<div style="font-size:12px;color:${K.warn};margin-top:4px">⚠ ${d.zmienne_tempo} ${lm(d.zmienne_tempo,'utwór ma','utwory mają','utworów ma')} w rekordboksie zmienne tempo — eksport odda tylko pierwszy znacznik siatki; po wysłaniu sprawdź siatkę tych utworów.</div>` : ''}${roz}`;
    }
  }catch(e){ pill.style.color = K.bad; pill.textContent = 'BŁĄD'; box.innerHTML = `<span class="bad" style="font-size:12.5px">✗ ${esc(e.message)}</span>`; }
  expRysujCel(host);
}
async function rbWczytaj(host, zapytanie){
  const prog = $('#rbProg', host);
  prog.innerHTML = '<span class="spin"></span> czytam XML…'; prog.style.color = K.dim;
  try{
    const d = await zapytanie();
    prog.innerHTML = `wczytano <b style="color:${K.txt}">${d.dopasowane}</b> z ${d.w_xml} utworów` + (d.z_reczna_praca ? ` · <b style="color:${K.txt}">${d.z_reczna_praca}</b> z ręczną pracą` : '') + (d.cue_selekty_pominiete ? ` · ${d.cue_selekty_pominiete} cue ${d.plik_selekty ? 'z tego pliku to nasza analiza' : 'to nasze intro/drop/outro'} — nie liczę ich jako Twojej pracy` : '') + (d.nieodnalezionych ? ` · <span class="warn">${d.nieodnalezionych} nie ma w bibliotece</span>` : '');
    rbPokazStan(host);
  }catch(e){ prog.style.color = K.bad; prog.textContent = `✗ ${e.message}`; }
}
async function expRb(host){
  try{ EXP.rb = await api('/api/rekordbox', {cicho:true}); }catch(e){ EXP.rb = null; }
  if(S.biezacy()==='eksport') S.tytul(EXP.rb && EXP.rb.installed ? `Eksport · rekordbox wykryty${EXP.rb.running ? ' · uruchomiony' : ''}` : 'Eksport');
  const odp = $('#rbOdepnij', host); if(odp) odp.classList.toggle('hide', !(EXP.rb && EXP.rb.linked));
  expRysujCel(host);
}
function usbRysuj(host){
  const tr = EXP.tracks, glowne = tr.filter(t => !String(t.rel||'').includes('/'));
  const wav = glowne.filter(t => t.ext==='wav').length, bezOkladki = glowne.filter(t => !t.has_cover).length;
  const zDiak = tr.map(t => t.file).find(f => /[^\x00-\x7f]/.test(f));
  let przyklad = '—';
  if(zDiak){ const seg = zDiak.replace(/\.[a-z0-9]{2,5}$/i,'').split(' - ').find(s => /[^\x00-\x7f]/.test(s)) || zDiak; przyklad = `${seg} → ${zwinDiakrytyki(seg)}`; }
  const w = (kolor, tekst, prawa='') => `<div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid ${K.line2};font-size:13.5px">${kropka(kolor)}<span style="min-width:0;${ELIP}">${tekst}</span>${prawa ? `<span style="margin-left:auto;font:500 11.5px var(--mono);color:${K.dim};white-space:nowrap">${prawa}</span>` : ''}</div>`;
  const mb = glowne.reduce((s,t) => s+(t.size_mb||0), 0);
  const nicWGlownym = tr.length && !glowne.length;
  $('#usbLista', host).innerHTML =
    (nicWGlownym ? w(K.warn, 'wszystkie pliki leżą w podfolderach — na USB idzie tylko główny folder biblioteki', `0 z ${tr.length}`)
                 : w(K.ok, 'płaski folder, bez podkatalogów', glowne.length!==tr.length ? `${glowne.length} z ${tr.length} plików leży w głównym folderze` : '')) +
    w(K.ok, 'nazwy FAT32-safe, diakrytyki zwinięte', esc(przyklad)) +
    (wav ? (EXP.konw==='keep' ? w(K.warn, `${wav} ${lm(wav,'plik WAV zostaje','pliki WAV zostają','plików WAV zostaje')} bez konwersji`, 'CDJ czyta WAV, ale bez tagów') : w(K.warn, `${wav} ${lm(wav,'plik WAV zostanie przekonwertowany','pliki WAV zostaną przekonwertowane','plików WAV zostanie przekonwertowanych')}`, `~${wav*20} s`))
         : w(K.ok, 'brak plików WAV — nic do konwersji')) +
    w(bezOkladki ? K.warn : K.ok, bezOkladki ? `${bezOkladki} ${lm(bezOkladki,'plik bez okładki','pliki bez okładki','plików bez okładki')} — dociągnij w Porządkach` : 'okładki osadzone, tagi po naprawie').replace('border-bottom:1px solid '+K.line2, 'border-bottom:0');
  $('#usbN', host).textContent = glowne.length;
  $('#usbMb', host).textContent = `${lm(glowne.length,'utwór','utwory','utworów')} · ${fmtLicz(Math.round(mb))} MB${nicWGlownym ? ' · nic do skopiowania' : ''}`;
  const go = $('#usbGo', host); go.disabled = !!nicWGlownym; go.title = nicWGlownym ? 'przenieś utwory do głównego folderu biblioteki albo wskaż go jako folder' : '';
  $$('#usbKonw span', host).forEach(s => { const onn = s.dataset.k===EXP.konw; s.style.background = onn ? K.panel2 : 'transparent'; s.style.color = onn ? K.txt : K.dim; });
}
async function usbGo(host, btn){
  const dest = $('#usbDest', host).value.trim(), wynik = $('#usbWynik', host);
  if(!dest){ wynik.style.color = K.warn; wynik.textContent = 'Podaj folder docelowy albo pendrive.'; return; }
  S.pref.set('usbDest', dest);
  btn.disabled = true; wynik.style.color = K.dim; wynik.innerHTML = '<span class="spin"></span> kopiuję na USB…';
  try{ const j = await api('/api/usb', {method:'POST', body:{dest, convert:EXP.konw}, cicho:true});
    wynik.style.color = K.ok; wynik.textContent = `✓ skopiowane ${j.copied}, skonwertowane ${j.converted}, pominięte ${j.skipped} · ${fmtLicz(j.mb)} MB`; }
  catch(e){ wynik.style.color = K.bad; wynik.textContent = `✗ ${e.message}`; }
  finally{ btn.disabled = false; }
}

S.ekran('eksport', {
  tytul: () => 'Eksport',
  render(host){
    host.classList.add('przewijany');
    const rzad = (etyk, tresc) => `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid ${K.line};font-size:13.5px"><span>${etyk}</span>${tresc}</div>`;
    host.innerHTML = `
      <div><h1 class="h1">Eksport</h1><div class="sub">Set w kolejności harmonicznej trafia tam, gdzie grasz.</div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;flex:1;min-height:0">
        <div style="display:flex;flex-direction:column;gap:16px">
          <div style="${PANEL};padding:22px 24px;display:flex;flex-direction:column;gap:16px">
            <div style="${ETYK}">CEL</div>
            <div id="expCele" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px"></div>
            <div style="display:flex;flex-direction:column;gap:10px">
              ${rzad('Zakres', '<span id="expZakres"></span>')}
              ${rzad('Kolejność', `<span style="font:500 12px var(--mono);color:${K.muted}">harmoniczna (Camelot, energia ↑)</span>`)}
              ${rzad('Cue z analizy', `<span id="expCue" style="font:500 12px var(--mono);color:${K.muted};text-align:right">intro · drop · outro → hot cue A B C</span>`)}
            </div>
            <div id="expUwaga" class="uwaga hide"></div>
            <button class="btn acc duzy" id="expGo" style="padding:14px 22px;align-self:flex-start">▶ WYŚLIJ DO REKORDBOXA</button>
            <div id="expWynik" class="hide" style="font:500 12px var(--mono);color:${K.dim};line-height:1.5;word-break:break-all"></div>
            <span class="setLink hide" id="rbOdepnij" style="align-self:flex-start" title="Przywraca w ustawieniach rekordboxa tylko wpis „importowana biblioteka” sprzed pierwszego wysłania z selekty — reszta ustawień zostaje">odepnij sety selekty od rekordboxa</span>
          </div>
          <div style="${PANEL};padding:22px 24px;display:flex;flex-direction:column;gap:12px;flex:1">
            <div style="display:flex;align-items:center;gap:12px"><div style="${ETYK}">WYMIANA Z REKORDBOXEM</div><span id="rbPill" style="margin-left:auto;font:500 11px var(--mono);color:${K.dim2}">…</span></div>
            <div style="font-size:13px;color:${K.dim};line-height:1.5">Twoje hot cue, kolory, oceny i komentarze są zapamiętane — przy eksporcie oddamy je nietknięte zamiast zastąpić własnym wyliczeniem.</div>
            <div id="rbStan"></div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <input type="file" id="rbPlik" accept=".xml" class="hide">
              <button class="btn sr" id="rbWczytaj" style="background:transparent">Wczytaj nowy XML</button>
              <button class="btn sr cichy" id="rbOdswiez">Odśwież stan</button>
              <span class="setLink" id="rbSciezka" title="Wskaż XML rekordboxa ścieżką na dysku">ze ścieżki…</span>
              <button class="btn sr goly zly hide" id="rbZapomnij" style="margin-left:auto">Zapomnij dane z rekordboxa</button>
            </div>
            <div id="rbProg" style="font:500 12px var(--mono);color:${K.dim};line-height:1.5"></div>
          </div>
        </div>
        <div style="${PANEL};padding:22px 24px;display:flex;flex-direction:column;gap:18px">
          <div style="display:flex;align-items:center;gap:12px"><div style="${ETYK}">USB POD CDJ</div>
            <label style="margin-left:auto;display:flex;align-items:center;gap:7px;font:500 11px var(--mono);color:${K.ok};min-width:0" title="Wolumin albo folder docelowy — pendrive pod CDJ"><span style="width:6px;height:6px;border-radius:50%;background:${K.ok};flex-shrink:0"></span><input id="usbDest" value="${esc(S.pref.get('usbDest','/Volumes/DJ_USB'))}" spellcheck="false" style="background:transparent;border:0;border-bottom:1px dashed ${K.line3};color:${K.ok};font:500 11px var(--mono);width:210px;text-align:right;padding:2px 0"></label></div>
          <div style="display:flex;flex-direction:column;gap:6px">
            <div style="font-size:12.5px;color:${K.dim}">Konwersja WAV</div>
            <div id="usbKonw" style="display:flex;gap:2px;background:${K.bg};border:1px solid ${K.line};border-radius:8px;padding:2px;width:max-content">
              <span data-k="aiff" style="padding:6px 12px;border-radius:6px;font-weight:600;font-size:12.5px;cursor:pointer">WAV → AIFF</span><span data-k="flac" style="padding:6px 12px;border-radius:6px;font-weight:600;font-size:12.5px;cursor:pointer">WAV → FLAC</span><span data-k="keep" style="padding:6px 12px;border-radius:6px;font-weight:600;font-size:12.5px;cursor:pointer">bez konwersji</span>
            </div>
          </div>
          <div id="usbLista" style="display:flex;flex-direction:column;border-top:1px solid ${K.line}"></div>
          <div style="margin-top:auto;display:flex;flex-direction:column;gap:12px">
            <div style="display:flex;align-items:baseline;gap:8px"><span id="usbN" style="font-size:28px;font-weight:700;letter-spacing:-.02em;line-height:1">—</span><span id="usbMb" style="font-size:13px;color:${K.dim}">utworów</span></div>
            <button class="btn obrys" id="usbGo" style="border-radius:10px;padding:13px 22px;font-size:13.5px;align-self:flex-start">PRZYGOTUJ USB</button>
            <div id="usbWynik" style="font:500 12px var(--mono);color:${K.dim};line-height:1.5">Kopiuje płasko z głównego folderu biblioteki, nazwy FAT32-safe, zwija diakrytyki.</div>
          </div>
        </div>
      </div>`;
    on(host, 'click', '#expCele [data-cel]', (e, el) => { EXP.cel = el.dataset.cel; expRysujCel(host); });
    on(host, 'click', '#expZakres [data-zakres]', () => { EXP.zakres = 'biblioteka'; expRysujCel(host); });
    on(host, 'change', '#expSet', (e, el) => { EXP.zakres = 'set'; EXP.playlista = el.value; S.stan.set = {tryb:'playlista', playlista:el.value}; expRysujCel(host); });
    $('#expGo', host).onclick = e => expWyslij(host, e.currentTarget);
    $('#rbWczytaj', host).onclick = () => $('#rbPlik', host).click();
    $('#rbPlik', host).onchange = e => { const f = e.target.files[0]; if(!f) return; const fd = new FormData(); fd.append('file', f); rbWczytaj(host, () => api('/api/rekordbox/wczytaj', {method:'POST', formData:fd, cicho:true})); e.target.value = ''; };
    $('#rbSciezka', host).onclick = async () => { const p = await zapytaj({kicker:'Wymiana z rekordboxem', tytul:'Ścieżka do XML-a', opis:'File → Export Collection in xml format, potem wskaż zapisany plik.', placeholder:'~/Documents/rekordbox.xml', cta:'Wczytaj'}); if(p) rbWczytaj(host, () => api('/api/rekordbox/wczytaj-sciezke', {method:'POST', body:{path:p}, cicho:true})); };
    $('#rbOdswiez', host).onclick = () => { rbPokazStan(host); expRb(host); };
    $('#rbOdepnij', host).onclick = async () => { const w = $('#expWynik', host); w.classList.remove('hide');
      try{ const j = await api('/api/rekordbox/restore', {method:'POST', body:{}}); w.style.color = j.ok ? K.ok : K.warn; w.textContent = (j.ok ? '✓ ' : '⚠ ') + j.message; expRb(host); }
      catch(e){ w.style.color = K.bad; w.textContent = `✗ ${e.message}`; } };
    $('#rbZapomnij', host).onclick = async e => { e.currentTarget.disabled = true; try{ const j = await api('/api/rekordbox/zapomnij', {method:'POST', body:{}}); $('#rbProg', host).textContent = `zapomniano ${j.usunietych} ${lm(j.usunietych,'utwór','utwory','utworów')}`; rbPokazStan(host); } finally{ e.currentTarget.disabled = false; } };
    on(host, 'click', '#usbKonw span', (e, el) => { EXP.konw = el.dataset.k; S.pref.set('usbKonw', EXP.konw); usbRysuj(host); });
    $('#usbDest', host).onchange = e => S.pref.set('usbDest', e.target.value.trim());
    $('#usbGo', host).onclick = e => usbGo(host, e.currentTarget);
  },
  async load(host){
    const z = S.stan.set;
    if(z.tryb==='playlista' && z.playlista){ EXP.zakres = 'set'; EXP.playlista = z.playlista; }
    const [pl, tr] = await Promise.all([api('/api/playlisty', {cicho:true}).catch(() => ({playlisty:[]})), S.tracks().catch(() => [])]);
    EXP.playlisty = pl.playlisty || []; EXP.tracks = tr; EXP.meta = S.stan.tracksMeta || {};
    expRysujCel(host); usbRysuj(host);
    await Promise.all([rbPokazStan(host), expRb(host)]);
  },
});

/* ============================================================
   4c · POBIERANIA
   ============================================================ */
const POB = {timer:null, nr:0, podejrzane:{}, doneWidziane:null, sprawdzone:new Set(), sprawdzam:false};
const ST = {active:['POBIERAM',K.acc,true], queued:['W KOLEJCE',K.warn,false], searching:['SZUKAM',K.info,true], waiting:['CZEKA',K.dim,false],
            done:['GOTOWE',K.ok,false], verified:['ZWERYFIKOWANE',K.ok,false], podejrzany:['DO SPRAWDZENIA',K.warn,false], failed:['BŁĄD',K.bad,false]};
const RANGA = {active:0, searching:1, queued:2, waiting:3, podejrzany:4, failed:5, done:6, verified:7};
const fmtPredkosc = kbs => kbs>=1000 ? `${fmtPL(kbs/1000,1)} MB/s` : `${kbs||0} kB/s`;
const widoczny = host => document.body.contains(host) && !host.classList.contains('hide') && S.biezacy()==='pobierania';

function pobWiersz(w, i){
  const [etyk, kolor, puls] = ST[w.st] || ST.queued;
  const zywy = w.typ==='transfer' && (w.status==='active' || w.status==='queued');
  const pct = w.typ==='transfer' ? (w.status==='done' || w.status==='failed' ? 100 : (w.percent||0)) : 0;
  const barBg = w.st==='failed' ? K.bad : (w.st==='done' || w.st==='verified' ? K.ok : (w.st==='podejrzany' ? K.warn : K.acc));
  let akcje = '';
  if(zywy) akcje = `<button class="btn mini cichy" data-akcja="anuluj">Anuluj</button>`;
  else if(w.st==='failed') akcje = `<button class="btn mini acc" data-akcja="ponow">Pobierz ponownie</button>`;
  else if(w.st==='podejrzany') akcje = `<button class="btn mini cichy" data-akcja="porzadki">Porządki →</button>`;
  return `<div class="setWiersz" data-i="${i}" style="display:grid;grid-template-columns:96px minmax(0,1fr) 120px auto;gap:18px;align-items:center;padding:14px 20px;border-bottom:1px solid ${K.line2}">
    <span style="display:flex;align-items:center;gap:8px;font:600 10px var(--mono);letter-spacing:.1em;color:${kolor}"><span style="width:7px;height:7px;border-radius:50%;background:${kolor};flex-shrink:0;animation:${puls ? 'pulse 1.2s ease-in-out infinite' : 'none'}"></span>${etyk}</span>
    <div style="min-width:0">
      <div style="font-weight:600;font-size:14px;${ELIP}">${esc(w.title)}<span style="font-weight:400;font-size:12.5px;color:${K.dim};margin-left:8px">${esc(w.artist)}</span></div>
      <div style="font:500 11.5px var(--mono);color:${K.dim};margin-top:3px;${ELIP}">${esc(w.file||'—')} · ${esc(w.user||'—')}</div>
      <div style="font-size:12px;margin-top:4px;color:${kolor};${ELIP}" title="${esc(w.nota)}">${esc(w.nota)}</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end"><span style="font:500 11px var(--mono);color:${K.dim}">${w.status==='active' ? Math.round(pct)+'%' : ''}</span><div style="width:120px;height:3px;background:${K.line};border-radius:2px;overflow:hidden"><div style="height:100%;border-radius:2px;width:${pct}%;background:${barBg};transition:width .4s"></div></div></div>
    <div style="display:flex;gap:6px;min-width:150px;justify-content:flex-end">${akcje}</div>
  </div>`;
}
function pobModel(t, q){
  const wiersze = [];
  const items = (t && t.items) || [], jobs = (q && q.jobs) || [];
  items.forEach(it => {
    const {artist, title} = rozbijNazwe(it.name);
    let st = it.status, nota;
    const pod = POB.podejrzane[it.name];
    if(it.status==='active') nota = `${it.percent}% · ${fmtPL(it.done_mb,1)}/${fmtPL(it.size_mb,1)} MB · ${fmtPredkosc(it.speed_kbs)}${it.remaining ? ' · zostało '+it.remaining : ''}`;
    else if(it.status==='queued') nota = `czeka w kolejce u ${it.user}${it.state_raw ? ' · '+it.state_raw : ''}`;
    else if(it.status==='failed') nota = it.state_raw || 'błąd';
    else if(pod){ st = 'podejrzany'; nota = pod.powod || 'plik nie zgadza się z zamówieniem'; }
    else if(POB.sprawdzone.has(it.name)){ st = 'verified'; nota = `zweryfikowany po pobraniu · ${fmtPL(it.size_mb,1)} MB · od ${it.user}`; }
    else nota = `${fmtPL(it.size_mb,1)} MB · od ${it.user}`;
    wiersze.push({typ:'transfer', st, status:it.status, artist, title, file:it.name, user:it.user, nota, percent:it.percent, id:it.id, name:it.name, kiedy:it.requested_at||''});
  });
  const nazwy = new Set(items.map(i => i.name));
  jobs.forEach(j => {
    const wTransferach = j.file && nazwy.has(nazwaPliku(j.file));
    if(j.status==='done' || (j.status==='queued' && wTransferach)) return;
    let nota;
    if(j.status==='searching') nota = `szukam na Soulseeku${j.attempts ? ` · próba ${j.attempts}` : ''}${j.detail ? ' · '+j.detail : ''}`;
    else if(j.status==='waiting') nota = `czeka na swoją kolej${j.detail ? ' · '+j.detail : ''}${q.paused_for_s ? ` · przerwa ${q.paused_for_s} s` : ''}`;
    else if(j.status==='queued') nota = `zlecone do slskd${j.detail ? ' · '+j.detail : ''}`;
    else nota = j.detail || 'nie udało się';
    wiersze.push({typ:'kolejka', st:j.status, status:j.status, artist:j.artist, title:j.title, file:j.file ? nazwaPliku(j.file) : '', user:'', nota, artist0:j.artist, title0:j.title, duration:j.duration});
  });
  wiersze.sort((a,b) => (RANGA[a.st]??9) - (RANGA[b.st]??9) || (b.kiedy||'').localeCompare(a.kiedy||''));
  return wiersze;
}
async function pobSprawdz(host, reczne){
  if(POB.sprawdzam) return; POB.sprawdzam = true;
  const b = $('#pobSprawdz', host); if(b){ b.disabled = true; b.innerHTML = '<span class="spin"></span> porównuję z próbkami z iTunes…'; }
  try{
    const d = await api('/api/pobrania/sprawdz', {method:'POST', cicho:true});
    (POB.ostatnieDone||[]).forEach(n => POB.sprawdzone.add(n));
    if(reczne) toast(d.podejrzanych ? `${d.podejrzanych} ${lm(d.podejrzanych,'pobranie budzi','pobrania budzą','pobrań budzi')} wątpliwości — decyzja czeka w Porządkach` : `sprawdzono ${d.sprawdzonych} ${lm(d.sprawdzonych,'pobranie','pobrania','pobrań')}, wszystko się zgadza`, d.podejrzanych ? 'warn' : 'ok');
    else if(d.podejrzanych) toast(`${d.podejrzanych} ${lm(d.podejrzanych,'pobranie budzi','pobrania budzą','pobrań budzi')} wątpliwości — decyzja czeka w Porządkach`, 'warn', 7000);
    S.pollLiczniki();
  }catch(e){ if(reczne) toast(e.message, 'bad'); }
  finally{ POB.sprawdzam = false; if(b){ b.disabled = false; b.textContent = 'Sprawdź pobrane'; } pobTick(host); }
}
async function pobTick(host){
  if(!widoczny(host)){ clearInterval(POB.timer); POB.timer = null; return; }
  if(document.hidden) return;
  const nr = ++POB.nr;
  const [t, q, st, dec] = await Promise.all([
    api('/api/transfers', {cicho:true}).catch(() => null), api('/api/queue', {cicho:true}).catch(() => null), S.status(),
    api('/api/decyzje?wszystkie=true', {cicho:true}).catch(() => null)]);
  if(nr!==POB.nr || !widoczny(host)) return;
  POB.podejrzane = {};
  ((dec && dec.decyzje) || []).forEach(d => { if(d.rodzaj==='podejrzany' && d.stan==='czeka') (d.usun||[]).forEach(p => { POB.podejrzane[nazwaPliku(p)] = d; }); });
  const tc = (t && t.counts) || {}, qc = (q && q.counts) || {};
  const wiersze = pobModel(t, q);
  const pobieram = tc.active||0, kolejka = (tc.queued||0) + (qc.waiting||0) + (qc.searching||0) + wiersze.filter(w => w.typ==='kolejka' && w.st==='queued').length;
  const podejrzane = wiersze.filter(w => w.st==='podejrzany').length;
  const zweryfikowane = (tc.done||0) - podejrzane, powtorka = (tc.failed||0) + (qc.failed||0) + podejrzane;
  $('#pobKafle', host).innerHTML = kafel(pobieram,'POBIERAM',K.acc) + kafel(kolejka,'W KOLEJCE / SZUKAM',K.warn) + kafel(Math.max(0,zweryfikowane),'ZWERYFIKOWANE',K.ok) + kafel(powtorka,'DO POWTÓRKI',K.bad);

  // pastylka slskd
  const pill = $('#pobPill', host), dot = pill.children[0];
  const dostepny = !!(t && t.available);
  const predkosc = ((t && t.items) || []).filter(i => i.status==='active').reduce((s,i) => s+(i.speed_kbs||0), 0);
  const kolorSt = !dostepny ? K.bad : ({green:K.ok, amber:K.warn, red:K.bad}[st.level] || K.dim);
  dot.style.background = kolorSt; dot.style.boxShadow = `0 0 8px ${kolorSt}`;
  pill.lastChild.textContent = !dostepny ? 'slskd niepodłączony · sprawdź Ustawienia' : `slskd · ${fmtPredkosc(predkosc)} ↓ · ${pobieram} ${lm(pobieram,'aktywne','aktywne','aktywnych')}${st.level!=='green' ? ' · '+st.label : ''}`;
  pill.title = st.hint || '';

  const stop = $('#pobStop', host); stop.disabled = !(qc.waiting||0); stop.title = qc.waiting ? `anuluje ${qc.waiting} ${lm(qc.waiting,'utwór czekający','utwory czekające','utworów czekających')} w kolejce apki — trwające pobrania w slskd zostają` : 'kolejka apki jest pusta';
  $('#pobWyczysc', host).classList.toggle('hide', !((qc.done||0) + (qc.failed||0)));
  $('#pobSprawdz', host).classList.toggle('hide', !(tc.done||0));

  const lista = $('#pobLista', host);
  if(!wiersze.length) lista.innerHTML = `<div class="pusto">${dostepny ? 'Nic jeszcze nie pobierano. Brakujące utwory z Importu trafiają tutaj.' : '⚠ slskd niepodłączony — sprawdź zakładkę Ustawienia.'}</div>`;
  else lista.innerHTML = (dostepny ? '' : `<div style="padding:12px 20px;border-bottom:1px solid ${K.line2};font-size:12.5px;color:${K.warn}">⚠ slskd niepodłączony — pokazuję tylko kolejkę apki; pobierania ruszą, gdy wróci połączenie.</div>`) + wiersze.map(pobWiersz).join('');
  POB.wiersze = wiersze;
  S.badge('pobierania', pobieram + (tc.queued||0) + (qc.waiting||0) + (qc.searching||0));
  S.tytul(`Pobierania · slskd · ${pobieram} ${lm(pobieram,'aktywne','aktywne','aktywnych')}`);

  // weryfikacja po pobraniu: uruchamiamy, gdy przybyło zakończone pobranie
  const doneTeraz = ((t && t.items) || []).filter(i => i.status==='done').map(i => i.name);
  if(POB.doneWidziane && doneTeraz.some(n => !POB.doneWidziane.includes(n))){ POB.ostatnieDone = doneTeraz; pobSprawdz(host, false); }
  POB.doneWidziane = doneTeraz; POB.ostatnieDone = doneTeraz;
}

S.ekran('pobierania', {
  tytul: () => 'Pobierania',
  render(host){
    host.innerHTML = `
      <div style="display:flex;align-items:flex-end;gap:16px">
        <div><h1 class="h1">Pobierania</h1><div class="sub">Każdy plik po pobraniu przechodzi weryfikację: integralność, tożsamość odsłuchem, prawdziwa jakość.</div></div>
        <div id="pobPill" style="margin-left:auto;display:flex;align-items:center;gap:10px;${PANEL};border-radius:10px;padding:10px 14px;font:500 11.5px var(--mono);color:${K.dim};white-space:nowrap"><span style="width:7px;height:7px;border-radius:50%;background:${K.line3};flex-shrink:0"></span><span>slskd · sprawdzam…</span></div>
        <button class="btn goly hide" id="pobSprawdz" title="Porównaj pobrane pliki z próbkami z iTunes — podejrzane trafią do Porządków">Sprawdź pobrane</button>
        <button class="btn goly hide" id="pobWyczysc" title="usuń z kolejki apki zadania zakończone i nieudane">Wyczyść zakończone</button>
        <button class="btn cichy" id="pobStop" disabled>Zatrzymaj kolejkę</button>
      </div>
      <div class="kafle c4" id="pobKafle">${kafel('—','POBIERAM',K.dim2)}${kafel('—','W KOLEJCE / SZUKAM',K.dim2)}${kafel('—','ZWERYFIKOWANE',K.dim2)}${kafel('—','DO POWTÓRKI',K.dim2)}</div>
      <div id="pobLista" style="${PANEL};overflow:auto;flex:1;min-height:0"><div class="pusto"><span class="spin"></span> czytam stan pobrań…</div></div>`;
    $('#pobStop', host).onclick = async e => { const b = e.currentTarget; b.disabled = true; try{ const j = await api('/api/queue/cancel', {method:'POST'}); toast(`anulowano ${j.cancelled} ${lm(j.cancelled,'oczekujący','oczekujące','oczekujących')}`, 'warn'); } finally{ pobTick(host); } };
    $('#pobWyczysc', host).onclick = async e => { const b = e.currentTarget; b.disabled = true; try{ const j = await api('/api/queue/clear', {method:'POST'}); toast(`usunięto ${j.removed} ${lm(j.removed,'zakończone','zakończone','zakończonych')} z kolejki`, 'ok'); } finally{ b.disabled = false; pobTick(host); } };
    $('#pobSprawdz', host).onclick = () => pobSprawdz(host, true);
    on(host, 'click', '#pobLista [data-akcja]', async (e, el) => {
      const w = POB.wiersze && POB.wiersze[+el.closest('[data-i]').dataset.i]; if(!w) return;
      const akcja = el.dataset.akcja; el.disabled = true; el.textContent = '…';
      try{
        if(akcja==='anuluj'){ await api('/api/transfers/cancel', {method:'POST', body:{user:w.user, id:w.id}}); pobTick(host); }
        else if(akcja==='porzadki') S.pokaz('porzadki');
        else if(akcja==='ponow'){
          if(w.typ==='transfer'){ const j = await api('/api/redownload', {method:'POST', body:{file:w.name}}); el.textContent = '✓ w życzeniach'; toast(`✓ ${j.queued} — na liście życzeń, apka sprawdzi Soulseek ponownie`, 'ok'); }
          else { const j = await api('/api/queue', {method:'POST', body:{items:[{artist:w.artist0, title:w.title0, duration:w.duration}]}}); el.textContent = j.added ? '✓ w kolejce' : 'już w kolejce'; pobTick(host); }
        }
      }catch(err){ el.disabled = false; el.textContent = akcja==='anuluj' ? 'Anuluj' : 'Pobierz ponownie'; }
    });
  },
  load(host){
    POB.doneWidziane = null;
    pobTick(host);
    if(!POB.timer) POB.timer = setInterval(() => pobTick(host), 3000);
  },
});
})();
