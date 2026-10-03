'''
Function:
    歌单服务 —— 民族歌单详情、专题曲库, 以及按歌手/专辑/合集聚合的虚拟歌单。
    对外形态与旧版 load_ethnos_playlist / _index_virtual_playlist 保持一致。
'''
from __future__ import annotations

import logging
from typing import Any

from app.domain.normalize import norm_str, split_singers
from app.extensions import session_scope
from app.repositories.playlist_repo import PlaylistRepository
from app.repositories.track_repo import TrackRepository
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

# 虚拟歌单(歌手/专辑/合集)曲目上限, 与旧版一致: 民族歌单不受此限制, 见 ethnos_detail 注释
_MAX_TRACKS = 2600
# 双向子串匹配的最短长度: 短于此会让 'a'/'K' 之类 UGC 歌手名大量误命中
_FUZZY_MIN_LEN = 3
_BIG = 10 ** 6
# 与前端 ethTrackKey(11-playlists.js) 及 curation_service._raw_key 一致: 原始复合键分隔符
_KEY_SEP = '\x1f'


def _order_key(track: dict) -> str:
    '''置顶/次序的稳定键: 歌名+歌手+音源(不归一化)。

    曲目的 id 是每次加载现编的位置号(Ethnos#N / TNNN), 拖动后位置就变了,
    拿它去查策展名单永远命中不上 —— 必须现算这个复合键。'''
    return _KEY_SEP.join((
        str(track.get('song_name') or ''),
        str(track.get('singers') or ''),
        str(track.get('source') or ''),
    ))


