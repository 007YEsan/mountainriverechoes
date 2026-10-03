/* ================================================================
 * 民族音乐页：渐变配色、民族卡片与库内视图、构建民族库
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 民族音乐(55个少数民族) */
const ETH_COLORS = [['#c21500', '#ffc500'], ['#8e2de2', '#4a00e0'], ['#136a8a', '#267871'], ['#cb2d3e', '#ef473a'],
  ['#f7971e', '#ffd200'], ['#654ea3', '#eaafc8'], ['#02aab0', '#00cdac'], ['#42275a', '#734b6d'],
  ['#20002c', '#cbb4d4'], ['#3a1c71', '#d76d77']];
const ETHNIC_ORDER = ['蒙古族', '回族', '藏族', '维吾尔族', '苗族', '彝族', '壮族', '布依族', '朝鲜族', '满族',
  '侗族', '瑶族', '白族', '土家族', '哈尼族', '哈萨克族', '傣族', '黎族', '傈僳族', '佤族',
  '畲族', '高山族', '拉祜族', '水族', '东乡族', '纳西族', '景颇族', '柯尔克孜族', '土族', '达斡尔族',
  '仫佬族', '羌族', '布朗族', '撒拉族', '毛南族', '仡佬族', '锡伯族', '阿昌族', '普米族', '塔吉克族',
  '怒族', '乌孜别克族', '俄罗斯族', '鄂温克族', '德昂族', '保安族', '裕固族', '京族', '塔塔尔族', '独龙族',
  '鄂伦春族', '赫哲族', '门巴族', '珞巴族', '基诺族'];
/* 取「民族名(可带 · 后缀)」对应的多彩渐变, 与民族tab卡片同一套配色; 汉族单独用金色。
   name 形如 '蒙古族·民族音乐' 时自动按 '·' 前一段取色。 */
function ethGrad(name){
  const g = String(name || '').split('·')[0].trim();
  if (g === '汉族' || g === '汉族民间小调') return ['#8f5e0d', '#c9962c'];
  const i = ETHNIC_ORDER.indexOf(g);
  return ETH_COLORS[(i < 0 ? 0 : i) % ETH_COLORS.length];
}
/* 向白色混合 k(0~1): 得到同一色相的淡色。卡片底色统一取淡色, 文字取本色(grad[0])保证可读。 */
function mixWhite(hex, k){
  const n = parseInt(String(hex).replace('#', ''), 16);
  const f = c => Math.round(c + (255 - c) * k);
  return '#' + [f((n >> 16) & 255), f((n >> 8) & 255), f(n & 255)]
    .map(x => x.toString(16).padStart(2, '0')).join('');
}
/* 卡片用淡色渐变(默认混白 68%); 横幅 .eth-head 等需要白字的场景仍用 ethGrad 本色。 */
function ethGradSoft(name, k){ const d = ethGrad(name); k = (k == null ? .68 : k); return [mixWhite(d[0], k), mixWhite(d[1], k)]; }
async function loadEthnos(){
  try {
    const d = await api('/api/ethnos');
    const prevDone = (state.ethnos.groups || []).filter(g => g.state === 'done').length;
    state.ethnos.groups = d.groups || []; state.ethnos.building = d.building; state.ethnos.hanDone = !!(d.han && d.han.done);
    state.hanInfo = d.han || state.hanInfo || {};
    if (d.done !== prevDone) state.index.data = null;   /* 新歌单构建完成 -> 索引需要刷新 */
    renderEthnos();
    clearTimeout(state.ethnos.timer);
    if (d.building) state.ethnos.timer = setTimeout(loadEthnos, 3000);
  } catch(err){}
}
function ethCardHTML(g){
  const grad = ETH_COLORS[g.ci % ETH_COLORS.length];
  const gs = [mixWhite(grad[0], .68), mixWhite(grad[1], .68)];   /* 淡色底 + 本色字 */
  /* 卡片上不再挂「N首」角标(密集), 只保留未构建/构建中这类状态提示; 曲目数在下方的 .nm 行 */
  const st = g.state === 'done' ? '' : (g.state === 'building' ? `<span class="st building">构建中</span>` : `<span class="st">未构建</span>`);
  const spin = g.state === 'building' ? `<span class="eth-spin"><span class="spin" style="width:18px;height:18px;border-width:2px;border-top-color:#ffd76e"></span></span>` : '';
  return `<div class="pl-card eth-card" data-k="${g.key}" data-nm="${esc(g.name)}">
    <div class="cov" style="background:linear-gradient(135deg,${gs[0]},${gs[1]});color:${grad[0]};text-shadow:none">${esc(g.name)}${st}${spin}<span class="play-cov"><svg class="ic fill"><use href="#i-play"/></svg></span></div>
    <div class="nm"><span>${esc(g.name)}音乐</span><span class="ct">${g.state === 'done' ? g.count + ' 首' : '点击构建'}</span></div></div>`;
}
function renderEthnos(){
  const groups = state.ethnos.groups || [];
  const done = groups.filter(g => g.state === 'done').length + (state.ethnos.hanDone ? 1 : 0);
  const grid = $('#ethnos-grid');
  if (grid) {
    const hanCnt = (state.hanInfo && state.hanInfo.count) || 0;
    const hanCard = `<div class="pl-card eth-card" data-k="han" data-nm="汉族" title="点击进入">
      <div class="cov" style="background:linear-gradient(135deg,#8f5e0d,#c9962c)">汉族<span class="play-cov"><svg class="ic fill"><use href="#i-play"/></svg></span></div>
      <div class="nm"><span>汉族音乐</span><span class="ct">${hanCnt ? hanCnt + ' 首' : '点击构建'}</span></div></div>`;
    grid.innerHTML = groups.map(ethCardHTML).join('') + hanCard || '<div class="empty">加载中...</div>';
    const hc = grid.querySelector('.eth-card[data-k="han"]');
    if (hc) hc.onclick = () => nav('playlist', { id: 'han', platform: 'ethnos', name: '汉族 · 民族音乐' });
  }
  const prog = $('#ethnos-progress');
  if (prog) {
    const building = state.ethnos.building;
    prog.style.display = building ? '' : 'none';
    $('#ethnos-fill').style.width = (done / 55 * 100).toFixed(1) + '%';
    $('#ethnos-prog-text').textContent = `已构建 ${done} / 55 个民族歌单${building ? '，正在后台遍历音源搜索...' : ''}`;
    $('#ethnos-stop').style.display = building ? '' : 'none';
  }
  $$('.eth-card[data-k]').forEach(card => card.onclick = async () => {
    const k = card.dataset.k;
    const g = (state.ethnos.groups || []).find(x => x.key === k);
    if (g && g.state === 'building') { toast('该民族歌单正在构建中...'); return; }
    if (g && g.state !== 'done') {
      toast(`开始构建「${g.name}」歌单，遍历音源搜索约需 30~60 秒`);
      try { await api('/api/ethnos/build', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group: k }) }); } catch(err){}
      loadEthnos();
    }
    nav('playlist', { id: k, platform: 'ethnos', name: card.dataset.nm + ' · 民族音乐' });
  });
  $$('.eth-card[data-more]').forEach(card => card.onclick = () => nav('ethnos'));
}
$('#ethnos-stop').onclick = async () => {
  try { await api('/api/ethnos/build', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'stop' }) }); toast('已请求停止，完成当前民族后停止'); } catch(err){}
};

