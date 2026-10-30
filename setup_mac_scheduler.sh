#!/usr/bin/env bash
# ==============================================================================
# Native macOS LaunchAgent Scheduler Setup
# ==============================================================================
# This script provisions an Apple macOS LaunchAgent daemon (.plist) that executes
# the autonomous LinkedIn Agent every day at a scheduled morning hour.
#
# Key Features:
#   - Runs natively under macOS launchd without requiring external cron daemons.
#   - Sleep/Wake Resilient: If the Mac is sleeping at the scheduled time, launchd
#     automatically fires the agent job as soon as the machine wakes up.
#   - Redirects stdout and stderr to agent.log for easy inspection.
#
# Usage:
#   ./setup_mac_scheduler.sh         (Defaults to 09:15 AM every day)
#   ./setup_mac_scheduler.sh 8 30    (Runs at 08:30 AM every day)
# ==============================================================================
set -e

# Identifier for the launchd service
PLIST_NAME="com.guha.linkedin-agent.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

# Resolve absolute project directory and virtual environment Python interpreter
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

# Scheduled run time parameters (defaults to 9:15 AM)
HOUR=${1:-9}
MINUTE=${2:-15}

echo "Configuring daily schedule for $HOUR:$(printf "%02d" $MINUTE) every morning..."

# Ensure the user's LaunchAgents directory exists
mkdir -p "$HOME/Library/LaunchAgents"

# Generate XML property list definition
cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Unique label identifying the LaunchAgent -->
    <key>Label</key>
    <string>com.guha.linkedin-agent</string>

    <!-- Command and arguments to execute -->
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$PROJECT_DIR/agent.py</string>
    </array>

    <!-- Working directory set to the project root for local file access -->
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <!-- Calendar trigger: fires daily at specified Hour and Minute -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>

    <!-- Standard and error output logging -->
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/agent.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/agent.log</string>
</dict>
</plist>
EOF

# Unload previous service instance if already registered in launchd
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Register and load the updated LaunchAgent
launchctl load "$PLIST_PATH"

echo "✅ Installed LaunchAgent at $PLIST_PATH"
echo "The agent will automatically run every day at $HOUR:$(printf "%02d" $MINUTE) AM."
echo "If your Mac was sleeping at that time, it will run as soon as your Mac wakes up."
echo "Logs will be written to: $PROJECT_DIR/agent.log"
