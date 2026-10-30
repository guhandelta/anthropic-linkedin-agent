#!/usr/bin/env bash
# ==============================================================================
# Autonomous LinkedIn Agent Runner
# Automatically executes using the project's virtualenv Python interpreter.
#
# Examples:
#   ./run.sh --dry-run
#   ./run.sh
#   ./run.sh --topic "React 19 Actions"
#   ./run.sh --listen
# ==============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "❌ Virtual environment not found at $PYTHON_BIN"
    echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/agent.py" "$@"
