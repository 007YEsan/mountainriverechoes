'''
Function:
    UI 状态控制器 —— 卡片顺序/我的歌单/隐藏曲目等服务端持久化。
'''
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.api.deps import svc
from app.errors import ValidationError

logger = logging.getLogger(__name__)

bp = Blueprint('ui', __name__)


@bp.get('/api/ui/state')
def get_state() -> tuple[dict, int]:
    return jsonify(svc('ui_state').snapshot()), 200


@bp.post('/api/ui/state')
def save_state() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        raise ValidationError('需要 JSON 对象')
    return jsonify(svc('ui_state').save(body)), 200


@bp.delete('/api/ui/state')
def clear_state() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    keys = body.get('keys') if isinstance(body, dict) else None
    if keys is not None and not isinstance(keys, list):
        raise ValidationError('keys 需为字符串数组')
    return jsonify(svc('ui_state').clear(keys)), 200