class PlaylistService:
    '''歌单读取与聚合。所有方法返回纯数据 dict'''

    # ---------------------------------------------------------------- 民族/专题歌单
    def ethnos_detail(self, key: str) -> dict | None:
        with session_scope() as session:
            repo = PlaylistRepository(session, session.get_bind())
            playlist = repo.get_by_key(key)
            if playlist is None:
                return None
            tracks = self._apply_user_order(repo.tracks_of(playlist), playlist.curation or {})
            curation: dict = playlist.curation or {}

            listed: list[dict] = []
            items: dict[str, Any] = {}
            sid = session_service.new()
            # 上限刻意留白: 民族歌单必须整本返回 —— 策展要在列表里增删任意位置的曲目,
            # 一刀截断会让后半部分的歌「存在但看不见», 反而没法删。
            # (旧版也只对歌手/专辑类虚拟歌单设限, 民族歌单是全量返回的)
            for t in tracks:
                song = t.get('_song') or {}
                url = song.get('download_url') or ''
                if not url:
                    continue
                item_id = f'Ethnos#{len(listed)}'
                items[item_id] = self._playable(song, t)
                row = {k: v for k, v in t.items() if k != '_song'}
                row.update({'id': item_id, 'sid': sid, 'download_url': url})
                listed.append(row)
            session_service.items(sid).update(items)

            return {
                'v': playlist.schema_v, 'partial': playlist.partial,
                'name': playlist.name, 'group': playlist.group_name, 'key': playlist.key,
                'cover': playlist.cover, 'count': len(listed), 'built_at': playlist.built_at,
                'kws': playlist.kws or [], **curation,
                'tracks': listed, 'platform': 'ethnos',
                'platform_name': self._platform_name(playlist.key),
                'id': playlist.key, 'sid': sid,
            }

    @staticmethod
    def _platform_name(key: str) -> str:
        if str(key).startswith('t'):
            return '专题音乐'
        if key == 'han':
            return '汉族音乐'
        return '民族音乐'

    @staticmethod
    def _apply_user_order(tracks: list[dict], curation: dict) -> list[dict]:
        '''用户拖动次序: 置顶在前(按其列表序), 其余按 track_order, 无记录者保持原序'''
        pinned = [str(x) for x in (curation.get('tracks_pinned') or [])]
        order = [str(x) for x in (curation.get('track_order') or [])]
        if not pinned and not order:
            return tracks
        pin_idx = {k: i for i, k in enumerate(pinned)}
        ord_idx = {k: i for i, k in enumerate(order)}
        return sorted(tracks, key=lambda t: (
            pin_idx.get(_order_key(t), _BIG), ord_idx.get(_order_key(t), _BIG),
        ))

    @staticmethod
    def _playable(song: dict, brief: dict) -> dict:
        return {
            'download_url': song.get('download_url') or '',
            'song_name': brief.get('song_name') or '',
            'singers': brief.get('singers') or '',
            'album': brief.get('album') or '',
            'ext': str(brief.get('ext') or '').lower(),
            'source': brief.get('source') or '',
            'source_client': song.get('source') or '',
            'identifier': song.get('identifier') or '',
            'cover_url': brief.get('cover_url') or '',
            'duration_s': int(brief.get('duration_s') or 0),
            'file_size_bytes': int(brief.get('file_size_bytes') or 0),
        }

    # ---------------------------------------------------------------- 虚拟歌单
    def virtual_detail(self, kind: str, key: str) -> dict | None:
        handlers = {
            'artist': self._by_artist, 'album': self._by_album, 'ytcoll': self._by_collection,
        }
        handler = handlers.get(kind)
        if handler is None:
            return None
        rows, label = handler(key)
        if not rows:
            return None
        return self._finalize(kind, key, label, rows)

    def _by_artist(self, key: str) -> tuple[list[dict], str]:
        artist_name, _, group_scope = str(key).partition('@')
        artist_name = artist_name or key
        group_scope = group_scope.strip()
        artist_key = norm_str(artist_name)

        with session_scope() as session:
            rows = TrackRepository.searchable_rows(
                session, group=group_scope or None, like_singers=artist_key,
            )
        seen: set[str] = set()
        picked: list[dict] = []
        for row in rows:
            if not row.get('download_url'):
                continue
            parts = [norm_str(x) for x in split_singers(row.get('singers'))]
            if not parts:
                continue
            matched = any(
                part and (part == artist_key or (not group_scope and self._fuzzy_hit(part, artist_key)))
                for part in parts
            )
            if not matched:
                continue
            # 去重键带 identifier: 电台节目同名不同集不再被误合并为一首
            dedup = '|'.join((norm_str(row.get('song_name')), parts[0], str(row.get('identifier') or '')))
            if dedup in seen:
                continue
            seen.add(dedup)
            picked.append(row)
        label = f'歌手「{artist_name}」' + (f' · {group_scope}' if group_scope else '')
        return picked, label

    @staticmethod
    def _fuzzy_hit(a: str, b: str) -> bool:
        short, long = sorted((a, b), key=len)
        return len(short) >= _FUZZY_MIN_LEN and short in long

    def _by_album(self, key: str) -> tuple[list[dict], str]:
        album_name, artist = (str(key).split('@', 1) + [''])[:2]
        target = norm_str(album_name)
        with session_scope() as session:
            rows = TrackRepository.searchable_rows(session, like_album=target)
        picked = []
        for row in rows:
            if norm_str(row.get('album')) != target:
                continue
            if artist:
                first = split_singers(row.get('singers'))
                if not first or norm_str(first[0]) != norm_str(artist):
                    continue
            picked.append(row)
        return picked, f'专辑「{album_name}」'

    def _by_collection(self, key: str) -> tuple[list[dict], str]:
        with session_scope() as session:
            rows = TrackRepository.searchable_rows(session, album_exact=str(key), with_url=True)
        return rows, f'合辑「{key}」'

    def _finalize(self, kind: str, key: str, label: str, rows: list[dict]) -> dict:
        items: dict[str, Any] = {}
        tracks: list[dict] = []
        sid = session_service.new()
        for row in rows[:_MAX_TRACKS]:
            item_id = f'Ethnos#{len(tracks)}'
            items[item_id] = {
                'download_url': row.get('download_url') or '',
                'song_name': row.get('song_name') or '',
                'singers': row.get('singers') or '',
                'album': row.get('album') or '',
                'ext': str(row.get('ext') or '').lower(),
                'source': row.get('source') or '',
                'source_client': row.get('source_client') or '',
                'identifier': row.get('identifier') or '',
                'cover_url': row.get('cover_url') or '',
                'duration_s': int(row.get('duration_s') or 0),
                'file_size_bytes': int(row.get('file_size_bytes') or 0),
            }
            tracks.append({**row, 'id': item_id, 'sid': sid})
        session_service.items(sid).update(items)
        return {
            'id': f'{kind}:{key}', 'name': label,
            'cover': tracks[0].get('cover_url') if tracks else '',
            'count': len(tracks), 'tracks': tracks,
            'platform': 'ethnos', 'platform_name': f'民族音乐索引 · {label}',
            'sid': sid,
        }
