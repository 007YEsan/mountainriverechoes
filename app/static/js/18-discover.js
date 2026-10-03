/* ================================================================
 * 发现音乐：榜单、预置歌单、歌单详情打开与渲染
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 发现音乐 / 榜单 / 歌单 */
const HOT_WORDS = ['周杰伦', '林俊杰', '陈奕迅', '邓紫棋', '薛之谦', '告五人', '五月天', 'Taylor Swift', '毛不易', 'BLACKPINK'];
async function initDiscover(){
  $('#hot-words').innerHTML = HOT_WORDS.map(w => `<span>${esc(w)}</span>`).join('');
  $$('#hot-words span').forEach(s => s.onclick = () => { $('#search-input').value = s.textContent; doSearch(s.textContent); });
  loadEthnos();
  if (!state.chartsList) {
    try { const d = await api('/api/charts'); state.chartsList = d.charts; } catch(err){ state.chartsList = []; }
  }
  renderChartCards();
  /* 榜单前3个做预览 (前5首): 每次进入发现页实时抓取, 60秒内不重复打接口 */
  if (Date.now() - (state.chartsFetchedAt || 0) > 60000) {
    state.chartsFetchedAt = Date.now();
    state.chartsList.slice(0, 3).forEach(c => loadChartPreview(c));
  }
  renderPlGrid();
}
async function loadChartPreview(chart){
  const el = $(`#chart-${chart.id}`);
  el.querySelector('.ct-items').innerHTML = `<div class="chart-item"><span class="spin"></span>加载中...</div>`;
  try {
    const d = await getPlaylistDetail(chart.id, 'netease', { refresh: true });
    chart._detail = d;
    el.querySelector('.ct-items').innerHTML = (d.tracks || []).slice(0, 5).map((t, i) => `<div class="chart-item" data-id="${chart.id}" data-i="${i}"><span class="rk">${i + 1}</span><span class="nm">${esc(t.name)}</span><span class="sg">${esc(t.artist)}</span></div>`).join('');
    el.querySelector('.upd').textContent = `${d.count}首 · ${new Date().toTimeString().slice(0, 5)}`;
    const cu = $('#charts-updated'); if (cu) cu.textContent = '实时更新 · ' + new Date().toTimeString().slice(0, 5);
    el.querySelectorAll('.chart-item').forEach(it => it.onclick = e => { e.stopPropagation(); const det = state.chartsList.find(c => c.id === it.dataset.id)._detail; const t = det.tracks[+it.dataset.i]; playTrack({ name: t.name, artist: t.artist, album: t.album, cover: t.cover, duration: fmtTime((t.duration_ms || 0) / 1000) }, { list: det.tracks.map(x => ({ name: x.name, artist: x.artist, album: x.album, cover: x.cover, duration: fmtTime((x.duration_ms || 0) / 1000) })) }); });
  } catch(err){ el.querySelector('.ct-items').innerHTML = `<div class="chart-item" style="color:var(--txt3)">榜单加载失败</div>`; }
}
function renderChartCards(){
  $('#chart-row').innerHTML = (state.chartsList || []).slice(0, 3).map(c => `<div class="chart-card" id="chart-${c.id}" data-id="${c.id}">
    <h3>${esc(c.name)} <span class="upd">...</span></h3><div class="ct-items"><div class="chart-item"><span class="spin"></span></div></div></div>`).join('');
  $$('#chart-row .chart-card').forEach(el => el.onclick = () => nav('playlist', { id: el.dataset.id, name: (state.chartsList.find(c => c.id === el.dataset.id) || {}).name }));
}
function renderPlGrid(){
  /* 汇总三个平台的预置歌单卡片 */
  const cards = [];
  (state.presets || []).forEach(g => g.items.slice(0, 4).forEach(it => cards.push({ ...it, platform: g.platform, platform_name: g.platform_name, platKey: (g.platform === 'qq' && it.kind === 'toplist') ? 'qq_toplist' : g.platform })));
  $('#pl-grid').innerHTML = cards.map(c => `<div class="pl-card" data-pk="${c.platKey}" data-id="${esc(c.id)}" data-nm="${esc(c.name)}">
    <div class="cov" style="background:linear-gradient(135deg,${(c.grad || ['#8e9eab','#eef2f3'])[0]},${(c.grad || ['#8e9eab','#eef2f3'])[1]})">${c.cover ? `<img src="/api/cover?url=${encodeURIComponent(c.cover)}" loading="lazy">` : esc(c.name)}<span class="plsrc" style="background:${(state.presets.find(g => g.platform === c.platform) || {}).color || '#9aa0a6'}">${esc(c.platform_name)}</span><span class="play-cov"><svg class="ic fill"><use href="#i-play"/></svg></span></div>
    <div class="nm">${esc(c.desc || c.name)}${c.count ? ` · ${c.count}首` : ''}</div></div>`).join('') + `<div class="pl-card" id="pl-import"><div class="cov" style="background:linear-gradient(135deg,#8e9eab,#eef2f3);color:#5b5b5b;text-shadow:none">＋ 导入歌单</div><div class="nm">粘贴网易云 / QQ / 汽水 / 酷狗歌单链接</div></div>`;
  $$('#pl-grid .pl-card[data-id]').forEach(el => el.onclick = () => nav('playlist', { id: el.dataset.id, platform: el.dataset.pk, name: el.dataset.nm }));
  $('#pl-import').onclick = () => $('#dlg-imp').classList.add('show');
}
function loadPresets(){
  if (state.presets) return Promise.resolve();
  const grab = () => api('/api/presetplaylists').then(d => {
    state.presets = d.presets || [];
    if (currentPage === 'discover') renderPlGrid();
    return state.presets.some(g => g.items.some(it => !it.cover));
  }).catch(() => false);
  grab().then(missing => { if (missing) setTimeout(() => grab().then(m2 => { if (m2) setTimeout(grab, 30000); }), 12000); });   /* 服务端后台补抓封面, 延时重拉两次 */
}
async function getPlaylistDetail(id, platform, opts){
  const key = (platform || 'netease') + ':' + id;
  const hit = state.playlistCache[key];
  const force = !!(opts && opts.refresh);
  if (!force && hit && Date.now() - hit.at < 600000) return hit.data;   /* 10 分钟内用缓存, 超时实时重抓 */
  const d = await api('/api/playlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, platform, refresh: force }) });
  if (!d.building) state.playlistCache[key] = { data: d, at: Date.now() };
  return d;
}
let currentDetail = null;
async function openPlaylistDetail(id, name, platform, attempt){
  $('#pld-name').textContent = name || '歌单';
  $('#pld-cov').innerHTML = '<span class="spin" style="width:26px;height:26px;border-width:3px"></span>';
  $('#pld-tbody').innerHTML = '';
  $('#pld-meta').textContent = '加载中...';
  currentDetail = null;
  let d;
  /* 我的歌单: 纯前端数据 */
  if (platform === 'my') {
    const p = state.myPlaylists.find(x => String(x.id) === String(id));
    if (!p) { $('#pld-meta').textContent = '歌单不存在'; return; }
    d = { id: String(p.id), name: p.name, cover: (p.tracks[0] || {}).cover_url || '', count: p.tracks.length, tracks: p.tracks, platform: 'my', platform_name: '我的歌单' };
  } else {
    try { d = await getPlaylistDetail(id, platform); } catch(err){ $('#pld-meta').textContent = '加载失败: ' + err.message; return; }
    /* 民族歌单可能仍在后台构建, 轮询等待 */
    if (d.building) {
      attempt = attempt || 0;
      $('#pld-meta').innerHTML = `正在遍历音源构建「${esc(name || '民族')}」歌单，约需 30~60 秒... (已等待 ${attempt * 4}s)`;
      if (attempt > 30) { $('#pld-meta').textContent = '构建超时，请稍后重试'; return; }
      setTimeout(() => openPlaylistDetail(id, name, platform, attempt + 1), 4000);
      return;
    }
  }
  currentDetail = d;
  renderPlaylistPage(name);
}

async function renderPlaylistPage(name){
  const d = currentDetail;
  if (!d) return;
  const isMy = d.platform === 'my';
  const plKey = (d.platform || 'netease') + ':' + d.id;
  const removed = (state.plRemoved[plKey] || []);
  const fallbackName = /^(榜单|歌单)\d+$/.test(d.name || '');
  $('#pld-name').textContent = (fallbackName && name) ? name : (d.name || name || '歌单');
  $('#pld-cov').innerHTML = d.cover ? `<img src="/api/cover?url=${encodeURIComponent(d.cover)}" onerror="this.style.display='none'">` : '♪';
  $('#pld-platform').textContent = '歌单 · ' + (d.platform_name || '网易云');
  let tracks = d.tracks.map(t => t.song_name
    ? { song_name: t.song_name, singers: t.singers, album: t.album, duration: t.duration || fmtTime((t.duration_ms || 0) / 1000), cover_url: t.cover_url || t.cover, sid: t.sid, id: t.id, source: t.source || 'Netease', source_cn: t.source_cn || state.srcNames[t.source] || '网易云', ext: t.ext, _versions: t._versions, ms: t.ms }
    : { song_name: t.name, singers: t.artist, album: t.album, duration: fmtTime((t.duration_ms || 0) / 1000), cover_url: t.cover, sid: t.sid, id: t.id, source: t.sid ? 'Playlist' : 'Netease', source_cn: t.sid ? '歌单解析' : '网易云', ms: t.ms });
  let visible = tracks.filter(t => !removed.includes(trackKeyOf(t)));
  /* 民族库详情页: 置顶/拖动次序(服务端单一事实来源), 置顶段在前 */
  const ethGroup = (d.platform === 'ethnos' && (d.id || d.key || d.group)) ? String(d.id || d.key || d.group) : null;
  let pinSet = new Set();
  if (ethGroup) {
    const cc = (state.ethCustom[ethGroup] = state.ethCustom[ethGroup] || {});
    if (cc.trackPinned === undefined) {
      try {
        const cd = await api(`/api/ethnos/custom?group=${encodeURIComponent(ethGroup)}`);
        cc.trackPinned = cd.tracks_pinned || [];
        cc.trackOrder = cd.track_order || [];
      } catch (e) { cc.trackPinned = []; cc.trackOrder = []; }
    }
    pinSet = new Set(cc.trackPinned || []);
    const tKey = ethTrackKey;
    const pIdx = new Map([...pinSet].map((k, i) => [k, i]));
    const oIdx = new Map((cc.trackOrder || []).map((k, i) => [k, i]));
    const dIdx = new Map(visible.map((t, i) => [tKey(t), i]));
    if (pinSet.size || oIdx.size) visible = visible.slice().sort((a, b) => {
      const ka = tKey(a), kb = tKey(b);
      const va = pIdx.has(ka) ? pIdx.get(ka) : (oIdx.has(ka) ? 100000 + oIdx.get(ka) : 200000 + (dIdx.get(ka) || 0));
      const vb = pIdx.has(kb) ? pIdx.get(kb) : (oIdx.has(kb) ? 100000 + oIdx.get(kb) : 200000 + (dIdx.get(kb) || 0));
      return va - vb;
    });
  }
  $('#pld-meta').innerHTML = `共 <b>${visible.length}</b> 首 · 来自${esc(d.platform_name || '网易云')}${d.update ? ' · 更新于 ' + esc(d.update) : ''}${removed.length ? ` · <span style="color:#e04b4b">已隐藏 ${removed.length} 首</span> <a id="pld-restore" style="color:var(--red);cursor:pointer">恢复</a>` : ''}${isMy ? ` · <a id="pld-delmy" style="color:#e04b4b;cursor:pointer">删除此歌单</a>` : ''}`;
  const rb = document.querySelector('#pld-restore'); if (rb) rb.onclick = () => restorePlaylistTracks(plKey);
  const db = document.querySelector('#pld-delmy'); if (db) db.onclick = () => deleteMyPlaylist(d.id);
  renderPlaylistPage._lastVisible = visible;
  $('#pld-tbody').innerHTML = visible.map((t, i) => songRow(t, i, { sid: d.sid, removable: true, plKey: isMy ? undefined : plKey, myId: isMy ? d.id : undefined, ethGroup, pinned: ethGroup && pinSet.has(ethTrackKey(t)) })).join('');
  bindSongRows($('#pld-tbody'), visible, { sid: d.sid, removable: true, plKey: isMy ? undefined : plKey, myId: isMy ? d.id : undefined, ethGroup, pinSet });
  if (ethGroup) {
    /* 行拖动: 改 DOM 顺序后把新次序(键序列)整体存服务端 */
    const tb = $('#pld-tbody');
    if (!tb._dragBound) {
      tb._dragBound = true;
      let dragTr = null;
      tb.addEventListener('dragstart', e => { const tr = e.target.closest('tr[draggable]'); if (!tr) return; dragTr = tr; tr.style.opacity = .35; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', ''); } catch(_){} });
      tb.addEventListener('dragend', async e => {
        if (!dragTr) return; dragTr.style.opacity = ''; dragTr = null;
        await postTrackOrder(ethGroup);
        renderPlaylistPage();
      });
      tb.addEventListener('dragover', e => {
        if (!dragTr) return; e.preventDefault();
        const over = e.target.closest('tr[draggable]'); if (!over || over === dragTr || over.parentElement !== dragTr.parentElement) return;
        const r = over.getBoundingClientRect();
        over.parentNode.insertBefore(dragTr, (e.clientY - r.top) > r.height / 2 ? over.nextSibling : over);
      });
    }
  }
}
$('#pld-back').onclick = () => { (state.navDepth > 0) ? history.back() : nav('discover'); };
$('#pld-playall').onclick = () => {
  if (!currentDetail) return;
  const list = currentDetail.tracks.map(t => ({ name: t.song_name || t.name, artist: t.singers || t.artist, album: t.album, cover: t.cover_url || t.cover, duration: t.duration || fmtTime((t.duration_ms || 0) / 1000), sid: t.sid, id: t.id, ms: t.ms }));
  if (!list.length) return toast('歌单为空');
  playTrack(list[0], { list });
};
