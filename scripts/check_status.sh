#!/bin/bash
# Check the status and results of a submission.
# Usage: bash scripts/check_status.sh <submission_id>
#
# With --poll flag, polls until completion:
#   bash scripts/check_status.sh <submission_id> --poll

set -e

API_URL="${API_URL:-http://localhost:8000}"
SUBMISSION_ID="${1:?Usage: $0 <submission_id> [--poll]}"
POLL="${2:-}"

fetch_status() {
    curl -s "${API_URL}/status/${SUBMISSION_ID}"
}

fetch_results() {
    curl -s "${API_URL}/results/${SUBMISSION_ID}"
}

if [ "$POLL" = "--poll" ]; then
    echo "Polling status for $SUBMISSION_ID ..."
    while true; do
        STATUS_BODY=$(fetch_status)
        STATUS=$(echo "$STATUS_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)

        echo "  Status: $STATUS"

        if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
            break
        fi
        sleep 2
    done
    echo ""
    echo "--- Results ---"
    fetch_results | python3 -m json.tool 2>/dev/null || fetch_results
else
    echo "--- Status ---"
    fetch_status | python3 -m json.tool 2>/dev/null || fetch_status
    echo ""
    echo "--- Results ---"
    fetch_results | python3 -m json.tool 2>/dev/null || fetch_results
fi
