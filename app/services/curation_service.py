'''
Function:
    策展编辑服务 —— 民族歌单协作编辑(增删歌手/曲目、搬库、改署名、置顶排序)。

    语义逐条复刻旧版 webui/mountainriverechoes.py 的 api_ethnos_edit():
      - 旧版改的是「某民族的单个 JSON 文件」(tracks + 策展名单混在一个 dict 里)
      - 新版拆成两处: 曲目归属落 playlist_tracks 关联, 策展名单落 playlists.curation(JSON)
      - 曲目本身是全局唯一的(按 recording_key 去重), 删关联=该民族不再显示, 全库无引用则物理删除

    服务层不依赖 Flask: 入参是纯 dict, 出错抛 app.errors 里的类型化异常。
    索引缓存失效由调用方注入回调(invalidate), 避免服务层反向依赖 library 服务。
'''
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.domain.catalog import ETHNIC_CONFIRMED, HAN_FOLK_GROUP, ethnic_groups
from app.domain.normalize import core_name, dedup_key, norm_str, recording_key, split_singers
from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import session_scope
from app.models import Artist, Playlist, PlaylistTrack, Track, now_ms
from app.repositories.playlist_repo import PlaylistRepository
from app.repositories.state_repo import StateRepository
from app.services.migration_service import SCHEMA_V, rebuild_artists
from app.services.online_search_service import SOURCE_NAMES
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 入参边界
_MAX_NAME = 128          # 歌手名/合集名
_MAX_SONG = 256          # 歌名
_MAX_FIELD = 500         # 专辑/署名等自由文本(与列宽对齐)
_MAX_LIST = 3000         # 批量条目上限
_TRACE_KEEP = 50         # 编辑留痕只留最近 50 条
# 受影响的歌手数超过这个数就整表重算: 逐个重算反而更慢
_ARTIST_SYNC_LIMIT = 32
# 与前端 ethTrackKey 一致: 置顶/次序存的是「原始」复合键, 不做归一化
_KEY_SEP = '\x1f'
_UI_CUSTOM_KEY = 'cm_ethnic_custom'

_CURATION_KEYS = (
    'artists_added', 'artists_removed', 'artists_pinned', 'artist_order',
    'collections_removed', 'tracks_pinned', 'track_order', 'edited_by', 'edited_at',
)

_NON_NAME_RE = re.compile(r'[\W_]+')


# ---------------------------------------------------------------- 小工具
def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ''


def _truthy(value: Any) -> bool:
    return bool(value)


def _name(value: Any, *, label: str) -> str:
    '''必填的歌手/合集名: 空值与超长都拒绝, 防止恶意长串入库'''
    v = _text(value)
    if not v:
        raise ValidationError(f'缺少{label}')
    if len(v) > _MAX_NAME:
        raise ValidationError(f'{label}过长(最多 {_MAX_NAME} 字)')
    return v


def _song_name(value: Any) -> str:
    v = _text(value)
    if len(v) > _MAX_SONG:
        raise ValidationError(f'歌名过长(最多 {_MAX_SONG} 字)')
    return v


def _field(src: Any, name: str) -> Any:
    return src.get(name) if isinstance(src, dict) else getattr(src, name, None)


def _track_key(src: Any) -> tuple[str, str, str]:
    '''复合键(归一化): 歌名+歌手+音源。
    只按歌名定位会把同名不同歌手的版本一并删掉(景颇族《目瑙纵歌》实测误删 24 条)。'''
    return (
        norm_str(_field(src, 'song_name')),
        norm_str(_field(src, 'singers')),
        norm_str(_field(src, 'source')),
    )


def _raw_key(src: Any) -> str:
    '''复合键(不归一化): 与前端 ethTrackKey 完全一致, 置顶/次序按它存取'''
    return _KEY_SEP.join((
        str(_field(src, 'song_name') or ''),
        str(_field(src, 'singers') or ''),
        str(_field(src, 'source') or ''),
    ))


def _key_dicts(value: Any) -> list[dict]:
    '''批量入参 [{song_name, singers, source}...]; 只收 dict, 字段一律截断'''
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value[:_MAX_LIST]:
        if not isinstance(item, dict):
            continue
        out.append({
            'song_name': _song_name(item.get('song_name')),
            'singers': _text(item.get('singers'))[:_MAX_FIELD],
            'source': _text(item.get('source'))[:64],
        })
    return out


def _name_dedup(song_name: Any) -> str:
    '''add_tracks 的指纹: 非文字符号全剔除后取前 40 字'''
    return _NON_NAME_RE.sub('', str(song_name or '').lower())[:40]


