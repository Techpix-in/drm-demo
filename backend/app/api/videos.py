from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import SessionUser
from app.core.auth import get_current_user
from app.services.videos import get_all_videos, get_video_by_id

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("")
async def list_videos(user: SessionUser = Depends(get_current_user)):
    videos = await get_all_videos()
    return {"videos": [v.model_dump() for v in videos]}


@router.get("/{video_id}")
async def get_video(video_id: str, user: SessionUser = Depends(get_current_user)):
    video = await get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video.model_dump()
