/* ================================================================
 * 搜索：历史记录、搜索发起、轮询、结果合并去重、结果 Tab 渲染、通用歌曲行渲染
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 搜索 */
function addHistory(q){ state.history = [q, ...state.history.filter(x => x !== q)].slice(0, 8); store.set('cm_history', state.history); }
function renderHist(){
  const box = $('#search-hist');
  if (!state.history.length) { box.classList.remove('show'); return; }
  box.innerHTML = `<div class="h-title"><span>搜索历史</span><span id="hist-clear">清空</span></div>` + state.history.map(h => `<div class="h-row" data-q="${esc(h)}"><svg class="ic sm"><use href="#i-clock"/></svg>${esc(h)}</div>`).join('');
  box.classList.add('show');
  box.querySelector('#hist-clear').onclick = () => { state.history = []; store.set('cm_history', []); box.classList.remove('show'); };
  box.querySelectorAll('.h-row').forEach(r => r.onclick = () => { box.classList.remove('show'); $('#search-input').value = r.dataset.q; doSearch(r.dataset.q); });
}
const si = $('#search-input');
si.addEventListener('focus', renderHist);
si.addEventListener('blur', () => setTimeout(() => $('#search-hist').classList.remove('show'), 180));
si.addEventListener('keydown', e => { if (e.key === 'Enter' && si.value.trim()) { $('#search-hist').classList.remove('show'); doSearch(si.value.trim()); } });
function doSearch(q){ addHistory(q); nav('search', { q }); }

