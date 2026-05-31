#!/bin/bash
set -e

cd "$(dirname "$0")"
mkdir -p logs
PLIST="$PWD/logs/com.xagent.web.plist"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -e .

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.xagent.web</string>
  <key>WorkingDirectory</key>
  <string>$PWD</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PWD/.venv/bin/python</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>web.backend.server:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>9531</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PWD/logs/web_server.log</string>
  <key>StandardErrorPath</key>
  <string>$PWD/logs/web_server.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "X-Agent macOS web UI is running."
echo "Open http://127.0.0.1:9531/"