def _known_keys() -> dict[str, str]:
    '''民族标识 -> 歌单 key。既接受 e26 这样的 key, 也接受「景颇族」这样的族名'''
    groups = ethnic_groups()
    out = {g['key']: g['key'] for g in groups}
    out.update({g['name']: g['key'] for g in groups})
    out.update({'han': 'han', '汉族': 'han', HAN_FOLK_GROUP: 'han'})
    return out


def _resolve_group(value: Any) -> str:
    key = _known_keys().get(_text(value))
    if key is None:
        raise ValidationError('未知的民族')
    return key


def _group_name(key: str) -> str | None:
    if key == 'han':
        return HAN_FOLK_GROUP
    return next((g['name'] for g in ethnic_groups() if g['key'] == key), None)


def _editor(value: Any) -> str:
    return _text(value)[:24] or 'anonymous'


def _blank_curation(curation: Any) -> dict:
    '''补齐 9 个策展字段, 一律返回新的可变 list(旧 JSON 里缺字段是常态)'''
    src = curation if isinstance(curation, dict) else {}
    return {k: list(src.get(k) or []) if isinstance(src.get(k), list) else [] for k in _CURATION_KEYS}


def _trace(curation: dict, label: str) -> None:
    '''编辑留痕: 只留最近 _TRACE_KEEP 条, 两个列表一一对应'''
    curation['edited_by'].append(label[:200])
    curation['edited_at'].append(int(time.time()))
    curation['edited_by'] = curation['edited_by'][-_TRACE_KEEP:]
    curation['edited_at'] = curation['edited_at'][-_TRACE_KEEP:]


def _unban(curation: dict, name: str) -> None:
    '''挂了新歌的歌手必须可见: 从移除名单解禁并登记进册'''
    if name in (curation.get('artists_removed') or []):
        curation['artists_removed'] = [x for x in curation['artists_removed'] if x != name]
    if name not in (curation.get('artists_added') or []):
        curation['artists_added'].append(name)


# ---------------------------------------------------------------- 数据访问
def _links(session: Session, playlist_id: int) -> list[PlaylistTrack]:
    return list(session.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    ).scalars().all())


def _count(session: Session, playlist_id: int) -> int:
    return int(session.execute(
        select(func.count(PlaylistTrack.track_id)).where(PlaylistTrack.playlist_id == playlist_id)
    ).scalar_one())


def _max_position(session: Session, playlist_id: int) -> int:
    return int(session.execute(
        select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist_id)
    ).scalar_one() or -1)


def _upsert_track(session: Session, row: dict) -> Track:
    '''按 dedup_key 取或建: 同一录音在全库只存一行, 可被多个歌单引用'''
    found = session.execute(
        select(Track).where(Track.dedup_key == row['dedup_key'])
    ).scalars().first()
    if found is not None:
        # 已存在时只补缺失的直链/封面, 不动其余字段(与迁移口径一致)
        if not found.download_url and row['download_url']:
            found.download_url = row['download_url']
            found.file_size_bytes = row['file_size_bytes']
            found.previewable = row['previewable']
            found.downloadable = row['downloadable']
        if not found.cover_url and row['cover_url']:
            found.cover_url = row['cover_url']
        return found
    track = Track(**row)
    session.add(track)
    session.flush()
    return track


def _attach(session: Session, playlist_id: int, track_id: int, position: int) -> None:
    session.execute(
        sqlite_insert(PlaylistTrack)
        .values(playlist_id=playlist_id, track_id=track_id, position=position, pinned=False)
        .on_conflict_do_nothing()
    )


def _detach(session: Session, links: list[PlaylistTrack]) -> list[int]:
    '''解绑曲目; 返回被解绑的 track_id 供调用方统计'''
    ids = [int(lk.track_id) for lk in links]
    for lk in links:
        session.delete(lk)
    session.flush()
    _prune_orphans(session, ids)
    return ids


def _prune_orphans(session: Session, track_ids: Iterable[int]) -> None:
    '''删除已无任何歌单引用的曲目行。

    检索(TrackRepository.search_library)只扫 tracks 表、不 join playlist_tracks,
    留着孤儿行会表现为「歌单里删掉了, 全局搜索还能搜到」。
    '''
    ids = sorted({int(i) for i in track_ids if i})
    if not ids:
        return
    linked = {
        row[0] for row in session.execute(
            select(PlaylistTrack.track_id).where(PlaylistTrack.track_id.in_(ids))
        )
    }
    dead = [i for i in ids if i not in linked]
    if not dead:
        return
    session.execute(delete(Track).where(Track.id.in_(dead)))
    session.flush()


