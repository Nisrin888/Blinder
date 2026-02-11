# Contributing to Blinder

Thank you for your interest in contributing to Blinder. This guide covers the development setup and contribution process.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker and Docker Compose
- Ollama

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_trf

# Start PostgreSQL
docker-compose up -d

# Copy and configure environment
cp ../.env.example .env
# Edit .env — set BLINDER_MASTER_KEY to output of: openssl rand -hex 32

# Run migrations
alembic upgrade head

# Start dev server
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
cd backend
pytest tests/ -v
```

## Code Conventions

### Python (Backend)

- Python 3.11+ — use modern syntax (`match/case`, `X | Y` type unions)
- Type hints on all function signatures
- Pydantic v2 for data models
- Async by default — all route handlers, DB operations, and I/O
- SQLAlchemy 2.0 async style — `AsyncSession`, `select()`, no legacy `Query`
- `logging` module, never `print()`
- Import order: stdlib, third-party, local

### JavaScript (Frontend)

- Functional components only — no class components
- Named exports — no default exports (except page-level components)
- All API calls go through `services/api.js`

### Security (Non-Negotiable)

- No real PII in logs — use pseudonymized values only
- No raw exception details exposed to clients
- All vault entries encrypted with AES-256-GCM
- Threat sanitizer runs on ALL inputs (documents and prompts)
- Session isolation enforced — unique salts, FK constraints with CASCADE delete
- No secrets in code — all keys from environment variables

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Make your changes with clear, focused commits
3. Ensure all tests pass (`pytest tests/ -v`)
4. Ensure no real PII appears in test fixtures or logs
5. Open a PR with a clear description of what changed and why
6. PRs that touch the blinder engine require test coverage

## What to Work On

- Check the [Issues](../../issues) tab for open issues
- Security improvements are always welcome
- New PII entity types or language support
- Performance improvements to the blinder pipeline
- Documentation improvements

## License

By contributing to Blinder, you agree that your contributions will be licensed under the [Server Side Public License v1](LICENSE).
