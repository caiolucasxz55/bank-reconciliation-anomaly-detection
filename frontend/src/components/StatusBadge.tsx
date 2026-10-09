import type { MatchStatus } from "@/lib/api";
import { STATUS_LABELS } from "@/lib/format";
import styles from "./dashboard.module.css";

export function StatusBadge({ status }: { status: MatchStatus }) {
  return <span className={`${styles.badge} ${styles[status]}`}>{STATUS_LABELS[status]}</span>;
}
