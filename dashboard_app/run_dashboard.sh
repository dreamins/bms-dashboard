#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/../.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[ERROR] Virtual environment not found."
    echo "[INFO]  Run run.sh from the project root to set up the environment."
    exit 1
fi

echo "[INFO] Launching Lithium Core Dashboard..."
echo "[INFO] Open http://localhost:8080 in your browser."
echo
"$VENV_PYTHON" dashboard.py
