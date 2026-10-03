'''
Function:
    数据访问基础设施 —— 引擎 / 会话 / PRAGMA 调优。
    SQLite 为单文件本地库, 用 WAL + 忙等待超时支撑多线程 Flask worker 并发读。
'''
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def sqlite_version() -> tuple[int, ...]:
    return sqlite3.sqlite_version_info


def init_engine(db_path: Path, *, echo: bool = False) -> Engine:
    '''创建全局引擎(幂等)。SQLite 必须关掉同线程检查以支持 Flask threaded 模式'''
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine

    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f'sqlite:///{db_path.as_posix()}'
    engine = create_engine(
        url,
        echo=echo,
        future=True,
        connect_args={'check_same_thread': False, 'timeout': 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001, ANN202
        cur = dbapi_connection.cursor()
        cur.execute('PRAGMA journal_mode=WAL')          # 读写并发: 读不阻塞写
        cur.execute('PRAGMA synchronous=NORMAL')        # WAL 下的安全/性能平衡点
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA busy_timeout=30000')        # 写锁争用时等 30s 再报错
        cur.execute('PRAGMA cache_size=-64000')         # ~64MB 页缓存
        cur.execute('PRAGMA temp_store=MEMORY')
        cur.close()

    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    logger.info(
        '数据库引擎就绪 path=%s sqlite=%s', db_path.as_posix(), '.'.join(map(str, sqlite_version())),
        extra={'mre_db_path': str(db_path)},
    )
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError('数据库引擎尚未初始化, 请先调用 init_engine()')
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    '''一次业务操作一个会话: 正常提交, 异常回滚并抛出'''
    factory = _SessionFactory
    if factory is None:
        raise RuntimeError('数据库尚未初始化, 请先调用 init_engine()')
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    '''优雅停机时释放连接'''
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
        logger.info('数据库引擎已释放')
    _engine, _SessionFactory = None, None
