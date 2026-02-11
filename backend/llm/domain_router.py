"""Lightweight domain router.

Sends a single non-streaming LLM call to classify the user's first message
into one of the supported domains.  Falls back to ``"general"`` on any
ambiguity or error.
"""

from __future__ import annotations

import logging

from llm.providers import LLMProvider
from llm.prompts import SUPPORTED_DOMAINS

logger = logging.getLogger(__name__)

ROUTER_PROMPT = (
    "Classify the following user message into exactly ONE domain.\n"
    "Reply with ONLY the domain name, nothing else.\n"
    "Domains: legal, finance, healthcare, hr, general"
)


async def detect_domain(text: str, client: LLMProvider) -> str:
    """Ask the LLM to classify *text* into a supported domain.

    Returns one of the ``SUPPORTED_DOMAINS`` strings, defaulting to
    ``"general"`` when the model output is unrecognisable or an error occurs.
    """
    messages = [
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        result = await client.chat_sync(messages)
        domain = result.strip().lower().rstrip(".")
        if domain in SUPPORTED_DOMAINS:
            logger.info("Domain auto-detected: %s", domain)
            return domain
        logger.info("LLM returned unrecognised domain %r, falling back to 'general'", domain)
    except Exception:
        logger.warning("Domain detection failed, falling back to 'general'", exc_info=True)
    return "general"
