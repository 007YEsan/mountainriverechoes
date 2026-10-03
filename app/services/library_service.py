'''
Function:
    本地库索引服务 —— /api/index 聚合数据、/api/index/sig 签名、/api/index/search 检索。
    返回结构与旧版严格对齐, 前端不需要任何改动。
'''
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.config import Settings
from app.domain.normalize import norm_str
from app.repositories.artist_repo import ArtistRepository
from app.repositories.playlist_repo import PlaylistRepository
from app.repositories.track_repo import TrackRepository
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

# 常驻会话: 曲库检索结果共用一条 sid, 避免每次检索都新建会话把正在播放的旧会话挤掉
_LIBRARY_ITEMS_CAP = 4000


class LibraryService:
    '''索引与检索业务。入参出参都是纯数据, 不依赖 request/response'''

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {'data': None, 'at': 0.0}
        self._library_sid: str | None = None

    # ---------------------------------------------------------------- 索引
    def index_payload(self) -> dict:
        ttl = max(0, self.settings.library_index_ttl)
        with self._lock:
            if self._cache['data'] is not None and time.time() - self._cache['at'] < ttl:
                return self._cache['data']
        data = self._compute_index()
        with self._lock:
            self._cache.update(data=data, at=time.time())
        return data

    def index_signature(self) -> str:
        from sqlalchemy import func, select

        from app.extensions import session_scope
        from app.models import Playlist, PlaylistTrack, Track
        with session_scope() as session:
            # 只取计数, 毫秒级 —— 任何曲目/歌单/关联的增删都会让签名变化
            counts = tuple(
                int(session.execute(select(func.count(col))).scalar_one())
                for col in (Track.id, PlaylistTrack.playlist_id, Playlist.id)
            )
            latest = int(session.execute(select(func.max(PlaylistTrack.position))).scalar_one() or 0)
        return f'{counts[0]}.{counts[1]}.{counts[2]}.{latest}'

    def invalidate(self) -> None:
        with self._lock:
            self._cache.update(data=None, at=0.0)

    def _compute_index(self) -> dict:
        from app.extensions import session_scope
        with session_scope() as session:
            engine = session.get_bind()
            playlists_repo = PlaylistRepository(session, engine)
            artists_repo = ArtistRepository(session, engine)

            artist_list = artists_repo.list_for_index()
            group_songs = playlists_repo.group_song_counts()
            removed = playlists_repo.removed_artists()
            coll_removed = playlists_repo.removed_collections()

            items: list[dict] = []
            for p in playlists_repo.list_ethnic():
                cnt = group_songs.get(p.group_name) or p.track_count
                if not cnt:
                    continue
                items.append({
                    'id': p.key, 'platform': 'ethnos',
                    'name': f'{p.group_name} · 民族音乐',
                    'group': p.group_name, 'count': cnt, 'kind': '民族歌单',
                })

            # YouTube/电台合集插到靠前位置, 位置与旧版一致
            for cs in playlists_repo.collection_stats():
                items.insert(min(4, len(items)), {
                    'id': 'ytcoll:' + cs['name'], 'platform': 'index',
                    'name': cs['name'], 'group': cs['group'],
                    'count': cs['count'], 'kind': 'YouTube合集', 'cover': cs['cover'],
                })

            for topic in playlists_repo.list_topics():
                items.append({
                    'id': topic['key'], 'platform': 'ethnos',
                    'name': f"{topic['name']} · 专题音乐",
                    'group': topic['group'], 'count': topic['count'], 'kind': '专题曲库',
                })

            stats = {
                'artists': artists_repo.count_distinct(),
                'songs': sum(group_songs.values()),
                'ethnos_done': sum(1 for p in playlists_repo.list_ethnic() if not p.partial),
                'ethnos_playlists': sum(1 for i in items if i['kind'] == '民族歌单'),
            }
        return {
            'artists': artist_list, 'playlists': items, 'group_songs': group_songs,
            'removed': removed, 'collections_removed': coll_removed, 'stats': stats,
        }

    # ---------------------------------------------------------------- 检索
    def search_library(
        self, query: str, *, group: str | None = None, limit: int = 60, offset: int = 0,
    ) -> dict:
        from app.extensions import session_scope
        q = norm_str(query)
        if len(q) < self.settings.search_min_query:
            return {
                'building': False, 'q': query, 'group': group or '', 'total': 0, 'count': 0,
                'capped': False, 'tracks': [], 'sid': None,
                'hint': f'请至少输入 {self.settings.search_min_query} 个字',
            }
        limit = max(1, min(int(limit or self.settings.search_page_size), self.settings.search_max_limit))
        offset = max(0, int(offset or 0))

        with session_scope() as session:
            repo = TrackRepository(session, session.get_bind())
            result = repo.search_library(q, group=group or None, limit=limit, offset=offset)
            # 注册进常驻会话: 前端播放/下载按 sid+id 回查, 不回传整条歌单
            tracks = result.tracks
            tracks = [{**t, **self._register(t)} for t in tracks] if tracks else []
        return {
            'building': False, 'q': query, 'group': group or '',
            'total': result.total, 'count': len(tracks), 'capped': result.capped,
            'tracks': tracks, 'sid': self._library_sid,
            'hint': '' if tracks else '没有匹配的歌曲，换个关键词试试',
        }

    def _register(self, track: dict) -> dict:
        '''把检索结果写进常驻会话并返回带 sid 的补丁'''
        from app.models import Track as TrackModel
        from app.extensions import session_scope
        with session_scope() as session:
            model = session.get(TrackModel, track['track_id'])
            if model is None:
                return {}
            with self._lock:
                if self._library_sid is None or session_service.get(self._library_sid) is None:
                    self._library_sid = session_service.new()
                sid = self._library_sid
                # 注意: 不能写 `items(sid) or {}` —— 空字典是 falsy, 那样会拿到一个临时字典,
                # 注册进去的曲目随即在函数结束时被丢弃, 表现为播放时报「会话已过期」。
                holder = session_service.get(sid)
                items = holder.items if holder is not None else {}
                if len(items) > _LIBRARY_ITEMS_CAP:
                    items.clear()
                items[track['id']] = PlayableTrack(model).as_dict()
        return {'sid': sid}

    # ---------------------------------------------------------------- 专题
    def list_topics(self) -> list[dict]:
        from app.extensions import session_scope
        with session_scope() as session:
            return PlaylistRepository(session, session.get_bind()).list_topics()


class PlayableTrack:
    '''会话里挂载的可播放/可下载载荷'''

    __slots__ = ('download_url', 'song_name', 'singers', 'album', 'ext', 'source',
                 'source_client', 'identifier', 'cover_url', 'duration_s', 'file_size_bytes')

    def __init__(self, track: Any) -> None:
        self.download_url = track.download_url
        self.song_name = track.song_name
        self.singers = track.singers
        self.album = track.album
        self.ext = track.ext
        self.source = track.source
        self.source_client = track.source_client
        self.identifier = track.identifier
        self.cover_url = track.cover_url
        self.duration_s = track.duration_s
        self.file_size_bytes = track.file_size_bytes

    def as_dict(self) -> dict:
        return {slot: getattr(self, slot) for slot in self.__slots__}
