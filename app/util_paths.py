'''
Function:
    打包资源定位 —— 区分「开发态读仓库」与「打包态读 _MEIPASS」。

    PyInstaller 单目录模式下, 数据文件被解包到 sys._MEIPASS 指向的临时目录,
    而不是 exe 所在目录, 所以必须按 _MEIPASS 找模板/静态资源。
'''
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    '''app 包所在目录(打包态为 _MEIPASS/app)。

    本文件路径是 app/util_paths.py, parent 才是 app 包目录;
    写成 parents[1] 会越过一层指到仓库根, 模板/静态就找不到了。
    '''
    if getattr(sys, 'frozen', False):
        meipass = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
        return meipass / 'app'
    return Path(__file__).resolve().parent


def template_dir() -> Path:
    return app_root() / 'templates'


def static_dir() -> Path:
    return app_root() / 'static'


def repo_root() -> Path:
    '''仓库根: 打包态没有仓库, 返回 app 所在目录的上一级'''
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]
