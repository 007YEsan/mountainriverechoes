'''
Function:
    页面与索引控制器。
      GET /                      前端 SPA 页面(服务端渲染外壳 + 模块化静态资源)
      GET /api/index             全局索引(歌手/歌单/统计)
      GET /api/index/sig         索引签名, 变了前端才重拉
      GET /api/index/search      本地曲库歌名检索
      GET /api/topics            专题曲库列表
      GET /api/ethnos            民族歌单构建状态(前端「民族音乐」页用它显示进度)
'''
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from app.api.deps import svc

logger = logging.getLogger(__name__)

bp = Blueprint('library', __name__)


@bp.get('/')
def index() -> str:
    return render_template('index.html')


@bp.get('/api/index')
def api_index() -> tuple[dict, int]:
    return jsonify(svc('library').index_payload()), 200


@bp.get('/api/index/sig')
def api_index_sig() -> tuple[dict, int]:
    sig = svc('library').index_signature()
    return jsonify({'sig': sig, 'n': len(sig)}), 200


@bp.get('/api/index/search')
def api_index_search() -> tuple[dict, int]:
    library = svc('library')
    payload = library.search_library(
        (request.args.get('q') or '').strip(),
        group=(request.args.get('group') or '').strip() or None,
        limit=request.args.get('limit'),
        offset=request.args.get('offset'),
    )
    return jsonify(payload), 200


@bp.get('/api/topics')
def api_topics() -> tuple[dict, int]:
    return jsonify({'topics': svc('library').list_topics()}), 200


@bp.get('/api/ethnos')
def api_ethnos() -> tuple[dict, int]:
    '''民族歌单构建状态。曲库由迁移一次性灌入, 不再有「正在构建」的中间态'''
    from app.extensions import session_scope
    from app.repositories.playlist_repo import PlaylistRepository
    with session_scope() as session:
        playlists = PlaylistRepository(session, session.get_bind()).list_ethnic()
        groups = [
            {'key': p.key, 'name': p.group_name, 'state': 'done', 'count': p.track_count}
            for p in playlists
        ]
    return jsonify({
        'groups': groups, 'building': False,
        'done': sum(1 for g in groups if g['count'] > 0),
        'total': len(groups),
        'han': {'state': 'done', 'count': next((g['count'] for g in groups if g['key'] == 'han'), 0),
                'done': True},
    }), 200
