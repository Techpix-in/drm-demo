"use client";

import { useEffect, useState, useRef } from "react";
import { api } from "@/lib/api";

interface VdoPlayerProps {
  videoId: string;
}

export default function VdoPlayer({ videoId }: VdoPlayerProps) {
  const [otp, setOtp] = useState<string | null>(null);
  const [playbackInfo, setPlaybackInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const sessionIdRef = useRef<string | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    async function fetchOTP() {
      try {
        const data = await api.getOTP(videoId);
        setOtp(data.otp);
        setPlaybackInfo(data.playback_info);
        sessionIdRef.current = data.session_id;

        // Start heartbeat every 30 seconds
        heartbeatRef.current = setInterval(() => {
          if (sessionIdRef.current) {
            api.sendHeartbeat(sessionIdRef.current).catch(() => {
              // Session expired or invalid, stop heartbeat
              if (heartbeatRef.current) {
                clearInterval(heartbeatRef.current);
              }
            });
          }
        }, 30000);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load video");
      } finally {
        setLoading(false);
      }
    }

    fetchOTP();

    // Cleanup: stop heartbeat and end session on unmount
    return () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
      }
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
    <div className="aspect-video bg-black rounded-lg overflow-hidden">
      <iframe
        src={`https://player.vdocipher.com/v2/?otp=${otp}&playbackInfo=${playbackInfo}`}
        style={{ width: "100%", height: "100%", border: 0 }}
        allow="encrypted-media"
        allowFullScreen
      />
    </div>
  );
}
