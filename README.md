# Blinder

**Privacy-preserving AI for legal professionals.** Blinder ensures no real PII ever reaches the LLM — names, SSNs, dates, and other sensitive data are automatically detected, pseudonymized, and encrypted before inference. After the AI responds, pseudonyms are mapped back to real values seamlessly.

> Your clients' data stays on your machine. Always.

## How It Works

![How It Works](resources/image-1.png)

The LLM only ever sees pseudonyms like `[PERSON_1]`, `[ORG_2]`, `[SSN_1]`. Even when using cloud models (GPT-4o, Claude), your clients' real identities never leave your machine.

## Features

- **Dual-Gate PII Detection** — Microsoft Presidio (SSNs, emails, phones, dates) + spaCy transformer NER (names, orgs, judges, courts)
- **AES-256-GCM Encrypted Vault** — Pseudonym mappings encrypted at rest, unique salt per session
- **Threat Sanitizer** — Blocks prompt injection, jailbreak attempts, unicode attacks, delimiter injection
- **Cross-Document Entity Resolution** — "Jane Smith" in a doc and "Jane" in your question resolve to the same pseudonym
- **Hybrid RAG** — BM25 full-text + vector embeddings (pgvector), Reciprocal Rank Fusion for retrieval
- **Tabular Query Engine** — Direct extraction from CSV/Excel uploads (sum, filter, lookup) without LLM hallucination
- **Multi-Model Support** — Ollama (local), OpenAI, Anthropic — switch models per message
- **Lawyer View / LLM View Toggle** — See exactly what the AI saw vs. the real content
- **Domain-Aware Prompting** — Auto-detects legal, finance, healthcare, HR domains
- **Citation Extraction** — Responses reference specific document chunks with relevance scores
- **Session Isolation** — Each conversation has its own encryption salt and vault — no cross-session leakage
- **Streaming Responses** — SSE-based real-time token streaming

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Python 3.11+](https://www.python.org/downloads/)
- [Node.js 18+](https://nodejs.org/)
- [Ollama](https://ollama.com/) (for local LLM inference)

### 1. Clone and configure

```bash
git clone https://github.com/Nisrin888/Blinder.git
cd blinder

# Create your environment file
cp .env.example backend/.env

# Generate a secure encryption key
# Linux/Mac:
sed -i "s/generate_with_openssl_rand_hex_32/$(openssl rand -hex 32)/" backend/.env
# Or manually edit backend/.env and replace the placeholder
```

### 2. Start PostgreSQL

```bash
docker-compose up -d
```

### 3. Set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Download the spaCy NER model (Gate B)
python -m spacy download en_core_web_trf

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn main:app --reload --port 8000
```

### 4. Set up the frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Start Ollama

```bash
ollama serve
ollama pull llama3
```

Open **http://localhost:5173** and start chatting.

## Using Cloud Models

Blinder supports OpenAI and Anthropic alongside local Ollama models. PII is pseudonymized before any data leaves your machine — cloud models only see `[PERSON_1]`, never real names.

1. Click **Model Settings** in the sidebar
2. Enter your API key (OpenAI or Anthropic)
3. Select the model from the dropdown above the chat input

Supported models: GPT-4o, GPT-4o Mini, GPT-4 Turbo, Claude Sonnet, Claude Haiku, Claude Opus, and any locally installed Ollama model.

## Architecture

```
frontend/          React (Vite) — dark theme, Gemini-style chat UI
backend/
  api/routes/      FastAPI endpoints (sessions, documents, chat, models)
  blinder/         The security engine
    pipeline.py      Orchestrator — ties all security layers together
    pii_detector.py  Dual-gate PII scanner (Presidio + spaCy)
    vault.py         Pseudonymization + AES-256-GCM encrypted mapping store
    threat_sanitizer.py  Unicode, injection, jailbreak detection
    entity_mapper.py     Cross-document entity resolution
    depseudonymizer.py   Reverse mapping on LLM output
    encryption.py        AES-256-GCM primitives
  llm/
    providers.py     LLM provider abstraction (Ollama, OpenAI, Anthropic)
    context_builder.py  Adaptive context assembly (stuff vs. RAG)
    domain_router.py    Domain detection for specialized prompting
    citation_extractor.py  Document citation scoring
  services/
    document_service.py  Document upload, text extraction, chunking, embedding
    embedding_service.py Local sentence-transformer embeddings (all-MiniLM-L6-v2)
    tabular_query.py     Structured data extraction from CSV/Excel
  db/
    models.py        SQLAlchemy models (sessions, vault, documents, messages, chunks)
    repositories.py  Data access layer + hybrid search (BM25 + vector)
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://blinder:localdev@localhost:5432/blinder_mvp` |
| `BLINDER_MASTER_KEY` | 256-bit hex key for vault encryption | (required) |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Default Ollama model | `llama3` |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | `http://localhost:5173` |
| `DEFAULT_PROVIDER` | Default LLM provider | `ollama` |
| `OPENAI_API_KEY` | OpenAI API key (optional) | |
| `ANTHROPIC_API_KEY` | Anthropic API key (optional) | |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Security Model

Blinder's security is not optional — it's the architecture:

1. **No PII reaches the LLM** — The blinder pipeline is the only path to inference. There is no bypass.
2. **Encrypted at rest** — Vault mappings use AES-256-GCM with per-session salts. Raw document text is deleted after processing.
3. **Session isolation** — Each session has a unique encryption salt. Vault entries from session A can never appear in session B.
4. **Threat detection** — All inputs (documents and prompts) pass through the threat sanitizer. Prompt injection, jailbreak attempts, and unicode attacks are blocked.
5. **No PII in logs** — All logging uses pseudonymized values only.
6. **Local-first** — With Ollama, nothing leaves your machine. With cloud models, only pseudonymized text is transmitted.
7. **Safe error handling** — Internal errors never expose file paths, DB strings, or stack traces to the client.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 (Vite) |
| Backend | Python 3.11+, FastAPI |
| Database | PostgreSQL 16 + pgvector |
| PII Detection | Microsoft Presidio + spaCy Transformers |
| Encryption | AES-256-GCM (cryptography library) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Ollama (local), OpenAI, Anthropic |
| ORM | SQLAlchemy 2.0 (async) + Alembic |

## License

This project is licensed under the **Server Side Public License v1 (SSPL)** — see the [LICENSE](LICENSE) file.

You are free to use, modify, and self-host Blinder. If you offer Blinder's functionality as a service to third parties, you must make the entire service source code available under the same license.