def _row_from_track(track: Track, *, singers: str | None = None) -> dict:
    '''现有曲目 -> 可插入的 tracks 行; singers 用于改署名(换歌手即换 dedup_key)'''
    name_singers = singers if singers is not None else track.singers
    return {
        'dedup_key': recording_key(
            song_name=track.song_name, singers=name_singers, source=track.source,
            duration_s=track.duration_s, size_bytes=track.file_size_bytes,
        ),
        'dedup_core': dedup_key(song_name=track.song_name, singers=name_singers),
        'song_name': track.song_name,
        'core_name': core_name(track.song_name),
        'norm_name': norm_str(track.song_name),
        'norm_singers': norm_str(name_singers),
        'norm_album': norm_str(track.album),
        'singers': name_singers,
        'album': track.album,
        'ext': track.ext,
        'file_size': track.file_size,
        'file_size_bytes': track.file_size_bytes,
        'bitrate': track.bitrate,
        'duration': track.duration,
        'duration_s': track.duration_s,
        'cover_url': track.cover_url,
        'source': track.source,
        'source_cn': track.source_cn,
        'source_client': track.source_client,
        'identifier': track.identifier,
        'download_url': track.download_url,
        'netease_id': track.netease_id,
        'voice_id': track.voice_id,
        'article_url': track.article_url,
        'previewable': track.previewable,
        'downloadable': track.downloadable,
        'has_lyric': track.has_lyric,
        'raw_json': track.raw_json,
    }


def _row_from_brief(brief: dict, *, singers: str | None = None) -> dict:
    '''前端回传的曲目简档 / 会话里的可播放载荷 -> tracks 行'''
    raw = brief.get('_song') if isinstance(brief.get('_song'), dict) else {}

    def pick(*keys: str) -> Any:
        for key in keys:
            for src in (brief, raw):
                value = src.get(key)
                if value not in (None, ''):
                    return value
        return ''

    song_name = _song_name(pick('song_name')) or '未知曲目'
    name_singers = str(singers or pick('singers') or '未知歌手')[:_MAX_FIELD]
    album = str(pick('album'))[:_MAX_FIELD]
    source = str(pick('source')).strip().removesuffix('MusicClient')[:32]
    url = str(pick('download_url')).strip()
    size_bytes = int(pick('file_size_bytes') or 0)
    duration_s = int(pick('duration_s') or 0)
    return {
        'dedup_key': recording_key(
            song_name=song_name, singers=name_singers, source=source,
            duration_s=duration_s, size_bytes=size_bytes,
        ),
        'dedup_core': dedup_key(song_name=song_name, singers=name_singers),
        'song_name': song_name,
        'core_name': core_name(song_name),
        'norm_name': norm_str(song_name),
        'norm_singers': norm_str(name_singers),
        'norm_album': norm_str(album),
        'singers': name_singers,
        'album': album,
        'ext': str(pick('ext')).lstrip('.').upper()[:16],
        'file_size': str(pick('file_size'))[:32],
        'file_size_bytes': size_bytes,
        'bitrate': str(pick('bitrate'))[:32],
        'duration': str(pick('duration'))[:32],
        'duration_s': duration_s,
        'cover_url': str(pick('cover_url')),
        'source': source,
        'source_cn': str(pick('source_cn') or SOURCE_NAMES.get(source, source))[:32],
        'source_client': str(raw.get('source') or '')[:64],
        'identifier': str(pick('identifier'))[:128],
        'download_url': url,
        'netease_id': str(pick('netease_id'))[:64],
        'voice_id': str(pick('voice_id'))[:64],
        'article_url': str(pick('article_url')),
        'previewable': bool(url),
        'downloadable': bool(url),
        'has_lyric': bool(pick('lyric')),
        'raw_json': '',
    }


def _singers_of(links: Iterable[PlaylistTrack]) -> set[str]:
    '''一批关联涉及的全部歌手名(用于事后重算聚合); 必须在解绑之前取'''
    return {nm for lk in links for nm in split_singers(lk.track.singers)}


def _session_item(sid: Any, tid: Any) -> dict | None:
    '''从常驻播放会话里取回完整曲目载荷(前端只回传 sid+id)'''
    items = session_service.items(str(sid or ''))
    if not items:
        return None
    item = items.get(str(tid or ''))
    return item if isinstance(item, dict) else None


# ---------------------------------------------------------------- 编辑上下文
@dataclass
class _Ctx:
    '''一次编辑的共享上下文: 会话 + 来源歌单 + 待写回的策展名单'''

    session: Session
    engine: Engine
    repo: PlaylistRepository
    group: str
    editor: str
    data: dict
    src: Playlist
    curation: dict
    touched: list[Playlist] = field(default_factory=list)
    artists: set[str] = field(default_factory=set)
    artists_all: bool = False
    skip_src: bool = False

    def touch(self, playlist: Playlist) -> None:
        '''登记待重算曲目数的歌单'''
        if all(p is not playlist for p in self.touched):
            self.touched.append(playlist)

    def touch_artists(self, names: Iterable[str]) -> None:
        if not self.artists_all:
            self.artists.update(n for n in names if n)

    def touch_all_artists(self) -> None:
        self.artists_all = True

    def artists_dirty(self) -> bool:
        return self.artists_all or bool(self.artists)


