from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bankrecon.api import imports, limits
from bankrecon.api.app import create_app
from bankrecon.db.session import create_schema, make_engine, make_session_factory

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


def _file(name: str) -> tuple[str, bytes]:
    return (name, (FIXTURES / name).read_bytes())


@pytest.fixture
def client():
    """An empty database, as a company starts with."""
    engine = make_engine("sqlite://")
    create_schema(engine)
    with TestClient(create_app(make_session_factory(engine))) as test_client:
        yield test_client
    engine.dispose()


def _upload_invoices(client, *names):
    return client.post("/api/imports/invoices", files=[("files", _file(n)) for n in names])


def test_starts_empty(client):
    assert client.get("/api/summary").json()["total"] == 0
    assert client.get("/api/transactions").json()["items"] == []
    assert client.get("/api/imports").json() == []


def test_upload_invoices_then_statement(client):
    response = _upload_invoices(client, "nfe_parcelada.xml", "nfe_a_vista.xml")
    assert response.status_code == 201
    body = response.json()
    assert (body["kind"], body["imported"], body["suppliers_created"]) == ("notas", 3, 2)
    assert body["processed"]["transactions"] == 0

    response = client.post(
        "/api/imports/statement", files={"file": _file("extrato_v1.ofx")}, data={"account": "cc"}
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["imported"], body["skipped"], body["duplicates"]) == (3, 1, 0)
    assert body["processed"]["transactions"] == 3

    summary = client.get("/api/summary").json()
    assert summary["total"] == 3
    items = client.get("/api/transactions", params={"sort": "data"}).json()["items"]
    norte = next(i for i in items if "NORTE" in i["description"])
    assert (norte["status"], norte["supplier_name"]) == ("conciliada", "Norte Transportes ME")


def test_reupload_is_recognized(client):
    for _ in range(2):
        response = client.post("/api/imports/statement", files={"file": _file("extrato_v1.ofx")})
    assert (response.json()["imported"], response.json()["duplicates"]) == (0, 3)
    assert client.get("/api/summary").json()["total"] == 3


def test_history_lists_imports_newest_first(client):
    _upload_invoices(client, "nfe_a_vista.xml")
    client.post("/api/imports/statement", files={"file": _file("extrato.csv")})
    history = client.get("/api/imports").json()
    assert [h["kind"] for h in history] == ["extrato", "notas"]
    assert history[0]["errors"] == ["linha 7: valor inválido: 'abc'"]


def test_unreadable_statement_is_rejected_and_nothing_is_stored(client):
    response = client.post("/api/imports/statement", files={"file": ("extrato.pdf", b"%PDF")})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("extrato.pdf: formato não suportado")
    assert client.get("/api/imports").json() == []


def test_invoices_that_cannot_be_read_are_rejected(client):
    response = _upload_invoices(client, "nfe_cancelada.xml")
    assert response.status_code == 422
    assert "nenhum arquivo pôde ser lido" in response.json()["detail"]
    assert client.get("/api/imports").json() == []


def test_partially_readable_invoices_import_with_errors(client):
    response = _upload_invoices(client, "nfe_a_vista.xml", "nfe_cancelada.xml")
    assert response.status_code == 201
    assert response.json()["imported"] == 1
    assert "nfe_cancelada.xml" in response.json()["errors"][0]


def test_files_too_large_are_rejected(client, monkeypatch):
    monkeypatch.setattr(imports, "MAX_FILE_BYTES", 10)
    response = client.post("/api/imports/statement", files={"file": ("extrato.csv", b"x" * 11)})
    assert response.status_code == 413
    assert "grande demais" in response.json()["detail"]


def test_too_many_files_are_rejected(client, monkeypatch):
    monkeypatch.setattr(imports, "MAX_FILES_PER_UPLOAD", 1)
    response = _upload_invoices(client, "nfe_a_vista.xml", "nfe_parcelada.xml")
    assert response.status_code == 422
    assert "no máximo 1" in response.json()["detail"]


def test_reprocess_endpoint(client):
    client.post("/api/imports/statement", files={"file": _file("extrato_v1.ofx")})
    assert client.post("/api/process").json() == {
        "transactions": 3,
        "kept_reviews": 0,
        "high_risk": 1,
    }


def test_invoices_arriving_after_the_statement_reconcile_old_payments(client):
    client.post("/api/imports/statement", files={"file": _file("extrato_v1.ofx")})

    def norte():
        items = client.get("/api/transactions").json()["items"]
        return next(i for i in items if "NORTE" in i["description"])

    assert norte()["status"] == "divergente"
    _upload_invoices(client, "nfe_a_vista.xml")
    assert norte()["status"] == "conciliada"


def test_oversized_request_is_rejected_before_parsing(client, monkeypatch):
    monkeypatch.setattr(limits, "MULTIPART_OVERHEAD_BYTES", 0)
    app = create_app(client.app.state.session_factory)
    app.user_middleware.clear()
    app.add_middleware(limits.UploadSizeLimit, max_bytes=100, path_prefix="/api/imports")
    with TestClient(app) as small:
        response = small.post("/api/imports/statement", files={"file": ("a.csv", b"x" * 500)})
    assert response.status_code == 413
    assert "envio grande demais" in response.json()["detail"]


def test_upload_without_content_length_is_refused(client):
    def chunks():
        yield b"--b\r\n"

    response = client.post(
        "/api/imports/statement",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code == 411


def test_file_without_name_is_rejected(client):
    response = client.post("/api/imports/statement", files={"file": ("", b"data;valor\n")})
    assert response.status_code == 422


def test_statement_with_no_readable_line_is_rejected(client):
    content = b"data;descricao;valor\n01/01/2025;X;abc\n"
    response = client.post("/api/imports/statement", files={"file": ("e.csv", content)})
    assert response.status_code == 422
    assert "nenhuma linha pôde ser lida" in response.json()["detail"]
    assert client.get("/api/imports").json() == []
