'''
Function:
    本地下载库控制器 —— 列举、播放、删除、打开目录。
'''
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, send_from_directory

from app.api.deps import svc

logger = logging.getLogger(__name__)

bp = Blueprint('files', __name__)


@bp.get('/api/files')
def api_files() -> tuple[dict, int]:
    return jsonify({'files': svc('files').list_files()}), 200


@bp.get('/files/<path:relative>')
def serve_file(relative: str):
    '''已下载音频直出。conditional=True 让 Flask 处理 Range 与 304,
    前端 <audio> 拖动进度依赖 Range 支持'''
    service = svc('files')
    service.resolve_safe(relative)                 # 越界路径会抛 ValidationError, 由全局处理器转成 400
    return send_from_directory(str(service.download_dir), relative, conditional=True)


@bp.post('/api/file/delete')
def api_file_delete() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    svc('files').delete(str(body.get('path') or ''))
    return jsonify({'ok': True}), 200


@bp.post('/api/open_folder')
def api_open_folder() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    svc('files').open_folder(str(body.get('path') or ''))
    return jsonify({'ok': True}), 200
