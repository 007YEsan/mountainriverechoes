/* ================================================================
 * 播放器核心：队列、播放/暂停、进度与音量、播放模式、播放列表抽屉
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 播放器核心 */
function currentTrack(){ return state.queue[state.qidx] || null; }
function setQueue(list, idx){ state.queue = list; state.qidx = idx; renderDrawer(); updateCount(); }
function updateCount(){ $('#pb-count').textContent = state.queue.length; }
function addToQueue(track, playNow){
  state.queue.push(track);
  if (playNow) { state.qidx = state.queue.length - 1; loadCurrent(); }
  renderDrawer(); updateCount();
  if (!playNow) toast('已加入播放列表');
}
async function playTrack(track, opts = {}){
  state.fm.on = false; renderFM();
  if (opts.list && opts.list.length) { state.queue = opts.list; state.qidx = opts.list.findIndex(t => t === track || (t.name === track.name && t.artist === track.artist)); if (state.qidx < 0) { state.queue.push(track); state.qidx = state.queue.length - 1; } }
  else addToQueue(track, true);
  loadCurrent();
}
/* 预览链接: 除 sid/id 外**一并带上曲目身份**(歌名/歌手/音源)。musicdl 的会话是纯内存态
   (上限 16 个, 服务重启即全失效), 会话一过期 /api/preview 就 404, 前端随即走"全网重搜同名曲"兜底 ——
   那条路曾把库内《你的微笑》(岳木果) 换成飞儿乐团同名曲。带上身份后服务端能直接回本地曲库重定位。 */
