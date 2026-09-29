#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Inspect local Claude Code transcripts for wedged loops. Python 3 standard library only.

Scans ~/.claude/projects/**/*.jsonl (newest first) and reports, per session:
  schedule_wakeup_overdue   a ScheduleWakeup whose delay times the grace multiplier has passed
                            with no assistant progress after it was due
  pending_bash_tool_result  a Bash tool_use with no matching tool_result older than the threshold
  transcript_parse_errors   JSONL lines that did not parse

Read-only on transcripts. The only writes are optional snapshots under --write-dir.

Usage:
  python3 loop_status.py [--json] [--home <dir>] [--limit <n>] [--watch]
  python3 loop_status.py --transcript <session.jsonl> [--json] [--watch]

Exit codes with --exit-code: 2 attention signals found, 1 transcripts could not be scanned, 0 clean.
"""
import datetime
import errno
import hashlib
import json
import os
import random
import re
import sys
import time

DEFAULT_BASH_TIMEOUT_SECONDS = 30 * 60
DEFAULT_LIMIT = 10
DEFAULT_WAKE_GRACE_MULTIPLIER = 2
DEFAULT_WATCH_INTERVAL_SECONDS = 5
SCHEMA = "neva.loop-status.v1"

USAGE = """Usage:
  python3 loop_status.py [--json] [--home <dir>] [--limit <n>] [--watch]
  python3 loop_status.py --transcript <session.jsonl> [--json] [--watch]

Options:
  --json                         Emit machine-readable status JSON
  --home <dir>                   Override the home directory to scan
  --transcript <session.jsonl>   Inspect one transcript directly (repeatable)
  --limit <n>                    Maximum recent transcripts to inspect (default: 10)
  --bash-timeout-seconds <n>     Age before a pending Bash call is stale (default: 1800)
  --wake-grace-multiplier <n>    ScheduleWakeup grace multiplier (default: 2)
  --now <time>                   Override current time (ISO, epoch ms, or "now")
  --exit-code                    Exit 2 on attention signals, 1 on scan errors
  --watch                        Refresh status until interrupted
  --watch-count <n>              Stop after n watch refreshes
  --watch-interval-seconds <n>   Seconds between watch refreshes (default: 5)
  --write-dir <dir>              Write index.json and per-session status snapshots

