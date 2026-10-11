"use client";

import Link from "next/link";
import { useState } from "react";

import { api, type ImportBatch, type ImportResult, type ProcessResult } from "@/lib/api";
import { formatDateTime, importSummary, plural } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import { UploadForm } from "./UploadForm";
import styles from "./imports.module.css";

type Busy = "extrato" | "notas" | "processar" | null;
type Outcome =
  | { type: "import"; result: ImportResult }
  | { type: "process"; result: ProcessResult }
  | { type: "error"; message: string };

const VISIBLE_ERRORS = 5;
const KIND_LABELS: Record<ImportBatch["kind"], string> = { extrato: "Extrato", notas: "Notas" };

function Errors({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null;
  const visible = errors.slice(0, VISIBLE_ERRORS);
  const hidden = errors.slice(VISIBLE_ERRORS);
  return (
    <div className={styles.warnings}>
      <strong>{plural(errors.length, "linha ou arquivo ignorado", "linhas ou arquivos ignorados")}:</strong>
      <ul>
        {visible.map((error, index) => (
          <li key={index}>{error}</li>
        ))}
      </ul>
      {hidden.length > 0 && (
        <details>
          <summary>ver mais {hidden.length}</summary>
          <ul>
            {hidden.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function processedLine(processed: ProcessResult): string {
  return (
    `Conciliação e ranking refeitos para ${plural(processed.transactions, "transação", "transações")}` +
    ` · ${processed.high_risk} de alto risco` +
    (processed.kept_reviews
      ? ` · ${plural(processed.kept_reviews, "revisão mantida", "revisões mantidas")}`
      : "")
  );
}

function OutcomeView({ outcome }: { outcome: Outcome }) {
  if (outcome.type === "error") {
    return (
      <div className={styles.error} role="alert">
        {outcome.message}
      </div>
    );
  }
  const processed = outcome.type === "import" ? outcome.result.processed : outcome.result;
  return (
    <div className={styles.success} role="status">
      {outcome.type === "import" && (
        <p>
          <strong>{outcome.result.filename}:</strong> {importSummary(outcome.result)}
        </p>
      )}
      <p>{processedLine(processed)}</p>
      {outcome.type === "import" && <Errors errors={outcome.result.errors} />}
      <Link href="/">Ver transações</Link>
    </div>
  );
}

export function ImportCenter() {
  const [busy, setBusy] = useState<Busy>(null);
  const [outcome, setOutcome] = useState<Outcome>();
  const [account, setAccount] = useState("conta");
  const [version, setVersion] = useState(0);
  const history = useResource(`imports:${version}`, (signal) => api.imports(signal));

  const run = async (kind: Exclude<Busy, null>, action: () => Promise<Outcome>) => {
    setBusy(kind);
    setOutcome(undefined);
    try {
      const result = await action();
      setOutcome(result);
      setVersion((v) => v + 1);
      return true;
    } catch (error) {
      setOutcome({
        type: "error",
        message: error instanceof Error ? error.message : "Erro inesperado ao importar",
      });
      return false;
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <h1>Importar dados</h1>
        <p>
          Envie o extrato do banco e as notas fiscais dos fornecedores. Cada importação refaz a
          conciliação e o ranking; arquivos ou linhas já importados são reconhecidos e não
          duplicam. Revisões feitas por analistas são mantidas.
        </p>
      </header>

      {outcome && <OutcomeView outcome={outcome} />}

      <div className={styles.grid}>
        <UploadForm
          title="Extrato bancário"
          accept=".ofx,.qfx,.csv,.txt"
          busy={busy !== null}
          submitLabel="Importar extrato"
          description={
            <>
              <p>
                <strong>OFX</strong> exportado pelo banco ou <strong>CSV</strong> com as colunas{" "}
                <code>data</code>, <code>descricao</code> e <code>valor</code> (negativo =
                pagamento). Só os pagamentos entram; créditos são ignorados.
              </p>
              <p>
                Modelos: <a href="/modelos/extrato.ofx" download>extrato.ofx</a> ·{" "}
                <a href="/modelos/extrato.csv" download>extrato.csv</a>
              </p>
            </>
          }
          onSubmit={([file]) =>
            run("extrato", async () => ({
              type: "import",
              result: await api.importStatement(file, account),
            }))
          }
        >
          <label className={styles.field}>
            Conta (identifica extratos CSV de contas diferentes)
            <input
              value={account}
              maxLength={64}
              onChange={(e) => setAccount(e.target.value)}
              disabled={busy !== null}
            />
          </label>
        </UploadForm>

        <UploadForm
          title="Notas fiscais"
          accept=".xml,.csv,.txt"
          multiple
          busy={busy !== null}
          submitLabel="Importar notas"
          description={
            <>
              <p>
                <strong>XML de NF-e</strong> (selecione vários de uma vez) ou <strong>CSV</strong>{" "}
                com <code>numero</code>, <code>cnpj</code>, <code>emissao</code> e{" "}
                <code>valor</code> (opcionais: <code>fornecedor</code>, <code>vencimento</code>,{" "}
                <code>parcela</code>). Cada parcela vira um título a pagar no seu vencimento, e os
                fornecedores são cadastrados pelo CNPJ.
              </p>
              <p>
                Modelos: <a href="/modelos/nfe.xml" download>nfe.xml</a> ·{" "}
                <a href="/modelos/notas.csv" download>notas.csv</a>
              </p>
            </>
          }
          onSubmit={(files) =>
            run("notas", async () => ({ type: "import", result: await api.importInvoices(files) }))
          }
        />
      </div>

      <section className={styles.history}>
        <div className={styles.historyHeader}>
          <h2>Histórico de importações</h2>
          <button
            type="button"
            className={styles.secondary}
            disabled={busy !== null}
            onClick={() =>
              run("processar", async () => ({ type: "process", result: await api.reprocess() }))
            }
          >
            {busy === "processar" ? "Reprocessando…" : "Reprocessar tudo"}
          </button>
        </div>
        {history.error && <p className={styles.error}>{history.error}</p>}
        {history.data && history.data.length === 0 && (
          <p className={styles.muted}>Nenhuma importação ainda.</p>
        )}
        {history.data && history.data.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Tipo</th>
                  <th>Arquivo</th>
                  <th>Resultado</th>
                  <th>Avisos</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((batch) => (
                  <tr key={batch.import_id}>
                    <td className={styles.nowrap}>{formatDateTime(batch.created_at)}</td>
                    <td>{KIND_LABELS[batch.kind]}</td>
                    <td className={styles.filename}>{batch.filename}</td>
                    <td>{importSummary(batch)}</td>
                    <td>
                      {batch.errors.length === 0 ? (
                        "—"
                      ) : (
                        <details>
                          <summary>{batch.errors.length}</summary>
                          <ul>
                            {batch.errors.map((error, index) => (
                              <li key={index}>{error}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
