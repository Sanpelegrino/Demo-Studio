# Demo Studio — User Guide

Demo Studio is an interactive data workspace that lets you reshape datasets for Tableau using natural language. You describe what you want, an AI agent proposes SQL or Python, and the change runs in a single Postgres transaction with automatic snapshots for rollback.

## Getting started

1. Open <http://localhost:3777> in your browser.
2. The **Tableau connection** card shows the credentials Tableau needs (server, port, database, user, password, schema, view).
3. In Tableau Desktop: **Connect → PostgreSQL**, enter those credentials, and drag the `demo.analytics` view onto the canvas.

## Chat workflow

1. Type a request in the chat box (e.g., "Add a churn_risk column that correlates with declining win rates").
2. Click **Plan change** — the agent returns a summary, language tag (SQL or Python), optional notes, and the raw code.
3. Review the plan. If it looks good, click **Apply**.
4. The code runs in one transaction. If it fails, everything rolls back automatically — the agent will retry up to 3 times with self-correction.
5. After a successful apply, Tableau will auto-refresh if the **Live Refresh** extension is loaded, or right-click the data source → Refresh.

### Autorun mode

Toggle **Autorun** to skip the review step. The agent plans and applies in one shot. Useful once you trust the agent on routine operations.

## Datasets

### Built-in seeds

- **Salesforce** — 400 accounts, ~2,000 opportunities, analytics view joining them.
- **Superstore** — Sample retail dataset (orders, returns, people).

Use the **Reseed from scratch** button to wipe and regenerate either seed.

### Manifest datasets (CSV upload)

Any folder with a `manifest.json` + CSV files can be loaded:

1. Click **Upload .zip** or select a pre-loaded dataset from the dropdown.
2. Click **Load** — this wipes the current workspace and builds all tables + views from the manifest.

Manifests declare table roles (fact/dimension), primary keys, and join paths. The system auto-generates analytics views from the join graph.

## Rollback and history

Every applied change creates a snapshot. Use **Rollback last change** to undo the most recent mutation. The **History** panel shows all changes applied this session — click any entry to see the code that ran.

## Tableau extensions

### Live Refresh

A dashboard extension that subscribes to workspace change events via Server-Sent Events. When data changes, all data sources in the workbook refresh automatically.

**Setup:** Dashboard → Extensions → Add → drag `live-refresh.trex` from <http://localhost:3777/extension/manifest>.

### Live Chat (Dashboard Embed)

An embedded version of the chat interface that runs inside a Tableau dashboard extension zone. Analysts can reshape data without leaving Tableau.

**Setup:** Dashboard → Extensions → Add → drag `live-chat.trex` from <http://localhost:3777/extension/chat>.

Features in embed mode:
- **Show code** toggle — hidden by default for non-technical viewers, flip it to see the raw SQL/Python.
- **Autorun** toggle — same as the main UI.
- History is intentionally omitted to keep the extension minimal.

## Self-improving error handling

The agent learns from its mistakes. Every failed execution is logged. After 5 failures accumulate, the system automatically:

1. Distills the errors into concise "Don't do X, Do Y" guidance (appended to the agent's system prompt).
2. Builds a detailed RAG knowledge base with root causes, fix strategies, and example code.

On retry, the agent receives targeted playbooks matching the specific error it hit — drawn from the RAG store rather than the lean system prompt rules. This process is fully automatic and requires no user intervention.
