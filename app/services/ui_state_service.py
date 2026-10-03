'''
Function:
    UI 状态服务 —— 收藏/排序/自定义歌单等前端状态的持久化与时间戳取舍。

    时间戳规则的由来: 浏览器可能同时在多个标签页打开, 旧标签页回放旧数据会把用户
    刚拖好的顺序碾掉。所以写入时比时间戳, 服务端这份更新就不回退。
'''
from __future__ import annotations

import logging
import re
import time

from app.repositories.state_repo import StateRepository

logger = logging.getLogger(__name__)

# 白名单: 只持久化已知的 UI 态键, 防止任意内容塞进本地库
UI_KEY_RE = re.compile(
    r'^cm_(order_ethcards|order_ethrows_[\w一-鿿]{1,24}|my_playlists|pl_removed|ethnic_custom|cfg_v5)$'
)
# 时间戳合理性窗口: 超出认为是脏数据(浏览器时钟错乱/跨时区)
MAX_FUTURE_MS = 5 * 60 * 1000
MAX_AGE_MS = 365 * 24 * 3600 * 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


class UiStateService:
    def __init__(self) -> None:
        pass

    def snapshot(self) -> dict:
        from app.extensions import session_scope
        with session_scope() as session:
            repo = StateRepository(session, session.get_bind())
            entries = repo.ui_state_all()
        return {
            'v': {k: (e or {}).get('v') for k, e in entries.items()},
            't': {k: int((e or {}).get('t') or 0) for k, e in entries.items()},
        }

    def save(self, body: dict) -> dict:
        '''body: {'d': {key: 值}, 't': {key: 时间戳}}'''
        if not isinstance(body, dict):
            return {'ok': False, 'written': 0, 'keys': 0}
        data = body.get('d') if isinstance(body.get('d'), dict) else body
        stamps = body.get('t') if isinstance(body.get('t'), dict) else {}
        now = _now_ms()
        written = 0
        kept = 0

        from app.extensions import session_scope
        with session_scope() as session:
            repo = StateRepository(session, session.get_bind())
            entries = repo.ui_state_all()
            for raw_key, value in data.items():
                key = str(raw_key)
                if not UI_KEY_RE.match(key):
                    continue
                stamp = self._sane_ts(stamps.get(key, now), now)
                prev = entries.get(key) or {}
                if prev and stamp < self._stamp_floor(int(prev.get('t') or 0), now):
                    continue                       # 服务端这份更新, 不回退
                entries[key] = {'v': value, 't': stamp}
                written += 1
            for key, entry in entries.items():
                repo.ui_state_set(key, entry)
                kept += 1
        return {'ok': True, 'written': written, 'keys': kept}

    def clear(self, keys: list[str] | None = None) -> dict:
        from app.extensions import session_scope
        with session_scope() as session:
            repo = StateRepository(session, session.get_bind())
            if keys:
                for key in keys:
                    repo.ui_state_delete(str(key))
            else:
                for key in list(repo.ui_state_all()):
                    repo.ui_state_delete(key)
            remaining = len(repo.ui_state_all())
        return {'ok': True, 'keys': remaining}

    # ---------------------------------------------------------------- 时间戳
    @staticmethod
    def _sane_ts(raw: object, now: int) -> int:
        '''时间戳异常(未来/过久以前/非整数)时回落到当前时刻'''
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return now
        if value > now + MAX_FUTURE_MS:
            return now
        if value < now - MAX_AGE_MS:
            return now
        return value

    @staticmethod
    def _stamp_floor(stamp: int, now: int) -> int:
        '''已有项的时间戳下界: 比 now 还新的按 now 算, 防止脏时间戳永久锁死更新'''
        return min(stamp, now)
