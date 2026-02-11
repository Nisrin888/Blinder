from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from db import repositories
from schemas.api import DocumentResponse, DocumentUploadResponse, ThreatResponse
from services import document_service

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "text/plain",
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".tsv"}


@router.post(
    "/{session_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=201,
)
async def upload_document(
    session_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document, extract text, and process through the blinding pipeline."""
    # Verify the session exists
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate file extension
    filename = file.filename or "unnamed"
    ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read file content with size limit
    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(file_content) // (1024*1024)}MB). Maximum is {MAX_UPLOAD_BYTES // (1024*1024)}MB.",
        )

    if len(file_content) == 0:
        raise HTTPException(status_code=422, detail="Empty file uploaded.")

    # Determine content type
    content_type = file.content_type or "text/plain"

    # Process through blinding pipeline
    doc_response, pii_summary, threats = await document_service.process_document(
        db=db,
        session_id=session_id,
        filename=file.filename or "unnamed",
        content_type=content_type,
        file_content=file_content,
    )

    # Convert threat dicts to ThreatResponse models
    threat_responses = [
        ThreatResponse(
            threat_type=t["threat_type"],
            description=t["description"],
            severity=t["severity"],
        )
        for t in threats
    ]

    return DocumentUploadResponse(
        document=doc_response,
        pii_summary=pii_summary,
        threats=threat_responses,
    )


@router.get(
    "/{session_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all documents for a session."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    documents = await repositories.get_documents(db, session_id)
    return [DocumentResponse.model_validate(doc) for doc in documents]