function previewUrl(t){
  return `/api/preview?sid=${encodeURIComponent(t.sid)}&id=${encodeURIComponent(t.id)}`
    + `&n=${encodeURIComponent(t.name || '')}&s=${encodeURIComponent(t.artist || '')}&src=${encodeURIComponent(t.source || '')}`;
}
async function loadCurrent(){
  const t = currentTrack(); if (!t) return;
  updatePlayerUI(t);
  pushHistory(t);
  loadLyric(t);
  audio.pause(); audio.removeAttribute('src');
  $('#pb-cover').classList.add('resolving');
  if (t.localUrl) { audio.src = t.localUrl; audio.play().catch(() => {}); }
  else if (t.sid && t.id) { audio.src = previewUrl(t) + (t.ms ? `#t=${t.ms}` : ''); audio.play().catch(() => {}); }
  else { /* 需要解析 */ $('#pb-name').textContent = t.name; $('#pb-artist').textContent = (t.artist || '') + ' · 正在解析播放链接...'; try { await resolveTrack(t); if (currentTrack() !== t) return; if (t.sid && t.id) { audio.src = previewUrl(t) + (t.ms ? `#t=${t.ms}` : ''); audio.play().catch(() => {}); } else { toast(`未找到《${t.name}》的可播放链接`, true); nextTrack(true); } } catch(err){ toast('解析失败: ' + err.message, true); } }
}
async function resolveTrack(t){
  if (t.resolving) return t.resolving;
  t.resolving = (async () => {
    const keyword = `${t.name} ${t.artist || ''}`.trim();
    const d = await api('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keyword, sources: state.cfg }) });
    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
      const st = await api('/api/search/status?job=' + d.job_id);
      const cands = [];
      st.groups.forEach(g => g.items.forEach(it => { if (it.previewable) cands.push(it); }));
      /* 只接受同一首歌(歌名完全相同+歌手相容): 换个同名通俗曲顶上来 = 放错歌, 比放不出更糟 */
      const best = pickSameRecording(cands, t.name, t.artist);
      if (best) {
        t.sid = st.sid; t.id = best.id; t.source = best.source; t.source_cn = best.source_cn; t.duration = t.duration || best.duration; t.cover = t.cover || best.cover_url;
        return t;
      }
      if (st.finished) return null;
      await new Promise(r => setTimeout(r, 900));
    }
    return null;
  })();
  const r = await t.resolving; t.resolving = null; return r;
}
function updatePlayerUI(t){
  $('#pb-name').textContent = t.name || '未知曲目';
  $('#pb-artist').textContent = t.artist || '—';
  $('#np-title').textContent = t.name || '';
  $('#np-sub').textContent = (t.artist || '') + (t.album ? ' · ' + t.album : '');
  const cv = $('#pb-cover'); cv.classList.remove('resolving');
  const setCover = (el, ph) => { el.innerHTML = (ph ? `<img src="${ph}" onerror="this.outerHTML='<div class=&quot;ph&quot;><svg class=&quot;ic lg&quot;><use href=&quot;#i-note&quot;/></svg></div>'">` : `<div class="ph"><svg class="ic lg"><use href="#i-note"/></svg></div>`); };
  setCover(cv, t.cover ? `/api/cover?url=${encodeURIComponent(t.cover)}` : '');
  setCover($('#np-cover'), t.cover ? `/api/cover?url=${encodeURIComponent(t.cover)}` : '');
  $('#np-bg').style.backgroundImage = t.cover ? `url(/api/cover?url=${encodeURIComponent(t.cover)})` : 'none';
  $('#t-dur').textContent = t.duration && /^\d+:\d+/.test(t.duration) ? t.duration : '00:00';
  $('#t-cur').textContent = '00:00'; $('#prog-bar .fill').style.width = '0%'; $('#prog-bar .dot').style.left = '0%';
  refreshHearts(); renderDrawer(); updateCount();
}
function refreshHearts(){
  const t = currentTrack(); const on = t && isFav(t);
  $('#pb-heart').classList.toggle('faved', !!on);
  $('#pb-heart svg').classList.toggle('fill', !!on);
  $('#np-heart').classList.toggle('faved', !!on);
  $('#np-heart svg').classList.toggle('fill', !!on);
}
function nextTrack(auto){
  const q = state.queue; if (!q.length) return;
  if (auto && state.fm.on) return fmNext();
  if (state.mode === 'single' && auto) { audio.currentTime = 0; audio.play(); return; }
  if (state.mode === 'shuffle') { let i; do { i = Math.floor(Math.random() * q.length); } while (q.length > 1 && i === state.qidx); state.qidx = i; }
  else state.qidx = (state.qidx + 1) % q.length;
  loadCurrent();
}
function prevTrack(){ const q = state.queue; if (!q.length) return; state.qidx = (state.qidx - 1 + q.length) % q.length; loadCurrent(); }
$('#pb-play').onclick = () => { if (!currentTrack()) { toast('播放列表为空，去搜索或打开推荐歌单吧'); return; } audio.paused ? audio.play().catch(e => toast('播放失败: ' + e.message, true)) : audio.pause(); };
$('#pb-prev').onclick = prevTrack;
$('#pb-next').onclick = () => nextTrack(false);
$('#pb-heart').onclick = () => toggleFav(currentTrack());
audio.addEventListener('play', () => { $('#pb-cover').classList.remove('resolving'); $('#pb-play').innerHTML = '<svg class="fill"><use href="#i-pause"/></svg>'; $('#np-disc').classList.add('rot'); $('#nowplaying').classList.add('playing'); if (state.fm.on) $('#fm-disc').classList.add('rot'); });
audio.addEventListener('pause', () => { $('#pb-play').innerHTML = '<svg class="fill"><use href="#i-play"/></svg>'; $('#np-disc').classList.remove('rot'); $('#nowplaying').classList.remove('playing'); $('#fm-disc').classList.remove('rot'); });
audio.addEventListener('ended', () => nextTrack(true));
audio.addEventListener('error', () => {
  const t = currentTrack(); if (!t || !audio.getAttribute('src')) return;
  t._errCount = (t._errCount || 0) + 1;
  if (t._errCount > 2) { toast(`《${t.name}》播放失败，已跳过`, true); return nextTrack(true); }
  toast('播放链接失效，尝试重新解析...', true);
  t.sid = null; t.id = null;
  resolveTrack(t).then(r => { if (r) loadCurrent(); else nextTrack(true); });
});
audio.addEventListener('timeupdate', () => {
  const c = audio.currentTime, d = audio.duration;
  $('#t-cur').textContent = fmtTime(c);
  if (isFinite(d) && d > 0) { $('#t-dur').textContent = fmtTime(d); const p = (c / d * 100).toFixed(2) + '%'; $('#prog-bar .fill').style.width = p; $('#prog-bar .dot').style.left = p; }
  else if (currentTrack() && currentTrack().duration) $('#t-dur').textContent = currentTrack().duration;
  syncLyric(c);
});
/* 进度条拖动 */
function bindBar(bar, cb){
  const apply = e => { const r = bar.getBoundingClientRect(); const x = Math.min(Math.max(e.clientX - r.left, 0), r.width); cb(x / r.width); };
  bar.addEventListener('mousedown', e => { apply(e); const mv = ev => apply(ev); const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); }; document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up); });
}
bindBar($('#prog-bar'), ratio => { if (isFinite(audio.duration)) { audio.currentTime = ratio * audio.duration; const p = (ratio * 100) + '%'; $('#prog-bar .fill').style.width = p; $('#prog-bar .dot').style.left = p; } });
const vol = store.get('cm_vol', 0.8);
function setVol(v){ audio.volume = v; store.set('cm_vol', v); $('#vol-bar .fill').style.width = (v * 100) + '%'; $('#vol-bar .dot').style.left = (v * 100) + '%'; $('#pb-vol').style.opacity = v === 0 ? .45 : 1; }
setVol(vol);
bindBar($('#vol-bar'), ratio => setVol(Math.min(Math.max(ratio, 0), 1)));
$('#pb-vol').onclick = () => setVol(audio.volume > 0 ? 0 : 0.8);
/* 播放模式 */
const MODES = [ ['list', '#i-repeat', '列表循环'], ['single', '#i-repeat1', '单曲循环'], ['shuffle', '#i-shuffle', '随机播放'] ];
function renderMode(){ const m = MODES.find(x => x[0] === state.mode) || MODES[0]; $('#pb-mode').innerHTML = `<svg class="ic"><use href="${m[1]}"/></svg>`; $('#pb-mode').title = m[2]; }
$('#pb-mode').onclick = () => { const i = MODES.findIndex(x => x[0] === state.mode); state.mode = MODES[(i + 1) % MODES.length][0]; store.set('cm_mode', state.mode); renderMode(); toast(MODES.find(x => x[0] === state.mode)[2]); };
renderMode();