def _dst_playlist(ctx: _Ctx, dst_key: str) -> Playlist:
    '''目标歌单: 必须存在、版本相符且不是来源本身'''
    if dst_key == ctx.group:
        raise ValidationError('目标民族与来源相同')
    dst = ctx.repo.get_by_key(dst_key)
    if dst is None:
        raise NotFoundError(f'目标歌单不存在: {dst_key}')
    if dst.schema_v != SCHEMA_V:
        raise ValidationError('目标歌单版本不符')
    return dst


def _unban_artist_ui(ctx: _Ctx, group_key: str, names: list[str]) -> None:
    '''把歌手从服务端 UI 态的「已移除」名单里解禁(旧版 _ui_unban_artist)。

    库里的 artists_removed 只管索引聚合, 前端歌手卡片过滤读的是 ui_state 的
    cm_ethnic_custom —— 两处都得清, 少一处就表现为「挂了歌还是搜不到」。'''
    if not names:
        return
    group_name = _group_name(group_key)
    if group_name is None:
        return
    repo = StateRepository(ctx.session, ctx.engine)
    entry = repo.ui_state_get(_UI_CUSTOM_KEY)
    if not isinstance(entry, dict):
        return
    body = entry.get('v')
    if not isinstance(body, dict):
        return
    slot = body.get(group_name)
    if not isinstance(slot, dict):
        return
    before = list(slot.get('removed') or [])
    slot['removed'] = [x for x in before if x not in set(names)]
    if slot['removed'] != before:
        added = list(slot.get('added') or [])
        for n in names:
            if n not in added:
                added.append(n)
        slot['added'] = added
        entry['t'] = now_ms()
        repo.ui_state_set(_UI_CUSTOM_KEY, entry)


# ---------------------------------------------------------------- 动作实现
def _act_add_artist(ctx: _Ctx) -> dict:
    '''歌手重新可见: 进「手动添加」名单, 并从「已移除」名单解禁'''
    name = _name(ctx.data.get('name'), label='歌手名')
    if name not in ctx.curation['artists_added']:
        ctx.curation['artists_added'].append(name)
    ctx.curation['artists_removed'] = [x for x in ctx.curation['artists_removed'] if x != name]
    ctx.touch_artists([name])
    return {}


def _act_remove_artist(ctx: _Ctx) -> dict:
    '''歌手隐藏(默认)或连同名下曲目硬删(kill_tracks)'''
    name = _name(ctx.data.get('name'), label='歌手名')
    if name not in ctx.curation['artists_removed']:
        ctx.curation['artists_removed'].append(name)
    ctx.curation['artists_added'] = [x for x in ctx.curation['artists_added'] if x != name]
    ctx.touch_artists([name])

    extra: dict[str, Any] = {}
    if _truthy(ctx.data.get('kill_tracks')):
        picked = [lk for lk in _links(ctx.session, ctx.src.id) if name in split_singers(lk.track.singers)]
        ctx.touch_artists(_singers_of(picked))
        if picked:
            _detach(ctx.session, picked)
        extra['killed'] = len(picked)
    return extra


def _act_save_artist_order(ctx: _Ctx) -> dict:
    '''歌手卡置顶/拖动: 只存「置顶集合 + 其余名单」, 不存位置索引 —— 新增歌手天然排在未排序区'''
    names = [_text(n)[:_MAX_NAME] for n in (ctx.data.get('names') or [])[:_MAX_LIST]]
    pinned = [_text(n)[:_MAX_NAME] for n in (ctx.data.get('pinned') or [])[:_MAX_LIST]]
    names = [n for n in names if n]
    pinned = [n for n in pinned if n]
    ctx.curation['artists_pinned'] = list(dict.fromkeys(pinned))
    ctx.curation['artist_order'] = [n for n in dict.fromkeys(names) if n not in ctx.curation['artists_pinned']]
    return {'pinned': len(ctx.curation['artists_pinned'])}


def _act_save_track_order(ctx: _Ctx) -> dict:
    '''曲目置顶/拖动: 同样只存名单+置顶集合(原始复合键)'''
    keys = _key_dicts(ctx.data.get('keys'))
    pinned = _key_dicts(ctx.data.get('pinned'))
    pinned_keys = {_raw_key(k) for k in pinned}
    ctx.curation['tracks_pinned'] = list(dict.fromkeys(_raw_key(k) for k in pinned))
    ctx.curation['track_order'] = [
        k for k in dict.fromkeys(_raw_key(k) for k in keys) if k not in pinned_keys
    ]
    return {'pinned': len(ctx.curation['tracks_pinned'])}


