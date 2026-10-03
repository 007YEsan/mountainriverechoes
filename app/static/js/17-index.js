/* ================================================================
 * 音乐库索引：索引自愈、歌手批量管理、服务端歌曲检索分页
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 音乐库索引 */
/* 索引自愈: 库文件签名变了就重拉索引(限频 6 秒), 保证歌手/曲目列表不会停在旧快照上 */
let _idxSig = null, _idxSigAt = 0, _idxSigBusy = false;
async function maybeRefreshIndex(){
  const now = Date.now();
  if (_idxSigBusy || now - _idxSigAt < 6000) return;
  _idxSigAt = now; _idxSigBusy = true;
  try {
    const j = await api('/api/index/sig');
    if (_idxSig === null) { _idxSig = j.sig; }
    else if (j.sig && j.sig !== _idxSig) {
      _idxSig = j.sig;
      state.index.data = null;
      /* /api/index 在重算期间会先把旧快照发出来(免得白屏), 所以这一次拿到的可能仍是旧的。
         等 4s(全量重算实测约 2.7s)再无条件复拉一次, 否则"改完数据界面没变"会一直留着。 */
      setTimeout(() => { _idxSigAt = 0; state.index.data = null; loadIndex(true); }, 4000);
      await loadIndex(true);           /* 拉到新数据后会自己 renderIndex */
      return;
    }
  } catch (e) {}
  finally { _idxSigBusy = false; }
}

async function loadIndex(force){
  if (state.index.data && !force) { renderIndex(); return; }
  try {
    const d = await api('/api/index');
    state.index.data = d; renderIndex();
  } catch(err){}
}

/* ============ 歌手批量管理(编辑模式) ============ */
let ethBatchSel = new Set();
let ethBatchSelKey = '';   /* 选中集所属民族; 切库/退出编辑时清空, 防止跨库误删 */
function ethBatchRefresh(){
  const n = ethBatchSel.size;
  const c = document.querySelector('#eth-bcnt'); if (c) c.textContent = n;
  const del = document.querySelector('#eth-bdel'); if (del) del.disabled = !n;
  const res = document.querySelector('#eth-brestore'); if (res) res.disabled = !n;
  const ball = document.querySelector('#eth-ball');
  if (ball) {
    const boxes = [...document.querySelectorAll('.eth-row .eth-chk')];
    ball.checked = n > 0 && n >= boxes.length;
    ball.indeterminate = n > 0 && n < boxes.length;
  }
  document.querySelectorAll('.eth-row').forEach(rw => {
    const cb = rw.querySelector('.eth-chk');
    if (cb) rw.classList.toggle('on', cb.checked);
  });
}
function bindEthBatch(sel, shownList){
  if (ethBatchSelKey !== sel) { ethBatchSel.clear(); ethBatchSelKey = sel; }
  document.querySelectorAll('.eth-row .eth-chk').forEach(cb => {
    cb.onclick = e => e.stopPropagation();
    cb.checked = ethBatchSel.has(cb.dataset.cn);
    cb.onchange = e => {
      e.stopPropagation();
      cb.checked ? ethBatchSel.add(cb.dataset.cn) : ethBatchSel.delete(cb.dataset.cn);
      ethBatchRefresh();
    };
  });
  const ball = document.querySelector('#eth-ball');
  if (ball) ball.onchange = e => {
    const on = e.target.checked;
    document.querySelectorAll('.eth-row .eth-chk').forEach(cb => {
      cb.checked = on;
      on ? ethBatchSel.add(cb.dataset.cn) : ethBatchSel.delete(cb.dataset.cn);
    });
    ethBatchRefresh();
  };
  const rbar = document.querySelector('#eth-removedbar');
  if (rbar) rbar.onclick = () => rbar.classList.toggle('open');
  const bdel = document.querySelector('#eth-bdel');
  if (bdel) bdel.onclick = async () => {
    const names = [...ethBatchSel];
    if (!names.length) return;
    /* 勾选里可能混着「合集」: 它与歌手同权, 但后端选曲口径不同(album vs singers) */
    const _collSet = new Set((((state.index.data || {}).playlists) || []).filter(p => p.kind === 'YouTube合集' && p.group === sel).map(p => p.name));
    const _nColl = names.filter(n => _collSet.has(n)).length;
    if (!confirm(`删除所选 ${names.length} 项${_nColl ? `（含 ${_nColl} 个合集）` : ''}？`)) return;
    const cnt = shownList.filter(a => ethBatchSel.has(a.name)).reduce((s, a) => s + (a.count || 0), 0);
    const kill = cnt > 0 && confirm(`同时删除这 ${names.length} 项名下的约 ${cnt} 首歌曲？\n\n【确定】卡片 + 曲目一起删（不可恢复）\n【取消】仅隐藏卡片，曲目保留`);
    toast(`正在删除 ${names.length} 项...`);
    let killed = 0, fail = 0;
    for (const name of names) {
      try {
        const j = await ethEditPost(sel, { action: _collSet.has(name) ? 'remove_collection' : 'remove_artist', name, kill_tracks: kill });
        killed += j.killed || 0;
      } catch (err) { fail++; }
    }
    ethBatchSel.clear();
    const cc = (state.ethCustom[sel] = state.ethCustom[sel] || {});
    names.forEach(n => {
      if (_collSet.has(n)) return;      /* 合集的隐藏状态由服务端 collections_removed 掌管, 不进本机名单 */
      cc.removed = cc.removed || []; if (!cc.removed.includes(n)) cc.removed.push(n);
      cc.added = (cc.added || []).filter(x => x !== n);      /* 必须同步剔除, 否则"手动添加"回填会把它重新画回列表 */
      cc.pinned = (cc.pinned || []).filter(x => x !== n);
    });
    store.set('cm_ethnic_custom', state.ethCustom);
    toast(`已删除 ${names.length - fail} 项${kill ? `（含 ${killed} 首歌曲）` : ''}${fail ? `，${fail} 项失败` : ''}`);
    if (kill || _nColl) { state.index.data = null; state.ethSynced = {}; await loadIndex(true); }
    renderIndex();
  };
  const bres = document.querySelector('#eth-brestore');
  if (bres) bres.onclick = async () => {
    const names = [...ethBatchSel];
    if (!names.length) return;
    for (const name of names) {
      const cc = (state.ethCustom[sel] = state.ethCustom[sel] || {});
      cc.removed = (cc.removed || []).filter(x => x !== name);
      ethEditPost(sel, { action: 'add_artist', name }).catch(() => {});
    }
    store.set('cm_ethnic_custom', state.ethCustom);
    ethBatchSel.clear();
    toast(`已恢复 ${names.length} 位歌手`);
    renderIndex();
  };
  ethBatchRefresh();
}

