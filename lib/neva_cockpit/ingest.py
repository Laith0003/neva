"""Incremental ingest from what the hooks runtime already writes, into the cockpit store.

Every source is read tail-only: nothing here loads a whole transcript or a whole growing log.
`ingest_offsets` remembers (path, offset, mtime, size) per source file, so re-running the
ingester after nothing changed inserts zero new rows, and a file that shrank (rotated or
truncated under us) is re-read from the start rather than silently skipped.

Sources, matching what plugins/neva-core/hooks/neva_hooks already writes:
  sessions_dir() *-session.tmp   header fields (project, branch, session id, timestamps)
  metrics/costs.jsonl            cumulative cost per session, and context tokens via the
                                  transcript_path it records (context_tokens does the bounded
                                  tail read; this module never opens a transcript itself)
  observations/<id>/observations.jsonl   risk flags: tool errors, a short list of destructive
                                  bash patterns
  ~/.codex/sessions/**/rollout-*.jsonl   only the first (session_meta) line is read, for id,
                                  cwd and start time; mtime gives last activity

hooks.log is intentionally not folded into any session's risk_flags: its lines are not
attributable to a session id (see module docstring in neva_hooks/common.py). Its new error
lines, and every rejected source line, go into the store's ingest_notes table in the same
transaction that advances that file's offset, and the views show them as standalone panels
instead of guessing which session they belong to.
"""
import datetime
import glob
import hashlib
import json
import math
import os
import re

from . import hooks_common
from .store import Store

CONTEXT_WINDOW_TOKENS = 200_000  # Claude's context window; used only to render a percentage
HEAD_BYTES = 4096  # enough for a session summary's header block
# Codex writes the whole system prompt (base_instructions) into the session_meta line: 18 KB to
# 42 KB on a real machine in 2026-10. The cap only stops a runaway line from being read whole.
CODEX_FIRST_LINE_MAX = 1 << 20
TAIL_BYTES = 256 * 1024  # mirrors neva_hooks.common.context_tokens's bounded tail read

HEADER_LINE_RE = re.compile(r"^\*\*([^:*]+):\*\*\s*(.*)$", re.M)

RISKY_BASH = [
    (re.compile(r"\brm\s+-rf\b"), "destructive-bash:rm-rf"),
    (re.compile(r"\bgit\s+push\s+(?:--force|-f)\b"), "destructive-bash:force-push"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "destructive-bash:reset-hard"),
    (re.compile(r"\bDROP\s+TABLE\b", re.I), "destructive-bash:drop-table"),
    (re.compile(r"\bcurl\b[^|]*\|\s*(?:sh|bash)\b"), "destructive-bash:curl-pipe-shell"),
]


SIGNATURE_BYTES = 4096  # read from each end of the consumed region to recognise the file


def _signature(path, offset):
    """A hash of the first and the last SIGNATURE_BYTES of the region already consumed, so a
    file rewritten with other content (same size or regrown past the old size, same inode or
    not) no longer matches the offset recorded for it. Two small reads, never the whole file."""
    if offset <= 0:
        return ""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            digest.update(fh.read(min(offset, SIGNATURE_BYTES)))
            fh.seek(max(0, offset - SIGNATURE_BYTES))
            digest.update(fh.read(min(offset, SIGNATURE_BYTES)))
    except OSError:
        return ""
    return digest.hexdigest()


def _record_offset(store, path, offset, st, notes=()):
    """Advance past what was read, saving its notes in the same transaction."""
    store.advance(path, offset, st.st_mtime, st.st_size, st.st_ino, _signature(path, offset),
                  notes)


def _stamp():
    return hooks_common.now().isoformat(timespec="seconds")


def _changed(store, path, st):
    """(needs reading, offset to read from). A new file reads from 0; an unchanged one is
    skipped; a grown one continues at its offset. The offset is thrown away, and the file read
    from the start, when it is no longer the file the offset was recorded for: a different
    inode (rotated or replaced), a size below what was consumed (truncated), or consumed bytes
    that no longer hash the same (rewritten in place, whatever the new size)."""
    prev = store.get_offset(path)
    if prev is None:
        return True, 0
    if prev.get("inode") and prev["inode"] != st.st_ino:
        return True, 0
    if prev["mtime"] == st.st_mtime and prev["size"] == st.st_size:
        return False, prev["offset"]
    if st.st_size < prev["size"] or st.st_size < prev["offset"]:
        return True, 0
    if prev.get("signature") and _signature(path, prev["offset"]) != prev["signature"]:
        return True, 0
    return True, prev["offset"]


class RejectedRow(ValueError):
    """A line that is valid JSON but not a record this source writes: wrong shape or wrong field
    type. Raised by an apply function, caught per line by _ingest_jsonl_tail. Database errors
    are deliberately not this type, so they still stop the run before the offset advances."""


