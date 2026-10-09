from dataclasses import dataclass

import pandas as pd
import pytest

from bankrecon.anomalies import detect_anomalies
from bankrecon.db.load import load_results
from bankrecon.db.session import create_schema, make_engine, make_session_factory
from bankrecon.generator import Dataset, GeneratorConfig, generate_dataset
from bankrecon.reconciliation import reconcile


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate_dataset(GeneratorConfig(seed=7))


@dataclass(frozen=True)
class PipelineOutput:
    dataset: Dataset
    matches: pd.DataFrame
    scores: pd.DataFrame


@pytest.fixture(scope="session")
def pipeline(dataset) -> PipelineOutput:
    matches = reconcile(dataset.transactions, dataset.invoices, dataset.suppliers)
    scores = detect_anomalies(dataset.transactions, matches, dataset.suppliers)
    return PipelineOutput(dataset, matches, scores)


@pytest.fixture
def session_factory(pipeline):
    """A fresh in-memory database loaded with the pipeline output, per test."""
    engine = make_engine("sqlite://")
    create_schema(engine)
    factory = make_session_factory(engine)
    with factory.begin() as session:
        load_results(
            session,
            suppliers=pipeline.dataset.suppliers,
            invoices=pipeline.dataset.invoices,
            transactions=pipeline.dataset.transactions,
            matches=pipeline.matches,
            scores=pipeline.scores,
        )
    yield factory
    engine.dispose()
