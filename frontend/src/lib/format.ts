import type { MatchStatus } from "./api";

const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 0 });

export function formatCurrency(value: number): string {
  return currency.format(value);
}

/** ISO date (YYYY-MM-DD) to dd/mm/aaaa without timezone shifts. */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

export function formatPercent(value: number): string {
  return percent.format(value);
}

export const STATUS_LABELS: Record<MatchStatus, string> = {
  conciliada: "Conciliada",
  sugerida: "Sugerida",
  divergente: "Divergente",
};

export const LAYER_LABELS: Record<number, string> = {
  1: "Camada 1 · exata",
  2: "Camada 2 · tolerante",
  3: "Camada 3 · várias notas",
};

export function layerLabel(layer: number | null): string {
  return layer === null ? "Sem nota correspondente" : (LAYER_LABELS[layer] ?? `Camada ${layer}`);
}

/** "1–25 de 608" */
export function pageRange(offset: number, count: number, total: number): string {
  if (total === 0) return "0 de 0";
  return `${offset + 1}–${offset + count} de ${total}`;
}
