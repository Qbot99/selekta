/* ============================================================
   Więcej — Statystyki (5b), Historia (5c), Ustawienia (6a),
   „Zanim zaczniesz” (6b) i Onboarding (6c).

   Wygląd 1:1 z docs/design/selekta-auto.dc.html (tokeny z index.html),
   dane wyłącznie z API — kształty odpowiedzi wg selekta/web.py.
   Kontrakt powłoki: static/ekrany/_powloka.js (obiekt S).
   ============================================================ */
(() => {
  const {CAM, esc, fmtTime, fmtLicz, $, $$, on, api, toast, arkusz, zamknijArkusz} = S;

  // ---------- style tych ekranów (klasy w-*, kolory tylko z tokenów) ----------
  const styl = document.createElement('style');
  styl.id = 'styl-wiecej';
  styl.textContent = `
/* wspólne */
.w-h2{margin:0;font-size:22px;font-weight:700;letter-spacing:-.02em}
.w-kol{display:flex;flex-direction:column;gap:14px;min-height:0}
.w-prog{font-size:12.5px;color:var(--dim);min-height:18px;line-height:1.45}
.w-prog.bad{color:var(--bad)}
.uwaga.ok{border-left-color:var(--ok)} .uwaga.ok b{color:var(--ok)}
.uwaga a{color:var(--acc);font-weight:600}
.w-menu{position:absolute;right:0;top:calc(100% + 6px);background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:6px;min-width:240px;max-height:320px;overflow:auto;z-index:20;box-shadow:0 14px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:2px}
.w-menu button{background:transparent;border:0;text-align:left;padding:8px 10px;border-radius:7px;color:var(--txt);font-weight:600;font-size:13px;display:flex;gap:10px;align-items:baseline;white-space:nowrap}
.w-menu button:hover{background:var(--hover)}
.w-menu button small{margin-left:auto;font:500 11px var(--mono);color:var(--dim)}
.w-lista-ark{display:flex;flex-direction:column;max-height:60vh;overflow:auto}
.w-lista-ark .r{display:flex;gap:12px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line2);font-size:13.5px;min-width:0}
.w-lista-ark .r .nr{font:500 11px var(--mono);color:var(--dim2);min-width:22px;flex-shrink:0}
.w-lista-ark .r .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.w-lista-ark .r .a{color:var(--dim);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.w-lista-ark .r .m{margin-left:auto;font:500 11.5px var(--mono);color:var(--dim);flex-shrink:0;white-space:nowrap}
/* 5b statystyki */
.w-slupki{display:flex;align-items:flex-end;gap:8px;flex:1;min-height:160px}
.w-slupek{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;align-items:center;gap:6px}
.w-slupek .n{font:500 10px var(--mono);color:var(--dim);height:12px;line-height:12px}
.w-slupek .s{flex:1;width:100%;display:flex;align-items:flex-end;min-height:0}
.w-slupek .s>span{display:block;width:100%;border-radius:3px 3px 0 0;min-height:2px}
.w-slupek .b{font:500 10px var(--mono);color:var(--dim2);height:12px;line-height:12px}
.w-kolo{display:grid;grid-template-columns:repeat(12,1fr);gap:6px;flex:1;min-height:160px}
.w-cam{display:flex;flex-direction:column;gap:4px;height:100%;min-width:0}
.w-cam .g,.w-cam .d{flex:1;display:flex;min-height:0}
.w-cam .g{align-items:flex-end} .w-cam .d{align-items:flex-start}
.w-cam .g>span{display:block;width:100%;border-radius:3px 3px 0 0;opacity:.85}
.w-cam .d>span{display:block;width:100%;border-radius:0 0 3px 3px}
.w-cam .n{font:600 10px var(--mono);text-align:center;color:var(--dim)}
.w-luka{display:flex;flex-direction:column;gap:6px;padding:12px 0;border-bottom:1px solid var(--line2);font-size:13.5px}
.w-wyjscia{display:flex;gap:6px;flex-wrap:wrap}
.w-wyjscie{font:600 11px var(--mono);padding:3px 8px;border-radius:5px;background:var(--ok-tlo);color:var(--ok)}
.w-wyjscie.zle{background:var(--warn-tlo);color:var(--warn)}
/* 5c historia */
.w-hrow{display:grid;grid-template-columns:64px minmax(0,1fr) 40px 84px 44px 96px 20px;gap:10px;align-items:center;padding:14px 20px;border-bottom:1px solid var(--line2)}
.w-hrow.head{padding:12px 20px;border-bottom:1px solid var(--line);font:500 10.5px var(--mono);letter-spacing:.1em;color:var(--dim2);position:sticky;top:0;background:var(--panel);z-index:1}
.w-hrow.klik{cursor:pointer} .w-hrow.klik:hover{background:var(--hover)}
.w-hrow .d{font:500 12px var(--mono);color:var(--dim)}
.w-hrow .s{font-weight:600;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.w-hrow .m{font:500 12.5px var(--mono)} .w-hrow .m.dim{color:var(--dim)} .w-hrow .m.dim2{color:var(--dim2)}
.w-hrow .k{font:500 12px var(--mono);color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.w-hrow .a{color:var(--dim2);text-align:right}
@media (max-width:1200px){.w-hrow{grid-template-columns:56px minmax(0,1fr) 40px 74px 44px 20px}.w-hrow .k{display:none}}
.w-top{display:flex;flex-direction:column;gap:6px}
.w-top .r{display:flex;align-items:baseline;gap:8px;font-size:13.5px;min-width:0}
.w-top .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.w-top .ar{color:var(--dim);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex-shrink:2}
.w-top .n{margin-left:auto;font:500 11.5px var(--mono);color:var(--acc);flex-shrink:0}
.w-top .p{height:3px;background:var(--line);border-radius:2px}
.w-top .p>i{display:block;height:100%;background:var(--acc);border-radius:2px}
/* 6a ustawienia */
.w-urow{display:grid;grid-template-columns:8px 190px minmax(0,1fr) auto;gap:18px;align-items:center;padding:18px 22px;border-bottom:1px solid var(--line2)}
.w-urow .nazwa{font-weight:600;font-size:14.5px}
.w-urow .wart{font:500 12.5px var(--mono);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.w-urow .sub{font-size:12.5px;color:var(--dim);margin-top:3px}
@media (max-width:1180px){.w-urow{grid-template-columns:8px 140px minmax(0,1fr) auto;gap:14px}}
.w-ust{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:13.5px}
.w-sonda{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line2);align-items:flex-start;font-size:12.5px}
.w-sonda:last-child{border-bottom:0}
.w-sonda .i{width:18px;flex-shrink:0}
.w-sonda .n{font-weight:600;display:flex;gap:8px;align-items:baseline}
.w-sonda .ms{margin-left:auto;font:500 10.5px var(--mono);color:var(--dim2);flex-shrink:0}
.w-sonda .o{color:var(--dim);font-size:12px;line-height:1.4;margin-top:2px}
.w-stan{display:flex;align-items:center;gap:10px;font-size:13.5px;flex-wrap:wrap}
.w-pola{display:grid;grid-template-columns:130px 1fr;gap:10px;align-items:center;font-size:13px}
/* 6b / 6c — ekrany pełne */
.w-pelny{position:relative;height:100%;display:flex;flex-direction:column;overflow:hidden}
.w-chrome{display:flex;align-items:center;padding:0 16px;gap:8px;height:44px;border-bottom:1px solid var(--line2);flex-shrink:0;-webkit-app-region:drag}
.w-chrome span{width:12px;height:12px;border-radius:50%;background:var(--line3)}
.w-glow{position:absolute;left:50%;top:40%;width:900px;height:900px;transform:translate(-50%,-50%);border-radius:50%;background:radial-gradient(circle,rgba(255,106,61,.08),transparent 60%);pointer-events:none}
.w-zanim{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;gap:60px;padding:60px 90px;position:relative;align-items:center;overflow:auto}
.w-zanim h1{margin:0;font-size:52px;font-weight:700;letter-spacing:-.025em;line-height:1.02}
.w-zanim p{margin:0;font-size:17px;color:var(--dim);line-height:1.5;max-width:440px}
.w-karta{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:26px 28px;display:flex;flex-direction:column;gap:20px}
.w-krok{display:grid;grid-template-columns:22px 1fr auto;gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line2)}
.w-krok .z{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font:600 11px var(--mono);border:1px solid var(--line);color:var(--dim);background:transparent}
.w-krok.done .z{background:var(--ok);border-color:var(--ok);color:#0f0d0c}
.w-krok.run .z{background:var(--acc);border-color:var(--acc);color:#0f0d0c}
.w-krok.run .z i{width:12px;height:12px;border:2px solid #0f0d0c;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;display:block}
.w-krok .t{font-weight:600;font-size:15px} .w-krok.wait .t{color:var(--dim)}
.w-krok .o{font-size:12.5px;color:var(--dim);margin-top:2px}
.w-konto{display:flex;flex-direction:column;gap:10px;padding:14px 16px;margin:10px 0;border:1px solid var(--line3);border-radius:12px;background:var(--panel2)}
.w-onb{flex:1;min-height:0;display:flex;padding:40px;overflow:auto}
.w-onb .karta{width:760px;max-width:100%;display:flex;flex-direction:column;gap:30px;margin:auto}
.w-onb .kropki{display:flex;gap:6px}
.w-onb .kropki span{height:3px;flex:1;border-radius:2px;background:var(--line)}
.w-onb .kropki span.on{background:var(--acc)}
.w-onb h1{margin:0;font-size:46px;font-weight:700;letter-spacing:-.025em;line-height:1.05}
.w-onb .lead{margin:0;font-size:17px;color:var(--dim);line-height:1.5}
.w-widma{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.w-widmo{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;display:flex;flex-direction:column;gap:10px}
.w-widmo.ok{border-color:var(--ok)}
.w-widmo .e{font:500 10.5px var(--mono);letter-spacing:.1em}
.w-widmo .s{display:flex;align-items:flex-end;gap:2px;height:64px}
.w-widmo .s span{flex:1;border-radius:2px;background:var(--txt)}
.w-widmo .p{font:500 11px var(--mono);color:var(--dim)}
.w-punkt{display:flex;gap:16px;padding:14px 0;border-bottom:1px solid var(--line2);align-items:flex-start}
.w-punkt .n{font:600 12px var(--mono);color:var(--acc);min-width:18px;padding-top:2px}
.w-punkt .t{font-size:15px;line-height:1.5}
.w-punkt .t span{color:var(--dim)}
`;
  document.head.appendChild(styl);

  // ---------- drobiazgi ----------
  const U = ['utwór', 'utwory', 'utworów'];
  const LOSSLESS = new Set(['flac', 'wav', 'aiff', 'aif']);       // jak LOSSLESS_EXT w web.py
  const MIES = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'];
  // polska liczba mnoga: lm(3, ['utwór','utwory','utworów']) → 'utwory'
  function lm(n, [j, m, w]){ n = Math.abs(Math.round(n || 0)); if(n === 1) return j; const r = n % 10, rr = n % 100; return (r >= 2 && r <= 4 && !(rr >= 12 && rr <= 14)) ? m : w; }
  const fmtN = (x, dp = 1) => Number(x).toFixed(dp).replace('.', ',');
  const bn = p => String(p || '').split('/').pop();
  const skroc = p => String(p || '').replace(/^\/Users\/[^/]+/, '~');
  function dataKrotka(iso){ const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? `${+m[3]} ${MIES[+m[2] - 1]}` : (iso || '—'); }
  function fmtGodz(s){ s = Math.max(0, Math.round(s || 0)); const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`; }
  function mediana(arr){ if(!arr.length) return null; const a = arr.slice().sort((x, y) => x - y); const i = Math.floor(a.length / 2); return a.length % 2 ? a[i] : (a[i - 1] + a[i]) / 2; }
  const czekaj = ms => new Promise(r => setTimeout(r, ms));
  // co dalej po ekranach pełnych: wybór trybu, gdy istnieje, inaczej biblioteka
  const dalejPoStarcie = () => S.pokaz(S.EKRANY.tryb ? 'tryb' : 'biblioteka');
  // stary samouczek (stary.html) zapisywał 'selekta_tutorial' — nie męczmy tych, którzy go widzieli
  const wprowadzenieWidziane = () => { try{ return S.pref.get('onboardingWidziany', false) || localStorage.getItem('selekta_tutorial') === '1'; }catch(e){ return false; } };
  // zaznaczenie w Bibliotece — biblioteka.js może wystawić S.zaznaczone (Set/tablica/funkcja)
  function zaznaczone(){
    let z = S.zaznaczone;
    if(typeof z === 'function'){ try{ z = z(); }catch(e){ z = null; } }
    if(!z) return [];
    if(z instanceof Set) return [...z];
    return Array.isArray(z) ? z.slice() : [];
  }
  function wybierzPlik(accept){
    return new Promise(res => {
      const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.style.display = 'none';
      document.body.appendChild(i);
      i.onchange = () => { res(i.files[0] || null); i.remove(); };
      i.oncancel = () => { res(null); i.remove(); };
      i.click();
    });
  }
  // arkusz z nagłówkiem i krzyżykiem
  // arkusz z nagłówkiem i krzyżykiem; zwraca WŁASNY element treści, żeby listenery
  // (S.on) znikały razem z nim, a nie zbierały się na trwałym #arkuszBody
  function ark(tytul, html, opts){
    arkusz(`<div class="w-ark" style="display:flex;flex-direction:column;gap:22px"><div class="head"><h2 class="w-h2">${tytul}</h2><button class="btn goly" style="margin-left:auto" data-zamknij title="zamknij (Esc)">✕</button></div>${html}</div>`, opts);
    const b = $('#arkuszBody .w-ark');
    b.querySelector('[data-zamknij]').onclick = zamknijArkusz;
    return b;
  }
  const uwaga = (typ, html) => `<div class="uwaga ${typ === 'ok' ? 'ok' : ''}">${html}</div>`;
  const kafel = (liczba, jedn, etyk, tytul = '') => `<div class="kafel" ${tytul ? `title="${esc(tytul)}"` : ''}><div class="liczba">${liczba}${jedn ? `<small>${jedn}</small>` : ''}</div><div class="etyk" style="color:var(--dim);letter-spacing:.1em">${etyk}</div></div>`;
  // mapa utworów z /api/tracks po nazwie pliku i ścieżce względnej — do dopasowań historii
  async function mapaUtworow(){
    const m = new Map();
    try{ (await S.tracks()).forEach(r => { m.set(r.file, r); if(r.rel) m.set(r.rel, r); }); }catch(e){}
    return m;
  }
  const utworZMapy = (mapa, p) => mapa.get(bn(p)) || mapa.get(p) || null;

  // ============================================================
  // 5b · STATYSTYKI — rozkład BPM i tonacji, luki w bibliotece
  // /api/statystyki (GET = cała biblioteka; POST {files}|{name}), /api/playlisty
  // ============================================================
  const stat = {tryb: 'biblioteka', playlista: null, dane: null, host: null};

  function statZakresTxt(){
    if(stat.tryb === 'zaznaczenie') return `zaznaczone · ${zaznaczone().length}`;
    if(stat.tryb === 'playlista' && stat.playlista) return `playlista „${stat.playlista.name}”`;
    return 'cała biblioteka';
  }
  function statCialo(){
    if(stat.tryb === 'zaznaczenie') return {files: zaznaczone()};
    if(stat.tryb === 'playlista' && stat.playlista) return {name: stat.playlista.name};
    return null;
  }
  // utwory zakresu z /api/tracks — pod kafle (GB, bezstratne, czas), których /api/statystyki nie liczy
  async function statUtwory(){
    let t; try{ t = await S.tracks(); }catch(e){ return null; }
    if(stat.tryb === 'zaznaczenie'){ const z = new Set(zaznaczone()); return t.filter(r => z.has(r.file) || z.has(r.rel)); }
    if(stat.tryb === 'playlista' && stat.playlista){
      const lib = String(S.stan.folder || '').replace(/\/+$/, ''), f = String(stat.playlista.folder || '').replace(/\/+$/, '');
      if(lib && f.startsWith(lib + '/')){ const pre = f.slice(lib.length + 1) + '/'; return t.filter(r => String(r.rel || '').startsWith(pre)); }
      return null;                                   // playlista poza biblioteką — kafle bez danych
    }
    return t;
  }
  function statMediana(d, utw){
    const bpmy = utw ? utw.map(t => +t.bpm).filter(x => x > 0) : [];
    if(bpmy.length) return mediana(bpmy);
    const roz = d.rozklad_bpm || [], razem = roz.reduce((s, r) => s + r.ile, 0);
    if(!razem) return null;
    let acc = 0; for(const r of roz){ acc += r.ile; if(acc >= razem / 2) return r.bpm; }
    return roz[roz.length - 1].bpm;
  }
  function statKafle(d, utw, med){
    let gb = '—', bezstr = 'BEZSTRATNE', czas = '—';
    if(utw && utw.length){
      gb = fmtN(utw.reduce((s, t) => s + (+t.size_mb || 0), 0) / 1000, 1);
      const bez = utw.filter(t => LOSSLESS.has(String(t.ext || '').toLowerCase())).length;
      bezstr = `${Math.round(100 * bez / utw.length)} % BEZSTRATNE`;
      const dl = utw.map(t => +t.duration || 0).filter(x => x > 0);
      if(dl.length) czas = fmtTime(dl.reduce((a, b) => a + b, 0) / dl.length);
    }
    const lufs = d.srednia_lufs ?? d.lufs ?? null;   // backend jeszcze nie oddaje średniej LUFS
    // rozkład formatów z /api/statystyki (FLAC 120 · MP3 98 · WAV 40)
    const formaty = (d.rozklad_formatow || []).map(f => `${f.format} ${f.ile}`).join(' · ');
    return kafel(med != null ? String(Math.round(med)) : '—', med != null ? 'BPM' : '', 'MEDIANA TEMPA')
      + kafel(gb, gb !== '—' ? 'GB' : '', formaty ? `${bezstr}<br><span style="letter-spacing:0;font-size:11px">${esc(formaty)}</span>` : bezstr,
              (d.rozklad_formatow || []).map(f => `${f.format}: ${f.ile} utw., ${f.mb} MB`).join('\n'))
      + kafel(lufs != null ? fmtN(lufs, 1).replace('-', '−') : '—', lufs != null ? 'LUFS' : '', 'ŚREDNIA GŁOŚNOŚĆ',
              lufs == null ? 'głośność liczy się per utwór (Szczegóły) — średniej dla zakresu API jeszcze nie oddaje' : '')
      + kafel(czas, '', 'ŚREDNI CZAS UTWORU');
  }
  // pasma po 4 BPM (jak statystyki._pasmo), puste pasma między skrajnymi dopełnione zerem
  function statHistogram(d, med){
    const roz = (d.rozklad_bpm || []).filter(r => r.ile > 0);
    if(!roz.length) return {head: '', html: '<div class="pusto" style="flex:1">brak przeanalizowanych utworów w tym zakresie</div>'};
    const mapa = new Map(roz.map(r => [r.bpm, r.ile]));
    const pasma = []; for(let b = roz[0].bpm; b <= roz[roz.length - 1].bpm; b += 4) pasma.push({bpm: b, ile: mapa.get(b) || 0});
    const razem = pasma.reduce((s, p) => s + p.ile, 0), maks = Math.max(1, ...pasma.map(p => p.ile));
    const akc = p => med != null && Math.abs(p.bpm - med) <= 4;
    const wAkc = pasma.filter(akc), ileAkc = wAkc.reduce((s, p) => s + p.ile, 0);
    const head = wAkc.length ? `${wAkc[0].bpm - 2}–${wAkc[wAkc.length - 1].bpm + 2} · ${Math.round(100 * ileAkc / razem)} %` : '';
    const co = pasma.length > 16 ? 2 : 1;
    const html = `<div class="w-slupki">${pasma.map((p, i) => `<div class="w-slupek" title="${p.bpm - 2}–${p.bpm + 2} BPM: ${p.ile}">
        <span class="n">${p.ile || ''}</span>
        <div class="s"><span style="height:${Math.round(100 * p.ile / maks)}%;background:${akc(p) ? 'var(--acc)' : 'var(--line3)'}"></span></div>
        <span class="b">${i % co === 0 ? p.bpm : ''}</span></div>`).join('')}</div>`;
    return {head, html};
  }
  function statLukaBpm(d, utw, med){
    if(med == null) return '';
    let bpmy = utw ? utw.map(t => +t.bpm).filter(x => x > 0) : [];
    if(!bpmy.length) (d.rozklad_bpm || []).forEach(r => { for(let i = 0; i < r.ile; i++) bpmy.push(r.bpm); });
    const razem = bpmy.length; if(!razem) return '';
    const dol = Math.round(med) - 6, gora = Math.round(med) + 6;
    const nisko = bpmy.filter(b => b < dol).length, wysoko = bpmy.filter(b => b > gora).length;
    if(nisko / razem < .1) return uwaga('warn', `<b>Luka:</b> tylko ${nisko} ${lm(nisko, U)} poniżej ${dol} BPM — mało materiału na rozgrzewkę.`);
    if(wysoko / razem < .1) return uwaga('warn', `<b>Luka:</b> tylko ${wysoko} ${lm(wysoko, U)} powyżej ${gora} BPM — mało czym podkręcić kulminację.`);
    return uwaga('ok', `<b>Bez luki:</b> ${nisko} ${lm(nisko, U)} na rozgrzewkę (poniżej ${dol} BPM) i ${wysoko} na kulminację (powyżej ${gora} BPM).`);
  }
  function statKolo(rozklad){
    const mapa = Object.fromEntries((rozklad || []).map(r => [r.tonacja, r.ile]));
    const maks = Math.max(1, ...(rozklad || []).map(r => r.ile));
    return `<div class="w-kolo">${[...Array(12)].map((_, i) => {
      const n = i + 1, a = mapa[n + 'A'] || 0, b = mapa[n + 'B'] || 0;
      return `<div class="w-cam" title="${n}B (dur): ${b} · ${n}A (moll): ${a}">
        <div class="g"><span style="height:${Math.round(100 * b / maks)}%;background:${CAM[n + 'B']}"></span></div>
        <span class="n">${n}</span>
        <div class="d"><span style="height:${Math.round(100 * a / maks)}%;background:${CAM[n + 'A']}"></span></div></div>`;
    }).join('')}</div>`;
  }
  // logika luk ze starego UI (statyLuki): gniazdo, z którego trudno wyjść przy ±6 % pitcha
  function statLukaTon(d){
    const luki = d.luki || [], puste = d.puste_tonacje || [];
    if(luki.length){
      const l = luki[0], lo = Math.round(l.srednie_bpm * 0.94), hi = Math.round(l.srednie_bpm * 1.06);
      return uwaga('warn', `<b>Luka:</b> ${l.masz} ${lm(l.masz, U)} w <b>${esc(l.tonacja)}</b> przy ~${Math.round(l.srednie_bpm)} BPM, a wyjścia ubogie — brakuje ${l.brakujace.map(esc).join(', ')} w ${lo}–${hi} BPM.`
        + ` <a href="#" data-luki>${luki.length > 1 ? `+${luki.length - 1} ${lm(luki.length - 1, ['inna', 'inne', 'innych'])} ›` : 'szczegóły ›'}</a>`);
    }
    if(puste.length) return uwaga('warn', `<b>Luka:</b> nic nie masz w ${puste.slice(0, 8).map(esc).join(', ')}${puste.length > 8 ? ` i ${puste.length - 8} innych` : ''}.`);
    if(!(d.przeanalizowanych || 0)) return '';
    return uwaga('ok', `<b>Bez luki:</b> z każdego licznego gniazda masz czym wyjść — nieźle.`);
  }
  function statArkuszLuki(luki){
    ark(`Luki w przejściach <span class="dim" style="font-size:14px;font-weight:500">${luki.length}</span>`, `
      <div class="dim" style="font-size:12.5px;line-height:1.5;margin-top:-10px">Gniazda, z których trudno wyjść: dużo utworów tutaj, mało w tonacjach, do których wolno przejść przy tym tempie (±6 % pitcha).</div>
      <div class="w-lista-ark">${luki.map(l => `<div class="w-luka">
        <div><b>${l.masz} ${lm(l.masz, U)}</b> w <span class="cam" style="background:${CAM[l.tonacja] || 'var(--line3)'}">${esc(l.tonacja)}</span> przy ~${fmtN(l.srednie_bpm, 1)} BPM — <span class="warn">wyjścia są ubogie</span></div>
        <div class="w-wyjscia">${l.wyjscia.map(w => `<span class="w-wyjscie ${w.ubogie ? 'zle' : ''}">${esc(w.tonacja)}: ${w.utworow}</span>`).join('')}</div>
        <div class="dim" style="font-size:11.5px">dokup coś w ${l.brakujace.map(esc).join(', ')} w tempie ${Math.round(l.srednie_bpm * 0.94)}–${Math.round(l.srednie_bpm * 1.06)} BPM</div>
      </div>`).join('')}</div>`, {szer: 640});
  }
  function statSeg(host){
    $$('#statZakres > button', host).forEach(b => b.classList.toggle('on', b.dataset.z === stat.tryb));
    $('#statZazN', host).textContent = zaznaczone().length;
    $('#statPl', host).textContent = (stat.tryb === 'playlista' && stat.playlista) ? `${stat.playlista.name} ▾` : 'Playlista ▾';
  }
  async function statMenuPlaylist(host, btn){
    const akcje = btn.closest('.akcje'), stare = akcje.querySelector('.w-menu');
    if(stare){ stare.remove(); return; }
    let lista = []; try{ lista = (await api('/api/playlisty')).playlisty || []; }catch(e){ return; }
    if(!lista.length){ toast('nie masz jeszcze playlist utworzonych w apce — zrób ją w Imporcie albo z zaznaczenia w Bibliotece'); return; }
    const m = document.createElement('div'); m.className = 'w-menu';
    m.innerHTML = lista.map((p, i) => `<button data-i="${i}">${esc(p.name)}<small>${p.utworow} ${lm(p.utworow, U)}</small></button>`).join('');
    akcje.appendChild(m);
    m.onclick = e => { const b = e.target.closest('button'); if(!b) return; stat.playlista = lista[+b.dataset.i]; stat.tryb = 'playlista'; m.remove(); statSeg(host); statLaduj(host); };
    const zamknij = e => { if(!m.contains(e.target) && e.target !== btn){ m.remove(); document.removeEventListener('click', zamknij, true); } };
    setTimeout(() => document.addEventListener('click', zamknij, true), 0);
  }
  function statRender(host){
    stat.host = host;
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Statystyki</h1><div class="sub">Rozkład, luki i łuk energii — dla całej biblioteki albo konkretnego setu.<span id="statBez"></span></div></div>
        <div class="akcje" style="position:relative"><div class="seg" id="statZakres">
          <button data-z="biblioteka" class="on">Cała biblioteka</button>
          <button data-z="zaznaczenie">Zaznaczone · <span id="statZazN">0</span></button>
          <button data-z="playlista" id="statPl">Playlista ▾</button>
        </div></div>
      </div>
      <div class="kafle c4" id="statKafle"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;flex:1;min-height:0">
        <div class="panel pad w-kol">
          <div class="head"><span class="etyk">ROZKŁAD BPM</span><span id="statBpmHead" style="margin-left:auto;font:500 11px var(--mono);color:var(--acc)"></span></div>
          <div id="statBpm" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>
          <div id="statLukaBpm"></div>
        </div>
        <div class="panel pad w-kol">
          <div class="head"><span class="etyk">TONACJE · KOŁO CAMELOT</span><span style="margin-left:auto;font:500 11px var(--mono);color:var(--dim)">góra: B (dur) · dół: A (moll)</span></div>
          <div id="statTon" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>
          <div id="statLukaTon"></div>
        </div>
      </div>`;
    on(host, 'click', '#statZakres > button', (e, b) => {
      const z = b.dataset.z;
      if(z === 'playlista'){ statMenuPlaylist(host, b); return; }
      if(z === 'zaznaczenie' && !zaznaczone().length){ toast('Najpierw zaznacz utwory w Bibliotece.', 'warn'); return; }
      stat.tryb = z; statSeg(host); statLaduj(host);
    });
    on(host, 'click', '[data-luki]', e => { e.preventDefault(); if(stat.dane) statArkuszLuki(stat.dane.luki || []); });
    document.addEventListener('selekta:zaznaczenie', () => { if(stat.host) statSeg(stat.host); });
  }
  async function statLaduj(host){
    statSeg(host);
    const cel = $('#statKafle', host); cel.innerHTML = '<div class="pusto" style="grid-column:1/-1"><span class="spin"></span> liczę…</div>';
    let d;
    try{ const body = statCialo(); d = body ? await api('/api/statystyki', {method: 'POST', body}) : await api('/api/statystyki'); }
    catch(e){ cel.innerHTML = `<div class="pusto bad" style="grid-column:1/-1">✗ ${esc(e.message)}</div>`; return; }
    if(stat.host !== host) return;
    const utw = await statUtwory();
    stat.dane = d;
    const med = statMediana(d, utw);
    cel.innerHTML = statKafle(d, utw, med);
    const h = statHistogram(d, med);
    $('#statBpmHead', host).textContent = h.head;
    $('#statBpm', host).innerHTML = h.html;
    $('#statLukaBpm', host).innerHTML = statLukaBpm(d, utw, med);
    $('#statTon', host).innerHTML = statKolo(d.rozklad_tonacji);
    $('#statLukaTon', host).innerHTML = statLukaTon(d);
    $('#statBez', host).innerHTML = d.bez_analizy ? ` · <span class="warn">${d.bez_analizy} bez analizy</span>` : '';
    if(S.biezacy() === 'statystyki') S.tytul(`STATYSTYKI · ${statZakresTxt()} · ${fmtLicz(d.przeanalizowanych)} PRZEANALIZOWANYCH`);
  }
  S.ekran('statystyki', {tytul: () => `STATYSTYKI · ${statZakresTxt()}`, render: statRender, load: statLaduj});

  // ============================================================
  // 5c · HISTORIA — sesje z rekordboxa, najczęściej grane, martwy balast
  // /api/historia (GET), /api/historia/wczytaj (multipart, ?wszystkie=),
  // /api/historia/wyczysc, /api/historia/martwe-do-decyzji
  // ============================================================
  const hist = {dane: null, mapa: null, host: null};

  // CZAS / BPM / TONACJE liczą się z utworów sesji; /api/historia oddaje w lista_sesji
  // tylko nazwę, datę i liczbę — gdy backend doda `sciezki`, kolumny same się wypełnią
  function histMetryki(s){
    const sc = Array.isArray(s.sciezki) ? s.sciezki : null;
    if(!sc || !sc.length || !hist.mapa) return null;
    const tr = sc.map(p => utworZMapy(hist.mapa, p)).filter(Boolean);
    if(!tr.length) return null;
    const czas = tr.reduce((a, t) => a + (+t.duration || 0), 0);
    const bpm = mediana(tr.map(t => +t.bpm).filter(x => x > 0));
    const ton = tr.map(t => t.camelot).filter(Boolean);
    return {czas, bpm, tonacje: ton.length ? `${ton[0]} → ${ton[ton.length - 1]}` : '', utwory: tr};
  }
  function histSesje(d){
    const lista = (d.lista_sesji || []).map((s, i) => ({...s, i}));
    lista.sort((a, b) => (b.data || '').localeCompare(a.data || '') || b.i - a.i);   // najnowsze na górze
    return lista;
  }
  function histTabela(d){
    const head = `<div class="w-hrow head"><span>DATA</span><span>SESJA</span><span>UTW.</span><span>CZAS</span><span>BPM</span><span class="k">TONACJE</span><span></span></div>`;
    if(!d.sesji) return head + `<div class="pusto" style="text-align:left;line-height:1.6;max-width:560px">
        Nie masz jeszcze wczytanej historii.<br><br>
        W rekordboksie: <b class="muted">File → Export Collection in xml format</b> — plik zawiera Twoje playlisty razem z folderem <b class="muted">History</b>. Wczytaj go tutaj.<br>
        Za sesję uznaję playlistę z datą w nazwie albo leżącą w folderze History. Jeśli nazywasz sesje po klubie, zapytam, czy wziąć wszystkie playlisty.</div>`;
    return head + histSesje(d).map(s => {
      const m = histMetryki(s);
      return `<div class="w-hrow ${m ? 'klik' : ''}" data-i="${s.i}" ${s.data ? `title="${esc(s.data)}"` : ''}>
        <span class="d">${s.data ? dataKrotka(s.data) : '—'}</span>
        <span class="s">${esc(s.nazwa || '(bez nazwy)')}</span>
        <span class="m">${s.utworow ?? '—'}</span>
        <span class="m ${m ? 'dim' : 'dim2'}">${m ? fmtGodz(m.czas) : '—'}</span>
        <span class="m ${m && m.bpm ? '' : 'dim2'}">${m && m.bpm ? Math.round(m.bpm) : '—'}</span>
        <span class="k">${m && m.tonacje ? esc(m.tonacje) : '—'}</span>
        <span class="a">→</span></div>`;
    }).join('');
  }
  function histTop(d){
    const top = (d.najczestsze || []).slice(0, 5), maks = Math.max(1, ...top.map(x => x.zagran));
    if(!top.length) return `<div class="etyk">NAJCZĘŚCIEJ GRANE</div><div class="dim" style="font-size:13px">— jeszcze nic</div>`;
    return `<div class="etyk">NAJCZĘŚCIEJ GRANE</div>` + top.map(x => {
      const t = utworZMapy(hist.mapa, x.path || x.file);
      const tytul = t ? t.title : bn(x.file).replace(/\.[^.]+$/, ''), art = t ? t.artist : '';
      return `<div class="w-top" title="${esc(x.file)}${x.ostatnio ? ' · ostatnio ' + esc(x.ostatnio) : ''}">
        <div class="r"><span class="t">${esc(tytul)}</span>${art ? `<span class="ar">${esc(art)}</span>` : ''}<span class="n">${x.zagran}×</span></div>
        <div class="p"><i style="width:${Math.round(100 * x.zagran / maks)}%"></i></div></div>`;
    }).join('');
  }
  function histWnioski(d){
    const tresc = d.sesji
      ? `Grasz <b class="muted">${d.sesji}</b> ${lm(d.sesji, ['sesję', 'sesje', 'sesji'])} · <b class="muted">${d.utworow_granych}</b> ${lm(d.utworow_granych, U)}.
         <b style="color:var(--txt)">${d.procent_martwych} %</b> biblioteki nigdy nie zagrane — ${d.martwy_balast} ${lm(d.martwy_balast, ['utwór czeka', 'utwory czekają', 'utworów czeka'])}.`
      : `Bez historii „martwy balast” to przeczucie, nie liczba. Wczytaj XML z rekordboxa, a policzę, co gra, a co leży.`;
    return `<div class="etyk">WNIOSKI</div>
      <div style="font-size:13px;color:var(--dim);line-height:1.5">${tresc}</div>
      <div style="margin-top:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn sr" data-a="martwe" ${d.sesji ? '' : 'disabled'}>Pokaż nigdy niegrane</button>
        ${d.sesji ? `<button class="btn goly zly mini" data-a="zapomnij" title="skasuj zapamiętane sesje (pliki zostają)">Zapomnij historię</button>` : ''}
      </div>`;
  }
  function histListaArk(lista, mapa){
    return `<div class="w-lista-ark">${lista.map((x, i) => {
      const t = utworZMapy(mapa, x.path || x.file);
      return `<div class="r"><span class="nr">${String(i + 1).padStart(2, '0')}</span><span class="t">${esc(t ? t.title : bn(x.file))}</span>${t && t.artist ? `<span class="a">${esc(t.artist)}</span>` : ''}<span class="m">${t && t.bpm ? Math.round(t.bpm) + ' BPM' : ''}${t && t.camelot ? ' · ' + esc(t.camelot) : ''}${x.ostatnio ? ' · ' + esc(x.ostatnio) : ''}</span></div>`;
    }).join('')}</div>`;
  }
  async function histMartwe(){
    let d; try{ d = await api('/api/historia/martwe-do-decyzji', {method: 'POST', body: {limit: 40}}); }catch(e){ return; }
    const lista = d.propozycje || [];
    ark(`Nigdy niegrane <span class="dim" style="font-size:14px;font-weight:500">${d.martwych}</span>`, `
      <div class="dim" style="font-size:12.5px;line-height:1.5;margin-top:-10px">Masz je na dysku i nigdy nie zagrałeś. To podpowiedź, nie wyrok — utwór mógł czekać na swój set. ${esc(d.uwaga || '')}</div>
      ${histListaArk(lista, hist.mapa)}
      ${d.martwych > lista.length ? `<div class="dim" style="font-size:11.5px">…i jeszcze ${d.martwych - lista.length}</div>` : ''}`, {szer: 640});
  }
  function histSesjaArk(s){
    const m = histMetryki(s); if(!m) return;
    ark(`${esc(s.nazwa)} <span class="dim" style="font-size:14px;font-weight:500">${s.data ? esc(s.data) : ''}</span>`, `
      <div class="dim" style="font-size:12.5px;margin-top:-10px">${m.utwory.length} ${lm(m.utwory.length, U)} · ${fmtGodz(m.czas)}${m.bpm ? ` · mediana ${Math.round(m.bpm)} BPM` : ''}${m.tonacje ? ` · ${esc(m.tonacje)}` : ''}</div>
      ${histListaArk(m.utwory.map(t => ({file: t.file, path: t.rel})), hist.mapa)}`, {szer: 640});
  }
  async function histWyslij(host, plik, wszystkie){
    const fd = new FormData(); fd.append('file', plik);
    const btn = $('#histWczytaj', host); btn.disabled = true; btn.innerHTML = '<span class="spin"></span> czytam sesje…';
    try{
      const d = await api('/api/historia/wczytaj?wszystkie=' + (wszystkie ? 'true' : 'false'), {method: 'POST', formData: fd, cicho: true});
      toast(`wczytano ${d.nowe} ${lm(d.nowe, ['nową sesję', 'nowe sesje', 'nowych sesji'])}${d.juz_znane ? ` · ${d.juz_znane} już znałem` : ''} · razem ${d.razem}`, 'ok', 6000);
      histLaduj(host);
    }catch(e){
      if(!wszystkie && /nie znalazłem sesji/i.test(e.message || '')){
        const b = ark('Nie znalazłem sesji', `
          <div class="dim" style="font-size:13px;line-height:1.5;margin-top:-10px">Rekordbox nazywa sesje datą albo trzyma je w folderze History — w tym pliku nie ma takich playlist. Jeśli nazywasz sesje po klubie, mogę wziąć <b class="muted">wszystkie playlisty</b> jako sesje.</div>
          <div style="display:flex;gap:10px"><button class="btn acc" data-a="wszystkie">Weź wszystkie playlisty</button><button class="btn cichy" data-zamknij2>Anuluj</button></div>`, {szer: 520});
        b.querySelector('[data-a="wszystkie"]').onclick = () => { zamknijArkusz(); histWyslij(host, plik, true); };
        b.querySelector('[data-zamknij2]').onclick = zamknijArkusz;
      } else toast(e.message, 'bad');
    }
    btn.disabled = false; btn.textContent = 'Wczytaj historię z rekordboxa';
  }
  function histRender(host){
    hist.host = host;
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Historia</h1><div class="sub">Rekordbox zapisuje każdą sesję jako playlistę nazwaną datą — tu widzisz, co i jak grałeś.</div></div>
        <div class="akcje"><button class="btn" id="histWczytaj">Wczytaj historię z rekordboxa</button></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 300px;gap:16px;flex:1;min-height:0">
        <div class="panel" style="overflow:auto;min-height:0" id="histTab"><div class="pusto"><span class="spin"></span> liczę…</div></div>
        <div style="display:flex;flex-direction:column;gap:16px;min-height:0">
          <div class="panel pad w-kol" id="histTop" style="flex-shrink:0"></div>
          <div class="panel pad w-kol" id="histWnioski" style="flex:1;gap:10px"></div>
        </div>
      </div>`;
    $('#histWczytaj', host).onclick = async () => { const f = await wybierzPlik('.xml,text/xml,application/xml'); if(f) histWyslij(host, f, false); };
    on(host, 'click', '.w-hrow.klik', (e, el) => { const s = (hist.dane && hist.dane.lista_sesji || [])[+el.dataset.i]; if(s) histSesjaArk(s); });
    on(host, 'click', '[data-a="martwe"]', histMartwe);
    on(host, 'click', '[data-a="zapomnij"]', async () => {
      if(!confirm('Zapomnieć całą historię grania? Pliki zostają, kasuję tylko zapamiętane sesje.')) return;
      try{ const j = await api('/api/historia/wyczysc', {method: 'POST'}); toast(`zapomniano ${j.usunietych} ${lm(j.usunietych, ['sesję', 'sesje', 'sesji'])}`); histLaduj(host); }catch(e){}
    });
  }
  async function histLaduj(host){
    let d;
    try{ [d, hist.mapa] = await Promise.all([api('/api/historia'), mapaUtworow()]); }
    catch(e){ $('#histTab', host).innerHTML = `<div class="pusto bad">✗ ${esc(e.message)}</div>`; return; }
    if(hist.host !== host) return;
    hist.dane = d;
    $('#histTab', host).innerHTML = histTabela(d);
    $('#histTop', host).innerHTML = histTop(d);
    $('#histWnioski', host).innerHTML = histWnioski(d);
    if(S.biezacy() === 'historia'){
      const daty = (d.zakres_dat || []).filter(Boolean);
      S.tytul(`HISTORIA · ${d.sesji} ${lm(d.sesji, ['SESJA', 'SESJE', 'SESJI'])}${daty.length ? ` · OSTATNIA ${dataKrotka(daty[daty.length - 1])}` : ''}`);
    }
  }
  S.ekran('historia', {tytul: 'HISTORIA', render: histRender, load: histLaduj});

  // ============================================================
  // 6a · USTAWIENIA — połączenia i narzędzia, każde ze stanem; doktor integracji
  // /api/config (GET/POST), /api/config/autodetect, /api/slskd/start|stop,
  // /api/setup/folder, /api/setup/instaluj, /api/setup/konto, /api/obserwator,
  // /api/rekordbox/stan, /api/rekordbox/wczytaj, /api/doktor (GET/POST)
  // ============================================================
  const ust = {dane: null, obs: null, dok: null, rb: null, host: null};

  const ustWiersz = ({dot, nazwa, wart, sub, cta}) => `<div class="w-urow">
      <span class="dot ${dot || ''}"></span>
      <span class="nazwa">${nazwa}</span>
      <div style="min-width:0"><div class="wart" title="${esc(wart.replace(/<[^>]+>/g, ''))}">${wart}</div><div class="sub">${sub}</div></div>
      ${cta || '<span></span>'}</div>`;

  function ustLista(d, obs, dok, rb, tracks){
    const s = d.slskd || {}, c = d.config || {}, r = d.rekordbox || {};
    const ff = ((dok && dok.wyniki) || []).find(x => x.nazwa === 'ffmpeg');
    const obsDziala = !!(obs && obs.wlaczony && obs.dziala);
    const n = tracks ? tracks.length : null;
    return [
      {dot: d.folder ? 'ok' : 'bad', nazwa: 'Folder biblioteki', wart: esc(skroc(d.folder) || 'nie ustawiony'),
       sub: `${n != null ? `${fmtLicz(n)} ${lm(n, ['plik', 'pliki', 'plików'])} · ` : ''}${obsDziala ? 'obserwowany na żywo' : 'obserwator wyłączony'}`,
       cta: `<button class="btn sr" data-a="folder">Zmień…</button>`},
      {dot: s.logged_in ? 'ok' : (s.running || s.reachable ? 'warn' : 'bad'), nazwa: 'Soulseek (slskd)', wart: esc(s.url || ''),
       sub: esc(s.logged_in ? 'połączony z siecią Soulseek' : s.running ? (s.detail || 'działa, ale nie jest zalogowany') : s.binary ? 'zainstalowany, nie uruchomiony' : 'nie zainstalowany — kreator pobierze go automatycznie')
            + (s.binary ? ` · ${esc(skroc(s.binary))}` : ''),
       cta: `<button class="btn sr" data-a="slskd">Konfiguruj…</button>`},
      {dot: r.installed ? (r.linked ? 'ok' : 'warn') : 'warn', nazwa: 'rekordbox',
       wart: r.installed ? `wykryty${r.running ? ' · uruchomiony' : ''}${r.linked ? ' · playlista podpięta' : ''}` : 'nie wykryto',
       sub: rb && rb.utworow
         ? `${rb.utworow} ${lm(rb.utworow, U)} z ręczną pracą · ${rb.hot_cue} hot cue · ${rb.z_kolorem} ${lm(rb.z_kolorem, ['kolor', 'kolory', 'kolorów'])} · ${rb.z_ocena} ${lm(rb.z_ocena, ['ocena', 'oceny', 'ocen'])}${rb.rozbieznosci_razem ? ` · <span class="warn">${rb.rozbieznosci_razem} ${lm(rb.rozbieznosci_razem, ['rozbieżność', 'rozbieżności', 'rozbieżności'])} BPM/tonacji</span>` : ''}`
         : 'hot cue, kolory i oceny zachowane przy eksporcie — wczytaj XML, żeby je pamiętać',
       cta: `<button class="btn sr" data-a="xml">Wczytaj XML…</button>`},
      {dot: ff ? (ff.ok ? 'ok' : 'bad') : '', nazwa: 'ffmpeg / ffprobe', wart: esc(ff ? ff.opis : 'nie sprawdzano'),
       sub: ff && !ff.ok ? 'bez tego nie ma analizy audio — zainstaluj: brew install ffmpeg' : (ff ? 'konwersja WAV → AIFF/FLAC, analiza widma' : 'kliknij „Sprawdź teraz” w Integracjach'), cta: ''},
      {dot: s.authorized ? 'ok' : (c.slskd_api_key_set ? 'warn' : 'bad'), nazwa: 'Klucz API slskd', wart: esc(c.slskd_api_key_set ? c.slskd_api_key : 'brak klucza'),
       sub: s.authorized ? 'łączy selektę ze slskd · działa' : (s.reachable ? 'slskd odpowiada, ale klucz nie pasuje — wykryj ponownie' : (s.config_file ? `znajdę go sam w ${esc(skroc(s.config_file))}` : 'sprawdzę, gdy slskd wstanie')),
       cta: `<button class="btn sr" data-a="wykryj">Wykryj automatycznie</button>`},
      {dot: obs ? (obs.wlaczony ? (obs.dziala ? 'ok' : 'warn') : '') : '', nazwa: 'Obserwator folderu',
       wart: obs ? (obs.wlaczony ? (obs.dziala ? 'włączony · działa' : 'włączony · nie wystartował') : 'wyłączony') : '—',
       sub: `nowe pliki analizują się same${obs && obs.przeanalizowane ? ` · od uruchomienia: ${obs.przeanalizowane}` : ''}${obs && obs.w_toku ? ` · teraz: ${esc(bn(obs.w_toku))}` : ''}`,
       cta: `<button class="przelacznik ${obs && obs.wlaczony ? 'on' : ''}" data-a="obserwator" title="analizuj nowe pliki automatycznie"></button>`},
    ].map(ustWiersz).join('');
  }
  function doktorHTML(r){
    if(!r || !r.kiedy) return `<div class="dim" style="font-size:12.5px;line-height:1.5">Jeszcze nie sprawdzano. Spotify, Beatport, iTunes i YouTube nie mają dla nas API — apka czyta ich strony, a gdy któraś się zmieni, funkcja cichnie zamiast krzyczeć. To sprawdzenie mówi wprost, co działa.</div>`;
    const ik = s => s.ok ? '✅' : (s.krytyczna ? '❌' : '⚠️');
    return `<div class="dim2" style="font:500 11px var(--mono);margin-bottom:4px">ostatnio: ${esc(String(r.kiedy).replace('T', ' ').slice(0, 16))}</div>`
      + (r.wyniki || []).map(s => `<div class="w-sonda"><span class="i">${ik(s)}</span><div style="min-width:0;flex:1"><div class="n">${esc(s.nazwa)}<span class="ms">${s.ms} ms</span></div><div class="o">${esc(s.opis)}</div></div></div>`).join('');
  }
  function ustZachowanie(){
    const tryb = S.pref.get('startTryb', 'pytaj'), jez = S.jezyk.get();
    return `<div class="etyk">ZACHOWANIE</div>
      <div class="w-ust"><span>Start w trybie</span><div class="seg ciemny" id="ustStart">
        <button data-v="pytaj" class="${tryb === 'pytaj' ? 'on' : ''}">Pytaj</button><button data-v="auto" class="${tryb === 'auto' ? 'on' : ''}">Auto</button><button data-v="reczny" class="${tryb === 'reczny' ? 'on' : ''}">Ręczny</button></div></div>
      <div class="w-ust"><span>Język</span><div class="seg ciemny mono" id="ustJezyk">
        <button data-v="pl" class="${jez === 'pl' ? 'on' : ''}">PL</button><button data-v="en" class="${jez === 'en' ? 'on' : ''}">EN</button></div></div>`;
  }
  // „Konfiguruj…” — pełny obraz slskd i pola zapisywane przez POST /api/config
  function ustArkuszSlskd(d){
    const s = d.slskd || {}, c = d.config || {};
    const linia = (stan, txt, extra = '') => `<div class="w-stan"><span class="dot ${stan}"></span><span>${txt}</span>${extra}</div>`;
    const b = ark('Soulseek (slskd)', `
      <div class="dim" style="font-size:13px;line-height:1.5;margin-top:-10px">selekta korzysta z Twojego własnego slskd. Nie hostuje ani nie udostępnia żadnych nagrań.</div>
      <div style="display:flex;flex-direction:column;gap:12px">
        ${linia(s.binary ? 'ok' : 'bad', s.binary ? `zainstalowany <span class="mono dim" style="font-size:11.5px">${esc(skroc(s.binary))}</span>` : 'nie znaleziono slskd', s.binary ? '' : `<button class="btn mini" data-a="instaluj" style="margin-left:auto">Zainstaluj (ok. 55 MB)</button>`)}
        ${linia(s.running ? 'ok' : 'bad', s.running ? 'działa' : 'nie działa', `<span style="margin-left:auto;display:flex;gap:6px"><button class="btn mini" data-a="start">Uruchom</button><button class="btn mini cichy" data-a="stop">Zatrzymaj</button></span>`)}
        ${linia(s.authorized ? 'ok' : 'warn', s.authorized ? 'klucz API działa' : (c.slskd_api_key_set ? 'klucz API zapisany, ale nie działa' : 'brak klucza API'), `<button class="btn mini" data-a="wykryj" style="margin-left:auto">Wykryj automatycznie</button>`)}
        ${linia(s.logged_in ? 'ok' : 'warn', s.logged_in ? 'zalogowany do sieci Soulseek — pobieranie działa' : 'nie zalogowany do sieci Soulseek', s.logged_in ? '' : `<button class="btn mini" data-a="konto" style="margin-left:auto">Podaj konto Soulseek…</button>`)}
        ${s.logged_in ? '' : `<div class="dim" style="font-size:12.5px;line-height:1.5">Hasło trafia wyłącznie do konfiguracji slskd na tym komputerze — apka go nie zapisuje. Możesz też wpisać je w <a href="${esc(s.url || '#')}" target="_blank" rel="noopener">panelu slskd</a> → Settings → Soulseek.</div>`}
      </div>
      <div id="slskdKonto"></div>
      <div class="w-pola">
        <span class="dim">Adres slskd</span><input class="pole" data-p="url" value="${esc(s.url || '')}" placeholder="http://localhost:5030">
        <span class="dim">Klucz API</span><input class="pole" data-p="key" placeholder="${c.slskd_api_key_set ? 'zapisany: ' + esc(c.slskd_api_key) + ' (puste = bez zmian)' : 'wklej klucz API slskd'}" autocomplete="off">
        <span class="dim">Program slskd</span><input class="pole" data-p="bin" value="${esc(s.binary || '')}" placeholder="ścieżka do slskd">
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <button class="btn acc" data-a="zapisz">Zapisz ustawienia</button><span class="w-prog" data-p="prog"></span>
        <a href="#" data-a="kreator" style="margin-left:auto;font-size:12.5px;font-weight:600">Kreator pierwszego uruchomienia ›</a>
      </div>`, {szer: 640});
    const prog = (html, zly) => { const p = b.querySelector('[data-p="prog"]'); p.innerHTML = html; p.className = 'w-prog' + (zly ? ' bad' : ''); };
    const odswiez = (ms = 600) => setTimeout(() => { if(ust.host) ustLaduj(ust.host); }, ms);
    on(b, 'click', '[data-a]', async (e, el) => {
      const a = el.dataset.a; e.preventDefault();
      try{
        if(a === 'instaluj'){ el.disabled = true; prog('<span class="spin"></span> pobieram slskd (ok. 55 MB)…'); const j = await api('/api/setup/instaluj', {method: 'POST'}); prog('✓ ' + esc(j.message)); odswiez(); }
        else if(a === 'start'){ prog('<span class="spin"></span> uruchamiam…'); const j = await api('/api/slskd/start', {method: 'POST'}); prog((j.ok ? '✓ ' : '✗ ') + esc(j.message), !j.ok); odswiez(2500); }
        else if(a === 'stop'){ prog('<span class="spin"></span> zatrzymuję…'); const j = await api('/api/slskd/stop', {method: 'POST'}); prog((j.ok ? '✓ ' : '✗ ') + esc(j.message), !j.ok); odswiez(1500); }
        else if(a === 'wykryj'){ prog('<span class="spin"></span> szukam klucza…'); await api('/api/config/autodetect', {method: 'POST'}); prog('✓ klucz znaleziony i zapisany'); odswiez(); }
        else if(a === 'zapisz'){
          prog('<span class="spin"></span> zapisuję…');
          const v = n => b.querySelector(`[data-p="${n}"]`).value.trim();
          await api('/api/config', {method: 'POST', body: {slskd_url: v('url'), slskd_api_key: v('key'), slskd_binary: v('bin')}});
          b.querySelector('[data-p="key"]').value = '';
          prog('✓ zapisane'); odswiez();
        }
        else if(a === 'konto'){ el.disabled = true; const msg = await formularzKonta(b.querySelector('#slskdKonto')); el.disabled = false; prog(esc(msg)); odswiez(); }
        else if(a === 'kreator'){ zamknijArkusz(); S.pokaz('zanim'); }
      }catch(err){ prog('✗ ' + esc(err.message), true); el.disabled = false; }
    });
  }
  async function ustZmienFolder(host){
    try{
      const d = await api('/api/setup/folder', {method: 'POST', cicho: true});
      if(d.cancelled){ toast('anulowano — folder bez zmian'); return; }
      toast(`ustawiono: ${d.utworow} ${lm(d.utworow, U)}`, 'ok'); S.uniewaznTracks(); ustLaduj(host);
    }catch(e){                                        // brak okna Findera — ścieżka ręcznie (POST /api/config {folder})
      const b = ark('Folder biblioteki', `
        <div class="dim" style="font-size:12.5px;line-height:1.5;margin-top:-10px">${esc(e.message || '')} — wpisz ścieżkę ręcznie.</div>
        <input class="pole" data-p="folder" value="${esc((ust.dane && ust.dane.folder) || '')}" placeholder="/Users/…/Music/dj">
        <div style="display:flex;gap:10px"><button class="btn acc" data-a="zapisz">Zapisz</button></div>`, {szer: 560});
      b.querySelector('[data-a="zapisz"]').onclick = async () => {
        const v = b.querySelector('[data-p="folder"]').value.trim(); if(!v) return;
        try{ await api('/api/config', {method: 'POST', body: {folder: v}}); zamknijArkusz(); S.uniewaznTracks(); toast('folder ustawiony', 'ok'); ustLaduj(host); }catch(err){}
      };
    }
  }
  async function ustWczytajXml(host){
    const f = await wybierzPlik('.xml,text/xml,application/xml'); if(!f) return;
    const fd = new FormData(); fd.append('file', f);
    const t = toast('czytam XML rekordboxa…', 'info', 90000);
    try{
      const d = await api('/api/rekordbox/wczytaj', {method: 'POST', formData: fd});
      t.remove();
      toast(`wczytano: ${d.dopasowane} z ${d.w_xml} ${lm(d.w_xml, U)} · ${d.z_reczna_praca} z ręczną pracą${d.nieodnalezionych ? ` · ${d.nieodnalezionych} nieodnalezionych` : ''}`, 'ok', 7000);
      ustLaduj(host);
    }catch(e){ t.remove(); }
  }
  async function ustDoktor(host, btn){
    btn.disabled = true; btn.textContent = 'sprawdzam… (do pół minuty)';
    try{ ust.dok = await api('/api/doktor', {method: 'POST', body: {}}); $('#doktorBody', host).innerHTML = doktorHTML(ust.dok); }
    catch(e){ $('#doktorBody', host).innerHTML = `<span class="bad">✗ ${esc(e.message)}</span>`; }
    btn.disabled = false; btn.textContent = 'Sprawdź teraz';
    ustLaduj(host);                                   // wiersz ffmpeg bierze wynik z doktora
  }
  function ustRender(host){
    ust.host = host;
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Ustawienia</h1><div class="sub">Wszystko, co apka musi wiedzieć, żeby działać sama. Ustawiasz raz.</div></div>
        <div class="akcje"><button class="btn" data-a="wprowadzenie">Pokaż wprowadzenie</button></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 320px;gap:16px;flex:1;min-height:0">
        <div class="panel" style="overflow:auto;min-height:0" id="ustLista"><div class="pusto"><span class="spin"></span> sprawdzam stan slskd i rekordboxa…</div></div>
        <div style="display:flex;flex-direction:column;gap:16px;min-height:0">
          <div class="panel pad w-kol" id="ustZach" style="flex-shrink:0">${ustZachowanie()}</div>
          <div class="panel pad w-kol" id="ustCache" style="gap:12px;flex-shrink:0"><div class="etyk">CACHE ANALIZ</div><div class="dim" style="font-size:13px">liczę…</div></div>
          <div class="panel pad w-kol" style="flex:1;gap:12px;min-height:120px">
            <div class="head"><span class="etyk">INTEGRACJE</span><button class="btn mini" data-a="doktor" style="margin-left:auto">Sprawdź teraz</button></div>
            <div id="doktorBody" style="overflow:auto;min-height:0"></div>
          </div>
        </div>
      </div>`;
    on(host, 'click', '[data-a="cache-wyczysc"]', async (e, b) => {
      if(b.dataset.uzbrojony !== '1'){ b.dataset.uzbrojony = '1'; b.textContent = 'Na pewno? Kliknij ponownie'; b.classList.add('bad'); setTimeout(() => { b.dataset.uzbrojony = ''; b.textContent = 'Wyczyść cache'; b.classList.remove('bad'); }, 4000); return; }
      b.disabled = true;
      try{ const r = await api('/api/cache/wyczysc', {method: 'POST', body: {}}); S.uniewaznTracks(); S.toast(`usunięto ${r.removed} wpisów cache — utwory policzą się od nowa`, 'ok'); ustLaduj(host); }
      catch(err){ b.disabled = false; }
    });
    on(host, 'click', '#ustStart > button', (e, b) => { S.pref.set('startTryb', b.dataset.v); $('#ustZach', host).innerHTML = ustZachowanie(); });
    on(host, 'click', '#ustJezyk > button', (e, b) => { S.jezyk.set(b.dataset.v); $('#ustZach', host).innerHTML = ustZachowanie(); });
    on(host, 'click', '[data-a]', async (e, el) => {
      const a = el.dataset.a;
      if(a === 'wprowadzenie') S.pokaz('onboarding', {powrot: 'ustawienia'});
      else if(a === 'folder') ustZmienFolder(host);
      else if(a === 'slskd' && ust.dane) ustArkuszSlskd(ust.dane);
      else if(a === 'xml') ustWczytajXml(host);
      else if(a === 'wykryj'){ el.disabled = true; try{ await api('/api/config/autodetect', {method: 'POST'}); toast('klucz znaleziony i zapisany', 'ok'); ustLaduj(host); }catch(err){} el.disabled = false; }
      else if(a === 'obserwator'){ const wl = !el.classList.contains('on'); el.classList.toggle('on', wl); try{ ust.obs = await api('/api/obserwator', {method: 'POST', body: {wlaczony: wl}}); toast(wl ? 'obserwator włączony — nowe pliki analizują się same' : 'obserwator wyłączony'); ustLaduj(host); }catch(err){} }
      else if(a === 'doktor') ustDoktor(host, el);
    });
  }
  async function ustLaduj(host){
    const cicho = {cicho: true};
    const [d, obs, dok, rb, tracks] = await Promise.all([
      api('/api/config').catch(e => ({blad: e.message})),
      api('/api/obserwator', cicho).catch(() => null),
      api('/api/doktor', cicho).catch(() => null),
      api('/api/rekordbox/stan', cicho).catch(() => null),
      S.tracks().catch(() => null),
    ]);
    if(ust.host !== host) return;
    if(d.blad){ $('#ustLista', host).innerHTML = `<div class="pusto bad">✗ ${esc(d.blad)}</div>`; return; }
    ust.dane = d; ust.obs = obs; ust.dok = dok; ust.rb = rb;
    $('#ustLista', host).innerHTML = ustLista(d, obs, dok, rb, tracks);
    const analiz = tracks ? tracks.filter(t => t.analyzed).length : 0, czeka = tracks ? tracks.length - analiz : 0;
    let cacheStat = null; try{ cacheStat = await api('/api/cache', {cicho: true}); }catch(e){}
    $('#ustCache', host).innerHTML = `<div class="etyk">CACHE ANALIZ</div>
      <div style="display:flex;align-items:baseline;gap:8px"><span style="font-size:28px;font-weight:700;letter-spacing:-.02em;line-height:1">${S.fmtLicz(cacheStat ? (cacheStat.harmonic ?? analiz) : analiz)}</span><span class="dim" style="font-size:13px">utworów z BPM i tonacją${cacheStat && cacheStat._total_bytes ? ` · ${S.fmtMB(cacheStat._total_bytes)} na dysku` : ''}${czeka ? ` · <span class="warn">${czeka} bez analizy</span>` : ''}</span></div>
      <div class="dim" style="font-size:12.5px">Wyniki analiz są zapamiętane, więc druga analiza tego samego pliku trwa ułamek sekundy. Czyszczenie wymusza policzenie wszystkiego od nowa.</div>
      <button class="btn sr cichy" data-a="cache-wyczysc" style="margin-top:auto;align-self:flex-start" title="usuwa zapamiętane analizy — pliki zostają nietknięte">Wyczyść cache</button>`;
    $('#doktorBody', host).innerHTML = doktorHTML(dok);
    if(S.biezacy() === 'ustawienia') S.tytul('USTAWIENIA · SELEKTA' + (S.stan.wersja ? ' ' + S.stan.wersja : ''));
  }
  S.ekran('ustawienia', {tytul: () => 'USTAWIENIA · SELEKTA' + (S.stan.wersja ? ' ' + S.stan.wersja : ''), render: ustRender, load: ustLaduj});

  // ============================================================
  // 6b · ZANIM ZACZNIESZ — pierwsze uruchomienie, konfiguracja w jednym kliknięciu
  // /api/setup/stan, /api/setup/folder, /api/setup/instaluj, /api/setup/konfiguruj,
  // /api/setup/konto, /api/setup/polaczenie, /api/slskd/start
  // Hasła do Soulseeka NIE dotykamy poza formularzem: idzie prosto do slskd na tej maszynie.
  // ============================================================
  const zan = {stan: null, wToku: null, zajety: false, host: null};

  async function czekajNaPolaczenie(prog, sekund = 25){
    for(let i = 0; i < sekund; i++){
      prog(`<span class="spin"></span> łączę z siecią Soulseek… ${i + 1}s`);
      await czekaj(1000);
      try{
        const d = await api('/api/setup/polaczenie', {cicho: true});
        if(d.stan === 'polaczony') return 'połączono z siecią Soulseek';
        if(d.stan === 'niezalogowany' && i > 12) throw new Error(d.opis);
      }catch(e){ if(i > 12) throw e; }
    }
    throw new Error('nie udało się połączyć — sprawdź login i hasło');
  }
  // Formularz konta (jak w starym UI). Hasło wpisuje UŻYTKOWNIK i trafia wyłącznie do
  // konfiguracji slskd na tym komputerze — nie zapisujemy go, nie pokazujemy, czyścimy z DOM.
  // Obietnica kończy się sukcesem albo anulowaniem; błąd zostaje w formularzu do poprawki.
  function formularzKonta(host){
    return new Promise(zwroc => {
      const box = document.createElement('div'); box.className = 'w-konto';
      box.innerHTML = `
        <div style="font-weight:600;font-size:14px">Konto Soulseek</div>
        <div class="dim" style="font-size:12.5px;line-height:1.5">Soulseek <b class="muted">nie ma rejestracji</b>. Wymyśl nazwę i hasło — konto powstaje przy pierwszym logowaniu. Jeśli nazwa jest zajęta, logowanie się nie uda i trzeba wybrać inną.<br><span class="warn">Zapisz hasło w menedżerze haseł — nie ma odzyskiwania, bo konto nie ma adresu e-mail.</span></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><input class="pole" data-p="login" placeholder="nazwa użytkownika" autocomplete="username" style="flex:1;min-width:150px"><input class="pole" data-p="haslo" type="password" placeholder="hasło" autocomplete="new-password" style="flex:1;min-width:150px"></div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><button class="btn acc sr" data-p="zapisz">Połącz</button><button class="btn cichy sr" data-p="anuluj">Anuluj</button><span class="dim" style="font-size:11.5px">hasło trafia tylko do konfiguracji slskd na tym komputerze (prawa 0600)</span></div>
        <div class="w-prog" data-p="prog"></div>`;
      host.appendChild(box);
      const q = n => box.querySelector(`[data-p="${n}"]`);
      const prog = (html, zly) => { q('prog').innerHTML = html; q('prog').className = 'w-prog' + (zly ? ' bad' : ''); };
      q('login').focus();
      q('anuluj').onclick = () => { box.remove(); zwroc('pominięte — konto podasz później w Ustawieniach → Soulseek'); };
      q('zapisz').onclick = async () => {
        const l = q('login').value.trim(), h = q('haslo').value;
        if(!l || !h){ prog('<span class="warn">podaj nazwę i hasło</span>'); return; }
        q('zapisz').disabled = true; prog('<span class="spin"></span> zapisuję i restartuję slskd…');
        try{
          await api('/api/setup/konto', {method: 'POST', body: {login: l, haslo: h}, cicho: true});
          q('haslo').value = '';                       // nie trzymamy go w DOM
          const wynik = await czekajNaPolaczenie(prog);
          box.remove(); zwroc(wynik);
        }catch(e){ q('zapisz').disabled = false; prog('✗ ' + esc(e.message), true); }
      };
      q('haslo').addEventListener('keydown', e => { if(e.key === 'Enter') q('zapisz').click(); });
    });
  }
  const AKCJE = {
    'wybierz-folder': {etykieta: 'Wskaż folder', fn: async () => {
      const d = await api('/api/setup/folder', {method: 'POST', cicho: true});
      if(d.cancelled) return 'anulowano — wskaż folder, w którym trzymasz muzykę';
      S.uniewaznTracks(); return `ustawiono: ${d.utworow} ${lm(d.utworow, U)}`; }},
    'instaluj-slskd': {etykieta: 'Zainstaluj', fn: async () => {
      zanimProg('pobieram slskd (ok. 55 MB) — to potrwa chwilę…', true);
      const d = await api('/api/setup/instaluj', {method: 'POST', cicho: true}); return d.message; }},
    'konfiguruj': {etykieta: 'Skonfiguruj', fn: async () => {
      await api('/api/setup/konfiguruj', {method: 'POST', body: {}, cicho: true}); return 'klucz wygenerowany, katalogi ustawione'; }},
    'podaj-konto': {etykieta: 'Podaj konto', fn: () => formularzKonta($('#zanimKroki', zan.host))},
    'uruchom-slskd': {etykieta: 'Uruchom', fn: async () => {
      const d = await api('/api/slskd/start', {method: 'POST', cicho: true});
      if(!d.ok) throw new Error(d.message || 'nie udało się uruchomić');
      return czekajNaPolaczenie(h => zanimProg(h)); }},
  };
  function zanimProg(html, spinner){ const el = $('#zanimProg', zan.host); if(!el) return; el.innerHTML = (spinner ? '<span class="spin"></span> ' : '') + html; el.className = 'w-prog'; }
  function zanimBlad(msg){ const el = $('#zanimProg', zan.host); if(!el) return; el.textContent = '✗ ' + msg; el.className = 'w-prog bad'; }
  function zanimKrokHTML(k, i){
    const st = k.gotowe ? 'done' : (zan.wToku === k.id ? 'run' : 'wait');
    const cta = (!k.gotowe && k.akcja && AKCJE[k.akcja] && !zan.zajety) ? `<button class="btn sr" data-i="${i}">${AKCJE[k.akcja].etykieta}</button>` : '<span></span>';
    return `<div class="w-krok ${st}"><span class="z">${st === 'done' ? '✓' : st === 'run' ? '<i></i>' : '·'}</span><div><div class="t">${esc(k.tytul)}</div><div class="o">${esc(k.opis)}</div></div>${cta}</div>`;
  }
  function zanimRysuj(){
    const d = zan.stan; if(!d || !zan.host) return;
    $('#zanimKroki', zan.host).innerHTML = (d.kroki || []).map(zanimKrokHTML).join('');
    $('#zanimLicznik', zan.host).textContent = `${d.zrobionych} / ${d.krokow}`;
    $('#zanimBar', zan.host).style.width = Math.round(100 * d.zrobionych / Math.max(1, d.krokow)) + '%';
    const auto = $('#zanimAuto', zan.host), pomin = $('#zanimPomin', zan.host);
    auto.textContent = d.gotowe ? 'GOTOWE — POKAŻ MI APKĘ ›' : 'USTAW WSZYSTKO ZA MNIE';
    pomin.classList.toggle('hide', !!d.gotowe);
  }
  async function zanimOdswiez(){
    const d = await api('/api/setup/stan', {cicho: true});
    zan.stan = d; S.stan.setup = d; zanimRysuj();
    if(d.gotowe) zanimProg('✅ wszystko gotowe');
    return d;
  }
  async function zanimWykonaj(i){
    const k = zan.stan.kroki[i], a = k && AKCJE[k.akcja];
    if(!a || zan.zajety) return false;
    zan.zajety = true; zan.wToku = k.id; zanimRysuj(); zanimProg('pracuję…', true);
    let ok = true;
    try{ zanimProg(esc(await a.fn(k))); }
    catch(e){ zanimBlad(e.message || 'nie udało się'); ok = false; }
    finally{ zan.zajety = false; zan.wToku = null; }
    await zanimOdswiez().catch(() => {});
    return ok;
  }
  // jedno kliknięcie robi wszystko, co da się zrobić bez pytania użytkownika
  async function zanimAuto(){
    if(zan.stan && zan.stan.gotowe){ zanimZakoncz(); return; }
    if(zan.zajety) return;
    const btn = $('#zanimAuto', zan.host); btn.disabled = true;
    for(let runda = 0; runda < 6; runda++){
      const stan = zan.stan || await zanimOdswiez();
      const konto = (stan.kroki || []).find(x => x.id === 'konto');
      const k = (stan.kroki || []).find(x => !x.gotowe && ['instaluj-slskd', 'konfiguruj', 'uruchom-slskd'].includes(x.akcja));
      if(!k) break;
      if(k.akcja === 'uruchom-slskd' && konto && !konto.gotowe) break;   // bez konta nie połączy się — nie każ czekać 25 s
      if(!await zanimWykonaj(stan.kroki.indexOf(k))) break;
    }
    btn.disabled = false;
    const stan = zan.stan;
    if(stan && !stan.gotowe){
      const brak = (stan.kroki || []).find(k => !k.gotowe && k.akcja);
      if(brak && brak.akcja === 'podaj-konto'){ zanimProg('resztę zrobiłem — zostało tylko Twoje konto Soulseek →'); zanimWykonaj(stan.kroki.indexOf(brak)); }
      else if(brak && brak.akcja === 'wybierz-folder') zanimProg('wskaż jeszcze folder z muzyką →');
    }
  }
  function zanimZakoncz(){
    S.status(true).catch(() => {});
    S.uniewaznTracks();
    if(!wprowadzenieWidziane() && S.EKRANY.onboarding) S.pokaz('onboarding');
    else dalejPoStarcie();
  }
  function zanimRender(host){
    zan.host = host;
    host.innerHTML = `<div class="w-pelny">
      <div class="w-chrome"><span></span><span></span><span></span></div>
      <div class="w-glow"></div>
      <div class="w-zanim">
        <div style="display:flex;flex-direction:column;gap:22px">
          <img src="/static/assets/selekta-mark.png" alt="" style="width:120px;height:120px;object-fit:contain;filter:drop-shadow(0 0 30px rgba(255,106,61,.4))">
          <div class="kicker">PIERWSZE URUCHOMIENIE</div>
          <h1>Zanim zaczniesz</h1>
          <p>Kilka rzeczy do ustawienia — raz, potem apka pamięta. Możesz zrobić wszystko jednym kliknięciem albo krok po kroku.</p>
          <div style="display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap">
            <button class="btn acc" id="zanimAuto" style="border-radius:12px;padding:16px 26px;font-size:14.5px;letter-spacing:.05em;box-shadow:0 0 30px rgba(255,106,61,.3)">USTAW WSZYSTKO ZA MNIE</button>
            <button class="btn goly" id="zanimPomin" style="padding:16px 14px;font-size:13.5px;color:var(--dim)">Pomiń konfigurację</button>
          </div>
          <div id="zanimProg" class="w-prog"></div>
        </div>
        <div class="w-karta">
          <div style="display:flex;align-items:center;gap:12px"><span class="etyk">KONFIGURACJA</span><span id="zanimLicznik" style="margin-left:auto;font:500 11px var(--mono);color:var(--dim)">— / —</span></div>
          <div class="pasek-post"><i id="zanimBar" style="width:0%"></i></div>
          <div id="zanimKroki" style="display:flex;flex-direction:column"><div class="pusto"><span class="spin"></span> sprawdzam, czego brakuje…</div></div>
          <div style="font-size:12.5px;color:var(--dim2);line-height:1.5">Soulseek zawsze jako Twój własny slskd — selekta zarządza biblioteką i szuka, nie rozprowadza nagrań.</div>
        </div>
      </div></div>`;
    $('#zanimAuto', host).onclick = zanimAuto;
    $('#zanimPomin', host).onclick = zanimZakoncz;
    on(host, 'click', '.w-krok button[data-i]', (e, b) => zanimWykonaj(+b.dataset.i));
  }
  async function zanimLaduj(host){
    zan.host = host; zan.wToku = null; zan.zajety = false;
    zanimProg('');
    try{ await zanimOdswiez(); }
    catch(e){ zanimBlad(e.message); $('#zanimKroki', host).innerHTML = `<div class="pusto">nie udało się sprawdzić stanu — czy apka działa?</div>`; }
  }
  S.ekran('zanim', {tytul: 'Zanim zaczniesz', pelny: true, render: zanimRender, load: zanimLaduj});

  // ============================================================
  // 6c · ONBOARDING — 7 kart wprowadzenia (treść ze starego samouczka, karta 5 wg projektu)
  // ============================================================
  const onb = {i: 0, powrot: null, host: null};
  const KARTY = [
    {temat: 'START', tytul: 'Playlista ze Spotify → gotowy set w rekordboksie',
     lead: 'Wklejasz link do playlisty. Selekta sprawdza, co już masz na dysku, resztę próbuje ściągnąć, poprawia nazwy i okładki, liczy BPM i tonację, układa kolejność i wysyła gotowy set do rekordboxa.',
     punkty: [['Masz / brakuje', 'porównanie z biblioteką — czego nie masz, apka szuka na Soulseeku, w tle.'],
              ['Porządek w plikach', 'nazwy, okładki, BPM, tonacja, jakość — policzone raz, pamiętane.'],
              ['Set w rekordboksie', 'kolejność ułożona, playlista podpięta. Odpalasz rekordbox i grasz.']]},
    {temat: 'DWA TRYBY', tytul: 'Dwa tryby', lead: 'Na pierwszym ekranie wybierasz, jak chcesz pracować.',
     punkty: [['AUTOMATYCZNY', 'pięć kroków, duże przyciski, wszystko dzieje się samo. Do użycia także wtedy, gdy jesteś po kilku piwach.'],
              ['RĘCZNY', 'pełna kontrola — biblioteka, analiza, zdrowie, eksport, ustawienia osobno.'],
              ['Zmienisz zdanie', 'w Ustawieniach → „Start w trybie”: Pytaj, Auto albo Ręczny.']]},
    {temat: 'TRYB AUTO', tytul: 'Tryb automatyczny — pięć kroków', lead: 'Klikasz „dalej” i tyle.',
     punkty: [['Wklej playlistę', 'Spotify, Apple Music, YouTube, Tidal, SoundCloud — albo przeciągnij plik M3U czy XML z rekordboxa.'],
              ['Masz / do ściągnięcia', 'dwie kolumny. Utwory pobierają się w tle i same przeskakują na lewo, gdy są gotowe.'],
              ['Nazwa setu', 'powstanie osobny folder — tylko z tym setem, nie z całą biblioteką.'],
              ['Analiza', 'BPM, tonacja, jakość, okładki, uszkodzenia.'],
              ['Sprawdź przed graniem', 'ostatni moment na poprawki. Potem playlista ląduje w rekordboksie.']], numery: true},
    {temat: 'BIBLIOTEKA', tytul: 'Biblioteka', lead: 'Zakładka „Biblioteka” w trybie ręcznym — wszystko, co masz na dysku, z analizą i odsłuchem.',
     punkty: [['Odsłuch', 'przycisk ▶ przy każdym utworze, z przewijaniem — gra w dolnym pasku.'],
              ['Filtry', 'szukajka plus format, jakość, tonacja, zakres BPM i czasu.'],
              ['Zaznaczanie', 'zaznacz kilka utworów i zrób z nich playlistę jednym kliknięciem.'],
              ['Finder i kosz', 'pokaż plik w Finderze albo usuń — usunięte idzie do kosza, z „cofnij”.']]},
    {temat: 'JAKOŚĆ', tytul: 'Jakość — po to jest ta apka', widma: true,
     punkty: [['Plik z YouTube’a przerobiony na „FLAC” dalej brzmi jak 128 kbps.', 'Selekta patrzy na widmo i mówi, co naprawdę siedzi w pliku.'],
              ['Po pobraniu porównuje odsłuchem z podglądem ze Spotify.', 'Łapie ucięte transfery, których widmo w środku nie widzi.'],
              ['Wersja miksu ma znaczenie.', 'Radio Edit 3:20 to nie Original 6:41 — czas trwania i sygnatura miksu rozstrzygają.']]},
    {temat: 'PORZĄDKI', tytul: 'Nic nie znika bez Twojej zgody',
     lead: 'Zakładka „Porządki” pokazuje propozycje: duplikaty, lepsze wersje, podejrzane pobrania. Przy każdej widzisz dowody i możesz odsłuchać pliki.',
     punkty: [['Zatwierdzasz Ty', 'apka sama nigdy nic nie kasuje.'],
              ['Kosz zamiast kasowania', 'zatwierdzone pliki idą do kosza i da się je przywrócić.']]},
    {temat: 'SOULSEEK', tytul: 'Dwie rzeczy o Soulseeku', lead: 'Warto wiedzieć, zanim się zdziwisz.',
     punkty: [['Jedno konto = jedno zalogowanie', 'jeśli zalogujesz się na tym samym koncie na innym komputerze, tutaj Cię wyrzuci.'],
              ['Nie ma odzyskiwania hasła', 'konto nie ma adresu e-mail. Zapisz hasło w menedżerze haseł.'],
              ['Pobieranie idzie w tle', 'możesz zamknąć apkę — kolejka wróci i dokończy przy następnym uruchomieniu.']]},
  ];
  // dwa panele-widma z projektu 6c — wysokości słupków 1:1
  const WIDMA = `<div class="w-widma">
    <div class="w-widmo"><div class="e bad">FAŁSZYWY FLAC · 24-BIT</div>
      <div class="s">${[96, 90, 82, 76, 60].map(h => `<span style="height:${h}%"></span>`).join('')}${[6, 4, 4, 3, 3].map(h => `<span style="height:${h}%;background:var(--bad)"></span>`).join('')}</div>
      <div class="p">pasmo ucięte na 16 kHz → źródło 128 kbps</div></div>
    <div class="w-widmo ok"><div class="e ok">PRAWDZIWY LOSSLESS</div>
      <div class="s">${[96, 90, 84, 78, 68].map(h => `<span style="height:${h}%"></span>`).join('')}${[58, 46, 34, 22, 12].map(h => `<span style="height:${h}%;background:var(--ok)"></span>`).join('')}</div>
      <div class="p">pasmo do 21,3 kHz · naturalny spadek</div></div></div>`;

  function onbRysuj(){
    const host = onb.host; if(!host) return;
    const k = KARTY[onb.i], ostatnia = onb.i === KARTY.length - 1;
    $('#onbKarta', host).innerHTML = `
      <div class="kropki">${KARTY.map((_, i) => `<span class="${i <= onb.i ? 'on' : ''}"></span>`).join('')}</div>
      <div><div class="kicker" style="margin-bottom:14px">${onb.i + 1} / ${KARTY.length} · ${k.temat}</div><h1>${esc(k.tytul)}</h1></div>
      ${k.widma ? WIDMA : ''}
      ${k.lead ? `<p class="lead">${esc(k.lead)}</p>` : ''}
      <div style="display:flex;flex-direction:column">${k.punkty.map(([a, b], i) => `<div class="w-punkt"><span class="n">${k.numery ? i + 1 : i + 1}</span><div class="t"><b>${esc(a)}</b> <span>${esc(b)}</span></div></div>`).join('')}</div>
      <div style="display:flex;align-items:center;gap:10px">
        <button class="btn cichy" data-a="wstecz" ${onb.i ? '' : 'disabled'} style="padding:11px 16px">‹ Wstecz</button>
        <button class="btn acc" data-a="dalej" style="padding:11px 20px">${ostatnia ? 'Zaczynamy ›' : 'Dalej ›'}</button>
        <button class="btn goly" data-a="pomin" style="margin-left:auto">Pomiń</button>
      </div>`;
  }
  function onbZakoncz(){
    S.pref.set('onboardingWidziany', true);
    if(onb.powrot && S.EKRANY[onb.powrot]) S.pokaz(onb.powrot); else dalejPoStarcie();
  }
  function onbRender(host){
    onb.host = host;
    host.innerHTML = `<div class="w-pelny"><div class="w-chrome"><span></span><span></span><span></span></div><div class="w-onb"><div class="karta" id="onbKarta"></div></div></div>`;
    on(host, 'click', '[data-a]', (e, b) => {
      const a = b.dataset.a;
      if(a === 'wstecz' && onb.i){ onb.i--; onbRysuj(); }
      else if(a === 'dalej'){ if(onb.i >= KARTY.length - 1) onbZakoncz(); else { onb.i++; onbRysuj(); } }
      else if(a === 'pomin') onbZakoncz();
    });
    document.addEventListener('keydown', e => {
      if(S.biezacy() !== 'onboarding' || !$('#arkusz').classList.contains('hide')) return;
      if(e.key === 'ArrowRight' || e.key === 'Enter') $('[data-a="dalej"]', host).click();
      else if(e.key === 'ArrowLeft') $('[data-a="wstecz"]', host).click();
      else if(e.key === 'Escape') onbZakoncz();
    });
  }
  function onbLaduj(host, arg){ onb.host = host; onb.i = 0; onb.powrot = (arg && arg.powrot) || null; onbRysuj(); }
  S.ekran('onboarding', {tytul: 'Wprowadzenie', pelny: true, render: onbRender, load: onbLaduj});

  // wprowadzenie przy pierwszym uruchomieniu pokazuje powłoka (S.start)
})();
