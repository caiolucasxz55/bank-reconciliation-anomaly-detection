"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from bankrecon.evaluation import evaluate_reconciliation, render_reconciliation
from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset
from bankrecon.reconciliation import reconcile

DEFAULT_DATA_DIR = Path("data")
RESULTS_DIR = "results"
MATCHES_FILE = "matches.csv"


def _cmd_generate(args: argparse.Namespace) -> int:
    try:
        config = GeneratorConfig(
            seed=args.seed,
            start=args.start,
            months=args.months,
            n_suppliers=args.suppliers,
            anomalies_per_type=args.anomalies_per_type,
        )
        dataset = generate_dataset(config)
    except ValueError as error:
        print(f"erro: {error}", file=sys.stderr)
        return 2
    dataset.save(args.out)
    anomalies = (dataset.ground_truth["anomaly_type"] != "").sum()
    print(
        f"Gerados {len(dataset.suppliers)} fornecedores, {len(dataset.invoices)} notas, "
        f"{len(dataset.transactions)} transações ({anomalies} anomalias) em {args.out}"
    )
    return 0


def _load_dataset(directory: Path) -> Dataset | None:
    try:
        return Dataset.load(directory)
    except FileNotFoundError as error:
        print(f"erro: {error}. Rode 'bankrecon generate' antes.", file=sys.stderr)
        return None


def _cmd_reconcile(args: argparse.Namespace) -> int:
    dataset = _load_dataset(args.data)
    if dataset is None:
        return 2
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    out = args.data / RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    matches.to_csv(out / MATCHES_FILE, index=False)
    counts = matches["status"].value_counts()
    summary = ", ".join(f"{count} {status}" for status, count in counts.items())
    print(f"Conciliação: {summary}. Resultado em {out / MATCHES_FILE}")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    dataset = _load_dataset(args.data)
    if dataset is None:
        return 2
    matches_path = args.data / RESULTS_DIR / MATCHES_FILE
    if not matches_path.exists():
        message = f"erro: {matches_path} não existe. Rode 'bankrecon reconcile' antes."
        print(message, file=sys.stderr)
        return 2
    matches = pd.read_csv(matches_path, keep_default_na=False, dtype={"invoice_ids": str})
    matches["layer"] = pd.to_numeric(matches["layer"]).astype("Int64")
    try:
        report = evaluate_reconciliation(matches, dataset.ground_truth)
    except ValueError as error:
        message = f"erro: {error}. Rode 'bankrecon reconcile' de novo para estes dados."
        print(message, file=sys.stderr)
        return 2
    print(render_reconciliation(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bankrecon", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="gera dados sintéticos e o gabarito")
    defaults = GeneratorConfig()
    generate.add_argument("--seed", type=int, default=defaults.seed)
    generate.add_argument("--start", type=date.fromisoformat, default=defaults.start)
    generate.add_argument("--months", type=int, default=defaults.months)
    generate.add_argument("--suppliers", type=int, default=defaults.n_suppliers)
    generate.add_argument("--anomalies-per-type", type=int, default=defaults.anomalies_per_type)
    generate.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR)
    generate.set_defaults(handler=_cmd_generate)

    reconcile_cmd = commands.add_parser("reconcile", help="concilia extrato e notas fiscais")
    reconcile_cmd.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
    reconcile_cmd.set_defaults(handler=_cmd_reconcile)

    evaluate = commands.add_parser("evaluate", help="compara os resultados com o gabarito")
    evaluate.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
    evaluate.set_defaults(handler=_cmd_evaluate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
