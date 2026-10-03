/* ================================================================
 * 快捷键与前进/后退/侧栏导航事件绑定
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 快捷键 */
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.code === 'Space') { e.preventDefault(); $('#pb-play').click(); }
  if (e.code === 'ArrowRight' && audio.currentTime < (audio.duration || 1e9)) audio.currentTime = Math.min(audio.currentTime + 5, audio.duration || audio.currentTime + 5);
  if (e.code === 'ArrowLeft') audio.currentTime = Math.max(audio.currentTime - 5, 0);
  if (e.code === 'ArrowUp') { e.preventDefault(); setVol(Math.min(audio.volume + 0.05, 1)); }
  if (e.code === 'ArrowDown') { e.preventDefault(); setVol(Math.max(audio.volume - 0.05, 0)); }
});
$('#btn-back').onclick = () => history.back();
$('#btn-fwd').onclick = () => history.forward();
$$('.nav-item[data-page]').forEach(n => n.onclick = () => nav(n.dataset.page));