def _act_reassign_singer(ctx: _Ctx) -> dict:
    '''同库内改归属: 把某条曲目的歌手改成目标歌手(修正错误署名/未署名)'''
    tname = _song_name(ctx.data.get('tname'))
    tsingers = _text(ctx.data.get('tsingers'))[:_MAX_FIELD]
    tsource = _text(ctx.data.get('tsource'))[:64]
    new_singers = _name(ctx.data.get('new_singers'), label='目标歌手')
    want = _track_key({'song_name': tname, 'singers': tsingers, 'source': tsource})

    link = next((lk for lk in _links(ctx.session, ctx.src.id) if _track_key(lk.track) == want), None)
    if link is None:
        raise NotFoundError('未找到该曲目')

    old_singers = link.track.singers
    moved = _upsert_track(ctx.session, _row_from_track(link.track, singers=new_singers))
    if moved.id != link.track_id:
        old_id = link.track_id
        clash = ctx.session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == ctx.src.id, PlaylistTrack.track_id == moved.id,
            )
        ).scalars().first()
        if clash is not None:
            ctx.session.delete(link)               # 目标行已在册, 丢掉旧行即可
        else:
            link.track_id = moved.id
        ctx.session.flush()
        _prune_orphans(ctx.session, [old_id])

    _unban(ctx.curation, new_singers)
    ctx.touch_artists([*split_singers(old_singers), new_singers])
    _unban_artist_ui(ctx, ctx.group, [new_singers])
    return {'reassigned': new_singers}


def _act_add_to_artist(ctx: _Ctx) -> dict:
    '''把会话里的某首歌挂到目标民族的某歌手名下(跨库复制, 源库不动)'''
    dst_key = _resolve_group(ctx.data.get('dst'))
    artist = _name(ctx.data.get('artist'), label='目标歌手')
    dst = ctx.repo.get_by_key(dst_key)
    if dst is None:
        raise NotFoundError(f'目标歌单不存在: {dst_key}')
    if dst.schema_v != SCHEMA_V:
        raise ValidationError('目标歌单版本不符')

    item = _session_item(ctx.data.get('sid'), ctx.data.get('tid'))
    if item is None:
        raise NotFoundError('会话已过期, 请重新搜索后再试')
    if not str(item.get('download_url') or '').startswith('http'):
        raise ValidationError('该曲目没有可用直链, 无法入库')
    if not _text(item.get('song_name')):
        raise ValidationError('缺少歌名')

    row = _row_from_brief(item, singers=artist)
    want = _track_key({'song_name': row['song_name'], 'singers': artist, 'source': row['source']})
    if want in {_track_key(lk.track) for lk in _links(ctx.session, dst.id)}:
        raise ConflictError(f'《{row["song_name"]}》已在「{artist}」名下')

    track = _upsert_track(ctx.session, row)
    _attach(ctx.session, dst.id, track.id, _max_position(ctx.session, dst.id) + 1)

    curation = _blank_curation(dst.curation)
    _unban(curation, artist)
    _trace(curation, f'{ctx.editor}:add_to_artist:{dst_key}:{artist}')
    dst.curation = curation
    ctx.touch(dst)
    ctx.touch_artists([artist])
    ctx.skip_src = True                            # 目标已落库, 不再回写来源歌单
    _unban_artist_ui(ctx, dst_key, [artist])
    return {
        'added': 1, 'dst': dst_key, 'artist': artist,
        'dst_count': _count(ctx.session, dst.id),
    }


def _act_add_tracks(ctx: _Ctx) -> dict:
    '''批量灌入曲目简档: 按「去符号歌名前 40 字」去重'''
    incoming = ctx.data.get('tracks')
    if not isinstance(incoming, list):
        return {}
    seen = {_name_dedup(lk.track.song_name) for lk in _links(ctx.session, ctx.src.id)}
    position = _max_position(ctx.session, ctx.src.id) + 1
    added = 0
    for raw in incoming[:_MAX_LIST]:
        if not isinstance(raw, dict):
            continue
        song_name = _song_name(raw.get('song_name'))
        fingerprint = _name_dedup(song_name)
        if not song_name or not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        track = _upsert_track(ctx.session, _row_from_brief(raw))
        _attach(ctx.session, ctx.src.id, track.id, position)
        position += 1
        added += 1
        ctx.touch_artists(split_singers(track.singers))
    return {'added': added}


