from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from db.database import get_db, async_session
from db import repositories
from schemas.api import ChatRequest, ChatHistoryResponse, MessageResponse
from services import chat_service
from blinder.encryption import derive_key
from blinder.pipeline import BlinderPipeline, HighSeverityThreatError
from blinder.vault import Vault, VaultEntry
from llm.client import get_llm_client
from llm.context_builder import ContextBuilder, SourceMeta
from llm.citation_extractor import CitationExtractor, DocumentChunk
from llm.domain_router import detect_domain
from config import get_settings
from services.embedding_service import EmbeddingService
from services.tabular_query import try_tabular_query

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


@router.post("/{session_id}/chat")
async def send_message(
    session_id: UUID,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a chat message and receive an SSE stream response.

    The SSE stream emits events:
    - {"type": "start"}
    - {"type": "chunk", "content": "..."}  (one per LLM token chunk)
    - {"type": "done", "lawyer_content": "...", "blinded_content": "...", "message_id": "..."}
    """
    # Verify the session exists before starting the stream
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    message = body.message
    req_provider = body.provider
    req_model = body.model

    async def event_generator():
        """SSE generator that runs with its own DB session."""
        # Get a fresh DB session inside the generator since SSE generators
        # run after the response starts and the original session may be closed
        async with async_session() as gen_db:
            try:
                # 1. Build vault for the session
                session_obj = await repositories.get_session(gen_db, session_id)
                encryption_key = derive_key(
                    settings.blinder_master_key, session_obj.session_salt
                )
                vault = Vault(
                    session_salt=session_obj.session_salt,
                    encryption_key=encryption_key,
                )

                # Load existing vault entries
                db_entries = await repositories.get_vault_entries(gen_db, session_id)
                if db_entries:
                    loaded_entries = []
                    for entry in db_entries:
                        real_value = vault.decrypt_value(
                            entry.encrypted_value, entry.nonce
                        )
                        loaded_entries.append(
                            VaultEntry(
                                entity_type=entry.entity_type,
                                pseudonym=entry.pseudonym,
                                real_value=real_value,
                                aliases=entry.aliases or [],
                            )
                        )
                    vault.load_entries(loaded_entries)

                # 2. Create pipeline and process prompt
                pipeline = BlinderPipeline(vault)
                try:
                    blinded_prompt, threats = await pipeline.process_prompt(message)
                except HighSeverityThreatError as exc:
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "type": "error",
                            "error": "High severity threat detected",
                            "threats": [
                                {
                                    "threat_type": t.threat_type,
                                    "description": t.description,
                                    "severity": t.severity,
                                }
                                for t in exc.threats
                            ],
                        }),
                    }
                    return

                # 3. Save user message
                threat_dicts = [
                    {
                        "threat_type": t.threat_type,
                        "description": t.description,
                        "severity": t.severity,
                    }
                    for t in threats
                ]
                user_msg = await repositories.create_message(
                    gen_db,
                    session_id=session_id,
                    role="user",
                    lawyer_content=message,
                    blinded_content=blinded_prompt,
                    threats_detected=threat_dicts,
                )
                await gen_db.commit()

                # 4. Load conversation history (excluding the message we just added)
                messages = await repositories.get_messages(gen_db, session_id)
                conversation_history = []
                for msg in messages:
                    if msg.id == user_msg.id:
                        continue
                    conversation_history.append({
                        "role": msg.role,
                        "content": msg.blinded_content,
                    })

                # 5. Load blinded documents (preserving metadata for citations)
                documents = await repositories.get_documents(gen_db, session_id)
                docs_with_text = [doc for doc in documents if doc.blinded_text]
                blinded_documents = [doc.blinded_text for doc in docs_with_text]
                doc_chunks = [
                    DocumentChunk(
                        document_id=str(doc.id),
                        filename=doc.filename,
                        chunk_index=0,
                        text=doc.blinded_text,
                    )
                    for doc in docs_with_text
                ]

                # Build numbered source metadata for inline citations
                source_metadata = [
                    SourceMeta(
                        index=i + 1,
                        filename=doc.filename,
                        document_id=str(doc.id),
                    )
                    for i, doc in enumerate(docs_with_text)
                ]

                # 6. Create LLM client (uses provider/model from request, or global default)
                llm_client = get_llm_client(provider=req_provider, model=req_model)
                logger.info(
                    "Using LLM provider=%s model=%s",
                    llm_client.provider_name, llm_client.model_name,
                )

                # Detect domain on first message, or use existing
                domain = session_obj.domain
                detected_domain = None
                if not domain and not conversation_history:
                    domain = await detect_domain(blinded_prompt, llm_client)
                    await repositories.update_session_domain(
                        gen_db, session_id, domain
                    )
                    await gen_db.commit()
                    detected_domain = domain
                domain = domain or "general"

                # 7. Build LLM context
                # Strategy: tabular extraction → hybrid RAG → context-stuffing
                context_builder = ContextBuilder(llm_client)
                retrieved_chunks = None
                rag_chunk_results = None  # track DB chunk objects for source metadata

                # Build doc_id → filename lookup for RAG metadata
                doc_filename_map = {str(doc.id): doc.filename for doc in docs_with_text}

                # 7a. Try structured tabular query first (fastest, most accurate)
                tabular_result = try_tabular_query(blinded_prompt, blinded_documents)
                if tabular_result and tabular_result.success:
                    # Hand the pre-extracted data to the LLM as context
                    retrieved_chunks = [tabular_result.context]
                    logger.info(
                        "Tabular query mode (%s): %s",
                        tabular_result.query_type,
                        tabular_result.details,
                    )
                else:
                    # 7b. Fall back to hybrid RAG for prose/semantic queries
                    context_window = await llm_client.get_context_window_size()
                    total_doc_tokens = sum(
                        context_builder._estimate_tokens(d) for d in blinded_documents
                    )
                    max_tokens = int(context_window * settings.context_window_threshold)

                    if total_doc_tokens > max_tokens * 0.6:
                        embedder = EmbeddingService()
                        query_embedding = embedder.embed(blinded_prompt)

                        # Adaptive top_k: budget chunks to fit within context window
                        history_tokens = sum(
                            context_builder._estimate_tokens(m.get("content", ""))
                            for m in conversation_history
                        )
                        prompt_tokens = context_builder._estimate_tokens(blinded_prompt)
                        overhead = 500 + history_tokens + prompt_tokens + 1000
                        chunk_budget_tokens = max(max_tokens - overhead, 1000)
                        adaptive_top_k = min(
                            settings.rag_top_k,
                            max(chunk_budget_tokens // 512, 3),
                        )

                        rag_chunk_results = await repositories.hybrid_search_chunks(
                            gen_db,
                            session_id,
                            blinded_prompt,
                            query_embedding,
                            top_k=adaptive_top_k,
                            rrf_k=settings.rrf_k,
                        )
                        retrieved_chunks = [chunk.content for chunk, score in rag_chunk_results]
                        logger.info(
                            "RAG mode: retrieved %d chunks (top_k=%d, budget=%d tokens, window=%d)",
                            len(retrieved_chunks), adaptive_top_k, chunk_budget_tokens, max_tokens,
                        )

                # Determine active source metadata + texts for citation extraction
                active_source_metadata = source_metadata
                active_source_texts = blinded_documents
                if retrieved_chunks is not None:
                    if rag_chunk_results is not None:
                        # RAG mode: build metadata from actual retrieved DB chunks
                        active_source_metadata = [
                            SourceMeta(
                                index=i + 1,
                                filename=doc_filename_map.get(str(chunk.document_id), f"chunk_{i+1}"),
                                document_id=str(chunk.document_id),
                            )
                            for i, (chunk, _score) in enumerate(rag_chunk_results)
                        ]
                    else:
                        # Tabular mode: keep doc-level source_metadata as-is
                        pass
                    active_source_texts = retrieved_chunks

                llm_messages = await context_builder.build_messages(
                    blinded_documents=blinded_documents,
                    conversation_history=conversation_history,
                    new_prompt=blinded_prompt,
                    domain=domain,
                    retrieved_chunks=retrieved_chunks,
                    source_metadata=active_source_metadata,
                )

                # 7c. Audit log — record the LLM request payload
                request_payload_json = json.dumps(llm_messages, ensure_ascii=False)
                request_hash = hashlib.sha256(request_payload_json.encode()).hexdigest()
                request_token_est = sum(
                    len(m.get("content", "")) // 4 for m in llm_messages
                )
                await repositories.create_audit_log(
                    gen_db,
                    session_id=session_id,
                    event_type="llm_request",
                    payload_blinded=request_payload_json,
                    payload_hash=request_hash,
                    provider=llm_client.provider_name,
                    model=llm_client.model_name,
                    token_estimate=request_token_est,
                    metadata_={"domain": domain},
                )
                await gen_db.commit()

                # 8. Yield start event
                yield {
                    "data": json.dumps({"type": "start"}),
                }

                # 9. Stream LLM response
                full_blinded_response = ""
                async for chunk in llm_client.chat(llm_messages, stream=True):
                    full_blinded_response += chunk
                    yield {
                        "data": json.dumps({"type": "chunk", "content": chunk}),
                    }

                # 10. Restore pseudonyms in the full response
                restored_response = pipeline.restore_response(full_blinded_response)

                # 11. Extract inline citations [N], fallback to BM25
                extractor = CitationExtractor(max_citations=5)
                source_meta_dicts = [
                    {"index": m.index, "filename": m.filename, "document_id": m.document_id}
                    for m in active_source_metadata
                ] if active_source_metadata else []

                citations = extractor.extract_inline(
                    full_blinded_response,
                    source_meta_dicts,
                    active_source_texts,
                ) if source_meta_dicts and active_source_texts else []

                # Fallback: if no inline citations found, use BM25 post-hoc
                if not citations and doc_chunks:
                    citations = extractor.extract(full_blinded_response, doc_chunks)

                citation_dicts = [
                    {
                        "document_id": c.document_id,
                        "filename": c.filename,
                        "chunk_index": c.chunk_index,
                        "score": c.score,
                        "snippet_blinded": c.snippet_blinded,
                        "snippet_lawyer": pipeline.restore_response(c.snippet_blinded),
                        "marker": c.marker,
                    }
                    for c in citations
                ]

                # 12. Save assistant message to DB
                assistant_msg = await repositories.create_message(
                    gen_db,
                    session_id=session_id,
                    role="assistant",
                    lawyer_content=restored_response,
                    blinded_content=full_blinded_response,
                    citations=citation_dicts,
                )
                await gen_db.commit()

                # 12b. Audit log — record the LLM response
                response_hash = hashlib.sha256(full_blinded_response.encode()).hexdigest()
                response_token_est = len(full_blinded_response) // 4
                await repositories.create_audit_log(
                    gen_db,
                    session_id=session_id,
                    event_type="llm_response",
                    payload_blinded=full_blinded_response,
                    payload_hash=response_hash,
                    provider=llm_client.provider_name,
                    model=llm_client.model_name,
                    token_estimate=response_token_est,
                    metadata_={"domain": domain},
                )
                await gen_db.commit()

                # 13. Save any new vault entries
                existing_db_entries = await repositories.get_vault_entries(
                    gen_db, session_id
                )
                existing_pseudonyms = {e.pseudonym for e in existing_db_entries}
                for vault_entry in vault.get_all_entries():
                    if vault_entry.pseudonym not in existing_pseudonyms:
                        encrypted_value, nonce = vault.encrypt_value(
                            vault_entry.real_value
                        )
                        await repositories.create_vault_entry(
                            gen_db,
                            session_id=session_id,
                            entity_type=vault_entry.entity_type,
                            pseudonym=vault_entry.pseudonym,
                            encrypted_value=encrypted_value,
                            nonce=nonce,
                            aliases=vault_entry.aliases,
                        )
                await gen_db.commit()

                # 14. Auto-generate session title after first message
                generated_title = None
                if not conversation_history:
                    try:
                        title_messages = [
                            {
                                "role": "system",
                                "content": (
                                    "Generate a brief title (3-6 words) for a conversation "
                                    "that starts with this message. Return ONLY the title, "
                                    "no quotes, no punctuation at the end."
                                ),
                            },
                            {"role": "user", "content": blinded_prompt},
                        ]
                        blinded_title = await llm_client.chat_sync(title_messages)
                        blinded_title = blinded_title.strip().strip('"').strip("'").rstrip(".")
                        generated_title = pipeline.restore_response(blinded_title)
                        await repositories.update_session_title(
                            gen_db, session_id, generated_title
                        )
                        await gen_db.commit()
                    except Exception:
                        logger.warning("Failed to generate session title", exc_info=True)

                # 15. Yield done event with final data including citations
                done_payload = {
                    "type": "done",
                    "lawyer_content": restored_response,
                    "blinded_content": full_blinded_response,
                    "message_id": str(assistant_msg.id),
                    "citations": citation_dicts,
                    "provider": llm_client.provider_name,
                    "model": llm_client.model_name,
                }
                if generated_title:
                    done_payload["title"] = generated_title
                if detected_domain:
                    done_payload["domain"] = detected_domain

                yield {
                    "data": json.dumps(done_payload),
                }

            except Exception as exc:
                logger.exception("Error in chat SSE stream")
                # Never expose raw exception details to the client —
                # internal errors can leak file paths, DB strings, etc.
                safe_error = "Something went wrong processing your message. Check server logs for details."
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code
                    if status == 401:
                        safe_error = "LLM provider authentication failed. Check your API key in Settings."
                    elif status == 429:
                        safe_error = "LLM provider rate limit exceeded. Please wait and try again."
                    elif status == 404:
                        safe_error = "LLM model not found. Check your model selection."
                    else:
                        safe_error = f"LLM provider returned an error (HTTP {status})."
                elif isinstance(exc, httpx.ConnectError):
                    safe_error = "Cannot connect to LLM provider. Is Ollama running?"
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "type": "error",
                        "error": safe_error,
                    }),
                }

    return EventSourceResponse(event_generator())


@router.get(
    "/{session_id}/chat/history",
    response_model=ChatHistoryResponse,
)
async def get_chat_history(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the full chat history for a session."""
    messages = await chat_service.get_chat_history(db, session_id)
    return ChatHistoryResponse(messages=messages)
