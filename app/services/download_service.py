'''
Function:
    下载服务 —— 任务注册表 + 后台线程池。
    幂等/重试: 同一 sid+id 重复提交不会排两次队; 网络中断按 Range 断点续传, 最多 5 次。

    两条通道:
      1) 有直链(本地曲库/绝大多数搜索结果): 直接 HTTP 流式落盘, Referer 按 CDN 匹配
      2) ytdlp: 伪协议(B站/YouTube): 先用 yt-dlp 提取实时音频直链再走通道 1
'''
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36')

# CDN 防盗链: 缺 Referer 必 403
REFERERS = [
    ('kugou.com', 'https://www.kugou.com/'),
    ('kuwo.cn', 'https://www.kuwo.cn/'),
    ('migudm.com', 'https://migu.cn/'),
    ('migu.cn', 'https://migu.cn/'),
    ('stream.qqmusic', 'https://y.qq.com/'),
    ('isure.stream', 'https://y.qq.com/'),
    ('y.qq.com', 'https://y.qq.com/'),
    ('gtimg.com', 'https://v.qq.com/'),
    ('v.qq.com', 'https://v.qq.com/'),
    ('bilibili.com', 'https://www.bilibili.com/'),
    ('bilivideo.com', 'https://www.bilibili.com/'),
    ('music.126.net', 'https://music.163.com/'),
    ('music.163.com', 'https://music.163.com/'),
    ('res.wx.qq.com', 'https://mp.weixin.qq.com/'),
    ('mpvideo.qpic.cn', 'https://mp.weixin.qq.com/'),
]

_MAX_TASKS = 200
_MAX_ATTEMPTS = 5
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\r\n]+')


