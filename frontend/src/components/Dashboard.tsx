"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, DEFAULT_FILTERS, type TransactionDetail, type TransactionFilters } from "@/lib/api";
import { useDebouncedValue, useResource } from "@/lib/hooks";
import { DetailPanel } from "./DetailPanel";
import { Filters } from "./Filters";
import { SummaryCards } from "./SummaryCards";
import { TransactionTable } from "./TransactionTable";
import styles from "./dashboard.module.css";

const SEARCH_DEBOUNCE_MS = 300;

/** Offset of the last page that still has rows. */
function lastPageOffset(total: number, limit: number): number {
  return total === 0 ? 0 : Math.floor((total - 1) / limit) * limit;
}

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.matches("input, select, textarea");
}

export function Dashboard() {
  const [filters, setFilters] = useState<TransactionFilters>(DEFAULT_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Bumped after a review or a retry so the totals and the list reload together.
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  // Errors and results of reviews are tied to the transaction they belong to.
  const [reviewError, setReviewError] = useState<{ id: string; message: string }>();
  const [reviewed, setReviewed] = useState<TransactionDetail>();

  // The search only applies (and goes back to the first page) once typing pauses.
  if (debouncedSearch !== filters.search) {
    setFilters({ ...filters, search: debouncedSearch, offset: 0 });
  }

  const summary = useResource(`summary:${version}`, (signal) => api.summary(signal));
  const page = useResource(JSON.stringify({ ...filters, version }), (signal) =>
    api.transactions(filters, signal),
  );
  const detail = useResource(selectedId, (signal) =>
    api.transaction(selectedId as string, signal),
  );

  // A review can empty the last page; step back to the last page that has rows.
  const loaded = page.data;
  if (loaded && !page.loading && loaded.offset > 0 && loaded.offset >= loaded.total) {
    const offset = lastPageOffset(loaded.total, loaded.limit);
    if (offset !== filters.offset) setFilters({ ...filters, offset });
  }

  const changeFilters = (change: Partial<TransactionFilters>) =>
    setFilters((current) => ({ ...current, offset: 0, ...change }));

  const select = (id: string | null) => {
    setSelectedId(id);
    setReviewed(undefined);
  };

  const review = async (id: string, action: "approve" | "reject") => {
    setBusy(true);
    setReviewError(undefined);
    try {
      // The response is the updated detail: show it instead of fetching it again.
      setReviewed(await api[action](id));
      setVersion((v) => v + 1);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Erro ao revisar a sugestão";
      setReviewError({ id, message });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Escape inside a field belongs to the field (e.g. clearing the search box).
      if (event.key === "Escape" && !isTyping(event.target)) {
        setSelectedId(null);
        setReviewed(undefined);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadError = summary.error ?? page.error;
  const shownDetail =
    reviewed?.transaction_id === selectedId
      ? reviewed
      : detail.data?.transaction_id === selectedId
        ? detail.data
        : undefined;
  const panelError =
    reviewError?.id === selectedId ? reviewError.message : shownDetail ? undefined : detail.error;

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
          Não foi possível carregar os dados: {loadError}{" "}
          <button type="button" className={styles.button} onClick={() => setVersion((v) => v + 1)}>
            Tentar novamente
          </button>
        </div>
      )}

      {!summary.data && !summary.error ? (
        // Until the totals arrive it is unknown whether there is anything to list.
        <SummaryCards summary={undefined} filters={filters} onSelect={changeFilters} />
      ) : summary.data?.total === 0 ? (
        <div className={styles.emptyState}>
          <h2>Nenhuma transação ainda</h2>
          <p>
            Importe o extrato do banco e as notas fiscais dos fornecedores para conciliar os
            pagamentos e ver as transações incomuns.
          </p>
          <Link href="/importar" className={`${styles.button} ${styles.primary}`}>
            Importar dados
          </Link>
        </div>
      ) : (
        <>
          <SummaryCards summary={summary.data} filters={filters} onSelect={changeFilters} />
          <Filters
            filters={filters}
            search={searchInput}
            onSearch={setSearchInput}
            onChange={changeFilters}
          />
          <TransactionTable
            page={page.data}
            loading={page.loading}
            failed={page.error !== undefined}
            selectedId={selectedId}
            onSelect={select}
            onPage={(offset) => setFilters((current) => ({ ...current, offset }))}
          />
        </>
      )}

      {selectedId && (
        <DetailPanel
          detail={shownDetail}
          error={panelError}
          busy={busy}
          onClose={() => select(null)}
          onApprove={() => review(selectedId, "approve")}
          onReject={() => review(selectedId, "reject")}
        />
      )}
    </main>
  );
}
