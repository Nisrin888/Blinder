from __future__ import annotations

import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from blinder.encryption import derive_key
from blinder.pipeline import BlinderPipeline, HighSeverityThreatError
from blinder.vault import Vault, VaultEntry
from config import get_settings
from db import repositories
from llm.client import OllamaClient
from llm.context_builder import ContextBuilder
from schemas.api import MessageResponse

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_or_create_vault(db: AsyncSession, session_id: UUID) -> Vault:
    """Load a session from the DB, derive the encryption key, and build a Vault
    populated with all existing vault entries for that session."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    encryption_key = derive_key(settings.blinder_master_key, session.session_salt)
    vault = Vault(session_salt=session.session_salt, encryption_key=encryption_key)

    # Load existing vault entries from DB
    db_entries = await repositories.get_vault_entries(db, session_id)
    if db_entries:
        loaded_entries = []
        for entry in db_entries:
            real_value = vault.decrypt_value(entry.encrypted_value, entry.nonce)
            loaded_entries.append(
                VaultEntry(
                    entity_type=entry.entity_type,
                    pseudonym=entry.pseudonym,
                    real_value=real_value,
                    aliases=entry.aliases or [],
                )
            )
        vault.load_entries(loaded_entries)

    return vault


async def process_chat_message(
    db: AsyncSession,
    session_id: UUID,
    message: str,
) -> AsyncIterator[tuple[str, str]]:
    """Orchestrate the full chat flow: blind prompt, call LLM, restore response.

    Yields (event_type, data_json) tuples for SSE streaming.
    """
    # 1. Load vault for session
    vault = await get_or_create_vault(db, session_id)

    # 2. Create BlinderPipeline and process the user prompt
    pipeline = BlinderPipeline(vault)
    try:
        blinded_prompt, threats = await pipeline.process_prompt(message)
    except HighSeverityThreatError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "High severity threat detected",
                "threats": [
                    {
                        "threat_type": t.threat_type,
                        "description": t.description,
                        "severity": t.severity,
                    }
                    for t in exc.threats
                ],
            },
        )

    # 3. Save user message to DB
    threat_dicts = [
        {
            "threat_type": t.threat_type,
            "description": t.description,
            "severity": t.severity,
        }
        for t in threats
    ]
    user_msg = await repositories.create_message(
        db,
        session_id=session_id,
        role="user",
        lawyer_content=message,
        blinded_content=blinded_prompt,
        threats_detected=threat_dicts,
    )
    await db.commit()

    # 4. Load conversation history from DB
    messages = await repositories.get_messages(db, session_id)
    conversation_history = []
    for msg in messages:
        if msg.id == user_msg.id:
            # Skip the message we just added; it will be the new_prompt
            continue
        conversation_history.append({
            "role": msg.role,
            "content": msg.blinded_content,
        })

    # 5. Load blinded documents for context
    documents = await repositories.get_documents(db, session_id)
    blinded_documents = [
        doc.blinded_text for doc in documents if doc.blinded_text
    ]

    # 6. Build LLM context (include pseudonym legend so LLM uses exact pseudonyms)
    pseudonym_legend = [
        f"{entry.pseudonym} ({entry.entity_type})"
        for entry in vault.get_all_entries()
    ]
    ollama_client = OllamaClient()
    context_builder = ContextBuilder(ollama_client)
    llm_messages = await context_builder.build_messages(
        blinded_documents=blinded_documents,
        conversation_history=conversation_history,
        new_prompt=blinded_prompt,
        pseudonym_legend=pseudonym_legend,
    )

    # 7. Stream LLM response and collect the full blinded response
    full_blinded_response = ""
    chunks_buffer: list[str] = []

    async for chunk in ollama_client.chat(llm_messages, stream=True):
        full_blinded_response += chunk
        chunks_buffer.append(chunk)

    # 8. Restore pseudonyms in the full response
    restored_response = pipeline.restore_response(full_blinded_response)

    # 9. Save assistant message to DB
    assistant_msg = await repositories.create_message(
        db,
        session_id=session_id,
        role="assistant",
        lawyer_content=restored_response,
        blinded_content=full_blinded_response,
    )
    await db.commit()

    # 10. Save any new vault entries created during prompt processing
    existing_db_entries = await repositories.get_vault_entries(db, session_id)
    existing_pseudonyms = {e.pseudonym for e in existing_db_entries}
    for vault_entry in vault.get_all_entries():
        if vault_entry.pseudonym not in existing_pseudonyms:
            encrypted_value, nonce = vault.encrypt_value(vault_entry.real_value)
            await repositories.create_vault_entry(
                db,
                session_id=session_id,
                entity_type=vault_entry.entity_type,
                pseudonym=vault_entry.pseudonym,
                encrypted_value=encrypted_value,
                nonce=nonce,
                aliases=vault_entry.aliases,
            )
    await db.commit()

    # 11. Yield SSE events: chunks first, then done
    yield "start", "{}"
    for chunk in chunks_buffer:
        yield "chunk", chunk
    yield "done", f'{{"lawyer_content": {_json_escape(restored_response)}, "blinded_content": {_json_escape(full_blinded_response)}, "message_id": "{assistant_msg.id}"}}'


async def get_chat_history(
    db: AsyncSession, session_id: UUID
) -> list[MessageResponse]:
    """Retrieve the full chat history for a session."""
    session = await repositories.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    messages = await repositories.get_messages(db, session_id)
    return [MessageResponse.model_validate(msg) for msg in messages]


def _json_escape(s: str) -> str:
    """Escape a string for safe embedding in a JSON value."""
    import json
    return json.dumps(s)
