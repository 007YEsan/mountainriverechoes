'''
Function:
    曲目仓储 —— 歌名检索(FTS5 + 打分排序 + 同名归并)与单曲读取。
    检索口径与旧版保持一致:
        完全相等 1000 > 前缀 700 > 子串 500 > 歌手 300 > 专辑 200
        有歌名命中(>=500)时丢弃纯歌手/专辑命中, 避免"搜歌名返回该歌手全部歌"
        最后按 歌名|首歌手 归并去重, 每个版本只留最优可播的那份
'''
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import Engine, func, or_, select, text
from sqlalchemy.orm import Session

from app.database import fts_ready
from app.models import Lyric, Playlist, PlaylistTrack, Track

logger = logging.getLogger(__name__)

# raw_json 里已单独建模的键, 合并回ാവ _song 时以列値为准
_RAW_SHADOWED = {
    'source', 'song_name', 'singers', 'album', 'ext', 'file_size_bytes',
    'duration_s', 'cover_url', 'download_url', 'identifier', 'bitrate', 'lyric',
}


@dataclass(frozen=True)
class LibrarySearchResult:
    tracks: list[dict]
    total: int
    capped: bool


def escape_fts(query: str) -> str:
    '''FTS5 短语查询: 双引号加倍后包 "...", 让 trigram 做子串匹配'''
    return '"' + str(query).replace('"', '""') + '"'


