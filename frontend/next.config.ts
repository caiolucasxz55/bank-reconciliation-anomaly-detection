import type { NextConfig } from "next";

// Calls to the FastAPI backend go through the /api/[...path] route handler, which reads
// API_URL at request time (see src/app/api/[...path]/route.ts).
const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
};

export default nextConfig;
