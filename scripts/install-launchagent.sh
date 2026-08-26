#!/usr/bin/env bash
# Install macOS LaunchAgent: SlotWake concierge every 15 minutes (hours gated in Python).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.inna.slotwake-muenchen.concierge"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$HOME/Library/Logs/slotwake-muenchen.launchd.log"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$(dirname "$LOG")" "$ROOT/data"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${ROOT}/scripts/concierge.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${HOME}/.local/bin</string>
    <key>STARNBERG_TERMIN_ROOT</key>
    <string>${ROOT}/../starnberg-termin</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Installed ${LABEL}"
echo "  plist: ${PLIST}"
echo "  log:   ${LOG}"
echo "  every 15 min; Python skips outside ${CONCIERGE_HOUR_START:-6}:00–${CONCIERGE_HOUR_END:-19}:00 Europe/Berlin"
echo "Run once now:"
echo "  CONCIERGE_FORCE=1 ${PY} ${ROOT}/scripts/concierge.py --dry-run"
