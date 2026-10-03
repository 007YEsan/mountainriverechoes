'''
Function:
    JSON 缓存 -> SQLite 迁移(幂等)。
    服务层不依赖 HTTP 类型, 打包成 exe 后可由安装器首次启动脚本调用。
    幂等策略:
      - 歌单/曲目/歌词/UI 状态全部走 UPSERT, 重复执行不产生重复行
      - 每个歌单重建前先清空其关联, 保证曲目顺序与磁盘 JSON 完全一致
'''
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.domain.catalog import ETHNIC_CONFIRMED, HAN_FOLK_GROUP, ethnic_groups
from app.domain.normalize import core_name, dedup_key, norm_str, recording_key, split_singers
from app.models import ALL_MODELS, Artist, Lyric, MetaEntry, Playlist, PlaylistTrack, Track, UiState
from app.models.base import Base, now_ms

logger = logging.getLogger(__name__)

SCHEMA_V = 2
_BATCH = 400
_BLANKS = {'NULL', 'NONE'}


@dataclass
class MigrationStats:
    playlists: int = 0
    tracks_seen: int = 0
    tracks_created: int = 0
    tracks_upgraded: int = 0
    lyrics_created: int = 0
    associations: int = 0
    artists: int = 0
    ui_state_keys: int = 0
    skipped_files: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def as_dict(self) -> dict:
        return {
            'playlists': self.playlists, 'tracks_seen': self.tracks_seen,
            'tracks_created': self.tracks_created, 'tracks_upgraded': self.tracks_upgraded,
            'lyrics_created': self.lyrics_created, 'associations': self.associations,
            'artists': self.artists, 'ui_state_keys': self.ui_state_keys,
            'skipped_files': self.skipped_files, 'elapsed_ms': self.elapsed_ms,
        }


def _clean(value: Any) -> str:
    v = str(value).strip() if value is not None else ''
    return '' if v.upper() in _BLANKS else v


def _classify(path: Path) -> tuple[str, str] | None:
    '''按文件名判定歌单类别 -> (platform, kind); 不识别返回 None'''
    stem = path.stem
    if stem == 'index_snapshot':
        return None
    if stem == 'han' or stem.startswith('han_'):
        return 'ethnos', '民族歌单'
    if stem[:1] in {'e', 't'} and stem[1:3].isdigit():
        return ('ethnos', '民族歌单') if stem[:1] == 'e' else ('topic', '专题曲库')
    return 'custom', '自建歌单'


def _key_from_doc(doc: dict, path: Path) -> str:
    return str(doc.get('key') or path.stem.split('_', 1)[0])


def _track_row(t: dict, raw: dict, *, keep_raw: bool = False) -> dict:
    song_name = _clean(t.get('song_name')) or '未知曲目'
    singers = _clean(t.get('singers')) or '未知歌手'
    album = _clean(t.get('album'))
    size_bytes = int(raw.get('file_size_bytes') or 0)
    return {
        'dedup_key': recording_key(
            song_name=song_name, singers=singers, source=_clean(t.get('source')),
            duration_s=int(t.get('duration_s') or 0), size_bytes=size_bytes,
        ),
        'dedup_core': dedup_key(song_name=song_name, singers=singers),
        'song_name': song_name,
        'core_name': core_name(song_name),
        'norm_name': norm_str(song_name),
        'norm_singers': norm_str(singers),
        'norm_album': norm_str(album),
        'singers': singers,
        'album': album,
        'ext': str(_clean(t.get('ext'))).lstrip('.').upper(),
        'file_size': _clean(t.get('file_size')),
        'file_size_bytes': int(raw.get('file_size_bytes') or 0),
        'bitrate': _clean(t.get('bitrate')),
        'duration': _clean(t.get('duration')),
        'duration_s': int(t.get('duration_s') or 0),
        'cover_url': _clean(t.get('cover_url')),
        'source': _clean(t.get('source')),
        'source_cn': _clean(t.get('source_cn')),
        'source_client': _clean(raw.get('source')),
        'identifier': _clean(raw.get('identifier')),
        'download_url': str(raw.get('download_url') or '').strip(),
        'netease_id': _clean(t.get('netease_id')),
        'voice_id': _clean(t.get('voice_id')),
        'article_url': _clean(t.get('article_url')),
        'previewable': bool(t.get('previewable')),
        'downloadable': bool(t.get('downloadable')),
        'has_lyric': bool(t.get('lyric')),
        'raw_json': json.dumps(raw, ensure_ascii=False, separators=(',', ':')) if keep_raw else '',
    }


