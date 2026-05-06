# Demo Studio

Interactive dataset builder for Tableau. Chat with an AI agent to reshape Postgres-backed data using natural language — the agent writes SQL or Python, executes in a transaction, and keeps your Tableau views in sync.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in Bedrock token + Postgres creds
uvicorn app:app --reload --port 3777
```

Open <http://localhost:3777>. First boot seeds a starter dataset automatically.

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** — How to use the app, chat workflow, Tableau extensions, datasets.
- **[Setup Guide](docs/SETUP_GUIDE.md)** — Installation, environment variables, architecture, API reference, manifest format.

## Features

- Natural language data mutations (SQL and Python) with transactional safety
- Automatic snapshots and one-click rollback
- Multiple dataset sources: built-in seeds, CSV manifest upload, or build your own
- Tableau Live Refresh extension (auto-refreshes dashboards on data change)
- Tableau Live Chat extension (embedded chat inside a dashboard)
- Self-improving error handling: auto-distills failures into prompt guidance + RAG playbooks
