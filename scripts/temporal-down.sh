#!/usr/bin/env bash
# Stop the Temporal port-forwards. With --purge, also uninstall the release and
# delete the temporal namespace (which destroys the Postgres volume).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d /opt/homebrew/bin ]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi

say() { printf '\n\033[1;35m✦ %s\033[0m\n' "$1"; }

for name in frontend web; do
  pidfile="data/temporal-${name}.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      say "Stopped the ${name} port-forward"
    fi
    rm -f "$pidfile"
  fi
done

if [ "${1:-}" = "--purge" ]; then
  say "Uninstalling the Temporal release"
  helm uninstall temporal --namespace temporal 2>/dev/null || true

  say "Deleting the temporal namespace and its PostgreSQL data"
  kubectl delete namespace temporal --ignore-not-found
fi

say "Done"
