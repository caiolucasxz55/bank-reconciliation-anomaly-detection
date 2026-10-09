import type { TransactionPage } from "@/lib/api";
import { formatCurrency, formatDate, pageRange } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";
import styles from "./dashboard.module.css";

interface Props {
  page: TransactionPage | undefined;
  loading: boolean;
  /** The first load failed: show that instead of a loading placeholder. */
  failed: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPage: (offset: number) => void;
}

export function TransactionTable({ page, loading, failed, selectedId, onSelect, onPage }: Props) {
  const items = page?.items ?? [];
  return (
    <div className={styles.tableWrap} aria-busy={loading}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Data</th>
            <th>Descrição no extrato</th>
            <th>Fornecedor</th>
            <th className={styles.num}>Valor</th>
            <th>Status</th>
            <th>Ranking</th>
            <th>Principal motivo</th>
          </tr>
        </thead>
        <tbody>
          {items.map((tx) => (
            <tr
              key={tx.transaction_id}
              className={tx.transaction_id === selectedId ? styles.selected : undefined}
              onClick={() => onSelect(tx.transaction_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(tx.transaction_id);
                }
              }}
              tabIndex={0}
              aria-selected={tx.transaction_id === selectedId}
            >
              <td className={styles.num}>{formatDate(tx.date)}</td>
              <td className={styles.mono}>{tx.description}</td>
              <td>{tx.supplier_name ?? <span className={styles.muted}>não identificado</span>}</td>
              <td className={styles.num}>{formatCurrency(tx.amount)}</td>
              <td>
                <StatusBadge status={tx.status} />
              </td>
              <td className={tx.high_risk ? styles.risk : styles.muted}>{tx.rank_label}</td>
              <td className={styles.reason}>{tx.top_reason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {page && items.length === 0 && (
        <div className={styles.empty}>Nenhuma transação com esses filtros.</div>
      )}
      {!page && (
        <div className={styles.empty}>
          {failed ? "Lista indisponível no momento." : "Carregando transações…"}
        </div>
      )}
      {page && page.total > 0 && (
        <div className={styles.pager}>
          <span>{pageRange(page.offset, items.length, page.total)}</span>
          <button
            type="button"
            className={styles.button}
            disabled={loading || page.offset === 0}
            onClick={() => onPage(Math.max(0, page.offset - page.limit))}
          >
            Anterior
          </button>
          <button
            type="button"
            className={styles.button}
            disabled={loading || page.offset + page.limit >= page.total}
            onClick={() => onPage(page.offset + page.limit)}
          >
            Próxima
          </button>
        </div>
      )}
    </div>
  );
}
