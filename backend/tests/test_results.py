import pandas as pd
import pytest

from bankrecon.results import (
    ResultsMissingError,
    StaleResultsError,
    fingerprint,
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
    save_matches(matches, tmp_path, dataset_fp="d1")
    pd.testing.assert_frame_equal(load_matches(tmp_path, dataset_fp="d1"), matches)


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
    save_scores(scores, tmp_path, dataset_fp="d1", matches_fp="m1")
    loaded = load_scores(tmp_path, dataset_fp="d1", matches_fp="m1")
    pd.testing.assert_frame_equal(loaded, scores)


def test_missing_results_name_the_step_to_run(tmp_path):
    with pytest.raises(ResultsMissingError, match="bankrecon reconcile") as info:
        load_matches(tmp_path, dataset_fp="d1")
    assert info.value.step == "reconcile"
    with pytest.raises(ResultsMissingError, match="bankrecon detect"):
        load_scores(tmp_path, dataset_fp="d1", matches_fp="m1")


def test_results_from_other_inputs_are_stale(tmp_path):
    frame = pd.DataFrame({"transaction_id": ["T1"]})
    save_matches(frame, tmp_path, dataset_fp="d1")
    with pytest.raises(StaleResultsError, match="bankrecon reconcile"):
        load_matches(tmp_path, dataset_fp="d2")

    save_scores(frame, tmp_path, dataset_fp="d1", matches_fp="m1")
    with pytest.raises(StaleResultsError, match="bankrecon detect"):
        load_scores(tmp_path, dataset_fp="d1", matches_fp="m2")


def test_results_without_metadata_are_stale(tmp_path):
    save_matches(pd.DataFrame({"transaction_id": ["T1"]}), tmp_path, dataset_fp="d1")
    (tmp_path / "results" / "matches.meta.json").unlink()
    with pytest.raises(StaleResultsError):
        load_matches(tmp_path, dataset_fp="d1")


def test_fingerprint_changes_with_content():
    a = pd.DataFrame({"x": [1, 2]})
    assert fingerprint(a) == fingerprint(a.copy())
    assert fingerprint(a) != fingerprint(pd.DataFrame({"x": [1, 3]}))
    assert fingerprint(a) != fingerprint(pd.DataFrame({"y": [1, 2]}))
