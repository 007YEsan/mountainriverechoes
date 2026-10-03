'''
Function:
    全网搜索服务 —— 多源并行、逐源流式返回歌曲结果, 并注册进可播放会话。

    为什么不用 Flask 全局状态: 搜索任务是带生命周期的实体, 放在服务层自己的注册表里,
    控制器只负责把它翻译成 HTTP 响应; 将来要换成进程外 worker 时不必动控制器。
'''
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

from app.errors import ValidationError
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36')

SOURCE_NAMES = {
    'Migu': '咪咕', 'Netease': '网易云', 'QQ': 'QQ音乐', 'Kuwo': '酷我', 'Kugou': '酷狗',
    'Qianqian': '千千', 'Soda': '汽水', 'Bilibili': 'B站', 'Bodian': '波点', 'FiveSing': '5sing',
    'StreetVoice': '街声', 'MOOV': '摩音符', 'Apple': '苹果音乐', 'ITunes': 'iTunes', 'Spotify': 'Spotify',
    'SoundCloud': '声云', 'TIDAL': 'TIDAL', 'Qobuz': 'Qobuz', 'Deezer': 'Deezer', 'Jamendo': 'Jamendo',
    'JioSaavn': 'JioSaavn', 'Joox': 'JOOX', 'Suno': 'Suno', 'YouTube': 'YouTube', 'Ximalaya': '喜马拉雅',
    'Lizhi': '荔枝FM', 'Qingting': '蜻蜓FM', 'LRTS': 'LRTS', 'GDStudio': 'GD聚合', 'WikimediaCommons': '维基共享',
    'OpenGameArt': '游戏素材', 'FMA': 'FMA', 'CCMixter': 'CCMixter', 'Audius': 'Audius', 'MyFreeMP3': 'MyFreeMP3',
    'MP3Juice': 'MP3Juice', 'TwoT58': 'TwoT58', 'XMFWAV': 'XMFWAV', 'Gequhai': '歌曲海', 'Sgogo': 'Sgogo',
    'JBSou': '聚爆搜', 'Yinyueku': '音乐库', 'XiaoBai': '小白聚合', 'Weixin': '微信公众号',
}

# 默认音源(与旧版一致): B站民族现场内容最丰富; 微信公众号受搜狗 IP 级配额限制, 仅手动场景携带
DEFAULT_SOURCES = ['BilibiliMusicClient', 'MiguMusicClient', 'NeteaseMusicClient',
                   'KugouMusicClient', 'KuwoMusicClient', 'QQMusicClient', 'WeixinMusicClient']
FAST_SOURCES = ['Bilibili', 'Migu', 'XMFWAV', 'Sgogo', 'Kuwo', 'Gequhai']
SEARCH_SIZE_PER_SOURCE = 12

MAX_JOBS = 20
# 90 秒兜底: 挂起音源强制标记完成, 避免前端无限转圈
STALL_TIMEOUT = 90
# 完成后 15 分钟清出注册表
JOB_RETAIN_AFTER = 900


def _client_for(sources: list[str], work_dir: str) -> Any:
    '''构造 musicdl 客户端。musicdl 依赖较重, 缺依赖时给出可读错误而不是崩掉'''
    try:
        import musicdl
    except Exception as exc:                                    # noqa: BLE001
        raise RuntimeError(f'音乐搜索依赖不可用: {exc}') from exc
    cfg = {
        s: {'work_dir': work_dir, 'search_size_per_source': SEARCH_SIZE_PER_SOURCE, 'max_retries': 1}
        for s in sources
    }
    return musicdl.MusicClient(music_sources=list(sources), init_music_clients_cfg=cfg)


