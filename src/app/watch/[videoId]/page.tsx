"use client";

import { useEffect, useState, use } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import VdoPlayer from "@/components/VdoPlayer";
import DebugPanel from "@/components/DebugPanel";
import type { DebugData, DebugEvent } from "@/components/DebugPanel";
import LoginForm from "@/components/LoginForm";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";

interface Video {
  id: string;
  title: string;
  description: string;
  thumbnail: string;
  duration: string;
}

interface WatchPageProps {
  params: Promise<{ videoId: string }>;
}

export default function WatchPage({ params }: WatchPageProps) {
  const { videoId } = use(params);
  const searchParams = useSearchParams();
  const isDebug = searchParams.get("debug") === "true";
  const { user, loading: authLoading } = useAuth();
  const [video, setVideo] = useState<Video | null>(null);
  const [loading, setLoading] = useState(true);

  // Debug state
  const [debugData, setDebugData] = useState<DebugData | null>(null);
  const [debugEvents, setDebugEvents] = useState<DebugEvent[]>([]);

  useEffect(() => {
    if (!user) return;
    api
      .getVideos()
      .then((data) => {
        const found = data.videos.find((v) => v.id === videoId);
        setVideo(found || null);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user, videoId]);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="w-10 h-10 border-4 border-gray-600 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <LoginForm />;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="w-10 h-10 border-4 border-gray-600 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  if (!video) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-12 text-center">
        <h1 className="text-2xl font-bold text-red-400">Video Not Found</h1>
        <Link href="/" className="text-blue-400 mt-4 inline-block">
          Back to Library
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <Link
        href="/"
        className="text-gray-400 hover:text-white text-sm mb-4 inline-flex items-center gap-1"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 19l-7-7 7-7"
          />
        </svg>
        Back to Library
      </Link>

      {/* Player */}
      <div className="mt-4">
        <VdoPlayer
          videoId={videoId}
          debug={isDebug}
          onDebugUpdate={(data, events) => {
            setDebugData(data);
            setDebugEvents(events);
          }}
        />
      </div>

      {/* Debug Panel — only when ?debug=true */}
      {isDebug && debugData && (
        <DebugPanel data={debugData} events={debugEvents} />
      )}

      {/* Video Info */}
      <div className="mt-6">
        <h1 className="text-2xl font-bold">{video.title}</h1>
        <p className="text-gray-400 mt-2">{video.description}</p>
        <div className="flex items-center gap-3 mt-4">
          <span className="text-xs bg-green-900/50 text-green-400 px-2 py-1 rounded">
            DRM Protected
          </span>
          <span className="text-xs bg-blue-900/50 text-blue-400 px-2 py-1 rounded">
            Watermarked
          </span>
          <span className="text-xs text-gray-500">{video.duration}</span>
          {isDebug && (
            <span className="text-xs bg-yellow-900/50 text-yellow-400 px-2 py-1 rounded">
              Debug Mode
            </span>
          )}
        </div>
      </div>

      {/* Security Details */}
      <div className="mt-8 bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">
          Content Protection Details
        </h2>
        <div className="space-y-2 text-sm text-gray-400">
          <p>
            <span className="text-gray-300 font-medium">DRM:</span> Widevine
            (Chrome, Firefox, Edge, Android) + FairPlay (Safari, iOS)
          </p>
          <p>
            <span className="text-gray-300 font-medium">Token:</span>{" "}
            Session-bound, expires in 5 minutes
          </p>
          <p>
            <span className="text-gray-300 font-medium">Watermark:</span>{" "}
            Forensic watermark with viewer identity embedded
          </p>
          <p>
            <span className="text-gray-300 font-medium">Browser Limit:</span>{" "}
            Widevine L3 restricted to 480p max resolution
          </p>
        </div>
      </div>

      {/* Debug hint */}
      {!isDebug && (
        <p className="text-xs text-gray-600 mt-4 text-center">
          Tip: Add <code className="text-gray-500">?debug=true</code> to the URL to see the developer debug panel
        </p>
      )}
    </div>
  );
}
