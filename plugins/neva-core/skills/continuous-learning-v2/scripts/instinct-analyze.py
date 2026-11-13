#!/usr/bin/env python3
"""
instinct-analyze: the nightly batch job for continuous-learning-v2 (Neva).

Adapted from affaan-m/ECC (MIT), commit d3b8a3e: the analysis step of
skills/continuous-learning-v2/agents/observer-loop.sh, without the daemon.
Neva runs this once a night from a launchd/systemd timer named
instinct-analyze. There is no PID file, no signal handling, no idle loop.

Run order (each step logs to <state root>/instinct-analyze.log; state root is NEVA_STATE_DIR,
else ${XDG_STATE_HOME:-~/.local/state}/neva):
  1. apply-promotions        apply blocks the human ticked since the last run
  2. analyze                 per project bucket with >= min observations:
                             newest file first (the live file, then rotated
                             files newest to oldest), each file head first, in
                             batches of at most max_analysis_lines whose compact
                             view stays under max_view_bytes, up to
                             max_batches_per_run model calls; run the analyzer
                             with claude --print per batch on the view, accept
                             only an exact completion record, then archive
                             exactly that batch's raw lines. A failed batch is
                             retried once at half size; a file that still fails
                             waits for the next run while later files go ahead.
                             A head batch that fails on quarantine_after_failures
                             separate runs at min_batch_lines moves, raw, to
                             observations.quarantine/ (kept, never pruned).
                             Nothing unread is ever archived or deleted.
  3. decay                   -0.02 confidence per full week without observation
  4. prune                   delete pending instincts older than 30 days
  5. propose                 write new candidates to
                             <proposals dir>/Instinct promotions YYYY-MM-DD.md and one
                             pointer line under the inbox note's `## Open actions`
                             (NEVA_INBOX, default 00 Inbox/inbox.md)

Vault: NEVA_VAULT, else VAULT_PATH in the identity file. The model binary is NEVA_CLAUDE_BIN,
else `claude` on PATH. The child runs with NEVA_SKIP_OBSERVE=1, NEVA_HEADLESS=1 and
NEVA_HOOK_PROFILE=minimal, so the analysis never observes or hooks itself.

Nothing in this job writes a global instinct, skill, command, agent or rule.
The analyzer writes project-scoped instinct notes only.

Usage:
  instinct-analyze.py [--dry-run] [--project ID] [--skip-analysis] [--max-batches N]
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learning_io  # noqa: E402  managed writes refuse symlinks below their root

SKILL_DIR = Path(__file__).resolve().parent.parent
CLI = SKILL_DIR / "scripts" / "instinct-cli.py"
PROMPT_TEMPLATE = SKILL_DIR / "analyzer-prompt.md"
CONFIG_FILE = SKILL_DIR / "config.json"
UNSCOPED_ID = "unscoped"


def _abs_env(name):
    value = os.environ.get(name)
    if value and Path(value).expanduser().is_absolute():
        return Path(value).expanduser()
    return None


def _obs_root() -> Path:
    override = _abs_env("NEVA_OBSERVATIONS_DIR")
    if override:
        return override
    data = _abs_env("NEVA_DATA_DIR")
    if data:
        return data / "observations"
    xdg = _abs_env("XDG_DATA_HOME")
    return (xdg / "neva" / "observations") if xdg else Path.home() / ".local" / "share" / "neva" / "observations"


def _state_root() -> Path:
    root = _abs_env("NEVA_STATE_DIR")
    if root:
        return root
    xdg = _abs_env("XDG_STATE_HOME")
    return (xdg / "neva") if xdg else Path.home() / ".local" / "state" / "neva"


LOG_FILE = _state_root() / "instinct-analyze.log"


def _instinct_state() -> tuple:
    """(allowed root, instinct state dir), resolved exactly as instinct-cli.py resolves them."""
    override = _abs_env("NEVA_INSTINCT_STATE_DIR")
    if override:
        return override, override
    return _state_root(), _state_root() / "instincts"


def _note_hashes(instincts_dir: Path) -> dict:
    out = {}
    if instincts_dir.is_dir():
        for f in instincts_dir.glob("*.md"):
            try:
                out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                continue
    return out


def _batch_sessions(lines: list) -> dict:
    """{session id: set of ISO days} in the raw observation lines of one batch."""
    out = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        session, day = rec.get("session"), str(rec.get("timestamp") or "")[:10]
        if isinstance(session, str) and session and session != "unknown" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            out.setdefault(session.lower(), set()).add(day)
    return out


def record_note_sessions(vault: Path, instincts_dir: Path, before: dict, lines: list) -> None:
    """After a successful batch, record for every note it created or changed the sessions and days of
    that batch's own observation lines. The quality gate counts only these: sessions the engine fed the
    model when it wrote the note, never session ids the model wrote into the note."""
    after = _note_hashes(instincts_dir)
    changed = [name for name, digest in after.items() if before.get(name) != digest]
    sessions = _batch_sessions(lines)
    if not changed or not sessions:
        return
    root, state_dir = _instinct_state()
    path = state_dir / "note-sessions.json"
    learning_io.ensure_dir(root, state_dir)
    data = learning_io.read_json_object(path) if path.exists() else {}
    base = Path(vault).resolve()
    for name in changed:
        ref = "vault:" + (Path(instincts_dir).resolve() / name).relative_to(base).as_posix()
        row = data.get(ref) if isinstance(data.get(ref), dict) else {}
        for session, days in sessions.items():
            row[session] = sorted(set(row.get(session) or []) | days)
        data[ref] = row
    learning_io.write_text_atomic(root, path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    with learning_io.open_append(_state_root(), LOG_FILE) as f:
        f.write(line + "\n")
    print(line)


def load_config() -> dict:
    return learning_io.load_analyzer_config(CONFIG_FILE)

def claude_bin() -> str:
    return os.environ.get("NEVA_CLAUDE_BIN") or shutil.which("claude") or "claude"


def _child_env() -> dict:
    """The analysis child's env. NEVA_INSTINCT_BASE_URL and/or NEVA_INSTINCT_AUTH_TOKEN route
    the child at a different Anthropic-compatible endpoint: they map to the SDK's own
    ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN. Only an auth token clears ANTHROPIC_API_KEY, so the
    token wins over a key already in the environment; a base URL alone keeps that key, for a
    gateway that forwards it. Neither set means this is a no-op."""
    env = dict(os.environ, NEVA_SKIP_OBSERVE="1", NEVA_HEADLESS="1", NEVA_HOOK_PROFILE="minimal")
    base_url = os.environ.get("NEVA_INSTINCT_BASE_URL")
    auth_token = os.environ.get("NEVA_INSTINCT_AUTH_TOKEN")
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = auth_token
        env["ANTHROPIC_API_KEY"] = ""
    return env


def vault_root():
    vault = _abs_env("NEVA_VAULT")
    if vault:
        return vault
    cfg = Path(os.environ.get("NEVA_CONFIG") or Path.home() / ".config" / "neva" / "identity.env").expanduser()
    try:
        m = re.search(r'^VAULT_PATH="([^"]*)"\s*$', cfg.read_text(encoding="utf-8"), re.M)
    except OSError:
        return None
    if not m or not m.group(1):
        return None
    value = m.group(1)
    if value.startswith("$HOME"):
        value = str(Path.home()) + value[len("$HOME"):]
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


def run_cli(*args) -> int:
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        if line.strip():
            log(f"  {args[0]}: {line}")
    return result.returncode


def render_prompt(analysis_file: Path, project_id: str, project_name: str, instincts_dir: Path) -> str:
    text = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"<!-- PROMPT START -->\n(.*?)<!-- PROMPT END -->", text, re.S)
    if not m:
        raise ValueError(f"{PROMPT_TEMPLATE} has no PROMPT START/END markers")
    prompt = m.group(1)
    for key, value in {"ANALYSIS_FILE": str(analysis_file), "PROJECT_ID": project_id,
                       "PROJECT_NAME": project_name, "INSTINCTS_DIR": str(instincts_dir),
                       "TODAY": date.today().isoformat()}.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def new_token() -> str:
    """12 random hex characters, one per batch: the model can only know it by reading the batch's
    last line."""
    return secrets.token_hex(6)


COMPLETION_STATUS = "analysis_complete"


def completion_record(token: str) -> str:
    return json.dumps({"status": COMPLETION_STATUS, "token": token}, separators=(",", ":"))


def _is_completion(line: str, token: str) -> bool:
    """One decoded completion record: exactly the keys status and token, this batch's token.
    Decoded, not matched byte for byte, so spacing and key order are the model's business. Any
    extra key, a different status or another batch's token is not completion."""
    try:
        rec = json.loads(line)
    except ValueError:
        return False
    return (isinstance(rec, dict) and set(rec) == {"status", "token"}
            and rec["status"] == COMPLETION_STATUS and rec["token"] == token)


