"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { api } from "@/lib/api";

interface VdoPlayerProps {
  videoId: string;
}

export default function VdoPlayer({ videoId }: VdoPlayerProps) {
  const [iframeSrc, setIframeSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tier, setTier] = useState<string>("browser");
  const [maxRes, setMaxRes] = useState<string>("480p");
  const [rotationCount, setRotationCount] = useState(0);
  const sessionIdRef = useRef<string | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rotationRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rotationIntervalRef = useRef(90); // seconds, updated from server

  // Behavioral tracking refs
  const seekCountRef = useRef(0);
  const restartCountRef = useRef(0);
  const lastHeartbeatTimeRef = useRef(Date.now());

  // Track seeks via iframe message events
  const handleMessage = useCallback((event: MessageEvent) => {
    if (event.origin !== "https://player.vdocipher.com") return;
    try {
      const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      if (data.event === "seeked" || data.event === "seeking") {
        seekCountRef.current += 1;
      }
    } catch {
      // not a JSON message, ignore
    }
  }, []);

  useEffect(() => {
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [handleMessage]);

  useEffect(() => {
    async function fetchOTP() {
      try {
        const data = await api.getOTP(videoId);
        setIframeSrc(
          `https://player.vdocipher.com/v2/?otp=${data.otp}&playbackInfo=${data.playback_info}`
        );
        setTier(data.tier || "browser");
        setMaxRes(data.max_resolution || "480p");
        sessionIdRef.current = data.session_id;
        rotationIntervalRef.current = data.rotation_interval || 90;
        lastHeartbeatTimeRef.current = Date.now();

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

          seekCountRef.current = 0;
          restartCountRef.current = 0;

          try {
            const result = await api.sendHeartbeat(
              sessionIdRef.current,
              events
            );
            if (result.risk_level === "blocked") {
              setError(
                "Playback suspended due to unusual activity. Please try again later."
              );
              if (heartbeatRef.current) clearInterval(heartbeatRef.current);
              if (rotationRef.current) clearInterval(rotationRef.current);
            }
          } catch {
            if (heartbeatRef.current) clearInterval(heartbeatRef.current);
          }
        }, 30000);

        // Start OTP rotation
        startOTPRotation();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load video");
      } finally {
        setLoading(false);
      }
    }

    function startOTPRotation() {
      // Clear any existing rotation timer
      if (rotationRef.current) clearInterval(rotationRef.current);

      rotationRef.current = setInterval(async () => {
        if (!sessionIdRef.current) return;

        try {
          const data = await api.rotateOTP(sessionIdRef.current, videoId);
          // Don't update iframe src — that would restart the player.
          // Rotation keeps the server session alive and logs fresh OTP generation.
          setRotationCount((c) => c + 1);

          // Update interval if server changed it
          if (data.rotation_interval) {
            rotationIntervalRef.current = data.rotation_interval;
          }
        } catch (err) {
          // If rotation fails, player continues with current OTP until it expires
          console.warn("OTP rotation failed:", err);
        }
      }, rotationIntervalRef.current * 1000);
    }

    fetchOTP();

    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (rotationRef.current) clearInterval(rotationRef.current);
      if (sessionIdRef.current) {
        api.endSession(sessionIdRef.current).catch(() => {});
      }
    };
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
