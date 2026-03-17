from typing import List, Optional
from models import Video

# Video catalog - replace IDs with your VdoCipher video IDs
VIDEOS: List[Video] = [
    Video(
        id="bd3ca7a235663ed1570e305f3775414a",
        title="Premium Content - Episode 1",
        description="DRM-protected premium content with forensic watermarking enabled.",
        thumbnail="/thumbnails/video1.jpg",
        duration="24:30",
    ),
]


def get_video_by_id(video_id: str) -> Optional[Video]:
    for video in VIDEOS:
        if video.id == video_id:
            return video
    return None
