import logging
import os
import re
import uuid

from sqlalchemy import select, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Session, VaultEntry, Document, Message, DocumentChunk

logger = logging.getLogger(__name__)

# Domain-agnostic pseudonym pattern — matches any [UPPERCASE_TYPE_N] format.
# Covers all entity categories the vault can produce:
#   PII:     [PERSON_1], [EMAIL_2], [PHONE_NUMBER_3], [ADDRESS_4], [SSN_1],
#            [DATE_TIME_5], [DOB_1], [AGE_1], [IP_ADDRESS_1], [LOCATION_1],
#            [GPE_1], [US_PASSPORT_1], [US_DRIVER_LICENSE_1], [NATIONALITY_1]
#   PHI:     [MEDICAL_RECORD_1], [MRN_1], [HEALTH_PLAN_1], [DIAGNOSIS_1],
#            [MEDICATION_1], [BLOOD_TYPE_1], [PATIENT_ID_1]
#   PCI:     [CREDIT_CARD_1], [CVV_1], [BANK_ACCOUNT_1], [ROUTING_NUMBER_1],
#            [IBAN_1], [SWIFT_1]
#   Legal:   [CASE_ID_1], [JUDGE_1], [COURT_1], [PLAINTIFF_1], [DEFENDANT_1]
#   HR:      [EMPLOYEE_ID_1], [SALARY_1], [COMPENSATION_1]
_PSEUDONYM_RE = re.compile(r"\[([A-Z][A-Z0-9_]*_\d+)\]")


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

