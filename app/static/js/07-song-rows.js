/* ================================================================
 * 歌曲行事件绑定、歌手/专辑智能跳转、搜索结果转曲目对象
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
function bindSongRows(tbody, items, ctx){
  tbody.querySelectorAll('tr').forEach(tr => {
    if (tr.dataset.i === undefined) return;
    const it = items[+tr.dataset.i];
    const track = { name: it.song_name, artist: it.singers, album: it.album, duration: it.duration, cover: it.cover_url, sid: ctx && ctx.sid, id: it.id, source: it.source, source_cn: it.source_cn || state.srcNames[it.source], versions: it._versions, ctxSid: ctx && ctx.sid, ms: it.ms };
    tr.querySelector('.pbtn').onclick = e => { e.stopPropagation(); playTrack(track, { list: items.map((x, xi) => toTrack(x, ctx, xi)), fromList: true }); };
    tr.onclick = () => {
      if (batchMode) {   /* 批量模式下整行点选。.pbtn 虽然隐藏了, 但 .click() 照样会触发 -> 不拦就变成边勾边播 */
        const cb = tr.querySelector('.bchk');
        if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change', { bubbles: true })); }
        return;
      }
      tr.querySelector('.pbtn').click();
    };
    const _cb = tr.querySelector('.bchk');
    if (_cb) {
      _cb.onclick = e => e.stopPropagation();
      _cb.onchange = e => {
        e.stopPropagation();
        const k = trackKeyOf(it);
        _cb.checked ? batchSel.add(k) : batchSel.delete(k);
        const trNow = _cb.closest('tr');
        if (trNow) trNow.classList.toggle('on', _cb.checked);
        refreshBatchBar();
      };
    }
    tr.querySelector('.a-fav').onclick = e => { e.stopPropagation(); toggleFav({ name: it.song_name, artist: it.singers, album: it.album, duration: it.duration, cover: it.cover_url }); };
    tr.querySelector('.a-pl').onclick = e => { e.stopPropagation(); openAddToPlaylist(track); };
    const _as = tr.querySelector('.a-artist');
    if (_as) _as.onclick = e => { e.stopPropagation(); openArtistAssign(it, ctx, track); };
    tr.querySelector('.a-dl').onclick = e => { e.stopPropagation(); openMsDialog(track); };
    tr.querySelector('.a-add').onclick = e => { e.stopPropagation(); addToQueue(toTrack(it, ctx, +tr.dataset.i), false); };
    const rm = tr.querySelector('.a-rm');
    if (rm) rm.onclick = e => { e.stopPropagation(); removeTrackFromPlaylist(ctx, it); };
    const gdel = tr.querySelector('.a-gdel');
    if (gdel) gdel.onclick = async e => {
      e.stopPropagation();
      const gname = it.group || tr.dataset.ethgroup || '';
      const gk = gname === '汉族' || gname === '汉族民间小调' ? 'han' : ((state.ethnos.groups || []).find(x => x.name === gname) || {}).key;
      if (!gk) return toast('无法定位民族库：' + gname, true);
      if (!confirm(`从「${gname}」库删除《${it.song_name}》？\n（按 歌名+歌手+音源 精确删除，硬删除不备份）`)) return;
      try {
        await api('/api/ethnos/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ group: gk, editor: ethEditor(), action: 'remove_track', tname: it.song_name, tsingers: it.singers || '', tsource: it.source || '' }) });
        toast(`已从「${gname}」删除《${it.song_name}》`);
        const s = state.index.song;
        s.rows = s.rows.filter(x => x !== it);
        s.total = Math.max(0, s.total - 1);
        renderSongResults();
        syncAfterEdit(false);
      } catch (err) { toast('删除失败: ' + err.message, true); }
    };
    const pn = tr.querySelector('.a-pin');
    if (pn && ctx.ethGroup) pn.onclick = async e => {
      e.stopPropagation();
      const k = ethTrackKey(it);
      const cc = (state.ethCustom[ctx.ethGroup] = state.ethCustom[ctx.ethGroup] || {});
      cc.trackPinned = cc.trackPinned || [];
      cc.trackPinned = cc.trackPinned.includes(k) ? cc.trackPinned.filter(x => x !== k) : [k, ...cc.trackPinned];
      store.set('cm_ethnic_custom', state.ethCustom);
      await postTrackOrder(ctx.ethGroup);
      renderPlaylistPage();
    };
    tr.querySelector('.td-singer').onclick = e => { e.stopPropagation(); smartSingerClick(it.singers, it, ctx); };
    tr.querySelector('.td-album').onclick = e => { e.stopPropagation(); smartAlbumClick(it.album, it.singers, it.album_url); };
  });
}
/* 歌手/专辑智能跳转: 歌手有内部歌单进歌单, 没有则询问建歌手卡片; 专辑一律外链原平台 */
async function smartSingerClick(singers, it, ctx){
  const name = (singers || '').split(/[\/,，、]/)[0].trim();
  if (!name || ['未知歌手', '—', '本地音乐'].includes(name)) return;
  if (!state.index.data) { await loadIndex(true).catch(() => {}); }
  /* 库内匹配收紧(2026-10-03): 双向子串要求短边>=3字 —— 此前 1 字歌手名(如「a」)会误吞一切
     含该字母的名字, 导致"库外建卡"永远弹不出来 */
  const hit = ((state.index.data || {}).artists || []).find(a => {
    const an = norm(a.name), n = norm(name);
    if (!an || !n) return false;
    if (an === n) return true;
    const sh = Math.min(an.length, n.length);
    return sh >= 3 && (an.includes(n) || n.includes(an));
  });
  if (hit) nav('playlist', { id: 'artist:' + hit.name + '@' + (hit.group || ''), platform: 'index', name: '歌手「' + hit.name + '」' });
  else if (it) {
    /* 库中无此歌手: 打开「添加到歌手」弹窗(预填歌手名), 选好民族点「创建并加入」即建卡片 */
    toast(`库中没有歌手「${name}」，可选择民族创建歌手卡片`);
    openArtistAssign(it, ctx || {});
  }
  else doSearch(name);
}
async function smartAlbumClick(album, singers, url){
  if (url) { window.open(url, '_blank'); return; }
  const al = (album || '').trim();
  const singer = (singers || '').split(/[\/,，、]/)[0].trim();
  if (!al || al === '—') return;
  if (!state.index.data) { await loadIndex(true).catch(() => {}); }
  const hit = ((state.index.data || {}).albums || []).find(b => norm(b.name) === norm(al) && (!singer || norm(b.artist) === norm(singer)))
    || ((state.index.data || {}).albums || []).find(b => norm(b.name) === norm(al));
  if (hit) { nav('playlist', { id: 'album:' + hit.name + '@' + hit.artist, platform: 'index', name: '专辑「' + hit.name + '」' }); return; }
  /* 专辑 Tab 已下线: 不再拿 BV 号这类脏专辑名去触发无意义的全网搜索 */
}
const toTrack = (it, ctx, i) => ({ name: it.song_name, artist: it.singers, album: it.album, duration: it.duration, cover: it.cover_url, sid: ctx && ctx.sid, id: it.id, source: it.source, source_cn: it.source_cn || state.srcNames[it.source], versions: it._versions, localUrl: it.localUrl, ms: it.ms });

