import Link from "next/link";

interface Video {
  id: string;
  title: string;
  description: string;
  thumbnail: string;
  duration: string;
}

interface VideoCardProps {
  video: Video;
}

export default function VideoCard({ video }: VideoCardProps) {
  return (
    <Link href={`/watch/${video.id}`} className="group block">
      <div className="bg-gray-800 rounded-lg overflow-hidden transition-transform group-hover:scale-[1.02] group-hover:shadow-xl">
        <div className="aspect-video bg-gray-700 relative flex items-center justify-center">
          <svg
            className="w-16 h-16 text-gray-500 group-hover:text-white transition-colors"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M8 5v14l11-7z" />
          </svg>
          <span className="absolute bottom-2 right-2 bg-black/80 text-white text-xs px-2 py-1 rounded">
            {video.duration}
          </span>
        </div>
        <div className="p-4">
          <h3 className="text-white font-semibold text-lg group-hover:text-blue-400 transition-colors">
            {video.title}
          </h3>
          <p className="text-gray-400 text-sm mt-1 line-clamp-2">
            {video.description}
          </p>
          <div className="flex items-center gap-2 mt-3">
            <span className="text-xs bg-green-900/50 text-green-400 px-2 py-0.5 rounded">
              DRM Protected
            </span>
            <span className="text-xs bg-blue-900/50 text-blue-400 px-2 py-0.5 rounded">
              Watermarked
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
