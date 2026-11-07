/* ============================================================
   Ekran „Playlista”: układanie playlisty ręcznie, z odsłuchem.

   Lewa kolumna: biblioteka (szukaj, ▶ odsłuch, + dodaj, dwuklik dodaje).
   Prawa: playlista — przeciąganie, ▶, ✕, przejścia BPM/tonacja, czas.
   Pod spodem: duplikaty — ten sam utwór dwa razy na playliście oraz
   utwory, które mają w bibliotece kilka kopii („Przejrzyj” = wybór wersji
   z S.pokazWersje, „Odrzuć” = nie pokazuj więcej).
   Robocza playlista żyje w localStorage, więc odświeżenie jej nie gubi.
   Zapis = /api/playlist/from-selection (folder playlisty z kopiami-klonami).
   ============================================================ */
(() => {
const {K, CAM, esc, fmtTime, fmtLicz, $, api, toast} = S;
const lm = (n, j, m, w) => n === 1 ? j : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? m : w);
const camNr = c => parseInt(String(c || ''), 10) || 0;
const camOk = (a, b) => {                 // 0 = ta sama/sąsiednia (gra), 1 = ryzyko, null = brak danych
  if(!a || !b) return null;
  const x = camNr(a), y = camNr(b), d = Math.min(Math.abs(x - y), 12 - Math.abs(x - y));
  if(a === b || (d === 1 && a.slice(-1) === b.slice(-1)) || (x === y)) return 0;
  return 1;
};
const norm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/\(.*?\)|\[.*?\]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();

const PL = {
  host: null, lib: [], szukaj: '',
  lista: S.pref.get('playlista_robocza', []),         // [rel]
  nazwa: S.pref.get('playlista_nazwa', ''),
  odrzucone: new Set(S.pref.get('dup_odrzucone', [])),
  grupy: [], przeciagany: null,
};
const zapamietaj = () => { S.pref.set('playlista_robocza', PL.lista); S.pref.set('playlista_nazwa', PL.nazwa); };
const mapa = () => { const m = {}; PL.lib.forEach(t => { m[t.rel] = t; }); return m; };

const STYLE = `
#ekran-playlista{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:18px;height:calc(100vh - 170px);min-height:480px}
#ekran-playlista .kol{display:flex;flex-direction:column;gap:10px;min-height:0}
#ekran-playlista .panel{background:${K.panel};border:1px solid ${K.line};border-radius:14px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
#ekran-playlista .lista{overflow:auto;flex:1;min-height:120px}
#ekran-playlista .w{display:flex;align-items:center;gap:10px;padding:7px 12px;border-bottom:1px solid ${K.line2};font-size:13px}
#ekran-playlista .w:hover{background:${K.hover}}
#ekran-playlista .w .tt{flex:1;min-width:0}
#ekran-playlista .w .tt div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#ekran-playlista .w .tt .a{color:${K.dim};font-size:12px}
#ekran-playlista .w .m{font:500 11.5px var(--mono);color:${K.dim};white-space:nowrap}
#ekran-playlista .ik{background:transparent;border:1px solid ${K.line};border-radius:7px;color:${K.muted};width:28px;height:28px;cursor:pointer;flex-shrink:0;font-size:11px}
#ekran-playlista .ik:hover{color:${K.txt};border-color:${K.line3}}
#ekran-playlista .ik.gra{color:${K.acc};border-color:${K.acc}}
#ekran-playlista .pw{cursor:grab}
#ekran-playlista .pw.nad{box-shadow:inset 0 2px 0 ${K.acc}}
#ekran-playlista .pw.brak{opacity:.5}
#ekran-playlista .nr{font:500 11px var(--mono);color:${K.dim2};width:22px;text-align:right}
#ekran-playlista .przejscie{font:500 10.5px var(--mono);padding:2px 12px 2px 56px;color:${K.dim2}}
#ekran-playlista .szukaj{display:flex;gap:8px}
#ekran-playlista .szukaj input,#ekran-playlista .nazwa{flex:1;min-width:0;background:${K.panel};border:1px solid ${K.line};border-radius:9px;padding:9px 12px;color:${K.txt};font-size:13.5px}
#ekran-playlista .dup{padding:8px 12px;border-bottom:1px solid ${K.line2};display:flex;align-items:center;gap:10px;font-size:12.5px}
@media (max-width:900px){#ekran-playlista{grid-template-columns:1fr}}
`;

function wiersz(t, i, wPlayliscie){
  const gra = S.player.gra(t.rel);
  const meta = [t.bpm ? Math.round(t.bpm) + ' BPM' : '', t.camelot || '', t.duration ? fmtTime(t.duration) : ''].filter(Boolean).join(' · ');
  const kolor = t.camelot && CAM[t.camelot] ? `style="color:${CAM[t.camelot]}"` : '';
  return wPlayliscie
    ? `<div class="w pw${t.brak ? ' brak' : ''}" draggable="true" data-i="${i}">
        <span class="nr">${i + 1}</span>
        <button class="ik${gra ? ' gra' : ''}" data-graj="${esc(t.rel)}" title="odsłuchaj">${gra ? '❚❚' : '▶'}</button>
        <div class="tt"><div>${esc(t.title)}</div><div class="a">${t.brak ? '<span class="bad">brak pliku — wybrano inną wersję albo usunięto</span>' : esc(t.artist)}</div></div>
        <span class="m" ${kolor}>${esc(meta)}</span>
        <button class="ik" data-usun="${i}" title="usuń z playlisty">✕</button></div>`
    : `<div class="w" data-dodaj2="${esc(t.rel)}">
        <button class="ik${gra ? ' gra' : ''}" data-graj="${esc(t.rel)}" title="odsłuchaj">${gra ? '❚❚' : '▶'}</button>
        <div class="tt"><div>${esc(t.title)}</div><div class="a">${esc(t.artist)}</div></div>
        <span class="m" ${kolor}>${esc(meta)}</span>
        <button class="ik" data-dodaj="${esc(t.rel)}" title="dodaj na koniec playlisty">${PL.lista.includes(t.rel) ? '✓' : '+'}</button></div>`;
}

function przejscie(a, b){
  if(!a || !b || a.brak || b.brak) return '';
  const d = (a.bpm && b.bpm) ? b.bpm - a.bpm : null;
  const k = camOk(a.camelot, b.camelot);
  const bpmTxt = d == null ? '' : `${d > 0 ? '+' : ''}${d.toFixed(1).replace('.', ',')} BPM`;
  const bpmKol = d == null ? K.dim2 : (Math.abs(d) <= 3 ? K.ok : Math.abs(d) <= 8 ? K.warn : K.bad);
  const kTxt = k == null ? '' : (k === 0 ? 'tonacja gra' : 'tonacja się gryzie');
  return `<div class="przejscie"><span style="color:${bpmKol}">${bpmTxt}</span>${bpmTxt && kTxt ? ' · ' : ''}<span style="color:${k === 0 ? K.ok : K.warn}">${kTxt}</span></div>`;
}

function rysujLib(){
  const box = $('#plLib', PL.host); if(!box) return;
  const q = norm(PL.szukaj);
  const lista = PL.lib.filter(t => !q || norm(`${t.artist} ${t.title} ${t.rel}`).includes(q));
  box.innerHTML = lista.slice(0, 600).map(t => wiersz(t, 0, false)).join('') +
    (lista.length > 600 ? `<div class="pusto">i ${lista.length - 600} więcej — zawęź wyszukiwanie</div>` : '') +
    (!lista.length ? '<div class="pusto">nic nie pasuje</div>' : '');
  $('#plLibIle', PL.host).textContent = `${fmtLicz(lista.length)} ${lm(lista.length, 'utwór', 'utwory', 'utworów')}`;
}

function rysujPlayliste(){
  const box = $('#plLista', PL.host); if(!box) return;
  const m = mapa();
  const utwory = PL.lista.map(rel => m[rel] || {rel, title: rel.split('/').pop(), artist: '', brak: true});
  box.innerHTML = utwory.length
    ? utwory.map((t, i) => (i ? przejscie(utwory[i - 1], t) : '') + wiersz(t, i, true)).join('')
    : '<div class="pusto">pusta — dodaj utwory z lewej (+ albo dwuklik), potem przeciągaj, żeby ułożyć kolejność</div>';
  const czas = utwory.reduce((s, t) => s + (t.duration || 0), 0);
  $('#plIle', PL.host).textContent = `${utwory.length} ${lm(utwory.length, 'utwór', 'utwory', 'utworów')} · ${fmtTime(czas)}`;
  $('#plZapisz', PL.host).disabled = !utwory.filter(t => !t.brak).length;
  rysujDuplikaty();
}

async function odswiezGrupy(){
  if(!PL.lista.length){ PL.grupy = []; rysujDuplikaty(); return; }
  try{ const d = await api('/api/wersje/grupy', {method: 'POST', body: {files: PL.lista}, cicho: true}); PL.grupy = d.grupy || []; }
  catch(e){ PL.grupy = []; }
  rysujDuplikaty();
}

function rysujDuplikaty(){
  const box = $('#plDup', PL.host); if(!box) return;
  const m = mapa();
  // 1) ten sam utwór dwa razy na playliście (różne pliki albo ten sam)
  const wg = {};
  PL.lista.forEach((rel, i) => { const t = m[rel]; if(!t) return; const k = norm(t.artist) + '|' + norm(t.title); (wg[k] = wg[k] || []).push(i); });
  const podwojne = Object.entries(wg).filter(([k, ix]) => ix.length > 1 && !PL.odrzucone.has('pl:' + k));
  // 2) kopie w bibliotece
  const kopie = PL.grupy.filter(g => !PL.odrzucone.has('kopie:' + [...g.kopie].sort().join('|')));
  const wiersze = [
    ...podwojne.map(([k, ix]) => { const t = m[PL.lista[ix[0]]]; return `<div class="dup"><span class="warn">2×</span>
      <div class="tt" style="flex:1;min-width:0">${esc(t.artist)} — ${esc(t.title)} <span style="color:${K.dim}">· na playliście ${ix.length} razy (pozycje ${ix.map(i => i + 1).join(', ')})</span></div>
      <button class="btn mini" data-zostaw1="${esc(k)}" title="zostaw pierwsze wystąpienie, resztę usuń z playlisty">Zostaw jeden</button>
      <button class="btn mini goly" data-odrzuc="pl:${esc(k)}" title="to celowe — nie pokazuj">Odrzuć</button></div>`; }),
    ...kopie.map(g => { const t = m[g.plik] || {title: g.plik, artist: ''}; return `<div class="dup"><span class="info">${g.kopie.length} kopie</span>
      <div style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.artist)} — ${esc(t.title)}${g.programy.length ? ` <span class="warn" style="font-size:11.5px">· jedna w folderze ${esc(g.programy.join(', '))}</span>` : ''}</div>
      <button class="btn mini" data-przejrzyj="${esc(g.plik)}" title="porównaj kopie (format, jakość, pasmo) i wybierz, która zostaje">Przejrzyj</button>
      <button class="btn mini goly" data-odrzuc="kopie:${esc([...g.kopie].sort().join('|'))}" title="zostaw wszystkie kopie i nie pokazuj">Odrzuć</button></div>`; }),
  ];
  box.innerHTML = wiersze.length ? wiersze.join('') : `<div class="pusto" style="padding:16px">${PL.lista.length ? '✓ bez duplikatów' : 'duplikaty utworów z playlisty pojawią się tutaj'}</div>`;
  $('#plDupIle', PL.host).textContent = wiersze.length ? String(wiersze.length) : '';
}

function graj(rel){
  const t = mapa()[rel]; if(!t) return;
  S.player.graj({file: t.rel, title: t.title, artist: t.artist, bpm: t.bpm, camelot: t.camelot, duration: t.duration});
}

function render(host){
  PL.host = host;
  if(!document.getElementById('styl-playlista')){ const s = document.createElement('style'); s.id = 'styl-playlista'; s.textContent = STYLE; document.head.appendChild(s); }
  host.innerHTML = `
    <div class="kol">
      <div style="display:flex;align-items:baseline;gap:10px"><h2 style="margin:0">Biblioteka</h2><span id="plLibIle" style="color:${K.dim};font-size:12.5px"></span></div>
      <div class="szukaj"><input id="plSzukaj" placeholder="szukaj: artysta, tytuł, folder…"></div>
      <div class="panel" style="flex:1"><div class="lista" id="plLib"><div class="pusto"><span class="spin"></span> wczytuję…</div></div></div>
    </div>
    <div class="kol">
      <div style="display:flex;align-items:center;gap:10px"><h2 style="margin:0">Playlista</h2><span id="plIle" style="color:${K.dim};font-size:12.5px"></span>
        <button class="btn mini goly" id="plWyczysc" type="button" style="margin-left:auto">wyczyść</button></div>
      <div class="szukaj"><input class="nazwa" id="plNazwa" placeholder="nazwa playlisty, np. piątek 22:00"><button class="btn acc" id="plZapisz" type="button" disabled>Zapisz playlistę</button></div>
      <div class="panel" style="flex:1.6"><div class="lista" id="plLista"></div></div>
      <div style="display:flex;align-items:center;gap:8px"><span style="font:500 10.5px var(--mono);letter-spacing:.12em;color:${K.dim2}">DUPLIKATY</span><span class="badge" id="plDupIle" style="font:600 10.5px var(--mono);background:${K.acc};color:#0f0d0c;border-radius:10px;padding:0 7px"></span></div>
      <div class="panel" style="flex:.7"><div class="lista" id="plDup"></div></div>
    </div>`;
  $('#plNazwa', host).value = PL.nazwa;
  $('#plNazwa', host).oninput = e => { PL.nazwa = e.target.value; zapamietaj(); };
  $('#plSzukaj', host).oninput = e => { PL.szukaj = e.target.value; rysujLib(); };
  $('#plWyczysc', host).onclick = () => { if(!PL.lista.length) return; if(!confirm('Wyczyścić playlistę roboczą?')) return; PL.lista = []; zapamietaj(); rysujPlayliste(); rysujLib(); odswiezGrupy(); };
  const dodaj = rel => { if(PL.lista.includes(rel)){ toast('już jest na playliście', 'info'); return; } PL.lista.push(rel); zapamietaj(); rysujPlayliste(); rysujLib(); odswiezGrupy(); };
  host.addEventListener('click', e => {
    const g = e.target.closest('[data-graj]'); if(g){ graj(g.dataset.graj); setTimeout(() => { rysujLib(); rysujPlayliste(); }, 50); return; }
    const d = e.target.closest('[data-dodaj]'); if(d){ dodaj(d.dataset.dodaj); return; }
    const u = e.target.closest('[data-usun]'); if(u){ PL.lista.splice(Number(u.dataset.usun), 1); zapamietaj(); rysujPlayliste(); rysujLib(); odswiezGrupy(); return; }
    const p = e.target.closest('[data-przejrzyj]'); if(p){ S.pokazWersje(p.dataset.przejrzyj); return; }
    const o = e.target.closest('[data-odrzuc]'); if(o){ PL.odrzucone.add(o.dataset.odrzuc); S.pref.set('dup_odrzucone', [...PL.odrzucone]); rysujDuplikaty(); return; }
    const z = e.target.closest('[data-zostaw1]');
    if(z){ const m = mapa(); let byl = false;
      PL.lista = PL.lista.filter(rel => { const t = m[rel]; if(!t || norm(t.artist) + '|' + norm(t.title) !== z.dataset.zostaw1) return true; if(byl) return false; byl = true; return true; });
      zapamietaj(); rysujPlayliste(); rysujLib(); return; }
  });
  host.addEventListener('dblclick', e => { const w = e.target.closest('[data-dodaj2]'); if(w && !e.target.closest('button')) dodaj(w.dataset.dodaj2); });
  // przeciąganie w obrębie playlisty
  const lista = $('#plLista', host);
  lista.addEventListener('dragstart', e => { const w = e.target.closest('.pw'); if(!w) return; PL.przeciagany = Number(w.dataset.i); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', w.dataset.i); });
  lista.addEventListener('dragover', e => { const w = e.target.closest('.pw'); if(PL.przeciagany == null || !w) return; e.preventDefault(); lista.querySelectorAll('.nad').forEach(x => x.classList.remove('nad')); w.classList.add('nad'); });
  lista.addEventListener('drop', e => {
    const w = e.target.closest('.pw'); if(PL.przeciagany == null || !w) return; e.preventDefault();
    const z = PL.przeciagany, na = Number(w.dataset.i); PL.przeciagany = null;
    if(z !== na){ const [x] = PL.lista.splice(z, 1); PL.lista.splice(na, 0, x); zapamietaj(); }
    rysujPlayliste();
  });
  lista.addEventListener('dragend', () => { PL.przeciagany = null; lista.querySelectorAll('.nad').forEach(x => x.classList.remove('nad')); });
  $('#plZapisz', host).onclick = async e => {
    const nazwa = (PL.nazwa || '').trim();
    if(!nazwa){ toast('wpisz nazwę playlisty', 'warn'); $('#plNazwa', host).focus(); return; }
    const m = mapa(), files = PL.lista.filter(rel => m[rel]);
    const b = e.currentTarget; b.disabled = true; b.innerHTML = '<span class="spin"></span> zapisuję…';
    try{
      const r = await api('/api/playlist/from-selection', {method: 'POST', body: {name: nazwa, files}});
      toast(`zapisano „${r.name}” — ${r.count} ${lm(r.count, 'utwór', 'utwory', 'utworów')}${r.pominietych ? `, ${r.pominietych} nie znaleziono` : ''}. Eksport do rekordboxa: ekran Eksport`, 'ok', 9000);
    }catch(err){}
    b.disabled = false; b.textContent = 'Zapisz playlistę';
  };
  document.addEventListener('selekta:player', () => { if(PL.host && PL.host.isConnected){ rysujLib(); rysujPlayliste(); } });
  // po wyborze wersji w „Przejrzyj”: wyrzucone kopie zamieniamy na zostawioną
  document.addEventListener('selekta:wersja', async e => {
    const {zostaw, usun} = e.detail || {};
    let zmiana = false;
    PL.lista = PL.lista.map(rel => { if((usun || []).includes(rel)){ zmiana = true; return zostaw; } return rel; })
                       .filter((rel, i, a) => a.indexOf(rel) === i);
    if(zmiana){ zapamietaj(); toast('na playliście podmieniono na wybraną wersję', 'info'); }
    await load(PL.host, true);
  });
}

async function load(host, force = false){
  PL.host = host;
  try{ PL.lib = await S.tracks(force); }
  catch(e){ $('#plLib', host).innerHTML = `<div class="pusto bad">✗ ${esc(e.message)}</div>`; return; }
  PL.lib = [...PL.lib].sort((a, b) => (a.artist || '').localeCompare(b.artist || '', 'pl') || (a.title || '').localeCompare(b.title || '', 'pl'));
  rysujLib(); rysujPlayliste(); odswiezGrupy();
}

S.ekran('playlista', {tytul: 'PLAYLISTA · układanie z odsłuchem', render, load});
})();
