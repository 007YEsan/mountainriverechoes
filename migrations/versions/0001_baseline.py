'''baseline schema —— 7 张业务表 + 索引/唯一约束 + FTS5 全文索引

基线说明:
  这是把运行时 app.database.create_schema() 的建表结果固化的第一个版本。
  内容由 `alembic revision --autogenerate` 对空库生成后人工校正, 与
  Base.metadata.create_all() 的产物逐条对齐(7 张表 / 13 个索引 / 2 个具名唯一约束)。

关于 SQLite 批处理模式(batch mode):
  本迁移只做 CREATE TABLE / DROP TABLE / CREATE INDEX 这类"整表"DDL, 不涉及
  ALTER TABLE, 因此**不启用** render_as_batch, 也不使用 `with op.batch_alter_table()`。
  批处理模式只有在需要"新建影子表 → 拷数据 → 换名"(即 ALTER 语义)时才有必要;
  若在这里启用, 它会把 op.execute() 里手写的 CREATE VIRTUAL TABLE / CREATE TRIGGER
  一起裹进它的重建流程, 反而破坏外部内容表(content='tracks')与 tracks 的绑定关系。

关于 FTS5:
  tracks_fts 是 SQLite 虚拟表, 三个 _ai/_ad/_au 触发器负责与 tracks 同步 ——
  这些对象不在 SQLAlchemy 元数据里, 只能 op.execute() 手写。SQL 与
  app/database.py::ensure_fts() 保持一字不差(包括 trigram/unicode61 的分词器选择),
  保证迁移建出来的索引和运行时建出来的是同一个东西。

Revision ID: 0001_baseline
Revises: None
'''
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.base import JSONText

revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FTS_TABLE = 'tracks_fts'
# trigram 要求 SQLite >= 3.34; 与 app/database.py 中的判定阈值一致
_MIN_TRIGRAM = (3, 34, 0)


def _fts_tokenizer() -> str:
    '''与 app/database.py::sqlite_supports_trigram() 同判据决定分词器'''
    bind = op.get_bind()
    ver = bind.exec_driver_sql('select sqlite_version()').scalar() or ''
    parts = tuple(int(x) for x in str(ver).split('.')[:3] if x.isdigit())
    return 'trigram' if len(parts) == 3 and parts >= _MIN_TRIGRAM else 'unicode61'


def _fts_object_exists(kind: str, name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text('select 1 from sqlite_master where type=:t and name=:n'), {'t': kind, 'n': name},
    ).first()
    return row is not None


def _create_fts() -> None:
    tokenizer = _fts_tokenizer()
    if not _fts_object_exists('table', FTS_TABLE):
        op.execute(
            f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5("
            f"song_name, singers, album, content='tracks', content_rowid='id', "
            f"tokenize='{tokenizer}')"
        )
    for tname, sql in (
        (f'{FTS_TABLE}_ai',
         f"CREATE TRIGGER {FTS_TABLE}_ai AFTER INSERT ON tracks BEGIN "
         f"INSERT INTO {FTS_TABLE}(rowid, song_name, singers, album) "
         f"VALUES (new.id, new.song_name, new.singers, new.album); END"),
        (f'{FTS_TABLE}_ad',
         f"CREATE TRIGGER {FTS_TABLE}_ad AFTER DELETE ON tracks BEGIN "
         f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, song_name, singers, album) "
         f"VALUES ('delete', old.id, old.song_name, old.singers, old.album); END"),
        (f'{FTS_TABLE}_au',
         f"CREATE TRIGGER {FTS_TABLE}_au AFTER UPDATE ON tracks BEGIN "
         f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, song_name, singers, album) "
         f"VALUES ('delete', old.id, old.song_name, old.singers, old.album); "
         f"INSERT INTO {FTS_TABLE}(rowid, song_name, singers, album) "
         f"VALUES (new.id, new.song_name, new.singers, new.album); END"),
    ):
        if not _fts_object_exists('trigger', tname):
            op.execute(sql)


def _drop_fts() -> None:
    # 触发器随 tracks 表级联消失, 但显式先删可保证顺序确定;
    # tracks_fts 是外部内容表, 必须在 tracks 之前删, 否则会留下悬空虚表。
    for tname in (f'{FTS_TABLE}_ai', f'{FTS_TABLE}_au', f'{FTS_TABLE}_ad'):
        if _fts_object_exists('trigger', tname):
            op.execute(f'DROP TRIGGER {tname}')
    if _fts_object_exists('table', FTS_TABLE):
        op.execute(f'DROP TABLE {FTS_TABLE}')