def _act_remove_track(ctx: _Ctx) -> dict:
    '''按复合键删单条; 只有歌名的旧式调用退化为「只删第一条同名」(宁可少删不可误删)'''
    tname = _song_name(ctx.data.get('tname'))
    tsingers = _text(ctx.data.get('tsingers'))[:_MAX_FIELD]
    tsource = _text(ctx.data.get('tsource'))[:64]
    if not tname:
        raise ValidationError('缺少歌名')

    links = _links(ctx.session, ctx.src.id)
    if tsingers or tsource:
        want = _track_key({'song_name': tname, 'singers': tsingers, 'source': tsource})
        picked = [lk for lk in links if _track_key(lk.track) == want]
    else:
        picked = next(([lk] for lk in links if str(lk.track.song_name).strip() == tname), [])
    if not picked:
        raise NotFoundError('未找到该曲目')
    ctx.touch_artists(_singers_of(picked))
    _detach(ctx.session, picked)
    return {}


def _act_remove_tracks(ctx: _Ctx) -> dict:
    '''批量删: keys=[{song_name,singers,source}...], 一律按复合键逐条精确定位'''
    keys = _key_dicts(ctx.data.get('keys'))
    if not keys:
        raise ValidationError('缺少曲目列表')
    want = {_track_key(k) for k in keys}
    picked = [lk for lk in _links(ctx.session, ctx.src.id) if _track_key(lk.track) in want]
    if not picked:
        raise NotFoundError('未找到匹配的曲目')
    ctx.touch_artists(_singers_of(picked))
    _detach(ctx.session, picked)
    return {'removed': len(picked)}


def _act_move_tracks(ctx: _Ctx) -> dict:
    '''跨库搬移曲目: move=源端删除(默认) / copy=源端保留(两边都有)'''
    dst_key = _resolve_group(ctx.data.get('dst'))
    keys = _key_dicts(ctx.data.get('keys'))
    if not keys:
        raise ValidationError('缺少曲目列表')
    dst = _dst_playlist(ctx, dst_key)

    want = {_track_key(k) for k in keys}
    picked = [lk for lk in _links(ctx.session, ctx.src.id) if _track_key(lk.track) in want]
    if not picked:
        raise NotFoundError('未找到匹配的曲目')
    have = {_track_key(lk.track) for lk in _links(ctx.session, dst.id)}
    added = [lk for lk in picked if _track_key(lk.track) not in have]
    if not added:
        raise ValidationError('这些曲目目标歌单里已存在')
    mode = 'copy' if _text(ctx.data.get('mode')).lower() == 'copy' else 'move'

    position = _max_position(ctx.session, dst.id) + 1
    for offset, link in enumerate(added):
        _attach(ctx.session, dst.id, link.track_id, position + offset)
    ctx.touch_artists(_singers_of(added))

    curation = _blank_curation(dst.curation)
    _trace(curation, f'{ctx.editor}:move_in:{dst_key}:{len(added)}')
    dst.curation = curation
    ctx.touch(dst)

    if mode == 'move':
        # 先挂目标再解绑来源: 这样「目标已有」的那些不会被当成孤儿物理删掉
        ctx.touch_artists(_singers_of(picked))
        _detach(ctx.session, picked)
    return {
        'moved': len(added), 'mode': mode, 'dst': dst_key,
        'dst_count': _count(ctx.session, dst.id),
    }


def _act_move_artist(ctx: _Ctx) -> dict:
    '''整个歌手搬库: 按 singers 命中选曲(与 move_tracks 的复合键选曲同源), 两端各清名单'''
    dst_key = _resolve_group(ctx.data.get('dst'))
    name = _name(ctx.data.get('name'), label='歌手名')
    dst = _dst_playlist(ctx, dst_key)

    picked = [lk for lk in _links(ctx.session, ctx.src.id) if name in split_singers(lk.track.singers)]
    if not picked:
        raise NotFoundError(f'「{name}」名下没有曲目')
    have = {_track_key(lk.track) for lk in _links(ctx.session, dst.id)}
    added = [lk for lk in picked if _track_key(lk.track) not in have]

    position = _max_position(ctx.session, dst.id) + 1
    for offset, link in enumerate(added):
        _attach(ctx.session, dst.id, link.track_id, position + offset)

    curation = _blank_curation(dst.curation)
    _unban(curation, name)
    _trace(curation, f'{ctx.editor}:move_artist_in:{dst_key}:{name}:{len(added)}')
    dst.curation = curation
    ctx.touch(dst)

    ctx.touch_artists(_singers_of(picked) | {name})
    _detach(ctx.session, picked)
    for key in ('artists_added', 'artists_removed', 'artists_pinned', 'artist_order'):
        ctx.curation[key] = [x for x in ctx.curation[key] if x != name]
    _unban_artist_ui(ctx, dst_key, [name])
    return {
        'moved': len(added), 'mode': 'move', 'dst': dst_key, 'artist': name,
        'dst_count': _count(ctx.session, dst.id),
        'src_left': _count(ctx.session, ctx.src.id),
    }


