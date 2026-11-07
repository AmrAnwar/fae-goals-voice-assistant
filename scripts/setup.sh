#!/usr/bin/env bash
# One-time setup: Python deps, local LiveKit server, .env file.
set -euo pipefail

cd "$(dirname "$0")/.."

say() { printf '\n\033[1;35m✦ %s\033[0m\n' "$1"; }
warn() { printf '\n\033[1;33m! %s\033[0m\n' "$1"; }

PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.12)"
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
fi

if [ -z "$PYTHON_BIN" ]; then
  warn "Python 3.10+ is required. Install it from https://python.org and run this again."
  exit 1
fi

say "Using $("$PYTHON_BIN" --version)"

if [ ! -d .venv ]; then
  say "Creating the virtual environment"
  "$PYTHON_BIN" -m venv .venv
fi

say "Installing Python dependencies (this can take a minute)"
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

if [ -x bin/livekit-server ]; then
  say "Using the local LiveKit server in bin/livekit-server"
elif ! command -v livekit-server >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing the local LiveKit server"
    brew install livekit || warn "brew install failed; you can build from source (see README)."
  else
    warn "livekit-server is not installed."
    echo "  macOS:  brew install livekit"
    echo "  Linux:  curl -sSL https://get.livekit.io/server | bash"
    echo "  Or use LiveKit Cloud and set LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in .env."
  fi
fi

if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env — add your Google API key there"
fi

say "Setup complete"
cat <<'EOF'

  Next steps:
    1. Put your Gemini API key in .env:
         GOOGLE_API_KEY=AIza...
       Get one at https://aistudio.google.com/apikey
    2. Start the demo:
         make dev
    3. Open http://localhost:3000

EOF