function renderIndex(){
  if (!(state.ethnos.groups || []).length) loadEthnos();   /* 深链直开索引页时补拉民族状态(徽标/发现页计数) */
  const d = state.index.data;
  $('#idx-sub').textContent = d ? `${(d.stats || {}).artists || 0} 位歌手 · ${(d.stats || {}).songs || 0} 首歌曲 · ${(d.stats || {}).ethnos_playlists || 56} 个民族歌单` : '';
  $$('#page-index .stab').forEach(t => {
    const tab = t.dataset.itab;
    t.classList.toggle('on', tab === state.index.tab);
    const pane = $('#itab-' + tab);
    if (pane) pane.style.display = tab === state.index.tab ? '' : 'none';
  });
  if (state.index.tab === 'topics') { loadTopics(); return; }   /* 专题 pane 独立渲染, 不走民族网格 */
  /* 民族: 两级导航 (首页=民族列表 -> 二级=该民族歌手目录, 支持手动增删歌手) */
  const eg = $('#idx-ethnos');
  /* 歌手/歌曲 模式显隐: 两栏并列, 歌曲模式隐藏民族网格 */
  const songMode = state.index.mode === 'song';
  const sbox = $('#idx-songs');
  if (sbox) sbox.style.display = songMode ? '' : 'none';
  if (eg) eg.style.display = songMode ? 'none' : '';
  if (eg) {
    const artists = (d && d.artists) || [];
    const groups = {};
    artists.forEach(a => { (groups[a.group] = groups[a.group] || []).push(a); });
    // 合并用户自定义增删
    const custom = state.ethCustom || {};
    Object.keys(custom).forEach(g => {
      const c = custom[g] || {};
      groups[g] = (groups[g] || []).filter(a => !(c.removed || []).includes(a.name));
      (c.added || []).forEach(n => { if (!(c.removed || []).includes(n) && !groups[g].some(a => a.name === n)) groups[g].push({ name: n, group: g, count: 0, cover: '' }); });
    });
    // 民族歌曲数一律取磁盘实际曲目数(与「民族音乐」专区同一口径)。
    // 旧口径是"该民族所有歌手计数求和", 一首歌有多个歌手时会被重复累加 —— 实测比实际多 8,172 首
    const gsongs = (d && d.group_songs) || {};
    const songCnt = g => (gsongs[g] != null ? gsongs[g] : (groups[g] || []).reduce((s, a) => s + a.count, 0));
    const order = Object.keys(groups).filter(g => ETHNIC_ORDER.includes(g) || g === '汉族民间小调').sort((x, y) => songCnt(y) - songCnt(x));
    const chip = a => `<div class="eth-artist" data-an="${esc(a.name)}" data-ag="${esc(a.group || '')}" title="${esc(a.name)} · ${a.count}首${a.confirmed ? ' · 官方收录' : ''}">
      <div class="av" ${a.cover ? `style="background-image:url('/api/cover?url=${encodeURIComponent(a.cover)}');background-size:cover"` : ''}>${a.cover ? '' : esc((a.name || '?')[0])}</div>
      <div class="nm">${esc(a.name)}${a.confirmed ? '<span class="cf" title="权威归类">✓</span>' : ''}${state.index.ethEdit ? '<span class="eth-rm" data-rm="${esc(a.name)}" title="从该民族移除">✕</span>' : ''}</div>
      <div class="ct">${a.count}首</div></div>`;
    const goArtist = c => nav('playlist', { id: 'artist:' + c.dataset.an + '@' + (c.dataset.ag || ''), platform: 'index', name: '歌手「' + c.dataset.an + '」' });
    if (!state.hanInfo) {
      state.hanInfo = { count: 0 };
      api('/api/ethnos').then(ed => { const _was = (state.hanInfo && state.hanInfo.count) || 0; state.hanInfo = ed.han || {}; if (currentPage === 'index' && !state.index.ethnicSel && (state.hanInfo.count || 0) !== _was) renderIndex(); }).catch(() => {});
    }
    const sel = state.index.ethnicSel;
    if (!sel) {
      /* 一级: 民族列表 (filter 有值时显示跨民族歌手搜索结果) */
      const lv1Filter = (state.index.filter || '').trim().toLowerCase();
      if (lv1Filter) {
        const _raw = artists.filter(a => a.name.toLowerCase().includes(lv1Filter));
        const _seen = new Set(); const hits = [];
        for (const a of _raw) { if (!_seen.has(a.name)) { _seen.add(a.name); hits.push(a); } }
        /* 置顶态与该歌手所属民族的二级列表共用同一份 state.ethCustom.pinned;
           置顶的浮到最前(与二级「置顶」语义一致), 其余保持原相对序。 */
        const _pk = new Map();
        hits.forEach(a => { const p = ((custom[a.group] || {}).pinned) || []; const i = p.indexOf(a.name); if (i >= 0) _pk.set(a.name, i); });
        if (_pk.size) {
          const _idx = new Map(hits.map((a, i) => [a.name, i]));
          const _rank = a => (_pk.has(a.name) ? _pk.get(a.name) : 100000 + _idx.get(a.name));
          hits.sort((a, b) => _rank(a) - _rank(b));
        }
        eg.innerHTML = hits.length ? `<div class="eth-grid">${hits.map(a => `<div class="eth-row" data-an="${esc(a.name)}" data-ag="${esc(a.group || '')}" title="${esc(a.group)} · ${a.count}首">
          <div class="av" ${a.cover ? `style="background-image:url('/api/cover?url=${encodeURIComponent(a.cover)}');background-size:cover"` : ''}>${a.cover ? '' : esc((a.name || '?')[0])}</div>
          <div class="nminfo"><div class="nm">${esc(a.name)}${a.confirmed ? '<span class="cf" title="权威归类">✓</span>' : ''}</div><div class="ct">${esc(a.group)} · ${a.count} 首</div></div>
          <span class="eth-lv1ops"><svg class="ic sm go"><use href="#i-play"/></svg><span class="eth-apin${_pk.has(a.name) ? ' on' : ''}" data-apin="${esc(a.name)}" data-aping="${esc(a.group || '')}" title="${_pk.has(a.name) ? '取消置顶' : '在该民族内置顶此歌手'}">${_pk.has(a.name) ? '已置顶' : '置顶'}</span><span class="eth-amove" data-amove="${esc(a.name)}" data-amoveg="${esc(a.group || '')}" title="把该歌手名下曲目移动到其他民族库">移动至</span><span class="eth-adel" data-adel="${esc(a.name)}" data-adelg="${esc(a.group || '')}" title="从民族库删除该歌手">✕</span></span></div>`).join('')}</div>` : `<div class="empty">没有匹配「${esc(lv1Filter)}」的歌手</div>`;
        eg.querySelectorAll('.eth-row').forEach(rw => rw.onclick = e => {
          if (e.target.closest && e.target.closest('.eth-apin,.eth-amove,.eth-adel')) return;
          nav('playlist', { id: 'artist:' + rw.dataset.an + '@' + (rw.dataset.ag || ''), platform: 'index', name: '歌手「' + rw.dataset.an + '」' });
        });
        eg.querySelectorAll('.eth-apin').forEach(x => x.onclick = e => {
          e.stopPropagation();
          const name = x.dataset.apin, gname = x.dataset.aping;
          const gk = (gname === '汉族' || gname === '汉族民间小调') ? 'han' : ((state.ethnos.groups || []).find(y => y.name === gname) || {}).key;
          if (!gk) return toast('无法定位民族库：' + gname, true);
          const cc = (custom[gname] = custom[gname] || {});
          cc.pinned = cc.pinned || [];
          if (cc.pinned.includes(name)) cc.pinned = cc.pinned.filter(n => n !== name);
          else cc.pinned.unshift(name);
          state.ethCustom = custom; store.set('cm_ethnic_custom', custom);
          ethSyncPinOrder(gname);
          toast(cc.pinned.includes(name) ? `已在「${gname}」置顶「${name}」` : `已取消置顶「${name}」`);
          renderIndex();
        });
        eg.querySelectorAll('.eth-amove').forEach(x => x.onclick = e => {
          e.stopPropagation();
          openMoveMenu(x, x.dataset.amove, x.dataset.amoveg);
        });
        eg.querySelectorAll('.eth-adel').forEach(x => x.onclick = async e => {
          e.stopPropagation();
          const name = x.dataset.adel, gname = x.dataset.adelg;
          const gk = gname === '汉族' || gname === '汉族民间小调' ? 'han' : ((state.ethnos.groups || []).find(y => y.name === gname) || {}).key;
          if (!gk) return toast('无法定位民族库：' + gname, true);
          if (!confirm(`从「${gname}」库删除歌手「${name}」？`)) return;
          const kill = confirm(`同时删除「${name}」名下的歌曲吗？\n\n【确定】歌手 + 曲目一起删（硬删除）\n【取消】仅隐藏歌手卡片，曲目保留`);
          try {
            await ethEditPost(gk, { action: 'remove_artist', name, kill_tracks: kill });
            toast(`已删除「${name}」${kill ? '及其歌曲' : '（曲目保留）'}`);
            state.ethSynced = {}; state.index.data = null;
            await loadIndex(true);
            renderIndex();
          } catch (err) { toast('删除失败: ' + err.message, true); }
        });
        $('#eth-filter-hint').textContent = `找到 ${hits.length} 位歌手`;
        return;
      }
      $('#eth-filter-hint').textContent = `${order.length} 个民族 · ${new Set(artists.map(a => a.name)).size} 位歌手，点击卡片进入（卡片可拖动排序）`;
      const hanCnt = (state.hanInfo && state.hanInfo.count) || 0;
      const cardOf = g => {
        const isHan = g === '汉族民间小调';
        const gi = ethGrad(g), gs = ethGradSoft(g);
        return `<div class="pl-card eth-card" draggable="true" data-eth="${esc(g)}" title="点击进入 · 拖动调整次序"><div class="cov" style="background:linear-gradient(135deg,${gs[0]},${gs[1]});color:${gi[0]};text-shadow:none">${isHan ? '汉族' : esc(g)}</div><div class="nm">${isHan ? '汉族音乐 · ' + hanCnt + ' 首' : esc(g) + '音乐 · ' + songCnt(g) + ' 首'}</div></div>`;
      };
      eg.innerHTML = `<div class="pl-grid">${applyOrder([...new Set([...order, '汉族民间小调'])], store.get('cm_order_ethcards', ETHCARD_ORDER_DEFAULT)).map(cardOf).join('')}</div>`;
      eg.querySelectorAll('.eth-card[data-eth]').forEach(c => c.onclick = () => {
        state.index.ethnicSel = c.dataset.eth; state.index.ethEdit = false; renderIndex();
      });
      bindDragSort(eg, '.eth-card[data-eth]', 'cm_order_ethcards', el => el.dataset.eth);
    } else {
      /* 二级: 该民族歌手目录 (横幅头部 + 行式歌手列表) */
      maybeRefreshIndex();     /* 后台库变了就重拉, 免得看到旧歌手列表 */
      const list = groups[sel] || [];
      const filter = (state.index.filter || '').trim().toLowerCase();
      const c = custom[sel] || {};
      const gi = ethGrad(sel);
      const totalSongs = songCnt(sel);   // 与民族音乐专区同一口径(磁盘实际曲目数), 不再用歌手计数求和
      /* 该民族的 YouTube 合集: 化成与歌手同形的条目并入列表, 与歌手共用同一套排序/置顶/删除/移动逻辑,
         点击走 ytcoll: 虚拟歌单。合集不再写死归属景颇族 —— 曲目在哪个库, 合集就归哪个库(可整包搬库);
         被隐藏的合集由服务端按 collections_removed 排掉, 前端不再自行过滤(单一事实来源, 避免本机过期记录藏住)。 */
      const collItems = ((d && d.playlists) || [])
        .filter(p => (p.kind === 'YouTube合集') && p.group === sel)
        .map(c2 => ({ name: c2.name, count: c2.count, cover: c2.cover || '', confirmed: false, _yt: c2.id }));
      const collNames = new Set(collItems.map(x => x.name));
      /* 服务端记录的「已隐藏合集」: 进编辑模式时一并列出可恢复, 与歌手并列显示 */
      const hiddenColls = ((d && d.collections_removed) || {})[sel] || [];
      // 按曲目数插进歌手序列(后端 artists 已按 -count 排序), 即默认混排在它该在的位置而非钉死最前
      const baseList = [...list];
      for (const ci of collItems) {
        const at = baseList.findIndex(a => (a.count || 0) < (ci.count || 0));
        baseList.splice(at < 0 ? baseList.length : at, 0, ci);
      }
      maybeRefreshIndex();
      let ord = store.get('cm_order_ethrows_' + sel, []) || [];
      if (ord.length && collItems.some(ci => ord.indexOf(ci.name) < 0)) {
        // 历史排序里没有合集名: 按 baseList 的默认位次把合集插回序列, 免得被当成"未排序项"沉到末尾
        let seq = ord.slice();
        for (const ci of collItems) {
          if (seq.indexOf(ci.name) >= 0) continue;
          const bi = baseList.findIndex(a => a.name === ci.name);
          let p = seq.length;
          for (let j = bi + 1; j < baseList.length; j++) { const q = seq.indexOf(baseList[j].name); if (q >= 0) { p = q; break; } }
          seq.splice(p, 0, ci.name);
        }
        ord = seq;
      }
      const orderedList = applyOrder(baseList, ord, a => a.name);
      /* 服务端置顶/拖动次序(单一事实来源): 置顶段在前按其序, 其余按服务端序, 未记录的保持默认相对序 */
      const pinSet = new Set((custom[sel] && custom[sel].pinned) || []);
      const svOrder = (custom[sel] && custom[sel].order) || [];
      if (pinSet.size || svOrder.length) {
        const pk = new Map(), ok2 = new Map(), defIdx = new Map();
        orderedList.forEach((a, i) => defIdx.set(a.name, i));
        /* Set.forEach 回调是(值,值)不是(值,索引): 必须先转数组, 否则置顶键变成字符串、比较器恒 NaN, 置顶不生效 */
        [...pinSet].forEach((n, i) => pk.set(n, i));
        svOrder.forEach((n, i) => ok2.set(n, i));
        orderedList.sort((a, b) => {
          const ka = pk.has(a.name) ? pk.get(a.name) : (ok2.has(a.name) ? 10000 + ok2.get(a.name) : 200000 + (defIdx.get(a.name) || 0));
          const kb = pk.has(b.name) ? pk.get(b.name) : (ok2.has(b.name) ? 10000 + ok2.get(b.name) : 200000 + (defIdx.get(b.name) || 0));
          return ka - kb;
        });
      }
      const shownList = filter ? orderedList.filter(a => a.name.toLowerCase().includes(filter)) : orderedList;
      const _edit = state.index.ethEdit;
      const row = a => `<div class="eth-row${pinSet.has(a.name) ? ' is-pinned' : ''}" draggable="${_edit ? 'false' : 'true'}" data-an="${esc(a.name)}" data-ag="${esc(sel)}" ${a._yt ? `data-yt="${esc(a._yt)}"` : ''} title="${esc(a.name)} · ${a.count}首${_edit ? ' · 勾选批量删除' : ' · 拖动调整次序'}">
        <input type="checkbox" class="eth-chk" data-cn="${esc(a.name)}">
        <div class="av" ${a.cover ? `style="background-image:url('/api/cover?url=${encodeURIComponent(a.cover)}');background-size:cover"` : ''}>${a.cover ? '' : esc((a.name || '?')[0])}</div>
        <div class="nminfo"><div class="nm">${esc(a.name)}${a.confirmed ? '<span class="cf" title="权威归类">✓</span>' : ''}</div><div class="ct">${a.count ? a.count + ' 首' : '待穷尽'}</div></div>
        <svg class="ic sm go"><use href="#i-play"/></svg>
        ${!_edit ? `<span class="row-ops" data-an="${esc(a.name)}">
          <button class="op-pin ${pinSet.has(a.name) ? 'pinned' : ''}" title="${pinSet.has(a.name) ? '取消置顶' : '置顶'}">${pinSet.has(a.name) ? '已置顶' : '置顶'}</button>
          <button class="op-move" title="把该条目的曲目移动到其他民族库">移动至</button>
          <button class="op-del" title="删除">删除</button>
        </span>` : ''}
      </div>`;
      eg.innerHTML = `
        <div class="eth-head" style="background:linear-gradient(120deg,${gi[0]},${gi[1]})">
          <button class="eth-hbtn" id="eth-back" title="返回民族列表"><svg class="ic"><use href="#i-arrow-l"/></svg></button>
          <div class="tblock"><div class="t">${esc(sel === '汉族民间小调' ? '汉族' : sel)}</div><div class="sub">${list.length} 位歌手 · ${totalSongs} 首${filter ? ` · 匹配「${esc(filter)}」${shownList.length} 位` : ''}</div></div>
          <span style="flex:1"></span>
          <button class="eth-hbtn" id="eth-adda"><svg class="ic sm"><use href="#i-plus"/></svg>添加歌手</button>
          <button class="eth-hbtn" id="eth-edit">${state.index.ethEdit ? '完成' : '移除歌手'}</button>
          <button class="eth-hbtn" id="eth-goplist" title="进入完整歌单"><svg class="ic sm"><use href="#i-list"/></svg>歌单</button>
        </div>
        ${state.index.ethEdit && ((c.removed || []).length + hiddenColls.length) ? `<div class="eth-removedbar" id="eth-removedbar">已移除 ${((c.removed || []).length + hiddenColls.length)} 项 · 点击展开恢复<div class="detail">${(c.removed || []).map(n => `<span class="eth-restore" data-rs="${esc(n)}" data-coll="0" style="color:var(--red);cursor:pointer;margin:0 6px">${esc(n)} ↺</span>`).join('')}${hiddenColls.map(n => `<span class="eth-restore" data-rs="${esc(n)}" data-coll="1" style="color:var(--red);cursor:pointer;margin:0 6px">${esc(n)}（合集）↺</span>`).join('')}</div></div>` : ''}
        ${state.index.ethEdit ? `<div class="eth-batchbar">
          <label style="display:flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" id="eth-ball"> 全选</label>
          <span>已选 <b id="eth-bcnt">0</b> 位</span><span style="flex:1"></span>
          <button class="btn btn-plain btn-sm" id="eth-brestore">恢复所选</button>
          <button class="btn btn-primary btn-sm" id="eth-bdel" disabled>删除所选</button>
        </div>` : ''}
        ${shownList.length ? `<div class="eth-grid">${shownList.map(row).join('')}</div>` : `<div class="empty">${filter ? '没有匹配的歌手' : '暂无歌手'}</div>`}`;
      $('#eth-back').onclick = () => { state.index.ethnicSel = null; state.index.ethEdit = false; state.index.filter = ''; const fi2 = $('#eth-filter'); if (fi2) fi2.value = ''; renderIndex(); };
      $('#eth-adda').onclick = () => {
        const n = prompt(`添加歌手到「${sel}」（可填任意歌手/乐队名）:`);
        if (n && n.trim()) {
          const cc = (custom[sel] = custom[sel] || {});
          cc.added = cc.added || [];
          if (!cc.added.includes(n.trim()) && !list.some(a => a.name === n.trim())) { cc.added.push(n.trim()); state.ethCustom = custom; store.set('cm_ethnic_custom', custom); toast(`已添加「${n.trim()}」到${sel}`); ethEditPost(sel, { action: 'add_artist', name: n.trim() }).catch(() => toast('服务端同步失败，仅本机生效', true)); renderIndex(); }
        }
      };
      $('#eth-edit').onclick = () => { state.index.ethEdit = !state.index.ethEdit; ethBatchSel.clear(); renderIndex(); };
      $('#eth-goplist').onclick = () => { const pid = ethKeyOf(sel); nav('playlist', { id: pid, platform: 'ethnos', name: sel === '汉族民间小调' ? '汉族' : sel + ' · 民族音乐' }); };
      eg.querySelectorAll('.eth-restore').forEach(r => r.onclick = async () => {
        const nm = r.dataset.rs;
        if (r.dataset.coll === '1') {
          /* 恢复被隐藏的合集: 服务端把它从 collections_removed 摘掉, 重拉索引即重新出现 */
          try {
            await ethEditPost(sel, { action: 'remove_collection', name: nm, restore: true });
            state.index.data = null; state.ethSynced = {}; await loadIndex(true);
            toast(`已恢复合集「${nm}」`);
          } catch (err) { toast('服务端恢复失败', true); }
          return;
        }
        const cc = custom[sel] || {}; cc.removed = (cc.removed || []).filter(x => x !== nm);
        state.ethCustom = custom; store.set('cm_ethnic_custom', custom); renderIndex();
        ethEditPost(sel, { action: 'add_artist', name: nm }).catch(() => {});
      });
      const postArtistOrder = () => {
        const names = [...eg.querySelectorAll('.eth-row[data-an]')].map(x => x.dataset.an);
        const curPinned = (custom[sel] && custom[sel].pinned) || [];
        ethEditPost(sel, { action: 'save_artist_order', names, pinned: curPinned.filter(n => names.includes(n)) }).catch(() => toast('服务端同步失败，仅本机生效', true));
      };
      eg.querySelectorAll('.eth-row .op-pin').forEach(b => b.onclick = e => {
        e.stopPropagation();
        const name = b.closest('.row-ops').dataset.an;
        const cc = (custom[sel] = custom[sel] || {});
        cc.pinned = cc.pinned || [];
        if (cc.pinned.includes(name)) cc.pinned = cc.pinned.filter(x => x !== name);
        else cc.pinned.unshift(name);
        state.ethCustom = custom; store.set('cm_ethnic_custom', custom);
        renderIndex();
        postArtistOrder();
      });
      eg.querySelectorAll('.eth-row .op-move').forEach(b => b.onclick = e => {
        e.stopPropagation();
        const _n = b.closest('.row-ops').dataset.an;
        openMoveMenu(b, _n, sel, collNames.has(_n));   /* 合集走 move_collection, 歌手走 move_artist */
      });
      eg.querySelectorAll('.eth-row .op-del').forEach(b => b.onclick = async e => {
        e.stopPropagation();
        const name = b.closest('.row-ops').dataset.an;
        /* 合集与歌手完全同权: 同样的两段确认(硬删曲目 / 仅隐藏卡片), 只是后端选曲口径不同
           (合集按 album 相等挑曲目, 歌手按 singers 命中)。 */
        const isColl = collNames.has(name);
        const what = isColl ? '合集' : '歌手';
        if (!confirm(`从「${sel}」删除${what}「${name}」？`)) return;
        const cnt = (((isColl ? collItems : list).find(a => a.name === name) || {}).count) || 0;
        const kill = cnt > 0 && confirm(`同时删除「${name}」名下的 ${cnt} 首歌曲？\n\n【确定】${what}卡片 + 曲目一起删（不可恢复）\n【取消】仅隐藏${what}卡片，曲目保留`);
        try {
          const j = await ethEditPost(sel, isColl ? { action: 'remove_collection', name, kill_tracks: kill }
                                                  : { action: 'remove_artist', name, kill_tracks: kill });
          toast(kill ? `已删除「${name}」及其 ${j.killed ?? cnt} 首歌曲` : `已从${sel}删除「${name}」（曲目保留）`);
        } catch (err) { toast('服务端同步失败，仅本机生效', true); }
        /* 合集: 隐藏/硬删都由服务端落 collections_removed 或真删曲目, 重拉索引即生效(不与 localStorage 双份记账) */
        if (isColl || kill) { state.index.data = null; state.ethSynced = {}; await loadIndex(true); return; }
        const cc = (custom[sel] = custom[sel] || {});
        cc.removed = cc.removed || []; cc.removed.push(name);
        cc.added = (cc.added || []).filter(n2 => n2 !== name);
        cc.pinned = (cc.pinned || []).filter(x => x !== name);
        state.ethCustom = custom; store.set('cm_ethnic_custom', custom);
        renderIndex();
      });
      eg.classList.toggle('eth-editing', !!state.index.ethEdit);
      if (state.index.ethEdit) { bindEthBatch(sel, shownList); }
      eg.querySelectorAll('.eth-row').forEach(rw => rw.onclick = e => {
        if (e.target.classList.contains('eth-chk')) return;
        if (e.target.closest('.row-ops') || e.target.classList.contains('eth-rm')) return;
        if (state.index.ethEdit) return;   /* 编辑模式点行不导航, 只勾选 */
        if (rw.dataset.yt) { nav('playlist', { id: rw.dataset.yt, platform: 'index', name: rw.dataset.an }); return; }
        nav('playlist', { id: 'artist:' + rw.dataset.an + '@' + (rw.dataset.ag || ''), platform: 'index', name: '歌手「' + rw.dataset.an + '」' });
      });
      bindDragSort(eg.querySelector('.eth-grid'), '.eth-row[data-an]', 'cm_order_ethrows_' + sel, el => el.dataset.an);
      (() => { const g = eg.querySelector('.eth-grid'); if (!g || g._dragSync) return; g._dragSync = true;
        g.addEventListener('dragend', () => setTimeout(postArtistOrder, 60)); })();
      eg.querySelectorAll('.eth-rm').forEach(x => x.onclick = async e => {
        e.stopPropagation();
        const name = x.dataset.rm;
        if (!confirm(`从「${sel}」移除歌手「${name}」？`)) return;
        const cnt = ((list.find(a => a.name === name) || {}).count) || 0;
        const kill = cnt > 0 && confirm(`同时删除「${name}」名下的 ${cnt} 首歌曲？\n\n【确定】歌手卡片 + 曲目一起删（不可恢复）\n【取消】仅隐藏歌手卡片，曲目保留`);
        const cc = (custom[sel] = custom[sel] || {});
        cc.removed = cc.removed || []; cc.removed.push(name);
        cc.added = (cc.added || []).filter(n2 => n2 !== name);
        state.ethCustom = custom; store.set('cm_ethnic_custom', custom);
        try {
          const j = await ethEditPost(sel, { action: 'remove_artist', name, kill_tracks: kill });
          toast(kill ? `已删除「${name}」及其 ${j.killed ?? cnt} 首歌曲` : `已从${sel}移除「${name}」（曲目保留）`);
          if (kill) { state.index.data = null; state.ethSynced = {}; }
        } catch (err) { toast('服务端同步失败，仅本机生效', true); }
        renderIndex();
      });
      /* 进入民族页时合并服务端协作名单(其他协作者的改动对所有人可见), 每会话每族同步一次 */
      if (!state.ethSynced) state.ethSynced = {};
      if (sel && !state.ethSynced[sel]) {
        state.ethSynced[sel] = true;
        (async () => {
          try {
            const gk = ethKeyOf(sel); if (!gk) return;
            const d = await api(`/api/ethnos/custom?group=${encodeURIComponent(gk)}`);
            const cc = (state.ethCustom[sel] = state.ethCustom[sel] || {});
            const before = JSON.stringify(cc);
            cc.added = [...new Set([...(d.artists_added || []), ...(cc.added || [])])];
            cc.removed = [...new Set([...(d.artists_removed || []), ...(cc.removed || [])])];
            /* 服务端「已显式添加/恢复」压过本地陈旧移除记录: 否则本机 localStorage 里一条过期的
               "已移除某某"会和服务端名单取并集后一直把该歌手藏住(服务端 restore 了也看不见) */
            cc.removed = cc.removed.filter(n => !(d.artists_added || []).includes(n));
            cc.added = (cc.added || []).filter(n => !cc.removed.includes(n));
            if ((d.artists_pinned || []).length || (d.artist_order || []).length) {
              /* 服务端有排布数据: 只有本地还没动过时才采纳(避免别的端旧数据盖掉本端新操作) */
              if (cc.pinned === undefined && cc.order === undefined) { cc.pinned = d.artists_pinned; cc.order = d.artist_order; }
            }
            if (JSON.stringify(cc) !== before) { store.set('cm_ethnic_custom', state.ethCustom); renderIndex(); }
          } catch (err) {}
        })();
      }
    }
    const fi = $('#eth-filter');
    if (fi && !fi._bound) {
      fi._bound = true;
      fi.addEventListener('input', () => {
        state.index.filter = fi.value;
        if (state.index.mode === 'song') { scheduleSongSearch(fi.value); return; }  /* 走服务端检索, 防抖 */
        renderIndex(); fi.focus(); fi.setSelectionRange(fi.value.length, fi.value.length);
      });
    }
    $$('#eth-mode .chip').forEach(c => { if (!c._bound) { c._bound = true; c.onclick = () => setIndexMode(c.dataset.mode); } });
  }
  if (!d) { loadIndex(true); return; }
  /* 注: 「歌单」tab 已下线(用户要求) —— 民族歌单列表由侧栏「民族音乐歌单」进入民族音乐专区查看,
     同一份卡片不再在两处重复堆叠。这里原来填充 #idx-playlists 的代码一并删除。 */
}
$$('#page-index .stab').forEach(t => t.onclick = () => { state.index.tab = t.dataset.itab; if (t.dataset.itab === 'topics') loadTopics(); renderIndex(); });

