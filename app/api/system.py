'''
Function:
    健康检查与系统控制。
      GET  /health            进程存活
      GET  /ready             依赖就绪(数据库可读 + 曲库非空)
      GET  /api/info          版本与环境摘要(不含敏感配置)
      POST /api/shutdown      退出进程(桌面端「退出」按钮用)
'''
from __future__ import annotations

import logging
import os
import threading

from flask import Blueprint, jsonify

from app import __version__
from app.api.deps import svc
from app.config import PUBLISHER
from app.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)

bp = Blueprint('system', __name__)


@bp.get('/health')
def health() -> tuple[dict, int]:
    return {'status': 'ok', 'version': __version__}, 200


@bp.get('/ready')
def ready() -> tuple[dict, int]:
    from sqlalchemy import text

    from app.extensions import get_engine
    from app.repositories.track_repo import TrackRepository
    from app.extensions import session_scope
    checks: dict[str, object] = {}
    try:
        engine = get_engine()
        with session_scope() as session:
            session.execute(text('SELECT 1'))
            tracks = TrackRepository(session, engine).count_playable()
        checks['database'] = 'ok'
        checks['playable_tracks'] = tracks
        healthy = tracks > 0
    except Exception as exc:                                       # noqa: BLE001
        logger.warning('就绪检查失败: %s', exc)
        checks['database'] = 'down'
        healthy = False
    return {'ready': healthy, 'checks': checks}, 200 if healthy else 503


@bp.get('/api/info')
def info() -> tuple[dict, int]:
    from sqlalchemy import func, select

    from app.extensions import session_scope
    from app.models import Playlist, Track
    counts = {}
    try:
        with session_scope() as session:
            counts = {
                'tracks': int(session.execute(select(func.count(Track.id))).scalar_one()),
                'playlists': int(session.execute(select(func.count(Playlist.id))).scalar_one()),
            }
    except Exception:                                              # noqa: BLE001
        counts = {'tracks': 0, 'playlists': 0}
    return {
        'version': __version__, 'publisher': PUBLISHER, 'pid': os.getpid(),
        'frozen': bool(getattr(__import__('sys'), 'frozen', False)),
        'library': counts,
    }, 200


@bp.post('/api/shutdown')
def shutdown() -> tuple[dict, int]:
    '''退出进程。留 1 秒让当前响应先发出去, 避免前端收到连接重置'''
    logger.info('收到退出请求')
    threading.Timer(1.0, _exit).start()
    return {'ok': True}, 200


def _exit() -> None:
    try:
        svc('lifecycle').shutdown()
    except Exception:                                              # noqa: BLE001
        pass
    os._exit(0)


@bp.errorhandler(DatabaseUnavailableError)
def _handle_db_unavailable(err: DatabaseUnavailableError) -> tuple[dict, int]:
    # 与全站保持一致: error 是可直接展示的文本(前端 throw new Error(d.error)), code 平级给
    return {'error': str(err), 'code': err.code}, err.http_status
