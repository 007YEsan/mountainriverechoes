'''
Function:
    歌手仓储 —— 索引页「民族」Tab 依赖的歌手聚合结果。
'''
from __future__ import annotations

from sqlalchemy import Engine, desc, select
from sqlalchemy.orm import Session

from app.models import Artist


class ArtistRepository:
    def __init__(self, session: Session, engine: Engine) -> None:
        self.session = session
        self.engine = engine

    def list_for_index(self, *, limit: int | None = None) -> list[dict]:
        stmt = select(Artist).order_by(desc(Artist.song_count), Artist.name)
        if limit:
            stmt = stmt.limit(limit)
        return [
            {'name': a.name, 'group': a.group_name, 'count': a.song_count,
             'cover': a.cover, 'confirmed': a.confirmed}
            for a in self.session.execute(stmt).scalars().all()
        ]

    def count_distinct(self) -> int:
        from sqlalchemy import func
        return int(self.session.execute(
            select(func.count(func.distinct(Artist.name)))
        ).scalar_one())