def _string_field(row, key, required=False):
    value = row.get(key)
    if value is None:
        if required:
            raise RejectedRow(f"{key} is missing")
        return ""
    if not isinstance(value, str):
        raise RejectedRow(f"{key} must be a string, got {type(value).__name__}")
    return value.strip()


def _number_field(row, key):
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RejectedRow(f"{key} must be a finite number, got {type(value).__name__}")
    try:
        number = float(value)  # a JSON integer can be too large for a float
    except OverflowError:
        raise RejectedRow(f"{key} is too large to be a number of dollars") from None
    if not math.isfinite(number):
        raise RejectedRow(f"{key} must be a finite number, got {number}")
    return number


def _present(update):
    """Drop empty values, so a source that lacks a field never blanks what another wrote."""
    return {k: v for k, v in update.items() if v not in ("", None)}


def _ingest_jsonl_tail(store, path, apply_fn, rejected=None):
    """Read only the complete lines appended since the last recorded offset. A line that is
    not valid JSON, or is JSON of the wrong shape or field types, is skipped; it never stops
    the lines around it from landing, and the offset always moves past it. Each skipped line is
    appended to `rejected` (when given) as {"path", "line", "reason"}, line counted from 1
    within this read, and stored as a rejected-row note in the same transaction that moves the
    offset past it, so a failed save never loses the note."""
    if not path or not os.path.isfile(path):
        return 0
    try:
        st = os.stat(path)
    except OSError:
        return 0
    changed, offset = _changed(store, path, st)
    if not changed:
        return 0
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    cut = data.rfind(b"\n") + 1  # only complete lines; a half-written tail waits for next time
    if not cut:
        _record_offset(store, path, offset, st)
        return 0
    count = 0
    skipped = []
    for number, raw in enumerate(data[:cut].splitlines(), start=1):
        line = raw.decode("utf-8", "ignore").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RejectedRow(f"expected a JSON object, got {type(row).__name__}")
            applied = apply_fn(store, row)
        except RejectedRow as error:
            skipped.append({"path": path, "line": number, "reason": str(error)})
            continue
        except ValueError:
            skipped.append({"path": path, "line": number, "reason": "not valid JSON"})
            continue
        if applied:
            count += 1
    notes = [("rejected-row", [f"{r['path']} line {r['line']}: {r['reason']}" for r in skipped],
              _stamp())] if skipped else []
    _record_offset(store, path, offset + cut, st, notes)
    if rejected is not None:
        rejected.extend(skipped)
    return count


# ---------------------------------------------------------------- costs.jsonl

def _apply_cost_row(store, row):
    session_id = _string_field(row, "session_id")
    if not session_id:
        return False
    cost = _number_field(row, "estimated_cost_usd")
    project = _string_field(row, "project")
    timestamp = _string_field(row, "timestamp")
    # Only what this row actually carries: an absent field must not blank what the session
    # summary or an earlier row already wrote (review M4).
    update = {"id": session_id, "harness": "claude"}
    if project:
        update["project"] = project
    if timestamp:
        update["last_activity"] = timestamp
    if cost is not None:
        update["cost_usd"] = cost
    transcript_path = _string_field(row, "transcript_path")
    if transcript_path and os.path.isfile(transcript_path):
        tokens, _model = hooks_common.context_tokens(transcript_path, tail_bytes=TAIL_BYTES)
        if tokens:
            update["context_pct"] = round(min(100.0, tokens / CONTEXT_WINDOW_TOKENS * 100), 1)
    store.upsert_session(update)
    return True


def ingest_costs(store, path=None, rejected=None):
    return _ingest_jsonl_tail(store, path or hooks_common.costs_path(), _apply_cost_row,
                              rejected)


# ---------------------------------------------------------------- observations.jsonl

TRUNCATED_RE = re.compile(r"\.\.\.\[truncated \d+ chars\]$")  # observe._truncate's suffix


def _bash_command(row):
    """(command text, truncated). observe._truncate cuts a long input at 5000 characters and
    appends `...[truncated N chars]`, after which the JSON no longer parses. The raw string
    still holds the start of the command verbatim, so the patterns run over that instead of
    over nothing, and `truncated` says the rest was never seen."""
    inp = row.get("input")
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except ValueError:
            return inp, bool(TRUNCATED_RE.search(inp))
    return (str(inp.get("command") or "") if isinstance(inp, dict) else ""), False


