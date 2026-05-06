# Demo Studio — Setup Guide

## Quick Install

The install script handles everything: Python, PostgreSQL, database creation, dependencies, and configuration.

**Windows:**
```
install.bat
```

**Mac/Linux:**
```bash
chmod +x install.sh
./install.sh
```

The script will:
1. Install Python 3.12 (via winget on Windows, Homebrew on Mac) if not already present.
2. Install PostgreSQL 16/17 if not already present.
3. Start the PostgreSQL service.
4. Create the `demo_studio` database and user.
5. Create a Python virtual environment and install dependencies.
6. Prompt you for your Anthropic Bedrock bearer token and write it to `.env`.
7. Launch the app and open your browser to <http://localhost:3777>.

### Subsequent launches

After the first install, use the start script instead — it skips setup and just launches the server:

**Windows:** `start.bat`
**Mac/Linux:** `./start.sh`

---

## What you need beforehand

- **Windows 10/11** or **macOS 12+** or **Linux** (Ubuntu 20.04+)
- An internet connection (for installing packages on first run)
- A **Salesforce Bedrock gateway bearer token** — this authenticates requests to Claude. Ask your team lead if you don't have one.
- (Optional) **Tableau Desktop** for the dashboard integration and extensions

---

## Manual Setup

If the install script fails on a specific step or you prefer to control each piece:

### 1. Install Python 3.10+

Download from <https://www.python.org/downloads/> or use your system package manager. Verify:

```
python --version
```

### 2. Install PostgreSQL 14+

Download from <https://www.postgresql.org/download/> or use your system package manager. Make sure the service is running:

```
pg_isready -h 127.0.0.1 -p 5432
```

### 3. Create the database

Connect as the PostgreSQL superuser and run:

```sql
CREATE USER demo_studio WITH PASSWORD 'demo_local_dev';
CREATE DATABASE demo_studio OWNER demo_studio;
```

### 4. Install Python dependencies

```bash
cd "Demo Studio"
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 5. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_AUTH_TOKEN` | Your Bedrock gateway bearer token |
| `ANTHROPIC_BEDROCK_BASE_URL` | Gateway URL (e.g. `https://...sfdc.sh/bedrock`) |
| `ANTHROPIC_MODEL` | Model ID (default: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| `NODE_EXTRA_CA_CERTS` | Path to CA bundle if behind a corporate proxy (leave blank otherwise) |
| `PGHOST` | `127.0.0.1` |
| `PGPORT` | `5432` |
| `PGUSER` | `demo_studio` |
| `PGPASSWORD` | `demo_local_dev` |
| `PGDATABASE` | `demo_studio` |
| `PGSCHEMA` | `demo` |

### 6. Launch

```bash
uvicorn app:app --host 0.0.0.0 --port 3777
```

Open <http://localhost:3777>. On first boot the app seeds a starter dataset automatically.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `psql` not found after installing PostgreSQL | Close your terminal and open a new one so the PATH updates. On Windows, check `C:\Program Files\PostgreSQL\17\bin` is on your PATH. |
| PostgreSQL won't start | On Windows: open Services (`services.msc`), find `postgresql-x64-17`, and start it. On Mac: `brew services start postgresql@16`. |
| `pip install` fails with SSL errors | Set `NODE_EXTRA_CA_CERTS` in `.env` to your corporate CA bundle path, or try `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt`. |
| Port 3777 already in use | Another instance is running. Kill it or change the port in `start.bat`/`start.sh`. |
| Browser opens but page is blank | Wait a few seconds for the server to finish starting. Check the terminal for errors. |
