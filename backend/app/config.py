import os
from dotenv import load_dotenv

load_dotenv()

VDOCIPHER_API_SECRET = os.getenv("VDOCIPHER_API_SECRET", "")
VDOCIPHER_API_BASE = "https://dev.vdocipher.com/api"
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
FRONTEND_URLS = [
    u.strip() for u in os.getenv("FRONTEND_URL", "http://localhost:3000").split(",") if u.strip()
]
ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "")

# ─── Database ────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://securestream:securestream_dev@postgres:5432/securestream",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# ─── Anti-Piracy Settings ────────────────────────────────────────────────

MAX_CONCURRENT_STREAMS = int(os.getenv("MAX_CONCURRENT_STREAMS", "2"))
SESSION_TOKEN_TTL = int(os.getenv("SESSION_TOKEN_TTL", "3600"))
REFRESH_TOKEN_TTL = int(os.getenv("REFRESH_TOKEN_TTL", "604800"))
HEARTBEAT_INTERVAL = 30
SESSION_EXPIRY = 90

# OTP TTL per tier
OTP_TTL_BROWSER = int(os.getenv("OTP_TTL_BROWSER", "120"))
OTP_TTL_MOBILE = int(os.getenv("OTP_TTL_MOBILE", "300"))

# OTP rotation — frontend requests a fresh OTP before the current one expires
OTP_ROTATION_INTERVAL_BROWSER = 90   # rotate every 90s (before 120s expiry)
OTP_ROTATION_INTERVAL_MOBILE = 240   # rotate every 240s (before 300s expiry)

# Rate limiting
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 900
OTP_RATE_LIMIT = 10
OTP_RATE_WINDOW = 60
LICENSE_RATE_LIMIT = 20
LICENSE_RATE_WINDOW = 60

# Anomaly detection
MAX_FINGERPRINTS_PER_USER = 5
IMPOSSIBLE_TRAVEL_WINDOW = 300
RISK_SCORE_THRESHOLD = 100
RISK_SCORE_DECAY_SECONDS = 3600

# Behavioral detection — thresholds tuned to avoid false positives
MAX_SEEKS_PER_MINUTE = 30
MAX_RESTARTS_PER_HOUR = 15
MAX_CONTINUOUS_PLAY_HOURS = 10
BEHAVIORAL_RISK_POINTS = 25

# Server-side signal detection — these don't rely on frontend reporting
MAX_OTP_ROTATIONS_PER_SESSION = 50     # Normal 2hr movie = ~80 rotations, but 50 in quick succession = suspicious
GHOST_SESSION_THRESHOLD = 3            # Sessions created with 0 heartbeats
RAPID_SESSION_CREATION_LIMIT = 5       # Max new sessions in 10 minutes
RAPID_SESSION_CREATION_WINDOW = 600    # 10 minutes
HEARTBEAT_GAP_TOLERANCE = 3            # Max missed heartbeats (90s gap) before flagging
MIN_PLAY_RATIO = 0.3                   # play_seconds / elapsed_seconds — below 30% = suspicious
