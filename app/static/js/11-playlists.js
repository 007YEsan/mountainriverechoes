/* ================================================================
 * 我的歌单、歌单内曲目微调（删除/移动/恢复）、最近播放
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 我的歌单 / 歌单微调 / 最近播放 */
const trackKeyOf = t => t.id || ((t.song_name || t.name || '') + '|' + (t.singers || t.artist || ''));
/* 民族库曲目稳定键(与后端 _track_rawkey 一致): id 每次加载会重排, 不能作为置顶/次序键 */
const ethTrackKey = t => [t.song_name || '', t.singers || '', t.source || ''].join('\u001f');

function renderMyPlaylists(){
  $('#my-playlists').innerHTML = state.myPlaylists.map(p => `<div class="nav-item" data-pl="${esc(p.id)}"><svg class="ic"><use href="#i-list"/></svg><span class="grow">${esc(p.name)}</span><button class="pl-del" data-del="${esc(p.id)}" title="删除此歌单"><svg class="ic sm"><use href="#i-trash"/></svg></button></div>`).join('');
  $$('#my-playlists .nav-item').forEach(el => el.onclick = () => nav('playlist', { id: el.dataset.pl, platform: 'my', name: (state.myPlaylists.find(p => String(p.id) === el.dataset.pl) || {}).name || '我的歌单' }));
  $$('#my-playlists .pl-del').forEach(b => b.onclick = e => { e.stopPropagation(); deleteMyPlaylist(b.dataset.del); });
}
$('#nav-newpl').onclick = () => {
  const name = prompt('新建歌单名称：');
  if (name && name.trim()) {
    state.myPlaylists.unshift({ id: Date.now(), name: name.trim(), tracks: [] });
    store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists();
    toast(`歌单「${name.trim()}」已创建`);
    nav('playlist', { id: String(state.myPlaylists[0].id), platform: 'my', name: name.trim() });
  }
};
function deleteMyPlaylist(id){
  const p = state.myPlaylists.find(x => String(x.id) === String(id));
  if (!p || !confirm(`删除歌单「${p.name}」？(不影响已下载文件)`)) return;
  state.myPlaylists = state.myPlaylists.filter(x => String(x.id) !== String(id));
  store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists(); toast('歌单已删除');
  if (currentPage === 'playlist') nav('discover');
}
function openAddToPlaylist(track){
  state.addPlTrack = track;
  $('#addpl-song').textContent = `${track.name || ''} - ${track.artist || ''}`;
  const box = $('#addpl-list');
  box.innerHTML = state.myPlaylists.length ? state.myPlaylists.map(p => `<div class="ms-row" data-id="${p.id}">
    <span class="cb" style="border-radius:6px"><svg class="ic sm"><use href="#i-list"/></svg></span>
    <span class="nm">${esc(p.name)}</span>
    <span class="meta">${p.tracks.length} 首</span></div>`).join('') : `<div class="empty" style="padding:26px 0">还没有自建歌单，先在下方新建一个吧</div>`;
  box.querySelectorAll('.ms-row').forEach(r => r.onclick = () => {
    const p = state.myPlaylists.find(x => String(x.id) === r.dataset.id);
    const key = trackKeyOf(state.addPlTrack);
    if (p.tracks.some(t => trackKeyOf(t) === key)) { toast('这首歌已在歌单中'); return; }
    p.tracks.push({ song_name: state.addPlTrack.name, singers: state.addPlTrack.artist, album: state.addPlTrack.album || '', duration: state.addPlTrack.duration || '', cover_url: state.addPlTrack.cover || '', source: state.addPlTrack.source || '', source_cn: state.addPlTrack.source_cn || '', sid: state.addPlTrack.sid, id: state.addPlTrack.id, localUrl: state.addPlTrack.localUrl });
    store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists();
    $('#dlg-addpl').classList.remove('show');
    toast(`已加入「${p.name}」`);
  });
  $('#dlg-addpl').classList.add('show');
}
$('#addpl-new').onclick = () => {
  const name = prompt('新建歌单名称：');
  if (name && name.trim()) {
    state.myPlaylists.unshift({ id: Date.now(), name: name.trim(), tracks: [] });
    store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists();
    openAddToPlaylist(state.addPlTrack);
  }
};
async function postTrackOrder(group){
  /* 收集当前 DOM 行序 -> keys(完整顺序) + pinned(置顶子集), 整体存服务端(原始复合键, 不带 id) */
  const tb = document.querySelector('#pld-tbody');
  if (!tb || !renderPlaylistPage._lastVisible) return;
  const rows = [...tb.querySelectorAll('tr[data-i]')];
  const ordered = rows.map(tr => (renderPlaylistPage._lastVisible || [])[+tr.dataset.i]).filter(Boolean);
  const keys = ordered.map(ethTrackKey);
  const cc = (state.ethCustom[group] = state.ethCustom[group] || {});
  cc.trackPinned = (cc.trackPinned || []).filter(k => keys.includes(k));
  cc.trackOrder = keys.filter(k => !(cc.trackPinned || []).includes(k));
  store.set('cm_ethnic_custom', state.ethCustom);
  const toDict = k => { const [a, b, c] = k.split('\u001f'); return { song_name: a || '', singers: b || '', source: c || '' }; };
  try {
    await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group, action: 'save_track_order', keys: keys.map(toDict), pinned: (cc.trackPinned || []).map(toDict), editor: ethEditor() }) });
  } catch (e) { toast('服务端同步失败，仅本机生效', true); }
}
function removeTrackFromPlaylist(ctx, it){
  /* 我的歌单: 真删除; 其他歌单: 本地隐藏(可恢复) */
  if (ctx.myId) {
    const p = state.myPlaylists.find(x => String(x.id) === String(ctx.myId));
    if (!p) return;
    const key = trackKeyOf(it);
    p.tracks = p.tracks.filter(t => trackKeyOf(t) !== key);
    store.set('cm_my_playlists', state.myPlaylists); renderMyPlaylists();
    toast(`已从「${p.name}」移除《${it.song_name}》`);
    renderPlaylistPage();
  } else {
    const key = ctx.plKey;
    if (!key) return;
    const tk = trackKeyOf(it);
    (state.plRemoved[key] = state.plRemoved[key] || []).push(tk);
    store.set('cm_pl_removed', state.plRemoved);
    toast(`已从歌单移除《${it.song_name}》`);
    renderPlaylistPage();
    /* 民族歌单: 服务端同步删除(所有协作者可见); 平台歌单维持本地隐藏 */
    if (key.startsWith('ethnos:')) {
      /* 必须带歌手与音源一起传: 后端按 (歌名+歌手+音源) 复合键定位,
         只传歌名会把同名不同歌手的曲目一次性全删(景颇族《目瑙纵歌》实测一次误删 24 条) */
      api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group: key.slice(7), action: 'remove_track', tname: it.song_name, tsingers: it.singers || '', tsource: it.source || '', editor: ethEditor() }) })
        .then(() => syncAfterEdit(false))
        .catch(() => toast('服务端删除失败，仅本机隐藏', true));
    }
  }
}
function restorePlaylistTracks(key){
  delete state.plRemoved[key];
  store.set('cm_pl_removed', state.plRemoved);
  renderPlaylistPage();
}
/* 最近播放 */
function pushHistory(t){
  if (!t || !t.name) return;
  if (state.history.length && state.history[0].name === t.name && state.history[0].artist === (t.artist || '')) return;
  state.history.unshift({ name: t.name, artist: t.artist || '', album: t.album || '', cover: t.cover || '', duration: t.duration || '', sid: t.sid, id: t.id, source: t.source || '', source_cn: t.source_cn || '', localUrl: t.localUrl || '', at: Date.now() });
  if (state.history.length > 500) state.history.length = 500;
  store.set('cm_history', state.history);
  if (currentPage === 'history') renderHistory();
}
function renderHistory(){
  const groups = [];
  const items = state.history.filter(h => h && typeof h === 'object' && h.name).map(h => ({ song_name: h.name, singers: h.artist, album: h.album, cover_url: h.cover, duration: h.duration, sid: h.sid, id: h.id, source: h.source || 'Hist', source_cn: h.source_cn || '历史', localUrl: h.localUrl, _at: h.at }));
  items.forEach(h => {
    const d = new Date(h._at || Date.now());
    if (isNaN(d)) { if (!groups.length || groups[groups.length - 1].label !== '更早') groups.push({ label: '更早', start: groups.length, count: 0 }); groups[groups.length - 1].count++; return; }
    const today = new Date(), yest = new Date(Date.now() - 86400000);
    const label = d.toDateString() === today.toDateString() ? '今天' : (d.toDateString() === yest.toDateString() ? '昨天' : d.toLocaleDateString('zh-CN'));
    if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, start: groups.length });
    groups[groups.length - 1].count = (groups[groups.length - 1].count || 0) + 1;
  });
  $('#hist-sub').textContent = `共 ${items.length} 条记录`;
  let html = '', cursor = 0;
  groups.forEach(g => {
    html += `<tr><td colspan="7" style="padding:14px 10px 4px;color:var(--txt3);font-size:12px;border-bottom:none;background:none">${esc(g.label)}</td></tr>`;
    html += items.slice(cursor, cursor + g.count).map((h, i) => songRow(h, cursor + i, { sid: h.sid })).join('');
    cursor += g.count;
  });
  $('#history-tbody').innerHTML = html || `<tr><td colspan="7"><div class="empty"><svg><use href="#i-clock"/></svg><div>暂无播放记录</div></div></td></tr>`;
  bindSongRows($('#history-tbody'), items, {});
}
$('#hist-clear').onclick = () => { if (!confirm('清空全部播放记录？')) return; state.history = []; store.set('cm_history', []); renderHistory(); };

