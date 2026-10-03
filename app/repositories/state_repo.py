'''
Function:
    状态仓储 —— 前端 UI 状态与库级元数据的键值读写。
'''
from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import MetaEntry, UiState
from app.models.base import now_ms


class StateRepository:
    def __init__(self, session: Session, engine: Engine) -> None:
        self.session = session
        self.engine = engine

    # ---------------------------------------------------------------- UI 状态
    def ui_state_all(self) -> dict[str, Any]:
        rows = self.session.execute(select(UiState)).scalars().all()
        return {r.key: r.value for r in rows}

    def ui_state_get(self, key: str) -> Any:
        row = self.session.get(UiState, key)
        return row.value if row else None

    def ui_state_set(self, key: str, value: Any) -> None:
        stmt = (
            sqlite_insert(UiState)
            .values(key=key, value=value, updated_at=now_ms())
            .on_conflict_do_update(index_elements=['key'], set_={'value': value, 'updated_at': now_ms()})
        )
        self.session.execute(stmt)

    def ui_state_delete(self, key: str) -> None:
        row = self.session.get(UiState, key)
        if row is not None:
            self.session.delete(row)

    # ---------------------------------------------------------------- 库级元数据
    def meta_get(self, key: str, default: Any = None) -> Any:
        row = self.session.get(MetaEntry, key)
        return row.value if row else default

    def meta_set(self, key: str, value: Any) -> None:
        self.session.execute(
            sqlite_insert(MetaEntry)
            .values(key=key, value=value, updated_at=now_ms())
            .on_conflict_do_update(index_elements=['key'], set_={'value': value, 'updated_at': now_ms()})
        )