class OnlineSearchService:
    def __init__(self, *, download_dir: Any) -> None:
        self.download_dir = str(download_dir)
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._clients: dict[frozenset, Any] = {}

    # ---------------------------------------------------------------- 音源清单
    def available_sources(self) -> dict:
        try:
            from musicdl.modules import MusicClientBuilder
            all_sources = sorted(k[:-len('MusicClient')] for k in MusicClientBuilder.REGISTERED_MODULES)
        except Exception:                                        # noqa: BLE001
            all_sources = []
        return {
            'default': [s[:-len('MusicClient')] for s in DEFAULT_SOURCES],
            'fast': FAST_SOURCES,
            'all': all_sources,
            'names': SOURCE_NAMES,
        }

    # ---------------------------------------------------------------- 搜索
    def start_search(self, keyword: str, sources: list[str] | None) -> dict:
        keyword = (keyword or '').strip()
        if not keyword:
            raise ValidationError('请输入搜索关键词')
        wanted = [s for s in (sources or DEFAULT_SOURCES) if s]
        client_keys = [s if s.endswith('MusicClient') else f'{s}MusicClient' for s in wanted]
        unique = list(dict.fromkeys(client_keys))
        if not unique:
            raise ValidationError('请至少选择一个音源')

        client = self._cached_client(unique)
        sid = session_service.new()
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                'client': client, 'keyword': keyword, 'sources': list(unique),
                'done': {s: False for s in unique}, 'results': {}, 'errors': {},
                'items': session_service.items(sid), 'sid': sid, 'created_at': time.time(),
            }
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)
        for src in unique:
            threading.Thread(target=self._worker, args=(job_id, src), daemon=True).start()
        return {'job_id': job_id, 'sid': sid,
                'sources': [s[:-len('MusicClient')] for s in unique]}

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValidationError('搜索任务不存在或已过期')
            expired = time.time() - job['created_at'] > STALL_TIMEOUT
            if expired:
                for s in job['sources']:
                    job['done'][s] = True
            groups = [
                {'source': src[:-len('MusicClient')],
                 'source_cn': SOURCE_NAMES.get(src[:-len('MusicClient')], src),
                 'done': bool(job['done'][src]),
                 'error': job['errors'].get(src),
                 'items': [self._brief(song, src, i) for i, song in enumerate(job['results'].get(src, []))]}
                for src in job['sources']
            ]
            snapshot = {
                'sid': job['sid'], 'keyword': job['keyword'], 'groups': groups,
                'total': sum(len(g['items']) for g in groups),
                'finished': all(job['done'].values()),
            }
            if snapshot['finished'] and time.time() - job['created_at'] > JOB_RETAIN_AFTER:
                self._jobs.pop(job_id, None)
        return snapshot

    # ---------------------------------------------------------------- 内部
    def _worker(self, job_id: str, src: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return
        try:
            songs = job['client'].music_clients[src].search(
                keyword=job['keyword'], num_threadings=3, request_overrides={}, rule={},
            ) or []
        except Exception as exc:                                 # noqa: BLE001
            songs = []
            with self._lock:
                job['errors'][src] = str(exc)[:200]
            logger.info('音源 %s 搜索失败: %s', src, exc)
        with self._lock:
            job['results'][src] = songs
            job['done'][src] = True
            items = job['items']
            for i, song in enumerate(songs):
                items[f'{src}#{i}'] = song

    def _cached_client(self, sources: list[str]) -> Any:
        key = frozenset(sources)
        with self._lock:
            cached = self._clients.get(key)
        if cached is not None:
            return cached
        client = _client_for(sources, self.download_dir)
        with self._lock:
            self._clients[key] = client
        return client

    @staticmethod
    def _brief(song: Any, source: str, idx: int) -> dict:
        def clean(v: Any) -> str:
            s = str(v).strip() if v is not None else ''
            return '' if s.upper() in {'NULL', 'NONE'} else s

        download_url = getattr(song, 'download_url', '') or ''
        is_bili_pipe = download_url.startswith('ytdlp:') and 'bilibili.com' in download_url
        previewable = (
            getattr(song, 'protocol', '') == 'HTTP'
            and isinstance(download_url, str)
            and (download_url.startswith('http') or is_bili_pipe)
        )
        return {
            'id': f'{source}#{idx}',
            'song_name': clean(getattr(song, 'song_name', '')) or '未知曲目',
            'singers': clean(getattr(song, 'singers', '')) or '未知歌手',
            'album': clean(getattr(song, 'album', '')),
            'ext': str(getattr(song, 'ext', '') or '').lstrip('.').upper(),
            'file_size': clean(getattr(song, 'file_size', '')),
            'duration': clean(getattr(song, 'duration', '')),
            'duration_s': getattr(song, 'duration_s', 0) or 0,
            'bitrate': getattr(song, 'bitrate', ''),
            'cover_url': clean(getattr(song, 'cover_url', '')),
            'lyric': bool(clean(getattr(song, 'lyric', ''))),
            'source': source[:-len('MusicClient')],
            'source_cn': SOURCE_NAMES.get(source[:-len('MusicClient')], source),
            'previewable': bool(previewable),
            'downloadable': bool(previewable or getattr(song, 'with_valid_download_url', False)),
        }