def upgrade() -> None:
    op.create_table(
        'artists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_name', sa.String(length=64), nullable=False),
        sa.Column('cover', sa.Text(), nullable=False),
        sa.Column('song_count', sa.Integer(), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'group_name', name='uq_artist_group'),
    )
    op.create_index(op.f('ix_artists_group_name'), 'artists', ['group_name'], unique=False)
    op.create_index(op.f('ix_artists_name'), 'artists', ['name'], unique=False)

    op.create_table(
        'meta',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', JSONText(), nullable=False),
        sa.Column('updated_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table(
        'playlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=48), nullable=False),
        sa.Column('platform', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_name', sa.String(length=64), nullable=False),
        sa.Column('cover', sa.Text(), nullable=False),
        sa.Column('track_count', sa.Integer(), nullable=False),
        sa.Column('built_at', sa.String(length=32), nullable=False),
        sa.Column('partial', sa.Boolean(), nullable=False),
        sa.Column('schema_v', sa.Integer(), nullable=False),
        sa.Column('kws', JSONText(), nullable=False),
        sa.Column('curation', JSONText(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # playlists.key 的 unique=True 在无 naming_convention 时被 SQLAlchemy 渲染成唯一索引
    op.create_index(op.f('ix_playlists_key'), 'playlists', ['key'], unique=True)
    op.create_index(op.f('ix_playlists_group_name'), 'playlists', ['group_name'], unique=False)

    op.create_table(
        'tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dedup_key', sa.String(length=512), nullable=False),
        sa.Column('dedup_core', sa.String(length=512), nullable=False),
        sa.Column('song_name', sa.String(length=512), nullable=False),
        sa.Column('core_name', sa.String(length=512), nullable=False),
        sa.Column('norm_name', sa.String(length=512), nullable=False),
        sa.Column('norm_singers', sa.String(length=512), nullable=False),
        sa.Column('norm_album', sa.String(length=512), nullable=False),
        sa.Column('singers', sa.String(length=512), nullable=False),
        sa.Column('album', sa.String(length=512), nullable=False),
        sa.Column('ext', sa.String(length=16), nullable=False),
        sa.Column('file_size', sa.String(length=32), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False),
        sa.Column('bitrate', sa.String(length=32), nullable=False),
        sa.Column('duration', sa.String(length=32), nullable=False),
        sa.Column('duration_s', sa.Integer(), nullable=False),
        sa.Column('cover_url', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('source_cn', sa.String(length=32), nullable=False),
        sa.Column('source_client', sa.String(length=64), nullable=False),
        sa.Column('identifier', sa.String(length=128), nullable=False),
        sa.Column('download_url', sa.Text(), nullable=False),
        sa.Column('netease_id', sa.String(length=64), nullable=False),
        sa.Column('voice_id', sa.String(length=64), nullable=False),
        sa.Column('article_url', sa.Text(), nullable=False),
        sa.Column('previewable', sa.Boolean(), nullable=False),
        sa.Column('downloadable', sa.Boolean(), nullable=False),
        sa.Column('has_lyric', sa.Boolean(), nullable=False),
        sa.Column('raw_json', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # tracks.dedup_key 的 unique=True 同样渲染为唯一索引
    op.create_index(op.f('ix_tracks_dedup_key'), 'tracks', ['dedup_key'], unique=True)
    op.create_index(op.f('ix_tracks_core_name'), 'tracks', ['core_name'], unique=False)
    op.create_index(op.f('ix_tracks_dedup_core'), 'tracks', ['dedup_core'], unique=False)
    op.create_index(op.f('ix_tracks_downloadable'), 'tracks', ['downloadable'], unique=False)
    op.create_index(op.f('ix_tracks_identifier'), 'tracks', ['identifier'], unique=False)
    op.create_index(op.f('ix_tracks_norm_name'), 'tracks', ['norm_name'], unique=False)
    op.create_index(op.f('ix_tracks_norm_singers'), 'tracks', ['norm_singers'], unique=False)
    op.create_index(op.f('ix_tracks_previewable'), 'tracks', ['previewable'], unique=False)
    op.create_index(op.f('ix_tracks_source'), 'tracks', ['source'], unique=False)

    op.create_table(
        'ui_state',
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', JSONText(), nullable=False),
        sa.Column('updated_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table(
        'lyrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # lyrics.track_id 的 unique=True 同样渲染为唯一索引
    op.create_index(op.f('ix_lyrics_track_id'), 'lyrics', ['track_id'], unique=True)

    op.create_table(
        'playlist_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('playlist_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('playlist_id', 'track_id', name='uq_playlist_track'),
    )
    # 复合索引名在 entities.py 里显式给定, 不走 op.f() 的命名约定前缀
    op.create_index(
        'ix_playlist_tracks_playlist_pos', 'playlist_tracks', ['playlist_id', 'position'], unique=False,
    )
    op.create_index(op.f('ix_playlist_tracks_track_id'), 'playlist_tracks', ['track_id'], unique=False)

    # --- SQLite 专有对象: FTS5 虚表 + 同步触发器(元数据里没有, 只能手写) ---
    _create_fts()


def downgrade() -> None:
    # FTS 必须先于 tracks 拆除: 外部内容表与触发器都挂在 tracks 上
    _drop_fts()

    op.drop_index(op.f('ix_playlist_tracks_track_id'), table_name='playlist_tracks')
    op.drop_index('ix_playlist_tracks_playlist_pos', table_name='playlist_tracks')
    op.drop_table('playlist_tracks')

    op.drop_index(op.f('ix_lyrics_track_id'), table_name='lyrics')
    op.drop_table('lyrics')

    op.drop_table('ui_state')

    op.drop_index(op.f('ix_tracks_source'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_previewable'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_norm_singers'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_norm_name'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_identifier'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_downloadable'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_dedup_key'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_dedup_core'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_core_name'), table_name='tracks')
    op.drop_table('tracks')

    op.drop_index(op.f('ix_playlists_key'), table_name='playlists')
    op.drop_index(op.f('ix_playlists_group_name'), table_name='playlists')
    op.drop_table('playlists')

    op.drop_table('meta')

    op.drop_index(op.f('ix_artists_name'), table_name='artists')
    op.drop_index(op.f('ix_artists_group_name'), table_name='artists')
    op.drop_table('artists')
