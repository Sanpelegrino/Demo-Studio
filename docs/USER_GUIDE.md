# Demo Studio — User Guide

Demo Studio is a local tool that lets you reshape Postgres-backed datasets using natural language. You describe what you want, Claude proposes SQL or Python, and the change runs in a single transaction with automatic snapshots for rollback. Tableau sees the results immediately.

---

## First launch

After running `install.bat` (Windows) or `./install.sh` (Mac/Linux), the app opens automatically at <http://localhost:3777>. You'll see two main panels:

- **Left panel — Tableau connection:** Shows the database credentials and current dataset info.
- **Right panel — Chat:** Where you talk to the agent and apply changes.

On first boot, a starter dataset (Superstore) is seeded automatically.

---

## Connecting Tableau

1. In the **Tableau connection** card, note the credentials: Server, Port, Database, Username, Password, Schema.
2. Open **Tableau Desktop**.
3. Click **Connect → To a Server → PostgreSQL**.
4. Enter the credentials from the connection card. Click the **copy** button next to the password to copy it to your clipboard.
5. Once connected, navigate to the schema shown in the connection card (default: `demo`).
6. Drag the **view** shown in the connection card (e.g. `analytics`) onto the canvas. Use the view, not the raw tables — the agent updates the view automatically when it reshapes data.

---

## Reshaping data with Chat

### Planning a change

1. Click in the **Chat** text area on the right panel.
2. Type what you want in plain English. Examples:
   - "Add a profit_margin column calculated as profit / sales"
   - "Split the customer_name column into first_name and last_name"
   - "Create a summary table with total sales by region and category"
3. Click the **Plan change** button.
4. The agent responds with:
   - A plain-English **summary** of what it will do
   - A **language tag** (SQL or Python)
   - The **raw code** it will execute

### Applying a change

5. Review the proposed code. If it looks good, click **Apply** (appears at the top of the chat card).
6. If you don't want to apply it, click **Discard** instead.
7. After a successful apply, the status indicator turns green and the connection card updates to reflect the new schema.

### Autorun mode

Click the **Autorun** toggle at the top of the chat card. When enabled, changes are planned and applied in one step — no review needed. Useful once you're comfortable with the agent's output on routine operations.

### Model selector

Use the **model dropdown** next to Autorun to switch between Claude models (Sonnet 4.5 for speed, Opus 4 for complex reasoning).

### Rollback

Click **Rollback last change** below the chat input to undo the most recent mutation. Every applied change creates a snapshot, so you can always step back.

---

## Managing datasets

### Switching datasets

At the bottom of the Tableau connection card:

1. Open the **dropdown** to see available datasets (Superstore and Salesforce are built-in).
2. Select one and click **Load**. This wipes the current workspace and loads the selected dataset from scratch.

### Uploading your own data

Click the **Upload** button next to the dataset dropdown. You can upload:

- **CSV files** — one or more `.csv` files. If you upload multiple CSVs, a configuration modal appears to define table relationships.
- **Excel files** (`.xls`, `.xlsx`) — the modal lets you pick which sheets to include and define joins between them.
- **ZIP archives** — a folder containing a `manifest.json` and CSV files (see below).

You can also click **or folder** to upload an entire folder at once.

### Configuration modal

When uploading multiple files or multi-sheet Excel, a modal appears:

1. **Select sheets/files** to include using the checkboxes.
2. Choose **single table** (no joins) or **multiple tables** (define relationships).
3. If multiple tables: set the **primary key** for each table, then define **join relationships** (which column in table A maps to which column in table B).
4. Click **Load dataset** to import.

### Saving your work

Click **Save Changes as Dataset** in the connection card to export your current workspace (including all modifications) as a reusable dataset you can reload later.

### Deleting a dataset

Click **Delete Dataset** (red button) to remove the current dataset entirely.

### Renaming a dataset

Click the pencil icon next to the dataset name in the connection card to rename it.

---

## History

The **History** card spans the bottom of the page and shows every change applied in this session. Click any entry to expand it and see the code that ran. Use this to review what's been done or to understand the agent's approach.

---

## Tableau Extensions

Demo Studio includes two Tableau dashboard extensions that connect Tableau directly to the workspace.

### Live Refresh extension

Automatically refreshes all data sources in your Tableau workbook whenever the workspace changes. No manual refresh needed.

**Setup:**

1. In Tableau Desktop, open your dashboard.
2. Go to **Dashboard → Extensions → Add Extension**.
3. Click **Access Local Extensions**.
4. Navigate to your Demo Studio folder and select `static/live-refresh.trex`.
5. Allow the extension when prompted.
6. The extension panel shows a **connected** tag when it's listening for changes.

**How it works:** The extension subscribes to a live event stream from Demo Studio. When you (or anyone using the Chat) applies a change, Tableau refreshes instantly — no polling, no clicking.

The extension panel shows:
- **Data sources** detected in the workbook
- **Last event** received from the server
- **Last refresh** timestamp
- A **Refresh now** button for manual refresh
- An **Activity log** (click to expand) showing all events

### Live Chat extension (embedded chat inside Tableau)

Puts the full Demo Studio chat interface inside a Tableau dashboard zone. Analysts can reshape data without leaving Tableau.

**Setup:**

1. In Tableau Desktop, open your dashboard.
2. Go to **Dashboard → Extensions → Add Extension**.
3. Click **Access Local Extensions**.
4. Navigate to your Demo Studio folder and select `static/live-chat.trex`.
5. Allow the extension when prompted.
6. The chat panel appears inside your dashboard.

**Features in embed mode:**

- **Autorun toggle** — plan + apply in one step.
- **Show code toggle** — hidden by default for non-technical viewers. Flip it to see the raw SQL/Python.
- **Model selector** — switch between Claude models.
- **Rollback** — undo the last change.
- History is intentionally omitted to keep the embedded view minimal.

### Using both extensions together

For the best experience, add both extensions to your dashboard:
1. Add **Live Refresh** so data sources stay current.
2. Add **Live Chat** so analysts can make requests directly.
3. Size the Live Chat zone to roughly 400px wide — it works well in a sidebar layout.

When an analyst types a request in the embedded chat, the change applies to Postgres, and the Live Refresh extension immediately triggers a data source refresh — the dashboard updates in real time.

---

## Tips

- **Be specific.** "Add a column called churn_risk that is 1 when days_since_last_order > 90, else 0" works better than "add churn risk."
- **Use Autorun for iteration.** Once you trust the agent's output, toggle Autorun on and rapid-fire requests to build up your dataset quickly.
- **Rollback is cheap.** Every change is snapshotted. Experiment freely — you can always undo.
- **The view is your contract.** Tableau connects to the view, not the raw tables. The agent handles updating the view when underlying tables change.
- **Maximize chat** — click the **Maximize** button in the chat card header to expand it full-screen for longer conversations. Click again to return to the two-column layout.
