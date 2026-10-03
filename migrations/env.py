'''
Function:
    Alembic 环境钩子 —— 把「运行时 create_schema() 建表」升级为可版本化的迁移。

    设计约定:
      - 数据库地址一律来自 app.config.load_settings().db_path, 不写死在 ini 里,
        因此 MRE_DB_PATH / MRE_DATA_DIR 对 alembic 和运行时完全同效。
      - target_metadata 直接指向 ORM 的 Base.metadata, 保证迁移与建表同源,
        不会出现「ORM 改了但迁移没跟上」的漂移。
      - 这是维护者工具, 不进 exe 打包产物(packaging 的 excludes 已排除 alembic);
        运行期建表入口仍是 app.database.create_schema(), 运行时行为不变。
'''
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Engine, create_engine

# env.py 是以文件路径方式被 alembic 加载的, 不能假设仓库根已在 sys.path —— 显式补上
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import load_settings            # noqa: E402  必须在 sys.path 补全之后
from app.models import Base                     # noqa: E402  导入即注册全部 7 张表

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    '''从运行配置推导 sqlite 地址; ini 里的 sqlalchemy.url 保持为空'''
    db_path = load_settings().db_path.expanduser()
    # 与 app.database.initialise() 对齐: sqlite 自己不会建父目录
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f'sqlite:///{db_path}'
    config.set_main_option('sqlalchemy.url', url)
    return url


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    '''离线模式: 只生成 SQL, 不连库'''
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    '''在线模式: 直接对 sqlite 文件执行'''
    engine: Engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