Examples:
  python3 loop_status.py --json
  python3 loop_status.py --transcript ~/.claude/projects/-repo/session.jsonl"""


class UsageError(Exception):
    pass


# ---------------------------------------------------------------- args

def _read_value(args, i, flag):
    if i + 1 >= len(args) or not args[i + 1] or args[i + 1].startswith("--"):
        raise UsageError(f"{flag} requires a value")
    return args[i + 1]


def _positive_number(value, flag):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise UsageError(f"{flag} must be a positive number")
    if not (n > 0) or n == float("inf"):
        raise UsageError(f"{flag} must be a positive number")
    return int(n) if n == int(n) else n


def _positive_int(value, flag):
    n = _positive_number(value, flag)
    if n != int(n):
        raise UsageError(f"{flag} must be a positive integer")
    return int(n)


def default_options():
    return {
        "bash_timeout_seconds": DEFAULT_BASH_TIMEOUT_SECONDS, "exit_code": False, "home": None,
        "json": False, "limit": DEFAULT_LIMIT, "now": None, "show_help": False, "transcript_paths": [],
        "watch": False, "watch_count": None, "wake_grace_multiplier": DEFAULT_WAKE_GRACE_MULTIPLIER,
        "watch_interval_seconds": DEFAULT_WATCH_INTERVAL_SECONDS, "write_dir": None,
    }


def parse_args(argv):
    args = list(argv)
    o = default_options()
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--help", "-h"):
            o["show_help"] = True
        elif a == "--json":
            o["json"] = True
        elif a == "--home":
            o["home"] = _read_value(args, i, a)
            i += 1
        elif a == "--transcript":
            o["transcript_paths"].append(_read_value(args, i, a))
            i += 1
        elif a == "--limit":
            o["limit"] = _positive_int(_read_value(args, i, a), a)
            i += 1
        elif a == "--bash-timeout-seconds":
            o["bash_timeout_seconds"] = _positive_number(_read_value(args, i, a), a)
            i += 1
        elif a == "--wake-grace-multiplier":
            o["wake_grace_multiplier"] = _positive_number(_read_value(args, i, a), a)
            i += 1
        elif a == "--now":
            o["now"] = _read_value(args, i, a)
            i += 1
        elif a == "--exit-code":
            o["exit_code"] = True
        elif a == "--watch":
            o["watch"] = True
        elif a == "--watch-count":
            o["watch_count"] = _positive_int(_read_value(args, i, a), a)
            i += 1
        elif a == "--watch-interval-seconds":
            o["watch_interval_seconds"] = _positive_number(_read_value(args, i, a), a)
            i += 1
        elif a == "--write-dir":
            o["write_dir"] = _read_value(args, i, a)
            i += 1
        else:
            raise UsageError(f"Unknown option: {a}. Run with --help for the list.")
        i += 1
    if o["exit_code"] and o["watch"] and o["watch_count"] is None:
        raise UsageError("--exit-code with --watch requires --watch-count so the process can exit")
    return o


def normalize(options):
    o = default_options()
    o.update({k: v for k, v in (options or {}).items() if v is not None})
    o["transcript_paths"] = o.get("transcript_paths") or []
    return o


# ---------------------------------------------------------------- time

def iso(d):
    if d is None:
        return None
    d = d.astimezone(datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_timestamp(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value / 1000.0, tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        # Same as JS new Date("123"): a bare numeric string is a year, not epoch; treat as invalid.
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(\.\d+)?(.*)", s)
    if m and m.group(2):
        # fromisoformat before 3.11 only takes 3 or 6 fractional digits
        s = m.group(1) + "." + (m.group(2)[1:] + "000000")[:6] + m.group(3)
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc) if "T" not in s and " " not in s else d.astimezone()
    return d


def get_now(o):
    v = o.get("now")
    if not v or v == "now":
        return datetime.datetime.now(datetime.timezone.utc)
    if re.fullmatch(r"\d+", str(v)):
        return datetime.datetime.fromtimestamp(int(v) / 1000.0, tz=datetime.timezone.utc)
    d = parse_timestamp(str(v))
    if d is None:
        raise UsageError("--now must be a valid timestamp (ISO 8601, epoch milliseconds, or now)")
    return d


def ms(d):
    return d.timestamp() * 1000.0


# ---------------------------------------------------------------- discovery

def home_dir(o):
    if o.get("home"):
        return os.path.abspath(os.path.expanduser(o["home"]))
    return os.environ.get("HOME") or os.environ.get("USERPROFILE") or os.path.expanduser("~")


def walk_jsonl(root):
    files, errors = [], []
    if not os.path.exists(root):
        return files, errors

    def onerror(e):
        errors.append({"code": _code(e), "message": str(e), "transcriptPath": getattr(e, "filename", None) or root})

    for d, _dirs, names in os.walk(root, onerror=onerror):
        for n in names:
            p = os.path.join(d, n)
            if n.endswith(".jsonl") and os.path.isfile(p):
                files.append(p)
    return files, errors


def _code(e):
    return errno.errorcode.get(getattr(e, "errno", 0) or 0)


def find_transcripts(o):
    if o.get("transcript_paths"):
        return [os.path.abspath(os.path.expanduser(p)) for p in o["transcript_paths"]], []
    root = os.path.join(home_dir(o), ".claude", "projects")
    files, errors = walk_jsonl(root)
    entries = []
    for p in files:
        try:
            entries.append((os.stat(p).st_mtime, p))
        except OSError as e:
            errors.append({"code": _code(e), "message": str(e), "transcriptPath": p})
    entries.sort(key=lambda x: -x[0])
    return [p for _, p in entries[: o["limit"]]], errors


# ---------------------------------------------------------------- analysis

def entry_timestamp(e):
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    return (parse_timestamp(e.get("timestamp")) or parse_timestamp(e.get("createdAt"))
            or parse_timestamp(e.get("created_at")) or parse_timestamp(msg.get("timestamp")))


def session_id_of(e, path):
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    sess = e.get("session") if isinstance(e.get("session"), dict) else {}
    base = os.path.basename(path)
    fallback = base[: -len(".jsonl")] if base.endswith(".jsonl") else base
    return (e.get("sessionId") or e.get("session_id") or sess.get("id") or msg.get("sessionId") or fallback)


def content_blocks(e):
    blocks = []
    msg = e.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        blocks.extend(msg["content"])
    if isinstance(e.get("content"), list):
        blocks.extend(e["content"])
    return blocks


def extract_tool_uses(e):
    uses = []
    for b in content_blocks(e):
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
            uses.append({"id": b["id"], "input": b.get("input") or {}, "name": b.get("name") or "unknown"})
    top = e.get("tool_use") or e.get("toolUse")
    if isinstance(top, dict) and top.get("id"):
        uses.append({"id": top["id"], "input": top.get("input") or {}, "name": top.get("name") or "unknown"})
    if e.get("type") == "tool_use" and e.get("id"):
        uses.append({"id": e["id"], "input": e.get("input") or {}, "name": e.get("name") or "unknown"})
    return uses


def extract_tool_result_ids(e):
    ids = []
    for b in content_blocks(e):
        if isinstance(b, dict) and b.get("type") == "tool_result":
            t = b.get("tool_use_id") or b.get("toolUseId") or b.get("id")
            if t:
                ids.append(t)
    top = e.get("tool_result") or e.get("toolResult") or e.get("toolUseResult")
    if isinstance(top, dict):
        t = top.get("tool_use_id") or top.get("toolUseId") or top.get("id")
        if t:
            ids.append(t)
    if e.get("type") == "tool_result":
        t = e.get("tool_use_id") or e.get("toolUseId") or e.get("id")
        if t:
            ids.append(t)
    return ids


def is_assistant_progress(e):
    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    return e.get("type") == "assistant" or msg.get("role") == "assistant" or len(extract_tool_uses(e)) > 0


def read_jsonl(path):
    entries, errors = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                v = json.loads(line)
            except ValueError:
                errors += 1
                continue
            if isinstance(v, dict):
                entries.append(v)
            else:
                errors += 1
    return entries, errors


def read_delay_seconds(inp):
    if not isinstance(inp, dict):
        return None
    delay = inp.get("delaySeconds") or inp.get("delay_seconds") or inp.get("seconds") or inp.get("delay")
    try:
        n = float(delay)
    except (TypeError, ValueError):
        return None
    if not (n > 0) or n == float("inf"):
        return None
    return int(n) if n == int(n) else n


def recommendation(signals):
    types = {s["type"] for s in signals}
    if "pending_bash_tool_result" in types:
        return "Open the transcript or interrupt the parked session; the Bash result appears stale."
    if "schedule_wakeup_overdue" in types:
        return "Open the transcript or interrupt the parked session; the scheduled wake is overdue."
    if "transcript_parse_errors" in types:
        return "Inspect the transcript; some JSONL lines could not be parsed."
    return "No stale ScheduleWakeup or Bash waits detected."


def analyze_transcript(path, options=None):
    o = normalize(options)
    path = os.path.abspath(path)
    now = o.get("now_date") or get_now(o)
    now_ms = ms(now)
    entries, parse_errors = read_jsonl(path)
    pending = {}
    latest_progress = None
    last_event = None
    latest_wake = None
    sid = os.path.basename(path)[:-6] if path.endswith(".jsonl") else os.path.basename(path)

    for e in entries:
        sid = session_id_of(e, path) or sid
        ts = entry_timestamp(e)
        if ts and (last_event is None or ts > last_event):
            last_event = ts
        if ts and is_assistant_progress(e) and (latest_progress is None or ts > latest_progress):
            latest_progress = ts
        for use in extract_tool_uses(e):
            started = ts or last_event
            inp = use["input"] if isinstance(use["input"], dict) else {}
            pending[use["id"]] = {
                "command": str(inp["command"]) if inp.get("command") else None,
                "input": use["input"],
                "name": use["name"],
                "startedAt": iso(started),
                "toolUseId": use["id"],
            }
            if use["name"] == "ScheduleWakeup":
                delay = read_delay_seconds(inp)
                if delay and started:
                    due = started + datetime.timedelta(seconds=delay)
                    latest_wake = {
                        "delaySeconds": delay,
                        "dueAt": iso(due),
                        "reason": str(inp["reason"]) if inp.get("reason") else None,
                        "scheduledAt": iso(started),
                        "toolUseId": use["id"],
                    }
        for rid in extract_tool_result_ids(e):
            pending.pop(rid, None)

    pending_list = []
    for t in pending.values():
        st = parse_timestamp(t["startedAt"])
        item = dict(t)
        item["ageSeconds"] = max(0, int((now_ms - ms(st)) // 1000)) if st else None
        pending_list.append(item)

    signals = []
    if latest_wake:
        scheduled = parse_timestamp(latest_wake["scheduledAt"])
        due = parse_timestamp(latest_wake["dueAt"])
        threshold = (ms(scheduled) + latest_wake["delaySeconds"] * o["wake_grace_multiplier"] * 1000) if scheduled else None
        progressed = bool(due and latest_progress and latest_progress >= due)
        if threshold is not None and now_ms >= threshold and not progressed:
            signals.append({
                "delaySeconds": latest_wake["delaySeconds"],
                "dueAt": latest_wake["dueAt"],
                "overdueSeconds": max(0, int((now_ms - ms(due)) // 1000)) if due else None,
                "scheduledAt": latest_wake["scheduledAt"],
                "toolUseId": latest_wake["toolUseId"],
                "type": "schedule_wakeup_overdue",
            })
    for t in pending_list:
        if t["name"] == "Bash" and t["ageSeconds"] is not None and t["ageSeconds"] >= o["bash_timeout_seconds"]:
            signals.append({
                "ageSeconds": t["ageSeconds"],
                "command": t["command"],
                "startedAt": t["startedAt"],
                "thresholdSeconds": o["bash_timeout_seconds"],
                "toolUseId": t["toolUseId"],
                "type": "pending_bash_tool_result",
            })
    if parse_errors > 0:
        signals.append({"count": parse_errors, "type": "transcript_parse_errors"})

    return {
        "eventCount": len(entries),
        "lastEventAt": iso(last_event),
        "latestWake": latest_wake,
        "parseErrors": parse_errors,
        "pendingTools": pending_list,
        "projectSlug": os.path.basename(os.path.dirname(path)),
        "recommendedAction": recommendation(signals),
        "sessionId": sid,
        "signals": signals,
        "state": "attention" if signals else "ok",
        "transcriptPath": path,
    }


def build_status(options=None):
    o = normalize(options)
    now = get_now(o)
    o["now_date"] = now
    home = home_dir(o)
    paths, errors = find_transcripts(o)
    sessions = []
    for p in paths:
        try:
            sessions.append(analyze_transcript(p, o))
        except OSError as e:
            errors.append({"code": _code(e), "message": str(e), "transcriptPath": p})
    sessions.sort(key=lambda s: s["lastEventAt"] or "", reverse=True)
    sessions.sort(key=lambda s: 0 if s["state"] == "attention" else 1)
    return {
        "generatedAt": iso(now),
        "errors": errors,
        "schemaVersion": SCHEMA,
        "sessions": sessions,
        "source": {
            "bashTimeoutSeconds": o["bash_timeout_seconds"],
            "homeDir": home,
            "limit": o["limit"],
            "transcriptCount": len(paths),
            "transcriptRoot": os.path.join(home, ".claude", "projects"),
            "wakeGraceMultiplier": o["wake_grace_multiplier"],
        },
    }


# ---------------------------------------------------------------- output

def format_text(payload):
    skipped = [f"  - {e['transcriptPath']}: {e['message']}" for e in payload["errors"]]
    head = f"Neva loop status ({payload['generatedAt']})"
    if not payload["sessions"]:
        lines = [head, "No readable Claude transcript JSONL files were found." if skipped
                 else f"No Claude transcript JSONL files found under {payload['source']['transcriptRoot']}."]
        if skipped:
            lines += ["Skipped transcript errors:"] + skipped
        return "\n".join(lines)
    lines = [head]
    for s in payload["sessions"]:
        lines.append(f"- {s['sessionId']} [{s['state']}] {s['transcriptPath']}")
        lines.append(f"  last event: {s['lastEventAt'] or 'unknown'}; events: {s['eventCount']}")
        lines.append("  signals: " + (", ".join(x["type"] for x in s["signals"]) or "none"))
        lines.append(f"  action: {s['recommendedAction']}")
    if skipped:
        lines += ["Skipped transcript errors:"] + skipped
    return "\n".join(lines)


def _hash(v):
    return hashlib.sha256(str(v).encode("utf-8")).hexdigest()


def _reserved(v):
    return re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])", str(v).split(".")[0], re.I) is not None


def sanitize_snapshot_name(value, fallback="session"):
    raw = str(value or "").strip() or fallback
    s = re.sub(r"[^a-zA-Z0-9._-]", "_", raw).strip("_")
    if s and len(s) <= 96 and not _reserved(s):
        return s
    if s and _reserved(s):
        suffix = _hash(raw)[:8]
        dot = s.find(".")
        return f"{s}-{suffix}" if dot == -1 else f"{s[:dot]}-{suffix}{s[dot:]}"
    prefix = re.sub(r"[._-]+$", "", s[:48]) if s else fallback
    return f"{prefix or fallback}-{_hash(raw)[:12]}"


def atomic_write_json(path, payload):
    data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = f"{path}.{os.getpid()}.{int(time.time() * 1000)}.{random.getrandbits(32):08x}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError as ce:
            sys.stderr.write(f"[loop-status] WARNING: could not remove temporary snapshot file {tmp}: {ce}\n")
        raise


def snapshot_path(out_dir, session, used):
    base = sanitize_snapshot_name(session["sessionId"])
    suffix_hash = _hash(session.get("transcriptPath") or session["sessionId"])[:8]
    for attempt in range(1000):
        suffix = "" if attempt == 0 else f"-{suffix_hash}" + ("" if attempt == 1 else f"-{attempt}")
        name = f"{base}{suffix}.json"
        if name not in used:
            used.add(name)
            return os.path.join(out_dir, name)
    raise RuntimeError(f"Could not allocate a snapshot filename for session {session['sessionId']}")


def write_snapshots(payload, write_dir):
    if not write_dir:
        return None
    out = os.path.abspath(os.path.expanduser(write_dir))
    os.makedirs(out, exist_ok=True)
    used = {"index.json"}
    rows = []
    for s in payload["sessions"]:
        p = snapshot_path(out, s, used)
        atomic_write_json(p, {"generatedAt": payload["generatedAt"], "schemaVersion": "neva.loop-status.session.v1",
                              "session": s})
        rows.append({"lastEventAt": s["lastEventAt"], "sessionId": s["sessionId"],
                     "signalTypes": [x["type"] for x in s["signals"]], "snapshotPath": p,
                     "state": s["state"], "transcriptPath": s["transcriptPath"]})
    index = os.path.join(out, "index.json")
    atomic_write_json(index, {"errors": payload["errors"], "generatedAt": payload["generatedAt"],
                              "schemaVersion": "neva.loop-status.index.v1", "sessionCount": len(payload["sessions"]),
                              "sessions": rows, "source": payload["source"]})
    return {"indexPath": index, "sessionCount": len(payload["sessions"])}


def try_write_snapshots(payload, o):
    if not o.get("write_dir"):
        return None
    try:
        return write_snapshots(payload, o["write_dir"])
    except (OSError, RuntimeError) as e:
        sys.stderr.write(f"[loop-status] WARNING: could not write status snapshots: {e}\n")
        return None


def write_status(payload, o):
    if o["json"]:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) if o["watch"] else json.dumps(payload, indent=2, ensure_ascii=False)
        print(text, flush=True)
    else:
        print(format_text(payload), flush=True)


def status_exit_code(payload):
    if any(s["state"] == "attention" for s in payload["sessions"]):
        return 2
    if payload["errors"]:
        return 1
    return 0


def run_watch(o):
    o = normalize(o)
    iteration, code = 0, 0
    while o["watch_count"] is None or iteration < o["watch_count"]:
        if iteration > 0 and not o["json"]:
            print("")
        payload = build_status(o)
        try_write_snapshots(payload, o)
        write_status(payload, o)
        code = max(code, status_exit_code(payload))
        iteration += 1
        if o["watch_count"] is not None and iteration >= o["watch_count"]:
            break
        time.sleep(o["watch_interval_seconds"])
    return code


def main(argv=None):
    try:
        o = parse_args(sys.argv[1:] if argv is None else argv)
        if o["show_help"]:
            print(USAGE)
            return 0
        if o["watch"]:
            code = run_watch(o)
            return code if o["exit_code"] else 0
        payload = build_status(o)
        try_write_snapshots(payload, o)
        write_status(payload, o)
        return status_exit_code(payload) if o["exit_code"] else 0
    except UsageError as e:
        sys.stderr.write(f"[loop-status] {e}\n")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
