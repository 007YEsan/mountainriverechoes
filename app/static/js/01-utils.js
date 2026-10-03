/* ================================================================
 * 工具层：$ / $$ 选择器、时间格式化、文本归一化与转义、uid、toast、api() 请求封装、localStorage store、UI 态服务端同步、民族库协作编辑、拖拽排序、音源配色与无损格式常量
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 工具 */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const audio = $('#audio');
const fmtTime = s => { if (!isFinite(s) || s < 0) s = 0; s = Math.round(s); return String(Math.floor(s/60)).padStart(2,'0') + ':' + String(s%60).padStart(2,'0'); };
const norm = s => (s||'').toLowerCase().replace(/[\s\-—－·・,，.。'"''`~～!！?？:：;；()（）\[\]【】{}<>《》&^%$#@*+=|\\/]/g, '');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => Math.random().toString(36).slice(2, 10);
function toast(msg, err){ const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg; $('#toasts').appendChild(t); setTimeout(() => { t.style.opacity = 0; t.style.transition = 'opacity .3s'; setTimeout(() => t.remove(), 320); }, err ? 3600 : 2400); }
async function api(url, opts){ const r = await fetch(url, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || ('请求失败 ' + r.status)); return d; }
/* 常驻服务端的 UI 态白名单: 拖动次序/我的歌单/隐藏曲目/民族歌手增删名单/音源配置。
   这些原先只落在 localStorage —— 清缓存或换浏览器就回到出厂样子, 现在同步到服务端 webui/ui_state.json。 */
const UI_SYNC_KEYS = ['cm_order_ethcards', 'cm_my_playlists', 'cm_pl_removed', 'cm_ethnic_custom', 'cm_cfg_v5'];
const isSyncKey = k => UI_SYNC_KEYS.includes(k) || /^cm_order_ethrows_/.test(k);
/* 56 民族卡片默认次序(2026-10-03 由用户自定义固化): 本机无 cm_order_ethcards 时按此排序 */
const ETHCARD_ORDER_DEFAULT = ['傈僳族','景颇族','佤族','藏族','高山族','傣族','哈尼族','彝族','维吾尔族','蒙古族','壮族','汉族民间小调','苗族','回族','哈萨克族','朝鲜族','拉祜族','黎族','侗族','俄罗斯族','纳西族','满族','白族','土家族','瑶族','畲族','塔吉克族','阿昌族','羌族','普米族','布依族','柯尔克孜族','布朗族','达斡尔族','仫佬族','东乡族','赫哲族','水族','乌孜别克族','裕固族','仡佬族','锡伯族','门巴族','塔塔尔族','鄂温克族','鄂伦春族','怒族','保安族','土族','撒拉族','毛南族','德昂族','独龙族','京族','基诺族','珞巴族'];
const store = {
  get(k, d){ try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch(e){ return d; } },
  set(k, v){
    localStorage.setItem(k, JSON.stringify(v));
    try { if (isSyncKey(k)) localStorage.setItem('__ts_' + k, String(Date.now())); } catch(e){}
    uiSyncPush(k, v);
  },
  ts(k){ try { return +localStorage.getItem('__ts_' + k) || 0; } catch(e){ return 0; } }
};
/* 服务端同步: 本地立即生效, 服务端防抖补写 */
let _uiBuf = {}, _uiTimer = null;
function uiSyncPush(k, v){
  _uiBuf[k] = v;
  clearTimeout(_uiTimer);
  _uiTimer = setTimeout(async () => {
    const d = _uiBuf, t = {}; for (const key of Object.keys(d)) t[key] = store.ts(key);
    _uiBuf = {};
    try { await api('/api/ui/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ d, t }) }); }
    catch(e){ /* 服务端不可达时静默降级为纯 localStorage */ }
  }, 500);
}
/* 启动时以服务端为准做一次对齐: 谁的时间戳新听谁的(跨设备/清缓存后能自动找回上次的样子) */
async function uiStateBootstrap(){
  let remote;
  try { remote = await api('/api/ui/state'); } catch(e){ return; }
  const rv = (remote && remote.v) || {}, rt = (remote && remote.t) || {};
  /* 时间戳有效性: 未来时间戳(如被误写的哨兵值)与非法值一律视为 0(无效)。
     否则本机时间戳永远追不上那个未来值 → 该键每次刷新都被服务端那份冻结旧值覆盖,
     再叠加服务端「新者胜」判定, 会形成"本机怎么改都改不动、刷新必定回滚"的死循环。 */
  const tsOk = x => { const n = +x || 0; return n > 0 && n < Date.now() + 86400000 ? n : 0; };
  let changed = false;
  for (const k of Object.keys(rv)) {
    if (!isSyncKey(k)) continue;
    const raw = localStorage.getItem(k), have = raw !== null;
    const lt = tsOk(store.ts(k)), time = tsOk(rt[k]);
    /* lt >= time 即视为「本地不旧」-> 保持本地(稍后由 uiSyncPush 补写)。
       用 >= 而非 >: 刚同步完两边时间戳必然相等, 若按 > 判断, 每次刷新都会把服务端那份
       原样重写一遍并弹一次「已从服务端恢复」—— 明明什么都没恢复。 */
    if (have && lt && lt >= time) continue;
    let same = false;
    if (have) { try { same = JSON.stringify(JSON.parse(raw)) === JSON.stringify(rv[k]); } catch(e){} }
    try {
      if (!same) { localStorage.setItem(k, JSON.stringify(rv[k])); changed = true; }   // 值真变了才算「恢复」
      if (time) localStorage.setItem('__ts_' + k, String(time));
      else localStorage.removeItem('__ts_' + k);                                      // 服务端时间戳不可信 -> 本机也不留
    } catch(e){}
  }
  /* 服务端还没有但本机有的: 反向迁移上去(首次升级 / 全新服务端的场景) */
  const miss = {};
  for (const k of isSyncKeyList()) {
    if (k in rv) continue;
    try { const raw = localStorage.getItem(k); if (raw !== null) miss[k] = JSON.parse(raw); } catch(e){}
  }
  if (Object.keys(miss).length) {
    const mt = {}; for (const k of Object.keys(miss)) mt[k] = Date.now();   /* 本机写入用毫秒, 与服务端口径一致 */
    try { await api('/api/ui/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ d: miss, t: mt }) }); } catch(e){}
  }
  if (!changed) return;
  /* state 是脚本加载时快照出来的, 这里把它重新对齐到刚下载的值, 然后重绘当前页 —
     不走 location.reload(): 那样会丢掉正在播放的曲子和未完成的滚动位置 */
  state.ethCustom = store.get('cm_ethnic_custom', {});
  state.myPlaylists = store.get('cm_my_playlists', []);
  state.plRemoved = store.get('cm_pl_removed', {});
  state.cfg = store.get('cm_cfg_v5', []) || [];
  try { renderMyPlaylists(); } catch(e){}
  try { if (currentPage === 'index') renderIndex(); } catch(e){}
  try { if (currentPage === 'playlist') renderPlaylistPage(); } catch(e){}
  toast('已从服务端恢复上次的排序与编辑');
}
function isSyncKeyList(){
  const out = [...UI_SYNC_KEYS];
  try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && /^cm_order_ethrows_/.test(k)) out.push(k); } } catch(e){}
  return out;
}
/* 民族歌单协作编辑: 身份标识 + 服务端同步(/api/ethnos/edit), localStorage 兜底 */
function ethEditor(){ let e = store.get('cm_editor'); if (!e) { e = 'user-' + Math.random().toString(36).slice(2, 6); store.set('cm_editor', e); } return e; }
/* 汉族库的对外显示名统一叫「汉族」(底层 key 仍是 han / 文件名 han_汉族民间小调.json 不动),
   两个名字都要能解析到 han —— 索引页二级列表内部仍沿用 '汉族民间小调' 作为分组键。 */
function ethKeyOf(sel){ if (sel === '汉族民间小调' || sel === '汉族') return 'han'; const g = (state.ethnos.groups || []).find(x => x.name === sel); return g ? g.key : ''; }
function ethEditPost(sel, body){
  const group = ethKeyOf(sel); if (!group) return Promise.resolve(null);
  return api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group, editor: ethEditor(), ...body }) });
}
/* 一级(跨族搜索结果)里置顶歌手时用: 把该民族的置顶/次序回写服务端。
   名单**以服务端既有 artist_order 为骨架**(不可用索引重建 —— 索引里没有的名字/合集会被挤掉),
   只把索引里新增的补在后面, 再让当前置顶段排最前。 */
