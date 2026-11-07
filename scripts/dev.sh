#!/usr/bin/env bash
# Run the whole demo: local LiveKit server + token server + voice agent.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data

say() { printf '\n\033[1;35m✦ %s\033[0m\n' "$1"; }
warn() { printf '\n\033[1;33m! %s\033[0m\n' "$1"; }

if [ ! -x .venv/bin/python ]; then
  warn "No virtual environment found. Run ./scripts/setup.sh first."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env from the example. Add GOOGLE_API_KEY, then run this again."
  exit 1
fi

GOOGLE_KEY="$(grep -E '^GOOGLE_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '\"' | xargs || true)"
if [ -z "$GOOGLE_KEY" ] || [ "$GOOGLE_KEY" = "your-google-ai-studio-key" ]; then
  warn "GOOGLE_API_KEY is not set in .env."
  echo "  Get a key at https://aistudio.google.com/apikey, then add:"
  echo "    GOOGLE_API_KEY=AIza..."
  exit 1
fi

LIVEKIT_URL="$(grep -E '^LIVEKIT_URL=' .env | head -1 | cut -d= -f2- | tr -d '\"' | xargs || echo ws://localhost:7880)"
PORT="${PORT:-3000}"
PIDS=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${PIDS[@]:-}"; do
    if [ -n "${pid:-}" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

port_open() {
  curl -s -o /dev/null --max-time 1 "$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------- LiveKit
case "$LIVEKIT_URL" in
  *localhost*|*127.0.0.1*)
    if port_open "http://127.0.0.1:7880"; then
      say "LiveKit server already running on :7880"
    else
      LIVEKIT_BIN="${LIVEKIT_SERVER_BIN:-}"
      if [ -z "$LIVEKIT_BIN" ] && [ -x "$PWD/bin/livekit-server" ]; then
        LIVEKIT_BIN="$PWD/bin/livekit-server"
      elif [ -z "$LIVEKIT_BIN" ] && command -v livekit-server >/dev/null 2>&1; then
        LIVEKIT_BIN="$(command -v livekit-server)"
      fi
      if [ -z "$LIVEKIT_BIN" ]; then
        warn "livekit-server is missing. Run ./scripts/setup.sh or use LiveKit Cloud."
        exit 1
      fi
      say "Starting local LiveKit server on :7880 ($LIVEKIT_BIN)"
      "$LIVEKIT_BIN" --dev --bind 127.0.0.1 > data/livekit.log 2>&1 &
      PIDS+=("$!")
      for _ in $(seq 1 40); do
        port_open "http://127.0.0.1:7880" && break
        sleep 0.25
      done
      if ! port_open "http://127.0.0.1:7880"; then
        warn "LiveKit server did not start. See data/livekit.log"
        tail -20 data/livekit.log || true
        exit 1
      fi
    fi
    ;;
  *)
    say "Using LiveKit at $LIVEKIT_URL"
    ;;
esac

# ------------------------------------------------------------- token server
if port_open "http://127.0.0.1:$PORT/api/health"; then
  say "Web/token server already running on :$PORT"
else
  say "Starting web + token server on :$PORT"
  .venv/bin/uvicorn backend.server:app --host 127.0.0.1 --port "$PORT" >> data/server.log 2>&1 &
  PIDS+=("$!")
  for _ in $(seq 1 60); do
    port_open "http://127.0.0.1:$PORT/api/health" && break
    sleep 0.25
  done
  if ! port_open "http://127.0.0.1:$PORT/api/health"; then
    warn "Token server did not start. See data/server.log"
    tail -30 data/server.log || true
    exit 1
  fi
fi

# -------------------------------------------------------------------- agent
say "Wake the fairy — starting the Gemini Live agent"
cat <<EOF

  ┌──────────────────────────────────────────────┐
  │  Open  http://localhost:$PORT                 │
  │  Click “Summon Fae” and allow the microphone │
  │  Press Ctrl-C here to stop everything        │
  └──────────────────────────────────────────────┘

EOF

.venv/bin/python -m backend.fairy_agent dev &
PIDS+=("$!")

wait
