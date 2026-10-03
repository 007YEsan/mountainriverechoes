'''
Function:
    数据库 schema 引导 —— 建表、建全文索引(FTS5)、挂同步触发器。
    设计要点:
      - 中文检索用 trigram 分词(SQLite>=3.34), 因为 unicode61 会把整串汉字当成一个 token,
        搜「景颇」命中不了「景颇族民歌」。
      - 外部内容表(content='tracks')不重复存正文, 靠三个触发器保持同步。
'''
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from app.models import Base

logger = logging.getLogger(__name__)

FTS_TABLE = 'tracks_fts'
# trigram 要求 SQLite >= 3.34
_MIN_TRIGRAM = (3, 34, 0)

_state: dict[str, Any] = {'fts_ready': False, 'tokenizer': None}


def fts_ready() -> bool:
    '''全文索引是否可用; 不可用时上层回退到 LIKE 检索'''
    return bool(_state['fts_ready'])


def fts_tokenizer() -> str | None:
    return _state['tokenizer']


def sqlite_supports_trigram(engine: Engine) -> bool:
    import sqlalchemy

    with engine.connect() as conn:
        ver = conn.exec_driver_sql('select sqlite_version()').scalar() or ''
    parts = tuple(int(x) for x in str(ver).split('.')[:3] if x.isdigit())
    return len(parts) == 3 and parts >= _MIN_TRIGRAM


def _has_trigger(conn: Any, name: str) -> bool:
    row = conn.execute(
        text('select 1 from sqlite_master where type=:t and name=:n'), {'t': 'trigger', 'n': name},
    ).first()
    return row is not None


def ensure_fts(engine: Engine) -> None:
    '''幂等建立 FTS 虚表与触发器。任何失败都不阻断服务, 只是退化成 LIKE 检索'''
    tokenizer = 'trigram' if sqlite_supports_trigram(engine) else 'unicode61'
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text('select 1 from sqlite_master where type=:t and name=:n'),
                {'t': 'table', 'n': FTS_TABLE},
            ).first()
            if not exists:
                conn.exec_driver_sql(
                    f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5("
                    f"song_name, singers, album, content='tracks', content_rowid='id', "
                    f"tokenize='{tokenizer}')"
                )
            for tname, sql in (
                (f'{FTS_TABLE}_ai',
                 f"CREATE TRIGGER {FTS_TABLE}_ai AFTER INSERT ON tracks BEGIN "
                 f"INSERT INTO {FTS_TABLE}(rowid, song_name, singers, album) "
                 f"VALUES (new.id, new.song_name, new.singers, new.album); END"),
                (f'{FTS_TABLE}_ad',
                 f"CREATE TRIGGER {FTS_TABLE}_ad AFTER DELETE ON tracks BEGIN "
                 f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, song_name, singers, album) "
                 f"VALUES ('delete', old.id, old.song_name, old.singers, old.album); END"),
                (f'{FTS_TABLE}_au',
                 f"CREATE TRIGGER {FTS_TABLE}_au AFTER UPDATE ON tracks BEGIN "
                 f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, song_name, singers, album) "
                 f"VALUES ('delete', old.id, old.song_name, old.singers, old.album); "
                 f"INSERT INTO {FTS_TABLE}(rowid, song_name, singers, album) "
                 f"VALUES (new.id, new.song_name, new.singers, new.album); END"),
            ):
                if not _has_trigger(conn, tname):
                    conn.exec_driver_sql(sql)
        _state.update(fts_ready=True, tokenizer=tokenizer)
        logger.info('全文索引就绪 table=%s tokenizer=%s', FTS_TABLE, tokenizer,
                    extra={'mre_fts_tokenizer': tokenizer})
    except Exception as exc:      # noqa: BLE001 - FTS 属增强能力, 失败必须降级而非崩服务
        _state.update(fts_ready=False, tokenizer=None)
        logger.warning('全文索引不可用, 检索将退化为 LIKE: %s', exc, extra={'mre_fts_error': str(exc)})


def rebuild_fts(engine: Engine) -> None:
    '''全量重建索引: 迁移或数据修复后调用'''
    if not _state['fts_ready']:
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')")


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    ensure_fts(engine)


def initialise(db_path: Path, engine: Engine) -> None:
    '''完整建库入口'''
    db_path.parent.mkdir(parents=True, exist_ok=True)
    create_schema(engine)
    logger.info('schema 校验完成 db=%s', db_path.name, extra={'mre_db_size_bytes': _safe_size(db_path)})


def _safe_size(db_path: Path) -> int:
    try:
        return db_path.stat().st_size
    except OSError:
        return -1