def _apply_observation(store, row):
    session_id = _string_field(row, "session")
    if not session_id or session_id == "unknown":
        return False
    flags = []
    event = _string_field(row, "event")
    tool = _string_field(row, "tool") or "unknown"
    if event == "tool_error":
        flags.append(f"tool-error:{tool}")
    elif event == "tool_start" and tool == "Bash":
        command, truncated = _bash_command(row)
        for pattern, label in RISKY_BASH:
            if pattern.search(command):
                flags.append(label)
        if truncated:
            flags.append("bash-input-truncated")  # never silently clean: the tail was unseen
    project = _string_field(row, "project_name")
    if project:
        store.upsert_session({"id": session_id, "harness": "claude", "project": project})
    if flags:
        store.add_risk_flags(session_id, flags)
    elif not project:
        # nothing to record for this line, but it still counted as ingested
        pass
    return True


def ingest_observations(store, path, rejected=None):
    return _ingest_jsonl_tail(store, path, _apply_observation, rejected)


def ingest_all_observations(store, rejected=None):
    root = hooks_common.observations_dir()
    total = 0
    try:
        project_ids = sorted(os.listdir(root))
    except OSError:
        return 0
    for project_id in project_ids:
        path = os.path.join(root, project_id, "observations.jsonl")
        total += ingest_observations(store, path, rejected)
    return total


# ---------------------------------------------------------------- session summary files

def _parse_header_fields(text):
    return {m.group(1).strip(): m.group(2).strip() for m in HEADER_LINE_RE.finditer(text)}


