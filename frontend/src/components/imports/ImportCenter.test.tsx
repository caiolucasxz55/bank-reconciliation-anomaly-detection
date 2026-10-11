import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportBatch, ImportResult } from "@/lib/api";
import { ImportCenter } from "./ImportCenter";

const history: ImportBatch[] = [];
let nextResponse: { status: number; body: unknown };
const calls: { url: string; method: string; body: unknown }[] = [];

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

function fakeFetch(url: string, init?: RequestInit) {
  calls.push({ url, method: init?.method ?? "GET", body: init?.body });
  if (url === "/api/imports") return json(history);
  return json(nextResponse.body, nextResponse.status);
}

const statementResult: ImportResult = {
  import_id: 1,
  kind: "extrato",
  filename: "extrato.ofx",
  created_at: "2025-04-30T15:00:00Z",
  imported: 3,
  duplicates: 1,
  skipped: 1,
  errors: ["linha 7: valor inválido: 'abc'"],
  suppliers_created: 0,
  processed: { transactions: 3, kept_reviews: 0, high_risk: 1 },
};

beforeEach(() => {
  history.length = 0;
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ofx = () => new File(["<OFX>"], "extrato.ofx", { type: "application/x-ofx" });

describe("ImportCenter", () => {
  it("starts with an empty history", async () => {
    render(<ImportCenter />);
    expect(await screen.findByText("Nenhuma importação ainda.")).toBeDefined();
  });

  it("uploads a statement with its account and shows the result", async () => {
    nextResponse = { status: 201, body: statementResult };
    render(<ImportCenter />);
    const card = screen.getByRole("heading", { name: "Extrato bancário" }).closest("form")!;
    const button = within(card).getByRole("button", { name: "Importar extrato" });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    await userEvent.upload(within(card).getByLabelText("Arquivo"), ofx());
    const accountInput = within(card).getByLabelText(/Conta/);
    await userEvent.clear(accountInput);
    await userEvent.type(accountInput, "corrente");
    await userEvent.click(button);

    const status = await screen.findByRole("status");
    expect(status.textContent).toContain(
      "3 pagamentos importados · 1 já existia · 1 crédito ignorado",
    );
    expect(status.textContent).toContain("refeitos para 3 transações · 1 de alto risco");
    expect(status.textContent).toContain("linha 7: valor inválido");

    const upload = calls.find((c) => c.url === "/api/imports/statement")!;
    expect(upload.method).toBe("POST");
    const form = upload.body as FormData;
    expect((form.get("file") as File).name).toBe("extrato.ofx");
    expect(form.get("account")).toBe("corrente");
    // The history is reloaded after the import.
    expect(calls.filter((c) => c.url === "/api/imports").length).toBe(2);
  });

  it("sends every selected invoice file", async () => {
    nextResponse = {
      status: 201,
      body: { ...statementResult, kind: "notas", filename: "2 arquivos", suppliers_created: 2 },
    };
    render(<ImportCenter />);
    const card = screen.getByRole("heading", { name: "Notas fiscais" }).closest("form")!;
    await userEvent.upload(within(card).getByLabelText("Arquivos"), [
      new File(["<NFe/>"], "a.xml"),
      new File(["<NFe/>"], "b.xml"),
    ]);
    expect(within(card).getByText("2 arquivos selecionados")).toBeDefined();
    await userEvent.click(within(card).getByRole("button", { name: "Importar notas" }));

    expect((await screen.findByRole("status")).textContent).toContain("2 fornecedores novos");
    const form = calls.find((c) => c.url === "/api/imports/invoices")!.body as FormData;
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["a.xml", "b.xml"]);
  });

  it("shows the API error and keeps the chosen file", async () => {
    nextResponse = { status: 422, body: { detail: "extrato.pdf: formato não suportado" } };
    render(<ImportCenter />);
    const card = screen.getByRole("heading", { name: "Extrato bancário" }).closest("form")!;
    await userEvent.upload(within(card).getByLabelText("Arquivo"), ofx());
    await userEvent.click(within(card).getByRole("button", { name: "Importar extrato" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "extrato.pdf: formato não suportado",
    );
    const button = within(card).getByRole("button", { name: "Importar extrato" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("lists past imports with their warnings", async () => {
    history.push(statementResult);
    render(<ImportCenter />);
    const table = await screen.findByRole("table");
    const [, row] = within(table).getAllByRole("row"); // header, then the import
    expect(within(row).getByText("Extrato")).toBeDefined();
    expect(within(row).getByText(/3 pagamentos importados/)).toBeDefined();
    expect(within(row).getByText("1")).toBeDefined(); // warnings count
  });

  it("reprocesses on demand", async () => {
    nextResponse = { status: 200, body: { transactions: 10, kept_reviews: 2, high_risk: 1 } };
    render(<ImportCenter />);
    await userEvent.click(screen.getByRole("button", { name: "Reprocessar tudo" }));
    expect((await screen.findByRole("status")).textContent).toContain(
      "10 transações · 1 de alto risco · 2 revisões mantidas",
    );
    expect(calls.some((c) => c.url === "/api/process" && c.method === "POST")).toBe(true);
  });
});
