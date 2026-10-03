/* ================================================================
 * 状态层：全局 state 对象、收藏判定与收藏切换
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 全局状态 */
/* 音源默认值一律来自后端 /api/sources (单一事实来源), 前端不再硬编码任何列表 */
const state = {
  allSources: [], srcNames: {}, fast: [], defaults: [], cfg: [],
  history: store.get('cm_history', []),
  favs: store.get('cm_favs', []),
  imported: store.get('cm_imported', []),
  queue: [], qidx: -1, mode: store.get('cm_mode', 'list'),
  fm: { on: false, pool: [], played: new Set() },
  search: { job: null, sid: null, keyword: '', groups: [], all: [], timer: null, filter: '全部', tab: 'songs' },
  charts: {}, playlistCache: {},
  ethnos: { groups: [], building: false, timer: null },
  index: { data: null, tab: 'ethnos', ethnicSel: null, ethEdit: false, mode: 'artist',
           song: { q: '', group: '', rows: [], total: 0, offset: 0, loading: false, sid: null, capped: false, hint: '' } },
  ethCustom: store.get('cm_ethnic_custom', {}),
  myPlaylists: store.get('cm_my_playlists', []),
  history: store.get('cm_history', []),
  plRemoved: store.get('cm_pl_removed', {}),
  lyrics: [], lyricTrackUid: null,
  navStack: [],
};
const isFav = t => state.favs.some(f => f.name === t.name && f.artist === t.artist);
function toggleFav(t){
  if (!t) return;
  const i = state.favs.findIndex(f => f.name === t.name && f.artist === t.artist);
  if (i >= 0) { state.favs.splice(i, 1); toast('已取消喜欢'); } else { state.favs.unshift({ name: t.name, artist: t.artist, album: t.album || '', duration: t.duration || '', cover: t.cover || '' }); toast('已添加到我喜欢的音乐'); }
  store.set('cm_favs', state.favs); if (currentPage === 'favorites') renderFavorites(); refreshHearts();
}

