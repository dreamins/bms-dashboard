#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "########################################"
echo "# Lithium Core Dashboard               #"
echo "########################################"

# Check for Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Please install Python 3.9+ via your package manager."
    exit 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv .venv
fi

# Install / sync dependencies
echo "[INFO] Checking dependencies..."
.venv/bin/pip install -r requirements.txt --quiet

# Launch (cd into dashboard_app so relative imports resolve)
echo "[INFO] Launching Lithium Core Dashboard..."
echo "[INFO] Open http://localhost:8080 in your browser."
echo
cd "$SCRIPT_DIR/dashboard_app"
"$SCRIPT_DIR/.venv/bin/python" dashboard.py
