/* ================================================================
 * 私人FM：推荐池、下一首、不再推荐
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 私人FM */
async function fmEnsurePool(){
  if (state.fm.pool.length) return;
  const ids = (state.chartsList || []).slice(0, 2).map(c => c.id);
  const pools = await Promise.all(ids.map(async id => { try { return (await getPlaylistDetail(id)).tracks; } catch(err){ return []; } }));
  state.fm.pool = pools.flat();
}
async function fmStart(){
  $('#fm-tip').textContent = '正在准备FM曲库...';
  await fmEnsurePool();
  if (!state.fm.pool.length) { $('#fm-tip').textContent = '曲库加载失败，请稍后再试'; return; }
  state.fm.on = true; state.fm.played = new Set();
  $('#fm-badge').style.display = '';
  $('#fm-next').style.display = ''; $('#fm-ban').style.display = '';
  $('#fm-tip').textContent = '根据热歌榜/新歌榜随机推荐 · 播放结束自动切歌';
  fmNext();
}
function fmPick(){
  const pool = state.fm.pool.filter(t => !state.fm.played.has(t.name));
  const arr = pool.length ? pool : state.fm.pool;
  return arr[Math.floor(Math.random() * arr.length)];
}
function fmNext(){
  const t = fmPick(); if (!t) return;
  state.fm.played.add(t.name);
  state.queue = [{ name: t.name, artist: t.artist, album: t.album, cover: t.cover, duration: fmtTime((t.duration_ms || 0) / 1000) }];
  state.qidx = 0; state.fm.on = true;
  loadCurrent();
  renderFM();
  $('#fm-tip').textContent = `正在播放: ${t.name} - ${t.artist}`;
}
function renderFM(){
  const on = state.fm.on;
  $('#fm-badge').style.display = on ? '' : 'none';
  $('#fm-next').style.display = on ? '' : 'none';
  $('#fm-ban').style.display = on ? '' : 'none';
  if (on && !audio.paused) $('#fm-disc').classList.add('rot'); else $('#fm-disc').classList.remove('rot');
}
$('#fm-start').onclick = fmStart;
$('#fm-next').onclick = () => fmNext();
$('#fm-ban').onclick = () => { const t = currentTrack(); if (t) { state.fm.played.add(t.name); toast('将减少这类推荐'); } fmNext(); };

