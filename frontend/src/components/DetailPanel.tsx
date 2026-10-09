import type { TransactionDetail } from "@/lib/api";
import { formatCurrency, formatDate, formatPercent, layerLabel } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";
import styles from "./dashboard.module.css";

interface Props {
  detail: TransactionDetail | undefined;
  error: string | undefined;
  busy: boolean;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
}

/** Side panel with the score reasons, the matched invoices and the review buttons. */
export function DetailPanel({ detail, error, busy, onClose, onApprove, onReject }: Props) {
  return (
    <aside className={styles.panel} aria-label="Detalhes da transação">
      <div className={styles.panelHeader}>
        <div>
          <h2>{detail ? detail.transaction_id : error ? "Transação" : "Carregando…"}</h2>
          {detail && <span className={styles.mono}>{detail.description}</span>}
        </div>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Fechar">
          ×
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {detail && (
        <>
          <section className={styles.section}>
            <dl className={styles.facts}>
              <dt>Data</dt>
              <dd>{formatDate(detail.date)}</dd>
              <dt>Valor</dt>
              <dd>{formatCurrency(detail.amount)}</dd>
              <dt>Fornecedor</dt>
              <dd>{detail.supplier_name ?? "não identificado"}</dd>
              <dt>Status</dt>
              <dd>
                <StatusBadge status={detail.status} />
              </dd>
              <dt>Conciliação</dt>
              <dd>
                {layerLabel(detail.layer)}
                {detail.layer !== null && ` · confiança ${formatPercent(detail.confidence)}`}
              </dd>
              <dt>Decidido por</dt>
              <dd>{detail.decided_by}</dd>
            </dl>
          </section>

          <section className={styles.section}>
            <h3>Por que chama atenção</h3>
            <p className={detail.high_risk ? styles.risk : undefined}>{detail.rank_label}</p>
            {detail.reasons.length > 0 ? (
              <ul className={styles.reasons}>
                {detail.reasons.map((reason, index) => (
                  // Reasons are plain strings and may repeat; their position is stable.
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            ) : (
              <p className={styles.muted}>Nenhum sinal fora do comum nesta transação.</p>
            )}
            <p className={styles.disclaimer}>
              O ranking compara esta transação com as demais; não é uma probabilidade de
              fraude. Ele indica o que merece investigação humana.
            </p>
          </section>

          <section className={styles.section}>
            <h3>Notas casadas</h3>
            {detail.invoices.length > 0 ? (
              <table className={styles.invoices}>
                <tbody>
                  {detail.invoices.map((invoice) => (
                    <tr key={invoice.invoice_id}>
                      <td className={styles.mono}>{invoice.invoice_id}</td>
                      <td>{formatDate(invoice.issue_date)}</td>
                      <td className={styles.num}>{formatCurrency(invoice.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className={styles.muted}>Nenhuma nota fiscal vinculada.</p>
            )}
          </section>

          {detail.can_review && (
            <section className={styles.section}>
              <h3>Revisão</h3>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={`${styles.button} ${styles.primary}`}
                  disabled={busy}
                  onClick={onApprove}
                >
                  Aprovar sugestão
                </button>
                <button
                  type="button"
                  className={`${styles.button} ${styles.danger}`}
                  disabled={busy}
                  onClick={onReject}
                >
                  Rejeitar
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </aside>
  );
}