async function ethSyncPinOrder(gname){
  const gk = ethKeyOf(gname) || ((gname === '汉族' || gname === '汉族民间小调') ? 'han' : '');
  if (!gk) return;
  const d = state.index.data || {};
  const cc = (state.ethCustom || {})[gname] || {};
  const singers = ((d.artists || []).filter(a => a.group === gname)).map(a => a.name);
  const colls = ((d.playlists || []).filter(p => p.kind === 'YouTube合集' && p.group === gname)).map(p => p.name);
  let sv = {};
  try { sv = await api(`/api/ethnos/custom?group=${encodeURIComponent(gk)}`) || {}; } catch(e){}
  const all = [...new Set([...(sv.artist_order || []), ...singers, ...colls, ...(cc.added || [])])];
  const src = (cc.pinned !== undefined) ? cc.pinned : (sv.artists_pinned || []);
  const pinned = [...new Set(src)].filter(n => all.includes(n));
  const names = [...pinned, ...all.filter(n => !pinned.includes(n))];
  try { await ethEditPost(gname, { action: 'save_artist_order', names, pinned }); }
  catch (e) { toast('服务端同步失败，仅本机生效', true); }
}
/* 歌手卡/合集卡「移动至」: 弹民族库下拉, 选中后把该条目名下曲目整体搬到目标民族库。
   带出 anchor(按钮) 定位, srcName 为来源民族名。isColl=true 表示移动的是「合集」而非歌手:
   选曲口径换成 album 相等(后端 move_collection), 其余流程完全一致 —— 合集与歌手同权。 */
