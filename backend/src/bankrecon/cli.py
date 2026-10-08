"""Command-line entry point.

Typical flow: ``generate`` -> ``reconcile`` -> ``detect`` -> ``evaluate``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from bankrecon.anomalies import detect_anomalies
from bankrecon.evaluation import evaluate_reconciliation, render_reconciliation
from bankrecon.evaluation.anomalies import evaluate_anomalies, render_anomalies
from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset
from bankrecon.reconciliation import reconcile
from bankrecon.results import (
    ResultsMissingError,
    load_matches,
    load_scores,
    save_matches,
    save_scores,
)

DEFAULT_DATA_DIR = Path("data")
EXIT_USAGE = 2


class CommandError(Exception):
    """Expected failure reported to the user without a traceback."""


def _load_dataset(directory: Path) -> Dataset:
    try:
        return Dataset.load(directory)
    except FileNotFoundError as error:
        raise CommandError(f"{error}. Rode 'bankrecon generate' antes.") from error


def _cmd_generate(args: argparse.Namespace) -> None:
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
        raise CommandError(str(error)) from error
    dataset.save(args.out)
    anomalies = (dataset.ground_truth["anomaly_type"] != "").sum()
    print(
        f"Gerados {len(dataset.suppliers)} fornecedores, {len(dataset.invoices)} notas, "
        f"{len(dataset.transactions)} transações ({anomalies} anomalias) em {args.out}"
    )


def _cmd_reconcile(args: argparse.Namespace) -> None:
    dataset = _load_dataset(args.data)
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    path = save_matches(matches, args.data)
    counts = matches["status"].value_counts()
    summary = ", ".join(f"{count} {status}" for status, count in counts.items())
    print(f"Conciliação: {summary}. Resultado em {path}")


def _cmd_detect(args: argparse.Namespace) -> None:
    dataset = _load_dataset(args.data)
    matches = load_matches(args.data)
    if set(matches["transaction_id"]) != set(dataset.transactions["transaction_id"]):
        raise CommandError("a conciliação é de outros dados. Rode 'bankrecon reconcile' de novo.")
    scores = detect_anomalies(dataset.transactions, matches, dataset.suppliers)
    path = save_scores(scores, args.data)
    print(f"Anomalias: {int(scores['high_risk'].sum())} transações de alto risco. Em {path}")


def _cmd_evaluate(args: argparse.Namespace) -> None:
    dataset = _load_dataset(args.data)
    truth = dataset.ground_truth
    matches = load_matches(args.data)
    scores = load_scores(args.data)
    try:
        sections = [
            render_reconciliation(evaluate_reconciliation(matches, truth)),
            render_anomalies(evaluate_anomalies(scores, truth)),
        ]
    except ValueError as error:
        raise CommandError(f"{error}. Rode o pipeline de novo para estes dados.") from error
    print("\n\n".join(sections))


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

    for name, handler, help_text in (
        ("reconcile", _cmd_reconcile, "concilia extrato e notas fiscais"),
        ("detect", _cmd_detect, "pontua transações incomuns e explica os motivos"),
        ("evaluate", _cmd_evaluate, "compara os resultados com o gabarito"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
        command.set_defaults(handler=handler)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except (CommandError, ResultsMissingError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_USAGE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
