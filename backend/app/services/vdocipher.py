import json
import time
import httpx

from app.config import (
    VDOCIPHER_API_BASE,
    VDOCIPHER_API_SECRET,
    ALLOWED_DOMAIN,
    OTP_TTL_BROWSER,
    OTP_TTL_MOBILE,
)
from app.models.schemas import SessionUser


TIER_CONFIG = {
    "browser": {"ttl": OTP_TTL_BROWSER, "max_resolution": "480p", "watermark": True},
    "mobile_app": {"ttl": OTP_TTL_MOBILE, "max_resolution": "1080p", "watermark": True},
    "smart_tv": {"ttl": OTP_TTL_MOBILE, "max_resolution": "4k", "watermark": True},
}


def _build_dynamic_watermark(user: SessionUser, device_fingerprint: str) -> dict:
    ts = int(time.time())
    return {
        "type": "rtext",
        "text": f"{user.user_id}|{ts}|{device_fingerprint[:6]}",
        "alpha": "0.10",
        "color": "0xFFFFFF",
        "size": "12",
        "interval": "3000",
    }


async def fetch_all_videos_from_vdocipher() -> list[dict]:
    """Fetch all videos from VdoCipher account via their API."""
    if not VDOCIPHER_API_SECRET:
        raise ValueError("VDOCIPHER_API_SECRET is not configured")

    all_videos = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            response = await client.get(
                f"{VDOCIPHER_API_BASE}/videos",
                headers={
                    "Authorization": f"Apisecret {VDOCIPHER_API_SECRET}",
                    "Accept": "application/json",
                },
                params={"page": page, "limit": 20},
            )

            if response.status_code != 200:
                raise Exception(
                    f"VdoCipher video list failed: {response.status_code} - {response.text}"
                )

            data = response.json()
            rows = data.get("rows", data) if isinstance(data, dict) else data

            if not rows:
                break

            for v in rows:
                # VdoCipher returns: id, title, description, length (seconds), status, poster
                vid_id = v.get("id", "")
                status = v.get("status", "")
                if not vid_id or status not in ("ready", "Ready"):
                    continue

                length_sec = v.get("length", 0) or 0
                mins = int(length_sec) // 60
                secs = int(length_sec) % 60
                duration = f"{mins}:{secs:02d}" if length_sec else ""

                all_videos.append({
                    "id": vid_id,
                    "title": v.get("title", "Untitled"),
                    "description": v.get("description", ""),
                    "thumbnail": v.get("poster", ""),
                    "duration": duration,
                })

            # Check if there are more pages
            count = data.get("count", 0) if isinstance(data, dict) else 0
            if len(all_videos) >= count or not rows:
                break
            page += 1

    return all_videos


async def generate_otp(
    video_id: str,
    user: SessionUser,
    ip_address: str,
    device_fingerprint: str,
    client_tier: str = "browser",
) -> dict:
    if not VDOCIPHER_API_SECRET:
        raise ValueError("VDOCIPHER_API_SECRET is not configured")

    tier = TIER_CONFIG.get(client_tier, TIER_CONFIG["browser"])

    body: dict = {"ttl": tier["ttl"]}

    if tier["watermark"]:
        watermark = _build_dynamic_watermark(user, device_fingerprint)
        body["annotate"] = json.dumps([watermark])

    body["userId"] = user.user_id[:36]

    if ALLOWED_DOMAIN:
        body["whitelisthref"] = ALLOWED_DOMAIN

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VDOCIPHER_API_BASE}/videos/{video_id}/otp",
            headers={
                "Authorization": f"Apisecret {VDOCIPHER_API_SECRET}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )

    if response.status_code != 200:
        raise Exception(
            f"VdoCipher OTP generation failed: {response.status_code} - {response.text}"
        )

    data = response.json()
    return {
        "otp": data["otp"],
        "playback_info": data["playbackInfo"],
        "tier": client_tier,
        "max_resolution": tier["max_resolution"],
    }
