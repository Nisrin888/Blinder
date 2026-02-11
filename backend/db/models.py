import uuid

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    Integer,
    DateTime,
    LargeBinary,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from db.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    title = Column(String(255), nullable=True)
    domain = Column(String(50), nullable=True, default="general", server_default=text("'general'"))
    session_salt = Column(LargeBinary, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class VaultEntry(Base):
    __tablename__ = "vault_entries"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(50), nullable=False)
    pseudonym = Column(String(100), nullable=False)
    encrypted_value = Column(LargeBinary, nullable=False)
    nonce = Column(LargeBinary, nullable=False)
    aliases = Column(JSON, default=list, server_default=text("'[]'::jsonb"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("session_id", "pseudonym", name="uq_vault_session_pseudonym"),
        Index("idx_vault_session", "session_id"),
        Index("idx_vault_pseudonym", "session_id", "pseudonym"),
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename = Column(String(255), nullable=True)
    content_type = Column(String(100), nullable=True)
    raw_text = Column(Text, nullable=True)
    blinded_text = Column(Text, nullable=True)
    pii_count = Column(Integer, default=0, server_default=text("0"))
    processed = Column(Boolean, default=False, server_default=text("false"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_documents_session", "session_id"),)


class Message(Base):
    __tablename__ = "messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    lawyer_content = Column(Text, nullable=False)
    blinded_content = Column(Text, nullable=False)
    threats_detected = Column(JSON, default=list, server_default=text("'[]'::jsonb"))
    citations = Column(JSON, default=list, server_default=text("'[]'::jsonb"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_messages_session", "session_id", "created_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(50), nullable=False)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    payload_blinded = Column(Text, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    token_estimate = Column(Integer, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_audit_session_created", "session_id", "created_at"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    search_vector = Column(TSVECTOR)
    embedding = Column(Vector(384))
    token_count = Column(Integer, default=0, server_default=text("0"))
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_chunks_session", "session_id"),
        Index("idx_chunks_document", "document_id"),
        Index("idx_chunks_search", "search_vector", postgresql_using="gin"),
        Index(
            "idx_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
