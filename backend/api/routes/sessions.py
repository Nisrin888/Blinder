from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db import repositories
from schemas.api import SessionCreate, SessionUpdate, SessionResponse, SessionList
from llm.prompts import SUPPORTED_DOMAINS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new session."""
    session = await repositories.create_session(
        db, title=body.title, domain=body.domain
    )
    return SessionResponse.model_validate(session)


@router.get("/", response_model=SessionList)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
):
    """List all sessions."""
    sessions = await repositories.list_sessions(db)
    return SessionList(
        sessions=[SessionResponse.model_validate(s) for s in sessions]
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a session by ID."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.model_validate(session)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: UUID,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a session's title and/or domain."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.domain is not None:
        if body.domain not in SUPPORTED_DOMAINS:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported domain. Choose from: {', '.join(SUPPORTED_DOMAINS)}",
            )
        await repositories.update_session_domain(db, session_id, body.domain)

    if body.title is not None:
        await repositories.update_session_title(db, session_id, body.title)

    updated = await repositories.get_session(db, session_id)
    return SessionResponse.model_validate(updated)


@router.delete("/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a session and all associated data."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await repositories.delete_session(db, session_id)
    return {"deleted": True}
