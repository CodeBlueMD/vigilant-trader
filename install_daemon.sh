#!/bin/bash
# Installs VigilantTrader as a macOS launchd daemon.
# Runs automatically on login and restarts on crash.
# macOS only.

set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJ_DIR/venv/bin/python3"
PLIST_LABEL="com.codebluemd.vigilant-trader"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_FILE="$PROJ_DIR/vigilant.log"

if [ ! -f "$PYTHON" ]; then
    echo "ERROR: venv not found. Run setup.sh first."
    exit 1
fi

# Unload existing agent if present
if launchctl list | grep -q "$PLIST_LABEL" 2>/dev/null; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    echo "Unloaded existing agent."
fi

# Write plist with current user's paths
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$PROJ_DIR/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJ_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>

    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>

    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH"
echo ""
echo "Daemon installed and started."
echo "  Status:  launchctl list | grep vigilant-trader"
echo "  Logs:    tail -f $LOG_FILE"
echo "  Stop:    launchctl unload $PLIST_PATH"
echo ""
echo "IMPORTANT: Go to System Settings → Energy → Power Adapter"
echo "and enable 'Prevent automatic sleeping when display is off'"
echo "so the daemon keeps running when your screen locks."
