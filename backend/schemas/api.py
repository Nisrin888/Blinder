from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- Session Schemas ---

class SessionCreate(BaseModel):
    title: str = Field("New Session", max_length=255)
    domain: str | None = Field(None, max_length=50)


class SessionUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    domain: str | None = Field(None, max_length=50)


class SessionResponse(BaseModel):
    id: UUID
    title: str
    domain: str | None = "general"
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SessionList(BaseModel):
    sessions: list[SessionResponse]


# --- Document Schemas ---

class DocumentResponse(BaseModel):
    id: UUID
    session_id: UUID
    filename: str
    content_type: str | None = None
    pii_count: int = 0
    processed: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreatResponse(BaseModel):
    threat_type: str
    description: str
    severity: str


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    pii_summary: dict[str, int] = {}  # entity_type -> count
    threats: list[ThreatResponse] = []


# --- Citation Schemas ---

class CitationResponse(BaseModel):
    document_id: str
    filename: str
    chunk_index: int = 0
    score: float
    snippet_blinded: str
    snippet_lawyer: str
    marker: int | None = None  # inline citation number [N]


# --- Chat Schemas ---

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=100_000)
    provider: str | None = Field(None, max_length=20)
    model: str | None = Field(None, max_length=100)


class MessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    lawyer_content: str
    blinded_content: str
    threats_detected: list[dict] = []
    citations: list[dict] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    messages: list[MessageResponse]


# --- Audit Log Schemas ---

class AuditLogResponse(BaseModel):
    id: UUID
    session_id: UUID
    event_type: str
    provider: str | None = None
    model: str | None = None
    payload_hash: str
    token_estimate: int | None = None
    metadata_: dict = Field(default_factory=dict, alias="metadata_")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class AuditSummaryResponse(BaseModel):
    session_id: UUID
    total_events: int
    events_by_type: dict[str, int]
    total_tokens: int
