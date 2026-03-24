from passlib.hash import bcrypt
from sqlalchemy import select

from app.db.postgres import async_session, UserDB


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

    # Sync videos from VdoCipher
    try:
        from app.services.videos import sync_videos_from_vdocipher
        result = await sync_videos_from_vdocipher()
        print(f"Synced videos from VdoCipher: {result['added']} added, {result['updated']} updated, {result['total_from_vdocipher']} total")
    except Exception as e:
        print(f"VdoCipher video sync failed (will use existing videos): {e}")
