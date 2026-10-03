'''
Function:
    歌单仓储 —— 民族歌单/专题曲库读取、单歌单曲目、索引页聚合数据。
'''
from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.domain.catalog import COLLECTION_ALBUMS, ethnic_groups
from app.domain.normalize import split_singers
from app.models import Playlist, PlaylistTrack, Track
from app.repositories.track_repo import TrackRepository


class PlaylistRepository:
    def __init__(self, session: Session, engine: Engine) -> None:
        self.session = session
        self.engine = engine

    # ---------------------------------------------------------------- 基础读取
    def get_by_key(self, key: str) -> Playlist | None:
        return self.session.execute(
            select(Playlist).where(Playlist.key == key)
        ).scalars().first()

    def list_by_platform(self, platform: str) -> list[Playlist]:
        return list(self.session.execute(
            select(Playlist).where(Playlist.platform == platform)
        ).scalars().all())

    def list_ethnic(self) -> list[Playlist]:
        '''按固定顺序返回 55 少数民族 + 汉族民间小调'''
        rows = {
            p.key: p for p in self.session.execute(
                select(Playlist).where(Playlist.platform == 'ethnos')
            ).scalars().all()
        }
        ordered: list[Playlist] = []
        for g in ethnic_groups():
            if p := rows.get(g['key']):
                ordered.append(p)
        if han := rows.get('han'):
            ordered.append(han)
        return ordered

    def list_topics(self) -> list[dict]:
        items = []
        for p in self.list_by_platform('topic'):
            cover = self.session.execute(
                select(Track.cover_url)
                .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .where(PlaylistTrack.playlist_id == p.id, Track.cover_url != '')
                .limit(1)
            ).scalar_one_or_none() or p.cover
            items.append({'key': p.key, 'name': p.group_name or p.name,
                          'group': p.group_name, 'count': p.track_count, 'cover': cover})
        items.sort(key=lambda x: x['key'])
        return items

    # ---------------------------------------------------------------- 曲目
    def tracks_of(self, playlist: Playlist, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        rows = self.session.execute(
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == playlist.id)
            .order_by(PlaylistTrack.position)
            .offset(offset)
            .limit(limit if limit is not None else -1)
        ).scalars().all()
        return [TrackRepository.to_full(t) for t in rows]

    def count_tracks(self, playlist_id: int) -> int:
        return int(self.session.execute(
            select(func.count(PlaylistTrack.track_id)).where(PlaylistTrack.playlist_id == playlist_id)
        ).scalar_one())

    def artists_of_group(self, playlist: Playlist) -> list[str]:
        '''该歌单内歌手名, 按曲目数降序'''
        rows = self.session.execute(
            select(Track.singers)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == playlist.id, Track.singers != '')
        ).scalars().all()
        counts: dict[str, int] = {}
        for singers in rows:
            for nm in split_singers(singers):
                counts[nm] = counts.get(nm, 0) + 1
        return [nm for nm, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    # ---------------------------------------------------------------- 索引聚合
    def group_song_counts(self) -> dict[str, int]:
        rows = self.session.execute(
            select(Playlist.group_name, func.count(PlaylistTrack.track_id))
            .join(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
            .where(Playlist.platform == 'ethnos')
            .group_by(Playlist.group_name)
        ).all()
        return {g: int(c) for g, c in rows}

    def removed_artists(self) -> dict[str, list[str]]:
        return self._curation_map('artists_removed')

    def removed_collections(self) -> dict[str, list[str]]:
        return self._curation_map('collections_removed')

    def _curation_map(self, field: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for group, curation in self.session.execute(
            select(Playlist.group_name, Playlist.curation)
            .where(Playlist.platform.in_(('ethnos', 'topic')))
        ):
            values = sorted({str(x).strip() for x in (curation or {}).get(field) or [] if str(x).strip()})
            if values:
                out[group] = values
        return out

    def collection_stats(self) -> list[dict]:
        '''YouTube/电台合集: 命中 COLLECTION_ALBUMS 的专辑, 按所属民族各立一条入口'''
        rows = self.session.execute(
            select(Playlist.group_name, Track.album, Track.cover_url, func.count(Track.id))
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
            .where(Playlist.platform.in_(('ethnos', 'topic')), Track.album.in_(sorted(COLLECTION_ALBUMS)))
            .group_by(Playlist.group_name, Track.album, Track.cover_url)
        ).all()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for group, album, cover, cnt in rows:
            slot = grouped.setdefault((group, album), {'n': 0, 'cover': ''})
            slot['n'] += int(cnt)
            if cover and not slot['cover']:
                slot['cover'] = cover
        hidden = self.removed_collections()
        return [
            {'group': g, 'name': al, 'count': s['n'], 'cover': s['cover']}
            for (g, al), s in sorted(grouped.items(), key=lambda kv: -kv[1]['n'])
            if al not in (hidden.get(g) or [])
        ]
