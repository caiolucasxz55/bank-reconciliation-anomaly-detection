import { describe, expect, it } from "vitest";

import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatPercent,
  importSummary,
  layerLabel,
  pageRange,
  plural,
} from "./format";

describe("format", () => {
  it("formats Brazilian currency", () => {
    expect(formatCurrency(1234.5)).toBe("R$ 1.234,50");
  });

  it("formats ISO dates without timezone shifts", () => {
    expect(formatDate("2025-01-01")).toBe("01/01/2025");
    expect(formatDate("2025-12-31T23:00:00Z")).toBe("31/12/2025");
  });

  it("formats percentages", () => {
    expect(formatPercent(0.719)).toBe("72%");
  });

  it("names layers", () => {
    expect(layerLabel(1)).toBe("Camada 1 · exata");
    expect(layerLabel(3)).toBe("Camada 3 · várias notas");
    expect(layerLabel(null)).toBe("Sem nota correspondente");
    expect(layerLabel(9)).toBe("Camada 9");
  });

  it("describes the visible page range", () => {
    expect(pageRange(0, 25, 608)).toBe("1–25 de 608");
    expect(pageRange(600, 8, 608)).toBe("601–608 de 608");
    expect(pageRange(0, 0, 0)).toBe("0 de 0");
  });
});

describe("import texts", () => {
  it("pluralizes", () => {
    expect(plural(1, "nota", "notas")).toBe("1 nota");
    expect(plural(0, "nota", "notas")).toBe("0 notas");
  });

  it("summarizes a statement import", () => {
    expect(importSummary({ kind: "extrato", imported: 1, duplicates: 2, skipped: 1 })).toBe(
      "1 pagamento importado · 2 já existiam · 1 crédito ignorado",
    );
  });

  it("summarizes an invoice import, omitting zero counts", () => {
    expect(
      importSummary({ kind: "notas", imported: 3, duplicates: 0, skipped: 0, suppliers_created: 1 }),
    ).toBe("3 notas importadas · 1 fornecedor novo");
  });

  it("formats date and time", () => {
    expect(formatDateTime("2025-04-30T15:00:00")).toMatch(/^30\/04\/2025/);
  });
});
