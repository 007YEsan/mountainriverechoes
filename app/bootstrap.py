'''
Function:
    首次启动引导 —— 把随安装包附带的曲库数据库复制到用户数据目录。

    为什么不在 Program Files 里直接读写:
      1) 安装目录在 Windows 上常被判为只读(尤其未按管理员权限运行时), SQLite 写不进去
      2) 卸载/升级时用户已做的策展(增删歌手、拖动卡序)不该被一起删掉
    所以: 安装目录放"母本", 用户目录放"工作副本", 只有工作副本不存在时才复制。
'''
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.util_paths import app_root

logger = logging.getLogger(__name__)

# 母本相对 app 目录 / _MEIPASS 的位置
BUNDLED_DB_RELPATH = 'library/mountainriverechoes.db'


def bundled_db_path() -> Path | None:
    '''安装目录里的母本; 开发态没有母本返回 None

    候选位置按打包形态不同而异, 逐个试而不写死一处:
      1) 解包根(_internal) —— PyInstaller onedir 的默认布局
      2) sys._MEIPASS      —— 某些版本/单文件模式下 _MEIPASS 才是解包根
      3) exe 所在目录      —— 安装包把母本放在程序根目录时的布局
    '''
    import sys
    candidates: list[Path] = [Path(app_root()).parent / BUNDLED_DB_RELPATH]
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            candidates.append(Path(meipass) / BUNDLED_DB_RELPATH)
        candidates.append(Path(sys.executable).resolve().parent / BUNDLED_DB_RELPATH)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def ensure_database(db_path: Path) -> bool:
    '''工作副本不存在时从母本复制。返回是否执行了复制'''
    if db_path.exists():
        return False
    source = bundled_db_path()
    if source is None:
        logger.warning('未找到随附曲库母本, 将以空库启动(请用迁移脚本导入曲库)')
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    size_mb = source.stat().st_size / 1024 / 1024
    logger.info('首次启动: 正在复制曲库到用户数据目录 (%.0f MB)', size_mb,
                extra={'mre_db_bootstrap_mb': round(size_mb)})
    tmp = db_path.with_suffix(db_path.suffix + '.copying')
    try:
        shutil.copyfile(source, tmp)
        # WAL/SHM 不属于母本, 复制后无需处理; 改名是原子操作, 中断不会留下半截库
        tmp.replace(db_path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    logger.info('曲库初始化完成: %s', db_path)
    return True
