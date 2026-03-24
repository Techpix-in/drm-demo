import type { NextConfig } from "next";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        // Proxy all /api/* requests to the backend server-side
        // This avoids mixed-content blocking (HTTPS frontend → HTTP backend)
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "frame-src https://player.vdocipher.com https://*.vdocipher.com",
              "connect-src 'self' https://*.vdocipher.com https://*.cloudfront.net",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.vdocipher.com",
              "style-src 'self' 'unsafe-inline' https://*.vdocipher.com",
              "media-src 'self' https://*.vdocipher.com https://*.cloudfront.net blob:",
              "img-src 'self' data: https:",
              "worker-src 'self' blob:",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
