#!/bin/bash
# Submit all 6 tasks and display results.
# Usage: bash scripts/run_all.sh
#
# Requires the API to be running at localhost:8000

set -e

API_URL="${API_URL:-http://localhost:8000}"

TASKS=(
    csv-to-json-cli-fix
    log-rotation-analyzer
    broken-coordinate-transform
    config-manifest-validator
    broken-flask-api
    fix-maven-artifact-dependencies
)

echo "Submitting ${#TASKS[@]} tasks to $API_URL ..."
echo ""

declare -A SUBMISSION_IDS

for task in "${TASKS[@]}"; do
    echo "--- Submitting: $task ---"
    RESULT=$(bash scripts/submit_task.sh "$task" 2>&1)
    SID=$(echo "$RESULT" | grep "Submission ID:" | awk '{print $NF}')
    if [ -n "$SID" ]; then
        SUBMISSION_IDS[$task]=$SID
        echo "  -> $SID"
    else
        echo "  -> FAILED to submit"
        echo "$RESULT"
    fi
    echo ""
done

echo "All tasks submitted. Polling for results..."
echo ""

for task in "${TASKS[@]}"; do
    SID=${SUBMISSION_IDS[$task]}
    if [ -z "$SID" ]; then
        echo "[$task] SKIPPED (no submission ID)"
        continue
    fi

    echo "[$task] Waiting..."
    while true; do
        STATUS=$(curl -s "${API_URL}/status/${SID}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
        if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
            break
        fi
        sleep 3
    done

    RESULTS=$(curl -s "${API_URL}/results/${SID}")
    PASSED=$(echo "$RESULTS" | python3 -c "import sys,json; r=json.load(sys.stdin); print(f'{r.get(\"passed_tests\",0)}/{r.get(\"total_tests\",0)} tests passed')" 2>/dev/null)
    ALL_PASS=$(echo "$RESULTS" | python3 -c "import sys,json; print('PASS' if json.load(sys.stdin).get('passed') else 'FAIL')" 2>/dev/null)

    echo "[$task] $ALL_PASS - $PASSED"
done

echo ""
echo "Done."
