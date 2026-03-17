# Frontend Service — SecureStream UI (Next.js)

## Overview

This is the Next.js frontend for the DRM-protected video streaming platform. It communicates with the FastAPI backend for authentication, video catalog, and DRM playback. All video playback uses VdoCipher's iframe embed with server-generated OTP tokens.

## How to Run

```bash
npm run dev
# Opens at http://localhost:3000
```

Requires the FastAPI backend running on port 8000.

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
        │   → POST /api/video/otp (with Bearer token + device fingerprint)
        │   ← otp + playbackInfo + session_id
        │   → Renders: <iframe src="player.vdocipher.com/v2/?otp=...&playbackInfo=...">
        │
        ├── Heartbeat (setInterval every 30s)
        │   → POST /api/playback/heartbeat {session_id}
        │
        └── On unmount:
            → DELETE /api/playback/session/{session_id}
```

## File-by-File Explanation

### `src/lib/api.ts` — API Client

The central API client that all components use to communicate with the FastAPI backend.

**Security features built into every request:**

1. **Device Fingerprint Header**: Every request includes `X-Device-Fingerprint` — a hash computed from browser properties (User-Agent, screen size, color depth, timezone, language, CPU cores). This binds sessions to the physical device.

2. **Automatic Token Refresh**: When any API call returns 401 (expired token), the client automatically attempts to exchange the refresh token for a new session token (`POST /api/auth/refresh`). If that fails, the user is logged out. This happens transparently — the original request is retried with the new token.

3. **Refresh Token Deduplication**: If multiple API calls fail with 401 simultaneously, only one refresh request is sent (using a shared Promise). This prevents race conditions.

**Key methods:**
- `login(email, password)` — Authenticates and stores both session + refresh tokens
- `logout()` — Calls backend logout (revokes token server-side) then clears local storage
- `getOTP(videoId)` — Returns `{otp, playback_info, session_id}` for video playback
- `sendHeartbeat(sessionId)` — Keeps a playback session alive
- `endSession(sessionId)` — Explicitly ends a playback session

**`getDeviceFingerprint()` function:**
Generates a fingerprint from: `navigator.userAgent | screen.width | screen.height | screen.colorDepth | timezone | navigator.language | navigator.hardwareConcurrency`. These values are hashed into a compact string. In production, consider using FingerprintJS for higher accuracy.

---

### `src/components/AuthProvider.tsx` — Auth Context

React context provider that manages authentication state app-wide.

**What it does:**
- On mount: checks if a session token exists in localStorage. If yes, validates it by calling `GET /api/auth/me`. If the token is invalid/expired, clears it.
- Provides `user`, `loading`, `login()`, and `logout()` to all child components via React context.
- `logout()` calls the backend to revoke the token server-side (not just local cleanup).

---

### `src/components/LoginForm.tsx` — Login Page

A form component shown when the user is not authenticated.

**What it does:**
- Collects email and password
- Calls `api.login()` which sends credentials with a device fingerprint
- On success, the AuthProvider updates the user state and the app navigates to the catalog
- Shows demo credentials (viewer@example.com / demo123) for testing

---

### `src/components/VdoPlayer.tsx` — DRM Video Player

The core component that handles secure video playback.

**Lifecycle:**

1. **Mount**: Calls `api.getOTP(videoId)` which triggers the backend's full security pipeline (rate limit → anomaly detection → concurrent check → VdoCipher OTP generation)

2. **Playback**: Renders a VdoCipher iframe with the received OTP. The iframe handles all DRM negotiation (Widevine for Chrome/Firefox/Edge, FairPlay for Safari) internally. The video stream contains the forensic watermark with the viewer's identity.

3. **Heartbeat**: Starts a `setInterval` that sends `POST /api/playback/heartbeat` every 30 seconds with the `session_id`. This keeps the playback session alive on the backend. If the heartbeat fails (session expired), the interval is cleared.

4. **Unmount**: Clears the heartbeat interval and calls `api.endSession(sessionId)` to free up the concurrent stream slot. This happens when:
   - User navigates away from the watch page
   - User closes the tab
   - Component is re-rendered with a different videoId

**Why heartbeats matter:** Without heartbeats, a user who closes their tab would keep a "phantom session" alive for up to 90 seconds, blocking them from watching on another device. The heartbeat + unmount cleanup ensures slots are freed promptly.

---

### `src/components/VideoCard.tsx` — Video Thumbnail Card

Simple presentational component that renders a video card in the catalog grid. Shows title, description, duration, and "DRM Protected" / "Watermarked" badges. Links to `/watch/{videoId}`.

---

### `src/components/Header.tsx` — Navigation Bar

Shows the SecureStream logo, "Powered by VdoCipher DRM" label, user name, and logout button. Uses the auth context to show/hide user-specific elements.

---

### `src/app/page.tsx` — Landing / Catalog Page

**When not logged in:** Shows the LoginForm component.

**When logged in:** Fetches the video catalog from `GET /api/videos` and displays a grid of VideoCard components. Also shows a "Security Active" banner listing all 4 protection layers visible to the user (DRM, Watermarking, Session Tokens, Browser L3 limit).

---

### `src/app/watch/[videoId]/page.tsx` — Watch Page

Dynamic route that loads a video for playback.

**What it does:**
1. Extracts `videoId` from the URL params
2. If not logged in, shows LoginForm
3. Fetches video metadata from the catalog
4. Renders the VdoPlayer component with the videoId
5. Shows video info and a "Content Protection Details" panel explaining the DRM, watermark, token TTL, and browser resolution limit

---

### `src/app/layout.tsx` — Root Layout

Wraps the entire app in the AuthProvider context. Sets up the dark theme (bg-gray-950), Header, and metadata.

---

### `src/app/globals.css` — Styles

Just imports Tailwind CSS. All styling uses Tailwind utility classes.

---

## Security Flow (Frontend Perspective)

```
1. User opens app
2. No token → Show login form
3. User logs in → Backend returns session_token + refresh_token
   Both stored in localStorage
   Device fingerprint sent with login request

4. User browses catalog → GET /api/videos
   Authorization: Bearer {session_token}
   X-Device-Fingerprint: {hash}

5. User clicks video → Navigate to /watch/{videoId}
   VdoPlayer mounts → POST /api/video/otp
   Backend runs 7 security checks → Returns OTP + session_id
   Player renders VdoCipher iframe with OTP

6. Every 30s → POST /api/playback/heartbeat {session_id}

7. User navigates away → VdoPlayer unmounts
   → DELETE /api/playback/session/{session_id}
   → Heartbeat interval cleared

8. Session token expires (1h) → Next API call returns 401
   → Auto-refresh: POST /api/auth/refresh with refresh_token
   → New session_token received, original request retried

9. User logs out → POST /api/auth/logout
   → Token revoked server-side
   → All playback sessions ended
   → localStorage cleared
```

## Environment Variables

Create `.env.local` in the project root:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```
