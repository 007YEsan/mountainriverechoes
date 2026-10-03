/* ================================================================
 * 路由层：hash 路由 nav() / render() 与各页面分发
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 路由 */
let currentPage = 'index';
function nav(page, params, push = true){
  const hash = '#' + page + (params ? '?' + new URLSearchParams(params).toString() : '');
  if (push && location.hash !== hash) { history.pushState({ page, params: params || {} }, '', hash); state.navDepth = (state.navDepth || 0) + 1; }
  render(page, params || {});
}
window.addEventListener('popstate', () => { state.navDepth = Math.max(0, (state.navDepth || 0) - 1); const m = location.hash.slice(1).split('?'); render(m[0] || 'index', Object.fromEntries(new URLSearchParams(m[1] || ''))); });
function render(page, params){
  currentPage = page;
  $$('.page').forEach(p => p.classList.remove('active'));
  const el = $('#page-' + page); if (el) el.classList.add('active');
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
  $('#content').scrollTop = 0;
  closeNowPlaying(false);
  if (page === 'discover') initDiscover();
  if (page === 'search') { if (params.q && params.q !== state.search.keyword) startSearch(params.q); else { renderSearchResults(); if (state.search.job && !state.search.finished) pollSearch(); } }
  if (page === 'playlist') openPlaylistDetail(params.id, params.name, params.platform);
  if (page === 'downloads') { renderDownloads(); pollTasks(); }
  if (page === 'local') loadLocal();
  if (page === 'favorites') renderFavorites();
  if (page === 'fm') renderFM();
  if (page === 'ethnos') { loadEthnos(); }
  if (page === 'index') { loadIndex(); loadEthnos(); }
  if (page === 'history') renderHistory();
}

