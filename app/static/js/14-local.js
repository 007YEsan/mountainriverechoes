/* ================================================================
 * 本地音乐：扫描、渲染、播放与打开目录
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 本地音乐 */
function playLocal(path, list){
  const mk = p => {
    const stem = decodeURIComponent(p).split('/').pop().replace(/\.[^.]+$/, '');
    const parts = stem.split(' - ').map(x => x.trim()).filter(Boolean);
    return { name: parts[0] || stem, artist: parts[1] || '本地音乐', localUrl: '/files/' + p.split('/').map(x => encodeURIComponent(x)).join('/'), cover: '' };
  };
  if (list && list.length) { state.queue = list.map(mk); state.qidx = list.indexOf(path); }
  else { state.queue.push(mk(path)); state.qidx = state.queue.length - 1; }
  if (state.qidx < 0) state.qidx = 0;
  loadCurrent();
}
async function loadLocal(){
  try {
    const d = await api('/api/files');
    state.files = d.files;
    const audioFiles = d.files.filter(f => f.playable);
    const totalMB = d.files.reduce((a, f) => a + (parseFloat(f.size) || 0), 0);
    $('#local-sub').textContent = `${audioFiles.length} 首可播放 · 共 ${d.files.length} 个文件`;
    renderLocal();
  } catch(err){ toast(err.message, true); }
}
function renderLocal(){
  const q = ($('#local-filter').value || '').toLowerCase();
  const files = (state.files || []).filter(f => f.playable && (!q || (f.name + f.file).toLowerCase().includes(q)));
  const list = files.map(f => f.path);
  $('#local-tbody').innerHTML = files.map((f, i) => `<tr data-p="${esc(f.path)}">
    <td class="td-index"><span class="num">${String(i + 1).padStart(2, '0')}</span><span class="pbtn"><svg class="ic sm fill"><use href="#i-play"/></svg></span></td>
    <td class="td-name"><div class="inner"><span class="t">${esc(f.name)}</span>${LOSSLESS.has(f.ext) ? '<span class="qbadge sq">SQ</span>' : ''}</div></td>
    <td class="td-singer">本地</td>
    <td><span class="srctag" style="background:${srcColor('Local') || '#9aa0a6'}">${esc(f.ext)}</span></td>
    <td class="td-time">${esc(f.size)}</td><td class="td-time">${esc(f.mtime)}</td>
    <td class="td-act"><button class="a-pl" title="加入歌单"><svg class="ic sm"><use href="#i-folder"/></svg></button><button class="a-del" title="删除"><svg class="ic sm"><use href="#i-trash"/></svg></button><button class="a-dir" title="所在目录"><svg class="ic sm"><use href="#i-extern"/></svg></button></td></tr>`).join('');
  $$('#local-tbody tr').forEach(tr => {
    tr.querySelector('.pbtn').onclick = e => { e.stopPropagation(); playLocal(tr.dataset.p, list); };
    tr.onclick = () => tr.querySelector('.pbtn').click();
    const localTrack = { name: tr.querySelector('.td-name .t').textContent, artist: '本地音乐' };
    const apl = tr.querySelector('.a-pl'); if (apl) apl.onclick = e => { e.stopPropagation(); openAddToPlaylist({ ...localTrack, localUrl: '/files/' + tr.dataset.p.split('/').map(x => encodeURIComponent(x)).join('/'), source: 'Local', source_cn: '本地' }); };
    tr.querySelector('.a-del').onclick = async e => { e.stopPropagation(); if (!confirm('删除文件 ' + tr.dataset.p + ' ?')) return; await api('/api/file/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: tr.dataset.p }) }); toast('已删除'); loadLocal(); };
    tr.querySelector('.a-dir').onclick = e => { e.stopPropagation(); api('/api/open_folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: tr.dataset.p }) }); };
  });
}
$('#local-filter').addEventListener('input', renderLocal);
$('#local-open').onclick = () => api('/api/open_folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
$('#local-playall').onclick = () => { const files = (state.files || []).filter(f => f.playable); if (!files.length) return toast('本地没有可播放文件'); playLocal(files[0].path, files.map(f => f.path)); };

