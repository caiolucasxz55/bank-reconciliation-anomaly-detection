"""Upload endpoints: bank statements and invoices, followed by reprocessing.

The handlers are plain ``def``: FastAPI runs them in a worker thread, so the blocking
database and pandas work of an import never stalls the event loop. The request body size
is limited before parsing by ``UploadSizeLimit`` (see ``app.py``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bankrecon.api.deps import SessionDep
from bankrecon.api.schemas import ImportOut, ImportResultOut, ProcessOut
from bankrecon.db.importer import ImportSummary, import_invoices, import_statement
from bankrecon.db.models import ImportBatch
from bankrecon.db.processing import ProcessSummary, process
from bankrecon.ingest import MAX_FILE_BYTES, ParseError

MAX_FILES_PER_UPLOAD = 500
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
HISTORY_LIMIT = 50
# Plain numbers: the named constants changed between Starlette versions.
HTTP_413_TOO_LARGE = 413
HTTP_422_UNPROCESSABLE = 422
HTTP_503_UNAVAILABLE = 503

router = APIRouter(prefix="/api", tags=["importação"])


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(HTTP_422_UNPROCESSABLE, message)


def _read(upload: UploadFile, budget: int) -> tuple[str, bytes]:
    """Name and content of an uploaded file, within the per-file and per-upload limits."""
    if not upload.filename:
        raise _unprocessable("arquivo enviado sem nome; o formato vem da extensão")
    limit = min(MAX_FILE_BYTES, budget)
    content = upload.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            HTTP_413_TOO_LARGE,
            f"{upload.filename}: arquivo grande demais (máximo "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB por arquivo e "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB por envio)",
        )
    return upload.filename, content


def _process_and_commit(session: Session) -> ProcessSummary:
    """Reprocess everything and commit before the response is built."""
    try:
        summary = process(session)
        session.commit()
    except ValueError as error:
        raise _unprocessable(f"falha ao processar os dados: {error}") from error
    except SQLAlchemyError as error:
        raise HTTPException(
            HTTP_503_UNAVAILABLE, "o banco está ocupado ou indisponível; tente de novo"
        ) from error
    return summary


def _result(session: Session, summary: ImportSummary) -> ImportResultOut:
    processed = _process_and_commit(session)
    batch = session.get(ImportBatch, summary.import_id)
    return ImportResultOut(
        **ImportOut.of(batch).model_dump(),
        suppliers_created=summary.suppliers_created,
        processed=ProcessOut.of(processed),
    )


@router.post("/imports/statement", status_code=201)
def upload_statement(
    session: SessionDep,
    file: UploadFile,
    account: Annotated[str, Form(max_length=64)] = "conta",
) -> ImportResultOut:
    """Import a bank statement (OFX or CSV). Only payments (debits) are imported;
    lines already imported are recognized and skipped."""
    filename, content = _read(file, MAX_UPLOAD_BYTES)
    try:
        summary = import_statement(session, filename, content, account)
    except ParseError as error:
        raise _unprocessable(f"{filename}: {error}") from error
    return _result(session, summary)


@router.post("/imports/invoices", status_code=201)
def upload_invoices(session: SessionDep, files: list[UploadFile]) -> ImportResultOut:
    """Import invoices (NF-e XML, several at once, or CSV). Suppliers are registered from
    the CNPJ; invoices already imported are recognized and skipped."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise _unprocessable(f"envie no máximo {MAX_FILES_PER_UPLOAD} arquivos por vez")
    contents, budget = [], MAX_UPLOAD_BYTES
    for upload in files:
        filename, content = _read(upload, budget)
        budget -= len(content)
        contents.append((filename, content))
    try:
        summary = import_invoices(session, contents)
    except ParseError as error:
        raise _unprocessable(str(error)) from error
    return _result(session, summary)


@router.get("/imports")
def import_history(session: SessionDep) -> list[ImportOut]:
    """The most recent imports, newest first."""
    batches = session.scalars(
        select(ImportBatch).order_by(ImportBatch.import_id.desc()).limit(HISTORY_LIMIT)
    )
    return [ImportOut.of(batch) for batch in batches]


@router.post("/process")
def reprocess(session: SessionDep) -> ProcessOut:
    """Recompute reconciliation and ranking over everything in the database."""
    return ProcessOut.of(_process_and_commit(session))
