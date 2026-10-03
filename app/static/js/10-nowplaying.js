/* ================================================================
 * 播放页：打开/关闭与页内下载、喜欢
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* 播放页 */
function openNowPlaying(){ const t = currentTrack(); if (!t) { toast('当前没有播放歌曲'); return; } $('#nowplaying').classList.add('show'); $('#content').classList.add('np-open'); syncLyric(audio.currentTime, true); }
function closeNowPlaying(){ $('#nowplaying').classList.remove('show'); $('#content').classList.remove('np-open'); }
$('#pb-cover').onclick = openNowPlaying; $('#pb-name').onclick = openNowPlaying;
$('#np-close').onclick = closeNowPlaying;
$('#btn-lyricpage').onclick = openNowPlaying;
/* 播放条/播放页 下载与喜欢 */
function downloadCurrent(){ const t = currentTrack(); if (!t) { toast('当前没有播放歌曲'); return; } openMsDialog(t); }
$('#pb-dl').onclick = downloadCurrent;
$('#np-dl').onclick = downloadCurrent;
$('#np-heart').onclick = () => toggleFav(currentTrack());

