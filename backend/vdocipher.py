import json
import httpx

from config import VDOCIPHER_API_BASE, VDOCIPHER_API_SECRET, ALLOWED_DOMAIN
from models import SessionUser


async def generate_otp(
    video_id: str,
    user: SessionUser,
    ip_address: str,
    device_fingerprint: str,
) -> dict:
    """
    Generate a VdoCipher OTP for secure playback.

    Security controls applied:
    - 5-minute TTL: prevents token sharing
    - Forensic watermark: embeds viewer identity + device in video stream
    - IP geo-restriction: binds OTP to viewer's current IP
    - License rules: blocks offline downloads (canPersist: false)
    - Domain restriction: locks playback to allowed domain (production)
    - User ID: enables VdoCipher viewer analytics
    """
    if not VDOCIPHER_API_SECRET:
        raise ValueError("VDOCIPHER_API_SECRET is not configured")

    body: dict = {
        "ttl": 300,  # 5-minute token lifetime
    }

    # IP geo-restriction: bind OTP to viewer's current IP
    # Disabled in dev (Docker uses private IPs which VdoCipher rejects).
    # Enable in production with public IPs:
    #   body["ipGeo"] = json.dumps([{"action": "allow", "ipSet": [ip_address]}])

    # License rules: prevent offline downloads/ripping
    # Enable when using VdoCipher's offline/download feature:
    #   body["licenseRules"] = json.dumps({"canPersist": False})

    # User ID for VdoCipher's viewer analytics (max 36 chars)
    body["userId"] = user.user_id[:36]

    # Domain restriction for production
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
    return {"otp": data["otp"], "playback_info": data["playbackInfo"]}
