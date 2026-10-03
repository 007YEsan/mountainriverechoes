'''
Function:
    应用启动入口 —— 开发、生产与打包产物都走这里。
    桌面端形态: 启动后在默认浏览器打开界面并常驻, Ctrl+C 触发优雅停机。
'''
from __future__ import annotations

import argparse
import logging
import threading
import webbrowser

from app import __version__
from app.config import load_settings
from app.factory import create_app

logger = logging.getLogger(__name__)


def _open_browser(url: str, delay: float = 1.5) -> None:
    '''延迟打开: 等服务真的监听上了再拉浏览器, 否则用户先看到一个打不开的页面'''
    def _run() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:                                   # noqa: BLE001
            logger.debug('打开浏览器失败: %s', exc)
    threading.Timer(delay, _run).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='山河回响 · 中国民族音乐曲库')
    parser.add_argument('--host', help='监听地址, 默认取 MRE_HOST(127.0.0.1)')
    parser.add_argument('--port', type=int, help='监听端口, 默认取 MRE_PORT(8766)')
    parser.add_argument('--no-browser', action='store_true', help='启动后不自动打开浏览器')
    args = parser.parse_args(argv)

    settings = load_settings()
    host = args.host or settings.host
    port = int(args.port or settings.port)

    app = create_app(settings)
    url = f'http://127.0.0.1:{port}' if host in {'0.0.0.0', '::'} else f'http://{host}:{port}'
    print(f'[山河回响 v{__version__}] {url}', flush=True)
    print(f'  数据目录: {settings.data_dir}', flush=True)

    if not args.no_browser:
        _open_browser(url)

    try:
        # threaded=True: 边播边下边检索; 单线程会被音频长连接占死
        app.run(host=host, port=port, threaded=True)
    except KeyboardInterrupt:
        print('\n正在退出…', flush=True)
        app.extensions['services']['lifecycle'].shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
