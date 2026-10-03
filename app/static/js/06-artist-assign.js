/* ================================================================
 * “添加到歌手”弹窗：模糊匹配定位歌手并提交写入民族库
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================== 添加到歌手(模糊搜索定位) */
let _asTrack = null, _asCtx = null, _asArtistList = null;
function _asFuzzy(q, list){
  /* 评分: 全等 > 前缀 > 子串 > 子序列(跳字匹配, 支持"阿乌"命中"曲比阿乌"); 同级按曲目数降序 */
  const nq = norm(q);
  if (!nq) return list.slice(0, 40);
  const out = [];
  for (const a of list) {
    const nm = norm(a.name);
    let sc = 0;
    if (nm === nq) sc = 1000;
    else if (nm.startsWith(nq)) sc = 900 - nm.length;
    else if (nm.includes(nq)) sc = 700 - nm.indexOf(nq);
    else {
      let i = 0;                       /* 子序列匹配 */
      for (const ch of nm) { if (ch === nq[i]) i++; if (i >= nq.length) break; }
      if (i >= nq.length) sc = 400 - (nm.length - nq.length);
    }
    if (sc > 0) out.push({ a, sc, c: a.count || 0 });
  }
  out.sort((x, y) => (y.sc - x.sc) || (y.c - x.c));
  return out.slice(0, 40).map(x => x.a);
}
async function _ensureArtists(){
  if (_asArtistList) return _asArtistList;
  if (!state.index.data) { try { await loadIndex(true); } catch(e){} }
  const raw = ((state.index.data || {}).artists) || [];
  const m = new Map();
  for (const a of raw) {
    const cur = m.get(a.name);
    if (!cur) m.set(a.name, { name: a.name, group: a.group, count: a.count || 0, cover: a.cover || '' });
    else { cur.count += (a.count || 0); if (!cur.cover && a.cover) cur.cover = a.cover; }
  }
  _asArtistList = [...m.values()];
  return _asArtistList;
}
async function openArtistAssign(it, ctx, track){
  _asTrack = it; _asCtx = ctx || {};
  $('#as-sub').textContent = `《${it.song_name || it.name}》 · 当前歌手：${it.singers || it.artist || '未知'}`;
  $('#as-q').value = it.singers ? String(it.singers).split('/')[0] : '';
  await _ensureArtists();
  $('#dlg-artist').classList.add('show');
  setTimeout(() => { $('#as-q').focus(); $('#as-q').select(); }, 60);
  _asRender();
}
function _asRender(){
  const q = ($('#as-q').value || '').trim();
  const list = _asArtistList || [];
  const hits = _asFuzzy(q, list);
  const ctxG = _asCtx.ethGroup || '';
  const ethOpts = [...(state.ethnos.groups || []).map(g => ({ k: g.key, n: g.name })), { k: 'han', n: '汉族' }];
  const exact = q && list.some(a => a.name === q);
  const rows = [];
  if (q && !exact) {
    /* 新建行: 与可点选行分离 —— 下拉不再是「点一下就提交」的陷阱, 必须先选民族再点按钮 */
    const opts = ['<option value="">请选择民族…</option>'].concat(
      ethOpts.map(o => `<option value="${esc(o.k)}"${o.k === ctxG ? ' selected' : ''}>${esc(o.n)}</option>`));
    rows.push(`<div class="as-newrow">
      <div class="as-newtitle">新建歌手「${esc(q)}」 · 归属民族</div>
      <div class="as-newbar">
        <select id="as-newg" class="filter-input">${opts.join('')}</select>
        <button class="btn btn-primary btn-sm" id="as-newok" disabled>创建并加入</button>
      </div></div>`);
  }
  rows.push(...hits.map(a => `<div class="p" data-an="${esc(a.name)}" data-ag="${esc(a.group)}" data-c="${a.count}">${esc(a.name)}<span style="color:var(--txt3);font-size:11.5px;margin-left:8px">${esc(a.group)} · ${a.count} 首</span>${a.name === q ? '<span style="color:var(--green);font-size:11px;margin-left:6px">已存在</span>' : ''}</div>`));
  $('#as-list').innerHTML = rows.join('') || '<div style="color:var(--txt3);font-size:12.5px">没有匹配的歌手，直接输入新名字可新建</div>';
  $('#as-tip').innerHTML = q ? `匹配 ${hits.length} 位（点击即可把这首歌加到该歌手名下）` : `共 ${list.length} 位歌手 · 输入关键字快速定位`;
  $$('#as-list .p[data-an]').forEach(el => el.onclick = async () => { await _asCommit(el.dataset.an, el.dataset.ag); });
  const _nsel = $('#as-newg'), _nok = $('#as-newok');
  if (_nsel && _nok) {
    /* 下拉的默认值是占位空项: 没显式选民族时按钮禁用, 从根上杜绝误选首个民族 */
    _nok.disabled = !_nsel.value;      /* 初始态与预选民族一致: 已预选当前库就不必再动下拉 */
    _nsel.addEventListener('change', () => { _nok.disabled = !_nsel.value; });
    ['click', 'mousedown', 'mouseup', 'pointerdown'].forEach(ev =>
      _nsel.addEventListener(ev, e => e.stopPropagation()));
    _nok.onclick = async e => {
      e.stopPropagation();
      if (!_nsel.value) return toast('请先选择归属民族', true);
      await _asCommit(q, _nsel.value);
    };
  }
}
async function _asCommit(artist, groupKey){
  const it = _asTrack, ctx = _asCtx || {};
  if (!artist) return;
  /* 搜索结果按民族「名」传参, 后端要民族 key(eNN/han): 这里统一归一, 已是 key 的原样透传 */
  const gkOf = nm => {
    if (!nm) return '';
    if (/^e\d{2}$/.test(nm) || nm === 'han') return nm;
    const g = (state.ethnos.groups || []).find(x => x.name === nm);
    return g ? g.key : (nm === '汉族' || nm === '汉族民间小调' ? 'han' : '');
  };
  const targetKey = gkOf(groupKey);
  if (!targetKey) return toast('无法确定目标民族（' + (groupKey || '未知') + '）', true);
  const curKey = ctx.ethGroup || '';
  const sameLib = curKey && (targetKey === curKey);
  try {
    if (sameLib) {
      /* 同库内: 直接改归属(不复制) */
      await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: curKey, action: 'reassign_singer', tname: it.song_name, tsingers: it.singers || '', tsource: it.source || '', new_singers: artist, editor: ethEditor() }) });
      toast(`已把《${it.song_name}》归到「${artist}」`);
      state.index.data = null;
      if (currentDetail) openPlaylistDetail(currentDetail.id, currentDetail.name, currentDetail.platform);
    } else {
      /* 跨库/来源歌曲: 复制进目标民族库、挂在目标歌手名下 */
      const sid = (ctx && ctx.sid) || it.ctxSid || it.sid;
      if (!sid || !it.id) throw new Error('该曲目不在可写会话里（请从搜索结果或民族歌单里操作）');
      const j = await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: 'han', action: 'add_to_artist', dst: targetKey, artist, sid, tid: it.id, editor: ethEditor() }) });
      toast(`已加入「${artist}」名下（${j.dst_count} 首）`);
      state.index.data = null;
      if (ctx.ethGroup) renderPlaylistPage();
    }
    /* 本地也解禁: 上次"移除歌手"若留在 localStorage, 前端仍会过滤掉这位歌手 */
    const cc = (state.ethCustom[targetKey] = state.ethCustom[targetKey] || {});
    if ((cc.removed || []).includes(artist)) { cc.removed = cc.removed.filter(x => x !== artist); store.set('cm_ethnic_custom', state.ethCustom); }
    if (!(cc.added || []).includes(artist)) { cc.added = [...(cc.added || []), artist]; store.set('cm_ethnic_custom', state.ethCustom); }
    state.ethSynced = {};   /* 下次进民族页重新拉歌手清单 */
    state.index.data = null; /* 让索引重算, 新歌手立刻可检索 */
    $('#dlg-artist').classList.remove('show');
  } catch (err) { toast(err.message || '操作失败', true); }
}
(function(){
  const el = $('#as-q');
  if (el) el.addEventListener('input', () => _asRender());
  document.addEventListener('click', e => { if (e.target.closest('[data-close="dlg-artist"]')) $('#dlg-artist').classList.remove('show'); });
  if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') { const first = $('#as-list .p'); if (first) first.click(); } });
})();

