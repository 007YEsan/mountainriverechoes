/* ================================================================
 * 音源设置弹窗、顶栏设置与关机按钮
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 音源设置 */
async function loadSources(){
  const d = await api('/api/sources');
  state.allSources = d.all; state.srcNames = d.names || {}; state.fast = d.fast || [];
  state.defaults = [...(d.default || [])];
  const validate = arr => (arr || []).filter(s => d.all.includes(s));
  // 已保存配置的来源: 若与后端当前默认不同(后端调了默认源), 以后端为准 — 否则用户会一直用着旧默认而不自知
  // key 换到 v5: 存的形状从 {search,download} 变成单数组, 旧值 Array.isArray 判 false 自然回落默认, 无需迁移
  const saved = store.get('cm_cfg_v5', null);
  if (saved && !(Array.isArray(saved) && saved.length && saved.join() === (d.default || []).join())) {
    store.set('cm_cfg_stale', true);
  }
  state.cfg = (Array.isArray(saved) && saved.length) ? validate(saved) : [...state.defaults];
  if (!state.cfg.length) state.cfg = [...state.defaults];
}
function openSettings(){
  const mk = (box, list) => {
    box.innerHTML = state.allSources.map(s => {
      const isFast = state.fast.includes(s);
      return `<label class="${list.includes(s) ? 'on' : ''}" data-s="${s}"><input type="checkbox" ${list.includes(s) ? 'checked' : ''}>${isFast ? '<span style="color:var(--red);flex:none" title="实测较快">⚡</span>' : ''}<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(state.srcNames[s] || s)}</span></label>`;
    }).join('');
    box.querySelectorAll('label').forEach(l => l.onclick = e => { e.preventDefault(); l.classList.toggle('on'); const on = l.classList.contains('on'); l.querySelector('input').checked = on; });
  };
  mk($('#set-search'), state.cfg);
  $('#dlg-set').classList.add('show');
}
$('#set-reset').onclick = () => { state.cfg = [...state.defaults]; openSettings(); };
$('#set-save').onclick = () => {
  const pick = box => [...box.querySelectorAll('label.on')].map(l => l.dataset.s);
  state.cfg = pick($('#set-search'));
  if (!state.cfg.length) state.cfg = [...state.defaults];
  store.set('cm_cfg_v5', state.cfg); $('#dlg-set').classList.remove('show'); toast('音源设置已保存');
};
$('#btn-settings').onclick = openSettings;
$('#btn-power').onclick = async () => { if (confirm('确定关闭 musicdl 服务吗？')) { try { await api('/api/shutdown', { method: 'POST' }); } catch(e){} toast('服务已关闭'); } };

