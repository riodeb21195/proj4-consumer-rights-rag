#!/usr/bin/env bash
# Trigger the Airflow ingest DAG and wait for it to finish (used by `make ingest`).
set -euo pipefail

DAG=consumer_law_ingest
COMPOSE=(docker compose)
af() { "${COMPOSE[@]}" exec -T airflow-scheduler airflow "$@"; }

echo "Waiting for Airflow to parse the DAG ..."
for _ in $(seq 1 60); do
  if af dags list -o plain 2>/dev/null | grep -q "^${DAG}"; then break; fi
  sleep 5
done
af dags unpause "$DAG" >/dev/null

RUN_ID="make_$(date -u +%Y%m%dT%H%M%S)"
af dags trigger "$DAG" --run-id "$RUN_ID" >/dev/null
echo "Triggered $DAG run $RUN_ID (UI: http://localhost:8080)"

while true; do
  STATE=$(af dags list-runs "$DAG" -o json 2>/dev/null \
    | python3 -c "import json,sys; print(next((r['state'] for r in json.load(sys.stdin) if r['run_id']=='$RUN_ID'), 'unknown'))")
  case "$STATE" in
    success) echo "Ingest finished: success"; break ;;
    failed) echo "Ingest finished: failed (some laws may still be indexed, see Airflow UI)"; exit 1 ;;
    *) echo "  state: $STATE"; sleep 15 ;;
  esac
done
"${COMPOSE[@]}" exec -T postgres psql -U rag -d rag -c \
  "SELECT id, status, trigger, stats->'index' AS index FROM ingest_runs ORDER BY id DESC LIMIT 5;"
