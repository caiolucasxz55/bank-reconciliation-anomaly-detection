import type { MatchStatus, RiskFilter, SortOrder, TransactionFilters } from "@/lib/api";
import { STATUS_LABELS } from "@/lib/format";
import styles from "./dashboard.module.css";

interface Props {
  filters: TransactionFilters;
  search: string;
  onSearch: (value: string) => void;
  onChange: (change: Partial<TransactionFilters>) => void;
}

const RISK_OPTIONS: { value: RiskFilter; label: string }[] = [
  { value: "todos", label: "Todos os scores" },
  { value: "alto", label: "Alto risco (top 5%)" },
  { value: "top10", label: "Top 10% mais incomuns" },
  { value: "top25", label: "Top 25% mais incomuns" },
];

const SORT_OPTIONS: { value: SortOrder; label: string }[] = [
  { value: "risco", label: "Mais incomuns primeiro" },
  { value: "data", label: "Mais recentes primeiro" },
  { value: "valor", label: "Maior valor primeiro" },
];

export function Filters({ filters, search, onSearch, onChange }: Props) {
  return (
    <div className={styles.filters} role="search">
      <label className={styles.field}>
        Status
        <select
          value={filters.status}
          onChange={(e) => onChange({ status: e.target.value as MatchStatus | "todos" })}
        >
          <option value="todos">Todos</option>
          {(Object.keys(STATUS_LABELS) as MatchStatus[]).map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.field}>
        Score
        <select
          value={filters.risk}
          onChange={(e) => onChange({ risk: e.target.value as RiskFilter })}
        >
          {RISK_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.field}>
        Ordenar
        <select
          value={filters.sort}
          onChange={(e) => onChange({ sort: e.target.value as SortOrder })}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className={`${styles.field} ${styles.search}`}>
        Buscar
        <input
          type="search"
          placeholder="Descrição ou ID (ex.: PIX ACME, TX00042)"
          value={search}
          maxLength={64}
          onChange={(e) => onSearch(e.target.value)}
        />
      </label>
    </div>
  );
}
