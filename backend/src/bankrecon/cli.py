"""Command-line entry point.

Typical flow: ``generate`` -> ``reconcile`` -> ``detect`` -> ``evaluate``, then
``load-db`` to feed the API. ``demo`` runs everything for an empty database.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from bankrecon.anomalies import detect_anomalies
from bankrecon.db.load import ReviewsWouldBeLostError, is_loaded, load_results
from bankrecon.db.session import (
    DEFAULT_DATA_DIR,
    create_schema,
    database_url,
    make_engine,
    make_session_factory,
)
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

EXIT_USAGE = 2


class CommandError(Exception):
    """Expected failure reported to the user without a traceback."""


# -- pipeline steps (shared by the single-step commands and ``demo``) ----------------------


def _load_dataset(directory: Path) -> tuple[Dataset, str]:
    """The dataset and the fingerprint of what the pipeline reads from it."""
    try:
        dataset = Dataset.load(directory)
    except FileNotFoundError as error:
        raise CommandError(f"{error}. Rode 'bankrecon generate' antes.") from error
    return dataset, fingerprint(dataset.transactions, dataset.invoices, dataset.suppliers)


def _generate(config: GeneratorConfig, out: Path) -> None:
    try:
        dataset = generate_dataset(config)
    except ValueError as error:
        raise CommandError(str(error)) from error
    dataset.save(out)
    anomalies = (dataset.ground_truth["anomaly_type"] != "").sum()
    print(
        f"Gerados {len(dataset.suppliers)} fornecedores, {len(dataset.invoices)} notas, "
        f"{len(dataset.transactions)} transações ({anomalies} anomalias) em {out}"
    )


def _reconcile(dataset: Dataset, dataset_fp: str, data_dir: Path) -> pd.DataFrame:
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    path = save_matches(matches, data_dir, dataset_fp=dataset_fp)
    counts = matches["status"].value_counts()
    summary = ", ".join(f"{count} {status}" for status, count in counts.items())
    print(f"Conciliação: {summary}. Resultado em {path}")
    return matches


def _detect(
    dataset: Dataset, dataset_fp: str, matches: pd.DataFrame, data_dir: Path
) -> pd.DataFrame:
    try:
        scores = detect_anomalies(dataset.transactions, matches, dataset.suppliers)
    except ValueError as error:
        raise CommandError(str(error)) from error
    path = save_scores(scores, data_dir, dataset_fp=dataset_fp, matches_fp=fingerprint(matches))
    print(f"Anomalias: {int(scores['high_risk'].sum())} transações de alto risco. Em {path}")
    return scores


def _open_database(url: str) -> Engine:
    engine = make_engine(url)
    try:
        create_schema(engine)
    except SQLAlchemyError as error:
        engine.dispose()
        raise CommandError(f"não foi possível acessar o banco: {error}") from error
    return engine


def _write_database(
    engine: Engine,
    dataset: Dataset,
    matches: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    discard_reviews: bool,
) -> None:
    try:
        with make_session_factory(engine).begin() as session:
            load_results(
                session,
                suppliers=dataset.suppliers,
                invoices=dataset.invoices,
                transactions=dataset.transactions,
                matches=matches,
                scores=scores,
                discard_reviews=discard_reviews,
            )
    except ReviewsWouldBeLostError as error:
        raise CommandError(f"{error}; use --discard-reviews para substituí-las.") from error
    except SQLAlchemyError as error:
        raise CommandError(f"falha ao gravar no banco: {error}") from error
    print(f"Banco carregado com {len(dataset.transactions)} transações.")


# -- commands ------------------------------------------------------------------------------


def _cmd_generate(args: argparse.Namespace) -> None:
    try:
        config = GeneratorConfig(
            seed=args.seed,
            start=args.start,
            months=args.months,
            n_suppliers=args.suppliers,
            anomalies_per_type=args.anomalies_per_type,
        )
    except ValueError as error:
        raise CommandError(str(error)) from error
    _generate(config, args.out)


def _cmd_reconcile(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    _reconcile(dataset, dataset_fp, args.data)


def _cmd_detect(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    matches = load_matches(args.data, dataset_fp=dataset_fp)
    _detect(dataset, dataset_fp, matches, args.data)


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


def _cmd_load_db(args: argparse.Namespace) -> None:
    dataset, dataset_fp = _load_dataset(args.data)
    matches = load_matches(args.data, dataset_fp=dataset_fp)
    scores = load_scores(args.data, dataset_fp=dataset_fp, matches_fp=fingerprint(matches))
    engine = _open_database(args.database_url or database_url(args.data))
    try:
        _write_database(engine, dataset, matches, scores, discard_reviews=args.discard_reviews)
    finally:
        engine.dispose()


def _cmd_demo(args: argparse.Namespace) -> None:
    """Load the database for the demo when it is empty, generating data if needed.

    ``--force`` regenerates the data with ``--seed`` and replaces everything in the
    database, analyst reviews included.
    """
    engine = _open_database(args.database_url or database_url(args.data))
    try:
        with make_session_factory(engine)() as session:
            loaded = is_loaded(session)
        if loaded and not args.force:
            print("O banco já tem dados; nada a fazer (use --force para recarregar).")
            return
        if args.force or not (args.data / TRANSACTIONS_FILE).exists():
            _generate(GeneratorConfig(seed=args.seed), args.data)
        else:
            print(f"Usando os dados já gerados em {args.data}.")
        dataset, dataset_fp = _load_dataset(args.data)
        matches = _reconcile(dataset, dataset_fp, args.data)
        scores = _detect(dataset, dataset_fp, matches, args.data)
        _write_database(engine, dataset, matches, scores, discard_reviews=args.force)
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bankrecon", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    defaults = GeneratorConfig()

    generate = commands.add_parser("generate", help="gera dados sintéticos e o gabarito")
    generate.add_argument("--seed", type=int, default=defaults.seed)
    generate.add_argument("--start", type=date.fromisoformat, default=defaults.start)
    generate.add_argument("--months", type=int, default=defaults.months)
    generate.add_argument("--suppliers", type=int, default=defaults.n_suppliers)
    generate.add_argument("--anomalies-per-type", type=int, default=defaults.anomalies_per_type)
    generate.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR)
    generate.set_defaults(handler=_cmd_generate)

    def add_command(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR)
        command.set_defaults(handler=handler)
        return command

    add_command("reconcile", _cmd_reconcile, "concilia extrato e notas fiscais")
    add_command("detect", _cmd_detect, "pontua transações incomuns e explica os motivos")
    add_command("evaluate", _cmd_evaluate, "compara os resultados com o gabarito")

    database_help = "padrão: $DATABASE_URL ou um SQLite dentro de --data"
    load_db = add_command("load-db", _cmd_load_db, "grava dados e resultados no banco da API")
    load_db.add_argument("--database-url", help=database_help)
    load_db.add_argument(
        "--discard-reviews", action="store_true", help="substitui revisões feitas por analistas"
    )

    demo = add_command("demo", _cmd_demo, "gera, processa e carrega o banco se estiver vazio")
    demo.add_argument("--database-url", help=database_help)
    demo.add_argument("--seed", type=int, default=defaults.seed)
    demo.add_argument(
        "--force",
        action="store_true",
        help="regenera os dados com --seed e recarrega o banco, descartando revisões",
    )
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
