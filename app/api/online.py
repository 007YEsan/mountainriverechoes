'''
Function:
    在线能力控制器 —— 全网搜索、播放代理、封面代理、歌词、下载任务。
'''
from __future__ import annotations

import logging
from typing import Any

import requests
from flask import Blueprint, jsonify, request, Response

from app.api.deps import svc
from app.errors import NotFoundError, ValidationError
from app.logging_setup import get_request_id

logger = logging.getLogger(__name__)

bp = Blueprint('online', __name__)

# 网易云/QQ/汽水的预置榜单: 长期稳定的官方榜单 id, 与旧版一致
NETEASE_CHARTS = [
    {'id': '3778678', 'name': '热歌榜', 'desc': '云音乐热歌榜', 'grad': ['#ff5f6d', '#ffc371']},
    {'id': '3779629', 'name': '新歌榜', 'desc': '云音乐新歌榜', 'grad': ['#36d1dc', '#5b86e5']},
    {'id': '19723756', 'name': '飙升榜', 'desc': '云音乐飙升榜', 'grad': ['#f7971e', '#ffd200']},
    {'id': '2884035', 'name': '原创榜', 'desc': '云音乐原创榜', 'grad': ['#834d9b', '#d04ed6']},
    {'id': '71385702', 'name': 'ACG音乐榜', 'desc': '云音乐ACG音乐榜', 'grad': ['#654ea3', '#eaafc8']},
    {'id': '991319590', 'name': '说唱榜', 'desc': '云音乐说唱榜', 'grad': ['#0f2027', '#2c5364']},
]
QQ_CHARTS = [
    {'id': '26', 'kind': 'toplist', 'name': '热歌榜', 'desc': '巅峰榜·热歌', 'grad': ['#f5515f', '#9f041b']},
    {'id': '27', 'kind': 'toplist', 'name': '新歌榜', 'desc': '巅峰榜·新歌', 'grad': ['#00b4db', '#0083b0']},
    {'id': '4', 'kind': 'toplist', 'name': '流行指数榜', 'desc': '巅峰榜·流行指数', 'grad': ['#f7971e', '#fd9853']},
    {'id': '62', 'kind': 'toplist', 'name': '巅峰飙升榜', 'desc': '巅峰榜·飙升', 'grad': ['#7f00ff', '#e100ff']},
]
SODA_PRESETS = [
    {'id': '7573986162419908648', 'name': '安静曲', 'desc': '汽水精选·安静曲', 'grad': ['#43cea2', '#185a9d']},
]
PRESET_PLAYLISTS = [
    {'platform': 'netease', 'platform_name': '网易云音乐', 'color': '#d33a31', 'items': NETEASE_CHARTS},
    {'platform': 'qq', 'platform_name': 'QQ音乐', 'color': '#31c27c', 'items': QQ_CHARTS},
    {'platform': 'soda', 'platform_name': '汽水音乐', 'color': '#ff5252', 'items': SODA_PRESETS},
]

_PROXY_TIMEOUT = (10, 60)


# ---------------------------------------------------------------- 搜索
@bp.get('/api/sources')
def api_sources() -> tuple[dict, int]:
    return jsonify(svc('online').available_sources()), 200


@bp.post('/api/search')
def api_search() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    payload = svc('online').start_search(
        keyword=str(body.get('keyword') or ''),
        sources=body.get('sources'),
    )
    return jsonify(payload), 200


@bp.get('/api/search/status')
def api_search_status() -> tuple[dict, int]:
    return jsonify(svc('online').status(str(request.args.get('job') or ''))), 200


