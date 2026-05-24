#!/bin/sh
# play-analytics container entrypoint.
#
# Behaviours:
#   default       run once, render, exit
#   SERVE=true    after rendering, start http.server on $PORT
#   CRON_SCHEDULE re-render on this cron expression (supercronic);
#                 if SERVE is also true, an http.server runs alongside.
set -e

cd /app

run_once() {
  echo "[entrypoint] $(date -u '+%Y-%m-%dT%H:%M:%SZ') rendering…"
  # Always disable main.py's own --serve in the container — the entrypoint
  # owns the HTTP server so the initial render returns and cron can start.
  SERVE=false python /app/main.py
}

run_once

# Start background HTTP server when SERVE=true (and cron is enabled, or always).
if [ "${SERVE:-}" = "true" ]; then
  echo "[entrypoint] starting http.server on :${PORT:-8080}"
  python -m http.server "${PORT:-8080}" \
    --bind 0.0.0.0 --directory "${OUTPUT_DIR:-/app/output}" &
fi

if [ -n "${CRON_SCHEDULE:-}" ]; then
  CRONTAB=/tmp/crontab
  # supercronic expects standard 5-field cron expressions; we re-run main.py
  # without --serve (the long-running server above keeps the dashboards live).
  echo "${CRON_SCHEDULE} cd /app && SERVE=false python main.py" > "$CRONTAB"
  echo "[entrypoint] cron: ${CRON_SCHEDULE} → main.py"
  exec supercronic -passthrough-logs "$CRONTAB"
elif [ "${SERVE:-}" = "true" ]; then
  # No cron, but we have a server in the background — keep PID 1 alive.
  wait
fi
