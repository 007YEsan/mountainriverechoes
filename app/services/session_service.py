'''
Function:
    播放会话 —— 把歌单/检索结果注册成可播放 items, 供前端播放与下载引用。

    为什么还需要 sid: 前端的播放/下载请求带的是 {sid, picks:[曲目 id]},
    服务端需要凭 sid 找回对应的完整曲目信息(含直链), 否则每次都要把整条歌单回传。
'''
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

MAX_SESSIONS = 32
SESSION_TTL = 6 * 3600


@dataclass
class PlaySession:
    sid: str
    items: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class SessionService:
    '''线程安全的会话注册表。生命周期止于进程重启 —— 桌面端无需持久化'''

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, PlaySession] = OrderedDict()

    def new(self, items: dict[str, Any] | None = None) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._sessions[sid] = PlaySession(sid=sid, items=items or {})
            self._evict_locked()
        return sid

    def get(self, sid: str) -> PlaySession | None:
        if not sid:
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is not None:
                self._sessions.move_to_end(sid)
            return session

    def items(self, sid: str) -> dict[str, Any] | None:
        session = self.get(sid)
        return session.items if session else None

    def drop(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def _evict_locked(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.created_at > SESSION_TTL]:
            self._sessions.pop(sid, None)
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)


session_service = SessionService()
