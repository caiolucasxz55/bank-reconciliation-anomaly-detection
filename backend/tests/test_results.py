import pandas as pd
import pytest

from bankrecon.results import (
    ResultsMissingError,
    load_matches,
    load_scores,
    save_matches,
    save_scores,
)


def test_matches_round_trip(tmp_path):
    matches = pd.DataFrame(
        {
            "transaction_id": ["T1", "T2"],
            "status": ["conciliada", "divergente"],
            "layer": pd.array([1, None], dtype="Int64"),
            "confidence": [1.0, 0.0],
            "invoice_ids": ["NF1;NF2", ""],
            "supplier_id": ["S1", ""],
        }
    )
    save_matches(matches, tmp_path)
    pd.testing.assert_frame_equal(load_matches(tmp_path), matches)


def test_scores_round_trip(tmp_path):
    scores = pd.DataFrame(
        {
            "transaction_id": ["T1"],
            "score": [0.61],
            "rank": [1],
            "percentile": [1.0],
            "rank_label": ["entre as 1% mais incomuns"],
            "high_risk": [True],
            "reasons": [""],
        }
    )
    save_scores(scores, tmp_path)
    pd.testing.assert_frame_equal(load_scores(tmp_path), scores)


@pytest.mark.parametrize(("loader", "step"), [(load_matches, "reconcile"), (load_scores, "detect")])
def test_missing_results_name_the_step_to_run(tmp_path, loader, step):
    with pytest.raises(ResultsMissingError, match=f"bankrecon {step}") as info:
        loader(tmp_path)
    assert info.value.step == step