/* ============ 专题曲库 tab ============ */
async function loadTopics(){
  if (state.index.topics) { renderTopics(); return; }
  try {
    const d = await api('/api/topics');
    state.index.topics = d.topics || [];
    renderTopics();
  } catch (err) {
    const g = $('#idx-topics');
    if (g) g.innerHTML = `<div class="empty">专题加载失败</div>`;
  }
}
function renderTopics(){
  const g = $('#idx-topics');
  if (!g) return;
  const ts = state.index.topics || [];
  if (!ts.length) { g.innerHTML = `<div class="empty"><svg><use href="#i-list"/></svg><div>暂无专题 · 敬请期待</div></div>`; return; }
  const COLORS = [['#7c4dbd', '#b28ae0'], ['#0f766e', '#5eead4'], ['#b45309', '#fbbf24']];
  g.innerHTML = ts.map((t, i) => {
    const c = COLORS[i % COLORS.length];
    /* 与民族卡同一套「淡底 + 本色淡字」口径: 底色向白混 68%, 文字向白混 30%, 并去掉 text-shadow */
    const cb = [mixWhite(c[0], .68), mixWhite(c[1], .68)];
    const ct = mixWhite(c[0], .3);
    return `<div class="pl-card eth-card" data-topic="${esc(t.key)}" title="点击进入「${esc(t.name)}」专题曲库">
      <div class="cov" style="background:linear-gradient(135deg,${cb[0]},${cb[1]});color:${ct};text-shadow:none">${esc(t.name)}</div>
      <div class="nm">${esc(t.name)} · 专题音乐 · ${t.count} 首</div></div>`;
  }).join('');
  g.querySelectorAll('.eth-card[data-topic]').forEach(c => c.onclick = () => {
    const t = ts.find(x => x.key === c.dataset.topic);
    if (t) nav('playlist', { id: t.key, platform: 'ethnos', name: t.name + ' · 专题音乐' });
  });
}

