"use client";

import { useEffect, useState } from "react";

import { api, DEFAULT_FILTERS, type TransactionFilters } from "@/lib/api";
import { useDebouncedValue, useResource } from "@/lib/hooks";
import { DetailPanel } from "./DetailPanel";
import { Filters } from "./Filters";
import { SummaryCards } from "./SummaryCards";
import { TransactionTable } from "./TransactionTable";
import styles from "./dashboard.module.css";

const SEARCH_DEBOUNCE_MS = 300;

export function Dashboard() {
  const [filters, setFilters] = useState<TransactionFilters>(DEFAULT_FILTERS);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Bumped after a review so the totals, the list and the panel reload together.
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string>();

  const query: TransactionFilters = { ...filters, search: debouncedSearch };
  const summary = useResource(`summary:${version}`, (signal) => api.summary(signal));
  const page = useResource(JSON.stringify({ ...query, version }), (signal) =>
    api.transactions(query, signal),
  );
  const detail = useResource(selectedId && `${selectedId}:${version}`, (signal) =>
    api.transaction(selectedId as string, signal),
  );

  // Any filter change goes back to the first page.
  const changeFilters = (change: Partial<TransactionFilters>) =>
    setFilters((current) => ({ ...current, offset: 0, ...change }));

  const changeSearch = (value: string) => {
    setSearch(value);
    setFilters((current) => ({ ...current, offset: 0 }));
  };

  const select = (id: string | null) => {
    setSelectedId(id);
    setReviewError(undefined);
  };

  const review = async (action: "approve" | "reject") => {
    if (!selectedId) return;
    setBusy(true);
    setReviewError(undefined);
    try {
      await api[action](selectedId);
      setVersion((v) => v + 1);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Erro ao revisar a sugestão");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadError = summary.error ?? page.error;
  // While a new transaction loads, do not show the previous one's details.
  const shownDetail = detail.data?.transaction_id === selectedId ? detail.data : undefined;

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <h1>Conciliação bancária e transações incomuns</h1>
        <p>
          Extrato conciliado com as notas fiscais. O ranking aponta o que merece investigação
          humana; não afirma que uma transação é fraude.
        </p>
      </header>

      {loadError && (
        <div className={styles.error} role="alert">
          Não foi possível carregar os dados: {loadError}
        </div>
      )}

      <SummaryCards summary={summary.data} filters={filters} onSelect={changeFilters} />
      <Filters
        filters={filters}
        search={search}
        onSearch={changeSearch}
        onChange={changeFilters}
      />
      <TransactionTable
        page={page.data}
        loading={page.loading}
        selectedId={selectedId}
        onSelect={select}
        onPage={(offset) => setFilters((current) => ({ ...current, offset }))}
      />

      {selectedId && (
        <DetailPanel
          detail={shownDetail}
          error={reviewError ?? detail.error}
          busy={busy || detail.loading}
          onClose={() => select(null)}
          onApprove={() => review("approve")}
          onReject={() => review("reject")}
        />
      )}
    </main>
  );
}
