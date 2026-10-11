"use client";

import { type FormEvent, type ReactNode, useState } from "react";

import styles from "./imports.module.css";

interface Props {
  title: string;
  /** What the files may be, shown to the user. */
  description: ReactNode;
  accept: string;
  multiple?: boolean;
  /** Any operation is running: the form is disabled. */
  busy: boolean;
  /** This form's own import is running. */
  working: boolean;
  submitLabel: string;
  /** Optional extra fields (e.g. the account label), rendered above the button. */
  children?: ReactNode;
  onSubmit: (files: File[]) => Promise<boolean>;
}

/** A card with a file picker; the picker is cleared after a successful import. */
export function UploadForm({
  title,
  description,
  accept,
  multiple = false,
  busy,
  working,
  submitLabel,
  children,
  onSubmit,
}: Props) {
  const [files, setFiles] = useState<File[]>([]);
  // Changing the key remounts the <input type="file">, the only way to clear it.
  const [inputKey, setInputKey] = useState(0);
  const inputId = `upload-${title.replace(/\s+/g, "-").toLowerCase()}`;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (files.length === 0) return;
    if (await onSubmit(files)) {
      setFiles([]);
      setInputKey((k) => k + 1);
    }
  };

  return (
    <form className={styles.card} onSubmit={submit}>
      <h2>{title}</h2>
      <div className={styles.help}>{description}</div>
      <label className={styles.field} htmlFor={inputId}>
        {multiple ? "Arquivos" : "Arquivo"}
        <input
          key={inputKey}
          id={inputId}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={busy}
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
      </label>
      {files.length > 1 && <p className={styles.muted}>{files.length} arquivos selecionados</p>}
      {children}
      <button type="submit" className={styles.primary} disabled={busy || files.length === 0}>
        {working ? "Importando…" : submitLabel}
      </button>
    </form>
  );
}
