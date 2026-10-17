#!/bin/bash
# Usage: verify_task.sh <task-dir> <mode: oracle|nop> <logfile>
TASK_DIR="$1"; MODE="$2"; LOG="$3"
NAME=$(basename "$TASK_DIR")
IMG="aq-verify-$NAME"
CTR="aq-verify-$NAME-$MODE"
exec > "$LOG" 2>&1
set -x
docker build -q -t "$IMG" "$TASK_DIR" || { echo "BUILD FAILED"; exit 1; }
docker rm -f "$CTR" >/dev/null 2>&1
docker run -d --name "$CTR" -e TEST_DIR=/tests "$IMG" sh -c "sleep infinity"
if [ "$MODE" = oracle ]; then
  docker exec "$CTR" mkdir -p /oracle
  docker cp "$TASK_DIR/solution.sh" "$CTR:/oracle/solution.sh"
  if [ "$NAME" = broken-flask-api ]; then
    docker exec -d "$CTR" bash -c "bash /oracle/solution.sh > /tmp/oracle.log 2>&1; sleep infinity"
    sleep 30
    docker exec "$CTR" cat /tmp/oracle.log | tail -5
  else
    docker exec "$CTR" bash /oracle/solution.sh
  fi
fi
docker exec "$CTR" mkdir -p /tests
docker cp "$TASK_DIR/run-tests.sh" "$CTR:/tests/run-tests.sh"
docker cp "$TASK_DIR/tests/." "$CTR:/tests/"
START=$(date +%s)
docker exec "$CTR" bash /tests/run-tests.sh
echo "TEST_DURATION_SEC=$(( $(date +%s) - START ))"
docker rm -f "$CTR" >/dev/null
