#!/usr/bin/env bash
# Launch the intake app and open it fullscreen — for a self-serve office tablet/kiosk.
# Usage: ./run_kiosk.sh            (serves on http://localhost:8080)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8080}"

# Activate the local venv if present.
[ -d .venv ] && source .venv/bin/activate

# Start the server in the background.
uvicorn app:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

# Give it a moment to boot, then open a browser in kiosk/fullscreen mode.
sleep 2
URL="http://localhost:$PORT/"
if command -v open >/dev/null 2>&1; then            # macOS
  # Chrome --kiosk gives a true full-screen kiosk; fall back to the default browser.
  if [ -d "/Applications/Google Chrome.app" ]; then
    open -a "Google Chrome" --args --kiosk --app="$URL"
  else
    open "$URL"
  fi
elif command -v xdg-open >/dev/null 2>&1; then       # Linux
  xdg-open "$URL"
fi

echo "Intake app running on $URL  (Ctrl+C to stop)"
wait $SERVER_PID
