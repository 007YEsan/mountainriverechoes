/* ================================================================
 * 歌词：拉取、渲染、手动编辑、滚动同步
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 歌词 */
function lyricKeyOf(t){ return norm(t && (t.name || t.song_name)) + '|' + norm(t && (t.artist || t.singers)); }
function manualLyrics(){ return store.get('cm_lyrics', {}) || {}; }
function renderLrcText(raw){
  const lines = [];
  raw.split(/\r?\n/).forEach(line => {
    const m = [...line.matchAll(/\[(\d+):(\d+)(?:[.:](\d+))?\]/g)];
    const text = line.replace(/\[[^\]]*\]/g, '').trim();
    if (!text) return;
    m.forEach(x => { const ms = x[3] ? +('0.' + x[3].padEnd(3, '0').slice(0, 3)) : 0; lines.push({ t: +x[1] * 60 + +x[2] + ms, text }); });
  });
  if (lines.length) { lines.sort((a, b) => a.t - b.t); state.lyrics = lines; $('#np-lyric').innerHTML = lines.map(l => `<div class="lrc-line" data-t="${l.t}">${esc(l.text)}</div>`).join(''); $$('#np-lyric .lrc-line').forEach(el => el.onclick = () => { if (isFinite(audio.duration) || state.lyrics.length) audio.currentTime = +el.dataset.t + 0.1; }); syncLyric(audio.currentTime, true); }
  else { state.lyrics = [{ t: 0, text: raw.trim() }]; $('#np-lyric').innerHTML = raw.split(/\n+/).map(x => `<div class="lrc-line">${esc(x.trim())}</div>`).join(''); }
}
function lyricUnavailableHTML(msg){
  return `<div class="lrc-line" style="text-align:center;margin-top:34%">${esc(msg)}<br><span id="lrc-retry" style="font-size:12px;color:rgba(0,0,0,.4);cursor:pointer;text-decoration:underline">点击重试</span> · <span class="lrc-addlink" id="lrc-add">手动添加歌词</span></div>`;
}
function bindLrcExtras(t){
  const rb = document.querySelector('#lrc-retry'); if (rb) rb.onclick = () => loadLyric(t, true);
  const ab = document.querySelector('#lrc-add'); if (ab) ab.onclick = () => openLyricEditor(t);
}
function openLyricEditor(t){
  t = t || currentTrack(); if (!t) return toast('当前没有播放歌曲');
  $('#ly-sub').textContent = `《${t.name || t.song_name}》 · ${t.artist || t.singers || ''}`;
  $('#ly-text').value = manualLyrics()[lyricKeyOf(t)] || '';
  $('#dlg-lyric').classList.add('show');
  setTimeout(() => $('#ly-text').focus(), 60);
}
$('#np-addlrc').onclick = () => openLyricEditor();
document.addEventListener('click', e => { if (e.target.closest('[data-close="dlg-lyric"]')) $('#dlg-lyric').classList.remove('show'); });
$('#ly-ok').onclick = () => {
  const t = currentTrack(); if (!t) return;
  const raw = ($('#ly-text').value || '').trim();
  const all = manualLyrics();
  if (!raw) { delete all[lyricKeyOf(t)]; toast('已清除本机歌词'); }
  else { all[lyricKeyOf(t)] = raw; toast('歌词已保存，立即显示'); }
  store.set('cm_lyrics', all);
  $('#dlg-lyric').classList.remove('show');
  if (raw && state.lyricTrackUid === (t.uid || (t.uid = uid()))) renderLrcText(raw);
  else if (!raw) loadLyric(t, true);   /* 清除本机歌词后回退到在线歌词 */
};
async function loadLyric(t, isRetry){
  state.lyrics = []; state.lyricTrackUid = t.uid || (t.uid = uid()); lastLrcIdx = -1;
  const manual = manualLyrics()[lyricKeyOf(t)];
  if (manual) { renderLrcText(manual); return; }
  $('#np-lyric').innerHTML = `<div class="lrc-line" style="text-align:center;margin-top:34%">加载歌词中...</div>`;
  try {
    const d = await api('/api/lyric', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sid: t.sid, id: t.id, name: t.name, artist: t.artist }) });
    const raw = d.lyric;
    if (state.lyricTrackUid !== t.uid) return;
    if (!raw) {
      if (!isRetry) { setTimeout(() => { if (currentTrack() === t && state.lyricTrackUid === t.uid) loadLyric(t, true); }, 2500); return; }
      $('#np-lyric').innerHTML = lyricUnavailableHTML('暂无歌词');
      bindLrcExtras(t);
      return;
    }
    renderLrcText(raw);
  } catch(err){ $('#np-lyric').innerHTML = lyricUnavailableHTML('歌词加载失败'); bindLrcExtras(t); }
}
let lastLrcIdx = -1;
function syncLyric(cur, force){
  if (!state.lyrics.length || state.lyrics.length < 2 || !state.lyrics.some(l => l.t > 0)) return;
  let i = 0; for (let j = 0; j < state.lyrics.length; j++) { if (state.lyrics[j].t <= cur + 0.2) i = j; else break; }
  if (i === lastLrcIdx && !force) return; lastLrcIdx = i;
  const els = $$('#np-lyric .lrc-line');
  els.forEach((e, j) => e.classList.toggle('on', j === i));
  const box = $('#np-lyric'), el = els[i];
  if (el && $('#nowplaying').classList.contains('show')) {
    const top = el.offsetTop - box.clientHeight / 2 + el.clientHeight / 2;
    box.scrollTo({ top, behavior: 'smooth' });
  }
}