def _act_remove_collection(ctx: _Ctx) -> dict:
    '''合集与歌手同权: hide(默认, 只藏卡片)/ restore(取消隐藏)/ kill_tracks(连曲目硬删)'''
    name = _name(ctx.data.get('name'), label='合集名')
    picked = [lk for lk in _links(ctx.session, ctx.src.id) if str(lk.track.album or '').strip() == name]

    if _truthy(ctx.data.get('restore')):
        ctx.curation['collections_removed'] = [
            x for x in ctx.curation['collections_removed'] if x != name
        ]
        # restored 是旧版遗留字段: 全仓无消费方(前端只读 killed / mode), 字面语义还与直觉相反
        # (有曲目被恢复出来时反而为 False)。刻意保持与旧版 webui 逐字一致, 勿按字面语义"纠正"。
        return {'n': len(picked), 'mode': 'restore', 'restored': not len(picked)}
    if _truthy(ctx.data.get('kill_tracks')):
        ctx.touch_artists(_singers_of(picked))
        if picked:
            _detach(ctx.session, picked)
        return {
            'killed': len(picked), 'mode': 'kill',
            'src_left': _count(ctx.session, ctx.src.id),
        }
    if name not in ctx.curation['collections_removed']:
        ctx.curation['collections_removed'].append(name)
    return {'n': len(picked), 'mode': 'hide'}


def _act_move_collection(ctx: _Ctx) -> dict:
    '''整个合集搬库: 选曲口径由 singers 命中换成 album 完全相等, 其余沿用 move_artist'''
    name = _name(ctx.data.get('name'), label='合集名')
    picked = [lk for lk in _links(ctx.session, ctx.src.id) if str(lk.track.album or '').strip() == name]
    if not picked:
        raise NotFoundError(f'「{name}」内没有曲目')
    dst_key = _resolve_group(ctx.data.get('dst'))
    dst = _dst_playlist(ctx, dst_key)

    have = {_track_key(lk.track) for lk in _links(ctx.session, dst.id)}
    added = [lk for lk in picked if _track_key(lk.track) not in have]
    position = _max_position(ctx.session, dst.id) + 1
    for offset, link in enumerate(added):
        _attach(ctx.session, dst.id, link.track_id, position + offset)

    curation = _blank_curation(dst.curation)
    curation['collections_removed'] = [x for x in curation['collections_removed'] if x != name]
    _trace(curation, f'{ctx.editor}:move_collection_in:{dst_key}:{name}:{len(added)}')
    dst.curation = curation
    ctx.touch(dst)

    ctx.touch_artists(_singers_of(picked))
    _detach(ctx.session, picked)
    ctx.curation['collections_removed'] = [
        x for x in ctx.curation['collections_removed'] if x != name
    ]
    return {
        'moved': len(added), 'mode': 'move', 'dst': dst_key, 'collection': name,
        'dst_count': _count(ctx.session, dst.id),
        'src_left': _count(ctx.session, ctx.src.id),
    }


_ACTIONS: dict[str, Callable[[_Ctx], dict]] = {
    'add_artist': _act_add_artist,
    'remove_artist': _act_remove_artist,
    'save_artist_order': _act_save_artist_order,
    'add_to_artist': _act_add_to_artist,
    'move_artist': _act_move_artist,
    'reassign_singer': _act_reassign_singer,
    'add_tracks': _act_add_tracks,
    'remove_track': _act_remove_track,
    'remove_tracks': _act_remove_tracks,
    'move_tracks': _act_move_tracks,
    'save_track_order': _act_save_track_order,
    'remove_collection': _act_remove_collection,
    # 任务清单只列了 12 个, 但前端 01-utils.js 的「合集移动至」确实在发这个动作
    'move_collection': _act_move_collection,
}


