/* ================================================================
 * 我喜欢的音乐：列表渲染与播放
 * ----------------------------------------------------------------
 * 本文件由 mountainriverechoes.html 的内联 <script> 原样拆分而来，
 * 内容与顺序均未做任何修改（纯搬运）。加载顺序见 index.html。
 * ================================================================ */
/* ================================================================ 我喜欢的音乐 */
function renderFavorites(){
  $('#fav-meta').innerHTML = `共 <b>${state.favs.length}</b> 首`;
  $('#fav-empty').style.display = state.favs.length ? 'none' : '';
  const items = state.favs;
  $('#fav-tbody').innerHTML = items.map((f, i) => `<tr data-i="${i}">
    <td class="td-index"><span class="num">${String(i + 1).padStart(2, '0')}</span><span class="pbtn"><svg class="ic sm fill"><use href="#i-play"/></svg></span></td>
    <td class="td-name"><div class="inner"><span class="t">${esc(f.name)}</span></div></td>
    <td class="td-singer">${esc(f.artist || '')}</td><td class="td-album">${esc(f.album || '')}</td>
    <td><span class="srctag" style="background:#9aa0a6">自动解析</span></td>
    <td class="td-time">${esc(f.duration || '--:--')}</td>
    <td class="td-act"><button class="a-fav faved"><svg class="ic sm fill"><use href="#i-heart"/></svg></button><button class="a-dl"><svg class="ic sm"><use href="#i-download"/></svg></button><button class="a-add"><svg class="ic sm"><use href="#i-plus"/></svg></button></td></tr>`).join('');
  $$('#fav-tbody tr').forEach(tr => {
    const f = items[+tr.dataset.i];
    const track = { ...f, source_cn: '自动解析' };
    tr.querySelector('.pbtn').onclick = e => { e.stopPropagation(); playTrack(track, { list: items.map(x => ({ ...x, source_cn: '自动解析' })) }); };
    tr.onclick = () => tr.querySelector('.pbtn').click();
    tr.querySelector('.a-fav').onclick = e => { e.stopPropagation(); toggleFav(f); };
    const apl = tr.querySelector('.a-pl'); if (apl) apl.onclick = e => { e.stopPropagation(); openAddToPlaylist(track); };
    tr.querySelector('.a-dl').onclick = e => { e.stopPropagation(); openMsDialog(track); };
    tr.querySelector('.a-add').onclick = e => { e.stopPropagation(); addToQueue(track, false); };
  });
}
$('#fav-playall').onclick = () => { if (!state.favs.length) return toast('喜欢的列表是空的'); playTrack({ ...state.favs[0] }, { list: state.favs.map(x => ({ ...x })) }); };

