# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Tool-use observations for continuous learning, and the edited-files accumulator.

observe (PreToolUse, PostToolUse, PostToolUseFailure): the observation hook contract of the
  continuous-learning-v2 skill. One compact JSON line per event, appended to
    <observations dir>/<project-id>/observations.jsonl
  which is exactly what skills/continuous-learning-v2/scripts/instinct-analyze.py reads.
  Record: timestamp (UTC), event (tool_start | tool_complete | tool_error), tool, session,
  project_id, project_name, tool_use_id when present, plus input and path (tool_start),
  output (tool_complete) or error (tool_error). input and output are JSON-serialized when they
  are objects, cut to 5000 chars, and secret-scrubbed before they touch disk. Unparseable hook
  input writes {"timestamp", "event": "parse_error", "raw"}.
  Skipped (nothing written) when: NEVA_SKIP_OBSERVE=1 (the nightly job sets it), the profile is
  minimal (hooks.meta.json), agent_id is present (subagent), CLAUDE_CODE_ENTRYPOINT is set and
  not an interactive surface, the cwd contains an entry of NEVA_OBSERVE_SKIP_PATHS, or the file
  <observations dir>/disabled exists.
  The live file rotates into <project-id>/observations.pending/ at NEVA_OBSERVE_MAX_MB
  (default 10); archive files older than 30 days are pruned at session start.
  Observations are machine data: they never go into the vault and are never exported.

edit_accumulator (PostToolUse): remembers which files this response edited so the Stop hook can
  format and typecheck them once instead of after every edit.
"""
import datetime
import errno
import json
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from .learning_trigger import _learning_io

from . import common as c

MAX_FIELD = 5000
PATH_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit")
ENTRYPOINTS = ("cli", "sdk-ts", "sdk-cli", "claude-desktop", "claude-vscode")
EVENTS = {"PreToolUse": "tool_start", "PostToolUse": "tool_complete", "PostToolUseFailure": "tool_error"}
# observe runs on every tool call, after the guards whose block decision dispatch prints only
# once every module returns. A wait here delays (or, at the hook timeout, loses) that decision,
# so the lock wait and the reopen loop are both bounded and the observation is skipped instead.
LOCK_DEADLINE_S = 0.2
LOCK_POLL_S = 0.01
MAX_REOPENS = 3
_BUSY = {errno.EAGAIN, errno.EACCES, getattr(errno, "EWOULDBLOCK", errno.EAGAIN)}


def _truncate(value):
    if value is None:
        return None
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= MAX_FIELD else s[:MAX_FIELD] + f"...[truncated {len(s) - MAX_FIELD} chars]"


def skipped(ctx):
    if c.env_flag("NEVA_SKIP_OBSERVE"):
        return True
    if ctx.data.get("agent_id"):
        return True
    ep = c.env("CLAUDE_CODE_ENTRYPOINT").strip()
    if ep and ep not in ENTRYPOINTS:
        return True
    skip = c.env("NEVA_OBSERVE_SKIP_PATHS", "observer-sessions,.claude-mem")
    if any(p.strip() and p.strip() in ctx.cwd for p in skip.split(",")):
        return True
    return os.path.exists(os.path.join(c.observations_dir(), "disabled"))


def live_file(project_id):
    root = Path(c.observations_dir())
    d = _learning_io().ensure_dir(root, root / project_id)
    return os.path.join(d, "observations.jsonl")


def _rotate(path):
    limit = c.env_int("NEVA_OBSERVE_MAX_MB", 10, 1, 1000) * 1024 * 1024
    root = Path(c.observations_dir())
    io = _learning_io()
    io.check(root, path)
    try:
        if os.path.getsize(path) >= limit:
            # pending, not archive: the nightly analyser reads these first and archives only what it analysed
            arch = io.ensure_dir(root, Path(path).parent / "observations.pending")
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            target = arch / f"observations-{stamp}-{os.getpid()}.jsonl"
            io.check(root, target)
            io.check(root, path)
            os.replace(path, target)
    except OSError:
        pass


def _open_live(path):
    return _learning_io().open_append(Path(c.observations_dir()), path)


def _lock(fh, deadline):
    """Non-blocking flock retried until `deadline`. Returns None on success, else the reason."""
    if fcntl is None:
        return None
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except OSError as exc:
            if exc.errno not in _BUSY:
                return f"cannot lock it ({exc})"
        if time.monotonic() >= deadline:
            return f"locked by another process for over {LOCK_DEADLINE_S:g}s"
        time.sleep(LOCK_POLL_S)


def _append(path, rec):
    _rotate(path)
    deadline = time.monotonic() + LOCK_DEADLINE_S
    for _ in range(MAX_REOPENS):
        with _open_live(path) as fh:
            reason = _lock(fh, deadline)
            if reason:
                c.log(f"[observe] {path} {reason}; observation skipped")
                return
            try:
                current = os.stat(path)
            except FileNotFoundError:
                continue
            if os.fstat(fh.fileno()).st_ino != current.st_ino:
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # Flush before close releases the inode lock.
            fh.flush()
            return
    c.log(f"[observe] {path} was replaced on each of {MAX_REOPENS} attempts; observation skipped")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def observe(ctx):
    event = EVENTS.get(ctx.event)
    if not event or skipped(ctx):
        return None
    proj = ctx.project
    if ctx.parse_error:
        _append(live_file(proj["id"]), {"timestamp": _now(), "event": "parse_error",
                                        "raw": c.scrub(ctx.raw[:2000])})
        return None
    if not ctx.tool_name:
        return None
    rec = {
        "timestamp": _now(),
        "event": event,
        "tool": ctx.tool_name,
        "session": ctx.session_id or "unknown",
        "project_id": proj["id"],
        "project_name": proj["name"],
        "harness": ctx.harness,
    }
    if ctx.data.get("tool_use_id"):
        rec["tool_use_id"] = str(ctx.data["tool_use_id"])
    if event == "tool_start":
        rec["input"] = c.scrub(_truncate(ctx.tool_input))
        fp = ctx.file_path()
        if fp and ctx.tool_name in PATH_TOOLS:
            rec["path"] = c.scrub(fp[:1000])
    elif event == "tool_complete":
        out = ctx.data.get("tool_response", ctx.data.get("tool_output", ctx.data.get("output", "")))
        rec["output"] = c.scrub(_truncate(out))
    else:
        rec["error"] = c.scrub(_truncate(ctx.data.get("error", "")))
    _append(live_file(proj["id"]), rec)
    return None


def edit_accumulator(ctx):
    if ctx.tool_name not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return None
    fp = ctx.file_path()
    if not fp:
        return None
    fp = fp if os.path.isabs(fp) else os.path.join(ctx.cwd, fp)
    with open(ctx.state_file("edited") + ".txt", "a", encoding="utf-8") as fh:
        fh.write(os.path.realpath(fp) + "\n")
    return None
