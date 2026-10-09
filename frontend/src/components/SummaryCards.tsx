import type { Summary, TransactionFilters } from "@/lib/api";
import styles from "./dashboard.module.css";

interface Props {
  summary: Summary | undefined;
  filters: TransactionFilters;
  onSelect: (change: Partial<TransactionFilters>) => void;
}

interface Card {
  label: string;
  value: (summary: Summary) => number;
  hint: string;
  change: Partial<TransactionFilters>;
  active: (filters: TransactionFilters) => boolean;
}

const CARDS: Card[] = [
  {
    label: "Conciliadas",
    value: (s) => s.conciliadas,
    hint: "casaram com notas fiscais",
    change: { status: "conciliada", risk: "todos" },
    active: (f) => f.status === "conciliada" && f.risk === "todos",
  },
  {
    label: "Sugeridas",
    value: (s) => s.sugeridas,
    hint: "aguardam aprovação",
    change: { status: "sugerida", risk: "todos" },
    active: (f) => f.status === "sugerida" && f.risk === "todos",
  },
  {
    label: "Divergentes",
    value: (s) => s.divergentes,
    hint: "sem nota correspondente",
    change: { status: "divergente", risk: "todos" },
    active: (f) => f.status === "divergente" && f.risk === "todos",
  },
  {
    label: "Alto risco",
    value: (s) => s.alto_risco,
    hint: "as mais incomuns do ranking",
    change: { status: "todos", risk: "alto" },
    active: (f) => f.status === "todos" && f.risk === "alto",
  },
];

/** Totals at the top of the page; clicking a card filters the list. */
export function SummaryCards({ summary, filters, onSelect }: Props) {
  return (
    <div className={styles.cards}>
      {CARDS.map((card) => {
        const active = card.active(filters);
        return (
          <button
            key={card.label}
            type="button"
            className={`${styles.card} ${active ? styles.cardActive : ""}`}
            aria-pressed={active}
            onClick={() =>
              onSelect(active ? { status: "todos", risk: "todos" } : card.change)
            }
          >
            <span className={styles.cardLabel}>{card.label}</span>
            <span className={styles.cardValue}>{summary ? card.value(summary) : "–"}</span>
            <span className={styles.cardHint}>{card.hint}</span>
          </button>
        );
      })}
    </div>
  );
}