async function startSearch(keyword){
  clearTimeout(state.search.timer);
  state.search = { ...state.search, keyword, job: null, sid: null, groups: [], all: [], finished: false };
  try {
    const d = await api('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keyword, sources: state.cfg }) });
    state.search.job = d.job_id; state.search.sid = d.sid;
    $('#search-summary').innerHTML = `正在搜索 <b>${esc(keyword)}</b> ...`;
    pollSearch();
  } catch(err){ toast(err.message, true); }
}
async function pollSearch(){
  if (!state.search.job || currentPage !== 'search') return;
  try {
    const d = await api('/api/search/status?job=' + state.search.job);
    state.search.groups = d.groups; state.search.finished = d.finished;
    mergeResults(); renderSearchResults();
    if (!d.finished) state.search.timer = setTimeout(pollSearch, 900);
  } catch(err){ /* 任务过期 */ }
}
function mergeResults(){
  const buckets = state.search.groups.map(g => g.items.slice()).filter(b => b.length);
  const merged = [], seen = new Map();
  let n = 0;
  while (buckets.some(b => b.length)) {
    for (const b of buckets) {
      const it = b.shift(); if (!it) continue;
      const key = norm(it.song_name) + '|' + norm((it.singers || '').split(/[\/,，、]/)[0]);
      const score = (LOSSLESS.has(it.ext) ? 1000 : 0) + (it.previewable ? 500 : 0) + (parseFloat((it.file_size || '0').replace(/[^\d.]/g, '')) || 0);
      if (!seen.has(key)) { seen.set(key, { best: it, others: [it] }); }
      else { const o = seen.get(key); o.others.push(it); if (score > scoreOf(o.best)) o.best = it; }
      merged.push(it); n++;
    }
  }
  state.search.all = merged;
  state.search.dedup = [...seen.values()].map(v => ({ ...v.best, _versions: v.others }));
}
function scoreOf(it){ return (LOSSLESS.has(it.ext) ? 1000 : 0) + (it.previewable ? 500 : 0) + (parseFloat((it.file_size || '0').replace(/[^\d.]/g, '')) || 0); }
/* ---------------------------------------------------------------- 同一首歌判定
   只在「同一首歌」之间才允许换源顶替(直链失效重解析 / 批量下载自动选版本)。
   判据: 归一化歌名完全相同 + 歌手相容。绝不使用子串或相似度 —— 否则库内景颇族《你的微笑》(岳木果)
   会被飞儿乐团同名曲顶替、《景颇山我的家乡》会被《我的家乡》顶替, 界面上却仍显示库内歌名。
   判定口径与后端 _same_recording() 保持一致。 */
function sameRecording(tname, tsingers, cname, csingers){
  const tn = norm(tname), cn = norm(cname);
  if (!tn || !cn || tn !== cn) return false;
  const na = norm(tsingers), nb = norm(csingers);
  if (!na || !nb || na === nb) return true;
  return (na.length >= 2 && nb.includes(na)) || (nb.length >= 2 && na.includes(nb));
}
function pickSameRecording(cands, name, singers){
  const s0 = String(singers || '').split(/[\/,，、]/)[0];
  return cands.filter(c => sameRecording(name, s0, c.song_name, String(c.singers || '').split(/[\/,，、]/)[0]))
              .sort((a, b) => scoreOf(b) - scoreOf(a))[0] || null;
}
function renderSearchResults(){
  if (currentPage !== 'search') return;
  const s = state.search;
  /* 限定 #page-search: 索引页的 tab 用的是 data-itab 而非 data-tab, 全局选择器会把它们也选中,
     导致 panes[undefined] -> null.style 抛 TypeError, 并误清掉索引页 tab 的 .on 状态 */
  $$('#page-search .stab').forEach(t => { t.classList.toggle('on', t.dataset.tab === s.tab); const panes = { songs: '#stab-songs', artists: '#stab-artists', albums: '#stab-albums', playlist: '#stab-playlist' }; $(panes[t.dataset.tab]).style.display = t.dataset.tab === s.tab ? '' : 'none'; });
  if (s.tab === 'artists') return renderArtistTab();
  if (s.tab === 'albums') return renderAlbumTab();
  if (s.tab === 'playlist') return;
  /* 音源筛选chips */
  const chips = $('#src-chips');
  const total = s.dedup ? s.dedup.length : 0;
  chips.innerHTML = `<div class="chip ${s.filter === '全部' ? 'on' : ''}" data-f="全部">全部 (${total})</div>` + s.groups.map(g => `<div class="chip ${s.filter === g.source ? 'on' : ''}" data-f="${g.source}">${g.done ? '' : '<span class="spin"></span>'}${g.error ? `<span style="color:#e04b4b;font-weight:700" title="该音源出错: ${esc(g.error)}">!</span>` : ''}${esc(g.source_cn)} <span class="cnt">${g.items.length}</span></div>`).join('');
  chips.querySelectorAll('.chip').forEach(c => c.onclick = () => { s.filter = c.dataset.f; renderSearchResults(); });
  const rows = (s.dedup || []).filter(it => s.filter === '全部' || it.source === s.filter);
  const slowHint = state.ethnos.building ? '（后台正在构建民族歌单，搜索可能稍慢，可到民族音乐页停止构建）' : '';
  $('#search-summary').innerHTML = s.keyword ? (total ? `搜索 “<b>${esc(s.keyword)}</b>” ${s.finished ? '找到' : '已找到'} <b>${total}</b> 首单曲${s.finished ? '' : '，其余音源仍在搜索...'}` : `正在搜索 “<b>${esc(s.keyword)}</b>” ，快源通常 5~10 秒返回首批结果...${slowHint}`) : '';
  $('#search-tbody').innerHTML = rows.map((it, i) => songRow(it, i, { sid: s.sid })).join('') || '';
  $('#search-empty').style.display = rows.length ? 'none' : (s.finished ? '' : 'none');
  bindSongRows($('#search-tbody'), rows, { sid: s.sid });
}
function renderArtistTab(){
  const map = new Map();
  state.search.all.forEach(it => { const k = it.singers || '未知歌手'; if (!map.has(k)) map.set(k, { k, n: 0 }); map.get(k).n++; });
  const arr = [...map.values()].sort((a, b) => b.n - a.n).slice(0, 30);
  $('#art-grid').innerHTML = arr.map(a => `<div class="art-card" data-k="${esc(a.k)}"><div class="av">${esc((a.k || '?')[0])}</div><div class="nm">${esc(a.k)}</div><div class="ct">${a.n} 首相关单曲</div></div>`).join('') || `<div class="empty">无数据</div>`;
  $$('#art-grid .art-card').forEach(c => c.onclick = () => doSearch(c.dataset.k));
}
function renderAlbumTab(){
  const map = new Map();
  state.search.all.forEach(it => { const al = it.album || '未知专辑'; const k = al + '|' + it.singers; if (!map.has(k)) map.set(k, { al, singer: it.singers, n: 0 }); map.get(k).n++; });
  const arr = [...map.values()].sort((a, b) => b.n - a.n).slice(0, 30);
  $('#alb-grid').innerHTML = arr.map(a => `<div class="alb-card" data-k="${esc(a.al)}"><div class="cov">${esc(a.al)}</div><div class="nm">${esc(a.al)}</div><div class="ct">${esc(a.singer || '')} · ${a.n}首</div></div>`).join('') || `<div class="empty">无数据</div>`;
  $$('#alb-grid .alb-card').forEach(c => c.onclick = () => doSearch(c.dataset.al || c.dataset.k));
}
$$('#page-search .stab').forEach(t => t.onclick = () => { state.search.tab = t.dataset.tab; renderSearchResults(); });

/* 通用歌曲行渲染 */
function songRow(it, i, ctx){
  const sq = LOSSLESS.has(it.ext) ? '<span class="qbadge sq">SQ</span>' : '';
  const playing = currentTrack() && norm(currentTrack().name) === norm(it.song_name) && norm(currentTrack().artist).includes(norm((it.singers||'').split(/[\/,，、]/)[0]));
  const isPinned = !!(ctx && ctx.pinned);
  const pinBtn = ctx && ctx.ethGroup ? `<button class="a-pin ${isPinned ? 'pinned' : ''}" title="${isPinned ? '取消置顶' : '置顶'}">${isPinned ? '📌' : '📌'}</button>` : '';
  const rmBtn = ctx && ctx.removable ? `<button class="a-rm" title="从歌单移除"><svg class="ic sm"><use href="#i-x"/></svg></button>` : '';
  /* 曲库检索结果: 附带民族库归属与「从库删除」按钮 */
  const showGroup = ctx && ctx.showGroup;
  const gCell = showGroup ? `<td class="td-group"><span class="grptag" data-g="${esc(it.group || '')}">${esc(it.group || '—')}</span></td>` : '';
  const delBtn = showGroup ? `<button class="a-gdel" title="从「${esc(it.group || '')}」库删除该曲"><svg class="ic sm"><use href="#i-trash"/></svg></button>` : '';
  const _bk = trackKeyOf(it), _on = batchSel.has(_bk);
  const chkEl = `<input type="checkbox" class="bchk" ${_on ? 'checked' : ''}>`;
  return `<tr data-i="${i}" ${ctx && ctx.ethGroup ? 'draggable="true"' : ''} class="${playing ? 'playing' : ''}${_on ? ' on' : ''}${isPinned ? ' is-pinned' : ''}" ${showGroup && it.group ? `data-ethgroup="${esc(it.group)}"` : ''}>
    <td class="td-index">${chkEl}<span class="num">${String(i + 1).padStart(2, '0')}</span><span class="pbtn"><svg class="ic sm fill"><use href="#i-play"/></svg></span></td>
    <td class="td-name"><div class="inner"><span class="t ${playing ? 'now' : ''}">${esc(it.song_name)}</span>${sq}</div></td>
    <td class="td-singer" title="查看歌手">${esc(it.singers || '')}</td>
    <td class="td-album" title="查看专辑">${esc(it.album || '')}</td>
    ${gCell}
    <td><span class="srctag" style="background:${srcColor(it.source)}">${esc(it.source_cn || state.srcNames[it.source] || it.source)}</span></td>
    <td class="td-time">${esc(it.duration || '--:--')}</td>
    <td class="td-act">
      ${pinBtn}
      <button class="a-fav ${isFav({ name: it.song_name, artist: it.singers }) ? 'faved' : ''}" title="喜欢"><svg class="ic sm ${isFav({ name: it.song_name, artist: it.singers }) ? 'fill' : ''}"><use href="#i-heart"/></svg></button>
      <button class="a-pl" title="加入歌单"><svg class="ic sm"><use href="#i-folder"/></svg></button>
      <button class="a-artist" title="添加到歌手（模糊搜索定位）"><svg class="ic sm"><use href="#i-artist"/></svg></button>
      <button class="a-add" title="加入播放列表"><svg class="ic sm"><use href="#i-plus"/></svg></button>
      <button class="a-dl" title="多音源下载"><svg class="ic sm"><use href="#i-download"/></svg></button>
      ${delBtn}
      ${rmBtn}
    </td></tr>`;
}