def completion_ok(stdout: str, token: str) -> bool:
    """Exactly one completion record carrying this batch's token, and it is the last non-empty
    line. A record without the token, or with another batch's token, is not completion."""
    non_empty = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    return (sum(1 for ln in non_empty if _is_completion(ln, token)) == 1
            and bool(non_empty) and _is_completion(non_empty[-1], token))


def plan_batches(lines: list, size: int, cap: int) -> list:
    """Split complete lines, head first, into ceil(len/size) near-equal batches of at most
    `size` lines, and return the first `cap` of them. Equal splitting avoids a tail batch of one
    line that would cost a whole model call."""
    size = max(1, size)
    total = -(-len(lines) // size)
    if total == 0:
        return []
    base, extra = divmod(len(lines), total)
    batches, i = [], 0
    for k in range(min(max(1, cap), total)):
        n = base + (1 if k < extra else 0)
        batches.append(lines[i:i + n])
        i += n
    return batches


def _complete_lines(path: Path) -> list:
    """Only complete lines: a trailing line without its newline may still be mid-append."""
    with open(path, "rb") as f:
        data = f.read()
    return [ln for ln in data.splitlines(keepends=True) if ln.endswith(b"\n")]


# The compact view: what the model reads instead of raw lines. The archive still gets the raw
# lines byte for byte; the view only exists in the temp analysis file.
VIEW_INPUT_CHARS = 200
VIEW_OUTPUT_CHARS = 120
VIEW_ERROR_CHARS = 400
VIEW_UNREADABLE_CHARS = 400
VIEW_METADATA = ("session", "project_id", "project_name", "harness")
# Only the view's own last line may carry these: an observation that happens to hold one is
# renamed on pass-through, so a record can never pose as the terminator and stop the model early.
RESERVED_EVENTS = ("end_of_batch", "oversized_record")
PAIRED_EVENTS = ("tool_start", "tool_complete", "tool_error")


def _cut(value, limit: int):
    if value is None:
        return None
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "..."


def _tool_half(rec: dict) -> dict:
    """One side of a tool call, fields cut. Used alone when its partner is not in the batch."""
    out = {"timestamp": rec.get("timestamp"), "event": rec.get("event"), "tool": rec.get("tool")}
    if rec.get("event") == "tool_start":
        out["input"] = _cut(rec.get("input"), VIEW_INPUT_CHARS)
        if rec.get("path"):
            out["path"] = rec["path"]
    elif rec.get("event") == "tool_complete":
        out["output"] = _cut(rec.get("output"), VIEW_OUTPUT_CHARS)
    else:
        out["error"] = _cut(rec.get("error"), VIEW_ERROR_CHARS)
    return {k: v for k, v in out.items() if v is not None}


VIEW_LINE_CHARS = 1800


def _dump(rec) -> str:
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str)


