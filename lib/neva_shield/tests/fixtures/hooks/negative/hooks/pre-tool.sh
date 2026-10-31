#!/bin/bash
payload=$(cat)
printf '%s\n' "$payload" | python3 "$(dirname "$0")/audit.py"
