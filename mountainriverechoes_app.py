'''
Function:
    PyInstaller 打包入口。
    打包时从这里进入, 详见 packaging/mountainriverechoes.spec。

    开发态也可直接用:`python -m app`(等价入口)。
'''
from __future__ import annotations

import sys

from app.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
