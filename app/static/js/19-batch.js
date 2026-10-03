/* ================================================================
 * 歌单批量管理：多选删除、移动/复制到歌手、批量下载
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================== 批量管理(多选删除/移动) */
let batchMode = false, batchSel = new Set();
/* 判定当前歌单详情能否做服务端写操作, 并给出源民族 key。
   只有民族歌单文件(eNN/han)与「歌手@民族」虚拟歌单有确定的落盘归属;
   平台歌单/我的歌单/搜索结果会话都是派生数据, 移动它们没有落盘意义。 */
function ethnosSourceOf(d){
  if (!d) return null;
  const id = d.id != null ? String(d.id) : '';
  /* 虚拟歌单详情加载后 platform 会变成 'ethnos' 但 id 仍是虚拟前缀 —— 必须先认前缀,
     否则整串 'artist:某某@民族' 会被当成 group key 传给后端(批量删除/移动全部失效) */
  if (id.startsWith('artist:')) {
    const at = id.indexOf('@');
    if (at > 0) { const nm = id.slice(at + 1).trim(); if (nm) return ethKeyOf(nm) || null; }
    return null;
  }
  if (id.startsWith('ytcoll:')) return ethKeyOf('景颇族') || null;   /* 景颇YouTube合集只在景颇库 */
  if (id.startsWith('album:')) return null;                          /* 专辑:xxx@歌手 不含民族归属 */
  /* 民族歌单详情: d.id 本身就是 group key(e26 / han), 后端 _cache_path 直接认 */
  if (d.platform === 'ethnos' && id) return id;
  return null;
}
function setBatchMode(on){
  batchMode = on;
  batchSel.clear();
  const pg = $('#page-playlist');
  pg.classList.toggle('batch-mode', on);
  $('#pld-batchbar').style.display = on ? 'flex' : 'none';
  $('#pld-batch').classList.toggle('btn-primary', on);
  $('#pld-batch').classList.toggle('btn-plain', !on);
  const src = ethnosSourceOf(currentDetail);
  if (on && !src) $('#pld-bmove').style.display = $('#pld-bcopy').style.display = 'none';
  else $('#pld-bmove').style.display = $('#pld-bcopy').style.display = '';
  refreshBatchBar();
  renderPlaylistPage();
}
function refreshBatchBar(){
  const n = batchSel.size;
  const el = $('#pld-bcnt'); if (el) el.innerHTML = `已选 <b>${n}</b> 首`;
  const ball = $('#pld-ball'); if (ball) { const rows = $('#pld-tbody').querySelectorAll('tr').length; ball.checked = n > 0 && n >= rows; ball.indeterminate = n > 0 && n < rows; }
  ['#pld-bdel', '#pld-bmove', '#pld-bcopy'].forEach(s => { const b = $(s); if (b) b.disabled = !n; });
}
$('#pld-batch').onclick = () => setBatchMode(!batchMode);
$('#pld-bexit').onclick = () => setBatchMode(false);
$('#pld-ball').onchange = e => {
  const on = e.target.checked;
  const rows = [...$('#pld-tbody').querySelectorAll('tr')];
  const ctx = buildPlCtx();
  rows.forEach(tr => {
    const i = +tr.dataset.i, it = (ctx.items || [])[i];
    if (!it) return;
    const k = trackKeyOf(it);
    on ? batchSel.add(k) : batchSel.delete(k);
    tr.classList.toggle('on', on);
    const cb = tr.querySelector('.bchk'); if (cb) cb.checked = on;
  });
  refreshBatchBar();
};
$('#pld-bdel').onclick = async () => {
  const n = batchSel.size; if (!n) return;
  if (!confirm(`确定删除所选 ${n} 首吗？\n（按 歌名+歌手+音源 定位，不会株连同名的其他版本）`)) return;
  const ctx = buildPlCtx();
  const src = ethnosSourceOf(currentDetail);
  const keys = [...batchSel].map(k => { const it = ctx.items.find(x => trackKeyOf(x) === k); return it ? { song_name: it.song_name, singers: it.singers, source: it.source } : null; }).filter(Boolean);
  toast(`正在删除 ${n} 首...`);
  try {
    if (src) {
      /* 民族歌单: 一次请求批量删, 不逐首打服务端 */
      const r = await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: src, editor: ethEditor(), action: 'remove_tracks', keys }) });
      toast(`已删除 ${r.removed || 0} 首`);
    } else if (ctx.myId) {
      const p = state.myPlaylists.find(x => String(x.id) === String(ctx.myId));
      if (p) { p.tracks = p.tracks.filter(t => !batchSel.has(trackKeyOf(t))); store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists(); toast(`已移除 ${n} 首`); }
    } else if (ctx.plKey) {
      /* 平台歌单没有落盘文件, 维持"本机隐藏"语义 */
      (state.plRemoved[ctx.plKey] = state.plRemoved[ctx.plKey] || []).push(...batchSel);
      store.set('cm_pl_removed', state.plRemoved);
      toast(`已隐藏 ${n} 首`);
    }
  } catch(e){ toast('删除失败: ' + e.message, true); return; }
  batchSel.clear(); refreshBatchBar();
  syncAfterEdit(true);
};
['#pld-bmove', '#pld-bcopy'].forEach(sel => $(sel).onclick = () => openMoveDialog(sel === '#pld-bcopy' ? 'copy' : 'move'));