/* ---------------------------------------------------------------- 索引页 · 歌曲检索 (服务端 /api/index/search) */
const SONG_PAGE = 60;
let _songTimer = null, _songSeq = 0;

function setIndexMode(m){
  state.index.mode = m;
  $$('#eth-mode .chip').forEach(c => c.classList.toggle('on', c.dataset.mode === m));
  /* 显隐必须由本函数直接处理: 切到歌曲模式不会走 renderIndex(), 面板切换逻辑在那里 */
  const sb = $('#idx-songs'), eg2 = $('#idx-ethnos');
  if (sb) sb.style.display = m === 'song' ? '' : 'none';
  if (eg2) eg2.style.display = m === 'song' ? 'none' : '';
  if (m === 'song') {
    state.index.song = { q: '', group: '', rows: [], total: 0, offset: 0, loading: false, sid: null, capped: false, hint: '' };
    runSongSearch(($('#eth-filter') ? $('#eth-filter').value : '').trim(), 0);
  } else {
    renderIndex();
  }
}

function scheduleSongSearch(v){
  clearTimeout(_songTimer);
  _songTimer = setTimeout(() => runSongSearch((v || '').trim(), 0), 250);
}

function songUrl(q, off){
  let u = `/api/index/search?q=${encodeURIComponent(q)}&limit=${SONG_PAGE}&offset=${off}`;
  if (state.index.ethnicSel) u += `&group=${encodeURIComponent(state.index.ethnicSel)}`;
  return u;
}