def _fit(rec: dict) -> str:
    """One view line of at most VIEW_LINE_CHARS characters. The longest field is cut, with a
    visible "...[cut N chars]" marker, until the line fits; a field that is not text is cut as
    its JSON text. A record that still cannot fit becomes one cut "oversized_record" line, so a
    record is shortened, never skipped."""
    line = _dump(rec)
    for _ in range(64):
        if len(line) <= VIEW_LINE_CHARS:
            return line
        key = max(rec, key=lambda k: len(_dump(rec[k])))
        value = rec[key]
        text = value if isinstance(value, str) else _dump(value)
        keep = max(0, len(text) - (len(line) - VIEW_LINE_CHARS) - 40)
        if keep >= len(text) or len(text) < 60:
            break
        rec = dict(rec, **{key: text[:keep] + f"...[cut {len(text) - keep} chars]"})
        line = _dump(rec)
    if len(line) <= VIEW_LINE_CHARS:
        return line
    keep = VIEW_LINE_CHARS // 3
    return _dump({"event": "oversized_record", "raw": line[:keep] + f"...[cut {len(line) - keep} chars]"})


def compact_view(lines: list, token: str = None) -> bytes:
    """The batch as the model reads it, one JSON record per line, every raw record represented:
    - a tool_start and the first later tool_complete or tool_error with the same tool_use_id
      become one `tool_call` record at the start's place (input cut to 200 chars, output to
      120, error to 400);
    - a half whose partner is not in this batch stays as its own tool_start, tool_complete or
      tool_error record, cut the same way;
    - session, project_id, project_name and harness are dropped from every record; a
      {"event": "session", "session": ...} line precedes the records of each new session;
    - any other record (user_prompt, parse_error, anything newer) passes through whole apart
      from those metadata keys;
    - a line that is not a JSON object becomes {"event": "unreadable_line", "raw": first 400};
    - a record whose own event is a reserved name (end_of_batch, oversized_record) passes
      through renamed to observed_<name>, so only the generated last line carries that name;
    - no line is longer than VIEW_LINE_CHARS (1800) characters (see _fit);
    - with a token, the last line is {"event": "end_of_batch", "records": <records above>,
      "token": <token>}: the model proves it read to the end by returning that token."""
    recs = []
    for line in lines:
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        try:
            rec = json.loads(text)
        except ValueError:
            rec = None
        recs.append(rec if isinstance(rec, dict) else {"event": "unreadable_line",
                                                       "raw": _cut(text, VIEW_UNREADABLE_CHARS)})
    results = {}
    for i, rec in enumerate(recs):
        if rec.get("event") in ("tool_complete", "tool_error") and rec.get("tool_use_id"):
            results.setdefault(str(rec["tool_use_id"]), []).append(i)
    used = set()
    out, session = [], None
    for i, rec in enumerate(recs):
        if i in used:
            continue
        if "session" in rec and rec["session"] != session:
            session = rec["session"]
            out.append({"event": "session", "session": session})
        event = rec.get("event")
        if event not in PAIRED_EVENTS:
            passed = {k: v for k, v in rec.items() if k not in VIEW_METADATA}
            if event in RESERVED_EVENTS:
                passed["event"] = "observed_" + event
            out.append(passed)
            continue
        view = _tool_half(rec)
        if event == "tool_start" and rec.get("tool_use_id"):
            partner = next((j for j in results.get(str(rec["tool_use_id"]), ()) if j > i and j not in used),
                           None)
            if partner is not None:
                used.add(partner)
                view["event"] = "tool_call"
                done = _tool_half(recs[partner])
                view.update({k: v for k, v in done.items() if k in ("output", "error")})
        out.append(view)
    text = [_fit(r) for r in out]
    if token is not None:
        text.append(_dump({"event": "end_of_batch", "records": len(text), "token": token}))
    # A lone surrogate (raw escape such as \ud83d) cannot be UTF-8; backslashreplace writes it
    # back as that same JSON escape, inside its string, so every view line stays valid JSON.
    return "".join(t + "\n" for t in text).encode("utf-8", errors="backslashreplace")


