#!/usr/bin/env bash
# Starts the LinkedIn Agent in interactive Telegram listening mode.
# Listens for /topic, /direct, photos, and /daily from your Telegram chat.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

echo "🤖 Starting Telegram bot listener for LinkedIn Agent..."
echo "Press Ctrl+C to stop."
exec "$PYTHON_BIN" "$PROJECT_DIR/agent.py" --listen
