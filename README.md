# Demo Studio

Interactive dataset builder for Tableau. Chat with an AI agent to reshape Postgres-backed data using natural language — the agent writes SQL or Python, executes in a transaction, and keeps your Tableau views in sync.

## Quick start

**Windows:**
```
install.bat
```

**Mac/Linux:**
```bash
chmod +x install.sh
./install.sh
```

The install script sets up Python, PostgreSQL, creates the database, installs dependencies, and prompts for your Bedrock bearer token. After setup, the app launches at <http://localhost:3777>.

For subsequent launches: `start.bat` (Windows) or `./start.sh` (Mac/Linux).

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