def _richness(row: dict) -> tuple:
    '''同一 dedup_key 多份候选时挑信息最全的: 有直链 > 有封面 > 有歌词 > 时长更长'''
    return (
        1 if row['download_url'] else 0,
        1 if row['cover_url'] else 0,
        1 if row['has_lyric'] else 0,
        int(row['duration_s'] or 0),
    )


def migrate_from_json(
    engine: Engine,
    *,
    cache_dir: Path,
    ui_state_path: Path | None = None,
    include_lyrics: bool = True,
    only_missing: bool = False,
    keep_raw: bool = False,
) -> MigrationStats:
    '''迁移入口。only_missing=True 时跳过已存在的歌单。'''
    started = time.perf_counter()
    stats = MigrationStats()
    Base.metadata.create_all(engine)

    files = _collect_playlist_files(cache_dir)
    if not files:
        raise FileNotFoundError(f'缓存目录中没有可迁移的歌单 JSON: {cache_dir}')

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:                            # noqa: BLE001 - 单文件坏不阻断整体
            stats.skipped_files.append(f'{path.name}: 解析失败 {exc}')
            logger.warning('跳过损坏文件 %s: %s', path.name, exc)
            continue
        if doc.get('v') != SCHEMA_V:
            stats.skipped_files.append(f'{path.name}: schema v{doc.get("v")} 不匹配')
            continue

        key = _key_from_doc(doc, path)
        if only_missing and _playlist_exists(engine, key):
            continue
        try:
            partial = _migrate_playlist(
                engine, key=key, doc=doc, path=path,
                include_lyrics=include_lyrics, keep_raw=keep_raw,
            )
        except Exception as exc:                            # noqa: BLE001
            stats.skipped_files.append(f'{path.name}: {exc}')
            logger.exception('歌单迁移失败 %s', path.name)
            continue
        stats.playlists += 1
        stats.tracks_seen += partial['seen']
        stats.tracks_created += partial['created']
        stats.tracks_upgraded += partial['upgraded']
        stats.lyrics_created += partial['lyrics']
        stats.associations += partial['assoc']
        logger.info('已迁移歌单 %-14s 曲目 %d', key, partial['seen'])

    stats.artists = rebuild_artists(engine)
    stats.ui_state_keys = _import_ui_state(engine, ui_state_path)
    _refresh_fts(engine)
    _write_meta(engine, stats)
    stats.elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info('迁移完成 %s', stats.as_dict(), extra={'mre_migration': stats.as_dict()})
    return stats


def _collect_playlist_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    seen: dict[str, Path] = {}
    for pattern in ('e*_*.json', 'han_*.json', 't*_*.json', 'e*.json', 'han.json'):
        for p in sorted(cache_dir.glob(pattern)):
            seen.setdefault(p.name, p)
    return [p for p in sorted(seen.values(), key=lambda x: x.name) if _classify(p) is not None]


def _playlist_exists(engine: Engine, key: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(Playlist.id).where(Playlist.key == key)).first() is not None


