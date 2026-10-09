import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TransactionDetail } from "@/lib/api";
import { DetailPanel } from "./DetailPanel";

const detail: TransactionDetail = {
  transaction_id: "TX00360",
  date: "2025-08-11",
  amount: 21955.04,
  description: "PIX VALE VERDE ENGENHARIA S A",
  status: "sugerida",
  layer: 2,
  confidence: 0.7191,
  supplier_id: "S006",
  supplier_name: "Vale Verde Engenharia S.A.",
  score: 0.58,
  rank: 33,
  rank_label: "entre as 6% mais incomuns",
  high_risk: false,
  top_reason: "valor 3,4 vezes acima do normal para o fornecedor",
  reasons: ["valor 3,4 vezes acima do normal para o fornecedor", "pago num sábado"],
  invoices: [{ invoice_id: "NF00412", issue_date: "2025-07-20", amount: 21962.54 }],
  decided_by: "sistema",
  decided_at: null,
  can_review: true,
};

function renderPanel(overrides: Partial<TransactionDetail> = {}, props = {}) {
  const handlers = { onClose: vi.fn(), onApprove: vi.fn(), onReject: vi.fn() };
  render(
    <DetailPanel
      detail={{ ...detail, ...overrides }}
      error={undefined}
      busy={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("DetailPanel", () => {
  afterEach(cleanup);

  it("shows ranking, reasons, matched invoices and the disclaimer", () => {
    renderPanel();
    expect(screen.getByText("entre as 6% mais incomuns")).toBeDefined();
    expect(screen.getByText("pago num sábado")).toBeDefined();
    expect(screen.getByText("NF00412")).toBeDefined();
    expect(screen.getByText(/Camada 2 · tolerante · confiança 72%/)).toBeDefined();
    expect(screen.getByText(/não é uma probabilidade de\s+fraude/)).toBeDefined();
  });

  it("approves and rejects suggestions", async () => {
    const handlers = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Aprovar sugestão" }));
    await userEvent.click(screen.getByRole("button", { name: "Rejeitar" }));
    expect(handlers.onApprove).toHaveBeenCalledOnce();
    expect(handlers.onReject).toHaveBeenCalledOnce();
  });

  it("hides review buttons when the match cannot be reviewed", () => {
    renderPanel({ status: "conciliada", can_review: false });
    expect(screen.queryByRole("button", { name: "Aprovar sugestão" })).toBeNull();
  });

  it("disables review buttons while busy", () => {
    renderPanel({}, { busy: true });
    const approve = screen.getByRole("button", { name: "Aprovar sugestão" }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
  });

  it("explains empty reasons and invoices", () => {
    renderPanel({ reasons: [], invoices: [], layer: null, can_review: false });
    expect(screen.getByText("Nenhum sinal fora do comum nesta transação.")).toBeDefined();
    expect(screen.getByText("Nenhuma nota fiscal vinculada.")).toBeDefined();
    expect(screen.getByText("Sem nota correspondente")).toBeDefined();
  });

  it("shows errors and closes", async () => {
    const handlers = renderPanel({}, { error: "só sugestões podem ser revisadas" });
    expect(screen.getByRole("alert").textContent).toBe("só sugestões podem ser revisadas");
    await userEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(handlers.onClose).toHaveBeenCalledOnce();
  });
});
