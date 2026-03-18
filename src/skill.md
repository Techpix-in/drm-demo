# Frontend Service — SecureStream UI (Next.js)

## Overview

Next.js frontend for the DRM-protected video streaming platform. Communicates with the FastAPI backend for authentication, video catalog, and DRM playback. All video playback uses VdoCipher's iframe embed with server-generated OTP tokens. Sends behavioral telemetry (seeks, restarts, play duration) with each heartbeat for server-side piracy detection.

## How to Run

```bash
# Start everything (backend + frontend)
./start.sh

# Or frontend only (requires backend on port 8000)
npm run dev
# Opens at http://localhost:3000
```

## Architecture

```
Browser
    │
    ├── Login Page (/LoginForm)
    │   → POST /api/auth/login
    │   ← session_token + refresh_token (stored in localStorage)
    │
    ├── Catalog Page (/)
    │   → GET /api/videos (with Bearer token + device fingerprint)
    │   ← list of videos
    │
    └── Watch Page (/watch/[videoId])
        │
        ├── VdoPlayer component
        │   → POST /api/video/otp {video_id, client_tier: "browser"}
        │   ← otp + playbackInfo + session_id + tier + max_resolution
        │   → Renders: <iframe src="player.vdocipher.com/v2/?otp=...&playbackInfo=...">
        │   → Shows tier badge: "Browser · Max 480p"
        │
        ├── Heartbeat (setInterval every 30s)
        │   → POST /api/playback/heartbeat {session_id, playback_events}
        │   ← {status, expires_in, risk_level}
        │   → If risk_level == "blocked": show error, stop playback
        │
        └── On unmount:
            → DELETE /api/playback/session/{session_id}
```

## File-by-File Explanation

### `src/lib/api.ts` — API Client

Central API client for all backend communication.

**Security features built into every request:**

1. **Device Fingerprint Header**: Every request includes `X-Device-Fingerprint` — a hash from browser properties (User-Agent, screen size, color depth, timezone, language, CPU cores). Binds sessions to the physical device.

2. **Automatic Token Refresh**: On 401 responses, automatically exchanges refresh token for a new session token. Original request retried transparently.

3. **Refresh Token Deduplication**: Multiple simultaneous 401s trigger only one refresh request (shared Promise).

4. **Tier Declaration**: `getOTP()` sends `client_tier: "browser"` — backend uses this for resolution capping and OTP TTL.

5. **Behavioral Events**: `sendHeartbeat()` sends `playback_events` (seek_count, restart_count, play_seconds) for server-side behavioral analysis.

**Key methods:**
- `login(email, password)` — Authenticates, stores session + refresh tokens
- `logout()` — Revokes token server-side, clears localStorage
- `getOTP(videoId)` — Returns `{otp, playback_info, session_id, tier, max_resolution}`
- `sendHeartbeat(sessionId, playbackEvents)` — Keeps session alive, sends behavioral data, returns `risk_level`
- `endSession(sessionId)` — Ends playback session

---

### `src/components/VdoPlayer.tsx` — DRM Video Player

Core component for secure video playback with behavioral tracking.

**Lifecycle:**

1. **Mount**: Calls `api.getOTP(videoId)` → triggers backend security pipeline → receives OTP + tier info

2. **Playback**: Renders VdoCipher iframe. Shows tier badge ("Browser · Max 480p"). The iframe handles Widevine/FairPlay DRM internally.

3. **Behavioral Tracking**: Listens to `message` events from the VdoCipher iframe to count seek events. Tracks restart count and play duration locally.

4. **Heartbeat (every 30s)**: Sends `{session_id, playback_events: {seek_count, restart_count, play_seconds}}`. Resets counters after sending. If server returns `risk_level: "blocked"`, shows error and stops playback.

5. **Unmount**: Clears heartbeat interval, calls `api.endSession()` to free concurrent stream slot.

**Behavioral events tracked:**
- `seek_count` — Number of seek events since last heartbeat (from iframe messages)
- `restart_count` — Number of video restarts
- `play_seconds` — Elapsed seconds since last heartbeat

---

### `src/components/AuthProvider.tsx` — Auth Context

React context managing authentication state app-wide.

- On mount: validates existing token via `GET /api/auth/me`
- Provides `user`, `loading`, `login()`, `logout()` to all components
- `logout()` revokes token server-side + clears localStorage

---

### `src/components/LoginForm.tsx` — Login Page

- Collects email/password, calls `api.login()` with device fingerprint
- Shows demo credentials for testing

---

### `src/components/VideoCard.tsx` — Video Thumbnail Card

Presentational component. Shows title, description, duration, protection badges. Links to `/watch/{videoId}`.

---

### `src/components/Header.tsx` — Navigation Bar

Shows logo, "Powered by VdoCipher DRM" label, user name, logout button.

---

### `src/app/page.tsx` — Catalog Page

- **Not logged in**: Shows LoginForm
- **Logged in**: Fetches video catalog, displays VideoCard grid, shows "Security Active" banner

---

### `src/app/watch/[videoId]/page.tsx` — Watch Page

- Extracts videoId from URL, loads VdoPlayer component
- Shows video info and content protection details panel

---

### `src/app/layout.tsx` — Root Layout

Wraps app in AuthProvider, sets dark theme, renders Header.

---

## Security Flow (Frontend Perspective)

```
1. User opens app
2. No token → Show login form
3. Login → Backend authenticates against Postgres
   Returns session_token + refresh_token
   Both stored in localStorage
   Device fingerprint sent with request

4. Browse catalog → GET /api/videos
   Authorization: Bearer {session_token}
   X-Device-Fingerprint: {hash}

5. Click video → Navigate to /watch/{videoId}
   VdoPlayer mounts → POST /api/video/otp {video_id, client_tier: "browser"}
   Backend runs security pipeline → Returns OTP + session_id + tier + max_resolution
   Player renders VdoCipher iframe with OTP
   Shows tier badge: "Browser · Max 480p"

6. Every 30s → POST /api/playback/heartbeat
   Sends: {session_id, playback_events: {seek_count, restart_count, play_seconds}}
   Backend validates IP binding + analyzes behavior
   Returns: {status, risk_level}
   If risk_level == "blocked" → show error, stop playback

7. User navigates away → VdoPlayer unmounts
   → DELETE /api/playback/session/{session_id}
   → Heartbeat interval cleared

8. Token expires (1h) → Auto-refresh with refresh_token
   → New session_token, original request retried

9. Logout → POST /api/auth/logout
   → Token revoked in Redis
   → All playback sessions ended
   → localStorage cleared
```

## Environment Variables

Create `.env.local` in the project root:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

For Vercel deployment, set `NEXT_PUBLIC_API_URL` to the Cloudflare tunnel URL of the backend.