def _migrate_playlist(
    engine: Engine, *, key: str, doc: dict, path: Path, include_lyrics: bool, keep_raw: bool = False,
) -> dict:
    platform, kind = _classify(path) or ('custom', '自建歌单')
    group_name = str(doc.get('group') or '').strip() or key

    # ---- 1. 本歌单内归并重复条目(按 dedup_key), 保留信息最全的一份
    rows: dict[str, dict] = {}
    lyric_of: dict[str, str] = {}
    order: list[str] = []
    for t in (doc.get('tracks') or []):
        row = _track_row(t, t.get('_song') or {}, keep_raw=keep_raw)
        dk = row['dedup_key']
        if dk in rows:
            if _richness(rows[dk]) >= _richness(row):
                continue
        else:
            order.append(dk)
        rows[dk] = row
        if include_lyrics:
            content = str((t.get('_song') or {}).get('lyric') or '')
            if content:
                lyric_of[dk] = content

    curation = {
        'artists_added': list(doc.get('artists_added') or []),
        'artists_removed': list(doc.get('artists_removed') or []),
        'artists_pinned': list(doc.get('artists_pinned') or []),
        'artist_order': list(doc.get('artist_order') or []),
        'collections_removed': list(doc.get('collections_removed') or []),
        'tracks_pinned': list(doc.get('tracks_pinned') or []),
        'track_order': list(doc.get('track_order') or []),
        'edited_by': list(doc.get('edited_by') or []),
        'edited_at': list(doc.get('edited_at') or []),
    }
    playlist_row = {
        'key': key, 'platform': platform, 'kind': kind,
        'name': str(doc.get('name') or group_name),
        'group_name': group_name,
        'cover': str(doc.get('cover') or ''),
        'track_count': len(rows),
        'built_at': str(doc.get('built_at') or ''),
        'partial': bool(doc.get('partial')),
        'schema_v': int(doc.get('v') or SCHEMA_V),
        # kws/curation 是 JSONText 列, 直接给 Python 对象, 不能再 dumps(否则二次编码)
        'kws': list(doc.get('kws') or []),
        'curation': curation,
    }

    created = upgraded = lyrics_count = assoc = 0
    id_of: dict[str, int] = {}

    with engine.begin() as conn:
        pid = conn.execute(
            sqlite_insert(Playlist).values(**playlist_row)
            .on_conflict_do_update(index_elements=['key'], set_=playlist_row)
            .returning(Playlist.id)
        ).scalar_one()

        # 先清空该歌单关联: 让外部直接改 JSON 后重跑迁移也能对齐顺序
        conn.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == pid))

        for start in range(0, len(order), _BATCH):
            chunk = order[start:start + _BATCH]
            existing = {
                r.dedup_key: r for r in conn.execute(
                    select(Track.id, Track.dedup_key, Track.download_url, Track.cover_url)
                    .where(Track.dedup_key.in_(chunk))
                )
            }
            for dk in chunk:
                row = rows[dk]
                cur = existing.get(dk)
                if cur is None:
                    tid = conn.execute(sqlite_insert(Track).values(**row)).inserted_primary_key[0]
                    created += 1
                else:
                    tid = cur.id
                    # 已存在: 仅在旧记录缺直链/封面时升级, 不动其余字段
                    patch = {}
                    if not cur.download_url and row['download_url']:
                        patch.update(download_url=row['download_url'], file_size_bytes=row['file_size_bytes'],
                                     previewable=row['previewable'], downloadable=row['downloadable'])
                    if not cur.cover_url and row['cover_url']:
                        patch['cover_url'] = row['cover_url']
                    if patch:
                        conn.execute(update(Track).where(Track.id == tid).values(**patch))
                        upgraded += 1
                id_of[dk] = tid

            for dk in chunk:
                content = lyric_of.get(dk)
                if not content:
                    continue
                conn.execute(
                    sqlite_insert(Lyric).values(track_id=id_of[dk], content=content)
                    .on_conflict_do_update(index_elements=['track_id'], set_={'content': content})
                )
                lyrics_count += 1

            conn.execute(
                sqlite_insert(PlaylistTrack).values([
                    {'playlist_id': pid, 'track_id': id_of[dk], 'position': start + i, 'pinned': False}
                    for i, dk in enumerate(chunk)
                ]).on_conflict_do_nothing()
            )
            assoc += len(chunk)

    return {'seen': len(rows), 'created': created, 'upgraded': upgraded,
            'lyrics': lyrics_count, 'assoc': assoc}


