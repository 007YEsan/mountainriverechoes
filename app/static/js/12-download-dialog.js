/* ================================================================
 * 多音源下载对话框：候选搜索、轮询、提交下载，以及遮罩与关闭按钮绑定
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 多音源下载对话框 */
const msState = { track: null, cands: [], sel: new Set(), job: null, timer: null };
function openMsDialog(track){
  msState.track = track; msState.cands = []; msState.sel = new Set(); msState.job = null;
  $('#ms-name').textContent = `${track.name} - ${track.artist || ''}`;
  $('#ms-sub').textContent = `在 ${state.cfg.length} 个音源中搜索全部可用版本`;
  $('#ms-body').innerHTML = `<div class="empty" style="padding:30px 0"><span class="spin" style="width:22px;height:22px"></span><div style="margin-top:12px">正在各音源搜索该歌曲...</div></div>`;
  $('#dlg-ms').classList.add('show');
  if (track.versions && track.versions.length) msState.cands = track.versions.map(v => ({ ...v, sid: track.ctxSid || track.sid }));
  msSearch();
  renderMs();
}
function msSearch(){
  const t = msState.track;
  clearTimeout(msState.timer);
  api('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keyword: `${t.name} ${t.artist || ''}`.trim(), sources: state.cfg }) })
    .then(d => { msState.job = d; msPoll(); })
    .catch(err => { $('#ms-body').innerHTML = `<div class="empty">搜索失败: ${esc(err.message)}</div>`; });
}
async function msPoll(){
  if (!msState.job || !$('#dlg-ms').classList.contains('show')) return;
  try {
    const st = await api('/api/search/status?job=' + msState.job.job_id);
    /* 合并新候选 */
    const known = new Set(msState.cands.map(c => c.sid + '/' + c.id));
    st.groups.forEach(g => g.items.forEach(it => {
      const key = st.sid + '/' + it.id;
      if (known.has(key)) return;
      const tn = norm(msState.track.name);
      const cn = norm(it.song_name);
      if (!(cn.includes(tn) || tn.includes(cn))) return;
      msState.cands.push({ ...it, sid: st.sid });
    }));
    msState.groups = st.groups; msState.finished = st.finished;
    if (!msState.cands.length && !msState.finished) { msState.timer = setTimeout(msPoll, 900); }
    renderMs();
    if (!msState.finished && !msState.cands.length) return;
    /* 已有候选即可停止轮询 */
  } catch(err){}
}
function renderMs(){
  const groups = msState.groups || [];
  $('#ms-progress').innerHTML = groups.map(g => `<span class="src-pill ${g.done ? (g.items.length ? 'ok' : 'zero') : ''}">${g.done ? (g.items.length ? '✓' : '✕') : '<span class="spin"></span>'}${esc(g.source_cn)} ${g.items.length}</span>`).join('');
  const best = msBest();
  $('#ms-body').innerHTML = msState.cands.length ? msState.cands.map((c, i) => {
    const key = c.sid + '/' + c.id;
    const isBest = best && best.sid + '/' + best.id === key;
    return `<div class="ms-row ${msState.sel.has(key) ? 'sel' : ''}" data-i="${i}">
      <span class="cb"><svg class="fill"><use href="#i-check"/></svg></span>
      <span class="nm">${esc(c.song_name)}${c.ext ? `<span class="qbadge ${LOSSLESS.has(c.ext) ? 'sq' : 'hq'}" style="margin-left:6px">${esc(c.ext)}</span>` : ''}${isBest ? '<span class="best-flag" style="margin-left:6px">最优</span>' : ''}<small>${esc(c.singers || '')}</small></span>
      <span class="meta">${esc(c.file_size || '')}<span>${esc(c.duration || '')}</span><span class="srctag" style="background:${srcColor(c.source)}">${esc(c.source_cn || c.source)}</span></span>
    </div>`;
  }).join('') : (msState.finished ? `<div class="empty">各音源均未找到该歌曲的可用版本</div>` : `<div class="empty"><span class="spin" style="width:20px;height:20px"></span><div style="margin-top:10px">搜索中...</div></div>`);
  $$('#ms-body .ms-row').forEach(r => r.onclick = () => { const c = msState.cands[+r.dataset.i]; const key = c.sid + '/' + c.id; msState.sel.has(key) ? msState.sel.delete(key) : msState.sel.add(key); renderMs(); });
  $('#ms-dl').textContent = `下载所选 (${msState.sel.size})`;
  $('#ms-dl').disabled = !msState.sel.size;
  $('#ms-best').disabled = !msState.cands.length;
}
function msBest(){
  const cands = msState.cands.filter(c => c.downloadable !== false);
  if (!cands.length) return null;
  return cands.sort((a, b) => scoreOf(b) - scoreOf(a))[0];
}
$('#ms-all').onclick = () => { if (msState.sel.size === msState.cands.length) msState.sel.clear(); else msState.cands.forEach(c => msState.sel.add(c.sid + '/' + c.id)); renderMs(); };
$('#ms-research').onclick = () => { msState.cands = []; msState.sel.clear(); msState.groups = []; renderMs(); msSearch(); };
$('#ms-best').onclick = () => { const b = msBest(); if (!b) return; submitDownload([b]); };
$('#ms-dl').onclick = () => { const picks = msState.cands.filter(c => msState.sel.has(c.sid + '/' + c.id)); submitDownload(picks); };
async function submitDownload(picks){
  if (!picks.length) return;
  /* 按sid分组提交 */
  const bySid = {};
  picks.forEach(p => { (bySid[p.sid] = bySid[p.sid] || []).push(p.id); });
  let n = 0;
  for (const sid of Object.keys(bySid)) {
    try { await api('/api/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sid, picks: bySid[sid] }) }); n += bySid[sid].length; } catch(err){ toast(err.message, true); }
  }
  toast(`已开始下载 ${n} 个文件，可到"下载管理"查看`);
  $('#dlg-ms').classList.remove('show');
  renderDownloads(); pollTasks();
}
$$('.dlg-close').forEach(b => b.onclick = () => $('#' + b.dataset.close).classList.remove('show'));
$$('.overlay').forEach(o => o.addEventListener('mousedown', e => { if (e.target === o) o.classList.remove('show'); }));