class TrackRepository:
    '''所有方法接收已打开的 Session, 不自己管理事务边界'''

    def __init__(self, session: Session, engine: Engine) -> None:
        self.session = session
        self.engine = engine

    # ---------------------------------------------------------------- 读取
    def get_by_id(self, track_id: int) -> Track | None:
        return self.session.get(Track, track_id)

    def get_by_ids(self, ids: Iterable[int]) -> list[Track]:
        ids = list(ids)
        if not ids:
            return []
        rows = self.session.execute(select(Track).where(Track.id.in_(ids))).scalars().all()
        index = {t.id: t for t in rows}
        return [index[i] for i in ids if i in index]

    def get_lyric(self, track_id: int) -> str | None:
        return self.session.execute(
            select(Lyric.content).where(Lyric.track_id == track_id)
        ).scalar_one_or_none()

    def count_all(self) -> int:
        return int(self.session.execute(select(func.count(Track.id))).scalar_one())

    def count_playable(self) -> int:
        return int(self.session.execute(
            select(func.count(Track.id)).where(or_(Track.previewable.is_(True), Track.downloadable.is_(True)))
        ).scalar_one())

    # ---------------------------------------------------------------- 检索
    def search_library(
        self, query: str, *, group: str | None = None, limit: int = 60, offset: int = 0,
    ) -> LibrarySearchResult:
        base_sql, params = self._candidate_filter(query, group=group)
        cte = f'''
            WITH scored AS (
                SELECT t.id AS id, t.dedup_core AS dedup_core,
                       {self._score_expr()} AS score,
                       ({self._score_expr()}
                         + (CASE WHEN t.previewable  THEN 200 ELSE 0 END)
                         + (CASE WHEN t.downloadable THEN  50 ELSE 0 END)) AS sort_score,
                       length(t.core_name) AS name_len,
                       t.duration_s       AS duration_s
                FROM tracks t
                WHERE (t.previewable = 1 OR t.downloadable = 1) AND ({base_sql})
            ),
            deduped AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY dedup_core
                    ORDER BY sort_score DESC, name_len ASC, duration_s DESC
                ) AS rn
                FROM scored
            )
        '''
        total_row = self.session.execute(
            text(f'{cte} SELECT COUNT(*), MAX(score) FROM deduped WHERE rn = 1'), params,
        ).first()
        total, top = int(total_row[0] or 0), int(total_row[1] or 0)
        if not total:
            return LibrarySearchResult(tracks=[], total=0, capped=False)

        # 有歌名命中就丢掉纯歌手/专辑命中
        threshold = 500 if top >= 500 else 1
        rows = self.session.execute(
            text(
                f'{cte} SELECT id FROM deduped WHERE rn = 1 AND score >= :threshold '
                f'ORDER BY sort_score DESC, name_len ASC, duration_s DESC LIMIT :limit OFFSET :offset'
            ),
            {**params, 'threshold': threshold, 'limit': limit, 'offset': offset},
        ).all()
        tracks = self.get_by_ids(r[0] for r in rows)
        return LibrarySearchResult(
            tracks=[self.to_brief(t) for t in tracks],
            total=total,
            capped=offset + limit < total,
        )

    @staticmethod
    def _score_expr() -> str:
        return (
            'CASE '
            ' WHEN t.core_name = :q OR t.norm_name = :q THEN 1000'
            ' WHEN t.core_name LIKE :prefix OR t.norm_name LIKE :prefix THEN 700'
            ' WHEN instr(t.core_name, :q) > 0 OR instr(t.norm_name, :q) > 0 THEN 500'
            ' WHEN instr(t.norm_singers, :q) > 0 THEN 300'
            ' WHEN instr(t.norm_album, :q) > 0 THEN 200'
            ' ELSE 0 END'
        )

    def _candidate_filter(self, query: str, *, group: str | None) -> tuple[str, dict[str, Any]]:
        '''候选集: FTS 先收窄范围, 打分表达式再精筛'''
        params: dict[str, Any] = {'q': query, 'prefix': f'{query}%'}
        clauses: list[str] = []
        fts_ids = self._fts_ids(query)
        if fts_ids:
            params['fts_ids'] = fts_ids
            clauses.append('t.id IN (SELECT value FROM json_each(:fts_ids))')
        else:
            clauses.append(
                '(t.core_name LIKE :contains OR t.norm_name LIKE :contains'
                ' OR t.norm_singers LIKE :contains OR t.norm_album LIKE :contains)'
            )
            params['contains'] = f'%{query}%'
        if group:
            clauses.append(
                'EXISTS (SELECT 1 FROM playlist_tracks pt JOIN playlists p ON p.id = pt.playlist_id'
                ' WHERE pt.track_id = t.id AND p.group_name = :group)'
            )
            params['group'] = group
        return ' AND '.join(clauses), params

    def _fts_ids(self, query: str) -> str:
        '''候选 id 的 JSON 数组; 不可用返回空串'''
        if not fts_ready() or len(query) < 3:
            return ''
        try:
            rows = self.session.execute(
                text('SELECT rowid FROM tracks_fts WHERE tracks_fts MATCH :m LIMIT 20000'),
                {'m': escape_fts(query)},
            ).all()
        except Exception as exc:                                   # noqa: BLE001
            logger.debug('FTS 查询失败, 回退 LIKE: %s', exc)
            return ''
        return '[' + ','.join(str(r[0]) for r in rows) + ']'

    # ---------------------------------------------------------------- 虚拟歌单取源
    @staticmethod
    def searchable_rows(
        session: Session,
        *,
        group: str | None = None,
        like_singers: str | None = None,
        like_album: str | None = None,
        album_exact: str | None = None,
        with_url: bool = False,
    ) -> list[dict]:
        '''虚拟歌单(歌手/专辑/合集)的候选集。返回扁平 dict, 含可直接播放的 download_url。

        不做 raw_json 反序列化: 聚合结果可能上万条, 解析开销没必要。
        '''
        if group:
            stmt = (
                select(Track)
                .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
                .where(Playlist.group_name == group)
            )
        else:
            stmt = (
                select(Track)
                .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
            )
        if like_singers:
            stmt = stmt.where(Track.norm_singers.like(f'%{like_singers}%'))
        if like_album:
            stmt = stmt.where(Track.norm_album.like(f'%{like_album}%'))
        if album_exact:
            stmt = stmt.where(Track.album == album_exact)
        if with_url:
            stmt = stmt.where(Track.download_url != '')
        stmt = stmt.distinct()

        out: list[dict] = []
        for t in session.execute(stmt).scalars().all():
            out.append({
                'track_id': t.id, 'song_name': t.song_name, 'singers': t.singers,
                'album': t.album, 'ext': t.ext, 'file_size': t.file_size,
                'file_size_bytes': t.file_size_bytes, 'duration': t.duration,
                'duration_s': t.duration_s, 'bitrate': t.bitrate, 'cover_url': t.cover_url,
                'source': t.source, 'source_cn': t.source_cn, 'source_client': t.source_client,
                'identifier': t.identifier, 'download_url': t.download_url,
                'netease_id': t.netease_id, 'lyric': t.has_lyric,
                'previewable': t.previewable, 'downloadable': t.downloadable,
            })
        return out

    # ---------------------------------------------------------------- 序列化
    @staticmethod
    def to_brief(track: Track) -> dict:
        '''本地曲库检索结果形态'''
        return {
            'id': f'Idx#{track.id}',
            'track_id': track.id,
            'song_name': track.song_name,
            'singers': track.singers,
            'album': track.album,
            'ext': track.ext,
            'file_size': track.file_size,
            'duration': track.duration,
            'duration_s': track.duration_s,
            'bitrate': track.bitrate,
            'cover_url': track.cover_url,
            'lyric': track.has_lyric,
            'source': track.source,
            'source_cn': track.source_cn,
            'previewable': track.previewable,
            'downloadable': track.downloadable,
        }

    @staticmethod
    def to_full(track: Track) -> dict:
        '''歌单曲目形态: 附带可回放的 _song 精简副本(不含歌词正文)'''
        try:
            raw: dict[str, Any] = json.loads(track.raw_json) if track.raw_json else {}
        except (ValueError, TypeError):
            raw = {}
        return {
            'id': f'T{track.id}',
            'track_id': track.id,
            'song_name': track.song_name,
            'singers': track.singers,
            'album': track.album,
            'ext': track.ext,
            'file_size': track.file_size,
            'duration': track.duration,
            'duration_s': track.duration_s,
            'bitrate': track.bitrate,
            'cover_url': track.cover_url,
            'lyric': track.has_lyric,
            'source': track.source,
            'source_cn': track.source_cn,
            'netease_id': track.netease_id,
            'voice_id': track.voice_id,
            'article_url': track.article_url,
            'previewable': track.previewable,
            'downloadable': track.downloadable,
            '_song': {
                'source': track.source_client or f'{track.source}MusicClient',
                'song_name': track.song_name,
                'singers': track.singers,
                'album': track.album,
                'ext': track.ext.lower(),
                'file_size_bytes': track.file_size_bytes,
                'duration_s': track.duration_s,
                'cover_url': track.cover_url,
                'download_url': track.download_url,
                'identifier': track.identifier,
                'bitrate': track.bitrate,
                **{k: v for k, v in raw.items() if k not in _RAW_SHADOWED},
            },
        }
