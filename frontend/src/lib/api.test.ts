import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, DEFAULT_FILTERS, transactionQuery } from "./api";

describe("transactionQuery", () => {
  it("sends only sort and pagination by default", () => {
    expect(transactionQuery(DEFAULT_FILTERS).toString()).toBe("sort=risco&limit=25&offset=0");
  });

  it("maps UI filters to API parameters", () => {
    const params = transactionQuery({
      ...DEFAULT_FILTERS,
      status: "sugerida",
      risk: "top10",
      search: "  PIX ACME ",
      offset: 50,
    });
    expect(params.get("status")).toBe("sugerida");
    expect(params.get("max_percentile")).toBe("0.1");
    expect(params.get("high_risk")).toBeNull();
    expect(params.get("q")).toBe("PIX ACME");
    expect(params.get("offset")).toBe("50");
  });

  it("uses the high-risk flag for the top 5%", () => {
    const params = transactionQuery({ ...DEFAULT_FILTERS, risk: "alto" });
    expect(params.get("high_risk")).toBe("true");
    expect(params.get("max_percentile")).toBeNull();
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("calls same-origin /api paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ total: 1 })));
    vi.stubGlobal("fetch", fetchMock);
    await api.summary();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/summary");
  });

  it("posts reviews and encodes the id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    await api.approve("TX 1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/transactions/TX%201/approve");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("surfaces the API error detail", async () => {
    const body = JSON.stringify({ detail: "só sugestões podem ser revisadas" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 409 })));
    const error = await api.reject("TX1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("só sugestões podem ser revisadas");
  });

  it("falls back to a generic message for non-JSON errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 502 })));
    await expect(api.summary()).rejects.toThrow("Erro 502 ao chamar a API");
  });
});
