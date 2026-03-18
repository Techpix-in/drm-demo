from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import FRONTEND_URLS
from app.db.postgres import init_db
from app.db.redis import init_redis, close_redis
from app.db.seed import seed_database
from app.api import auth, videos, playback, health

app = FastAPI(title="SecureStream API", version="3.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_URLS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# Register routers
app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(playback.router)
app.include_router(health.router)


@app.on_event("startup")
async def startup():
    await init_redis()
    await init_db()
    await seed_database()


@app.on_event("shutdown")
async def shutdown():
    await close_redis()
