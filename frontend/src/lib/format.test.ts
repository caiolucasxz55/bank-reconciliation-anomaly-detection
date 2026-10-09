import { describe, expect, it } from "vitest";

import { formatCurrency, formatDate, formatPercent, layerLabel, pageRange } from "./format";

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
