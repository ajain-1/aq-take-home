#!/bin/bash
python3 -c "bytearray(3 * 1024**3)"
echo $? > /app/alloc_exit.txt