/* 重建当前详情页的行上下文(与 renderPlaylistPage 保持同一套映射规则) */
function buildPlCtx(){
  const d = currentDetail; if (!d) return { items: [] };
  const isMy = d.platform === 'my';
  const plKey = (d.platform || 'netease') + ':' + d.id;
  const removed = (state.plRemoved[plKey] || []);
  const tracks = d.tracks.map(t => t.song_name
    ? { song_name: t.song_name, singers: t.singers, album: t.album, duration: t.duration || fmtTime((t.duration_ms || 0) / 1000), cover_url: t.cover_url || t.cover, sid: t.sid, id: t.id, source: t.source || 'Netease', source_cn: t.source_cn || state.srcNames[t.source] || '网易云', ext: t.ext, _versions: t._versions, ms: t.ms }
    : { song_name: t.name, singers: t.artist, album: t.album, duration: fmtTime((t.duration_ms || 0) / 1000), cover_url: t.cover, sid: t.sid, id: t.id, source: t.sid ? 'Playlist' : 'Netease', source_cn: t.sid ? '歌单解析' : '网易云', ms: t.ms });
  const items = tracks.filter(t => !removed.includes(trackKeyOf(t)));
  return { items, sid: d.sid, removable: true, plKey: isMy ? undefined : plKey, myId: isMy ? d.id : undefined };
}