# ---------------------------------------------------------------- 播放 / 封面 / 歌词
@bp.get('/api/preview')
def api_preview():
    '''按 sid+id 取出会话里的曲目, 代理其音频直链(补 Referer 防盗链 + 支持 Range)'''
    sid = str(request.args.get('sid') or '')
    item_id = str(request.args.get('id') or '')
    item = _session_item(sid, item_id)
    if item is None:
        raise NotFoundError('曲目不存在或会话已过期')

    url = svc('media').resolve_stream_url(item)
    if not url:
        raise NotFoundError('该曲没有可用的播放链接')
    if url.startswith('file://') or url.startswith('/'):
        raise ValidationError('不支持的播放地址')

    headers = svc('media').request_headers(url, range_header=request.headers.get('Range'))
    upstream = requests.get(url, headers=headers, stream=True, timeout=_PROXY_TIMEOUT)
    # 直链是抓取时缓存的, 音乐会 CDN 普遍带时效(实测约三成已过期, 返回 403/410)。
    # 这里统一转成 404 —— 前端看到 404 会走「全网重搜同名曲」兜底, 比把 CDN 的 HTML
    # 错误页当音频塞给 <audio> 好得多。
    if upstream.status_code >= 400:
        upstream.close()
        logger.info('直链失效 upstream=%s url=%s', upstream.status_code, url[:120])
        raise NotFoundError('该曲链接已失效，请重新搜索')
    media_type = upstream.headers.get('Content-Type', 'application/octet-stream')
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key.lower() in {'content-length', 'content-range', 'accept-ranges', 'etag', 'last-modified'}
    }
    response_headers['X-Request-Id'] = get_request_id()
    downstream = request.headers.get('Range')
    status = 206 if downstream and upstream.status_code == 206 else upstream.status_code
    return Response(
        _iter_qt(upstream), status=status,
        content_type=media_type, headers=response_headers, direct_passthrough=True,
    )


def _iter_qt(resp: Any):
    with resp:
        yield from resp.iter_content(chunk_size=64 * 1024)


@bp.get('/api/cover')
def api_cover():
    '''封面代理: 音乐 CDN 普遍有防盗链与跨域限制, 直接让浏览器拉会被拦'''
    from urllib.parse import unquote
    raw = request.args.get('url') or ''
    url = unquote(raw)
    if not url.startswith(('http://', 'https://')):
        raise ValidationError('封面地址不合法')
    headers = svc('media').request_headers(url)
    upstream = requests.get(url, headers=headers, timeout=_PROXY_TIMEOUT)
    return Response(
        upstream.content, status=upstream.status_code,
        content_type=upstream.headers.get('Content-Type', 'image/jpeg'),
    )


@bp.post('/api/lyric')
def api_lyric() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    sid = str(body.get('sid') or '')
    item_id = str(body.get('id') or '')
    if item_id:
        _session_item(sid, item_id)
    content = svc('media').get_lyric(
        item=_session_item(sid, item_id), item_id=item_id,
        name=str(body.get('name') or ''), artist=str(body.get('artist') or ''),
    )
    return jsonify({'lyric': content or ''}), 200


# ---------------------------------------------------------------- 下载
@bp.post('/api/download')
def api_download() -> tuple[dict, int]:
    body = request.get_json(force=True, silent=True) or {}
    sid = str(body.get('sid') or '')
    picks = body.get('picks') or []
    if not isinstance(picks, list):
        raise ValidationError('picks 需为数组')

    payloads = []
    for pick in picks:
        item_id = pick.get('id') if isinstance(pick, dict) else pick
        item = _session_item(sid, str(item_id))
        if item is not None:
            payloads.append((sid, str(item_id), item))
    if not payloads:
        raise ValidationError('会话已过期或没有可下载的曲目，请重新搜索')
    return jsonify({'task_ids': svc('download').submit(payloads)}), 200


@bp.get('/api/tasks')
def api_tasks() -> tuple[dict, int]:
    return jsonify(svc('download').list_tasks()), 200


@bp.post('/api/tasks/clear')
def api_tasks_clear() -> tuple[dict, int]:
    svc('download').clear_finished()
    return jsonify({'ok': True}), 200


# ---------------------------------------------------------------- 预置榜单
@bp.get('/api/charts')
def api_charts() -> tuple[dict, int]:
    return jsonify({'charts': NETEASE_CHARTS}), 200


@bp.get('/api/presetplaylists')
def api_preset_playlists() -> tuple[dict, int]:
    return jsonify({'presets': PRESET_PLAYLISTS}), 200


# ---------------------------------------------------------------- 会话工具
def _session_item(sid: str, item_id: str) -> Any:
    items = svc('sessions').items(sid)
    return items.get(item_id) if items else None
