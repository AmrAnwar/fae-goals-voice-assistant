#!/usr/bin/env bash
# Bring up minikube + Temporal (PostgreSQL, frontend, web UI) and expose the
# frontend/UI on localhost.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data

# Homebrew is not always on PATH in non-login shells.
if [ -d /opt/homebrew/bin ]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi

say() { printf '\n\033[1;35m✦ %s\033[0m\n' "$1"; }
warn() { printf '\n\033[1;33m! %s\033[0m\n' "$1"; }

need() {
  local bin="$1" formula="${2:-$1}"
  if ! command -v "$bin" >/dev/null 2>&1; then
    warn "$bin is missing. Install it with: brew install $formula"
    exit 1
  fi
}

need docker docker
need minikube minikube
need kubectl kubernetes-cli
need helm helm

# ------------------------------------------------------------------- docker
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    say "Starting the Docker VM with Colima"
    colima start --cpu 6 --memory 12 --disk 60 --vm-type vz
  else
    warn "No Docker daemon is reachable and Colima is not installed."
    echo "  Start Docker Desktop, or install Colima: brew install colima"
    exit 1
  fi
fi

# ----------------------------------------------------------------- minikube
if ! minikube status >/dev/null 2>&1; then
  say "Starting minikube"
  minikube start --driver=docker --cpus=4 --memory=8g --disk-size=40g
fi

# ----------------------------------------------------------------- postgres
say "Applying PostgreSQL"
kubectl apply -f deploy/temporal/postgres.yaml
kubectl -n temporal rollout status statefulset/temporal-postgres --timeout=300s

# ----------------------------------------------------------------- temporal
if ! helm repo list 2>/dev/null | awk '{print $1}' | grep -qx temporal; then
  say "Adding the Temporal Helm repository"
  # helm.temporal.io does not resolve on every network; this GitHub Pages
  # mirror serves the same chart index.
  helm repo add temporal https://temporalio.github.io/helm-charts
fi
helm repo update temporal >/dev/null

say "Installing/upgrading Temporal (this can take a few minutes on first run)"
helm upgrade --install temporal temporal/temporal \
  --namespace temporal \
  --values deploy/temporal/values.yaml \
  --timeout 15m \
  --wait

# ------------------------------------------------------------ port forwards
start_forward() {
  local name="$1" svc="$2" ports="$3" port="${3%%:*}"
  local pidfile="data/temporal-${name}.pid"

  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    say "Port-forward for ${name} already running"
    return 0
  fi

  nohup kubectl -n temporal port-forward "svc/${svc}" "${ports}" \
    > "data/temporal-${name}.log" 2>&1 &
  echo "$!" > "$pidfile"

  for _ in $(seq 1 40); do
    if nc -z 127.0.0.1 "${port}" 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done

  warn "Port-forward for ${name} did not become ready. See data/temporal-${name}.log"
  return 1
}

say "Exposing Temporal on localhost"
start_forward frontend temporal-frontend 7233:7233
start_forward web temporal-web 8080:8080

kubectl -n temporal get pods
cat <<'EOF'

  ┌──────────────────────────────────────────────────────────────┐
  │  Temporal frontend   localhost:7233                          │
  │  Temporal Web UI     http://localhost:8080                   │
  │                                                              │
  │  Next, in another terminal:                                  │
  │    make temporal-worker     # run the worker                 │
  │    make temporal-schedule   # create the daily schedule      │
  │    make temporal-run        # trigger a check-in right now   │
  └──────────────────────────────────────────────────────────────┘

EOF
