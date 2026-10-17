#!/bin/bash
# Prints the timestamp of the most recent event in an asciinema v2 recording.
# Usage: get-asciinema-timestamp.sh <recording_path>

if [ $# -ne 1 ] || [ ! -f "$1" ]; then
    echo "0.0"
    exit 0
fi

last_timestamp=$(grep -E '^\[[0-9]+\.[0-9]+,' "$1" | tail -n 1 | sed -E 's/^\[([0-9]+\.[0-9]+),.*/\1/')
echo "${last_timestamp:-0.0}"
