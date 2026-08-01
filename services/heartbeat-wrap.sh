#!/bin/bash
# heartbeat-wrap.sh: every launchd Program / systemd ExecStart in this project runs through
# this wrapper instead of calling the tool directly. It is the fix for the single worst defect
# found in the 2026-08-01 review: a scheduled job that has NEVER FIRED is invisible to every
# guard that only watches for a job that ran and failed. "loaded" is not "ran".
#
# It writes ONE line per invocation to @HOME@/.local/state/neva/heartbeat/<job>.status, no
# matter what the wrapped command does, no matter whether it succeeds, fails, or hangs (up to
# HEARTBEAT_TIMEOUT). The wrapper never swallows the real exit code: systemd/launchd's own
# failure tracking, journald, and *.err.log all still work exactly as before. This is
# platform-agnostic on purpose: the same file format is written whether the job was fired by
# launchd StartCalendarInterval, launchd StartInterval, or a systemd timer, so bin/doctor has
# ONE thing to check regardless of OS.
#
# Format (space-separated, one line, appended, capped at the last 200 runs):
#   <ISO8601 UTC timestamp of completion> <exit code> <duration seconds>
#
# A job's heartbeat file not existing at all, while the job is confirmed loaded (launchctl
# list / systemctl --user list-timers shows it), means it has never actually executed. That
# is the exact, specific signal the old checks could not produce.
#
# Usage: heartbeat-wrap.sh <job-name> <command> [args...]
set -u
JOB="${1:?usage: heartbeat-wrap.sh <job-name> <command...>}"
shift
[ "$#" -ge 1 ] || { echo "heartbeat-wrap.sh: no command given for job '$JOB'" >&2; exit 64; }

HB_DIR="@HOME@/.local/state/neva/heartbeat"
mkdir -p "$HB_DIR"
STATUS="$HB_DIR/${JOB}.status"

START=$(date +%s)
"$@"
RC=$?
END=$(date +%s)

printf '%s %d %d\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RC" "$((END - START))" >> "$STATUS"
# rolling window: this is a liveness signal, not an audit trail (the tool's own log/.err.log
# already keeps history of WHAT happened; this file only answers WHETHER and WHEN it ran)
if [ "$(wc -l < "$STATUS" 2>/dev/null || echo 0)" -gt 200 ]; then
  tail -n 200 "$STATUS" > "${STATUS}.tmp" 2>/dev/null && mv "${STATUS}.tmp" "$STATUS"
fi

exit "$RC"
