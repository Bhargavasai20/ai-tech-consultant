#!/usr/bin/env bash
# One command: starts all three tasks. Without ANTHROPIC_API_KEY it runs in MOCK mode with demo data.
set -e
cd "$(dirname "$0")/.."
if [ -z "$ANTHROPIC_API_KEY" ]; then export BRAIN_MOCK=1 INBOX_MOCK=1 SCOPE_MOCK=1; echo ">> MOCK mode (no ANTHROPIC_API_KEY): shows wiring, not model quality"; fi
export BRAIN_URL=${BRAIN_URL:-http://localhost:8001}
pids=()
trap 'kill ${pids[@]} 2>/dev/null' EXIT
if [ "$BRAIN_MOCK" = "1" ]; then (cd task1_brain && python3 -m brain.cli demo >/dev/null); fi
(cd task1_brain && python3 -m brain.cli serve --port 8001) & pids+=($!)
(cd task2_inbox && node src/server.ts) & pids+=($!)
(cd task3_scope && python3 -m scope.cli serve) & pids+=($!)
sleep 2
echo ">> Task 1 Knowledge Brain  http://localhost:8001   (API docs: /docs)"
echo ">> Task 2 Inbox Agent      http://localhost:8002"
echo ">> Task 3 Scope of Work    http://localhost:8003"
wait
