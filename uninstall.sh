#!/bin/bash
# Stop the bridge and remove what install.sh added. Traktor's own settings are left alone:
# delete the "Push 2 Bridge" device in Traktor's Controller Manager yourself.
set -euo pipefail
LABEL=local.push2-traktor-bridge
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Library/Application Support/Push2TraktorBridge"
rm -f "$HOME/Library/Logs/push2-traktor-bridge.log"
echo "Removed the bridge, its login item and its log."
