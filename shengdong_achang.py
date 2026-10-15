'''
声动阿昌 —— 阿昌族民族音乐桌面播放器（打包入口）

复用 webui/mountainriverechoes.py 的 Flask 后端（曲库加载 / 播放续签 / 封面代理 / 歌词），
用 pywebview 起一个原生桌面窗口打开 /achang，不弹浏览器。

用法：
  开发态：  venv/Scripts/python.exe shengdong_achang.py
  打包：    pyinstaller packaging/shengdong-achang.spec --noconfirm
'''
from __future__ import annotations

import os
import sys
import socket
import threading
from pathlib import Path


def _resource_root() -> Path:
    '''定位运行时资源根目录（曲库缓存 / 模板所在）。

    开发态：仓库根（webui/ethnos_cache、webui/templates 都在这下面）
    打包态：PyInstaller 单目录产物的 _internal 里，datas 会被摊到 _internal/webui/...
    '''
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).resolve().parent / '_internal'
    else:
        base = Path(__file__).resolve().parent
    return base


def _ensure_data_dir() -> Path:
    '''用户数据目录：曲库母本首次启动复制到这里，之后读写都在这（安装目录只读也安全）。'''
    root = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    d = Path(root) / '声动阿昌' / 'data'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stage_library() -> None:
    '''把打包进 exe 的阿昌族曲库母本，复制到用户数据目录（若尚未存在）。

    这样播放侧写回直链、置顶/排序等都不会落到只读的安装目录里。'''
    res = _resource_root()
    src = res / 'webui' / 'ethnos_cache'
    dst = _ensure_data_dir() / 'ethnos_cache'
    dst.mkdir(parents=True, exist_ok=True)
    # 只搬阿昌族（e37）曲库母本
    for f in src.glob('e37_*.json'):
        target = dst / f.name
        if not target.exists():
            try:
                target.write_bytes(f.read_bytes())
            except Exception:
                pass


def _pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 200):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
            return port
        except OSError:
            continue
    return preferred


def main() -> int:
    # Windows 控制台默认 GBK，中文 print 会崩；确保 UTF-8
    try:
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    _stage_library()

    res = _resource_root()
    if str(res) not in sys.path:
        sys.path.insert(0, str(res))

    from webui import mountainriverechoes as backend  # noqa: PLC0415
    app = backend.app

    host = '127.0.0.1'
    port = _pick_port(host, 8771)
    url = f'http://{host}:{port}/achang'

    print(f'[声动阿昌] {url}', flush=True)

    if '--no-window' in sys.argv:
        print('[声动阿昌] 仅后端模式（--no-window）', flush=True)
        app.run(host=host, port=port, threaded=True)
        return 0

    threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
        daemon=True,
    ).start()

    try:
        import webview  # noqa: PLC0415
        webview.create_window(
            '声动阿昌 · 阿昌族民族音乐',
            url,
            width=1200, height=800, min_size=(900, 600),
        )
        webview.start()
    except Exception:
        import webbrowser  # noqa: PLC0415
        webbrowser.open(url)
        try:
            app.run(host=host, port=port, threaded=True)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
