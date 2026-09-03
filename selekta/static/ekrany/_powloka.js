/* ============================================================
   S — wspólne API powłoki dla ekranów (static/ekrany/*.js).

   Ekran rejestruje się przez S.ekran(id, {tytul, pelny, render, load}):
     tytul  — tekst paska tytułu (string albo funkcja zwracająca string)
     pelny  — true: ekran zajmuje całe okno (bez nawigacji): kreator, wybór
              trybu, „zanim zaczniesz", onboarding
     render(host) — buduje DOM raz (host = <section class="ekran">)
     load(host, arg) — odświeża dane przy każdym wejściu (opcjonalne)

   Pomocnicze: S.api, S.esc, S.fmtTime, S.fmtMB, S.CAM, S.K (kolory),
   S.toast, S.arkusz/S.zamknijArkusz, S.player.graj/stop, S.badge,
   S.tracks (cache /api/tracks), S.status (cache /api/status), S.jezyk.
   Ekrany wystawiają dla siebie nawzajem: S.otworzSzczegoly(file)
   (biblioteka.js), S.wybierzWynik(utwor) (kreator.js).
   ============================================================ */
window.S = (() => {
  const K = {acc:'#ff6a3d', accH:'#ff8a66', ok:'#5cd6a0', warn:'#f0b64a', bad:'#ff5a6a', info:'#7a9cff',
             txt:'#f2ece6', muted:'#c9c0b8', dim:'#8f857c', dim2:'#5e5650',
             line:'#2a2522', line2:'#1d1917', line3:'#3a3330', panel:'#171412', panel2:'#1e1a17', bg:'#0f0d0c', hover:'#1a1613'};
  // kolory koła Camelot z projektu (A = moll, B = dur)
  const CAM = {'1A':'#7de0c6','2A':'#8ee0a3','3A':'#b8e08a','4A':'#e0d97a','5A':'#f0b64a','6A':'#ff9b6b','7A':'#ff7f8a','8A':'#e08ad0','9A':'#b58ae0','10A':'#8a9ce0','11A':'#7ac0e0','12A':'#7ad9e0',
               '1B':'#5cd6a0','2B':'#6fd67e','3B':'#a3d66a','4B':'#d6cc5c','5B':'#e0a13a','6B':'#ff8656','7B':'#ff6a7a','8B':'#d675c6','9B':'#a575d6','10B':'#7587d6','11B':'#63b0d6','12B':'#63ccd6'};
  const EKRANY = {};
  const stan = {biezacy:null, status:null, statusKiedy:0, tracks:null, tracksKiedy:0, folder:'', wybrane:new Set()};
  const PELNE = new Set();

  // ---------- drobiazgi ----------
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtTime = s => { if(!isFinite(s)||s==null) return '—'; s=Math.max(0,Math.round(s)); const m=Math.floor(s/60), r=s%60; return `${m}:${String(r).padStart(2,'0')}`; };
  const fmtMB = b => b==null ? '' : (b >= 1e9 ? (b/1e9).toFixed(1).replace('.',',')+' GB' : (b/1e6).toFixed(1).replace('.',',')+' MB');
  const fmtLicz = n => (n==null ? '—' : String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '));
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];
  function on(root, evt, sel, fn){ root.addEventListener(evt, e => { const el = e.target.closest(sel); if(el && root.contains(el)) fn(e, el); }); }
  const nazwaPliku = p => String(p||'').split('/').pop();

  // ---------- zapytania ----------
  async function api(url, opts={}){
    const {method='GET', body, formData, cicho=false} = opts;
    const init = {method, headers:{}};
    if(formData){ init.body = formData; }
    else if(body !== undefined){ init.headers['Content-Type']='application/json'; init.body = JSON.stringify(body); }
    let r;
    try{ r = await fetch(url, init); }
    catch(e){ if(!cicho) toast('brak połączenia z aplikacją', 'bad'); throw e; }
    const ct = r.headers.get('content-type') || '';
    const d = ct.includes('json') ? await r.json().catch(()=>null) : await r.text();
    if(!r.ok){
      const det = d && d.detail;
      const msg = typeof det === 'string' ? det : (det ? JSON.stringify(det) : `HTTP ${r.status}`);
      if(!cicho) toast(msg, 'bad');
      const err = new Error(msg); err.status = r.status; err.dane = d; throw err;
    }
    return d;
  }
  async function status(force=false){
    if(!force && stan.status && Date.now()-stan.statusKiedy < 4000) return stan.status;
    try{ stan.status = await api('/api/status', {cicho:true}); }
    catch(e){ stan.status = {level:'red', label:'brak połączenia z apką', hint:''}; }
    stan.statusKiedy = Date.now();
    return stan.status;
  }
  async function tracks(force=false){
    if(!force && stan.tracks && Date.now()-stan.tracksKiedy < 15000) return stan.tracks;
    const d = await api('/api/tracks');
    stan.tracks = Array.isArray(d) ? d : (d.tracks || d.rows || d.items || []);
    stan.tracksMeta = Array.isArray(d) ? {} : d;
    stan.tracksKiedy = Date.now();
    if(stan.tracksMeta.folder) stan.folder = stan.tracksMeta.folder;
    return stan.tracks;
  }
  function uniewaznTracks(){ stan.tracks = null; }

  // ---------- powiadomienia ----------
  function toast(msg, typ='info', ms=4200){
    const el = document.createElement('div'); el.className = 'toast '+typ; el.textContent = msg;
    $('#toasty').appendChild(el);
    setTimeout(()=>{ el.style.opacity='0'; el.style.transition='opacity .3s'; setTimeout(()=>el.remove(), 320); }, ms);
    return el;
  }

  // ---------- arkusz (nakładka jak w 2b/3c) ----------
  let arkuszNaZamkniecie = null;
  function arkusz(html, {szer=860, naZamkniecie=null}={}){
    const box = $('#arkusz'), body = $('#arkuszBody');
    if(!box.classList.contains('hide') && arkuszNaZamkniecie){ const f = arkuszNaZamkniecie; arkuszNaZamkniecie = null; try{ f(); }catch(e){} }
    body.style.width = szer+'px'; body.innerHTML = html;
    arkuszNaZamkniecie = naZamkniecie;
    box.classList.remove('hide');
    return body;
  }
  function zamknijArkusz(){
    const box=$('#arkusz'); if(box.classList.contains('hide')) return;
    box.classList.add('hide'); $('#arkuszBody').innerHTML='';
    const f = arkuszNaZamkniecie; arkuszNaZamkniecie = null;
    if(f){ try{ f(); }catch(e){ console.error('naZamkniecie', e); } }
  }
  const arkuszOtwarty = () => !$('#arkusz').classList.contains('hide');
  document.addEventListener('keydown', e => { if(e.key==='Escape' && !$('#arkusz').classList.contains('hide')) zamknijArkusz(); });

  // ---------- liczniki na nawigacji ----------
  function badge(id, n){ const b = $('#badge-'+id); if(!b) return; b.textContent = n ? String(n) : ''; }

  // ---------- router ----------
  function tytul(t){ $('#tytulOkna').textContent = t || 'selekta'; }
  function ekran(id, def){ EKRANY[id] = def; if(def.pelny) PELNE.add(id); }
  function _host(id){
    const def = EKRANY[id];
    const rodzic = def.pelny ? $('#pelne') : $('#ekrany');
    let sec = $('#ekran-'+id);
    if(!sec){
      sec = document.createElement('section'); sec.className = 'ekran'; sec.id = 'ekran-'+id;
      rodzic.appendChild(sec);
      try{ def.render && def.render(sec); }
      catch(e){ console.error('render', id, e); sec.innerHTML = `<div class="pusto">nie udało się zbudować ekranu „${esc(id)}”: ${esc(e.message)}</div>`; }
    }
    return sec;
  }
  function pokaz(id, arg){
    let def = EKRANY[id];
    if(!def){ def = EKRANY[id] = {tytul:id, render(h){ h.innerHTML = `<div class="pusto">ekran „${esc(id)}” jeszcze nie jest gotowy</div>`; }}; }
    const pelny = !!def.pelny;
    $('#pelne').classList.toggle('hide', !pelny);
    $('#okno').classList.toggle('hide', pelny);
    $$('#pelne .ekran, #ekrany .ekran').forEach(s => s.classList.add('hide'));
    const host = _host(id); host.classList.remove('hide');
    $$('#nav .poz').forEach(p => p.classList.toggle('on', p.dataset.ekran === id));
    const t = typeof def.tytul === 'function' ? def.tytul(arg) : def.tytul;
    if(!pelny) tytul(t);
    stan.biezacy = id;
    if(!pelny) try{ history.replaceState(null, '', '#'+id); }catch(e){}
    try{ const r = def.load && def.load(host, arg); if(r && r.catch) r.catch(e => console.error('load', id, e)); }
    catch(e){ console.error('load', id, e); }
    return host;
  }
  const biezacy = () => stan.biezacy;

  // ---------- odtwarzacz (dolny pasek) ----------
  const player = (() => {
    let audio = null, utwor = null;
    const ui = () => ({box:$('#player'), btn:$('#playerBtn'), t:$('#playerTytul'), a:$('#playerArtysta'), czas:$('#playerCzas'), dl:$('#playerDlugosc'), fala:$('#playerFala'), meta:$('#playerMeta')});
    function rysuj(){
      const u = ui(); if(!audio) return;
      const p = audio.duration ? audio.currentTime/audio.duration : 0;
      u.fala.children[0].style.flex = String(Math.max(0, p*100));
      u.fala.children[1].style.flex = String(Math.max(0, 100 - p*100));
      u.czas.textContent = fmtTime(audio.currentTime);
      u.dl.textContent = fmtTime(audio.duration || utwor.duration);
      u.btn.textContent = audio.paused ? '▶' : '❚❚';
      u.btn.title = audio.paused ? 'graj' : 'pauza';
    }
    function stop(){
      if(audio){ audio.pause(); audio.src=''; }
      audio = null; utwor = null;
      ui().box.classList.add('hide');
      document.dispatchEvent(new CustomEvent('selekta:player', {detail:{file:null}}));
    }
    function graj(t){
      // t = {file, title, artist, bpm, camelot, duration, lufs, intro, drop}
      if(utwor && utwor.file === t.file){ audio.paused ? audio.play().catch(()=>{}) : audio.pause(); rysuj(); return; }
      if(audio){ audio.pause(); }
      audio = new Audio('/api/audio?file='+encodeURIComponent(t.file));
      utwor = t;
      const u = ui();
      u.box.classList.remove('hide');
      u.t.textContent = t.title || nazwaPliku(t.file);
      u.a.textContent = [t.artist, t.bpm ? Math.round(t.bpm)+' BPM' : '', t.camelot].filter(Boolean).join(' · ');
      const meta = [t.lufs!=null ? `${Number(t.lufs).toFixed(1).replace('.',',')} LUFS` : '', t.intro!=null ? 'intro '+fmtTime(t.intro) : '', t.drop!=null ? 'drop '+fmtTime(t.drop) : ''].filter(Boolean).join(' · ');
      u.meta.textContent = meta; u.meta.className = 'meta';
      audio.ontimeupdate = rysuj; audio.onloadedmetadata = rysuj; audio.onpause = rysuj; audio.onplay = rysuj;
      audio.onended = stop;
      audio.onerror = () => { u.meta.textContent = 'nie udało się odtworzyć — przeglądarka nie obsługuje tego formatu'; u.meta.className = 'blad'; };
      audio.play().catch(()=>{});
      rysuj();
      document.dispatchEvent(new CustomEvent('selekta:player', {detail:{file:t.file}}));
    }
    const gra = file => !!(utwor && utwor.file === file && audio && !audio.paused);
    const biezacyPlik = () => utwor ? utwor.file : null;
    document.addEventListener('DOMContentLoaded', () => {
      const u = ui();
      u.btn.onclick = () => { if(!audio) return; audio.paused ? audio.play().catch(()=>{}) : audio.pause(); };
      u.fala.onclick = e => { if(!audio || !audio.duration) return; const r = u.fala.getBoundingClientRect(); audio.currentTime = audio.duration * (e.clientX - r.left) / r.width; };
    });
    return {graj, stop, gra, biezacyPlik};
  })();

  // ---------- stan Soulseeka + liczniki (w tle, w każdym trybie) ----------
  async function pollSlsk(){
    const d = await status(true);
    const dot = $('#navSlsk'), tx = $('#navSlskTxt');
    if(!dot) return;
    const kl = {green:'ok swieci', amber:'warn', red:'bad'}[d.level] || '';
    dot.className = 'dot '+kl; tx.textContent = d.label; tx.title = d.hint || '';
    if(d.wersja) stan.wersja = d.wersja;
    document.dispatchEvent(new CustomEvent('selekta:status', {detail:d}));
  }
  async function pollLiczniki(){
    try{ const d = await api('/api/transfers', {cicho:true}); const c = d.counts||{}; badge('pobierania', (c.active||0)+(c.queued||0)); }catch(e){}
    try{ const d = await api('/api/decyzje', {cicho:true}); badge('porzadki', d.count||0); }catch(e){}
    try{ const d = await api('/api/uchem', {cicho:true}); badge('uchem', (d.utwory||[]).length); }catch(e){}
  }

  // ---------- język (kreator ma PL/EN) i preferencje ----------
  const pref = {
    get(k, d){ try{ const v = localStorage.getItem('selekta.'+k); return v==null ? d : JSON.parse(v); }catch(e){ return d; } },
    set(k, v){ try{ localStorage.setItem('selekta.'+k, JSON.stringify(v)); }catch(e){} },
  };
  const jezyk = { get:()=>pref.get('jezyk','pl'), set:v=>{ pref.set('jezyk', v); document.dispatchEvent(new CustomEvent('selekta:jezyk', {detail:v})); } };

  // ---------- zaznaczenie (współdzielone między ekranami) ----------
  // biblioteka.js wystawia S.stan.wybrane (Set ścieżek) i wysyła 'selekta:wybor';
  // ekrany zakresu (kolejność, eksport, statystyki) czytają S.zaznaczone —
  // powłoka spina obie nazwy, żeby żaden ekran nie zależał od drugiego.
  const zaznaczone = () => (stan.wybrane instanceof Set ? stan.wybrane : new Set(stan.wybrane || []));
  document.addEventListener('selekta:wybor', e => {
    const w = e.detail && e.detail.wybrane; if(w) stan.wybrane = new Set(w);
    document.dispatchEvent(new CustomEvent('selekta:zaznaczenie', {detail:{wybrane:[...zaznaczone()]}}));
  });

  // ---------- start ----------
  async function start(){
    on($('#nav'), 'click', '.poz', (e, el) => pokaz(el.dataset.ekran));
    $('#navLogo').onclick = () => pokaz('biblioteka');
    $('#doKreatora').onclick = () => pokaz('kreator');
    $('#arkusz').addEventListener('click', e => { if(e.target.id === 'arkusz') zamknijArkusz(); });
    pollSlsk(); setInterval(pollSlsk, 5000);
    pollLiczniki(); setInterval(pollLiczniki, 10000);
    window.addEventListener('hashchange', () => { const id = location.hash.slice(1); if(id && EKRANY[id] && !EKRANY[id].pelny && id !== stan.biezacy) pokaz(id); });

    const hash = location.hash.slice(1);
    let gotowe = true;
    try{ const d = await api('/api/setup/stan', {cicho:true}); gotowe = !!d.gotowe; stan.setup = d; }catch(e){}
    if(!gotowe && EKRANY.zanim){ pokaz('zanim'); return; }
    // pierwsze uruchomienie z gotową konfiguracją: raz pokaż wprowadzenie
    const widzial = pref.get('onboardingWidziany', false) || (()=>{ try{ return !!localStorage.getItem('selekta_tutorial'); }catch(e){ return false; } })();
    if(!widzial && EKRANY.onboarding && !hash){ pokaz('onboarding'); return; }
    if(hash && EKRANY[hash]){ pokaz(hash); return; }
    const tryb = pref.get('startTryb', 'pytaj');
    if(tryb === 'auto' && EKRANY.kreator) pokaz('kreator');
    else if(tryb === 'reczny' || !EKRANY.tryb) pokaz('biblioteka');
    else pokaz('tryb');
  }

  return {K, CAM, esc, fmtTime, fmtMB, fmtLicz, $, $$, on, nazwaPliku, api, status, tracks, uniewaznTracks,
          toast, arkusz, zamknijArkusz, arkuszOtwarty, badge, zaznaczone, tytul, ekran, pokaz, biezacy, player, pref, jezyk, stan, start, EKRANY,
          pollLiczniki};
})();
