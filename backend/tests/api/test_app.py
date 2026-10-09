import pytest
from fastapi.testclient import TestClient

from bankrecon.api.app import create_app


@pytest.fixture
def client(session_factory):
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


def _first_with_status(pipeline, status):
    return pipeline.matches.loc[pipeline.matches["status"] == status, "transaction_id"].iloc[0]


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_summary(client, pipeline):
    body = client.get("/api/summary").json()
    counts = pipeline.matches["status"].value_counts()
    assert body == {
        "total": len(pipeline.matches),
        "conciliadas": int(counts["conciliada"]),
        "sugeridas": int(counts["sugerida"]),
        "divergentes": int(counts["divergente"]),
        "alto_risco": int(pipeline.scores["high_risk"].sum()),
    }


def test_list_defaults_to_risk_order(client, pipeline):
    body = client.get("/api/transactions", params={"limit": 5}).json()
    assert body["total"] == len(pipeline.matches)
    assert body["limit"] == 5
    assert [item["rank"] for item in body["items"]] == [1, 2, 3, 4, 5]
    first = body["items"][0]
    assert first["top_reason"]
    assert first["rank_label"].startswith("entre as")
    assert set(first) >= {"transaction_id", "date", "amount", "status", "supplier_name", "score"}


def test_list_filters(client, pipeline):
    body = client.get("/api/transactions", params={"status": "divergente", "limit": 200}).json()
    assert body["total"] == (pipeline.matches["status"] == "divergente").sum()
    assert {item["status"] for item in body["items"]} == {"divergente"}

    high = client.get("/api/transactions", params={"high_risk": "true", "limit": 200}).json()
    assert all(item["high_risk"] for item in high["items"])

    top = client.get("/api/transactions", params={"max_percentile": 0.1}).json()
    assert top["total"] == (pipeline.scores["percentile"] <= 0.1).sum()


@pytest.mark.parametrize(
    "params",
    [
        {"status": "aprovada"},
        {"limit": 0},
        {"limit": 1000},
        {"offset": -1},
        {"max_percentile": 0},
        {"max_percentile": 2},
        {"sort": "nome"},
        {"unknown": "1"},
    ],
)
def test_list_rejects_invalid_parameters(client, params):
    assert client.get("/api/transactions", params=params).status_code == 422


def test_detail(client, pipeline):
    tx_id = _first_with_status(pipeline, "conciliada")
    body = client.get(f"/api/transactions/{tx_id}").json()
    assert body["transaction_id"] == tx_id
    assert body["invoices"]
    assert body["can_review"] is False
    assert body["decided_by"] == "sistema"
    assert isinstance(body["reasons"], list)


def test_detail_not_found(client):
    response = client.get("/api/transactions/TX99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "transação não encontrada"


def test_approve_then_summary_changes(client, pipeline):
    tx_id = _first_with_status(pipeline, "sugerida")
    before = client.get("/api/summary").json()

    response = client.post(f"/api/transactions/{tx_id}/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "conciliada"
    assert body["decided_by"] == "analista"
    assert body["can_review"] is False

    after = client.get("/api/summary").json()
    assert after["sugeridas"] == before["sugeridas"] - 1
    assert after["conciliadas"] == before["conciliadas"] + 1


def test_reject_releases_invoices(client, pipeline):
    tx_id = _first_with_status(pipeline, "sugerida")
    body = client.post(f"/api/transactions/{tx_id}/reject").json()
    assert body["status"] == "divergente"
    assert body["invoices"] == []
    assert body["layer"] is None


def test_reviewing_twice_is_a_conflict(client, pipeline):
    tx_id = _first_with_status(pipeline, "sugerida")
    assert client.post(f"/api/transactions/{tx_id}/approve").status_code == 200
    response = client.post(f"/api/transactions/{tx_id}/reject")
    assert response.status_code == 409
    assert "conciliada" in response.json()["detail"]


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_review_unknown_transaction(client, action):
    assert client.post(f"/api/transactions/TX99999/{action}").status_code == 404


def test_cors_allows_the_web_origin(client):
    response = client.get("/api/summary", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
