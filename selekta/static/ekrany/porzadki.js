/* ============================================================
   porzadki.js — cztery ekrany grupy „Biblioteka”:
     porzadki  (artboard 3b)  — kolejka decyzji: kopie, ulepszenia,
                                podejrzane pobrania, uszkodzone, okładki
     zdrowie   (bez artboardu) — raport /api/health i akcje naprawcze
     uchem     (bez artboardu) — wyniki analiz, których apka nie jest pewna
     radar     (artboard 5a)  — nowe wydania artystów z biblioteki

   Zasada wspólna: apka pokazuje DOWODY i czeka. Nic nie znika bez
   zgody, kasowanie = kosz, każdą decyzję da się cofnąć.
   ============================================================ */
(() => {
const {esc, $, $$, on, api, toast, fmtLicz, fmtTime, nazwaPliku, CAM, pref} = S;

/* ---------- style czterech ekranów (tokeny z index.html) ---------- */
const CSS = `
#ekran-porzadki .kafel .etyk,#ekran-zdrowie .kafel .etyk,#ekran-uchem .kafel .etyk{color:var(--dim);letter-spacing:.1em}
.tag.warn{background:var(--warn);color:#0f0d0c} .tag.ok{background:var(--ok);color:#0f0d0c} .tag.bad{background:var(--bad);color:#0f0d0c}
.tag.info{background:var(--info);color:#0f0d0c} .tag.acc{background:var(--acc);color:#0f0d0c} .tag.dim{background:var(--line3);color:var(--muted)}
.btn.pytam{border-color:var(--warn);color:var(--warn)}
.pz-btn{background:transparent;border:1px solid var(--line);color:var(--dim);border-radius:8px;padding:8px 12px;font-weight:600;font-size:12.5px;white-space:nowrap}
.pz-btn:hover{color:var(--txt)} .pz-btn.acc{color:var(--acc);border-color:var(--acc)} .pz-btn.acc:hover{background:var(--acc);color:#0f0d0c}
.pz-cta{border:0;border-radius:8px;padding:8px 14px;font-weight:800;font-size:12.5px;color:#0f0d0c;background:var(--acc);white-space:nowrap}
.pz-cta.ok{background:var(--ok)} .pz-cta.bad{background:var(--bad)} .pz-cta.info{background:var(--info)} .pz-cta.warn{background:var(--warn)}
.pz-cta:hover{filter:brightness(1.12)}
.pz-btn:disabled,.pz-cta:disabled{opacity:.5;cursor:default}
.pz-lista{display:flex;flex-direction:column;gap:10px;overflow:auto;flex:1;min-height:0}
.pz-karta{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;display:grid;grid-template-columns:100px minmax(0,1fr) auto;gap:20px;align-items:center}
.pz-karta:hover{border-color:var(--line3)}
.pz-karta.gotowa{opacity:.72}
.pz-karta .tytul{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pz-karta .opis{font-size:13px;color:var(--dim);margin-top:3px;line-height:1.45}
.pz-karta .opis b{color:var(--txt);font-weight:600}
.pz-karta .uwaga{margin-top:8px}
.uwaga.ok{border-left-color:var(--ok)} .uwaga.ok b{color:var(--ok)} .uwaga.bad{border-left-color:var(--bad)} .uwaga.bad b{color:var(--bad)}
.pz-karta .chipy{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.chip{font:500 11.5px var(--mono);background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:3px 9px;color:var(--muted);max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip.b{color:var(--dim)} .chip.klik{cursor:pointer} .chip.klik:hover{border-color:var(--line3);color:var(--txt)} .chip.gra{border-color:var(--acc);color:var(--acc)}
.chip i{font-style:normal;font-size:10px;letter-spacing:.08em;text-transform:uppercase;margin-right:7px;color:var(--dim2)} .chip i.ok{color:var(--ok)}
.chip em{font-style:normal;margin-left:7px} .chip em.ok{color:var(--ok)} .chip em.warn{color:var(--warn)} .chip em.bad{color:var(--bad)}
.pz-karta .akcje{display:flex;gap:8px;align-items:center}

.zd-siatka{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:16px;flex:1;min-height:0}
.zd-panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.zd-panel .glowa{display:flex;align-items:center;gap:10px;padding:15px 20px;border-bottom:1px solid var(--line);flex-shrink:0}
.zd-panel .glowa .n{font:500 11px var(--mono);color:var(--dim)}
.zd-panel .glowa .btn{margin-left:auto}
.zd-panel .lista{padding:4px 0}
.zd-wiersz{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;padding:9px 20px;border-bottom:1px solid var(--line2)}
.zd-wiersz:last-child{border-bottom:0} .zd-wiersz:hover{background:var(--hover)}
.zd-wiersz .t{font-weight:600;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.zd-wiersz .s{font:500 11.5px var(--mono);color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.zd-pusto{padding:22px 20px;color:var(--dim2);font-size:13px}

.uch-naglowek,.uch-wiersz{display:grid;grid-template-columns:24px 40px minmax(0,1fr) 64px 40px 28px auto;gap:12px;align-items:center;padding:10px 18px;border-bottom:1px solid var(--line2)}
.uch-naglowek{padding:12px 18px 12px 20px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel);z-index:1}
.uch-wiersz{border-left:2px solid transparent} .uch-wiersz:hover{background:var(--hover)}
.uch-wiersz.w3{border-left-color:var(--bad)} .uch-wiersz.w2{border-left-color:var(--warn)} .uch-wiersz.w1{border-left-color:var(--line3)}
.uch-wiersz .znak{font:700 16px var(--mono);text-align:center;line-height:1}
.uch-wiersz .okladka{width:40px;height:40px;display:block}
.uch-wiersz .t{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.uch-wiersz .t span{font-weight:400;font-size:12.5px;color:var(--dim);margin-left:8px}
.uch-wiersz .powody{margin:4px 0 0;padding:0;list-style:none;font-size:12.5px;line-height:1.45}
.uch-wiersz .bpm{font:500 12.5px var(--mono);color:var(--dim);text-align:right}
.uch-wiersz .graj{width:28px;height:28px;border-radius:50%;border:1px solid var(--line);background:transparent;display:grid;place-items:center;font-size:10px;color:var(--dim);padding:0}
.uch-wiersz .graj:hover,.uch-wiersz .graj.gra{border-color:var(--acc);color:var(--acc)}
.uch-arkusz .graj-duzy{width:40px;height:40px;border-radius:50%;background:var(--acc);color:#0f0d0c;border:0;font-size:12px;display:grid;place-items:center}
.uch-arkusz .zamknij{background:transparent;border:1px solid var(--line);color:var(--dim);border-radius:8px;width:40px;height:40px;font-size:14px}
.uch-arkusz .zamknij:hover{color:var(--txt)}
.uch-arkusz .kafel{background:var(--bg)} .uch-arkusz .kafel .etyk{margin-top:0} .uch-arkusz .kafel .liczba{margin-top:10px}
.uch-arkusz .kafel .pod{font-size:12px;color:var(--dim);margin-top:6px;line-height:1.4}

.rd-siatka{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;overflow:auto;flex:1;min-height:0;align-content:start}
.rd-karta{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:12px}
.rd-karta:hover{border-color:var(--line3)}
.rd-okladka{aspect-ratio:1;border-radius:10px;background:repeating-linear-gradient(135deg,#221d1a 0 6px,#1a1613 6px 12px);position:relative;overflow:hidden}
.rd-okladka img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.rd-okladka .podpis{position:absolute;top:10px;left:10px;font:500 10px var(--mono);color:var(--dim2)}
.rd-okladka .kropka{position:absolute;top:10px;right:10px;width:8px;height:8px;border-radius:50%;background:var(--line3)}
.rd-okladka .kropka.nowe{background:var(--acc);box-shadow:0 0 8px var(--acc)}
.rd-tytul{font-weight:700;font-size:15px} .rd-kto{font-size:13px;color:var(--dim);margin-top:2px}
.rd-stopka{display:flex;align-items:center;gap:8px;margin-top:auto}
.rd-stopka .data{font:500 11px var(--mono);color:var(--dim2);white-space:nowrap}
.rd-btn{background:transparent;border:1px solid var(--line);color:var(--txt);border-radius:7px;padding:6px 11px;font-weight:600;font-size:12px;white-space:nowrap;cursor:pointer;text-decoration:none;display:inline-block}
.rd-btn:hover{border-color:var(--acc);color:var(--txt)} .rd-btn.sklep{margin-left:auto}
.rd-btn.cichy{color:var(--dim)} .rd-btn.cichy:hover{color:var(--txt);border-color:var(--line)}
.rd-btn.jest{color:var(--ok);border-color:transparent;cursor:default}
.rd-btn:disabled{opacity:.5;cursor:default}
.rd-pusto{grid-column:1/-1;padding:48px 40px;text-align:center;color:var(--dim);font-size:13.5px;line-height:1.5;border:1px dashed var(--line3);border-radius:14px}
.rd-zyczenia{grid-column:1/-1;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.rd-zyczenia .glowa{display:flex;align-items:center;gap:10px;padding:15px 20px;border-bottom:1px solid var(--line)}
.rd-zyczenia .glowa .n{font:500 11px var(--mono);color:var(--dim)}
.rd-zyczenia .wiersze{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 24px;padding:4px 20px}
.rd-zycz{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line2);min-width:0}
.rd-zycz .t{flex:1;min-width:0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rd-zycz .t span{color:var(--dim)}
.rd-zycz .data{font:500 10.5px var(--mono);color:var(--dim2)}
`;
const styl = document.createElement('style'); styl.textContent = CSS; document.head.appendChild(styl);

/* ---------- drobiazgi wspólne ---------- */
const odmiana = (n, [j, m, w]) => { n = Math.abs(n || 0); if(n === 1) return j; const r = n % 10, r2 = n % 100; return (r >= 2 && r <= 4 && !(r2 >= 12 && r2 <= 14)) ? m : w; };
const pl = (v, d = 1) => (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d).replace('.', ',');
const fmtMb = v => v == null ? '' : pl(v) + ' MB';
const bezRozsz = n => String(n || '').replace(/\.[a-z0-9]{2,5}$/i, '');
const skrocFolder = f => String(f || '').replace(/^\/Users\/[^/]+/, '~');
const dwie = n => String(n).padStart(2, '0');
const dataKrotka = ts => { const d = new Date(ts); return isNaN(d) ? '' : `${dwie(d.getDate())}.${dwie(d.getMonth() + 1)}.${d.getFullYear()}`; };
const godzina = ts => { const d = new Date(ts); return isNaN(d) ? '' : `${dwie(d.getHours())}:${dwie(d.getMinutes())}`; };
const dzisiaj = ts => new Date(ts).toDateString() === new Date().toDateString();
function ileTemu(ts){
  const s = (Date.now() - ts) / 1000;
  if(s < 60) return 'przed chwilą';
  const m = Math.round(s / 60); if(m < 60) return `${m} min temu`;
  const h = Math.round(m / 60); if(h < 24) return `${h} godz. temu`;
  const d = Math.round(h / 24); return `${d} ${odmiana(d, ['dzień', 'dni', 'dni'])} temu`;
}
const kafel = (liczba, etyk, kolor = '') =>
  `<div class="kafel"><div class="liczba ${kolor}">${liczba}</div><div class="etyk">${etyk}</div></div>`;

async function bezpiecznie(fn){ try{ return await fn(); }catch(e){ console.warn(e); } }

// przycisk w trakcie pracy: kręciołek zamiast tekstu, szerokość bez skoków
async function zajety(btn, tekst, fn){
  const html = btn.innerHTML, szer = btn.offsetWidth;
  btn.disabled = true; btn.style.minWidth = szer + 'px';
  btn.innerHTML = `<span class="spin"></span> ${esc(tekst)}`;
  try{ return await fn(); }
  finally{ btn.disabled = false; btn.innerHTML = html; btn.style.minWidth = ''; }
}

// nieodwracalne (albo hurtowe) akcje wymagają drugiego kliknięcia w ten sam
// przycisk — natywny confirm() wybija z okna, a przypadkowe kliknięcie
// w „Napraw wszystkie tagi” nie powinno przepisywać setek plików
function potwierdz(btn, pytanie, fn){
  if(btn.dataset.pytam){
    clearTimeout(btn._t); delete btn.dataset.pytam; btn.classList.remove('pytam'); btn.innerHTML = btn._html;
    return fn();
  }
  btn._html = btn.innerHTML; btn.dataset.pytam = '1'; btn.classList.add('pytam'); btn.textContent = pytanie;
  btn._t = setTimeout(() => { delete btn.dataset.pytam; btn.classList.remove('pytam'); btn.innerHTML = btn._html; }, 6000);
}

// odsłuch: tytuł/artystę bierzemy z metadanych, a gdy ich brak — z nazwy
function grajPlik(plik, meta = {}){
  const stem = bezRozsz(nazwaPliku(plik));
  const [a, ...t] = stem.split(' - ');
  S.player.graj({file: plik, title: meta.title || (t.length ? t.join(' - ') : stem),
                 artist: meta.artist || (t.length ? a : ''), bpm: meta.bpm, camelot: meta.camelot});
}
function podswietlGrane(){
  const f = S.player.biezacyPlik();
  $$('[data-graj]').forEach(el => el.classList.toggle('gra', !!f && el.dataset.graj === f));
}
document.addEventListener('selekta:player', podswietlGrane);

// /api/health liczy się długo przy dużej bibliotece — Porządki i Zdrowie
// dzielą jeden wynik zamiast skanować dwa razy. Skan idzie W TLE na serwerze
// (?tlo=1): odpytujemy o postęp co sekundę, zamiast trzymać jedno zapytanie
// przez minutę i dostać „Failed to fetch”.
const czekaj = ms => new Promise(r => setTimeout(r, ms));
async function wTle(url, postep){
  for(let i = 0; i < 3600; i++){
    const d = await api(url + (url.includes('?') ? '&' : '?') + 'tlo=1', {cicho: true});
    if(!d.w_toku) return d;
    if(d.blad) throw new Error(d.blad);
    if(postep) postep(d.zrobione || 0, d.wszystkie || 0);
    await czekaj(1000);
  }
  throw new Error('skan trwa zbyt długo');
}
const zdrowie = {
  dane: null, kiedy: 0, wTrakcie: null, postep: null,
  async pobierz(force = false){
    if(!force && this.dane && Date.now() - this.kiedy < 60000) return this.dane;
    if(this.wTrakcie) return this.wTrakcie;
    this.wTrakcie = wTle('/api/health', (z, w) => { this.postep = w ? `${z}/${w}` : null; document.dispatchEvent(new CustomEvent('selekta:zdrowie-postep')); })
      .then(d => { this.dane = d; this.kiedy = Date.now(); this.postep = null; return d; })
      .finally(() => { this.wTrakcie = null; });
    return this.wTrakcie;
  },
};
const powodUszkodzenia = f => {
  const h = zdrowie.dane || {};
  const x = (h.corrupt_info || []).find(c => c.file === f);
  return x ? x.powod : 'plik nie daje się odczytać — najpewniej przerwane pobieranie';
};
const folderINazwa = f => { const i = String(f || '').lastIndexOf('/'); return i < 0 ? {folder: '', nazwa: f} : {folder: f.slice(0, i), nazwa: f.slice(i + 1)}; };

/* ============================================================
   PORZĄDKI (3b)
   ============================================================ */
const RODZAJ = {
  duplikat:   {tag: 'DUBEL',      kolor: 'warn', cta: 'Zatwierdź', ctaKolor: ''},
  podmiana:   {tag: 'ULEPSZENIE', kolor: 'ok',   cta: 'Podmień',   ctaKolor: 'ok'},
  podejrzany: {tag: 'PODEJRZANY', kolor: 'bad',  cta: 'Do kosza',  ctaKolor: 'bad'},
};
const pz = {filtr: 'czeka', decyzje: [], zrobione: {}, pominiete: new Set(pref.get('porzadki.pominiete', []))};

// kopie w różnych folderach mają tę samą nazwę — wtedy dopisujemy folder
function etykietyPlikow(opisy){
  const foldery = new Set(opisy.map(o => o.folder || ''));
  return o => foldery.size > 1 && o.folder ? `${nazwaPliku(o.folder)}/${o.nazwa}` : o.nazwa;
}
function chip(o, rola, etyk){
  const jak = {ok: '✓', warn: '!', bad: '✗'}[o.jakosc] || '';
  const cechy = [o.format, fmtMb(o.mb), o.bitrate ? `${o.bitrate} kbps` : '',
                 o.pasmo_khz ? `pasmo ${pl(o.pasmo_khz)} kHz` : ''].filter(Boolean).join(' · ');
  const rolaTxt = {zostaw: 'zostaje', kosz: 'do kosza', pobrany: 'pobrany plik', wKoszu: 'w koszu'}[rola] || rola;
  const tytul = `${rolaTxt}${o.opis_jakosci ? ' · ' + o.opis_jakosci : ''}\n${o.path}\nkliknij, żeby odsłuchać`;
  return `<span class="chip klik ${rola === 'zostaw' ? '' : 'b'}" data-graj="${esc(o.path)}" title="${esc(tytul)}">` +
    `<i class="${rola === 'zostaw' ? 'ok' : ''}">${esc(rolaTxt)}</i>${esc(etyk(o))} · ${esc(cechy)}${jak ? `<em class="${o.jakosc}">${jak}</em>` : ''}</span>`;
}
function odcisk(o){
  if(!o) return '';
  const dobry = o.werdykt === 'match', zly = o.werdykt === 'mismatch';
  const kl = dobry ? 'ok' : (zly ? 'bad' : 'warn');
  const slowo = dobry ? 'dźwięk się zgadza' : (zly ? 'dźwięk to INNY utwór' : 'niepewne');
  return `<div class="uwaga ${kl}"><b>odcisk akustyczny: ${slowo}</b> — zgodność ${Math.round((o.zgodnosc || 0) * 100)} %` +
    `${o.zrodlo ? ` · porównano z: ${esc(o.zrodlo)}` : ''}</div>`;
}
function zastrzezenia(l){
  if(!l || !l.length) return '';
  return `<div class="uwaga"><b>zastrzeżenia</b>${l.map(z => `<div>– ${esc(z)}</div>`).join('')}</div>`;
}
const przyciskGraj = plik => `<button class="pz-btn" data-akcja="graj" data-plik="${esc(plik || '')}" ${plik ? '' : 'disabled'}>Odsłuchaj</button>`;

function kartaDecyzji(d){
  const r = RODZAJ[d.rodzaj] || {tag: d.rodzaj, kolor: 'dim', cta: 'Zatwierdź', ctaKolor: ''};
  const dow = d.dowody || {}, zostaw = dow.zostaw, zam = dow.zamowiono;
  let usun = dow.usun || [];
  if(d.stan === 'zatwierdzona'){
    // pary skąd → dokąd (stare decyzje: dopasowanie po pozycji)
    const gdzie = new Map((d.przeniesienia || []).map(p => [p.z, p.do]));
    usun = usun.map((o, i) => ({...o, path: gdzie.get(o.path) || (d.przeniesienia ? o.path : ((d.w_koszu || [])[i] || o.path))}));
  }
  const etyk = etykietyPlikow([zostaw, ...usun].filter(Boolean));
  const pierwszy = zostaw || usun[0] || {};
  let tytul, opis;
  if(d.rodzaj === 'podejrzany'){
    tytul = zam && (zam.artysta || zam.tytul) ? `${zam.artysta} — ${zam.tytul}` : bezRozsz(pierwszy.nazwa);
    opis = esc(d.powod);
  } else {
    tytul = bezRozsz(pierwszy.nazwa);
    const mbKosz = usun.reduce((s, o) => s + (o.mb || 0), 0);
    const ile = `${usun.length} ${odmiana(usun.length, ['plik', 'pliki', 'plików'])} · ${fmtMb(mbKosz)}`;
    opis = zostaw
      ? `${esc(d.powod)} — zostaje <b>${esc(zostaw.format || '')}</b>${zostaw.pasmo_khz ? ` (pasmo ${pl(zostaw.pasmo_khz)} kHz)` : (zostaw.bitrate ? ` (${zostaw.bitrate} kbps)` : '')}, do kosza ${ile}`
      : esc(d.powod);
  }
  if(d.stan === 'zatwierdzona') opis += ` <span class="ok">✓ zatwierdzone — ${(d.w_koszu || []).length} w koszu</span>`;
  if(d.stan === 'odrzucona') opis += ' <span class="dim2">— zostawione bez zmian</span>';
  const chipy = [
    zostaw ? chip(zostaw, 'zostaw', etyk) : '',
    ...usun.map(o => chip(o, d.rodzaj === 'podejrzany' ? 'pobrany' : (d.stan === 'zatwierdzona' ? 'wKoszu' : 'kosz'), etyk)),
    zam && (zam.artysta || zam.tytul)
      ? `<span class="chip b" title="tak brzmiało zamówienie"><i>zamówiono</i>${esc(zam.artysta)} — ${esc(zam.tytul)}${zam.czas ? ` · ${fmtTime(zam.czas)}` : ''}</span>` : '',
  ].join('');
  const akcje = d.stan === 'czeka'
    ? `${przyciskGraj(pierwszy.path)}
       <button class="pz-btn" data-akcja="odrzuc" data-id="${esc(d.id)}" title="zostaw wszystko bez zmian i nie pytaj o to ponownie">Pomiń</button>
       <button class="pz-cta ${r.ctaKolor}" data-akcja="zatwierdz" data-id="${esc(d.id)}" title="${d.rodzaj === 'podejrzany' ? 'przenieś pobrany plik do kosza' : 'przenieś gorsze kopie do kosza — da się cofnąć'}">${esc(r.cta)}</button>`
    : d.stan === 'zatwierdzona'
      ? `${przyciskGraj(pierwszy.path)}
         <button class="pz-btn acc" data-akcja="cofnij" data-id="${esc(d.id)}" title="przywróć pliki z kosza — decyzja wróci do kolejki">Cofnij</button>`
      : `${przyciskGraj(pierwszy.path)}
         <button class="pz-btn" data-akcja="cofnij" data-id="${esc(d.id)}" title="pominięta propozycja wróci do kolejki">Przywróć do kolejki</button>`;
  return `<div class="pz-karta ${d.stan !== 'czeka' ? 'gotowa' : ''}" data-id="${esc(d.id)}">
    <span class="tag ${d.stan === 'czeka' ? r.kolor : 'dim'}">${esc(r.tag)}</span>
    <div style="min-width:0"><div class="tytul" title="${esc(tytul)}">${esc(tytul)}</div><div class="opis">${opis}</div>
      ${odcisk(dow.odcisk)}${zastrzezenia(dow.zastrzezenia)}<div class="chipy">${chipy}</div></div>
    <div class="akcje">${akcje}</div></div>`;
}

// uszkodzone pliki i brak okładek nie są decyzjami w backendzie (to /api/health),
// ale w projekcie stoją w tej samej kolejce — „Pomiń” chowa kartę do czasu,
// aż problem zniknie i wróci; wykonane akcje zostają na ekranie do końca sesji
function kartaZdrowia(typ, f){
  const usz = typ === 'uszkodzony';
  const klucz = (usz ? 'c:' : 'o:') + f;
  const zrob = pz.zrobione[klucz];
  const opis = zrob ? `<span class="ok">✓ ${esc(zrob)}</span>` : (usz
    ? `${esc(powodUszkodzenia(f))}. „Pobierz ponownie” dopisze go do listy życzeń; sam plik zostaje na miejscu`
    : 'w tagach nie ma okładki — „Dociągnij” poszuka jej w iTunes po artyście i tytule z tagów (tylko przy zgodnym wykonawcy) i nie zmieni tagów');
  const akcje = zrob ? '' : `${przyciskGraj(f)}
      <button class="pz-btn" data-akcja="pomin" data-klucz="${esc(klucz)}" title="schowaj tę kartę, dopóki problem nie zniknie">Pomiń</button>
      <button class="pz-cta ${usz ? 'bad' : 'info'}" data-akcja="${usz ? 'pobierz' : 'okladka'}" data-plik="${esc(f)}" data-klucz="${esc(klucz)}">${usz ? 'Pobierz ponownie' : 'Dociągnij'}</button>`;
  return `<div class="pz-karta ${zrob ? 'gotowa' : ''}"><span class="tag ${usz ? 'bad' : 'info'}">${usz ? 'USZKODZONY' : 'OKŁADKA'}</span>
    <div style="min-width:0"><div class="tytul" title="${esc(f)}">${esc(bezRozsz(f))}</div><div class="opis">${opis}</div>
      <div class="chipy"><span class="chip klik" data-graj="${esc(f)}" title="kliknij, żeby odsłuchać">${esc(f)}</span></div></div>
    <div class="akcje">${akcje}</div></div>`;
}

function pzWidoczne(){
  const h = zdrowie.dane;
  const usz = h ? (h.corrupt || []).filter(f => !pz.pominiete.has('c:' + f) && !pz.zrobione['c:' + f]) : [];
  const okl = h ? (h.missing_covers || []).filter(f => !pz.pominiete.has('o:' + f) && !pz.zrobione['o:' + f]) : [];
  return {usz, okl};
}

function pzRysuj(host){
  const czeka = pz.decyzje.filter(d => d.stan === 'czeka');
  const dup = czeka.filter(d => d.rodzaj === 'duplikat'), pod = czeka.filter(d => d.rodzaj === 'podmiana');
  const mbDup = dup.reduce((s, d) => s + ((d.dowody || {}).usun || []).reduce((a, o) => a + (o.mb || 0), 0), 0);
  const h = zdrowie.dane;
  const {usz, okl} = pzWidoczne();
  const n = czeka.length + usz.length + okl.length;

  $('#pzSub', host).textContent = `${n} ${odmiana(n, ['decyzja czeka', 'decyzje czekają', 'decyzji czeka'])} · nic nie zniknie bez Twojej zgody — zatwierdzone trafiają do kosza i da się je cofnąć`;

  // etykieta ulepszeń: z realnych formatów („MP3 → FLAC”), a bez propozycji — jak w projekcie
  const formaty = pod.map(d => { const w = d.dowody || {}; return {z: (w.zostaw || {}).format, u: [...new Set((w.usun || []).map(o => o.format))].join('/')}; });
  const etykPod = formaty.length && formaty.every(f => f.z === formaty[0].z && f.u === formaty[0].u)
    ? `${odmiana(pod.length, ['ULEPSZENIE', 'ULEPSZENIA', 'ULEPSZEŃ'])} ${esc(formaty[0].u)} → ${esc(formaty[0].z)}`
    : (formaty.length ? `${odmiana(pod.length, ['ULEPSZENIE', 'ULEPSZENIA', 'ULEPSZEŃ'])} → LOSSLESS` : 'ULEPSZENIA MP3 → FLAC');
  const meta = S.stan.tracksMeta || {};
  $('#pzKafle', host).innerHTML =
    kafel(h ? fmtLicz(h.files) : (meta.count ? fmtLicz(meta.count) : '<span class="dim2">…</span>'), 'UTWORÓW') +
    kafel(dup.length, `DUPLIKATY${mbDup ? ` · ${Math.round(mbDup)} MB` : ''}`, dup.length ? 'warn' : '') +
    kafel(h ? usz.length : '<span class="dim2">…</span>', odmiana(usz.length, ['USZKODZONY', 'USZKODZONE', 'USZKODZONYCH']), usz.length ? 'bad' : '') +
    kafel(pod.length, etykPod, pod.length ? 'ok' : '');

  let karty;
  if(pz.filtr === 'czeka'){
    karty = [...czeka.map(kartaDecyzji), ...usz.map(f => kartaZdrowia('uszkodzony', f)), ...okl.map(f => kartaZdrowia('okladka', f)),
             ...Object.keys(pz.zrobione).map(k => kartaZdrowia(k[0] === 'c' ? 'uszkodzony' : 'okladka', k.slice(2)))];
  } else {
    const kolej = {czeka: 0, zatwierdzona: 1, odrzucona: 2};
    karty = [...pz.decyzje].sort((a, b) => ((kolej[a.stan] ?? 3) - (kolej[b.stan] ?? 3)) || ((b.kiedy || 0) - (a.kiedy || 0))).map(kartaDecyzji);
  }
  const pusto = pz.filtr === 'czeka'
    ? (h ? 'Nic do rozpatrzenia — biblioteka jest uporządkowana. „Skanuj ponownie” poszuka kopii i ulepszeń, „Sprawdź pobrania” porówna świeże pobrania z próbkami z iTunes.'
         : '<span class="spin"></span> sprawdzam bibliotekę…')
    : 'Historia jest pusta — jeszcze nic nie zatwierdzono ani nie odrzucono.';
  $('#pzLista', host).innerHTML = karty.length ? karty.join('') : `<div class="pusto">${pusto}</div>`;
  podswietlGrane();

  if(S.biezacy() === 'porzadki'){
    const ostatni = Math.max(0, ...pz.decyzje.map(d => d.kiedy || 0)) * 1000;
    S.tytul([S.stan.folder ? skrocFolder(S.stan.folder) : 'porządki',
             ostatni ? `ostatni skan ${ileTemu(ostatni)}` : 'jeszcze nie skanowano'].join(' · '));
  }
}

async function pzOdswiez(host){
  const d = await api('/api/decyzje' + (pz.filtr === 'wszystkie' ? '?wszystkie=1' : ''));
  pz.decyzje = d.decyzje || [];
  pzRysuj(host);
}
async function pzZdrowie(host, force = false){
  const d = await zdrowie.pobierz(force);
  // pominięte karty żyją tak długo, jak problem — gdy zniknie, zapomnij o nich
  const obecne = new Set([...(d.corrupt || []).map(f => 'c:' + f), ...(d.missing_covers || []).map(f => 'o:' + f)]);
  pz.pominiete = new Set([...pz.pominiete].filter(k => obecne.has(k)));
  pref.set('porzadki.pominiete', [...pz.pominiete]);
  pzRysuj(host);
}
async function pzAkcja(host, id, akcja, btn){
  await zajety(btn, '…', async () => {
    const r = await api(`/api/decyzje/${encodeURIComponent(id)}/${akcja}`, {method: 'POST'});
    const msg = {zatwierdz: `zatwierdzone — ${r.w_koszu || 0} w koszu, da się cofnąć w Historii`,
                 odrzuc: 'zostawione bez zmian — nie zapytam o to ponownie',
                 cofnij: (r.decyzja && (r.decyzja.nie_wrocily || []).length)
                   ? `cofnięte, ale ${r.decyzja.nie_wrocily.length} plików nie dało się przywrócić — sprawdź kosz`
                   : 'cofnięte — decyzja czeka od nowa (pliki z kosza wróciły na swoje miejsca)'}[akcja];
    toast(msg, akcja === 'zatwierdz' ? 'ok' : 'info');
    S.uniewaznTracks(); zdrowie.kiedy = 0;
    await pzOdswiez(host);
    S.pollLiczniki();
  });
}

S.ekran('porzadki', {
  tytul: 'Porządki',
  render(host){
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Porządki</h1><div class="sub" id="pzSub">…</div></div>
        <div class="akcje" style="gap:16px">
          <button class="btn" id="pzSprawdz" title="porównuje świeże pobrania z Soulseeka z 30-sekundowymi próbkami z iTunes — czy to na pewno zamówiony utwór">Sprawdź pobrania (odcisk akustyczny)</button>
          <button class="btn" id="pzSkanuj" title="szuka kopii tego samego utworu i lepszych wersji — nic nie zmienia na dysku">Skanuj ponownie</button>
        </div>
      </div>
      <div class="kafle c4" id="pzKafle"></div>
      <div style="display:flex;align-items:center;gap:12px;flex-shrink:0">
        <div class="seg" id="pzSeg"><button data-f="czeka" class="on">Czekają</button><button data-f="wszystkie">Historia</button></div>
        <span class="dim2" style="font-size:12.5px">w Historii są zatwierdzone (z przyciskiem „Cofnij”) i pominięte</span>
      </div>
      <div class="pz-lista" id="pzLista"><div class="pusto"><span class="spin"></span> czytam kolejkę decyzji…</div></div>`;

    on(host, 'click', '#pzSeg button', (e, el) => {
      pz.filtr = el.dataset.f;
      $$('#pzSeg button', host).forEach(b => b.classList.toggle('on', b === el));
      bezpiecznie(() => pzOdswiez(host));
    });
    on(host, 'click', '#pzSkanuj', (e, el) => bezpiecznie(() => zajety(el, 'przeglądam bibliotekę…', async () => {
      const d = await api('/api/decyzje/skanuj', {method: 'POST'});
      toast(d.nowych ? `znalazłem ${d.nowych} ${odmiana(d.nowych, ['nową propozycję', 'nowe propozycje', 'nowych propozycji'])} — nic jeszcze nie ruszyłem`
                     : (d.czeka ? `nic nowego · ${d.czeka} czeka na decyzję` : 'nie znalazłem kopii ani ulepszeń'), d.nowych ? 'ok' : 'info');
      await pzOdswiez(host); S.pollLiczniki();
      bezpiecznie(() => pzZdrowie(host, true));
    })));
    on(host, 'click', '#pzSprawdz', (e, el) => bezpiecznie(() => zajety(el, 'porównuję dźwięk z próbkami z iTunes…', async () => {
      const d = await api('/api/pobrania/sprawdz', {method: 'POST'});
      toast(d.podejrzanych ? `${d.podejrzanych} ${odmiana(d.podejrzanych, ['pobranie budzi', 'pobrania budzą', 'pobrań budzi'])} wątpliwości — obejrzyj dowody poniżej`
                           : `sprawdzono ${d.sprawdzonych} ${odmiana(d.sprawdzonych, ['pobranie', 'pobrania', 'pobrań'])}, wszystko się zgadza`, d.podejrzanych ? 'warn' : 'ok');
      await pzOdswiez(host); S.pollLiczniki();
    })));
    on(host, 'click', '.chip.klik[data-graj]', (e, el) => grajPlik(el.dataset.graj));
    on(host, 'click', '[data-akcja]', (e, el) => bezpiecznie(async () => {
      const a = el.dataset.akcja;
      if(a === 'graj') return grajPlik(el.dataset.plik);
      if(a === 'pomin'){
        pz.pominiete.add(el.dataset.klucz); pref.set('porzadki.pominiete', [...pz.pominiete]);
        toast('schowane — wróci, jeśli problem zniknie i pojawi się znowu', 'info', 2500);
        return pzRysuj(host);
      }
      if(a === 'pobierz') return zajety(el, '…', async () => {
        const r = await api('/api/redownload', {method: 'POST', body: {file: el.dataset.plik}});
        pz.zrobione[el.dataset.klucz] = `na liście życzeń jako „${r.queued}” — apka poszuka go w Soulseeku`;
        toast('dodane do listy życzeń', 'ok'); pzRysuj(host);
      });
      if(a === 'okladka') return zajety(el, 'szukam w iTunes…', async () => {
        const r = await api('/api/covers/fill?file=' + encodeURIComponent(el.dataset.plik), {method: 'POST'});
        pz.zrobione[el.dataset.klucz] = `okładka dociągnięta: ${r.desc || ''}`;
        toast('okładka zapisana w tagach', 'ok'); zdrowie.kiedy = 0; pzRysuj(host);
      });
      if(a === 'zatwierdz' || a === 'odrzuc' || a === 'cofnij') return pzAkcja(host, el.dataset.id, a, el);
    }));
  },
  load(host){
    bezpiecznie(() => pzOdswiez(host));
    bezpiecznie(() => pzZdrowie(host));
  },
});

/* ============================================================
   ZDROWIE — bez artboardu; kafle jak w 3b, panele jak w 5b/6a
   ============================================================ */
const zd = {dedupe: null, tagfix: null, zyczenia: new Set()};

function zdRysuj(host){
  const h = zdrowie.dane; if(!h) return;
  const corrupt = h.corrupt || [], dups = h.duplicates || [], covers = h.missing_covers || [];
  const hits = zd.tagfix ? (zd.tagfix.hits || []) : null;
  const plikiTagow = hits ? [...new Set(hits.map(x => x.file))] : null;
  const akcje = zd.dedupe ? (zd.dedupe.actions || []) : null;
  const mbDup = akcje ? akcje.reduce((s, a) => s + (a.reclaim_mb || 0), 0) : 0;
  const kopii = akcje ? akcje.reduce((s, a) => s + (a.remove || []).length, 0) : dups.reduce((s, g) => s + Math.max(0, (g.n || 1) - 1), 0);

  const kopieSetow = h.kopii_w_setach ? ` (+ ${fmtLicz(h.kopii_w_setach)} ${odmiana(h.kopii_w_setach, ['kopia', 'kopie', 'kopii'])} w folderach setów — nietykalne)` : '';
  $('#zdSub', host).textContent = `${h.problems} ${odmiana(h.problems, ['sprawa', 'sprawy', 'spraw'])} do uwagi w ${fmtLicz(h.files)} ${odmiana(h.files, ['utworze', 'utworach', 'utworach'])}${kopieSetow} · integralność, kopie, tagi, okładki · naprawy idą do kosza albo w tagi — nic nie znika na zawsze`;
  $('#zdKafle', host).innerHTML =
    kafel(corrupt.length, odmiana(corrupt.length, ['USZKODZONY', 'USZKODZONE', 'USZKODZONYCH']), corrupt.length ? 'bad' : '') +
    kafel(dups.length, `${odmiana(dups.length, ['DUPLIKAT', 'DUPLIKATY', 'DUPLIKATÓW'])}${mbDup ? ` · ${Math.round(mbDup)} MB` : ''}`, dups.length ? 'warn' : '') +
    kafel(plikiTagow ? plikiTagow.length : '<span class="dim2">…</span>', 'TAGI DO NAPRAWY', plikiTagow && plikiTagow.length ? 'info' : '') +
    kafel(covers.length, 'BEZ OKŁADKI', covers.length ? 'acc' : '');

  // uszkodzone
  $('#zdUszN', host).textContent = corrupt.length;
  $('#zdUsz', host).innerHTML = corrupt.length ? corrupt.map(f => `
    <div class="zd-wiersz"><div style="min-width:0"><div class="t" title="${esc(f)}">${esc(f)}</div><div class="s" title="${esc(powodUszkodzenia(f))}">${esc(powodUszkodzenia(f))}</div></div>
      ${zd.zyczenia.has(f) ? '<span class="ok" style="font-size:12.5px;white-space:nowrap">✓ na liście życzeń</span>'
                           : `<button class="btn sr" data-akcja="pobierz" data-plik="${esc(f)}" title="dopisze utwór do listy życzeń — plik zostaje na miejscu">Pobierz ponownie</button>`}</div>`).join('')
    : '<div class="zd-pusto">brak — wszystkie pliki czytają się poprawnie</div>';

  // duplikaty
  $('#zdDupN', host).textContent = akcje ? `${dups.length} ${odmiana(dups.length, ['grupa', 'grupy', 'grup'])} · ${kopii} ${odmiana(kopii, ['kopia', 'kopie', 'kopii'])} do kosza · ${Math.round(mbDup)} MB` : `${dups.length} ${odmiana(dups.length, ['grupa', 'grupy', 'grup'])}`;
  // pełne ścieżki (folder/nazwa): kopie w różnych folderach mają tę samą
  // nazwę i „zostaje X / do kosza X” wyglądało identycznie
  const sciezka = f => { const {folder, nazwa} = folderINazwa(f); return folder ? `<span class="dim2">${esc(folder)}/</span>${esc(nazwa)}` : esc(nazwa); };
  $('#zdDup', host).innerHTML = akcje
    ? (akcje.length ? akcje.map(a => `
        <div class="zd-wiersz"><div style="min-width:0"><div class="t" title="zostaje: ${esc(a.keep)}"><span class="ok">zostaje</span> ${sciezka(a.keep)}</div>
          ${(a.remove || []).map((r, i) => `<div class="s" title="do kosza: ${esc(r)}"><span class="warn">do kosza</span> ${sciezka(r)}${(a.remove_desc || [])[i] ? ` · ${esc(a.remove_desc[i])}` : ''}</div>`).join('')}
          <div class="s" title="${esc(a.reason || '')}">${fmtMb(a.reclaim_mb)} · ${esc(a.reason || '')}${(a.sety || []).length ? ` · użyty w setach: ${esc(a.sety.join(', '))} (kopie w setach zostają)` : ''}</div></div>
          <span class="etyk">×${(a.remove || []).length + 1}</span></div>`).join('')
      : `<div class="zd-pusto">${zd.dedupe.blad ? 'nie udało się zaplanować porządków' : (dups.length ? 'kopie są, ale różnią się czasem trwania — to mogą być inne edycje, więc nie planuję ich usuwania' : 'brak kopii')}</div>`)
    : (dups.length ? dups.map(g => `
        <div class="zd-wiersz"><div style="min-width:0"><div class="t" title="${esc(g.keep)}">${esc(g.keep)}</div><div class="s"><span class="spin"></span> planuję, którą kopię zostawić…</div></div><span class="etyk">×${g.n}</span></div>`).join('')
      : '<div class="zd-pusto">brak kopii</div>');
  $('#zdDedupe', host).disabled = !(akcje && akcje.length);

  // tagi
  const bezTagow = h.missing_tags || [];
  $('#zdTagN', host).textContent = plikiTagow ? `${plikiTagow.length} ${odmiana(plikiTagow.length, ['plik', 'pliki', 'plików'])} do naprawy${bezTagow.length ? ` · ${bezTagow.length} bez tagów` : ''}` : '…';
  const wierszeBezTagow = bezTagow.map(x => `
        <div class="zd-wiersz"><div style="min-width:0"><div class="t" title="${esc(x.file)}">${esc(x.file)}</div>
          <div class="s">brak ${esc((x.brak || []).map(b => ({ARTIST: 'artysty', TITLE: 'tytułu'}[b] || b)).join(' i '))} w tagach — uzupełnij w szczegółach utworu albo w rekordboxie</div></div></div>`).join('');
  $('#zdTag', host).innerHTML = hits
    ? ((hits.length || bezTagow.length) ? plikiTagow.map(f => `
        <div class="zd-wiersz"><div style="min-width:0"><div class="t" title="${esc(f)}">${esc(f)}</div>
          <div class="s">${hits.filter(x => x.file === f).map(x => `${esc(x.field)}: ${esc(x.current || '∅')} → <span class="ok">${esc(x.suggested)}</span>`).join(' · ')}</div></div></div>`).join('') + wierszeBezTagow
      : `<div class="zd-pusto">${zd.tagfix.blad ? 'nie udało się sprawdzić tagów' : 'tagi w porządku'}</div>`)
    : '<div class="zd-pusto"><span class="spin"></span> sprawdzam tagi…</div>';
  $('#zdTagfix', host).disabled = !(hits && hits.length);

  // okładki
  $('#zdOklN', host).textContent = covers.length;
  $('#zdOkl', host).innerHTML = covers.length ? covers.map(f => `
    <div class="zd-wiersz" data-plik="${esc(f)}"><div style="min-width:0"><div class="t" title="${esc(f)}">${esc(f)}</div><div class="s">brak okładki w tagach</div></div>
      <button class="btn sr" data-akcja="okladka" data-plik="${esc(f)}" title="szuka w iTunes po artyście i tytule z tagów — tylko przy zgodnym wykonawcy; tagów nie zmienia">Dociągnij</button></div>`).join('')
    : '<div class="zd-pusto">wszystkie mają okładkę</div>';
  $('#zdCovers', host).disabled = !covers.length;

  if(S.biezacy() === 'zdrowie') S.tytul(`zdrowie · ${fmtLicz(h.files)} plików · ${h.problems} ${odmiana(h.problems, ['sprawa', 'sprawy', 'spraw'])}`);
}

async function zdLoad(host, force = false){
  const sub = $('#zdSub', host);
  const napis = () => `<span class="spin"></span> skanuję bibliotekę — pełne sprawdzenie plików${zdrowie.postep ? ` (${zdrowie.postep})` : ''}; wynik zostaje zapamiętany, kolejne skany są szybkie…`;
  const odswiezNapis = () => { if(zdrowie.wTrakcie) sub.innerHTML = napis(); };
  document.addEventListener('selekta:zdrowie-postep', odswiezNapis);
  if(!zdrowie.dane || force) sub.innerHTML = napis();
  try{ await zdrowie.pobierz(force); }
  catch(e){ sub.innerHTML = `<span class="bad">nie udało się sprawdzić zdrowia: ${esc(e.message)}</span>`; return; }
  finally{ document.removeEventListener('selekta:zdrowie-postep', odswiezNapis); }
  zd.dedupe = null; zd.tagfix = null;
  zdRysuj(host);
  wTle('/api/dedupe').then(d => { zd.dedupe = d; }).catch(() => { zd.dedupe = {actions: [], blad: true}; }).finally(() => zdRysuj(host));
  api('/api/tagfix', {cicho: true}).then(d => { zd.tagfix = d; }).catch(() => { zd.tagfix = {hits: [], blad: true}; }).finally(() => zdRysuj(host));
}

// cofnięcie przeniesienia do kosza: każdy plik wraca tam, skąd przyszedł
async function przywrocZKosza(wKoszu){
  let ok = 0;
  for(const w of wKoszu){ try{ await api('/api/tracks/przywroc', {method: 'POST', body: {w_koszu: w}, cicho: true}); ok++; }catch(e){} }
  return ok;
}
function toastCofnij(msg, wKoszu, poCofnieciu){
  const el = toast(msg, 'ok', 15000);
  if(!el || !wKoszu.length) return;
  const b = document.createElement('button'); b.className = 'btn mini obrys'; b.style.marginLeft = '10px'; b.textContent = 'cofnij';
  b.onclick = async () => {
    b.disabled = true;
    const ok = await przywrocZKosza(wKoszu);
    el.remove();
    toast(ok === wKoszu.length ? `przywrócono ${ok}` : `przywrócono ${ok} z ${wKoszu.length} — reszta jest w „Kosz”`, ok ? 'ok' : 'warn');
    if(poCofnieciu) poCofnieciu();
  };
  el.appendChild(b);
}

// kosz: przywracanie także po odświeżeniu strony (wcześniej „Cofnij” żyło do przeładowania)
async function pokazKosz(host){
  const sheet = S.arkusz('<div class="pusto"><span class="spin"></span> czytam kosz…</div>', {szer: 820});
  let d;
  try{ d = await api('/api/kosz'); }catch(e){ sheet.innerHTML = `<div class="pusto bad">✗ ${esc(e.message)}</div>`; return; }
  const pliki = d.pliki || [];
  const rysuj = () => {
    sheet.innerHTML = `<div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;align-items:center;gap:12px"><h2 style="margin:0">Kosz</h2><span class="dim">${pliki.length} ${odmiana(pliki.length, ['plik', 'pliki', 'plików'])} · każdy wraca dokładnie tam, skąd przyszedł</span></div>
      ${pliki.length ? pliki.map((x, i) => `<div class="zd-wiersz"><div style="min-width:0"><div class="t" title="${esc(x.skad)}">${esc(x.skad)}</div><div class="s">${fmtMb(x.mb)} · usunięty ${esc(dataKrotka(x.kiedy * 1000))} ${esc(godzina(x.kiedy * 1000))}</div></div>
        ${x.wrocil ? '<span class="ok">✓ wrócił</span>' : `<button class="btn sr" data-kosz="${i}">Przywróć</button>`}</div>`).join('') : '<div class="zd-pusto">kosz jest pusty</div>'}</div>`;
  };
  rysuj();
  sheet.addEventListener('click', async e => {
    const b = e.target.closest('[data-kosz]'); if(!b) return;
    const x = pliki[Number(b.dataset.kosz)]; b.disabled = true;
    try{ await api('/api/tracks/przywroc', {method: 'POST', body: {w_koszu: x.w_koszu}}); x.wrocil = true; S.uniewaznTracks(); zdrowie.kiedy = 0; }
    catch(err){ b.disabled = false; }
    rysuj();
  });
}

async function zdOkladka(btn, plik){
  return zajety(btn, 'szukam…', async () => {
    const r = await api('/api/covers/fill?file=' + encodeURIComponent(plik), {method: 'POST', cicho: true});
    const w = btn.closest('.zd-wiersz');
    const kopie = r.kopii ? ` · także ${r.kopii} ${odmiana(r.kopii, ['kopia', 'kopie', 'kopii'])} w setach` : '';
    if(w){ w.querySelector('.s').innerHTML = `<span class="ok">✓ ${esc(r.desc || 'okładka zapisana')}${esc(kopie)}</span>`; btn.replaceWith(Object.assign(document.createElement('span'), {className: 'ok', textContent: '✓', style: 'font-size:13px'})); }
    return true;
  }).catch(e => {
    const w = btn.closest('.zd-wiersz');
    if(w) w.querySelector('.s').innerHTML = `<span class="bad">✗ ${esc(e.message)}</span>`;
    return false;
  });
}

S.ekran('zdrowie', {
  tytul: 'Zdrowie',
  render(host){
    const panel = (id, etyk, przycisk) => `
      <div class="zd-panel"><div class="glowa"><span class="etyk">${etyk}</span><span class="n" id="${id}N"></span>${przycisk || ''}</div>
        <div class="lista" id="${id}"><div class="zd-pusto"><span class="spin"></span></div></div></div>`;
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Zdrowie</h1><div class="sub" id="zdSub">…</div></div>
        <div class="akcje" style="gap:16px"><button class="btn" id="zdKosz" title="pliki przeniesione do kosza — przywróć, jeśli trzeba">Kosz</button><button class="btn" id="zdSkanuj" title="pełne sprawdzenie plików od nowa">Skanuj ponownie</button></div>
      </div>
      <div class="kafle c4" id="zdKafle"></div>
      <div class="zd-siatka">
        ${panel('zdUsz', 'USZKODZONE PLIKI')}
        ${panel('zdDup', 'DUPLIKATY', '<button class="btn sr" id="zdDedupe" title="zostawia najlepszą kopię z każdej grupy, resztę przenosi do kosza w bibliotece" disabled>Usuń duplikaty (do kosza)</button>')}
        ${panel('zdTag', 'TAGI', '<button class="btn sr" id="zdTagfix" title="zapisuje poprawione tagi we wszystkich plikach z listy" disabled>Napraw wszystkie tagi</button>')}
        ${panel('zdOkl', 'OKŁADKI', '<button class="btn sr" id="zdCovers" title="po kolei szuka okładek w iTunes i zapisuje je w tagach" disabled>Dociągnij okładki</button>')}
      </div>`;

    on(host, 'click', '#zdSkanuj', (e, el) => bezpiecznie(() => zajety(el, 'skanuję…', () => zdLoad(host, true))));
    on(host, 'click', '#zdKosz', () => bezpiecznie(() => pokazKosz(host)));
    on(host, 'click', '#zdDedupe', (e, el) => {
      const akcje = (zd.dedupe && zd.dedupe.actions) || [];
      const doKosza = akcje.flatMap(a => a.remove || []);
      const n = doKosza.length;
      potwierdz(el, `Na pewno? ${n} ${odmiana(n, ['kopia', 'kopie', 'kopii'])} → kosz`, () => bezpiecznie(() => zajety(el, 'przenoszę do kosza…', async () => {
        // wykonujemy DOKŁADNIE to, co jest na ekranie — nie plan liczony od nowa
        const r = await api('/api/dedupe/apply', {method: 'POST', body: {remove: doKosza}});
        const wKoszu = (r.przeniesione || []).map(x => x.w_koszu);
        toastCofnij(`przeniesiono ${r.moved} do kosza · odzyskano ${pl(r.reclaimed_mb)} MB`, wKoszu,
                    () => { S.uniewaznTracks(); S.pollLiczniki(); zdLoad(host, true); });
        S.uniewaznTracks(); S.pollLiczniki();
        await zdLoad(host, true);
      })));
    });
    on(host, 'click', '#zdTagfix', (e, el) => {
      const n = zd.tagfix ? new Set((zd.tagfix.hits || []).map(x => x.file)).size : 0;
      potwierdz(el, `Na pewno? Zapisz tagi w ${n} ${odmiana(n, ['pliku', 'plikach', 'plikach'])}`, () => bezpiecznie(() => zajety(el, 'naprawiam…', async () => {
        const r = await api('/api/tagfix/apply', {method: 'POST'});
        toast(`naprawiono tagi w ${r.fixed} ${odmiana(r.fixed, ['pliku', 'plikach', 'plikach'])}`, 'ok');
        S.uniewaznTracks();
        zd.tagfix = null; zdRysuj(host);
        api('/api/tagfix', {cicho: true}).then(d => { zd.tagfix = d; }).catch(() => { zd.tagfix = {hits: [], blad: true}; }).finally(() => zdRysuj(host));
      })));
    });
    on(host, 'click', '#zdCovers', (e, el) => bezpiecznie(() => zajety(el, 'dociągam po kolei…', async () => {
      const przyciski = $$('#zdOkl [data-akcja="okladka"]', host);
      let ok = 0;
      for(const b of przyciski){ if(await zdOkladka(b, b.dataset.plik)) ok++; }
      toast(`dociągnięto ${ok} z ${przyciski.length} okładek`, ok ? 'ok' : 'warn');
      zdrowie.kiedy = 0; S.uniewaznTracks();
    })));
    on(host, 'click', '[data-akcja="okladka"]', (e, el) => { zdOkladka(el, el.dataset.plik).then(() => { zdrowie.kiedy = 0; }); });
    on(host, 'click', '[data-akcja="pobierz"]', (e, el) => bezpiecznie(() => zajety(el, '…', async () => {
      const r = await api('/api/redownload', {method: 'POST', body: {file: el.dataset.plik}});
      zd.zyczenia.add(el.dataset.plik);
      toast(`„${r.queued}” na liście życzeń — apka poszuka go w Soulseeku`, 'ok');
      zdRysuj(host);
    })));
  },
  load(host){ bezpiecznie(() => zdLoad(host)); },
});

/* ============================================================
   SPRAWDŹ UCHEM — bez artboardu; wiersze jak w 3a/2c
   ============================================================ */
const uch = {dane: null, filtr: 0, mapa: new Map()};
const UCH_ZNAK = {3: '‼', 2: '!', 1: '·'}, UCH_KL = {3: 'bad', 2: 'warn', 1: 'dim'};

function uchWiersz(u){
  const w = u.waga || 1, tytul = u.title || bezRozsz(nazwaPliku(u.file));
  const cam = u.camelot && CAM[u.camelot] ? `style="background:${CAM[u.camelot]}"` : 'style="background:var(--panel2);color:var(--dim2)"';
  return `<div class="uch-wiersz w${w}" data-file="${esc(u.file)}">
    <span class="znak ${UCH_KL[w]}">${UCH_ZNAK[w]}</span>
    <img class="okladka" src="/api/cover?file=${encodeURIComponent(u.file)}" alt="" loading="lazy">
    <div style="min-width:0"><div class="t" title="${esc(u.file)}">${esc(tytul)}<span>${esc(u.artist || '')}${u.kopii > 1 ? ` · ${u.kopii} identyczne kopie w bibliotece` : ''}</span></div>
      <ul class="powody">${(u.powody || []).map(p => `<li class="${UCH_KL[p.waga] || 'dim'}">– ${esc(p.opis)}</li>`).join('')}</ul></div>
    <span class="bpm">${u.bpm ? pl(u.bpm) : '—'}</span>
    <span class="cam" ${cam}>${esc(u.camelot || '—')}</span>
    <button class="graj" data-graj="${esc(u.file)}" title="odsłuchaj">▶</button>
    <button class="btn sr" data-szczegoly title="analiza, pewność, siatka beatów">Szczegóły i siatka</button></div>`;
}

function uchRysuj(host){
  const d = uch.dane; if(!d) return;
  const u = d.utwory || [];
  const n3 = u.filter(x => x.waga === 3).length, n2 = u.filter(x => x.waga === 2).length, n1 = u.filter(x => x.waga === 1).length;
  uch.mapa = new Map(u.map(x => [x.file, x]));

  const bezTempa = d.bez_sprawdzenia_tempa || 0;
  $('#uchSub', host).textContent = (u.length
    ? `${u.length} ${odmiana(u.length, ['utwór', 'utwory', 'utworów'])} do sprawdzenia · najpilniejsze na górze · apka podaje tempo i tonację, ale nie zawsze jest ich pewna — posłuchaj, zanim trafią do setu`
    : `Nic do sprawdzania — ${d.sprawdzonych} ${odmiana(d.sprawdzonych, ['utwór', 'utwory', 'utworów'])} z pewnymi wynikami${d.bez_analizy ? ` · ${d.bez_analizy} jeszcze bez analizy (uruchom „Analizuj” w Bibliotece)` : ''}`)
    + (bezTempa ? ` · ${bezTempa} bez sprawdzenia stabilności tempa — zmienne tempo wyjdzie dopiero po „Sprawdź tempo”` : '');
  const bt = $('#uchTempo', host);
  if(bt){ bt.hidden = !bezTempa; if(!bt.disabled) bt.textContent = `Sprawdź tempo (${bezTempa})`; }
  $('#uchKafle', host).innerHTML =
    kafel(n3, 'NIE GRAJ BEZ SPRAWDZENIA', n3 ? 'bad' : '') +
    kafel(n2, 'SPRAWDŹ PRZY OKAZJI', n2 ? 'warn' : '') +
    kafel(n1, 'DROBIAZGI', '') +
    kafel(d.bez_analizy || 0, 'BEZ ANALIZY', d.bez_analizy ? 'info' : '');
  const liczby = {0: u.length, 3: n3, 2: n2, 1: n1};
  $$('#uchSeg button', host).forEach(b => { b.querySelector('span').textContent = liczby[b.dataset.w]; b.classList.toggle('on', Number(b.dataset.w) === uch.filtr); });

  const widoczne = uch.filtr ? u.filter(x => x.waga === uch.filtr) : u;
  $('#uchLista', host).innerHTML = widoczne.length
    ? `<div class="uch-naglowek etyk"><span></span><span></span><span>UTWÓR · DLACZEGO SPRAWDZIĆ</span><span style="text-align:right">BPM</span><span>KLUCZ</span><span></span><span></span></div>` + widoczne.map(uchWiersz).join('')
    : `<div class="pusto">${u.length ? 'nic w tej grupie — przełącz na „Wszystkie”' : `nic do sprawdzania${d.bez_analizy ? ` · ${d.bez_analizy} ${odmiana(d.bez_analizy, ['utwór czeka', 'utwory czekają', 'utworów czeka'])} na analizę` : ''}`}</div>`;
  podswietlGrane();
  if(S.biezacy() === 'uchem') S.tytul(`sprawdź uchem · ${u.length} do odsłuchu · ${d.sprawdzonych} sprawdzonych${d.bez_analizy ? ` · ${d.bez_analizy} bez analizy` : ''}`);
}

async function uchOdswiez(host){
  if(!uch.dane) $('#uchLista', host).innerHTML = '<div class="pusto"><span class="spin"></span> przeglądam wyniki analiz…</div>';
  uch.dane = await api('/api/uchem');
  uchRysuj(host);
}

// Szczegóły i siatka są w Bibliotece (S.otworzSzczegoly); gdy jej ekran nie
// jest jeszcze wczytany, pokazujemy własny arkusz z tym, co apka wie z /api/track
function otworzSzczegoly(u){
  if(typeof S.otworzSzczegoly === 'function'){
    // Biblioteka zna utwory po nazwie pliku; ścieżkę bezwzględną dajemy
    // tylko wtedy, gdy ta sama nazwa leży w kilku podfolderach
    const nazwa = nazwaPliku(u.file);
    const kopie = (S.stan.tracks || []).filter(t => t.file === nazwa).length;
    return S.otworzSzczegoly(kopie > 1 ? u.file : nazwa);
  }
  return arkuszUtworu(u);
}
async function arkuszUtworu(u){
  const sheet = S.arkusz('<div class="pusto"><span class="spin"></span> czytam analizę…</div>', {szer: 900});
  let t;
  try{ t = await api('/api/track?file=' + encodeURIComponent(u.file)); }
  catch(e){ sheet.innerHTML = `<div class="pusto bad">✗ ${esc(e.message)}</div>`; return; }
  // własny wrapper zamiast klasy na współdzielonym #arkuszBody — style
  // arkusza nie mogą przeciekać do arkuszy innych ekranów
  sheet.innerHTML = '<div class="uch-arkusz" style="display:flex;flex-direction:column;gap:24px"></div>';
  const body = sheet.firstElementChild;
  const h = t.harmonic || {}, q = t.quality_full || {}, l = t.loudness || {}, integ = t.integrity || {};
  const klJ = {ok: 'ok', warn: 'warn', bad: 'bad'}[q.grade] || 'dim';
  const ext = (t.ext || '').toLowerCase();
  const cam = h.camelot && CAM[h.camelot] ? `background:${CAM[h.camelot]};color:#0f0d0c` : 'background:var(--panel2);color:var(--dim2)';
  body.innerHTML = `
    <div style="display:flex;align-items:flex-start;gap:22px">
      <img class="okladka" style="width:96px;height:96px;border-radius:12px" src="/api/cover?file=${encodeURIComponent(u.file)}" alt="">
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:6px">
        <div style="display:flex;align-items:center;gap:10px"><span class="fmt ${esc(ext)}">${esc(ext.toUpperCase())}</span>
          <span class="mono" style="font-size:11.5px;color:var(--dim)">${t.sr ? pl(t.sr / 1000) + ' kHz' : ''}${t.bits ? ` · ${t.bits}-bit` : ''} · ${fmtMb(t.size_mb)} · ${fmtTime(t.duration)}</span></div>
        <div style="font-size:32px;font-weight:700;letter-spacing:-.02em;line-height:1.05">${esc(t.title || u.title || '')}</div>
        <div style="font-size:16px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.artist || '')} · ${esc(t.file || nazwaPliku(u.file))}</div>
      </div>
      <div style="display:flex;gap:8px"><button class="graj-duzy" data-graj="${esc(u.file)}" title="odsłuchaj">▶</button><button class="zamknij" title="zamknij (Esc)">✕</button></div>
    </div>
    <div class="kafle c4">
      <div class="kafel"><div class="etyk">TEMPO</div><div class="liczba">${h.bpm ? Math.round(h.bpm) : '—'}<small>BPM</small></div>
        <div class="pod">pewność ${pl(h.confidence_bpm, 2)}${h.confidence_bpm != null && h.confidence_bpm < 0.25 ? ` · <span class="bad">możliwe ${Math.round(h.bpm / 2)} albo ${Math.round(h.bpm * 2)}</span>` : ''}</div></div>
      <div class="kafel"><div class="etyk">TONACJA</div><div style="display:flex;align-items:center;gap:10px;margin-top:10px"><span class="mono" style="font-weight:700;font-size:14px;padding:5px 10px;border-radius:6px;${cam}">${esc(h.camelot || '—')}</span><span style="font-size:20px;font-weight:600">${esc(h.key || '—')}</span></div>
        <div class="pod">pewność ${pl(h.confidence_key, 2)}${h.confidence_key != null && h.confidence_key < 0.4 ? ' · <span class="warn">sąsiednia na kole równie prawdopodobna</span>' : ''}</div></div>
      <div class="kafel"><div class="etyk">GŁOŚNOŚĆ</div><div class="liczba">${pl(l.integrated_lufs)}<small>LUFS</small></div>
        <div class="pod">peak ${pl(l.true_peak_dbtp)} dBTP · RG ${pl(l.gain_db)} dB</div></div>
      <div class="kafel" style="border-color:var(--${klJ === 'dim' ? 'line' : klJ})"><div class="etyk">JAKOŚĆ</div><div class="${klJ}" style="font-size:16px;font-weight:700;margin-top:12px;line-height:1.3">${esc(q.verdict || 'bez oceny')}</div>
        <div class="pod">${q.cutoff_hz ? `pasmo do ${pl(q.cutoff_hz / 1000)} kHz · ` : ''}integralność ${integ.ok ? 'OK' : `<span class="bad">✗ ${esc(integ.detail || '')}</span>`}</div></div>
    </div>
    <div><div class="etyk" style="margin-bottom:10px">DLACZEGO SPRAWDZIĆ UCHEM</div>
      ${(u.powody || []).map(p => `<div style="display:flex;gap:12px;align-items:flex-start;font-size:13px;line-height:1.45;padding:4px 0"><span class="dot ${UCH_KL[p.waga] === 'dim' ? '' : UCH_KL[p.waga]}" style="margin-top:6px"></span><span>${esc(p.opis)}</span></div>`).join('')}</div>
    <div class="dim" style="font-size:12.5px;border-top:1px solid var(--line);padding-top:16px">Siatka beatów, cue i przeliczenie analizy są w Bibliotece → szczegóły utworu.</div>`;
  body.querySelector('.zamknij').onclick = S.zamknijArkusz;
  body.querySelector('.graj-duzy').onclick = () => grajPlik(u.file, {title: t.title, artist: t.artist, bpm: h.bpm, camelot: h.camelot});
  body.addEventListener('error', e => { if(e.target.tagName === 'IMG') e.target.replaceWith(Object.assign(document.createElement('span'), {className: 'okladka', style: 'width:96px;height:96px;border-radius:12px;display:block'})); }, true);
}

S.ekran('uchem', {
  tytul: 'Sprawdź uchem',
  render(host){
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Sprawdź uchem</h1><div class="sub" id="uchSub">…</div></div>
        <div class="akcje" style="gap:16px">
          <div class="seg" id="uchSeg"><button data-w="0" class="on">Wszystkie <span class="dim"></span></button><button data-w="3" title="nie graj bez sprawdzenia">‼ <span class="dim"></span></button><button data-w="2" title="sprawdź przy okazji">! <span class="dim"></span></button><button data-w="1" title="drobiazgi">· <span class="dim"></span></button></div>
          <button class="btn" id="uchTempo" hidden title="sprawdza, czy tempo trzyma się przez cały utwór — po kolei, utwór po utworze">Sprawdź tempo</button>
          <button class="btn" id="uchOdswiez" title="czyta wyłącznie pamięć podręczną analiz — niczego nie liczy">Odśwież</button>
        </div>
      </div>
      <div class="kafle c4" id="uchKafle"></div>
      <div class="panel lista" id="uchLista"></div>`;
    on(host, 'click', '#uchSeg button', (e, el) => { uch.filtr = Number(el.dataset.w); uchRysuj(host); });
    on(host, 'click', '#uchOdswiez', (e, el) => bezpiecznie(() => zajety(el, '…', () => uchOdswiez(host))));
    on(host, 'click', '#uchTempo', (e, el) => bezpiecznie(async () => {
      // stabilność tempa liczy się osobno — po jednym utworze, żeby nie
      // trzymać jednego długiego zapytania (i żeby było widać postęp)
      const d = await api('/api/uchem/bez-tempa');
      const pliki = d.pliki || [];
      el.disabled = true;
      let ok = 0;
      try{
        for(let i = 0; i < pliki.length; i++){
          el.innerHTML = `<span class="spin"></span> tempo ${i + 1}/${pliki.length}`;
          try{ await api('/api/tempo', {method: 'POST', body: {file: pliki[i]}, cicho: true}); ok++; }catch(err){}
        }
      } finally { el.disabled = false; }
      toast(`sprawdzono tempo w ${ok} ${odmiana(ok, ['utworze', 'utworach', 'utworach'])}`, 'ok');
      await uchOdswiez(host);
    }));
    on(host, 'click', '.uch-wiersz .graj', (e, el) => { const u = uch.mapa.get(el.dataset.graj) || {}; grajPlik(el.dataset.graj, {title: u.title, artist: u.artist, bpm: u.bpm, camelot: u.camelot}); });
    on(host, 'click', '[data-szczegoly]', (e, el) => { const u = uch.mapa.get(el.closest('.uch-wiersz').dataset.file); if(u) otworzSzczegoly(u); });
    // brak okładki w tagach = 404 → zamiast pustego obrazka pokaż wzorek z projektu
    host.addEventListener('error', e => {
      const el = e.target;
      if(el.tagName === 'IMG' && el.classList.contains('okladka')) el.replaceWith(Object.assign(document.createElement('span'), {className: 'okladka', style: 'width:40px;height:40px;display:block'}));
    }, true);
  },
  load(host){ bezpiecznie(() => uchOdswiez(host)); },
});

/* ============================================================
   RADAR (5a)
   GET /api/radar oddaje zapamiętane znaleziska (bez sieci), a
   POST /api/radar/sprawdz pyta Beatport i Bandcamp o porcję artystów
   i dopisuje nowości do pamięci serwera.
   ============================================================ */
const rd = {
  okres: pref.get('radar.okres', 30),
  pamiec: {ostatnio: null, nowe: 0, pozycje: [], sprawdzono: null, artystow: null},
  zyczenia: null,
  poszukiwacz: null,      // stan szukania listy życzeń w tle (/api/wishlist)
};
const kluczUtworu = (a, t) => `${String(a || '').trim().toLowerCase()}|${String(t || '').trim().toLowerCase()}`;
const SKLEP = {beatport: 'Beatport', bandcamp: 'Bandcamp'};
const dataPozycji = it => (it.date && !isNaN(Date.parse(it.date))) ? Date.parse(it.date) : (it.znalezione || 0);

function rdKarta(it, nowe, naLiscie){
  const sklep = SKLEP[it.store || it.source] || (it.store || it.source || 'sklep');
  const okladka = it.cover || it.image || it.artwork || '';
  const data = it.date ? dataKrotka(it.date) : (it.znalezione ? `znalezione ${dataKrotka(it.znalezione)}` : '');
  const jest = naLiscie.has(kluczUtworu(it.artist, it.title));
  return `<div class="rd-karta">
    <div class="rd-okladka">${okladka ? `<img src="${esc(okladka)}" alt="" loading="lazy">` : '<span class="podpis">okładka wydania</span>'}<span class="kropka ${nowe ? 'nowe' : ''}" title="${nowe ? 'nowe od ostatniego sprawdzenia' : 'widziane wcześniej'}"></span></div>
    <div><div class="rd-tytul">${esc(it.title || '(bez tytułu)')}</div><div class="rd-kto">${esc(it.artist || '')}${it.label ? ` · ${esc(it.label)}` : ''}</div></div>
    <div class="rd-stopka"><span class="data">${esc(data)}</span>
      ${it.url ? `<a class="rd-btn sklep" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(sklep)} ↗</a>` : `<span class="rd-btn sklep" style="opacity:.5">${esc(sklep)}</span>`}
      ${jest ? '<span class="rd-btn jest" title="już na liście życzeń">✓ na liście</span>'
             : `<button class="rd-btn cichy" data-wish data-artist="${esc(it.artist || '')}" data-title="${esc(it.title || '')}" title="apka będzie szukać tego wydania w Soulseeku">+ Lista życzeń</button>`}
    </div></div>`;
}

function rdRysuj(host){
  const p = rd.pamiec, teraz = Date.now();
  const wszystkie = p.pozycje || [];
  const poz = wszystkie.filter(it => !rd.okres || (teraz - dataPozycji(it)) <= rd.okres * 864e5);
  const zycz = rd.zyczenia || [];
  const naLiscie = new Set(zycz.map(z => kluczUtworu(z.artist, z.title)));

  $$('#rdSeg button', host).forEach(b => b.classList.toggle('on', Number(b.dataset.d) === rd.okres));
  $('#rdSub', host).innerHTML = `Beatport i Bandcamp · <b style="color:var(--txt)">${p.nowe || 0} ${odmiana(p.nowe || 0, ['nowe', 'nowe', 'nowych'])}</b> od ostatniego sprawdzenia` +
    (p.ostatnio ? ` · sprawdzono ${dzisiaj(p.ostatnio) ? 'dziś ' + godzina(p.ostatnio) : dataKrotka(p.ostatnio)}, ${p.sprawdzono ?? '?'} z ${p.artystow ?? '?'} artystów` +
        (p.artystow > p.sprawdzono ? ` · <a href="#" data-wszyscy title="wszyscy artyści z biblioteki — może potrwać kilka minut">sprawdź wszystkich</a>` : '')
      : ' · jeszcze nie sprawdzano');

  const karty = poz.map(it => rdKarta(it, !!p.ostatnio && it.znalezione === p.ostatnio, naLiscie));
  const pusto = !wszystkie.length
    ? `<div class="rd-pusto">Jeszcze nic tu nie ma. „Sprawdź teraz” odpyta Beatport i Bandcamp o nowe wydania artystów z Twojej biblioteki — pierwsze sprawdzenie zapamiętuje, co już jest, kolejne pokazują tylko nowości.<br><span class="dim2">Sprawdzenie chwilę trwa: apka czyta strony sklepu, artysta po artyście.</span></div>`
    : (!poz.length ? `<div class="rd-pusto">Nic z ostatnich ${rd.okres} dni — przełącz na „Wszystko”, żeby zobaczyć ${wszystkie.length} ${odmiana(wszystkie.length, ['zapamiętane wydanie', 'zapamiętane wydania', 'zapamiętanych wydań'])}.</div>` : '');

  // stan pozycji z poszukiwania w tle: pewny plik apka pobiera sama, niepewny pokazuje do potwierdzenia
  const zyczTag = z => {
    if(z.found) return `<span class="tag ok" title="${esc(z.opis || `znaleziono ${dataKrotka(z.found_at)} u ${(z.found_hit || {}).username || ''}`)}">${z.stan === 'zlecone' ? 'pobieram' : 'jest'}</span>`;
    if(z.stan === 'do-potwierdzenia') return `<button class="rd-btn" data-zpobierz="${esc(z.id)}" title="${esc(z.opis || '')}">Pobierz?</button>`;
    const kiedy = z.szukano_at ? `sprawdzone ${dataKrotka(z.szukano_at)} ${godzina(Date.parse(z.szukano_at))}` : 'jeszcze nie sprawdzane';
    return `<span class="tag dim" title="${esc((z.opis ? z.opis + ' · ' : '') + kiedy)} — apka szuka w Soulseeku w tle">szukam</span>`;
  };
  const zyczHtml = rd.zyczenia === null ? '<div class="zd-pusto"><span class="spin"></span></div>'
    : (zycz.length ? `<div class="wiersze">${[...zycz].reverse().map(z => `
        <div class="rd-zycz"><span class="t" title="${esc(z.artist)} — ${esc(z.title)}${z.opis ? ' · ' + esc(z.opis) : ''}">${esc(z.artist)} <span>— ${esc(z.title)}</span></span>
          ${zyczTag(z)}
          <span class="data">${dataKrotka(z.added_at)}</span></div>`).join('')}</div>`
      : '<div class="zd-pusto">lista pusta — „+ Lista życzeń” przy wydaniu albo „Pobierz ponownie” przy uszkodzonym pliku dopisują tu utwory</div>');
  const znal = zycz.filter(z => z.found).length;
  const doPotw = zycz.filter(z => !z.found && z.stan === 'do-potwierdzenia').length;
  const ps = rd.poszukiwacz || {};
  const tlo = ps.w_toku ? `szukam teraz: ${esc(ps.w_toku)}`
    : ps.notka ? esc(ps.notka)
    : ps.dziala ? `szukane w Soulseeku w tle${ps.nastepny_za_s != null ? ` · następne sprawdzenie za ${Math.max(1, Math.round(ps.nastepny_za_s / 60))} min` : ''}`
    : 'szukane w Soulseeku w tle, gdy apka działa';

  $('#rdSiatka', host).innerHTML = karty.join('') + pusto + `
    <div class="rd-zyczenia"><div class="glowa"><span class="etyk">LISTA ŻYCZEŃ</span><span class="n">${zycz.length} ${odmiana(zycz.length, ['utwór', 'utwory', 'utworów'])}${znal ? ` · ${znal} ${odmiana(znal, ['znaleziony', 'znalezione', 'znalezionych'])}` : ''}${doPotw ? ` · ${doPotw} do potwierdzenia` : ''} · ${tlo}</span>${zycz.some(z => !z.found) ? '<button class="rd-btn cichy" data-zszukaj style="margin-left:auto" title="sprawdź listę teraz — apka i tak pilnuje tempa, żeby Soulseek nie odciął połączenia">Szukaj teraz</button>' : ''}</div>${zyczHtml}</div>`;

  if(S.biezacy() === 'radar') S.tytul(`radar · ${p.artystow != null ? `${p.artystow} artystów · ` : ''}${p.ostatnio ? `sprawdzono ${dzisiaj(p.ostatnio) ? 'dziś ' + godzina(p.ostatnio) : dataKrotka(p.ostatnio)}` : 'jeszcze nie sprawdzano'}`);
}

// pamięć znalezisk żyje po stronie serwera (~/.selekta/radar-wyniki.json):
// GET /api/radar oddaje ją bez sieci, POST /api/radar/sprawdz pyta sklepy o porcję artystów
function rdZSerwera(d){
  const kiedy = d.checked_at ? Date.parse(d.checked_at) : null;
  const last = d.last || {};
  const pozycje = (d.items || []).map(it => ({...it, klucz: it.id || it.url || kluczUtworu(it.artist, it.title),
                                                znalezione: it.znalezione ? Date.parse(it.znalezione) : (kiedy || 0)}));
  rd.pamiec = {ostatnio: kiedy, nowe: last.new || 0, pozycje, sprawdzono: last.checked ?? null, artystow: d.total_artists ?? null};
}
async function rdSprawdz(host, btn, limit){
  await zajety(btn, limit > 10 ? `pytam Beatport i Bandcamp o ${limit} artystów…` : 'pytam Beatport i Bandcamp…', async () => {
    // „Sprawdź teraz” idzie dalej po liście artystów (serwer pamięta, gdzie
    // skończył); „sprawdź wszystkich” zaczyna od początku
    const d = await api('/api/radar/sprawdz', {method: 'POST', body: limit > 10 ? {limit, offset: 0} : {limit}});
    const nowe = d.new || [];
    rdZSerwera(await api('/api/radar', {cicho: true}));
    toast(nowe.length ? `${nowe.length} ${odmiana(nowe.length, ['nowe wydanie', 'nowe wydania', 'nowych wydań'])} · sprawdzono ${d.checked} z ${d.total_artists} artystów`
                      : `nic nowego u ${d.checked} z ${d.total_artists} sprawdzonych artystów`, nowe.length ? 'ok' : 'info');
    rdRysuj(host);
  });
}

S.ekran('radar', {
  tytul: 'Radar',
  render(host){
    host.innerHTML = `
      <div class="naglowek">
        <div><h1>Radar</h1><div class="sub" id="rdSub">…</div></div>
        <div class="akcje" style="gap:16px">
          <div class="seg" id="rdSeg"><button data-d="30">30 dni</button><button data-d="90">90 dni</button><button data-d="0">Wszystko</button></div>
          <button class="btn" id="rdSprawdz" title="odpytuje Beatport i Bandcamp o pierwszych 10 artystów z biblioteki (alfabetycznie) — chwilę trwa">Sprawdź teraz</button>
        </div>
      </div>
      <div class="rd-siatka" id="rdSiatka"></div>`;
    on(host, 'click', '#rdSeg button', (e, el) => { rd.okres = Number(el.dataset.d); pref.set('radar.okres', rd.okres); rdRysuj(host); });
    on(host, 'click', '#rdSprawdz', (e, el) => bezpiecznie(() => rdSprawdz(host, el, 10)));
    on(host, 'click', '[data-wszyscy]', (e) => { e.preventDefault(); bezpiecznie(() => rdSprawdz(host, $('#rdSprawdz', host), rd.pamiec.artystow || 10)); });
    on(host, 'click', '[data-wish]', (e, el) => bezpiecznie(() => zajety(el, '…', async () => {
      const r = await api('/api/wishlist', {method: 'POST', body: {artist: el.dataset.artist, title: el.dataset.title}});
      rd.zyczenia = r.items || []; rd.poszukiwacz = r.poszukiwacz || rd.poszukiwacz;
      toast(`„${el.dataset.artist} — ${el.dataset.title}” na liście życzeń`, 'ok');
      rdRysuj(host);
    })));
    on(host, 'click', '[data-zpobierz]', (e, el) => bezpiecznie(() => zajety(el, '…', async () => {
      const r = await api('/api/wishlist/pobierz', {method: 'POST', body: {id: el.dataset.zpobierz}});
      rd.zyczenia = r.items || rd.zyczenia;
      toast('pobieranie zlecone — zobaczysz je w Pobieraniach', 'ok');
      rdRysuj(host);
    })));
    on(host, 'click', '[data-zszukaj]', (e, el) => bezpiecznie(() => zajety(el, '…', async () => {
      const r = await api('/api/wishlist/szukaj', {method: 'POST'});
      rd.poszukiwacz = r.poszukiwacz || rd.poszukiwacz;
      toast('sprawdzam listę życzeń — wyniki pojawią się tu za kilka minut', 'info');
      rdRysuj(host);
    })));
  },
  load(host){
    rdRysuj(host);
    api('/api/radar', {cicho: true}).then(d => { rdZSerwera(d); rdRysuj(host); }).catch(() => {});
    api('/api/wishlist', {cicho: true}).then(w => { rd.zyczenia = w.items || []; rd.poszukiwacz = w.poszukiwacz || null; }).catch(() => { rd.zyczenia = []; }).finally(() => rdRysuj(host));
  },
});
})();
