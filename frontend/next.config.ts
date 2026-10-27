import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server in .next/standalone, for the Docker image a
  // producer's own copy runs on Railway (frontend/Dockerfile). Vercel ignores it.
  output: "standalone",
};

export default nextConfig;
