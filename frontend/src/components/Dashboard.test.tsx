import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MatchStatus, Transaction, TransactionDetail } from "@/lib/api";
import { Dashboard } from "./Dashboard";

/** In-memory stand-in for the FastAPI backend, served through a mocked fetch. */
class FakeApi {
  rows: TransactionDetail[];
  failSummary = false;
  failReviewFor = new Set<string>();
  calls: string[] = [];

  constructor(count: number) {
    this.rows = Array.from({ length: count }, (_, i) => this.row(i + 1));
  }

  private row(n: number): TransactionDetail {
    const id = `TX${String(n).padStart(5, "0")}`;
    return {
      transaction_id: id,
      date: "2025-03-10",
      amount: 100 + n,
      description: `PIX FORNECEDOR ${n}`,
      status: "sugerida",
      layer: 2,
      confidence: 0.7,
      supplier_id: "S001",
      supplier_name: "Fornecedor",
      score: 1 / n,
      rank: n,
      rank_label: "entre as 1% mais incomuns",
      high_risk: n <= 2,
      top_reason: `motivo ${n}`,
      reasons: [`motivo ${n}`],
      invoices: [],
      decided_by: "sistema",
      decided_at: null,
      can_review: true,
    };
  }

  private json(body: unknown, status = 200) {
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  }

  fetch = (input: string, init?: RequestInit): Promise<Response> => {
    const url = new URL(input, "http://test");
    this.calls.push(`${init?.method ?? "GET"} ${url.pathname}${url.search}`);
    const parts = url.pathname.split("/").filter(Boolean); // ["api", ...]

    if (parts[1] === "summary") {
      if (this.failSummary) return this.json({ detail: "fora do ar" }, 503);
      const count = (s: MatchStatus) => this.rows.filter((r) => r.status === s).length;
      return this.json({
        total: this.rows.length,
        conciliadas: count("conciliada"),
        sugeridas: count("sugerida"),
        divergentes: count("divergente"),
        alto_risco: this.rows.filter((r) => r.high_risk).length,
      });
    }
    if (parts[1] === "transactions" && parts.length === 2) {
      const status = url.searchParams.get("status");
      const limit = Number(url.searchParams.get("limit"));
      const offset = Number(url.searchParams.get("offset"));
      const matching = this.rows.filter((r) => !status || r.status === status);
      const items: Transaction[] = matching.slice(offset, offset + limit);
      return this.json({ items, total: matching.length, limit, offset });
    }
    const row = this.rows.find((r) => r.transaction_id === parts[2]);
    if (!row) return this.json({ detail: "transação não encontrada" }, 404);
    if (parts[3] === "approve") {
      if (this.failReviewFor.has(row.transaction_id)) {
        return this.json({ detail: `falha ao aprovar ${row.transaction_id}` }, 409);
      }
      Object.assign(row, { status: "conciliada", can_review: false, decided_by: "analista" });
    }
    return this.json(row);
  };
}

let fake: FakeApi;

beforeEach(() => {
  fake = new FakeApi(26);
  vi.stubGlobal("fetch", vi.fn(fake.fetch));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const rowFor = (n: number) => screen.getByText(`PIX FORNECEDOR ${n}`);

describe("Dashboard", () => {
  it("loads totals and the first page", async () => {
    render(<Dashboard />);
    expect(await screen.findByText("1–25 de 26")).toBeDefined();
    expect(screen.getByText("PIX FORNECEDOR 1")).toBeDefined();
  });

  it("approving the only row of the last page steps back a page", async () => {
    render(<Dashboard />);
    await screen.findByText("1–25 de 26");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "sugerida");
    await userEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await screen.findByText("26–26 de 26");

    await userEvent.click(rowFor(26));
    const panel = await screen.findByRole("complementary");
    await userEvent.click(within(panel).getByRole("button", { name: "Aprovar sugestão" }));

    expect(await screen.findByText("1–25 de 25")).toBeDefined();
    expect(within(panel).getByText("analista")).toBeDefined();
    // The panel shows the POST response; the detail is not fetched again.
    const detailFetches = fake.calls.filter((c) => c === "GET /api/transactions/TX00026");
    expect(detailFetches).toHaveLength(1);
  });

  it("keeps a review error on the transaction it belongs to", async () => {
    fake.failReviewFor.add("TX00001");
    render(<Dashboard />);
    await screen.findByText("1–25 de 26");

    await userEvent.click(rowFor(1));
    let panel = await screen.findByRole("complementary");
    await userEvent.click(within(panel).getByRole("button", { name: "Aprovar sugestão" }));
    expect(await within(panel).findByText("falha ao aprovar TX00001")).toBeDefined();

    await userEvent.click(rowFor(2));
    panel = screen.getByRole("complementary");
    await within(panel).findByRole("heading", { name: "TX00002" });
    expect(within(panel).queryByRole("alert")).toBeNull();
  });

  it("offers a retry when loading fails", async () => {
    fake.failSummary = true;
    render(<Dashboard />);
    const retry = await screen.findByRole("button", { name: "Tentar novamente" });
    fake.failSummary = false;
    await userEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Tentar novamente" })).toBeNull());
    expect(screen.getByText("26")).toBeDefined();
  });

  it("Escape in the search box does not close the panel", async () => {
    render(<Dashboard />);
    await screen.findByText("1–25 de 26");
    await userEvent.click(rowFor(3));
    await screen.findByRole("complementary");

    await userEvent.type(screen.getByRole("searchbox"), "abc{Escape}");
    expect(screen.queryByRole("complementary")).not.toBeNull();

    await userEvent.click(document.body);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("complementary")).toBeNull();
  });
});