def rebuild_artists(engine: Engine) -> int:
    '''重算歌手聚合。语意见 app/domain/catalog.ETHNIC_CONFIRMED: 权威歌手只归指定民族。'''
    agg: dict[str, dict] = {}          # name -> {'total': int, 'groups': {g: n}, 'cover': str}
    with engine.begin() as conn:
        conn.execute(delete(Artist))
        for entry in conn.execute(
            select(Playlist.id, Playlist.group_name, Playlist.curation)
            .where(Playlist.platform.in_(('ethnos', 'topic')))
            .execution_options(stream_results=True, yield_per=1000)
        ):
            pid, group, curation = entry
            removed = {str(x).strip() for x in (curation or {}).get('artists_removed') or []}
            rows = conn.execute(
                select(Track.singers, Track.cover_url)
                .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .where(PlaylistTrack.playlist_id == pid)
            ).all()
            for singers, cover in rows:
                for nm in split_singers(singers):
                    if nm in removed:
                        continue
                    slot = agg.setdefault(nm, {'total': 0, 'groups': {}, 'cover': ''})
                    slot['total'] += 1
                    slot['groups'][group] = slot['groups'].get(group, 0) + 1
                    if not slot['cover'] and cover:
                        slot['cover'] = cover

        rows_to_insert = []
        stamp = now_ms()
        for nm, slot in agg.items():
            if nm in ETHNIC_CONFIRMED:
                pairs = [(ETHNIC_CONFIRMED[nm], slot['total'])]
            else:
                pairs = list(slot['groups'].items())
            for group, count in pairs:
                rows_to_insert.append({
                    'name': nm, 'group_name': group, 'song_count': count,
                    'cover': slot['cover'], 'confirmed': nm in ETHNIC_CONFIRMED,
                })
        if rows_to_insert:
            values = [
                {k: r[k] for k in ('name', 'group_name', 'song_count', 'cover', 'confirmed')}
                for r in rows_to_insert
            ]
            for i in range(0, len(values), _BATCH):
                conn.execute(
                    sqlite_insert(Artist).values(values[i:i + _BATCH])
                    .on_conflict_do_update(
                        index_elements=['name', 'group_name'],
                        set_={'song_count': sqlite_insert(Artist).excluded.song_count,
                              'cover': sqlite_insert(Artist).excluded.cover,
                              'confirmed': sqlite_insert(Artist).excluded.confirmed},
                    )
                )
        return len(rows_to_insert)


def _import_ui_state(engine: Engine, ui_state_path: Path | None) -> int:
    '''导入旧版 ui_state.json: 顶层 key 逐条落 ui_state 表'''
    if ui_state_path is None or not ui_state_path.exists():
        return 0
    try:
        data = json.loads(ui_state_path.read_text(encoding='utf-8'))
    except Exception as exc:                                # noqa: BLE001
        logger.warning('UI 状态导入失败 %s: %s', ui_state_path.name, exc)
        return 0
    if not isinstance(data, dict):
        return 0
    stamp = now_ms()
    count = 0
    with engine.begin() as conn:
        for k, v in data.items():
            conn.execute(
                sqlite_insert(UiState)
                .values(key=str(k)[:128], value=v, updated_at=stamp)
                .on_conflict_do_update(
                    index_elements=['key'],
                    set_={'value': v, 'updated_at': stamp},
                )
            )
            count += 1
    return count


def _refresh_fts(engine: Engine) -> None:
    '''FTS 可能晚于数据创建(如先迁移后建索引), 这里强制重建一次'''
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO tracks_fts(tracks_fts) VALUES('rebuild')")
    except Exception:                                       # noqa: BLE001 - 索引缺失不影响主流程
        pass


def _write_meta(engine: Engine, stats: MigrationStats) -> None:
    stamp = now_ms()
    with engine.begin() as conn:
        conn.execute(
            sqlite_insert(MetaEntry)
            .values(key='migration', value=stats.as_dict(), updated_at=stamp)
            .on_conflict_do_update(index_elements=['key'], set_={'value': stats.as_dict(), 'updated_at': stamp})
        )
        conn.execute(
            sqlite_insert(MetaEntry)
            .values(key='schema_version', value={'version': SCHEMA_V}, updated_at=stamp)
            .on_conflict_do_update(index_elements=['key'], set_={'value': {'version': SCHEMA_V}, 'updated_at': stamp})
        )
