"""Upload endpoints: bank statements and invoices, followed by reprocessing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrecon.api.deps import SessionDep
from bankrecon.api.schemas import ImportOut, ImportResultOut, ProcessOut
from bankrecon.db.importer import ImportSummary, import_invoices, import_statement
from bankrecon.db.models import ImportBatch
from bankrecon.db.processing import process
from bankrecon.ingest import MAX_FILE_BYTES, ParseError

MAX_FILES_PER_UPLOAD = 500
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
HISTORY_LIMIT = 50

router = APIRouter(prefix="/api", tags=["importação"])


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


async def _read(upload: UploadFile, budget: int) -> bytes:
    """File content, refusing files bigger than the per-file or remaining upload budget."""
    limit = min(MAX_FILE_BYTES, budget)
    content = await upload.read(limit + 1)
    if len(content) > limit:
        mb = MAX_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"{upload.filename}: arquivo grande demais (máximo {mb} MB por arquivo, "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB por envio)",
        )
    return content


def _finish(session: Session, summary: ImportSummary) -> ImportResultOut:
    """Reprocess, commit (before responding) and describe the import."""
    try:
        processed = process(session)
    except ValueError as error:
        raise _unprocessable(f"falha ao processar os dados: {error}") from error
    session.commit()
    batch = session.get(ImportBatch, summary.import_id)
    return ImportResultOut(
        **ImportOut.of(batch).model_dump(),
        suppliers_created=summary.suppliers_created,
        processed=ProcessOut.of(processed),
    )


@router.post("/imports/statement", status_code=status.HTTP_201_CREATED)
async def upload_statement(
    session: SessionDep,
    file: UploadFile,
    account: Annotated[str, Form(max_length=64)] = "conta",
) -> ImportResultOut:
    """Import a bank statement (OFX or CSV). Only payments (debits) are imported;
    lines already imported are recognized and skipped."""
    content = await _read(file, MAX_UPLOAD_BYTES)
    try:
        summary = import_statement(session, file.filename or "extrato", content, account)
    except ParseError as error:
        raise _unprocessable(f"{file.filename}: {error}") from error
    return _finish(session, summary)


@router.post("/imports/invoices", status_code=status.HTTP_201_CREATED)
async def upload_invoices(session: SessionDep, files: list[UploadFile]) -> ImportResultOut:
    """Import invoices (NF-e XML, several at once, or CSV). Suppliers are registered from
    the CNPJ; invoices already imported are recognized and skipped."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise _unprocessable(f"envie no máximo {MAX_FILES_PER_UPLOAD} arquivos por vez")
    contents, budget = [], MAX_UPLOAD_BYTES
    for upload in files:
        content = await _read(upload, budget)
        budget -= len(content)
        contents.append((upload.filename or "notas", content))
    summary = import_invoices(session, contents)
    if summary.files_failed == summary.files:
        raise _unprocessable("nenhum arquivo pôde ser lido: " + "; ".join(summary.errors))
    return _finish(session, summary)


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
    try:
        processed = process(session)
    except ValueError as error:
        raise _unprocessable(f"falha ao processar os dados: {error}") from error
    session.commit()
    return ProcessOut.of(processed)
