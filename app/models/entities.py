'''
Function:
    ORM 实体 —— 本地曲库的权威数据结构。
    分层约定: 只有 repositories 层可以直接 import 这里的模型。
'''
from __future__ import annotations

from sqlalchemy import (
    Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JSONText, Base


class Playlist(Base):
    '''歌单: 56 民族歌单 / 专题曲库 / 虚拟歌单, 统一在此表'''

    __tablename__ = 'playlists'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), default='ethnos', nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default='民族歌单', nullable=False)
    name: Mapped[str] = mapped_column(String(255), default='', nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), default='', nullable=False, index=True)
    cover: Mapped[str] = mapped_column(Text, default='', nullable=False)
    track_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    built_at: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schema_v: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    # 搜索种子关键词 / 策展名单(增删/pinned/排序/编辑留痕) —— 结构松散, 以 JSON 存
    kws: Mapped[list] = mapped_column(JSONText(default=[]), default=list, nullable=False)
    curation: Mapped[dict] = mapped_column(JSONText(default={}), default=dict, nullable=False)

    tracks: Mapped[list['PlaylistTrack']] = relationship(
        back_populates='playlist', cascade='all, delete-orphan', passive_deletes=True,
    )


class Track(Base):
    '''曲目: 全库唯一(按 归一化歌名|首歌手 去重), 可被多个歌单引用'''

    __tablename__ = 'tracks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 物理唯一键: 歌名+首歌手+音源+时长+字节数 —— 同一录音在全库只存一行, 但不同录音互不覆盖
    dedup_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    # 逻辑归并键: 歌名+首歌手 —— 检索结果按此去重, 避免同一民歌的多音源版本刷屏
    dedup_core: Mapped[str] = mapped_column(String(512), default='', nullable=False, index=True)
    song_name: Mapped[str] = mapped_column(String(512), default='', nullable=False)
    # 匹配键: core_name=去括号/版本后缀后的主名, norm_name=完整归一化, 二者用于检索打分
    core_name: Mapped[str] = mapped_column(String(512), default='', nullable=False, index=True)
    norm_name: Mapped[str] = mapped_column(String(512), default='', nullable=False, index=True)
    norm_singers: Mapped[str] = mapped_column(String(512), default='', nullable=False, index=True)
    norm_album: Mapped[str] = mapped_column(String(512), default='', nullable=False)

    singers: Mapped[str] = mapped_column(String(512), default='', nullable=False)
    album: Mapped[str] = mapped_column(String(512), default='', nullable=False)
    ext: Mapped[str] = mapped_column(String(16), default='', nullable=False)
    file_size: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bitrate: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    duration: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cover_url: Mapped[str] = mapped_column(Text, default='', nullable=False)

    source: Mapped[str] = mapped_column(String(32), default='', nullable=False, index=True)
    source_cn: Mapped[str] = mapped_column(String(32), default='', nullable=False)
    source_client: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), default='', nullable=False, index=True)
    download_url: Mapped[str] = mapped_column(Text, default='', nullable=False)
    netease_id: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    voice_id: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    article_url: Mapped[str] = mapped_column(Text, default='', nullable=False)

    previewable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    downloadable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    has_lyric: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 原始 _song 全量快照兜底(_song 的字段已全部建模, 默认不灌入以省 ~50MB; --keep-raw 可开)
    raw_json: Mapped[str] = mapped_column(Text, default='', nullable=False)

    lyric: Mapped['Lyric | None'] = relationship(
        back_populates='track', cascade='all, delete-orphan', passive_deletes=True, uselist=False,
    )


class Lyric(Base):
    '''歌词独立表: 正文体积大且检索用不到, 拆出去保证 tracks 表常驻内存页缓存高效'''

    __tablename__ = 'lyrics'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(
        ForeignKey('tracks.id', ondelete='CASCADE'), unique=True, nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, default='', nullable=False)

    track: Mapped['Track'] = relationship(back_populates='lyric')


class PlaylistTrack(Base):
    '''歌单-曲目关联: 同一首歌可以出现在多个民族歌单里'''

    __tablename__ = 'playlist_tracks'
    __table_args__ = (
        UniqueConstraint('playlist_id', 'track_id', name='uq_playlist_track'),
        Index('ix_playlist_tracks_playlist_pos', 'playlist_id', 'position'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[int] = mapped_column(
        ForeignKey('playlists.id', ondelete='CASCADE'), nullable=False,
    )
    track_id: Mapped[int] = mapped_column(
        ForeignKey('tracks.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    playlist: Mapped['Playlist'] = relationship(back_populates='tracks')
    track: Mapped['Track'] = relationship(lazy='joined')


class Artist(Base):
    '''歌手在某个民族下的聚合条目(同一歌手可在多个民族各有一条)'''

    __tablename__ = 'artists'
    __table_args__ = (UniqueConstraint('name', 'group_name', name='uq_artist_group'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default='', nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(64), default='', nullable=False, index=True)
    cover: Mapped[str] = mapped_column(Text, default='', nullable=False)
    song_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UiState(Base):
    '''前端状态持久化: 收藏/黑名单/播放记录等, 按 key 存 JSON'''

    __tablename__ = 'ui_state'

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONText(default={}), default=dict, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MetaEntry(Base):
    '''库级元数据: 索引签名 / 迁移版本 / 统计快照'''

    __tablename__ = 'meta'

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONText(default={}), default=dict, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
