# -*- mode: python ; coding: utf-8 -*-
'''
Function:
    PyInstaller 打包脚本(单目录模式 onedir)。

    用法:
        pyinstaller packaging/mountainriverechoes.spec --noconfirm

    产物: dist/mountainriverechoes/mountainriverechoes.exe

    注意两个坑(都踩过):
      1) yt-dlp 的提取器是惰性导入的, 不显式收集会报 "extractor not found"
      2) musicdl 的音源客户端靠注册表动态发现, 必须整包收集子模块
'''
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent          # noqa: F821  仓库根

# 图标按平台挑选: Windows 用 .ico, macOS 用 .icns; 缺了就无图标(便于本机验证打包能否跑通)
_icon_win = ROOT / 'packaging' / 'mountainriverechoes.ico'
_icon_mac = ROOT / 'packaging' / 'mountainriverechoes.icns'
ICON = str(_icon_win if sys.platform == 'win32' else _icon_mac)
if not Path(ICON).exists():
    ICON = None

hiddenimports = []
# 本项目自身的子模块必须显式收集: 蓝图是 app/factory.py 里用 importlib 动态导入的,
# PyInstaller 的静态分析看不到, 漏了就会在打包后报 "No module named 'app.api.xxx'
# 且静默降级为「蓝图未启用」(实测: 只有静态 import 的 system 蓝图活着, 其余全残废)。
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('musicdl')
hiddenimports += collect_submodules('yt_dlp.extractor')
hiddenimports += collect_submodules('yt_dlp.postprocessor')
hiddenimports += [
    # SQLAlchemy 的方言与连接池按字符串动态加载
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.sql.default_comparator',
    'sqlalchemy.pool',
    # 曲库解析链
    'orjson', 'pathvalidate', 'platformdirs', 'filetype', 'puremagic',
    'mutagen', 'tinytag', 'emoji', 'bleach', 'bs4', 'lxml', 'tabulate',
    # 网络栈: curl-cffi 走原生库, 缺了会静默退化成失败请求
    'curl_cffi', 'websocket', 'brotli',
    # Flask / Jinja 运行时
    'jinja2.ext',
]

# 明确排除: 占了体积且运行时用不到
excludes = [
    'tkinter', 'unittest', 'pydoc', 'doctest', 'test',
    'matplotlib', 'pandas', 'scipy', 'PIL',
    'pytest', 'IPython', 'notebook',
    'alembic',            # 迁移只在开发/CI 用, 运行时不需要
    'setuptools._distutils',
]

datas = [
    (str(ROOT / 'app' / 'templates'), 'app/templates'),
    (str(ROOT / 'app' / 'static'), 'app/static'),
]
# 附带许可证与说明: 桌面端软件应可被用户查阅版权信息
for name in ('LICENSE', 'README.md'):
    src = ROOT / name
    if src.exists():
        datas.append((str(src), '.'))

# 音源客户端依赖的原生/数据文件
datas += collect_data_files('musicdl', include_py_files=False)
datas += collect_data_files('yt_dlp', excludes=['**/__pycache__'])

binaries = []

a = Analysis(                                        # noqa: F821
    [str(ROOT / 'mountainriverechoes_app.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / 'packaging' / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)                                    # noqa: F821

exe = EXE(                                           # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mountainriverechoes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                       # UPX 会拖慢启动且易被杀软误报, 不用
    console=False,                                   # 桌面端: 不弹控制台黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(                                      # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='mountainriverechoes',
)
