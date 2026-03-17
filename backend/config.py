import os
from dotenv import load_dotenv

load_dotenv()

VDOCIPHER_API_SECRET = os.getenv("VDOCIPHER_API_SECRET", "")
VDOCIPHER_API_BASE = "https://dev.vdocipher.com/api"
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
# Comma-separated list of allowed frontend origins
FRONTEND_URLS = [
    u.strip() for u in os.getenv("FRONTEND_URL", "http://localhost:3000").split(",") if u.strip()
]
ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "")

# ─── Anti-Piracy Settings ────────────────────────────────────────────────

# Session & token TTLs
MAX_CONCURRENT_STREAMS = int(os.getenv("MAX_CONCURRENT_STREAMS", "2"))
SESSION_TOKEN_TTL = int(os.getenv("SESSION_TOKEN_TTL", "3600"))       # 1 hour
REFRESH_TOKEN_TTL = int(os.getenv("REFRESH_TOKEN_TTL", "604800"))     # 7 days
HEARTBEAT_INTERVAL = 30       # seconds — frontend pings this often
SESSION_EXPIRY = 90           # seconds without heartbeat = dead session

# Rate limiting
LOGIN_RATE_LIMIT = 5          # attempts per window
LOGIN_RATE_WINDOW = 900       # 15 minutes
OTP_RATE_LIMIT = 10           # requests per window
OTP_RATE_WINDOW = 60          # 1 minute

# Anomaly detection
MAX_FINGERPRINTS_PER_USER = 5         # unique fingerprints before flagging
IMPOSSIBLE_TRAVEL_WINDOW = 300        # 5 minutes — different IP in this window is suspicious
RISK_SCORE_THRESHOLD = 100            # block at this cumulative score
RISK_SCORE_DECAY_SECONDS = 3600       # risk points decay after 1 hour
