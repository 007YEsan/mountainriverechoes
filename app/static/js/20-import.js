/* ================================================================
 * 导入歌单：链接导入与文本导入
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 导入歌单 */
$('#nav-import').onclick = () => $('#dlg-imp').classList.add('show');
$('#pl-go').onclick = () => { const v = $('#pl-url').value.trim(); if (v) importPlaylist(v); };
$('#imp-go').onclick = () => { const v = $('#imp-url').value.trim(); if (v) importPlaylist(v); };
$('#imp-txt-go').onclick = () => importText();
async function importText(){
  const text = $('#imp-text').value.trim();
  if (!text) { $('#imp-tip').textContent = '请先粘贴歌曲文本（每行"歌手 - 歌名"）'; return; }
  const nm = text.split('\n').length;
  $('#imp-tip').textContent = `文本导入中: ${nm} 行逐行搜索匹配(酷狗/酷我/咪咕), 每行约需数秒, 请勿关闭弹窗...`;
  try {
    const d = await api('/api/playlist/text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    state.playlistCache['musicdl:' + d.id] = { data: d, at: Date.now() };
    if (!state.imported.some(p => p.id === d.id)) {
      state.imported.unshift({ id: d.id, platform: 'musicdl', name: d.name, count: d.count });
      store.set('cm_imported', state.imported); renderImported();
    }
    $('#dlg-imp').classList.remove('show'); $('#imp-tip').textContent = ''; $('#imp-text').value = '';
    const miss = d.unmatched || [];
    toast(`已导入「${d.name}」${d.count}/${d.total_lines} 首${miss.length ? `, ${miss.length} 首未匹配` : ''}`);
    if (miss.length) setTimeout(() => toast('未匹配: ' + miss.slice(0, 5).join('; ') + (miss.length > 5 ? ' 等' : ''), true), 900);
    nav('playlist', { id: d.id, platform: 'musicdl', name: d.name });
  } catch(err){ $('#imp-tip').innerHTML = `<span style="color:#e04b4b">${esc(err.message)}</span>`; }
}
$('#imp-url').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.value.trim()) importPlaylist(e.target.value.trim()); });
async function importPlaylist(url){
  $('#imp-tip').textContent = '解析中，网易云 / QQ音乐 / 汽水音乐歌单几秒内完成，酷狗/酷我走逐首解析较慢...';
  try {
    const d = await api('/api/playlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
    state.playlistCache[(d.platform || 'netease') + ':' + d.id] = { data: d, at: Date.now() };
    if (!state.imported.some(p => p.id === d.id && p.platform === (d.platform || 'netease'))) {
      state.imported.unshift({ id: d.id, platform: d.platform || 'netease', name: d.name, count: d.count });
      store.set('cm_imported', state.imported); renderImported();
    }
    $('#dlg-imp').classList.remove('show'); $('#imp-tip').textContent = '';
    toast(`已导入「${d.name}」(${d.count}首)`);
    nav('playlist', { id: d.id, platform: d.platform || 'netease', name: d.name });
  } catch(err){ $('#imp-tip').innerHTML = `<span style="color:#e04b4b">${esc(err.message)}</span>`; }
}
function renderImported(){
  $('#custom-playlists').innerHTML = state.imported.map((p, i) => `<div class="nav-item" data-pl="${esc(p.id)}" data-pk="${esc(p.platform || 'netease')}" data-nm="${esc(p.name)}"><svg class="ic"><use href="#i-list"/></svg><span class="grow">${esc(p.name)}</span><button class="rm" title="移除导入记录" data-rm="${i}" style="display:none;position:absolute;right:8px;color:var(--txt3);padding:2px"><svg class="ic sm"><use href="#i-x"/></svg></button></div>`).join('');
  $$('#custom-playlists .nav-item').forEach(el => {
    el.onclick = () => nav('playlist', { id: el.dataset.pl, platform: el.dataset.pk, name: el.dataset.nm });
    el.onmouseenter = () => { const b = el.querySelector('.rm'); if (b) b.style.display = 'block'; };
    el.onmouseleave = () => { const b = el.querySelector('.rm'); if (b) b.style.display = 'none'; };
    const rm = el.querySelector('.rm');
    if (rm) rm.onclick = e => {
      e.stopPropagation();
      const idx = +rm.dataset.rm, p = state.imported[idx];
      if (!p || !confirm(`从侧栏移除「${p.name}」？(不影响已下载文件)`)) return;
      state.imported.splice(idx, 1); store.set('cm_imported', state.imported); renderImported(); toast('已移除');
    };
  });
}
renderImported();