/* ---- 移动/复制到歌手: 民族下拉 + 歌手模糊选择(与单曲"添加到歌手"同一套交互) ---- */
let mvMode = 'move', mvDst = null, mvArtist = null;
function ethOptsOf(){
  return [...(state.ethnos.groups || []).map(g => ({ k: g.key, n: g.name })), { k: 'han', n: '汉族' }];
}
function sourceLabelOf(key){
  if (key === 'han') return '汉族';
  const g = (state.ethnos.groups || []).find(x => x.key === key);
  return g ? g.name : (key || '');
}
function gkOfName(nm){
  if (!nm) return '';
  if (/^e\d{2}$/.test(nm) || nm === 'han') return nm;
  if (nm === '汉族' || nm === '汉族民间小调') return 'han';
  const g = (state.ethnos.groups || []).find(x => x.name === nm);
  return g ? g.key : '';
}
async function openMoveDialog(mode){
  mvMode = mode; mvDst = null; mvArtist = null;
  const n = batchSel.size; if (!n) return;
  const src = ethnosSourceOf(currentDetail);
  await _ensureArtists();
  $('#mv-title').textContent = (mode === 'copy' ? '复制到歌手' : '移动到歌手') + `（${n} 首）`;
  $('#mv-sub').textContent = src ? `源：${sourceLabelOf(src)} · 选择目标民族与歌手后确认` : '选择目标民族与歌手';
  $('#mv-ok').textContent = mode === 'copy' ? '确认复制' : '确认移动';
  $('#mv-ok').disabled = true;
  const opts = ethOptsOf().map(o => `<option value="${esc(o.k)}"${o.k === src ? ' selected' : ''}>${esc(o.n)}</option>`).join('');
  $('#mv-eth').innerHTML = opts;
  $('#mv-q').value = '';
  renderMvArtists('');
  $('#dlg-move').classList.add('show');
  setTimeout(() => { $('#mv-q').focus(); }, 60);
}
function renderMvArtists(q){
  const gk = $('#mv-eth').value || '';
  const gname = sourceLabelOf(gk);
  let pool = (_asArtistList || []).filter(a => (a.group === gname) || (gk === 'han' && (a.group === '汉族' || a.group === '汉族民间小调')));
  const hits = _asFuzzy((q || '').trim(), pool);
  const exact = q && pool.some(a => a.name === q);
  const rows = [];
  if (q && !exact) rows.push(`<div class="p as-newp" data-an="${esc(q)}">＋ 新建歌手「${esc(q)}」<span style="color:var(--txt3);font-size:11.5px;margin-left:8px">归入 ${esc(gname)}</span></div>`);
  rows.push(...hits.map(a => `<div class="p${mvArtist === a.name ? ' on' : ''}" data-an="${esc(a.name)}">${esc(a.name)}<span style="color:var(--txt3);font-size:11.5px;margin-left:8px">${esc(a.group)} · ${a.count} 首</span></div>`));
  $('#mv-list').innerHTML = rows.join('') || '<div style="color:var(--txt3);font-size:12.5px">该民族暂无歌手，输入名字即可新建</div>';
  $$('#mv-list .p[data-an]').forEach(el => el.onclick = () => {
    mvArtist = el.dataset.an;
    $$('#mv-list .p').forEach(o => o.classList.toggle('on', o === el));
    $('#mv-ok').disabled = false;
  });
  $('#mv-tip').textContent = mvMode === 'copy'
    ? `复制后这批歌曲会同时出现在「${mvArtist || '…'}」名下，源歌手保留`
    : `移动后这批歌曲挂到「${mvArtist || '…'}」名下，并从源歌手处删除`;
}
$('#mv-eth').addEventListener('change', () => { mvArtist = null; $('#mv-ok').disabled = true; renderMvArtists($('#mv-q').value); });
$('#mv-q').addEventListener('input', e => renderMvArtists(e.target.value));
$('#mv-q').addEventListener('keydown', e => { if (e.key === 'Enter') { const first = $('#mv-list .p'); if (first) first.click(); } });
$('#mv-ok').onclick = async () => {
  const n = batchSel.size;
  if (!n) return toast('未选择曲目');
  const dstKey = $('#mv-eth').value;
  if (!dstKey) return toast('请选择目标民族');
  if (!mvArtist) return toast('请选择目标歌手（或输入新名字新建）');
  const src = ethnosSourceOf(currentDetail);
  const ctx = buildPlCtx();
  const picks = [...batchSel].map(k => ctx.items.find(x => trackKeyOf(x) === k)).filter(Boolean);
  const sid = ctx.sid || (picks[0] || {}).sid;
  if (!sid) return toast('当前会话不可写，请重新打开该页面', true);
  $('#dlg-move').classList.remove('show');
  toast(`正在${mvMode === 'copy' ? '复制' : '移动'} ${picks.length} 首 → 「${mvArtist}」...`);
  let ok = 0, dup = 0, fail = 0;
  for (const it of picks) {
    try {
      await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: dstKey, action: 'add_to_artist', dst: dstKey, artist: mvArtist, sid, tid: it.id, editor: ethEditor() }) });
      ok++;
    } catch (err) {
      if ((err.message || '').includes('已在')) dup++; else { fail++; console.warn(err); }
    }
  }
  let removedN = 0;
  if (mvMode === 'move' && src && ok) {
    const keys = picks.filter(it => it.song_name).map(it => ({ song_name: it.song_name, singers: it.singers, source: it.source }));
    try {
      const r = await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: src, editor: ethEditor(), action: 'remove_tracks', keys }) });
      removedN = r.removed || 0;
    } catch (e) { /* 源删除失败不阻断: 曲目已复制 */ }
  }
  toast(`已${mvMode === 'copy' ? '复制' : '移动'} ${ok} 首到「${mvArtist}」${dup ? `，${dup} 首已存在` : ''}${fail ? `，${fail} 首失败` : ''}${removedN ? `，源处移除 ${removedN} 首` : ''}`);
  batchSel.clear(); refreshBatchBar();
  /* 本地解禁目标歌手 */
  const cc = (state.ethCustom[dstKey] = state.ethCustom[dstKey] || {});
  if ((cc.removed || []).includes(mvArtist)) { cc.removed = cc.removed.filter(x => x !== mvArtist); store.set('cm_ethnic_custom', state.ethCustom); }
  state.ethSynced = {}; state.index.data = null;
  syncAfterEdit(true);
};
/* 任何写操作后: 让服务端重新算索引, 并把各层级视图一起刷掉 */
async function syncAfterEdit(reloadDetail){
  try { await api('/api/index'); } catch(e){}
  try { await loadIndex(true); } catch(e){}
  try { await loadEthnos(); } catch(e){}
  try { if (reloadDetail && currentDetail) await openPlaylistDetail(currentDetail.id, currentDetail.name, currentDetail.platform); } catch(e){}
  if (currentPage === 'index') { try { renderIndex(); } catch(e){ /* 页面尚未就绪, 忽略 */ } }
  try { setBatchMode(false); } catch(e){}
}
async function batchDownload(songs){
  toast(`开始批量下载 ${songs.length} 首...`);
  let ok = 0;
  const worker = async (song) => {
    try {
      const d = await api('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keyword: `${song.name} ${song.artist || ''}`.trim(), sources: state.cfg }) });
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline) {
        const st = await api('/api/search/status?job=' + d.job_id);
        const cands = [];
        st.groups.forEach(g => g.items.forEach(it => { if (it.downloadable !== false) cands.push(it); }));
        /* 同 resolveTrack: 只有同一首歌才自动下载, 否则宁可这首匹配不到也不下错 */
        const best = pickSameRecording(cands, song.name, song.artist);
        if (best) { await api('/api/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sid: st.sid, picks: [best.id] }) }); ok++; pollTasks(); return; }
        if (st.finished) return;
        await new Promise(r => setTimeout(r, 1000));
      }
    } catch(err){}
  };
  const q = songs.slice(); const workers = [0, 1].map(() => (async () => { while (q.length) await worker(q.shift()); })());
  await Promise.all(workers);
  toast(`批量下载任务已全部提交（成功匹配 ${ok}/${songs.length} 首）`);
}

