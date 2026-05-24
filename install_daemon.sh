#!/bin/bash
# Installs VigilantTrader as a macOS launchd daemon.
# Runs automatically on login and restarts on crash.
# macOS only.
#
# macOS launchd gotchas (learned the hard way):
#
# 1. Gatekeeper blocks Homebrew/non-system Python when called directly from launchd.
#    Fix: use a /bin/bash wrapper script — bash is always trusted.
#
# 2. TCC (Privacy) blocks launchd from opening files in ~/Desktop, ~/Documents,
#    ~/Downloads for StandardOutPath/StandardErrorPath — even with Full Disk Access.
#    launchd opens those file handles before exec-ing your program.
#    Fix: point stdout/stderr to /dev/null; let the app write its own log.
#
# 3. If the service crashes repeatedly, launchd poisons the label in its persistent
#    state database. bootout/bootstrap does NOT clear it. Fix: use a new label or reboot.
#
# 4. If the project lives in ~/Desktop (or ~/Documents/~/Downloads), grant Full Disk
#    Access to /bin/bash in System Settings → Privacy & Security → Full Disk Access.

set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJ_DIR/venv/bin/python3"
WRAPPER="$PROJ_DIR/run_daemon.sh"
PLIST_LABEL="com.codebluemd.vigilanttrader"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

if [ ! -f "$PYTHON" ]; then
    echo "ERROR: venv not found. Run setup.sh first."
    exit 1
fi

# Write the bash wrapper (Gatekeeper fix — launchd calls bash, bash calls Python)
cat > "$WRAPPER" << WRAPPER_EOF
#!/bin/bash
cd "$PROJ_DIR"
exec "$PYTHON" "$PROJ_DIR/main.py"
WRAPPER_EOF
chmod +x "$WRAPPER"

# Unload existing agent if present (both old and new label)
launchctl bootout gui/$(id -u)/com.codebluemd.vigilant-trader 2>/dev/null || true
launchctl bootout gui/$(id -u)/$PLIST_LABEL 2>/dev/null || true
sleep 1

# Write plist — stdout/stderr to /dev/null (TCC fix); app writes its own log via FileHandler
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$WRAPPER</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJ_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/dev/null</string>

    <key>StandardErrorPath</key>
    <string>/dev/null</string>

    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
EOF

launchctl bootstrap gui/$(id -u) "$PLIST_PATH"
sleep 3

if launchctl list | grep -q "$PLIST_LABEL"; then
    echo ""
    echo "Daemon installed and running."
    echo "  Status:  launchctl list | grep vigilanttrader"
    echo "  Logs:    tail -f $PROJ_DIR/vigilant.log"
    echo "  Stop:    launchctl bootout gui/\$(id -u)/$PLIST_LABEL"
    echo "  Restart: launchctl kickstart gui/\$(id -u)/$PLIST_LABEL"
    echo ""
    echo "IMPORTANT — System Settings → Energy → Power Adapter:"
    echo "  ✓ Prevent automatic sleeping when display is off"
    echo "  ✓ Enable Power Nap"
    echo "  ✓ Wake for network access"
    echo ""
    echo "If the project is in ~/Desktop or ~/Documents, also go to:"
    echo "  System Settings → Privacy & Security → Full Disk Access"
    echo "  and add /bin/bash (press Cmd+Shift+G in the file picker, type /bin)"
else
    echo ""
    echo "WARNING: daemon may not have started. Check:"
    echo "  launchctl print gui/\$(id -u)/$PLIST_LABEL"
fi
