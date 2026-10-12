'''
Function:
    应用启动入口 —— 开发、生产与打包产物都走这里。
    桌面端形态: 启动后在默认浏览器打开界面并常驻, Ctrl+C 触发优雅停机。
'''
from __future__ import annotations

import argparse
import logging
import socket
import threading
import webbrowser

from app import __version__
from app.config import load_settings
from app.factory import create_app
from app.logging_setup import ensure_utf8_streams

logger = logging.getLogger(__name__)


def _pick_port(host: str, preferred: int) -> int:
    '''探测空闲端口: preferred 被占用就 +1 往后找。

    避免两个实例(三族版与完整版、或重复打开多个窗口)抢同一端口,
    后启动的那个会连到先启动的后端而「串台」。'''
    for port in range(preferred, preferred + 200):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
            return port
        except OSError:
            continue
    return preferred


def _open_browser(url: str, delay: float = 1.5) -> None:
    '''延迟打开: 等服务真的监听上了再拉浏览器, 否则用户先看到一个打不开的页面'''
    def _run() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:                                   # noqa: BLE001
            logger.debug('打开浏览器失败: %s', exc)
    threading.Timer(delay, _run).start()


def _start_window(app, host: str, port: int, url: str) -> bool:
    '''原生桌面窗口(pywebview + 系统 WebView2): 独立应用窗口而非浏览器标签页。

    失败(缺 WebView2 / 环境不支持)时返回 False, 由调用方退回 webbrowser。
    '''
    try:
        import webview                                              # noqa: PLC0415
    except Exception:                                               # noqa: BLE001
        return False
    # Flask 放到后台线程, 主线程交给 webview 事件循环
    threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
        daemon=True,
    ).start()
    try:
        webview.create_window(
            '山河回响 · 三族民族音乐', url,
            width=1200, height=800, min_size=(1024, 680),
        )
        webview.start()
        return True
    except Exception as exc:                                        # noqa: BLE001
        logger.debug('原生窗口启动失败, 退回浏览器: %s', exc)
        return False


def main(argv: list[str] | None = None) -> int:
    # 必须先于任何 print: Windows 控制台默认 ANSI 编码, 中文 print 会直接崩进程
    ensure_utf8_streams()
    parser = argparse.ArgumentParser(description='山河回响 · 中国民族音乐曲库')
    parser.add_argument('--host', help='监听地址, 默认取 MRE_HOST(127.0.0.1)')
    parser.add_argument('--port', type=int, help='监听端口, 默认取 MRE_PORT(8767)')
    parser.add_argument('--no-browser', action='store_true', help='启动后不自动打开浏览器')
    args = parser.parse_args(argv)

    settings = load_settings()
    host = args.host or settings.host
    # 动态端口: 首选端口被占(如已开着完整版 8766 / 另一个实例)则自动顺延, 互不串台
    port = _pick_port(host, int(args.port or settings.port))

    app = create_app(settings)
    url = f'http://127.0.0.1:{port}' if host in {'0.0.0.0', '::'} else f'http://{host}:{port}'
    print(f'[山河回响 v{__version__}] {url}', flush=True)
    print(f'  数据目录: {settings.data_dir}', flush=True)

    if not args.no_browser:
        # 优先原生桌面窗口; 不可用则退回浏览器
        if _start_window(app, host, port, url):
            return 0
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
