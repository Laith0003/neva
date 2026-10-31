#!/bin/bash
claude --dangerously-skip-permissions -p "$1"
codex exec --dangerously-bypass-approvals-and-sandbox "$1"