function openMoveMenu(anchor, name, srcName, isColl){
  document.querySelectorAll('.move-menu').forEach(m => m.remove());
  const what = isColl ? '合集' : '歌手';
  const srcKey = ethKeyOf(srcName);
  const items = [];
  (state.ethnos.groups || []).forEach(g => {
    if (g.name === srcName || g.key === srcKey || g.state !== 'done') return;
    items.push({ key: g.key, name: g.name, count: g.count || 0 });
  });
  if (srcName !== '汉族民间小调' && srcName !== '汉族') items.push({ key: 'han', name: '汉族', count: (state.hanInfo && state.hanInfo.count) || 0 });
  items.sort((a, b) => b.count - a.count);
  const menu = document.createElement('div');
  menu.className = 'move-menu';
  menu.innerHTML = `<div class="mm-hd">移动${what}「${esc(name)}」到…</div>
    <div class="mm-list">${items.map(it => `<div class="mm-i" data-k="${esc(it.key)}" data-n="${esc(it.name)}">${esc(it.name)}<span>${it.count}首</span></div>`).join('') || '<div class="mm-empty">暂无可选目标库</div>'}</div>`;
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect(), w = 210;
  menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  menu.style.top = Math.min(r.bottom + 6, window.innerHeight - (menu.offsetHeight || 320) - 8) + 'px';
  const close = () => menu.remove();
  setTimeout(() => document.addEventListener('click', close, { once: true }), 0);
  menu.addEventListener('click', ev => ev.stopPropagation());
  menu.querySelectorAll('.mm-i').forEach(el => el.onclick = async () => {
    const dstKey = el.dataset.k, dstName = el.dataset.n;
    close();
    if (!confirm(`把${what}「${name}」的曲目全部移动到「${dstName}」？\n源库将不再显示该${what}。`)) return;
    try {
      const j = await ethEditPost(srcName, { action: isColl ? 'move_collection' : 'move_artist', name, dst: dstKey });
      toast(`已移动${what}「${name}」${(j && j.moved != null) ? j.moved : ''} 首到「${dstName}」`);
      if (!isColl) {
        // 歌手: 本机名单同步隐藏, 免得目标库还没刷新完就在源库重复出现
        const custom = state.ethCustom || {};
        const cc = (custom[srcName] = custom[srcName] || {});
        cc.removed = cc.removed || []; if (!cc.removed.includes(name)) cc.removed.push(name);
        cc.pinned = (cc.pinned || []).filter(x => x !== name);
        state.ethCustom = custom; store.set('cm_ethnic_custom', custom);
      }
      state.index.data = null; state.ethSynced = {};
      await loadIndex(true);
    } catch (err) {
      toast('移动失败: ' + ((err && err.message) || err), true);
    }
  });
}
/* 拖拽排序: 卡片/行拖动调整次序, 顺序持久化到 localStorage */
function applyOrder(arr, order, kFn = x => x){ if (!order || !order.length) return arr; const idx = new Map(order.map((n, i) => [n, i])); return [...arr].sort((a, b) => ((idx.get(kFn(a)) ?? 1e9) - (idx.get(kFn(b)) ?? 1e9))); }
function bindDragSort(container, itemSel, orderKey, kFn){
  if (!container || container._dragBound) return; container._dragBound = true;
  let dragEl = null;
  container.addEventListener('dragstart', e => { const it = e.target.closest(itemSel); if (!it || !it.draggable) return; dragEl = it; it.style.opacity = .35; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', ''); } catch(_){} });
  container.addEventListener('dragend', () => { if (!dragEl) return; dragEl.style.opacity = ''; dragEl = null; store.set(orderKey, [...container.querySelectorAll(itemSel)].map(kFn)); });
  container.addEventListener('dragover', e => {
    if (!dragEl) return; e.preventDefault();
    const over = e.target.closest(itemSel); if (!over || over === dragEl || over.parentElement !== dragEl.parentElement) return;
    const r = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragEl, (e.clientY - r.top) > r.height / 2 ? over.nextSibling : over);
  });
}
const SRC_COLORS = { Migu:'#ff7a00', Netease:'#d33a31', QQ:'#31c27c', Kuwo:'#00b7ff', Kugou:'#2ca7f8', Bilibili:'#fb7299', Soda:'#ff5252', Qianqian:'#8e7bff', Ximalaya:'#f86442', Playlist:'#ec4141', GDStudio:'#00c4a7', Apple:'#fa57c1', Spotify:'#1db954', YouTube:'#ff0000', SoundCloud:'#ff5500', TIDAL:'#111111', MyFreeMP3:'#7c5cff', TwoT58:'#00c2a8', XMFWAV:'#ff9f43', Gequhai:'#f06292', JBSou:'#5c6bc0', Yinyueku:'#26a69a', Sgogo:'#66bb6a', Weixin:'#07c160' };
const srcColor = k => SRC_COLORS[k] || '#9aa0a6';
const LOSSLESS = new Set(['FLAC','WAV','ALAC','APE','WV','TTA','DSF','DFF']);

