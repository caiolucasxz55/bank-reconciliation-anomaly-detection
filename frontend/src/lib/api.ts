// Client for the FastAPI backend. The browser calls same-origin /api/* paths, which
// next.config.ts rewrites to the API, so no CORS setup is needed in production.

export type MatchStatus = "conciliada" | "sugerida" | "divergente";
export type SortOrder = "risco" | "data" | "valor";

export interface Summary {
  total: number;
  conciliadas: number;
  sugeridas: number;
  divergentes: number;
  alto_risco: number;
}

export interface Transaction {
  transaction_id: string;
  date: string;
  amount: number;
  description: string;
  status: MatchStatus;
  layer: number | null;
  confidence: number;
  supplier_id: string | null;
  supplier_name: string | null;
  score: number;
  rank: number;
  rank_label: string;
  high_risk: boolean;
  top_reason: string | null;
}

export interface Invoice {
  invoice_id: string;
  issue_date: string;
  amount: number;
}

export interface TransactionDetail extends Transaction {
  reasons: string[];
  invoices: Invoice[];
  decided_by: string;
  decided_at: string | null;
  can_review: boolean;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

/** Score filter shown in the UI, mapped to API parameters. */
export type RiskFilter = "todos" | "alto" | "top10" | "top25";

export interface TransactionFilters {
  status: MatchStatus | "todos";
  risk: RiskFilter;
  search: string;
  sort: SortOrder;
  offset: number;
  limit: number;
}

export const DEFAULT_FILTERS: TransactionFilters = {
  status: "todos",
  risk: "todos",
  search: "",
  sort: "risco",
  offset: 0,
  limit: 25,
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function transactionQuery(filters: TransactionFilters): URLSearchParams {
  const params = new URLSearchParams({
    sort: filters.sort,
    limit: String(filters.limit),
    offset: String(filters.offset),
  });
  if (filters.status !== "todos") params.set("status", filters.status);
  if (filters.risk === "alto") params.set("high_risk", "true");
  if (filters.risk === "top10") params.set("max_percentile", "0.1");
  if (filters.risk === "top25") params.set("max_percentile", "0.25");
  const search = filters.search.trim();
  if (search) params.set("q", search);
  return params;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Erro ${response.status} ao chamar a API`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const api = {
  summary: (signal?: AbortSignal) => request<Summary>("/summary", { signal }),
  transactions: (filters: TransactionFilters, signal?: AbortSignal) =>
    request<TransactionPage>(`/transactions?${transactionQuery(filters)}`, { signal }),
  transaction: (id: string, signal?: AbortSignal) =>
    request<TransactionDetail>(`/transactions/${encodeURIComponent(id)}`, { signal }),
  approve: (id: string) =>
    request<TransactionDetail>(`/transactions/${encodeURIComponent(id)}/approve`, {
      method: "POST",
    }),
  reject: (id: string) =>
    request<TransactionDetail>(`/transactions/${encodeURIComponent(id)}/reject`, {
      method: "POST",
    }),
};
