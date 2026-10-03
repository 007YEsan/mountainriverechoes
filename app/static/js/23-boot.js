/* ================================================================
 * 入口自执行：启动 boot() 与交互增强 enhance()
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 启动 */
(async function boot(){
  await loadSources();
  loadPresets();
  initDiscover();   /* 后台预热榜单/预置歌单, 不阻塞首屏 */
  renderMyPlaylists();
  const m = location.hash.slice(1).split('?');
  render(m[0] || 'index', Object.fromEntries(new URLSearchParams(m[1] || '')));
  pollTasks();
  /* UI 态服务端对齐: 换设备/清缓存后能把上次的排序、隐藏、我的歌单找回来 */
  uiStateBootstrap();
})();

/* ================================================================ UI 增强 (交互层) */
(function enhance(){
  /* ---- 1. 搜索结果骨架屏: 首批结果回来前显示占位行, 避免空白焦虑 ---- */
  try {
    const skRow = n => `<tr class="sk-row"><td class="td-index"><span class="num">${n}</span></td>`+
      `<td class="td-name"><div class="sk" style="height:13px;width:${58+((n*13)%30)}%"></div></td>`+
      `<td class="td-singer"><div class="sk" style="height:12px;width:${44+((n*17)%32)}%"></div></td>`+
      `<td class="td-album"><div class="sk" style="height:12px;width:${40+((n*11)%34)}%"></div></td>`+
      `<td class="td-time"><div class="sk" style="height:12px;width:30px"></div></td><td class="td-act"></td></tr>`;
    const _render = renderSearchResults;
    renderSearchResults = function(){
      _render.apply(this, arguments);
      const s = state.search || {}, el = $('#search-tbody');
      if (el && s.keyword && !s.finished && !(s.dedup || []).length)
        el.innerHTML = Array.from({length:7}, (_, i) => skRow(i + 1)).join('');
    };
  } catch(e){ console.warn('[enhance] skeleton:', e); }

  /* ---- 2. Cmd/Ctrl+K 聚焦搜索框 ---- */
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'){
      e.preventDefault();
      const si = $('#search-input'); si.focus(); si.select();
    }
    if (e.key === '?' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA'){
      e.preventDefault(); toggleKeyHelp();
    }
    if (e.key === 'Escape' && $('#kbd-help').classList.contains('show')) $('#kbd-help').classList.remove('show');
  });

  /* ---- 3. 快捷键帮助面板 ---- */
  let helpEl = null;
  function toggleKeyHelp(){
    if (!helpEl){
      helpEl = document.createElement('div');
      helpEl.id = 'kbd-help';
      helpEl.innerHTML = '<div class="kh-card"><b>键盘快捷键</b>' +
        [['Space','播放 / 暂停'],['← →','快退 / 快进 5 秒'],['↑ ↓','音量调节'],
         ['⌘/Ctrl + K','聚焦搜索框'],['Esc','关闭弹窗 / 帮助'],['?','打开本帮助']]
        .map(([k, v]) => `<div class="kh-row"><kbd>${k}</kbd><span>${v}</span></div>`).join('') +
        '<div class="kh-foot">点击任意处关闭</div></div>';
      document.body.appendChild(helpEl);
      helpEl.onclick = () => helpEl.classList.remove('show');
    }
    helpEl.classList.toggle('show');
  }

  /* ---- 4. 图片加载失败兜底: 隐藏破图, 露出底层渐变色块 ---- */
  document.addEventListener('error', e => {
    const t = e.target;
    if (t && t.tagName === 'IMG'){ t.style.visibility = 'hidden'; t.setAttribute('data-failed', '1'); }
  }, true);

  /* ---- 5. 内容区滚动时给顶栏加投影, 强化层次 ---- */
  const content = $('#content'), topbar = $('#topbar');
  if (content && topbar) content.addEventListener('scroll', () => {
    topbar.classList.toggle('scrolled', content.scrollTop > 4);
  }, { passive: true });

  /* ---- 6. 侧栏 logo 点击回到音乐库索引 ---- */
  const logo = document.querySelector('.logo');
  if (logo){ logo.style.cursor = 'pointer'; logo.onclick = () => nav('index'); logo.title = '回到音乐库索引'; }
})();