# ---------------------------------------------------------------- 歌手聚合
def _resync_artists(engine: Engine, names: Iterable[str]) -> None:
    '''只重算给定歌手的聚合行(规则与 rebuild_artists 完全一致)。

    权威歌手(ETHNIC_CONFIRMED)只归指定民族: 计数是该歌手在全库的总数,
    所以即便只动了一个民族, 也要按「该歌手的全部出现」重新汇总。'''
    targets = sorted({str(n).strip() for n in names if str(n).strip()})
    if not targets:
        return
    with engine.begin() as conn:
        removed_map: dict[str, set[str]] = {}
        for group, curation in conn.execute(
            select(Playlist.group_name, Playlist.curation)
            .where(Playlist.platform.in_(('ethnos', 'topic')))
        ):
            removed_map[group] = {str(x).strip() for x in (curation or {}).get('artists_removed') or []}
        conn.execute(delete(Artist).where(Artist.name.in_(targets)))

        rows: list[dict] = []
        for name in targets:
            key = norm_str(name)
            if not key:
                continue
            total = 0
            groups: dict[str, int] = {}
            cover = ''
            for group, singers, track_cover in conn.execute(
                select(Playlist.group_name, Track.singers, Track.cover_url)
                .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
                .where(Playlist.platform.in_(('ethnos', 'topic')), Track.norm_singers.like(f'%{key}%'))
            ):
                if name not in split_singers(singers):
                    continue                        # LIKE 只是粗筛, 这里精确判定
                if name in (removed_map.get(group) or set()):
                    continue
                total += 1
                groups[group] = groups.get(group, 0) + 1
                if not cover and track_cover:
                    cover = track_cover
            if not total:
                continue                            # 名下已无曲目 -> 不落行
            confirmed = name in ETHNIC_CONFIRMED
            pairs = [(ETHNIC_CONFIRMED[name], total)] if confirmed else list(groups.items())
            for group, count in pairs:
                rows.append({
                    'name': name, 'group_name': group, 'song_count': count,
                    'cover': cover, 'confirmed': confirmed,
                })
        if rows:
            conn.execute(
                sqlite_insert(Artist).values(rows).on_conflict_do_update(
                    index_elements=['name', 'group_name'],
                    set_={
                        'song_count': sqlite_insert(Artist).excluded.song_count,
                        'cover': sqlite_insert(Artist).excluded.cover,
                        'confirmed': sqlite_insert(Artist).excluded.confirmed,
                    },
                )
            )


class CurationService:
    '''民族歌单策展编辑。每个动作一个入口, apply() 为统一分发入口'''

    # ---------------------------------------------------------------- 入口
    def apply(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        '''按 payload['action'] 分发。invalidate 由控制器注入(如 library.invalidate)'''
        data = payload if isinstance(payload, dict) else {}
        action = _text(data.get('action'))
        if action not in _ACTIONS:
            raise ValidationError(f'不支持的编辑动作: {action or "(空)"}')
        return self._execute(action, data, invalidate)

    def add_artist(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('add_artist', payload, invalidate)

    def remove_artist(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('remove_artist', payload, invalidate)

    def save_artist_order(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('save_artist_order', payload, invalidate)

    def save_track_order(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('save_track_order', payload, invalidate)

    def add_to_artist(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('add_to_artist', payload, invalidate)

    def add_tracks(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('add_tracks', payload, invalidate)

    def reassign_singer(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('reassign_singer', payload, invalidate)

    def remove_track(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('remove_track', payload, invalidate)

    def remove_tracks(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('remove_tracks', payload, invalidate)

    def move_tracks(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('move_tracks', payload, invalidate)

    def move_artist(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('move_artist', payload, invalidate)

    def remove_collection(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('remove_collection', payload, invalidate)

    def move_collection(self, payload: dict, *, invalidate: Callable[[], None] | None = None) -> dict:
        return self._execute('move_collection', payload, invalidate)

    # ---------------------------------------------------------------- 执行
    def _execute(
        self, action: str, payload: Any, invalidate: Callable[[], None] | None,
    ) -> dict:
        data = payload if isinstance(payload, dict) else {}
        group = _resolve_group(data.get('group'))
        editor = _editor(data.get('editor'))

        with session_scope() as session:
            engine = session.get_bind()
            repo = PlaylistRepository(session, engine)
            src = repo.get_by_key(group)
            if src is None:
                raise NotFoundError('歌单文件不存在')

            ctx = _Ctx(
                session=session, engine=engine, repo=repo, group=group, editor=editor,
                data=data, src=src, curation=_blank_curation(src.curation),
            )
            extra = _ACTIONS[action](ctx)
            if not ctx.skip_src:
                _trace(ctx.curation, f'{editor}:{action}:{_text(data.get("name")) or _text(data.get("tname"))}')
                ctx.touch(src)
            session.flush()

            counts: dict[str, int] = {}
            for playlist in ctx.touched:
                counts[playlist.key] = _count(session, playlist.id)
                playlist.track_count = counts[playlist.key]
                if playlist is src:
                    playlist.curation = ctx.curation

        if ctx.artists_dirty():
            self._sync_artists(engine, ctx)
        if invalidate is not None:
            invalidate()

        logger.info(
            '策展编辑 group=%s action=%s editor=%s', group, action, editor,
            extra={'mre_curation_action': action, 'mre_curation_group': group},
        )
        result: dict[str, Any] = {'ok': True}
        if not ctx.skip_src:
            result['count'] = counts.get(group, 0)
        result.update(extra)
        return result

    @staticmethod
    def _sync_artists(engine: Engine, ctx: _Ctx) -> None:
        '''歌手聚合同步: 少量歌手逐个重算, 规模大时整表重算(两种口径结果一致)'''
        if ctx.artists_all or len(ctx.artists) > _ARTIST_SYNC_LIMIT:
            rebuild_artists(engine)
            return
        _resync_artists(engine, ctx.artists)
