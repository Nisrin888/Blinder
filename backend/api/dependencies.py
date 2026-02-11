from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from llm.client import OllamaClient
from config import get_settings

settings = get_settings()


def get_ollama_client() -> OllamaClient:
    return OllamaClient()


# DB dependency is just get_db re-exported
