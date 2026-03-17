"use client";

import { useEffect, useState } from "react";
import VideoCard from "@/components/VideoCard";
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

export default function HomePage() {
  const { user, loading: authLoading } = useAuth();
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api
      .getVideos()
      .then((data) => setVideos(data.videos))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user]);

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

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Content Library</h1>
        <p className="text-gray-400 mt-2">
          All content is DRM-protected with Widevine &amp; FairPlay encryption
          and forensic watermarking.
        </p>
      </div>

      {/* Security Info Banner */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-8">
        <h2 className="text-sm font-semibold text-green-400 uppercase tracking-wide">
          Security Active
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full" />
            <span className="text-sm text-gray-300">
              Widevine / FairPlay DRM
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full" />
            <span className="text-sm text-gray-300">Forensic Watermarking</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full" />
            <span className="text-sm text-gray-300">
              Session-Bound Tokens (5min TTL)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full" />
            <span className="text-sm text-gray-300">
              Browser L3: 480p Max
            </span>
          </div>
        </div>
      </div>

      {/* Video Grid */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-10 h-10 border-4 border-gray-600 border-t-white rounded-full animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </div>
      )}
    </div>
  );
}
