# Demo Studio — Setup Guide

This guide is for agents or engineers setting up Demo Studio from scratch.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (local or remote)
- A Salesforce Bedrock gateway endpoint with a valid auth token (Claude via Anthropic-on-Bedrock)
- (Optional) Tableau Desktop for dashboard integration

## Installation

```bash
cd "Demo Studio"
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Environment variables

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_AUTH_TOKEN` | Bearer token for the Bedrock gateway |
| `ANTHROPIC_BEDROCK_BASE_URL` | Gateway base URL (e.g., `https://...sfdc.sh/bedrock`) |
| `ANTHROPIC_MODEL` | Model ID (default: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| `NODE_EXTRA_CA_CERTS` | Path to CA bundle if behind corporate proxy |
| `PGHOST` | Postgres host (default: `127.0.0.1`) |
| `PGPORT` | Postgres port (default: `5432`) |
| `PGUSER` | Postgres user (default: `demo_studio`) |
| `PGPASSWORD` | Postgres password (default: `demo_local_dev`) |
| `PGDATABASE` | Database name (default: `demo_studio`) |
| `PGSCHEMA` | Working schema (default: `demo`) |

## Database setup

Create the database and user (as a Postgres superuser):

```sql
CREATE USER demo_studio WITH PASSWORD 'demo_local_dev';
CREATE DATABASE demo_studio OWNER demo_studio;
```

The application creates the `demo` and `snapshots` schemas automatically on first boot. No manual migration required.

## Running the server

```bash
uvicorn app:app --reload --port 3777
```

The server:
1. Checks if the `demo` schema has any tables.
2. If empty, seeds the default Salesforce-style dataset (400 accounts, ~2,000 opportunities, `demo.analytics` view).
3. Starts accepting requests on <http://localhost:3777>.

## Architecture

```
Demo Studio/
  app.py                  # FastAPI endpoints, EventBus, apply/retry loop
  planner.py              # Claude invocation, prompt assembly, pitfalls RAG
  seed.py                 # Salesforce seed (accounts + opportunities)
  seed_superstore.py      # Superstore seed (orders + returns + people)
  seed_manifest.py        # CSV manifest loader (multi-table, join graph)
  snapshots_store.py      # Postgres snapshot/rollback system
  prompts/
    pitfalls.md           # Curated rules (injected into system prompt)
    pitfalls_raw.jsonl    # Raw error log (auto-cleared after distillation)
    pitfalls_rag.json     # Detailed error playbooks (used at retry time)
    pitfalls_distill_prompt.md   # Prompt for consolidating raw → curated
    pitfalls_rag_prompt.md       # Prompt for building RAG entries
  datasets/               # Manifest dataset folders (CSV + manifest.json)
  static/
    index.html            # Main UI (full controls)
    embed.html            # Tableau dashboard embed (chat only, no history)
    extension.html        # Live Refresh extension UI
    history.html          # Standalone history view
    app.js                # Shared frontend logic
    styles.css            # All styles (CSS custom properties, no framework)
    live-refresh.trex     # Tableau extension manifest (auto-refresh)
    live-chat.trex        # Tableau extension manifest (embedded chat)
    tableau.extensions.1.latest.min.js  # Tableau Extensions API
  docs/
    USER_GUIDE.md         # End-user documentation
    SETUP_GUIDE.md        # This file
```

## Key endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Main UI |
| `GET` | `/embed` | Dashboard chat embed |
| `GET` | `/api/status` | Schema, tables, views, history, connection info |
| `POST` | `/api/chat` | Plan a mutation (returns summary + code) |
| `POST` | `/api/apply` | Execute a plan (with auto-retry up to 3x) |
| `POST` | `/api/rollback` | Undo the last applied change |
| `POST` | `/api/reseed?dataset=salesforce\|superstore` | Wipe and reseed |
| `POST` | `/api/load-manifest` | Load a manifest dataset |
| `GET` | `/api/datasets` | List available manifest datasets |
| `POST` | `/api/datasets/upload` | Upload a .zip manifest dataset |
| `GET` | `/api/events` | SSE stream (workspace_changed events) |
| `GET` | `/api/pitfalls` | Current pitfalls state |
| `PUT` | `/api/pitfalls` | Update curated pitfalls |
| `POST` | `/api/pitfalls/distill` | Manually trigger distillation |
| `DELETE` | `/api/pitfalls/raw` | Clear raw error log |

## Pitfalls system (self-improving prompts)

The system has two tiers:

1. **Prevention layer** (`pitfalls.md`, max 120 lines) — injected into the system prompt on every call. Contains concise "Don't X, Do Y" rules for common mistakes.

2. **RAG rescue layer** (`pitfalls_rag.json`, unlimited) — detailed entries with error patterns, keywords, root causes, fix strategies, and example code. Queried via keyword matching at retry time and injected alongside the error context.

**Auto-distillation trigger:** After 5 errors accumulate in `pitfalls_raw.jsonl`, a background thread:
- Calls Claude to merge raw errors into `pitfalls.md` (respecting the 120-line cap)
- Calls Claude to build/update `pitfalls_rag.json` with detailed entries
- Clears the raw log

## Tableau extensions setup

### Live Refresh

1. In Tableau: Dashboard → Extensions → Add Extension
2. Point to: `http://localhost:3777/extension/manifest`
3. The extension auto-refreshes all data sources when `workspace_changed` events fire

### Live Chat

1. In Tableau: Dashboard → Extensions → Add Extension
2. Point to: `http://localhost:3777/extension/chat`
3. Analysts can reshape data from within the dashboard

## Manifest dataset format

A manifest dataset is a folder containing:

```json
// manifest.json
{
  "dataset": "My Dataset",
  "tables": [
    {
      "tableName": "orders",
      "fileName": "orders.csv",
      "tableRole": "fact",
      "primaryKey": "order_id"
    },
    {
      "tableName": "customers",
      "fileName": "customers.csv",
      "tableRole": "dimension",
      "primaryKey": "customer_id"
    }
  ],
  "joinPaths": [
    {
      "from": "orders",
      "to": "customers",
      "fromKey": "customer_id",
      "toKey": "customer_id"
    }
  ]
}
```

Each table entry references a CSV file in the same folder. The system creates tables, loads data, and auto-generates analytics views from the join graph (BFS from fact tables through dimensions).
