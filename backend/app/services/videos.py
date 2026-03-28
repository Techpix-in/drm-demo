from typing import Optional

from sqlalchemy import select, update
from app.db.postgres import async_session, VideoDB
from app.models.schemas import Video
from app.services.vdocipher import fetch_all_videos_from_vdocipher


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


async def sync_videos_from_vdocipher() -> dict:
    """Fetch all videos from VdoCipher and upsert into Postgres."""
    vdocipher_videos = await fetch_all_videos_from_vdocipher()

    added = 0
    updated = 0

    async with async_session() as session:
        for v in vdocipher_videos:
            result = await session.execute(
                select(VideoDB).where(VideoDB.id == v["id"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.title = v["title"]
                existing.description = v["description"]
                existing.thumbnail = v["thumbnail"]
                existing.duration = v["duration"]
                existing.is_active = True
                updated += 1
            else:
                session.add(VideoDB(
                    id=v["id"],
                    title=v["title"],
                    description=v["description"],
                    thumbnail=v["thumbnail"],
                    duration=v["duration"],
                    is_active=True,
                ))
                added += 1

        # Deactivate videos no longer in VdoCipher
        vdocipher_ids = {v["id"] for v in vdocipher_videos}
        await session.execute(
            update(VideoDB)
            .where(VideoDB.id.notin_(vdocipher_ids), VideoDB.is_active == True)
            .values(is_active=False)
        )

        await session.commit()

    return {
        "total_from_vdocipher": len(vdocipher_videos),
        "added": added,
        "updated": updated,
    }
