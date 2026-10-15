# -*- mode: python ; coding: utf-8 -*-
'''
声动阿昌 —— 阿昌族民族音乐桌面播放器 打包脚本（PyInstaller 单目录模式）

用法：
    pyinstaller packaging/shengdong-achang.spec --noconfirm
产物：
    dist/shengdong-achang/shengdong-achang.exe

复用 mountainriverechoes.spec 的隐藏依赖收集（yt-dlp 惰性导入 / musicdl 子模块 /
pywebview），入口改为 shengdong_achang.py，并把阿昌族曲库母本 + 模板打进包。
'''
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent          # noqa: F821  仓库根

_icon_win = ROOT / 'packaging' / 'shengdong-achang.ico'
_icon_mac = ROOT / 'packaging' / 'shengdong-achang.icns'
ICON = str(_icon_win if sys.platform == 'win32' else _icon_mac)
if not Path(ICON).exists():
    ICON = None

hiddenimports = []
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('musicdl')
hiddenimports += collect_submodules('yt_dlp.extractor')
hiddenimports += collect_submodules('yt_dlp.postprocessor')
hiddenimports += collect_submodules('webview')
hiddenimports += [
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.sql.default_comparator',
    'sqlalchemy.pool',
    'orjson', 'pathvalidate', 'platformdirs', 'filetype', 'puremagic',
    'mutagen', 'tinytag', 'emoji', 'bleach', 'bs4', 'lxml', 'tabulate',
    'curl_cffi', 'websocket', 'brotli',
    'jinja2.ext',
    'clr', 'clr_loader', 'pythonnet',
]

excludes = [
    'tkinter', 'unittest', 'pydoc', 'doctest', 'test',
    'matplotlib', 'pandas', 'scipy', 'PIL',
    'pytest', 'IPython', 'notebook',
    'alembic',
    'setuptools._distutils',
]

datas = [
    # 前端模板（含 achang-player.html 与 56 民族主站模板，后端 render_template 都要找得到）
    (str(ROOT / 'webui' / 'templates'), 'webui/templates'),
    # 阿昌族曲库母本（后端 ETHNOS_CACHE_DIR = _internal/webui/ethnos_cache）
    (str(ROOT / 'webui' / 'ethnos_cache'), 'webui/ethnos_cache'),
]

for name in ('LICENSE', 'README.md'):
    src = ROOT / name
    if src.exists():
        datas.append((str(src), '.'))

datas += collect_data_files('musicdl', include_py_files=False)
datas += collect_data_files('yt_dlp', excludes=['**/__pycache__'])
datas += collect_data_files('webview')

binaries = []

a = Analysis(                                        # noqa: F821
    [str(ROOT / 'shengdong_achang.py')],
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
    name='shengdong-achang',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name='shengdong-achang',
)
