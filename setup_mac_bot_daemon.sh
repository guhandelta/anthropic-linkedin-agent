#!/usr/bin/env bash
# Sets up a native macOS LaunchAgent daemon to keep the Telegram bot listener running 24/7.
set -e

PLIST_NAME="com.guha.linkedin-agent-bot.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

echo "🤖 Configuring background Telegram Bot listener daemon for LinkedIn Agent..."

mkdir -p "$HOME/Library/LaunchAgents"

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.guha.linkedin-agent-bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$PROJECT_DIR/agent.py</string>
        <string>--listen</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/bot_listener.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/bot_listener.log</string>
</dict>
</plist>
EOF

# Unload previous instance if running
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load new daemon
launchctl load "$PLIST_PATH"

echo "✅ Installed background LaunchAgent at $PLIST_PATH"
echo "🤖 The Telegram bot listener is now running 24/7 in the background!"
echo "It will automatically restart if your Mac reboots or wakes up from sleep."
echo "Live logs: tail -f $PROJECT_DIR/bot_listener.log"
