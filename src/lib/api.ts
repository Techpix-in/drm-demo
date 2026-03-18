// Use same origin — Next.js rewrites /api/* to the backend server-side
// This avoids mixed-content blocking (HTTPS frontend → HTTP backend)
const API_BASE = "";

/**
 * Generate a simple device fingerprint from browser properties.
 * In production, use a library like FingerprintJS for better accuracy.
 */
function getDeviceFingerprint(): string {
  if (typeof window === "undefined") return "server";
  const raw = [
    navigator.userAgent,
    screen.width,
    screen.height,
    screen.colorDepth,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.language,
    navigator.hardwareConcurrency,
  ].join("|");
  // Simple hash
  let hash = 0;
  for (let i = 0; i < raw.length; i++) {
    const char = raw.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

class ApiClient {
  private token: string | null = null;
  private refreshToken: string | null = null;
  private refreshing: Promise<boolean> | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== "undefined") {
      localStorage.setItem("auth_token", token);
    }
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== "undefined") {
      this.token = localStorage.getItem("auth_token");
    }
    return this.token;
  }

  setRefreshToken(token: string) {
    this.refreshToken = token;
    if (typeof window !== "undefined") {
      localStorage.setItem("refresh_token", token);
    }
  }

  getRefreshToken(): string | null {
    if (this.refreshToken) return this.refreshToken;
    if (typeof window !== "undefined") {
      this.refreshToken = localStorage.getItem("refresh_token");
    }
    return this.refreshToken;
  }

  clearToken() {
    this.token = null;
    this.refreshToken = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem("auth_token");
      localStorage.removeItem("refresh_token");
    }
  }

  private async attemptRefresh(): Promise<boolean> {
    const refresh = this.getRefreshToken();
    if (!refresh) return false;

    try {
      const res = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Device-Fingerprint": getDeviceFingerprint(),
        },
        body: JSON.stringify({ refresh_token: refresh }),
      });

      if (!res.ok) return false;

      const data = await res.json();
      this.setToken(data.token);
      return true;
    } catch {
      return false;
    }
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
    isRetry = false
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Device-Fingerprint": getDeviceFingerprint(),
      ...(options.headers as Record<string, string>),
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    // On 401, try refresh token before giving up
    if (res.status === 401 && !isRetry) {
      if (!this.refreshing) {
        this.refreshing = this.attemptRefresh().finally(() => {
          this.refreshing = null;
        });
      }
      const refreshed = await this.refreshing;
      if (refreshed) {
        return this.request<T>(path, options, true);
      }
      this.clearToken();
      throw new Error("Session expired. Please login again.");
    }

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Request failed: ${res.status}`);
    }

    return res.json();
  }

  async login(email: string, password: string) {
    const data = await this.request<{
      token: string;
      refresh_token: string;
      user: { user_id: string; email: string; name: string };
    }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    this.setToken(data.token);
    this.setRefreshToken(data.refresh_token);
    return data;
  }

  async logout() {
    try {
      await this.request("/api/auth/logout", { method: "POST" });
    } catch {
      // Ignore errors on logout
    }
    this.clearToken();
  }

  async getMe() {
    return this.request<{ user_id: string; email: string; name: string }>(
      "/api/auth/me"
    );
  }

  async getVideos() {
    return this.request<{
      videos: {
        id: string;
        title: string;
        description: string;
        thumbnail: string;
        duration: string;
      }[];
    }>("/api/videos");
  }

  async getOTP(videoId: string) {
    return this.request<{
      otp: string;
      playback_info: string;
      session_id: string;
      tier: string;
      max_resolution: string;
      rotation_interval: number;
    }>("/api/video/otp", {
      method: "POST",
      body: JSON.stringify({ video_id: videoId, client_tier: "browser" }),
    });
  }

  async rotateOTP(sessionId: string, videoId: string) {
    return this.request<{
      otp: string;
      playback_info: string;
      session_id: string;
      tier: string;
      max_resolution: string;
      rotation_interval: number;
    }>("/api/video/otp/rotate", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, video_id: videoId }),
    });
  }

  async sendHeartbeat(
    sessionId: string,
    playbackEvents: Record<string, number> = {}
  ) {
    return this.request<{
      status: string;
      expires_in: number;
      risk_level: string;
    }>("/api/playback/heartbeat", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        playback_events: playbackEvents,
      }),
    });
  }

  async endSession(sessionId: string) {
    return this.request<{ status: string }>(
      `/api/playback/session/${sessionId}`,
      { method: "DELETE" }
    );
  }

  async getActiveSessions() {
    return this.request<{
      sessions: { session_id: string; video_id: string }[];
      max_allowed: number;
    }>("/api/playback/sessions");
  }
}

export const api = new ApiClient();
