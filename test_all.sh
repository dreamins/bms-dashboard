#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "########################################"
echo "# Lithium Core -- Test Suite           #"
echo "########################################"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
APP_DIR="$SCRIPT_DIR/dashboard_app"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[ERROR] Virtual environment not found. Run ./run.sh first to set it up."
    exit 1
fi

echo "[INFO] Running test suite..."
echo
cd "$APP_DIR"
"$VENV_PYTHON" -m unittest discover -s tests -v
RESULT=$?
cd "$SCRIPT_DIR"

echo
if [ $RESULT -eq 0 ]; then
    echo "##################################"
    echo "# ALL TESTS PASSED               #"
    echo "##################################"
else
    echo "##################################"
    echo "# TESTS FAILED                   #"
    echo "##################################"
fi
exit $RESULT
