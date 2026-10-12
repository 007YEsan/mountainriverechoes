# -*- coding: utf-8 -*-
"""山河回响 · 三民族版曲库母本构建脚本

只把 土族(e28) / 阿昌族(e37) / 德昂族(e44) 三个民族的歌单迁移进 SQLite，
生成打包用的曲库母本 dist/library/mountainriverechoes.db。
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.extensions import init_engine, dispose_engine
from app.database import create_schema
from app.services.migration_service import migrate_from_json

TARGETS = ['e28_土族.json', 'e37_阿昌族.json', 'e44_德昂族.json']
SRC_DIR = ROOT / 'webui' / 'ethnos_cache'
OUT_DB = ROOT / 'dist' / 'library' / 'mountainriverechoes.db'


def main() -> None:
    # 1) 建临时目录，只放三族 JSON
    tmp = ROOT / 'dist' / '_libsrc'
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob('*.json'):
        f.unlink()
    for name in TARGETS:
        shutil.copy(SRC_DIR / name, tmp / name)

    # 2) 清掉旧库，重新构建
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DB.exists():
        OUT_DB.unlink()
    for suffix in ('-wal', '-shm'):
        p = OUT_DB.with_name(OUT_DB.name + suffix)
        if p.exists():
            p.unlink()

    # 3) 建引擎 + schema + 迁移
    engine = init_engine(OUT_DB)
    create_schema(engine)
    stats = migrate_from_json(engine, cache_dir=tmp, ui_state_path=None)
    dispose_engine()

    # 4) 清理临时目录
    shutil.rmtree(tmp, ignore_errors=True)

    print('[构建完成]', OUT_DB, f'{OUT_DB.stat().st_size / 1024 / 1024:.1f} MB')
    print('[统计]', stats.as_dict())


if __name__ == '__main__':
    main()