async function runSongSearch(q, offset){
  const seq = ++_songSeq, s = state.index.song;
  if (offset === 0) { s.q = q; s.rows = []; s.offset = 0; s.group = state.index.ethnicSel || ''; }
  if (!q) { s.rows = []; s.total = 0; s.loading = false; renderSongResults(); return; }
  s.loading = true; renderSongResults();
  try {
    let d = await api(songUrl(q, offset));
    for (let i = 0; i < 20 && d && d.building; i++) {   /* 首次建索引, 轮询最多约 30s */
      await new Promise(r => setTimeout(r, 1500));
      d = await api(songUrl(q, offset));
    }
    if (seq !== _songSeq) return;                       /* 丢弃过期响应, 防网络乱序 */
    s.loading = false; s.total = d.total || 0; s.offset = offset; s.hint = d.hint || '';
    if (!s.rows.length) s.sid = d.sid;
    s.rows = s.rows.concat(d.tracks || []);
    s.capped = !!d.capped;
    renderSongResults();
  } catch (err) {
    if (seq === _songSeq) { s.loading = false; renderSongResults(err); }
  }
}

function renderSongResults(err){
  const s = state.index.song;
  const sum = $('#idx-songs-summary'), tb = $('#idx-songs-tbody'), em = $('#idx-songs-empty');
  if (!sum || !tb) return;
  const scope = s.group ? `在「${esc(s.group)}」内检索 · <a id="idx-song-unscope" style="color:var(--red);cursor:pointer">不限定民族</a> · ` : '';
  if (err) { sum.innerHTML = `<span style="color:#e04b4b">检索失败: ${esc(err.message || err)}</span>`; tb.innerHTML = ''; if (em) em.style.display = ''; return; }
  if (s.loading) { sum.innerHTML = `正在检索 <b>${esc(s.q)}</b> ... <span class="spin"></span>`; return; }
  sum.innerHTML = s.rows.length
    ? `${scope}“<b>${esc(s.q)}</b>” 共 <b>${s.total}</b> 首，已显示 ${s.rows.length} 首`
      + (s.capped ? ` · <a id="idx-song-more" style="color:var(--red);cursor:pointer">加载更多</a>` : '')
    : `${scope}${esc(s.hint || '没有匹配的歌曲，换个关键词试试')}`;
  tb.innerHTML = s.rows.map((it, i) => songRow(it, i, { sid: s.sid, showGroup: true })).join('');
  if (em) em.style.display = s.rows.length ? 'none' : '';
  if (s.rows.length) bindSongRows(tb, s.rows, { sid: s.sid, showGroup: true });
  const un = document.querySelector('#idx-song-unscope');
  if (un) un.onclick = () => { state.index.ethnicSel = null; renderIndex(); runSongSearch(s.q, 0); };
  const mo = document.querySelector('#idx-song-more');
  if (mo) mo.onclick = () => runSongSearch(s.q, s.offset + s.rows.length);
}

