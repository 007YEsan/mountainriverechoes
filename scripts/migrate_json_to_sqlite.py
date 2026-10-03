'''
Function:
    JSON 缓存 -> SQLite 迁移命令行入口。

用法(默认全保留: 歌词 + _song 原始快照):
    python scripts/migrate_json_to_sqlite.py
    python scripts/migrate_json_to_sqlite.py --incremental   # 只补缺失歌单(幂等, 可重复执行)
    python scripts/migrate_json_to_sqlite.py --slim          # 剔除冗余的 _song 快照(-79MB)
    python scripts/migrate_json_to_sqlite.py --no-lyrics     # 不导入歌词正文(-32MB)
    python scripts/migrate_json_to_sqlite.py --reset         # 先删库再来一遍
'''
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import load_settings                     # noqa: E402
from app.database import create_schema                    # noqa: E402
from app.extensions import init_engine                    # noqa: E402
from app.logging_setup import setup_logging               # noqa: E402
from app.services.migration_service import migrate_from_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='将旧版 JSON 曲库迁移到 SQLite')
    parser.add_argument('--db', help='目标数据库路径(默认取 MRE_DB_PATH)')
    parser.add_argument('--cache-dir', help='旧版 ethnos_cache 目录')
    parser.add_argument('--ui-state', help='旧版 ui_state.json 路径')
    parser.add_argument('--incremental', action='store_true', help='只迁移尚不存在的歌单')
    parser.add_argument('--slim', action='store_true', help='剔除冗余的 _song 原始快照(省约 79MB)')
    parser.add_argument('--no-lyrics', action='store_true', help='不导入歌词正文(省约 32MB)')
    parser.add_argument('--reset', action='store_true', help='迁移前删除已有数据库')
    parser.add_argument('--quiet', action='store_true', help='只输出结果摘要')
    args = parser.parse_args(argv)

    settings = load_settings()
    setup_logging(
        level='WARNING' if args.quiet else settings.log_level,
        json_format=settings.log_json and not args.quiet,
        log_dir=settings.log_dir,
    )

    db_path = Path(args.db).expanduser() if args.db else settings.db_path
    cache_dir = Path(args.cache_dir).expanduser() if args.cache_dir else settings.legacy_cache_dir
    ui_state = Path(args.ui_state).expanduser() if args.ui_state else settings.legacy_ui_state

    if args.reset and db_path.exists():
        for suffix in ('', '-wal', '-shm'):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        print(f'[migrate] 已删除旧库 {db_path}')

    engine = init_engine(db_path)
    create_schema(engine)

    stats = migrate_from_json(
        engine,
        cache_dir=cache_dir,
        ui_state_path=ui_state,
        include_lyrics=not args.no_lyrics,
        only_missing=args.incremental,
        keep_raw=not args.slim,
    )
    summary = stats.as_dict()
    print('\n===== 迁移结果 =====')
    for k, v in summary.items():
        if k == 'skipped_files':
            continue
        print(f'  {k:<18} {v}')
    if summary['skipped_files']:
        print(f'  跳过 {len(summary["skipped_files"])} 个文件:')
        for line in summary['skipped_files'][:10]:
            print(f'    - {line}')
    print(f'\n数据库: {db_path}')
    return 0 if not summary['skipped_files'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
