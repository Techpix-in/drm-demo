from passlib.hash import bcrypt
from sqlalchemy import select

from app.db.postgres import async_session, UserDB, VideoDB


SEED_USERS = [
    {
        "id": "user-001",
        "email": "viewer@example.com",
        "name": "Demo Viewer",
        "password": "demo123",
        "role": "viewer",
    },
    {
        "id": "user-002",
        "email": "admin@example.com",
        "name": "Admin User",
        "password": "admin123",
        "role": "admin",
    },
]

SEED_VIDEOS = [
    {
        "id": "bd3ca7a235663ed1570e305f3775414a",
        "title": "Premium Content - Episode 1",
        "description": "DRM-protected premium content with forensic watermarking enabled.",
        "thumbnail": "/thumbnails/video1.jpg",
        "duration": "24:30",
    },
]


async def seed_database():
    async with async_session() as session:
        existing = await session.execute(select(UserDB).limit(1))
        if not existing.scalar_one_or_none():
            for u in SEED_USERS:
                user = UserDB(
                    id=u["id"],
                    email=u["email"],
                    name=u["name"],
                    password_hash=bcrypt.hash(u["password"]),
                    role=u["role"],
                )
                session.add(user)
            await session.commit()
            print(f"Seeded {len(SEED_USERS)} users")
        else:
            print("Users already exist, skipping seed")

        existing = await session.execute(select(VideoDB).limit(1))
        if not existing.scalar_one_or_none():
            for v in SEED_VIDEOS:
                video = VideoDB(**v)
                session.add(video)
            await session.commit()
            print(f"Seeded {len(SEED_VIDEOS)} videos")
        else:
            print("Videos already exist, skipping seed")
