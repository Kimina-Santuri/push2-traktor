#!/bin/bash
# Install the Push 2 -> Traktor bridge on macOS.
#
#   ./install.sh                     four-deck layout (push_quad.py), starts at login
#   ./install.sh --layout advanced   8-column layout with modes (push_bridge.py)
#   ./install.sh --no-login-item     install, but don't start it automatically
#
# Builds the Traktor mappings into the repo folder and copies them to your Desktop.
# Needs macOS, python3 3.9+ and Traktor Pro 4 (the .tsi builder reads one of its files).
set -euo pipefail

LAYOUT=quad
LOGIN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --layout) LAYOUT="$2"; shift 2 ;;
    --no-login-item) LOGIN=0; shift ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
case "$LAYOUT" in
  quad) SCRIPT=push_quad.py ;;
  advanced) SCRIPT=push_bridge.py ;;
  *) echo "--layout must be quad or advanced"; exit 1 ;;
esac

[ "$(uname)" = "Darwin" ] || { echo "This installer is for macOS."; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found. Install it from python.org first."; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "python3 3.9 or newer is needed."; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Library/Application Support/Push2TraktorBridge"
LABEL=local.push2-traktor-bridge
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/push2-traktor-bridge.log"

# The Push 2 screen talks USB through libusb; without it the bridge still runs, just without the screen.
if [ ! -e /opt/homebrew/lib/libusb-1.0.0.dylib ] && [ ! -e /usr/local/lib/libusb-1.0.0.dylib ]; then
  if command -v brew >/dev/null; then
    echo "==> Installing libusb (for the Push 2 screen)"
    brew install libusb || echo "    libusb install failed: the screen will stay off"
  else
    echo "    No Homebrew, so no libusb: the Push 2 screen will stay off (everything else works)"
  fi
fi

echo "==> Installing to $DEST"
mkdir -p "$DEST"
[ -x "$DEST/venv/bin/python" ] || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$REPO/requirements.txt"
cp "$REPO/push_quad.py" "$REPO/push_bridge.py" "$REPO/push_display.py" "$REPO/contract.py" "$DEST/"

echo "==> Building Traktor mappings"
if "$DEST/venv/bin/python" "$REPO/build_tsi.py" && "$DEST/venv/bin/python" "$REPO/build_simple_tsi.py"; then
  cp "$REPO/Push2 Bridge.tsi" "$REPO/Push2 Simple.tsi" "$HOME/Desktop/"
  echo "    Copied Push2 Bridge.tsi and Push2 Simple.tsi to your Desktop"
else
  echo "    Skipped: open Traktor Pro 4 once so its default settings exist, then run this again."
fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "$LOGIN" = 1 ]; then
  echo "==> Starting $SCRIPT now and at every login"
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DEST/venv/bin/python</string>
    <string>-u</string>
    <string>$DEST/$SCRIPT</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
else
  rm -f "$PLIST"
  echo "==> Not starting at login. Run it yourself with:"
  echo "    \"$DEST/venv/bin/python\" \"$DEST/$SCRIPT\""
fi

cat <<EOF

Done. Next:
  1. Quit Ableton Live and plug in the Push 2.
  2. Traktor > Preferences > Controller Manager > Import TSI > Push2 Bridge.tsi (Desktop).
     In-Port and Out-Port must both be "Push2 Traktor Bridge".
     Updating? Delete the old "Push 2 Bridge (smart LEDs)" device first, then import the new file.
  3. Cheat sheet: $REPO/docs/cheatsheet.svg
Log: $LOG    Remove everything: ./uninstall.sh
EOF
