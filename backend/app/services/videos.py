from typing import Optional

from sqlalchemy import select
# Comment
from app.db.postgres import async_session, VideoDB
from app.models.schemas import Video


async def get_all_videos() -> list[Video]:
    async with async_session() as session:
        result = await session.execute(
            select(VideoDB).where(VideoDB.is_active == True).order_by(VideoDB.created_at)
        )
        return [
            Video(
                id=row.id,
                title=row.title,
                description=row.description or "",
                thumbnail=row.thumbnail or "",
                duration=row.duration or "",
            )
            for row in result.scalars().all()
        ]


async def get_video_by_id(video_id: str) -> Optional[Video]:
    async with async_session() as session:
        result = await session.execute(
            select(VideoDB).where(VideoDB.id == video_id, VideoDB.is_active == True)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return Video(
            id=row.id,
            title=row.title,
            description=row.description or "",
            thumbnail=row.thumbnail or "",
            duration=row.duration or "",
        )
