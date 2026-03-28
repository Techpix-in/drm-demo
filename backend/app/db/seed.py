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
    {
        "id": "user-003",
        "email": "tester1@example.com",
        "name": "Tester One",
        "password": "test123",
        "role": "viewer",
    },
    {
        "id": "user-004",
        "email": "tester2@example.com",
        "name": "Tester Two",
        "password": "test123",
        "role": "viewer",
    },
    {
        "id": "user-005",
        "email": "tester3@example.com",
        "name": "Tester Three",
        "password": "test123",
        "role": "viewer",
    },
    {
        "id": "user-006",
        "email": "tester4@example.com",
        "name": "Tester Four",
        "password": "test123",
        "role": "viewer",
    },
    {
        "id": "user-007",
        "email": "tester5@example.com",
        "name": "Tester Five",
        "password": "test123",
        "role": "viewer",
    },
]


async def seed_database():
    async with async_session() as session:
        added = 0
        for u in SEED_USERS:
            existing = await session.execute(
                select(UserDB).where(UserDB.email == u["email"])
            )
            if not existing.scalar_one_or_none():
                user = UserDB(
                    id=u["id"],
                    email=u["email"],
                    name=u["name"],
                    password_hash=bcrypt.hash(u["password"]),
                    role=u["role"],
                )
                session.add(user)
                added += 1
        if added:
            await session.commit()
            print(f"Seeded {added} new users")
        else:
            print("All users already exist, skipping seed")

    # Sync videos from VdoCipher
    try:
        from app.services.videos import sync_videos_from_vdocipher
        result = await sync_videos_from_vdocipher()
        print(f"Synced videos from VdoCipher: {result['added']} added, {result['updated']} updated, {result['total_from_vdocipher']} total")
    except Exception as e:
        print(f"VdoCipher video sync failed (will use existing videos): {e}")
