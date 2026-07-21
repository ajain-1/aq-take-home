#!/bin/bash
# Submit a task directory to the executor API.
# Usage: bash scripts/submit_task.sh <task-name>
# Example: bash scripts/submit_task.sh csv-to-json-cli-fix

set -e

API_URL="${API_URL:-http://localhost:8000}"
TASK_NAME="${1:?Usage: $0 <task-name>}"
TASK_DIR="tasks/${TASK_NAME}"

if [ ! -d "$TASK_DIR" ]; then
    echo "Error: Task directory '$TASK_DIR' does not exist."
    echo ""
    echo "Available tasks:"
    ls -1 tasks/
    exit 1
fi

# Create a temporary ZIP
TMPZIP=$(mktemp /tmp/task-XXXXXX.zip)
trap "rm -f $TMPZIP" EXIT

echo "Zipping task: $TASK_NAME"
(cd tasks && zip -r "$TMPZIP" "$TASK_NAME" -x '*.DS_Store' '__pycache__/*')

echo "Submitting to $API_URL/submit ..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -F "file=@${TMPZIP}" \
    "${API_URL}/submit")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" -ge 400 ]; then
    echo "Error (HTTP $HTTP_CODE): $BODY"
    exit 1
fi

echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"

# Extract submission_id and poll for results
SUBMISSION_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['submission_id'])" 2>/dev/null)

if [ -n "$SUBMISSION_ID" ]; then
    echo ""
    echo "Submission ID: $SUBMISSION_ID"
    echo "Check status:  bash scripts/check_status.sh $SUBMISSION_ID"
fi