SIZE_TOKEN = "0" * 12  # same length as a real token, for measuring a view


def next_batch(remaining: list, max_lines: int, cfg: dict):
    """The next head batch of `remaining`: an equal-split share of at most `max_lines` lines,
    shrunk until its compact view fits max_view_bytes (never below one line). Returns
    (number of lines, view size in bytes)."""
    n = len(plan_batches(remaining, max_lines, 1)[0])
    size = len(compact_view(remaining[:n], SIZE_TOKEN))
    cap = cfg["max_view_bytes"]
    while size > cap and n > 1:
        n = max(1, min(n - 1, n * cap // size))
        size = len(compact_view(remaining[:n], SIZE_TOKEN))
    return n, size


FAILURES_FILE = "instinct-analyze-failures.json"


def _head_id(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()[:16]


class FailureLedger:
    """Per-file failure memory across runs, in <state root>/instinct-analyze-failures.json:
    {"<bucket id>/<file name>": {"head": <hash of the file's first line>, "size": <lines to try
    next>, "failures_at_min": <runs that failed at the minimum size>}}. An entry counts only
    while the file still starts with the same line. Written atomically through learning_io. A
    missing, corrupt or refused file never stops a run: it is logged and treated as empty, and
    a refused path is never written."""

    def __init__(self, root: Path, write: bool = True):
        self.root, self.prefix = root, "failure counter"
        self.path = root / FAILURES_FILE
        self.writable = write
        self.data = {}
        try:
            learning_io.check(root, self.path)
            self.data = learning_io.read_json_object(self.path)
        except learning_io.ManagedPathError as exc:
            log(f"{self.prefix} {self.path.name} refused: {exc} Failure counts are not kept this run.")
            self.writable = False
        except (learning_io.LearningDataError, OSError) as exc:
            log(f"{self.prefix} {self.path.name} is unreadable ({exc}); starting from no recorded "
                f"failures, the file is rewritten on the next change")

    def get(self, key: str, head: str):
        entry = self.data.get(key)
        if (isinstance(entry, dict) and entry.get("head") == head
                and type(entry.get("size")) is int and entry["size"] >= 1
                and type(entry.get("failures_at_min")) is int and entry["failures_at_min"] >= 0):
            return entry
        return None

    def set(self, key: str, entry) -> None:
        if entry is None:
            if key not in self.data:
                return
            self.data.pop(key)
        else:
            self.data[key] = entry
        if not self.writable:
            return
        try:
            learning_io.write_text_atomic(self.root, self.path,
                                          json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        except (OSError, learning_io.ManagedPathError) as exc:
            log(f"{self.prefix}: could not record failure counts in {self.path.name} ({exc}); the run continues")


def _plan(per_file: list, cfg: dict, budget: int, ledger) -> list:
    """What a run does if every batch succeeds: [(file, lines, view bytes)], newest file first,
    head first inside a file, at most `budget` batches."""
    plan = []
    for src, lines in per_file:
        pos = 0
        while budget > 0 and pos < len(lines):
            remaining = lines[pos:]
            n, size = next_batch(remaining, _start_size(ledger, src, remaining, cfg), cfg)
            plan.append((src, n, size))
            pos += n
            budget -= 1
    return plan


def _start_size(ledger, src: Path, remaining: list, cfg: dict) -> int:
    entry = ledger.get(ledger_key(src), _head_id(remaining[0])) if ledger else None
    return min(cfg["max_analysis_lines"], entry["size"]) if entry else cfg["max_analysis_lines"]


def ledger_key(src: Path) -> str:
    bucket = src.parent.parent if src.parent.name == "observations.pending" else src.parent
    return f"{bucket.name}/{src.name}"


class RunState:
    """What one run learns across buckets, so failures are judged once the run is over. Every
    model call gets a sequence number. A failure is blamed on its batch only when a call AFTER it
    in the same run succeeded: the model was demonstrably working once the failure was behind
    it. A failure with no later success may be an outage, a usage limit or a bad login that
    started mid-run, so it counts nothing and shrinks nothing."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.calls = 0
        self.last_success = 0
        self.successes = 0
        self.failures = []

    def call(self) -> int:
        self.calls += 1
        return self.calls


def analyze_bucket(obs_dir: Path, name: str, vault: Path, cfg: dict, dry_run: bool, state=None) -> None:
    """Analyse a bucket newest first: the live file, then the files the observe hook rotated into
    observations.pending/ (never yet analysed), newest to oldest. Inside a file, batches run head
    first so archive_analyzed can prove each batch is the file's head. Each model call spends one
    unit of max_batches_per_run. A batch is archived, raw, only after it succeeds; a failed batch
    is retried once at half size while budget remains; a file that still fails is left whole
    from that batch on and the run moves to the next file. Its failure is recorded in `state`
    and judged by finish_run after every bucket ran."""
    own = state is None
    if own:
        state = RunState(FailureLedger(_state_root(), write=not dry_run))
    pid = obs_dir.name
    root = obs_dir.parent
    prefix = f"{name} ({pid})"
    leftovers = interrupted_files(obs_dir)
    if leftovers and dry_run:
        log(f"{prefix}: {len(leftovers)} file(s) from an interrupted run would be recovered")
    elif leftovers:
        for path in leftovers:
            back = _restore(path, root)
            log(f"{prefix}: recovered {path.name} from an interrupted run as {back.name}")
    sources = learning_io.observation_sources(obs_dir, newest_first=True)
    if not sources:
        return
    for src in sources:
        learning_io.check(root, src)
    per_file = [(src, _complete_lines(src)) for src in sources]
    count = sum(len(lines) for _, lines in per_file)
    if count < cfg["min_observations_to_analyze"]:
        log(f"{prefix}: {count} observations < {cfg['min_observations_to_analyze']}, skipped")
        return
    ledger = state.ledger
    budget = cfg["max_batches_per_run"]
    plan = _plan(per_file, cfg, budget, ledger)
    planned = sum(n for _, n, _ in plan)
    order = []
    for src, lines in per_file:
        k = sum(1 for s, _, _ in plan if s == src)
        order.append(f"{src.name} ({len(lines)} lines, {k} batch(es))")
    kb = ", ".join(f"{size / 1024:.0f}" for _, _, size in plan)
    log(f"{prefix}: {'dry run, nothing moved: would analyze' if dry_run else 'analyzing'} {planned} of "
        f"{count} observations in {len(plan)} batch(es) of at most {budget}, newest first: "
        f"{'; '.join(order)}; view KB per batch: {kb or 'none'}"
        + (f"; {count - planned} left in place for the next run" if planned < count else ""))
    if dry_run:
        return
    archive_dir = learning_io.ensure_dir(root, obs_dir / "observations.archive")
    tmp_dir = learning_io.ensure_dir(root, obs_dir / ".analyze-tmp")
    instincts_dir = vault / "06 Memory" / "instincts" / "project" / pid
    instincts_dir.mkdir(parents=True, exist_ok=True)
    min_lines = min(cfg["min_batch_lines"], cfg["max_analysis_lines"])
    number = 0
    for src, lines in per_file:
        pos = 0
        while budget > 0 and pos < len(lines):
            remaining = lines[pos:]
            key, head = ledger_key(src), _head_id(remaining[0])
            n, size = next_batch(remaining, _start_size(ledger, src, remaining, cfg), cfg)
            number += 1
            budget -= 1
            label = f"{prefix} batch {number} ({src.name}, {n} lines, {size / 1024:.0f} KB view)"
            tried = n
            seq = state.call()
            before = _note_hashes(instincts_dir)
            outcome = run_batch(tmp_dir, pid, name, label, remaining[:n], instincts_dir, cfg)
            if outcome != "ok" and n <= min_lines:
                log(f"{label}: no half-size retry, {n} lines is already at or below the minimum of {min_lines}")
            elif outcome != "ok" and budget > 0:
                tried = min(n, max(min_lines, n // 2))
                number += 1
                budget -= 1
                label = f"{prefix} batch {number} ({src.name}, retry at half size, {tried} lines)"
                log(f"{label}: retrying the head of {src.name} at half size")
                seq = state.call()
                outcome = run_batch(tmp_dir, pid, name, label, remaining[:tried], instincts_dir, cfg)
            chunk = b"".join(remaining[:tried])
            if outcome == "ok":
                record_note_sessions(vault, instincts_dir, before, remaining[:tried])
                state.successes += 1
                state.last_success = seq
                ledger.set(key, None)
                if not archive_analyzed(src, chunk, archive_dir, root):
                    log(f"{label}: {src.name} no longer starts with the analyzed batch (rotated or rewritten "
                        f"during the run); nothing archived, observations retained for the next run")
                    break
                log(f"{label}: analysis complete; {tried} analyzed observations archived")
                pos += tried
                continue
            state.failures.append({"prefix": prefix, "src": src, "obs_dir": obs_dir, "root": root, "key": key,
                                   "head": head, "tried": tried, "waiting": len(remaining), "chunk": chunk,
                                   "outcome": outcome, "min_lines": min_lines, "seq": seq})
            log(f"{prefix}: {src.name} failed at {tried} lines ({outcome}); its {len(remaining)} unread "
                f"observations stay in place; whether this failure counts is decided at the end of the run")
            break
    if own:
        finish_run(state, cfg)


def finish_run(state, cfg: dict) -> None:
    """Judge every failure of the run at once. With no successful batch anywhere in the run the
    model was unavailable: nothing is counted and nothing moves. Otherwise each failed file's next
    start size shrinks, a failure at the minimum size counts one run, and a head that reached
    quarantine_after_failures moves, raw, to observations.quarantine/."""
    if not state.failures:
        return
    if state.successes == 0:
        names = ", ".join(f"{f['prefix']} {f['src'].name}" for f in state.failures)
        log(f"every model call this run failed ({names}); this looks like a model outage, not bad data: "
            f"no failure was counted and nothing was moved")
        return
    limit = cfg["quarantine_after_failures"]
    for f in state.failures:
        prefix, src, tried, min_lines = f["prefix"], f["src"], f["tried"], f["min_lines"]
        if f["seq"] > state.last_success:
            log(f"{prefix}: {src.name} failed at call {f['seq']} ({f['outcome']}) and no later call in this run "
                f"succeeded; it may be an outage that began mid-run, so it counts nothing and shrinks nothing")
            continue
        if tried > min_lines:
            nxt = max(min_lines, tried // 2)
            state.ledger.set(f["key"], {"head": f["head"], "size": nxt, "failures_at_min": 0})
            log(f"{prefix}: {src.name} failed at {tried} lines ({f['outcome']}) and a later call succeeded; "
                f"the next run starts it at {nxt} lines")
            continue
        entry = state.ledger.get(f["key"], f["head"])
        failures = (entry["failures_at_min"] if entry else 0) + 1
        if failures < limit:
            state.ledger.set(f["key"], {"head": f["head"], "size": min_lines, "failures_at_min": failures})
            log(f"{prefix}: {src.name} failed at the minimum size ({tried} lines, {f['outcome']}) and a later "
                f"call succeeded, run {failures} of {limit} before quarantine; its {f['waiting']} unread "
                f"observations stay in place")
            continue
        try:
            moved = quarantine(src, f["chunk"], f["obs_dir"], f["root"])
        except (OSError, learning_io.ManagedPathError) as exc:
            log(f"{prefix}: could not quarantine the head of {src.name} ({exc}); observations retained")
            continue
        if moved is None:
            log(f"{prefix}: {src.name} no longer starts with the failing batch; nothing quarantined, "
                f"observations retained for the next run")
            continue
        state.ledger.set(f["key"], None)
        log(f"{prefix}: {tried} observations at the head of {src.name} failed at the minimum size on {limit} "
            f"separate runs; moved unread, bytes intact, to observations.quarantine/{moved.name} "
            f"(kept, never pruned, not read again)")


def quarantine(src: Path, chunk: bytes, obs_dir: Path, root: Path):
    """Move the head chunk of `src` to observations.quarantine/ with archive_analyzed's head check
    and crash safety. Returns the new file, or None when `src` no longer starts with `chunk`."""
    qdir = learning_io.ensure_dir(root, obs_dir / "observations.quarantine")
    before = {p.name for p in qdir.iterdir()}
    if not archive_analyzed(src, chunk, qdir, root, prefix="quarantined"):
        return None
    new = sorted(p for p in qdir.iterdir() if p.name not in before)
    return new[-1] if new else qdir


def allowed_tools(instincts_dir) -> str:
    """The child's whole tool grant: read anything, edit only under the instincts folder.

    Claude Code accepts a Write(...) permission rule but never matches it, so it grants nothing,
    and in an Edit rule a single leading slash is relative to the project, so the folder goes in
    as //<absolute path>/**.
    Edit rules cover creating files too. Nothing wider is ever granted."""
    root = Path(instincts_dir).resolve()
    return "Read,Edit(//" + str(root).lstrip("/") + "/**)"


def analyze_batch(tmp_dir: Path, pid: str, name: str, label: str, batch: list,
                  instincts_dir: Path, cfg: dict) -> bool:
    """True only on an exact completion record. See run_batch."""
    return run_batch(tmp_dir, pid, name, label, batch, instincts_dir, cfg) == "ok"


def run_batch(tmp_dir: Path, pid: str, name: str, label: str, batch: list,
              instincts_dir: Path, cfg: dict) -> str:
    """Run the analysis child on one batch of raw lines. The child reads the batch's compact view
    (compact_view), never the raw lines. Returns "ok" only on an exact completion record, else
    "timeout", "exit <code>" or "no completion record" (exit 0 without a record carrying this
    batch's token, which the model can only take from the view's end_of_batch line). `tmp_dir` was
    checked by learning_io.ensure_dir; mkstemp creates its file with O_EXCL."""
    token = new_token()
    fd, analysis_path = tempfile.mkstemp(prefix="analysis.", suffix=".jsonl", dir=tmp_dir)
    with os.fdopen(fd, "wb") as f:
        f.write(compact_view(batch, token))
    analysis_file = Path(analysis_path)
    try:
        prompt = render_prompt(analysis_file, pid, name, instincts_dir)
        max_turns = cfg["max_turns"] or min(100, max(20, len(batch) // 10))
        if max_turns < 4:
            max_turns = 20
        env = _child_env()
        cmd = [claude_bin(), "--model", cfg["model"], "--max-turns", str(max_turns), "--print",
               "--allowedTools", allowed_tools(instincts_dir), "-p", prompt]
        proc = subprocess.Popen(cmd, cwd=str(instincts_dir), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=cfg["timeout_seconds"])
        except subprocess.TimeoutExpired:
            log(f"{label}: analysis timed out after {cfg['timeout_seconds']}s; terminating")
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.communicate()
            log(f"{label}: observations retained for retry")
            return "timeout"
        if stderr.strip():
            log(f"{label}: stderr: {stderr.strip()[-2000:]}")
        if proc.returncode != 0:
            log(f"{label}: analysis failed (exit {proc.returncode}); observations retained for retry")
            return f"exit {proc.returncode}"
        if not completion_ok(stdout, token):
            log(f"{label}: completion record with this batch's token missing; observations retained for retry")
            return "no completion record"
        return "ok"
    finally:
        try:
            analysis_file.unlink()
        except FileNotFoundError:
            pass


MOVING_PREFIX = ".observations.analyzing-"


def interrupted_files(obs_dir: Path) -> list:
    """Hidden in-flight files a run renamed aside and never finished with (crash, kill, power
    loss). Safe to recover: the analyzer lock guarantees no other run owns them."""
    found = []
    for d in (obs_dir, obs_dir / "observations.pending"):
        if d.is_dir():
            found += sorted(p for p in d.glob(MOVING_PREFIX + "*.jsonl"))
    return found


def _restore(moving: Path, root: Path) -> Path:
    """Put a renamed-aside file back where discovery reads it, without touching the live file
    the hook may have recreated since: it becomes a pending file named for the interrupted run,
    so it sorts among the rotated files by that time. A pending file gets its own name back
    (carried after the "--" in the moving name), so it keeps its place among the other pending
    files. Its lines may be analysed twice; none are lost."""
    pending = learning_io.ensure_dir(root, moving.parent if moving.parent.name == "observations.pending"
                                     else moving.parent / "observations.pending")
    learning_io.check(root, moving)
    stem = moving.name[len(MOVING_PREFIX):-len(".jsonl")]
    stamp, sep, original = stem.partition("--")
    if sep and original.startswith("observations-") and "/" not in original:
        base = original[:-len(".jsonl")] if original.endswith(".jsonl") else original
    else:
        base = "observations-" + stamp
    target = pending / f"{base}.jsonl"
    n = 1
    while target.exists() or target.is_symlink():
        target = pending / f"{base}-{n}.jsonl"
        n += 1
    os.rename(moving, target)
    return target


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def archive_analyzed(obs_file: Path, chunk: bytes, archive: Path, root: Path, prefix: str = "processed") -> bool:
    """Archive `chunk`, which must be the exact head of the file; keep everything after it,
    including anything the hook appended since. Returns False and changes nothing if the file
    no longer starts with the chunk. Every path must sit under `root` with no symlink.

    Recoverable at every step: the archive copy is written before the source moves, so a failed
    archive write leaves the source untouched; once the source is renamed aside, any failure
    puts it back as a pending file and drops the archive copy, and a run killed mid-way leaves a
    hidden file that interrupted_files() finds at the next start. Failure may analyse a line
    twice, never lose one."""
    learning_io.check(root, obs_file)
    with open(obs_file, "rb") as f:
        if f.read(len(chunk)) != chunk:
            return False
    learning_io.ensure_dir(root, archive)
    stamp = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{os.getpid()}"
    archived = archive / f"{prefix}-{stamp}.jsonl"
    learning_io.write_new(root, archived, chunk)
    moving = obs_file.parent / f"{MOVING_PREFIX}{stamp}--{obs_file.name}"
    try:
        os.rename(obs_file, moving)
    except BaseException:
        _discard(archived)
        raise
    try:
        with open(moving, "rb") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            data = f.read()
            if not data.startswith(chunk):  # changed between the check and the rename
                _discard(archived)
                _restore(moving, root)
                return False
            tail = data[len(chunk):]
            if tail:
                with learning_io.open_append(root, obs_file, binary=True) as live:
                    live.write(tail)
            moving.unlink()
    except BaseException:
        _discard(archived)
        if moving.exists():
            _restore(moving, root)
        raise
    return True


def _touch_lock(lock_fd) -> None:
    """Stamp the lock's mtime with this run's start: the same-day trigger's
    NEVA_INSTINCT_SAMEDAY_HOURS cooldown reads it. Through the descriptor learning_io already
    verified, never by path, so a symlink swapped in since cannot redirect it. Every run that
    takes the lock stamps it, --dry-run and --skip-analysis included, as the original
    open(lock, "w") did."""
    fd = lock_fd.fileno()
    if os.utime in os.supports_fd:
        os.utime(fd)
    else:
        os.ftruncate(fd, 0)


ORDER_FILE = "instinct-analyze-order.json"


def rotate_buckets(buckets: list, advance: bool) -> list:
    """The buckets in name order, rotated to start one further each run, so no bucket is always
    last when the budget or a mid-run outage cuts a night short. The start lives in
    <state root>/instinct-analyze-order.json ({"next_start": n}); a missing, corrupt or refused
    file means start 0 and never stops a run."""
    root = _state_root()
    path = root / ORDER_FILE
    start = 0
    try:
        learning_io.check(root, path)
        value = learning_io.read_json_object(path).get("next_start", 0)
        start = value if type(value) is int and value >= 0 else 0
    except learning_io.ManagedPathError as exc:
        log(f"bucket order: {exc} Starting from the first bucket; the order is not advanced.")
        advance = False
    except (learning_io.LearningDataError, OSError) as exc:
        log(f"bucket order: {path.name} is unreadable ({exc}); starting from the first bucket")
    k = start % len(buckets) if buckets else 0
    if advance:
        try:
            learning_io.write_text_atomic(root, path, json.dumps({"next_start": start + 1}) + "\n")
        except (OSError, learning_io.ManagedPathError) as exc:
            log(f"bucket order: could not record the next start in {path.name} ({exc}); the run continues")
    return buckets[k:] + buckets[:k]


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"--max-batches must be an integer >= 1, got {value!r}. "
                                         "Fix: pass a whole number such as --max-batches 8.")
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly instinct analysis (Neva)")
    parser.add_argument("--dry-run", action="store_true", help="Log what would run; call nothing")
    parser.add_argument("--project", help="Analyze one project id only")
    parser.add_argument("--skip-analysis", action="store_true", help="Run apply, decay, prune, propose only")
    parser.add_argument("--max-batches", type=_positive_int, metavar="N",
                        help="Model calls per bucket for this run only (overrides max_batches_per_run)")
    args = parser.parse_args()

    try:
        cfg = load_config()
        registry = learning_io.read_json_object(_obs_root() / "projects.json")
    except learning_io.LearningDataError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    vault = vault_root()
    if vault is None or not vault.is_dir():
        log("NEVA_VAULT is not set to an existing absolute path and the identity file has no usable VAULT_PATH. "
            "Fix: set NEVA_VAULT in the timer's environment, or VAULT_PATH in ~/.config/neva/identity.env.")
        return 2
    os.environ["NEVA_VAULT"] = str(vault)
    if args.max_batches is not None:
        cfg["max_batches_per_run"] = args.max_batches

    lock_path = _state_root() / "instinct-analyze.lock"
    try:
        lock_fd = learning_io.open_lock(_state_root(), lock_path)
    except learning_io.ManagedPathError as exc:
        log(str(exc))
        return 2
    if _HAS_FCNTL:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("previous instinct-analyze run still active; exiting")
            return 0
    _touch_lock(lock_fd)

    log(f"start (model={cfg['model']}, min={cfg['min_observations_to_analyze']}, "
        f"max_lines={cfg['max_analysis_lines']}, max_view_bytes={cfg['max_view_bytes']}, "
        f"max_batches={cfg['max_batches_per_run']}, dry_run={args.dry_run})")

    if not args.dry_run:
        run_cli("apply-promotions")

    if not args.skip_analysis:
        exe = claude_bin()
        if not (os.path.isabs(exe) and os.access(exe, os.X_OK)) and shutil.which(exe) is None:
            log("claude CLI not found on PATH; analysis skipped. Fix: add the claude binary's directory to the "
                "timer's PATH, or set NEVA_CLAUDE_BIN.")
        else:
            obs_root = _obs_root()
            state = RunState(FailureLedger(_state_root(), write=not args.dry_run)) if obs_root.is_dir() else None
            if obs_root.is_dir():
                buckets = rotate_buckets(sorted(p for p in obs_root.iterdir() if p.is_dir()),
                                         advance=not args.dry_run)
                for obs_dir in buckets:
                    if args.project and obs_dir.name != args.project:
                        continue
                    name = registry.get(obs_dir.name, {}).get("name", obs_dir.name)
                    try:
                        analyze_bucket(obs_dir, name, vault, cfg, args.dry_run, state)
                    except learning_io.ManagedPathError as exc:
                        log(f"{name} ({obs_dir.name}): {exc} Observations retained.")
                    except Exception as exc:  # one bad bucket must not stop the night
                        log(f"{name} ({obs_dir.name}): error {exc!r}; observations retained")
                finish_run(state, cfg)

    if args.dry_run:
        run_cli("decay", "--dry-run")
        run_cli("prune", "--dry-run")
        run_cli("propose", "--dry-run")
    else:
        run_cli("decay", "--quiet")
        run_cli("prune", "--quiet")
        run_cli("propose")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
