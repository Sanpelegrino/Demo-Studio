#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PORT=3777

[[ -d .venv ]] || { echo "ERROR: Virtual environment not found. Run ./install.sh first."; exit 1; }
[[ -f .env ]]  || { echo "ERROR: .env not found. Run ./install.sh first."; exit 1; }

# Ensure Postgres is running
if ! pg_isready -h 127.0.0.1 -p 5432 &>/dev/null; then
    echo "Starting PostgreSQL..."
    if [[ "$(uname)" == "Darwin" ]]; then
        brew services start postgresql@16 2>/dev/null || brew services start postgresql 2>/dev/null || true
    else
        sudo systemctl start postgresql 2>/dev/null || sudo service postgresql start 2>/dev/null || true
    fi
    sleep 2
    pg_isready -h 127.0.0.1 -p 5432 &>/dev/null || { echo "ERROR: PostgreSQL is not running."; exit 1; }
fi

source .venv/bin/activate

echo "Starting Demo Studio on http://localhost:$PORT ..."
echo "Press Ctrl+C to stop."
echo ""

(sleep 3 && {
    if [[ "$(uname)" == "Darwin" ]]; then
        open "http://localhost:$PORT"
    else
        xdg-open "http://localhost:$PORT" 2>/dev/null || true
    fi
} &) 2>/dev/null

python -m uvicorn app:app --host 0.0.0.0 --port $PORT
