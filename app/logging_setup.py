'''
Function:
    结构化日志 —— 统一 JSON 输出 + 全链路 request_id。
    严禁记录: 访问口令、完整 cookie、歌词正文等隐私/大体量内容。
'''
from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUEST_ID_KEY = 'request_id'
_request_id: ContextVar[str] = ContextVar(REQUEST_ID_KEY, default='-')


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


class JsonFormatter(logging.Formatter):
    '''单行 JSON, 便于 exe 场景下用文件采集排查'''

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
            REQUEST_ID_KEY: getattr(record, REQUEST_ID_KEY, get_request_id()),
        }
        # 结构化附加字段
        for key, value in record.__dict__.items():
            if key.startswith('mre_'):
                payload[key[4:]] = value
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__('%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s')

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, REQUEST_ID_KEY):
            record.__dict__[REQUEST_ID_KEY] = get_request_id()
        return super().format(record)


class RequestIdFilter(logging.Filter):
    '''把当前上下文的 request_id 注入每条日志'''

    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__[REQUEST_ID_KEY] = get_request_id()
        return True


_LOGGER_NAMES = ('mre', 'app')


def setup_logging(*, level: str, json_format: bool, log_dir: Path | None, console: bool = True) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt: logging.Formatter = JsonFormatter() if json_format else PlainFormatter()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        console_handler.addFilter(RequestIdFilter())
        root.addHandler(console_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.StreamHandler(
            (log_dir / 'mountainriverechoes.log').open('a', encoding='utf-8')
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(RequestIdFilter())
        root.addHandler(file_handler)

    # 关掉 werkzeug 默认的逐请求 INFO 噪音, 交由 access log 逻辑自己打
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


class Timer:
    '''轻量耗时统计: with Timer() as t: ... -> t.ms'''

    __slots__ = ('_start', 'ms')

    def __enter__(self) -> 'Timer':
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = round((time.perf_counter() - self._start) * 1000, 2)
