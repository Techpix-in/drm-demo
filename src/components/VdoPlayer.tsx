"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import type { DebugData, DebugEvent } from "./DebugPanel";

interface VdoPlayerProps {
  videoId: string;
  debug?: boolean;
  onDebugUpdate?: (data: DebugData, events: DebugEvent[]) => void;
}

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
  let hash = 0;
  for (let i = 0; i < raw.length; i++) {
    const char = raw.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

function nowTime(): string {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

export default function VdoPlayer({ videoId, debug = false, onDebugUpdate }: VdoPlayerProps) {
  const [iframeSrc, setIframeSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tier, setTier] = useState<string>("browser");
  const [maxRes, setMaxRes] = useState<string>("480p");
  const [rotationCount, setRotationCount] = useState(0);
  const sessionIdRef = useRef<string | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rotationRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const debugPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rotationIntervalRef = useRef(90);

  // Behavioral tracking refs
  const seekCountRef = useRef(0);
  const restartCountRef = useRef(0);
  const lastHeartbeatTimeRef = useRef(Date.now());

  // Debug state refs (avoid re-renders, push via callback)
  const debugDataRef = useRef<DebugData>({
    sessionId: null, tier: "browser", maxRes: "480p",
    deviceFingerprint: getDeviceFingerprint(),
    createdAt: null, lastHeartbeat: null, heartbeatStatus: "",
    riskLevel: "normal", sessionTtl: 90, totalPlaySeconds: 0,
    ipChanges: 0, currentIp: "", seeksLastMinute: 0,
    otpRotations: 0, rotationInterval: 90,
    lastRotation: null,
    heartbeatCount: 0, missedHeartbeats: 0, sessionAgeSeconds: 0,
    playRatio: 1, recentSessionCreations: 0, ghostSessions: 0,
    flags: [],
    rateLimits: null,
    riskScore: 0, riskThreshold: 100, riskStatus: "normal",
  });
  const debugEventsRef = useRef<DebugEvent[]>([]);

  const debugRef = useRef(debug);
  const onDebugUpdateRef = useRef(onDebugUpdate);
  debugRef.current = debug;
  onDebugUpdateRef.current = onDebugUpdate;

  const pushDebug = useCallback(() => {
    if (!debugRef.current || !onDebugUpdateRef.current) return;
    onDebugUpdateRef.current({ ...debugDataRef.current }, [...debugEventsRef.current]);
  }, []);

  const addEvent = useCallback((type: DebugEvent["type"], message: string, details?: Record<string, unknown>) => {
    debugEventsRef.current.unshift({ time: nowTime(), type, message, details });
    if (debugEventsRef.current.length > 100) debugEventsRef.current.pop();
    pushDebug();
  }, [pushDebug]);

  // Seek detection: VdoCipher's iframe is cross-origin and does not emit
  // seek events via postMessage. Seek tracking requires either:
  // 1. VdoCipher's native mobile SDK (gives direct player event access)
  // 2. A custom player (Shaka/dash.js) with your own DRM license server
  //
  // For the iframe embed, we track restarts (OTP re-requests) and
  // continuous play time instead. Seek detection is a limitation of
  // third-party iframe-based players.
  //
  // We still listen for any messages VdoCipher might send in the future:
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      if (!data) return;
      const eventName = data.event || data.type || data.name || "";
      if (["seeked", "seeking", "seek"].includes(eventName)) {
        seekCountRef.current += 1;
      }
    } catch {
      // not a JSON message
    }
  }, []);

  useEffect(() => {
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [handleMessage]);

  // Live counter update for debug panel (every 1s)
  useEffect(() => {
    if (!debug) return;
    const interval = setInterval(pushDebug, 1000);
    return () => clearInterval(interval);
  }, [debug, pushDebug]);

  useEffect(() => {
    let mounted = true;

    async function fetchOTP() {
      if (!mounted) return;
      try {
        const data = await api.getOTP(videoId);
        if (!mounted) return;
        setIframeSrc(
          `https://player.vdocipher.com/v2/?otp=${data.otp}&playbackInfo=${data.playback_info}`
        );
        setTier(data.tier || "browser");
        setMaxRes(data.max_resolution || "480p");
        sessionIdRef.current = data.session_id;
        rotationIntervalRef.current = data.rotation_interval || 90;
        lastHeartbeatTimeRef.current = Date.now();

        // Update debug
        debugDataRef.current.sessionId = data.session_id;
        debugDataRef.current.tier = data.tier || "browser";
        debugDataRef.current.maxRes = data.max_resolution || "480p";
        debugDataRef.current.rotationInterval = data.rotation_interval || 90;
        debugDataRef.current.createdAt = Date.now();
        debugDataRef.current.lastRotation = Date.now();
        addEvent("SESSION", `Created session ${data.session_id.slice(0, 12)}...`);
        addEvent("OTP_CREATED", `OTP #1 (tier: ${data.tier}, res: ${data.max_resolution})`);

        // Start heartbeat every 30 seconds
        heartbeatRef.current = setInterval(async () => {
          if (!sessionIdRef.current) return;

          const now = Date.now();
          const elapsed = (now - lastHeartbeatTimeRef.current) / 1000;
          lastHeartbeatTimeRef.current = now;

          const events = {
            seek_count: seekCountRef.current,
            restart_count: restartCountRef.current,
            play_seconds: Math.round(elapsed),
          };

          const seekSnapshot = seekCountRef.current;
          const restartSnapshot = restartCountRef.current;
          seekCountRef.current = 0;
          restartCountRef.current = 0;

          try {
            const result = await api.sendHeartbeat(sessionIdRef.current, events);

            // Update debug from server-side signals
            debugDataRef.current.lastHeartbeat = Date.now();
            debugDataRef.current.heartbeatStatus = result.status;
            debugDataRef.current.riskLevel = result.risk_level;
            debugDataRef.current.flags = result.flags || [];
            if (result.debug) {
              debugDataRef.current.sessionTtl = result.debug.session_ttl;
              debugDataRef.current.totalPlaySeconds = result.debug.total_play_seconds;
              debugDataRef.current.ipChanges = result.debug.ip_changes;
              debugDataRef.current.currentIp = result.debug.current_ip;
              debugDataRef.current.otpRotations = result.debug.otp_rotations;
              debugDataRef.current.heartbeatCount = result.debug.heartbeat_count;
              debugDataRef.current.missedHeartbeats = result.debug.missed_heartbeats;
              debugDataRef.current.sessionAgeSeconds = result.debug.session_age_seconds;
              debugDataRef.current.playRatio = result.debug.play_ratio;
              debugDataRef.current.recentSessionCreations = result.debug.recent_session_creations;
              debugDataRef.current.ghostSessions = result.debug.ghost_sessions;
            }

            const flagStr = result.flags?.length ? ` [${result.flags.join(", ")}]` : "";
            addEvent(
              result.risk_level === "normal" ? "HEARTBEAT" : "WARNING",
              `${result.risk_level} (play:${Math.round(elapsed)}s, ratio:${result.debug?.play_ratio?.toFixed(2) || "--"})${flagStr}`
            );

            if (result.risk_level === "blocked") {
              setError("Playback suspended due to unusual activity. Please try again later.");
              if (heartbeatRef.current) clearInterval(heartbeatRef.current);
              if (rotationRef.current) clearInterval(rotationRef.current);
              if (debugPollRef.current) clearInterval(debugPollRef.current);
              addEvent("ERROR", "Session blocked — playback stopped");
            }
          } catch {
            if (heartbeatRef.current) clearInterval(heartbeatRef.current);
            addEvent("ERROR", "Heartbeat failed — timer stopped");
          }
        }, 30000);

        // Start OTP rotation
        startOTPRotation();

        // Start debug polling (rate limits + risk score)
        if (debug) {
          fetchDebugInfo();
          debugPollRef.current = setInterval(fetchDebugInfo, 15000);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load video");
        addEvent("ERROR", err instanceof Error ? err.message : "Failed to load video");
      } finally {
        setLoading(false);
      }
    }

    function startOTPRotation() {
      if (rotationRef.current) clearInterval(rotationRef.current);

      rotationRef.current = setInterval(async () => {
        if (!sessionIdRef.current) return;

        try {
          const data = await api.rotateOTP(sessionIdRef.current, videoId);
          setRotationCount((c) => c + 1);
          debugDataRef.current.lastRotation = Date.now();
          debugDataRef.current.otpRotations = (debugDataRef.current.otpRotations || 0) + 1;

          if (data.rotation_interval) {
            rotationIntervalRef.current = data.rotation_interval;
            debugDataRef.current.rotationInterval = data.rotation_interval;
          }

          addEvent("OTP_ROTATED", `OTP #${debugDataRef.current.otpRotations + 1} issued`);
        } catch (err) {
          console.warn("OTP rotation failed:", err);
          addEvent("WARNING", `OTP rotation failed: ${err instanceof Error ? err.message : "unknown"}`);
        }
      }, rotationIntervalRef.current * 1000);
    }

    async function fetchDebugInfo() {
      if (!sessionIdRef.current) return;
      try {
        const info = await api.getDebugInfo(sessionIdRef.current);
        debugDataRef.current.rateLimits = info.rate_limits;
        debugDataRef.current.riskScore = info.risk.score;
        debugDataRef.current.riskThreshold = info.risk.threshold;
        debugDataRef.current.riskStatus = info.risk.status;
        pushDebug();
      } catch {
        // Debug endpoint failure is non-critical
      }
    }

    fetchOTP();

    return () => {
      mounted = false;
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (rotationRef.current) clearInterval(rotationRef.current);
      if (debugPollRef.current) clearInterval(debugPollRef.current);
      if (sessionIdRef.current) {
        api.endSession(sessionIdRef.current).catch(() => {});
        sessionIdRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  if (loading) {
    return (
      <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-gray-600 border-t-white rounded-full animate-spin" />
          <p className="text-gray-400 text-sm">Loading secure player...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="aspect-video bg-gray-900 rounded-lg flex items-center justify-center">
        <div className="text-center px-6">
          <p className="text-red-400 text-lg font-medium">Playback Error</p>
          <p className="text-gray-400 text-sm mt-2">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="aspect-video bg-black rounded-lg overflow-hidden relative">
      <iframe
        src={iframeSrc!}
        style={{ width: "100%", height: "100%", border: 0 }}
        allow="encrypted-media"
        allowFullScreen
      />
      {/* Tier badge + rotation indicator */}
      <div className="absolute top-3 right-3 flex items-center gap-2">
        {rotationCount > 0 && (
          <div className="bg-green-900/60 text-xs text-green-300 px-2 py-1 rounded">
            OTP #{rotationCount + 1}
          </div>
        )}
        <div className="bg-black/60 text-xs text-gray-300 px-2 py-1 rounded">
          {tier === "browser" ? `Browser · Max ${maxRes}` : `${tier} · ${maxRes}`}
        </div>
      </div>
    </div>
  );
}