def referer_for(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    for domain, ref in REFERERS:
        if domain in url:
            return ref
    return None


class DownloadService:
    def __init__(self, *, download_dir: Path, workers: int = 3) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tasks: OrderedDict[str, dict] = OrderedDict()
        self._claimed: set[tuple[str, str]] = set()
        self.pool = ThreadPoolExecutor(max_workers=max(1, workers))

    # ---------------------------------------------------------------- 提交
    def submit(self, items: list[tuple[str, str, Any]]) -> list[str]:
        '''items: [(sid, item_id, payload)] —— payload 可以是 SongInfo 或 dict。

        同一 (sid, item_id) 在任务出表前不会被排第二次, 挡住双击造成的重复下载。
        '''
        submitted: list[str] = []
        for sid, item_id, payload in items:
            claim = (sid or '', str(item_id))
            with self._lock:
                if claim in self._claimed:
                    continue
                self._claimed.add(claim)
                tid = uuid.uuid4().hex[:8]
                self._tasks[tid] = {
                    'id': tid, 'claim': claim,
                    'name': self._name_of(payload), 'singer': self._singer_of(payload),
                    'source': self._source_of(payload), 'ext': self._ext_of(payload),
                    'file_size': '', 'status': 'queued', 'file': None, 'error': None,
                    'created_at': time.time(), 'finished_at': None,
                }
                self._trim_tasks()
            self.pool.submit(self._run, tid, payload)
            submitted.append(tid)
        return submitted

    def _trim_tasks(self) -> None:
        '''超出上限时按插入顺序淘汰最旧任务, 连带释放其占位(在锁内调用)'''
        while len(self._tasks) > _MAX_TASKS:
            _, evicted = self._tasks.popitem(last=False)
            self._claimed.discard(evicted.get('claim'))

    # ---------------------------------------------------------------- 查询
    def list_tasks(self) -> dict:
        with self._lock:
            values = list(self._tasks.values())
        # 返回副本且剔除内部占位字段, 避免这里的清理反过来删掉注册表里的 claim
        items = [{k: v for k, v in t.items() if k != 'claim'} for t in reversed(values)]
        return {'tasks': items, 'active': any(t['status'] in ('queued', 'downloading') for t in items)}

    def clear_finished(self) -> None:
        with self._lock:
            for tid in [k for k, v in self._tasks.items() if v['status'] in ('done', 'failed')]:
                task = self._tasks.pop(tid)
                self._claimed.discard(task.get('claim'))

    # ---------------------------------------------------------------- 执行
    def _run(self, tid: str, payload: Any) -> None:
        with self._lock:
            if tid not in self._tasks:
                return
            self._tasks[tid]['status'] = 'downloading'
        try:
            url = self._download_url_of(payload)
            if not isinstance(url, str) or not url:
                raise RuntimeError('该曲没有可用直链')
            if url.startswith('ytdlp:'):
                url = self._resolve_ytdlp(url)
                if not url:
                    raise RuntimeError('yt-dlp 提取音频链接失败')
            saved = self._stream_to_disk(payload, url)
            with self._lock:
                self._tasks[tid].update(
                    status='done', file=os.path.relpath(saved, self.download_dir),
                    finished_at=time.time(),
                )
        except Exception as exc:                                  # noqa: BLE001
            logger.info('下载失败 %s: %s', tid, exc)
            with self._lock:
                self._tasks[tid].update(status='failed', error=str(exc)[:200], finished_at=time.time())

    def _stream_to_disk(self, payload: Any, url: str) -> Path:
        from pathvalidate import sanitize_filepath
        name = str(self._name_of(payload) or '未知曲目')[:60]
        ident = str(self._identifier_of(payload) or uuid.uuid4().hex[:6])
        ext = str(self._ext_of(payload) or 'mp3').lstrip('.') or 'mp3'
        stem = _UNSAFE_NAME.sub(' ', f'{name} - {ident}').strip()
        path = Path(sanitize_filepath(str(self.download_dir / f'{stem}.{ext}')))

        headers = {'User-Agent': UA}
        if ref := referer_for(url):
            headers['Referer'] = ref

        offset, attempt = 0, 0
        while attempt < _MAX_ATTEMPTS:
            attempt += 1
            req_headers = dict(headers)
            if offset:
                req_headers['Range'] = f'bytes={offset}-'
            try:
                with requests.get(url, headers=req_headers, stream=True, timeout=(10, 120)) as resp, \
                        open(path, 'ab' if offset else 'wb') as fh:
                    for chunk in resp.iter_content(chunk_size=512 * 1024):
                        if chunk:
                            fh.write(chunk)
                            offset += len(chunk)
                if offset > 0:
                    return path
                raise RuntimeError('下载内容为空')
            except Exception:                                      # noqa: BLE001
                time.sleep(2)
                if attempt >= _MAX_ATTEMPTS:
                    raise
        raise RuntimeError('重试次数耗尽')

    @staticmethod
    def _resolve_ytdlp(fake_url: str) -> str | None:
        '''ytdlp:<watch_url> -> 实时音频直链'''
        watch = fake_url[6:]
        try:
            import yt_dlp
        except Exception:                                          # noqa: BLE001
            return None
        opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True, 'noplaylist': True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(watch, download=False)
        except Exception as exc:                                   # noqa: BLE001
            logger.info('yt-dlp 解析失败: %s', exc)
            return None
        if not info:
            return None
        if isinstance(info.get('url'), str):
            return info['url']
        for fmt in (info.get('formats') or []):
            if fmt.get('url'):
                return fmt['url']
        return None

    # ---------------------------------------------------------------- payload 适配
    @staticmethod
    def _attr(payload: Any, name: str, default: Any = '') -> Any:
        if isinstance(payload, dict):
            return payload.get(name, default)
        return getattr(payload, name, default)

    def _name_of(self, payload: Any) -> str:
        return str(self._attr(payload, 'song_name') or '未知曲目')

    def _singer_of(self, payload: Any) -> str:
        return str(self._attr(payload, 'singers') or '—')

    def _source_of(self, payload: Any) -> str:
        raw = str(self._attr(payload, 'source') or '')
        return raw[:-len('MusicClient')] if raw.endswith('MusicClient') else raw

    def _ext_of(self, payload: Any) -> str:
        return str(self._attr(payload, 'ext') or '').lstrip('.').upper()

    def _identifier_of(self, payload: Any) -> str:
        return str(self._attr(payload, 'identifier') or '')

    def _download_url_of(self, payload: Any) -> str:
        return str(self._attr(payload, 'download_url') or '')
