'''
Function:
    ORM 基类与通用列类型。
'''
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import Text, types
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_ms() -> int:
    return int(time.time() * 1000)


class JSONText(types.TypeDecorator):
    '''JSON 序列化列: 写入 dumps, 读出 loads, 失败时回退默认值'''

    impl = Text
    cache_ok = True

    def __init__(self, default: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._default = default

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None if self._default is None else self._default
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return self._default


class Base(DeclarativeBase):
    '''声明式基类。

    刻意不在这里放通用 id 主键: ui_state / meta 这类表以业务键做主键,
    基类塞 id 会静默变成 (id, key) 复合主键, 导致 UPSERT 找不到唯一约束。
    每张表自己声明主键, 意图显式优于隐式。
    '''