async def create_session(
    db: AsyncSession,
    title: str | None = None,
    domain: str | None = None,
) -> Session:
    """Create a new session with a random 32-byte salt."""
    session = Session(
        id=uuid.uuid4(),
        title=title,
        domain=domain,
        session_salt=os.urandom(32),
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> Session | None:
    """Retrieve a session by its primary key."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession) -> list[Session]:
    """List all sessions ordered by creation date descending."""
    result = await db.execute(select(Session).order_by(Session.created_at.desc()))
    return list(result.scalars().all())


async def update_session_title(
    db: AsyncSession, session_id: uuid.UUID, title: str
) -> Session | None:
    """Update a session's title."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        return None
    session.title = title
    await db.flush()
    return session


async def update_session_domain(
    db: AsyncSession, session_id: uuid.UUID, domain: str
) -> Session | None:
    """Update a session's domain."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        return None
    session.domain = domain
    await db.flush()
    return session


async def delete_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Delete a session; CASCADE handles child rows."""
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.flush()


# ---------------------------------------------------------------------------
# Vault Entry CRUD
# ---------------------------------------------------------------------------

async def create_vault_entry(
    db: AsyncSession,
    session_id: uuid.UUID,
    entity_type: str,
    pseudonym: str,
    encrypted_value: bytes,
    nonce: bytes,
    aliases: list | None = None,
) -> VaultEntry:
    """Create a new vault entry."""
    entry = VaultEntry(
        id=uuid.uuid4(),
        session_id=session_id,
        entity_type=entity_type,
        pseudonym=pseudonym,
        encrypted_value=encrypted_value,
        nonce=nonce,
        aliases=aliases or [],
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def get_vault_entries(
    db: AsyncSession, session_id: uuid.UUID
) -> list[VaultEntry]:
    """Return all vault entries for a given session."""
    result = await db.execute(
        select(VaultEntry).where(VaultEntry.session_id == session_id)
    )
    return list(result.scalars().all())


async def get_vault_entry_by_pseudonym(
    db: AsyncSession, session_id: uuid.UUID, pseudonym: str
) -> VaultEntry | None:
    """Look up a vault entry by session + pseudonym."""
    result = await db.execute(
        select(VaultEntry).where(
            VaultEntry.session_id == session_id,
            VaultEntry.pseudonym == pseudonym,
        )
    )
    return result.scalar_one_or_none()


async def update_vault_aliases(
    db: AsyncSession, entry_id: uuid.UUID, aliases: list
) -> VaultEntry | None:
    """Update the aliases JSON list on a vault entry."""
    result = await db.execute(
        select(VaultEntry).where(VaultEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.aliases = aliases
    await db.flush()
    await db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

async def create_document(
    db: AsyncSession,
    session_id: uuid.UUID,
    filename: str,
    content_type: str,
    raw_text: str | None = None,
) -> Document:
    """Create a new document record."""
    doc = Document(
        id=uuid.uuid4(),
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        raw_text=raw_text,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def update_document_processed(
    db: AsyncSession,
    doc_id: uuid.UUID,
    blinded_text: str,
    pii_count: int,
) -> Document | None:
    """Mark a document as processed, store blinded text, and NULL out raw_text."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        return None
    doc.blinded_text = blinded_text
    doc.pii_count = pii_count
    doc.processed = True
    doc.raw_text = None
    await db.flush()
    await db.refresh(doc)
    return doc


async def get_documents(db: AsyncSession, session_id: uuid.UUID) -> list[Document]:
    """List all documents for a session."""
    result = await db.execute(
        select(Document).where(Document.session_id == session_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------

async def create_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    lawyer_content: str,
    blinded_content: str,
    threats_detected: list | None = None,
    citations: list | None = None,
) -> Message:
    """Create a new chat message."""
    msg = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        lawyer_content=lawyer_content,
        blinded_content=blinded_content,
        threats_detected=threats_detected or [],
        citations=citations or [],
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    return msg


async def get_messages(db: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    """Return all messages for a session ordered by creation time ascending."""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Document Chunk CRUD + Hybrid Search
# ---------------------------------------------------------------------------

async def create_chunks_bulk(
    db: AsyncSession,
    chunks: list[dict],
) -> None:
    """Bulk insert document chunks with embeddings and tsvector.

    Each dict must have: session_id, document_id, chunk_index, content, embedding.
    The search_vector is computed via to_tsvector('english', content).
    """
    if not chunks:
        return

    for chunk_data in chunks:
        stmt = text("""
            INSERT INTO document_chunks
                (id, session_id, document_id, chunk_index, content, search_vector, embedding, token_count)
            VALUES
                (gen_random_uuid(), :session_id, :document_id, :chunk_index, :content,
                 to_tsvector('english', :content), :embedding, :token_count)
        """)
        await db.execute(
            stmt,
            {
                "session_id": chunk_data["session_id"],
                "document_id": chunk_data["document_id"],
                "chunk_index": chunk_data["chunk_index"],
                "content": chunk_data["content"],
                "embedding": str(chunk_data["embedding"]),
                "token_count": len(chunk_data["content"]) // 4,
            },
        )
    await db.flush()


async def get_chunks_by_session(
    db: AsyncSession, session_id: uuid.UUID
) -> list[DocumentChunk]:
    """Get all chunks for a session ordered by document and chunk index."""
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.session_id == session_id)
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def get_chunks_by_document(
    db: AsyncSession, document_id: uuid.UUID
) -> list[DocumentChunk]:
    """Get all chunks for a specific document."""
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def hybrid_search_chunks(
    db: AsyncSession,
    session_id: uuid.UUID,
    query_text: str,
    query_embedding: list[float],
    top_k: int = 10,
    rrf_k: int = 60,
) -> list[tuple[DocumentChunk, float]]:
    """Tri-signal hybrid search using Reciprocal Rank Fusion.

    Three retrieval signals merged via RRF:
      1. Pseudonym exact match — regex extracts [TYPE_N] pseudonyms from query,
         finds chunks containing those exact strings via LIKE. Handles identity
         lookups across all entity categories (PII, PHI, PCI, legal, HR).
      2. BM25 full-text — tsvector @@ plainto_tsquery for keyword overlap.
         Handles broad keyword queries ("show all addresses").
      3. Vector cosine — embedding <=> query_embedding for semantic similarity.
         Handles meaning-based queries ("which clients are at risk?").

    RRF score = sum of 1/(k + rank_i) across all signals where the chunk appears.
    """
    # --- Signal 1: Pseudonym exact match ---
    # Extract all pseudonyms from the query (any domain: PII, PHI, PCI, legal, HR)
    pseudonyms = _PSEUDONYM_RE.findall(query_text)
    pseudo_ranks: dict[uuid.UUID, int] = {}

    if pseudonyms:
        # Build LIKE conditions for each pseudonym found in the query
        like_conditions = []
        params: dict[str, str | uuid.UUID] = {"session_id": session_id}
        for i, pseudo in enumerate(pseudonyms):
            param_name = f"pseudo_{i}"
            # Search for the full bracketed form, e.g. [PERSON_927]
            like_conditions.append(f"content LIKE :{param_name}")
            params[param_name] = f"%[{pseudo}]%"

        where_clause = " OR ".join(like_conditions)
        # Count how many query pseudonyms each chunk contains — more matches = higher rank
        count_exprs = " + ".join(
            f"CASE WHEN content LIKE :{f'pseudo_{i}'} THEN 1 ELSE 0 END"
            for i in range(len(pseudonyms))
        )
        pseudo_stmt = text(f"""
            SELECT id, ({count_exprs}) AS match_count
            FROM document_chunks
            WHERE session_id = :session_id AND ({where_clause})
            ORDER BY match_count DESC
            LIMIT 50
        """)
        pseudo_result = await db.execute(pseudo_stmt, params)
        pseudo_rows = pseudo_result.fetchall()

        for rank, row in enumerate(pseudo_rows, 1):
            pseudo_ranks[row[0]] = rank

        logger.info(
            "Pseudonym search: found %d pseudonyms in query %s, matched %d chunks",
            len(pseudonyms),
            [f"[{p}]" for p in pseudonyms],
            len(pseudo_rows),
        )

    # --- Signal 2: BM25 full-text search ---
    bm25_ranks: dict[uuid.UUID, int] = {}
    bm25_stmt = text("""
        SELECT id, ts_rank(search_vector, plainto_tsquery('english', :query)) AS rank_score
        FROM document_chunks
        WHERE session_id = :session_id
          AND search_vector @@ plainto_tsquery('english', :query)
        ORDER BY rank_score DESC
        LIMIT 50
    """)
    bm25_result = await db.execute(
        bm25_stmt, {"session_id": session_id, "query": query_text}
    )
    for rank, row in enumerate(bm25_result.fetchall(), 1):
        bm25_ranks[row[0]] = rank

    # --- Signal 3: Vector cosine similarity ---
    vector_ranks: dict[uuid.UUID, int] = {}
    vector_stmt = text("""
        SELECT id, embedding <=> :query_embedding AS distance
        FROM document_chunks
        WHERE session_id = :session_id
        ORDER BY distance ASC
        LIMIT 50
    """)
    vector_result = await db.execute(
        vector_stmt, {"session_id": session_id, "query_embedding": str(query_embedding)}
    )
    for rank, row in enumerate(vector_result.fetchall(), 1):
        vector_ranks[row[0]] = rank

    # --- RRF merge across all three signals ---
    all_ids = set(pseudo_ranks.keys()) | set(bm25_ranks.keys()) | set(vector_ranks.keys())
    if not all_ids:
        return []

    max_rank = 51  # fallback rank for chunks absent from a signal
    rrf_scores: dict[uuid.UUID, float] = {}
    for chunk_id in all_ids:
        score = 0.0
        # Pseudonym exact match (weighted 2x — most reliable for identity lookups)
        if pseudo_ranks:
            p_rank = pseudo_ranks.get(chunk_id, max_rank)
            score += 2.0 / (rrf_k + p_rank)
        # BM25 keyword match
        score += 1.0 / (rrf_k + bm25_ranks.get(chunk_id, max_rank))
        # Vector semantic match
        score += 1.0 / (rrf_k + vector_ranks.get(chunk_id, max_rank))
        rrf_scores[chunk_id] = score

    # Sort by RRF score descending, take top-K
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]
    if not sorted_ids:
        return []

    # Fetch full chunk objects
    result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.id.in_(sorted_ids))
    )
    chunk_map = {chunk.id: chunk for chunk in result.scalars().all()}

    return [(chunk_map[cid], rrf_scores[cid]) for cid in sorted_ids if cid in chunk_map]
