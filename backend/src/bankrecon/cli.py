"""Command-line entry point.

Typical flow: ``generate`` -> ``reconcile`` -> ``detect`` -> ``evaluate``, then
``load-db`` to feed the API. ``demo`` runs everything for an empty database.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from bankrecon.anomalies import detect_anomalies
from bankrecon.db.load import is_loaded, load_results
from bankrecon.db.session import create_schema, make_engine, make_session_factory
from bankrecon.evaluation import evaluate_reconciliation, render_reconciliation
from bankrecon.evaluation.anomalies import evaluate_anomalies, render_anomalies
from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset
from bankrecon.generator.dataset import TRANSACTIONS_FILE
from bankrecon.reconciliation import reconcile
from bankrecon.results import (
    ResultsMissingError,
    StaleResultsError,
    fingerprint,
    load_matches,
    load_scores,
    save_matches,
    save_scores,
)

DEFAULT_DATA_DIR = Path("data")
EXIT_USAGE = 2
SQLITE_FILE = "bankrecon.db"


class CommandError(Exception):
    """Expected failure reported to the user without a traceback."""


def _load_dataset(directory: Path) -> tuple[Dataset, str]:
    """The dataset and the fingerprint of what the pipeline reads from it."""
    try:
        dataset = Dataset.load(directory)
    except FileNotFoundError as error:
        raise CommandError(f"{error}. Rode 'bankrecon generate' antes.") from error
    return dataset, fingerprint(dataset.transactions, dataset.invoices, dataset.suppliers)


def _generate(config: GeneratorConfig, out: Path) -> None:
    dataset = generate_dataset(config)
    dataset.save(out)
    anomalies = (dataset.ground_truth["anomaly_type"] != "").sum()
    print(
        f"Gerados {len(dataset.suppliers)} fornecedores, {len(dataset.invoices)} notas, "
        f"{len(dataset.transactions)} transações ({anomalies} anomalias) em {out}"
    )


def _cmd_generate(args: argparse.Namespace) -> None:
    try:
        config = GeneratorConfig(
            seed=args.seed,
            start=args.start,
            months=args.months,
            n_suppliers=args.suppliers,
            anomalies_per_type=args.anomalies_per_type,
        )
        _generate(config, args.out)
    except ValueError as error:
        raise CommandError(str(error)) from error


def _cmd_reconcile(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    path = save_matches(matches, args.data, dataset_fp=dataset_fp)
    counts = matches["status"].value_counts()
    summary = ", ".join(f"{count} {status}" for status, count in counts.items())
    print(f"Conciliação: {summary}. Resultado em {path}")


def _cmd_detect(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    matches = load_matches(args.data, dataset_fp=dataset_fp)
    try:
        scores = detect_anomalies(dataset.transactions, matches, dataset.suppliers)
    except ValueError as error:
        raise CommandError(str(error)) from error
    path = save_scores(scores, args.data, dataset_fp=dataset_fp, matches_fp=fingerprint(matches))
    print(f"Anomalias: {int(scores['high_risk'].sum())} transações de alto risco. Em {path}")


def _cmd_evaluate(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    truth = dataset.ground_truth
    matches = load_matches(args.data, dataset_fp=dataset_fp)
    scores = load_scores(args.data, dataset_fp=dataset_fp, matches_fp=fingerprint(matches))
    sections = [
        render_reconciliation(evaluate_reconciliation(matches, truth)),
        render_anomalies(evaluate_anomalies(scores, truth)),
    ]
    print("\n\n".join(sections))


def _database_url(args: argparse.Namespace) -> str:
    """--database-url, else $DATABASE_URL, else a SQLite file inside the data directory."""
    default = f"sqlite:///{(args.data / SQLITE_FILE).as_posix()}"
    return args.database_url or os.environ.get("DATABASE_URL") or default


def _open_database(args: argparse.Namespace) -> Engine:
    args.data.mkdir(parents=True, exist_ok=True)
    engine = make_engine(_database_url(args))
    try:
        create_schema(engine)
    except OperationalError as error:
        engine.dispose()
        raise CommandError(f"não foi possível acessar o banco: {error.orig}") from error
    return engine


def _cmd_load_db(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    matches = load_matches(args.data, dataset_fp=dataset_fp)
    scores = load_scores(args.data, dataset_fp=dataset_fp, matches_fp=fingerprint(matches))
    engine = _open_database(args)
    try:
        with make_session_factory(engine).begin() as session:
            load_results(
                session,
                suppliers=dataset.suppliers,
                invoices=dataset.invoices,
                transactions=dataset.transactions,
                matches=matches,
                scores=scores,
            )
    finally:
        engine.dispose()
    print(f"Banco carregado com {len(dataset.transactions)} transações.")


def _cmd_demo(args: argparse.Namespace) -> None:
    """Generate (if needed), run the pipeline and load the database, unless already loaded."""
    engine = _open_database(args)
    try:
        with make_session_factory(engine)() as session:
            loaded = is_loaded(session)
    finally:
        engine.dispose()
    if loaded and not args.force:
        print("O banco já tem dados; nada a fazer (use --force para recarregar).")
        return
    if not (args.data / TRANSACTIONS_FILE).exists():
        _generate(GeneratorConfig(seed=args.seed), args.data)
    _cmd_reconcile(args)
    _cmd_detect(args)
    _cmd_load_db(args)


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

    for name, handler, help_text in (
        ("load-db", _cmd_load_db, "grava dados e resultados no banco usado pela API"),
        ("demo", _cmd_demo, "gera, processa e carrega o banco se ele estiver vazio"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
        command.add_argument("--database-url", default=None, help="padrão: $DATABASE_URL")
        if name == "demo":
            command.add_argument("--seed", type=int, default=defaults.seed)
            command.add_argument("--force", action="store_true", help="recarrega mesmo com dados")
        command.set_defaults(handler=handler)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.handler(args)
    except (CommandError, ResultsMissingError, StaleResultsError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_USAGE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
