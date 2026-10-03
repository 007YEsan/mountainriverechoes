'''
Function:
    媒体服务 —— 播放直链解析(含 ytdlp 伪协议)、CDN 防盗链头、歌词获取。
'''
from __future__ import annotations

import logging
import re
from typing import Any

from app.services.download_service import UA, referer_for

logger = logging.getLogger(__name__)

# 本地曲库会话 item 的 id 形态: Idx#<track_id>
_LOCAL_ID_PREFIX = 'Idx#'
# 歌词时间轴标记: LRC 形如 [00:12.34] 或 [00:12]
_TIME_TAG = re.compile(r'\[\d{1,3}:\d{2}')


class MediaService:
    def __init__(self) -> None:
        pass

    # ---------------------------------------------------------------- 播放
    def resolve_stream_url(self, item: Any) -> str:
        '''取出可播放直链; ytdlp: 伪协议实时提取'''
        url = self._url_of(item)
        if isinstance(url, str) and url.startswith('ytdlp:'):
            from app.services.download_service import DownloadService
            return DownloadService._resolve_ytdlp(url) or ''
        return url if isinstance(url, str) else ''

    def request_headers(self, url: str, *, range_header: str | None = None) -> dict[str, str]:
        headers = {'User-Agent': UA}
        if referer := referer_for(url):
            headers['Referer'] = referer
        if range_header:
            headers['Range'] = range_header
        return headers

    @staticmethod
    def _url_of(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get('download_url') or '')
        return str(getattr(item, 'download_url', '') or '')

    # ---------------------------------------------------------------- 歌词
    def get_lyric(self, *, item: Any, item_id: str, name: str = '', artist: str = '') -> str:
        '''本地库优先; 拿不到再回落在线搜词'''
        local_id = self._local_track_id(item_id)
        if local_id is not None:
            from app.extensions import session_scope
            from app.repositories.track_repo import TrackRepository
            with session_scope() as session:
                content = TrackRepository(session, session.get_bind()).get_lyric(local_id)
            if content:
                return content
        return self._online_lyric(name=name, artist=artist, item=item)

    @staticmethod
    def _local_track_id(item_id: str) -> int | None:
        if not isinstance(item_id, str) or not item_id.startswith(_LOCAL_ID_PREFIX):
            return None
        try:
            return int(item_id[len(_LOCAL_ID_PREFIX):])
        except ValueError:
            return None

    @staticmethod
    def _online_lyric(*, name: str, artist: str, item: Any) -> str:
        '''本地库没有歌词时回落在线搜词(searchbylrclib 系列接口)。

        musicdl 的 LyricSearchClient.search 签名是 (track_name, artist_name, ...),
        返回 (lyric_result, lyric) 二元组 —— 不是「(歌曲, 歌词)列表」, 早先按列表解包会炸。
        '''
        try:
            from musicdl.modules import LyricSearchClient
        except Exception:                                          # noqa: BLE001
            return ''
        song_name = name or (
            item.get('song_name') if isinstance(item, dict) else getattr(item, 'song_name', '')
        )
        singers = artist or (
            item.get('singers') if isinstance(item, dict) else getattr(item, 'singers', '')
        )
        if not song_name:
            return ''
        try:
            _result, lyric = LyricSearchClient.search(
                track_name=str(song_name).strip(), artist_name=str(singers or '').strip(),
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.debug('在线歌词搜索失败: %s', exc)
            return ''
        # 搜不到时接口会回一个占位串(形如 "[id:$00000000]"), 没有一句带时间轴的歌词,
        # 直接回给前端会显示成一张空白歌词卡 —— 按"有没有时间轴"判定它是不是真歌词。
        if isinstance(lyric, str) and lyric.strip() and lyric.upper() not in {'NULL', 'NONE'}:
            return lyric if _TIME_TAG.search(lyric) else ''
        return ''
