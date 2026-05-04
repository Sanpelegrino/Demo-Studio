# Demo Studio (local prototype)

FastAPI app that:

1. Seeds a Salesforce-style dataset (`demo.accounts`, `demo.opportunities`) into a local Postgres database.
2. Lets you connect Tableau Desktop to the `demo` schema.
3. Lets you chat with Claude to reshape the data or the schema (free SQL / Python).
4. Snapshots every change so you can roll back.

## Setup

```bash
cd "Demo Studio"
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
cp .env.example .env              # then fill in ANTHROPIC_AUTH_TOKEN + PG creds
```

The `.env` expects:

```
ANTHROPIC_AUTH_TOKEN=...
ANTHROPIC_BEDROCK_BASE_URL=...
ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
NODE_EXTRA_CA_CERTS=...

PGHOST=127.0.0.1
PGPORT=5432
PGUSER=pulse_app
PGPASSWORD=pulse_local_dev
PGDATABASE=demo_studio
PGSCHEMA=demo
```

You must create the `demo_studio` database once (as a Postgres superuser):

```sql
CREATE DATABASE demo_studio OWNER pulse_app;
```

## Run

```bash
uvicorn app:app --reload --port 3777
```

Open <http://localhost:3777>. First boot seeds the schema automatically.

## Connect Tableau

- **Connect → PostgreSQL** (native Tableau connector, no JDBC driver needed).
- Use the connection details shown on the page.
- Pick schema `demo` and drag `accounts` and `opportunities` onto the canvas.
- After each applied change in the app, right-click the data source → **Refresh**.

## Chat loop

Describe what you want — the LLM picks SQL or Python:

- *"Add a churn_risk column to accounts that correlates with declining opp win rates."*
- *"Increase Q4 2025 Enterprise amounts by 20%."*
- *"Drop is_active from accounts. Add a customer_health table linked by account_id."*
- *"Rename 'amount' to 'deal_size' on opportunities."*

You review the proposed code, then **Apply**. The code runs in a single Postgres transaction; if it errors, everything rolls back.

## Safety net

- Every applied change first snapshots every table in `demo` into a parallel `snapshots` schema (`snapshots.snap_<ts>__accounts`, etc.).
- **Rollback last change** drops the current tables and restores from the most recent snapshot.
- **Reseed from scratch** wipes and regenerates the starter dataset.

## File layout

```
Demo Studio/
  app.py                # FastAPI endpoints
  planner.py            # Claude (Bedrock gateway) call + prompt
  seed.py               # generates accounts + opportunities
  snapshots_store.py    # Postgres-based snapshots/rollback
  static/               # single-page UI
  requirements.txt
  .env.example
```

## Notes

- The LLM has full DDL freedom inside the `demo` schema — it can add, drop, rename columns and tables. The snapshot system is your undo stack.
- The app runs every mutation in a transaction, so a failed script leaves the schema untouched.
- Multiple readers (e.g. Tableau) don't block writes in Postgres — no lock dance like DuckDB.
