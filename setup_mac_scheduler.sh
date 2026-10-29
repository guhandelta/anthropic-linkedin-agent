#!/usr/bin/env bash
# Sets up a native macOS LaunchAgent to run the LinkedIn Agent every morning.
set -e

PLIST_NAME="com.guha.linkedin-agent.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

HOUR=${1:-9}
MINUTE=${2:-15}

echo "Configuring daily schedule for $HOUR:$(printf "%02d" $MINUTE) every morning..."

mkdir -p "$HOME/Library/LaunchAgents"

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.guha.linkedin-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$PROJECT_DIR/agent.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/agent.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/agent.log</string>
</dict>
</plist>
EOF

# Unload previous instance if running
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load new schedule
launchctl load "$PLIST_PATH"

echo "✅ Installed LaunchAgent at $PLIST_PATH"
echo "The agent will automatically run every day at $HOUR:$(printf "%02d" $MINUTE) AM."
echo "If your Mac was sleeping at that time, it will run as soon as your Mac wakes up."
echo "Logs will be written to: $PROJECT_DIR/agent.log"
