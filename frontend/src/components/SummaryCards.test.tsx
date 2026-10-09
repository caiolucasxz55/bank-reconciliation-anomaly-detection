import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_FILTERS } from "@/lib/api";
import { SummaryCards } from "./SummaryCards";

const summary = { total: 608, conciliadas: 573, sugeridas: 26, divergentes: 9, alto_risco: 30 };

describe("SummaryCards", () => {
  afterEach(cleanup);

  it("shows the four totals", () => {
    render(<SummaryCards summary={summary} filters={DEFAULT_FILTERS} onSelect={vi.fn()} />);
    for (const value of ["573", "26", "9", "30"]) {
      expect(screen.getByText(value)).toBeDefined();
    }
  });

  it("shows placeholders while loading", () => {
    render(<SummaryCards summary={undefined} filters={DEFAULT_FILTERS} onSelect={vi.fn()} />);
    expect(screen.getAllByText("–")).toHaveLength(4);
  });

  it("filters the list when a card is clicked", async () => {
    const onSelect = vi.fn();
    render(<SummaryCards summary={summary} filters={DEFAULT_FILTERS} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: /Alto risco/ }));
    expect(onSelect).toHaveBeenCalledWith({ status: "todos", risk: "alto" });
  });

  it("clears the filter when the active card is clicked again", async () => {
    const onSelect = vi.fn();
    const filters = { ...DEFAULT_FILTERS, status: "sugerida" as const };
    render(<SummaryCards summary={summary} filters={filters} onSelect={onSelect} />);
    const card = screen.getByRole("button", { name: /Sugeridas/ });
    expect(card.getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(card);
    expect(onSelect).toHaveBeenCalledWith({ status: "todos", risk: "todos" });
  });
});