def ingest_session_files(store, sessions_dir=None):
    sessions_dir = sessions_dir or hooks_common.sessions_dir()
    try:
        names = os.listdir(sessions_dir)
    except OSError:
        return 0
    count = 0
    for name in names:
        if not name.endswith("-session.tmp"):
            continue
        path = os.path.join(sessions_dir, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        changed, _offset = _changed(store, path, st)
        if not changed:
            continue
        fields = _parse_header_fields(hooks_common.read_text(path, limit=HEAD_BYTES))
        session_id = fields.get("Session", "").strip()
        if session_id:
            date = fields.get("Date", "").strip()
            store.upsert_session(_present({
                "id": session_id,
                "harness": "claude",
                "project": fields.get("Project", "").strip(),
                "branch": fields.get("Branch", "").strip(),
                "started_at": " ".join(p for p in (date, fields.get("Started", "").strip()) if p),
                "last_activity": " ".join(
                    p for p in (date, fields.get("Last Updated", "").strip()) if p),
            }))
            count += 1
        _record_offset(store, path, st.st_size, st)
    return count


# ---------------------------------------------------------------- codex sessions

class _CodexLineRejected(Exception):
    """The first line is complete, or over the cap, and is not a session record we can read."""


def _codex_first_line(path):
    """The first line as a dict, or "incomplete" while Codex is still writing it (no newline
    yet, under the cap). Raises _CodexLineRejected, with the reason, for a line over
    CODEX_FIRST_LINE_MAX or one that is not a JSON object."""
    with open(path, "rb") as fh:
        line = fh.readline(CODEX_FIRST_LINE_MAX + 1)
    if not line.endswith(b"\n"):
        if len(line) > CODEX_FIRST_LINE_MAX:
            raise _CodexLineRejected(
                f"first line is longer than the {CODEX_FIRST_LINE_MAX}-byte cap; "
                "fix: raise ingest.CODEX_FIRST_LINE_MAX if Codex really writes lines this long")
        return "incomplete"
    try:
        meta = json.loads(line.decode("utf-8", "ignore"))
    except ValueError:
        raise _CodexLineRejected("first line is not valid JSON") from None
    if not isinstance(meta, dict):
        raise _CodexLineRejected(f"first line is JSON {type(meta).__name__}, not an object")
    return meta


def _codex_session_meta(meta):
    """The session metadata payload, the way Codex itself reads it: a `session_meta` line's
    payload, or (older rollouts) the bare first-line object. The session id is
    payload.session_id, falling back to payload.id exactly as Codex's SessionMetaLine
    deserializer does for records written before session_id existed."""
    if meta.get("type") == "session_meta":
        payload = meta.get("payload")
    elif "type" not in meta and "payload" not in meta:
        payload = meta
    else:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    for key in ("session_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), payload
    return None, None


def _mtime_iso(st):
    tz = hooks_common.now().tzinfo
    return datetime.datetime.fromtimestamp(st.st_mtime, tz).isoformat(timespec="seconds")


def ingest_codex_sessions(store, root=None, rejected=None):
    """One session per rollout file, from its first (session_meta) line. A file whose first
    line cannot be read as a session record is never silently marked read: it becomes a
    rejected-row note, saved with its offset, once per file (not again on every append)."""
    root = root or os.path.join(hooks_common.home(), ".codex", "sessions")
    if not os.path.isdir(root):
        return 0
    count = 0
    for path in glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True):
        try:
            st = os.stat(path)
        except OSError:
            continue
        changed, _offset = _changed(store, path, st)
        if not changed:
            continue
        reason = None
        try:
            meta = _codex_first_line(path)
        except OSError:
            continue
        except _CodexLineRejected as error:
            meta, reason = None, str(error)
        if meta == "incomplete":
            continue  # Codex is still writing the first line; read it next time
        session_id, payload = _codex_session_meta(meta) if meta else (None, None)
        if meta and not session_id:
            reason = "first line is not a session_meta record with a session_id or id"
        if reason:
            prev = store.get_offset(path)
            already_noted = prev is not None and prev.get("inode") == st.st_ino
            entry = {"path": path, "line": 1, "reason": reason}
            if rejected is not None:
                rejected.append(entry)
            notes = [] if already_noted else [
                ("rejected-row", [f"{path} line 1: {reason}"], _stamp())]
            _record_offset(store, path, st.st_size, st, notes)
            continue
        if session_id:
            cwd = payload.get("cwd")
            cwd = cwd if isinstance(cwd, str) else ""
            started = payload.get("timestamp")
            store.upsert_session(_present({
                "id": session_id,
                "harness": "codex",
                "project": os.path.basename(cwd.rstrip("/")) if cwd else "",
                "started_at": started if isinstance(started, str) else "",
                "last_activity": _mtime_iso(st),
            }))
            count += 1
        _record_offset(store, path, st.st_size, st)
    return count


# ---------------------------------------------------------------- hooks.log (not session-scoped)

HOOK_ERROR_MAX_CHARS = 400
_TRACEBACK_HEAD = "Traceback (most recent call last):"
_TRACE_FILE_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def _summarize_hook_error(record):
    """One panel line for one hooks.log error record. neva_hooks.common.log_exception writes
    `[error] <where>: ` plus the traceback, its lines indented four spaces, so the first
    physical line is always "Traceback (most recent call last):". Keep `<where>`, the last line
    (the exception type and message) and where it was raised, bounded to HOOK_ERROR_MAX_CHARS
    with the location kept even when the message is cut."""
    head, rest = record[0].rstrip(), [ln.strip() for ln in record[1:] if ln.strip()]
    if not rest:
        return head[:HOOK_ERROR_MAX_CHARS]
    if head.endswith(_TRACEBACK_HEAD):
        head = head[:-len(_TRACEBACK_HEAD)].rstrip()
    message = rest[-1]
    frames = [m for m in map(_TRACE_FILE_RE.search, rest) if m]
    suffix = ""
    if frames:
        where = frames[-1]
        suffix = f" (at {os.path.basename(where.group(1))}:{where.group(2)} in {where.group(3)})"
    room = HOOK_ERROR_MAX_CHARS - len(head) - len(suffix) - 1
    if room < 20:  # a pathological head: cut the whole line instead
        return (head + " " + message + suffix)[:HOOK_ERROR_MAX_CHARS]
    if len(message) > room:
        message = message[:room - 3] + "..."
    return f"{head} {message}{suffix}"


def _hook_error_records(lines):
    """Group each `[error]` line with the indented continuation lines under it."""
    records, current = [], None
    for line in lines:
        if current is not None and line.startswith("    "):
            current.append(line)
            continue
        if current is not None:
            records.append(current)
            current = None
        if "[error]" in line:
            current = [line]
    if current is not None:
        records.append(current)
    return [_summarize_hook_error(record) for record in records]


def ingest_hooks_log(store, path=None):
    """Return the error records newly appended to hooks.log since the last call, one summary
    line each (see _summarize_hook_error), after
    storing them as hook-error notes in the same transaction that moves the offset past them.
    They are not attributed to a session (the log line carries no session id), so they are kept
    for display rather than written into any session's risk_flags."""
    path = path or os.path.join(hooks_common.data_dir(), "hooks.log")
    if not os.path.isfile(path):
        return []
    try:
        st = os.stat(path)
    except OSError:
        return []
    changed, offset = _changed(store, path, st)
    if not changed:
        return []
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    cut = data.rfind(b"\n") + 1
    errors = _hook_error_records(data[:cut].decode("utf-8", "ignore").splitlines())
    _record_offset(store, path, offset + cut, st,
                   [("hook-error", errors, _stamp())] if errors else [])
    return errors


# ---------------------------------------------------------------- everything

def ingest_all(store=None):
    owns_store = store is None
    store = store or Store()
    rejected = []
    try:
        result = {
            "session_files": ingest_session_files(store),
            "costs": ingest_costs(store, rejected=rejected),
            "observations": ingest_all_observations(store, rejected),
            "codex_sessions": ingest_codex_sessions(store, rejected=rejected),
            "hook_errors": ingest_hooks_log(store),
            "rejected": rejected,
        }
        return result
    finally:
        if owns_store:
            store.close()
