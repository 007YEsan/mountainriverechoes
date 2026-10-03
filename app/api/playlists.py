'''
Function:
    歌单控制器。
      POST /api/playlist         取歌单详情: platform=ethnos(民族/专题) | index(虚拟歌单)
      GET  /api/ethnos/custom    某民族的协作增删改名单
      GET  /api/ethnos/export    协作导出(Markdown 清单)
'''
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, Response

from app.api.deps import svc
from app.domain.catalog import HAN_FOLK_GROUP, ethnic_groups
from app.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

bp = Blueprint('playlists', __name__)

# 外部平台歌单解析(网易云/QQ/汽水)需要在线拉取, 当前版本未包含, 给出明确提示而非静默失败
_EXTERNAL_HINT = '在线歌单解析尚未包含在本版本中；本地曲库(民族歌单/专题/歌手)不受影响'


@bp.post('/api/playlist')
def api_playlist() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    target = str(body.get('url') or body.get('id') or '').strip()
    platform = str(body.get('platform') or '').strip()
    if not target:
        raise ValidationError('请输入歌单链接或ID')

    if platform == 'ethnos':
        # 前端既传 key(e26) 也传族名(景颇族), 主链路同样要翻译, 否则族名一律 404
        playlist = svc('playlists').ethnos_detail(_group_key(target))
        if playlist is None:
            raise NotFoundError('歌单不存在')
        return jsonify(playlist), 200

    if platform == 'index':
        kind, _, key = target.partition(':')
        if kind not in {'artist', 'album', 'ytcoll'} or not key:
            raise ValidationError('非法索引请求')
        detail = svc('playlists').virtual_detail(kind, key)
        if detail is None:
            raise NotFoundError('索引中暂无该歌手/专辑的歌曲')
        return jsonify(detail), 200

    if platform in {'netease', 'qq', 'qq_toplist', 'soda'}:
        return jsonify({'error': _EXTERNAL_HINT}), 501
    raise ValidationError('不支持的歌单类型')


@bp.get('/api/ethnos/custom')
def api_ethnos_custom() -> tuple[dict, int]:
    group = str(request.args.get('group') or '').strip()
    if group not in _known_keys():
        raise ValidationError('未知的民族')
    from app.extensions import session_scope
    from app.repositories.playlist_repo import PlaylistRepository
    with session_scope() as session:
        playlist = PlaylistRepository(session, session.get_bind()).get_by_key(_group_key(group))
    curation = (playlist.curation if playlist else None) or {}
    keys = ('artists_added', 'artists_removed', 'artists_pinned', 'artist_order',
            'collections_removed', 'tracks_pinned', 'track_order')
    return jsonify({k: curation.get(k) or [] for k in keys}), 200


@bp.get('/api/ethnos/export')
def api_ethnos_export() -> Response:
    '''导出单个民族的 Markdown 清单; 不带 group 时输出目录页'''
    from app.repositories.playlist_repo import PlaylistRepository
    group = request.args.get('group')
    if not group:
        from app.extensions import session_scope
        with session_scope() as session:
            rows = PlaylistRepository(session, session.get_bind()).list_ethnic()
        links = ''.join(
            f'<li><a href="/api/ethnos/export?group={p.key}">{p.group_name}</a> — {p.track_count} 首</li>'
            for p in rows
        )
        return Response(
            f'<meta charset="utf-8"><h2>民族歌单导出目录</h2><ol>{links}</ol>',
            content_type='text/html; charset=utf-8',
        )

    if group not in _known_keys():
        raise ValidationError('未知的民族')
    detail = svc('playlists').ethnos_detail(_group_key(group))
    if detail is None:
        raise NotFoundError('歌单不存在')
    tracks = detail.get('tracks') or []
    lines = [
        f"# {detail.get('group')} · 音乐歌单", '',
        f"> 共 **{len(tracks)} 首**", '',
    ]
    added = (detail.get('artists_added') or [])
    removed = (detail.get('artists_removed') or [])
    if added or removed:
        lines += ['## 歌手增删名单', '']
        if added:
            lines.append('- 手动添加: ' + '、'.join(added))
        if removed:
            lines.append('- 手动移除: ' + '、'.join(removed))
        lines.append('')
    lines += ['## 曲目清单', '', '| # | 歌名 | 歌手 | 专辑 | 时长 | 音源 |',
              '|---|------|------|------|------|------|']
    for i, t in enumerate(tracks, 1):
        cell = lambda v: str(v or '').replace('|', '/')          # noqa: E731
        lines.append(
            f"| {i} | {cell(t.get('song_name'))[:60]} | {cell(t.get('singers'))} "
            f"| {cell(t.get('album'))[:24]} | {t.get('duration') or ''} "
            f"| {t.get('source_cn') or t.get('source') or ''} |"
        )
    return Response('\n'.join(lines), content_type='text/markdown; charset=utf-8')


def _known_keys() -> set[str]:
    return {g['key'] for g in ethnic_groups()} | {
        'han', HAN_FOLK_GROUP, *{g['name'] for g in ethnic_groups()},
    }


def _group_key(group: str) -> str:
    '''族名 -> 歌单 key。

    _known_keys 刻意放行了族名(前端就是这么传的), 但仓储/服务只认 e26 这类 key,
    不翻译的话 ?group=景颇族 校验能过、下游查不到就 404。命中不了即原样传。

    HAN_FOLK_GROUP(汉族民间小调)不在 ethnic_groups() 里 —— 后者只有 55 个少数民族,
    而它被 _known_keys 放行, 属于同一个洞, 所以单独补一条映射到 'han'。
    '''
    mapping = {g['name']: g['key'] for g in ethnic_groups()}
    mapping[HAN_FOLK_GROUP] = 'han'
    return mapping.get(group, group)
