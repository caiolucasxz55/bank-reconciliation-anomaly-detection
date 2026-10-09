// Same-origin proxy to the FastAPI backend. The browser only talks to this Next.js
// server, and API_URL is read on every request, so one image works with any API address.

const DEFAULT_API_URL = "http://localhost:8000";
const UPSTREAM_TIMEOUT_MS = 15_000;

function apiUrl(): string {
  return process.env.API_URL ?? DEFAULT_API_URL;
}

async function forward(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, apiUrl());

  const headers = new Headers({ accept: request.headers.get("accept") ?? "application/json" });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch {
    return Response.json({ detail: "API indisponível no momento" }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
