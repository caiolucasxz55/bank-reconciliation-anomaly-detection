import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "./route";

describe("API proxy route", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("forwards path and query to API_URL read at request time", async () => {
    vi.stubEnv("API_URL", "http://api:8000");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"total":1}', { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://web/api/transactions?status=sugerida&limit=5"));

    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "http://api:8000/api/transactions?status=sugerida&limit=5",
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ total: 1 });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("forwards POST and keeps the upstream status", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('{"detail":"conflito"}', { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://web/api/transactions/TX1/approve", { method: "POST" }),
    );

    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "http://localhost:8000/api/transactions/TX1/approve",
    );
    expect(response.status).toBe(409);
  });

  it("answers 502 when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const response = await GET(new Request("http://web/api/summary"));
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "API indisponível no momento" });
  });
});