/* ================================================================ 播放列表抽屉 */
$('#btn-drawer').onclick = () => $('#drawer').classList.toggle('show');
$('#dw-close').onclick = () => $('#drawer').classList.remove('show');
$('#dw-clear').onclick = () => { state.queue = []; state.qidx = -1; audio.pause(); audio.removeAttribute('src'); renderDrawer(); updateCount(); toast('播放列表已清空'); $('#pb-name').textContent = '未在播放'; $('#pb-artist').textContent = '—'; };
function renderDrawer(){
  $('#dw-title').textContent = `播放列表 (${state.queue.length})`;
  const list = $('#dw-list');
  list.innerHTML = state.queue.map((t, i) => `<div class="dw-row ${i === state.qidx ? 'playing' : ''}" data-i="${i}">
    <svg class="ic sm ${i === state.qidx ? 'fill' : ''}" style="flex:none;opacity:${i === state.qidx ? 1 : .35}"><use href="#i-play"/></svg>
    <span class="nm">${esc(t.name)}</span><span class="ar">${esc(t.artist || '')}</span>
    <button class="rm" title="移除"><svg class="ic sm"><use href="#i-x"/></svg></button></div>`).join('') || `<div class="empty" style="padding:40px 0">播放列表是空的</div>`;
  list.querySelectorAll('.dw-row').forEach(r => {
    const i = +r.dataset.i;
    r.onclick = () => { state.qidx = i; loadCurrent(); };
    r.querySelector('.rm').onclick = e => { e.stopPropagation(); state.queue.splice(i, 1); if (i < state.qidx) state.qidx--; else if (i === state.qidx) { audio.pause(); if (state.qidx >= state.queue.length) state.qidx = 0; if (state.queue.length) loadCurrent(); } renderDrawer(); updateCount(); };
  });
  const cur = list.querySelector('.dw-row.playing'); if (cur) cur.scrollIntoView({ block: 'nearest' });
}

