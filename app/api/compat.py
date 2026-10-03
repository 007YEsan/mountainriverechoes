'''
Function:
    兼容与降级端点 —— 前端会调但在新架构下语义已变化的旧接口。

    /api/ethnos/build  曲库由迁移一次性灌入 SQLite, 不再有「后台构建」阶段,
                       这里给出明确回执而不是让前端空等一个不会来的进度。
    /api/playlist/text 粘贴文本曲目清单 -> 逐行在本地/全网匹配, 用于一次性导入歌单。
'''
from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request

from app.api.deps import svc
from app.errors import ValidationError

logger = logging.getLogger(__name__)

bp = Blueprint('compat', __name__)

_MAX_TEXT_LINES = 200
# 「歌名 - 歌手」「歌名(歌手)」两种常见写法
_LINE_SPLIT = re.compile(r'\s+[-–—]\s+|\s*[（(]\s*[^）)]*\s*[）)]\s*$')


@bp.post('/api/ethnos/build')
def api_ethnos_build() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    if str(body.get('action') or '') == 'stop':
        return jsonify({'ok': True}), 200
    return jsonify({
        'ok': True, 'started': False,
        'reason': '曲库已随安装包内置到 SQLite, 无需再构建；如需更新请替换数据库文件',
    }), 200


@bp.post('/api/playlist/text')
def api_playlist_text() -> tuple[dict, int]:
    '''把粘贴的「歌名 - 歌手」清单解析成曲目; 本地曲库命中优先, 未命中的返回待补列表'''
    body = request.get_json(force=True, silent=True) or {}
    raw = str(body.get('text') or body.get('content') or '')
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise ValidationError('请粘贴曲目清单')
    if len(lines) > _MAX_TEXT_LINES:
        lines = lines[:_MAX_TEXT_LINES]

    from app.extensions import session_scope
    from app.repositories.track_repo import TrackRepository
    from app.domain.normalize import norm_str

    matched: list[dict] = []
    missing: list[str] = []
    with session_scope() as session:
        repo = TrackRepository(session, session.get_bind())
        for line in lines:
            name = _LINE_SPLIT.sub(' ', line).strip()
            query = norm_str(name)[:40]
            hit = None
            if len(query) >= 2:
                result = repo.search_library(query, limit=1)
                hit = result.tracks[0] if result.tracks else None
            if hit is None:
                missing.append(line)
            else:
                matched.append({**hit, 'sid': None})
    return jsonify({
        'id': 'text-import', 'name': '文本导入',
        'count': len(matched), 'tracks': matched,
        'missing': missing, 'platform': 'text', 'platform_name': '文本清单导入',
    }), 200
