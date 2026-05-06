#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PG_USER="demo_studio"
PG_PASS="demo_local_dev"
PG_DB="demo_studio"
PORT=3777

# ─── Colors ───────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Demo Studio Installer         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ─── 1. Check/Install Python ─────────────────────────────
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    if ! command -v brew &>/dev/null; then
        fail "Python >= 3.10 not found and Homebrew is not installed.\n       Install Homebrew first: https://brew.sh"
    fi
    info "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON_CMD="python3.12"
fi
ok "Python: $($PYTHON_CMD --version)"

# ─── 2. Check/Install PostgreSQL ─────────────────────────
if ! command -v psql &>/dev/null; then
    if ! command -v brew &>/dev/null; then
        fail "PostgreSQL not found and Homebrew is not installed.\n       Install Homebrew first: https://brew.sh"
    fi
    info "Installing PostgreSQL 16 via Homebrew..."
    brew install postgresql@16
    brew link postgresql@16 --force 2>/dev/null || true
fi
ok "PostgreSQL: $(psql --version | head -1)"

# ─── 3. Start PostgreSQL ─────────────────────────────────
if ! pg_isready -h 127.0.0.1 -p 5432 &>/dev/null; then
    info "Starting PostgreSQL..."
    if [[ "$(uname)" == "Darwin" ]]; then
        brew services start postgresql@16 2>/dev/null || brew services start postgresql 2>/dev/null || true
    else
        sudo systemctl start postgresql 2>/dev/null || sudo service postgresql start 2>/dev/null || true
    fi
    for i in $(seq 1 15); do
        pg_isready -h 127.0.0.1 -p 5432 &>/dev/null && break
        sleep 1
    done
    if ! pg_isready -h 127.0.0.1 -p 5432 &>/dev/null; then
        fail "PostgreSQL did not start. Please start it manually and re-run this script."
    fi
fi
ok "PostgreSQL is running."

# ─── 4. Create Database and User ─────────────────────────
# On Mac (Homebrew), the superuser is the current OS user.
# On Linux, it's typically 'postgres'.
if [[ "$(uname)" == "Darwin" ]]; then
    PSQL_SUPER="psql -h 127.0.0.1 -d postgres"
else
    PSQL_SUPER="sudo -u postgres psql -h 127.0.0.1"
fi

$PSQL_SUPER -c "DO \$\$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$PG_USER') THEN
        CREATE ROLE $PG_USER WITH LOGIN PASSWORD '$PG_PASS';
    END IF;
END \$\$;" 2>/dev/null || fail "Could not create database user. Check PostgreSQL superuser access."

DB_EXISTS=$($PSQL_SUPER -tc "SELECT 1 FROM pg_database WHERE datname = '$PG_DB'" 2>/dev/null | tr -d ' ')
if [[ "$DB_EXISTS" != "1" ]]; then
    $PSQL_SUPER -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" 2>/dev/null || fail "Could not create database."
fi
ok "Database '$PG_DB' and user '$PG_USER' ready."

# ─── 5. Python venv + Dependencies ───────────────────────
if [[ ! -d ".venv" ]]; then
    info "Creating virtual environment..."
    $PYTHON_CMD -m venv .venv
fi
source .venv/bin/activate
info "Installing Python dependencies..."
pip install --upgrade pip -q 2>/dev/null
pip install -r requirements.txt -q
ok "Python dependencies installed."

# ─── 6. Configure .env ───────────────────────────────────
if [[ -f .env ]]; then
    echo ""
    read -rp ".env already exists. Overwrite? [y/N]: " OVERWRITE
    if [[ "${OVERWRITE,,}" != "y" ]]; then
        ok "Keeping existing .env."
    else
        rm .env
    fi
fi

if [[ ! -f .env ]]; then
    echo ""
    read -rp "Enter your Anthropic bearer token: " AUTH_TOKEN
    if [[ -z "$AUTH_TOKEN" ]]; then
        fail "Token cannot be empty."
    fi
    cp .env.example .env
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s|your-bedrock-bearer-token|$AUTH_TOKEN|" .env
    else
        sed -i "s|your-bedrock-bearer-token|$AUTH_TOKEN|" .env
    fi
    ok ".env configured."
fi

# ─── 7. Launch ───────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "  Starting Demo Studio on port $PORT..."
echo "  Press Ctrl+C to stop."
echo "════════════════════════════════════════"
echo ""

# Open browser after a short delay
(sleep 3 && {
    if [[ "$(uname)" == "Darwin" ]]; then
        open "http://localhost:$PORT"
    else
        xdg-open "http://localhost:$PORT" 2>/dev/null || true
    fi
} &) 2>/dev/null

python -m uvicorn app:app --host 0.0.0.0 --port $PORT
