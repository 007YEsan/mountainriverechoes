/* ================================================================
 * 下载任务管理：轮询与列表渲染
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 下载管理 */
let dlFilter = 'all', taskTimer = null;
function pollTasks(){
  clearTimeout(taskTimer);
  const tick = async () => {
    try {
      const d = await api('/api/tasks');
      state.tasks = d.tasks;
      if (currentPage === 'downloads') renderDownloads();
      if (d.active) taskTimer = setTimeout(tick, 2000);
    } catch(err){}
  };
  tick();
}
function renderDownloads(){
  const list = (state.tasks || []);
  const n = { all: list.length, downloading: 0, done: 0, failed: 0 };
  list.forEach(t => { if (t.status === 'done') n.done++; else if (t.status === 'failed') n.failed++; else n.downloading++; });
  $('#dl-sub').textContent = list.length ? `${n.done} 已完成 · ${n.downloading} 进行中 · ${n.failed} 失败` : '';
  const labels = { all: '全部', downloading: '进行中', done: '已完成', failed: '失败' };
  $$('#dl-chips .chip').forEach(c => { const f = c.dataset.f; c.classList.toggle('on', dlFilter === f); c.textContent = `${labels[f]} (${n[f] || 0})`; });
  const rows = list.filter(t => dlFilter === 'all' || (dlFilter === 'downloading' ? (t.status === 'queued' || t.status === 'downloading') : t.status === dlFilter));
  const icon = { queued: ['⏳', 'queued'], downloading: ['⬇', 'downloading'], done: ['✓', 'done'], failed: ['✕', 'failed'] };
  $('#dl-list').innerHTML = rows.map(t => `<div class="dl-row">
    <span class="dl-status ${icon[t.status][1]}">${t.status === 'downloading' ? '<span class="spin" style="width:13px;height:13px;border-width:2px"></span>' : icon[t.status][0]}</span>
    <div class="dl-main"><div class="nm">${esc(t.name)}</div><div class="sub">${esc(t.singer || '')} · ${esc(t.source)} ${t.ext ? '· ' + esc(t.ext) : ''} ${t.file_size ? '· ' + esc(t.file_size) : ''}${t.error ? ' · <span style="color:#e04b4b">' + esc(t.error) + '</span>' : ''}</div></div>
    <span class="dl-time">${t.finished_at ? new Date(t.finished_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''}</span>
    ${t.status === 'done' && t.file ? `<button class="btn btn-plain btn-sm" data-play="${esc(t.file)}">播放</button>` : ''}
    <button class="btn btn-plain btn-sm" data-dir="${t.file ? esc(t.file) : ''}">目录</button>
  </div>`).join('') || `<div class="empty"><svg><use href="#i-download"/></svg><div>暂无下载任务</div></div>`;
  $$('#dl-list [data-play]').forEach(b => b.onclick = () => playLocal(b.dataset.play));
  $$('#dl-list [data-dir]').forEach(b => b.onclick = () => api('/api/open_folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: b.dataset.dir }) }).catch(e => toast(e.message, true)));
}
$$('#dl-chips .chip').forEach(c => c.onclick = () => { dlFilter = c.dataset.f; renderDownloads(); });
$('#dl-clear').onclick = async () => { await api('/api/tasks/clear', { method: 'POST' }); pollTasks(); };

