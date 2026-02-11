from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db import repositories
from schemas.api import AuditLogResponse, AuditSummaryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{session_id}/audit",
    response_model=AuditSummaryResponse,
)
async def get_audit_summary(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return a summary of audit events for a session."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = await repositories.get_audit_logs(db, session_id)

    events_by_type: dict[str, int] = {}
    total_tokens = 0
    for log in logs:
        events_by_type[log.event_type] = events_by_type.get(log.event_type, 0) + 1
        if log.token_estimate:
            total_tokens += log.token_estimate

    return AuditSummaryResponse(
        session_id=session_id,
        total_events=len(logs),
        events_by_type=events_by_type,
        total_tokens=total_tokens,
    )


@router.get("/{session_id}/audit/export")
async def export_audit_report(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Export a full audit report as a downloadable JSON file.

    Includes all audit log entries (with blinded payloads and hashes),
    blinded message history, document metadata, and vault statistics.
    An auditor can verify hashes independently.
    """
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    audit_logs = await repositories.get_audit_logs(db, session_id)
    messages = await repositories.get_messages(db, session_id)
    documents = await repositories.get_documents(db, session_id)
    vault_entries = await repositories.get_vault_entries(db, session_id)

    # Vault stats — entity count by type, no real values exposed
    vault_stats: dict[str, int] = {}
    for entry in vault_entries:
        vault_stats[entry.entity_type] = vault_stats.get(entry.entity_type, 0) + 1

    report = {
        "report_type": "blinder_audit_export",
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session": {
            "id": str(session_id),
            "title": session.title,
            "domain": session.domain,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        },
        "audit_logs": [
            {
                "id": str(log.id),
                "event_type": log.event_type,
                "provider": log.provider,
                "model": log.model,
                "payload_blinded": log.payload_blinded,
                "payload_hash": log.payload_hash,
                "payload_hash_verified": (
                    hashlib.sha256(log.payload_blinded.encode()).hexdigest() == log.payload_hash
                ),
                "token_estimate": log.token_estimate,
                "metadata": log.metadata_,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in audit_logs
        ],
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "blinded_content": msg.blinded_content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
        "documents": [
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "content_type": doc.content_type,
                "pii_count": doc.pii_count,
                "processed": doc.processed,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in documents
        ],
        "vault_stats": {
            "total_entities": len(vault_entries),
            "entities_by_type": vault_stats,
        },
        "integrity_note": (
            "Each audit log entry includes a SHA-256 hash of its payload. "
            "Verify with: echo -n '<payload_blinded>' | sha256sum"
        ),
    }

    report_json = json.dumps(report, indent=2, ensure_ascii=False)
    filename = f"audit_{session_id}.json"

    return StreamingResponse(
        iter([report_json]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
