# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Shared helpers for the Neva hook runtime. Standard library only.

Nothing in here may raise into the session: callers wrap every module, and helpers that
touch the filesystem or git return empty values on failure.

Paths (all overridable by environment):
  NEVA_DATA_DIR          machine data, default $XDG_DATA_HOME/neva or ~/.local/share/neva
  NEVA_STATE_DIR         machine state, default $XDG_STATE_HOME/neva or ~/.local/state/neva
                         (per-session hook state lives in its hooks/ subfolder)
  NEVA_METRICS_DIR       cost log folder, default <data dir>/metrics
  NEVA_OBSERVATIONS_DIR  tool observations, default <data dir>/observations
  NEVA_VAULT             the vault; falls back to VAULT_PATH in the identity file
  NEVA_CONFIG            identity file, default ~/.config/neva/identity.env
  NEVA_INBOX             inbox note, absolute or vault-relative (default 00 Inbox/inbox.md)
"""
import datetime
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
SUMMARY_START = "<!-- NEVA:SUMMARY:START -->"
SUMMARY_END = "<!-- NEVA:SUMMARY:END -->"
TRUE_VALUES = ("1", "true", "yes", "on", "enabled", "enable")
FALSE_VALUES = ("0", "false", "no", "off", "disabled", "disable")


# ---------------------------------------------------------------- harness payload normalization
#
# Neva's hook modules are written against the Claude Code payload: an event name plus
# tool_name, tool_input, cwd, session_id and transcript_path. Other harnesses send the
# same facts under different key names and different event names. Normalizing once here,
# at the edge, is what lets every module stay harness-agnostic and unchanged.
#
# A Claude payload is passed through untouched. Rewriting the shape Claude already sends
# could only introduce regressions, so the foreign-harness code path is never entered for
# the harness Neva runs on natively.

HARNESS_EVENTS = {
    "opencode": {
        # OpenCode plugin hooks, plus the two bus events the bridge subscribes to.
        "tool.execute.before": "PreToolUse", "tool.execute.after": "PostToolUse",
        "session.created": "SessionStart", "session.idle": "Stop",
        "command.execute.before": "UserPromptSubmit",
    },
    "cursor": {
        # Cursor hook events are camelCase; see .cursor/hooks.json.
        "sessionstart": "SessionStart", "beforeshellexecution": "PreToolUse",
        "aftershellexecution": "PostToolUse", "beforesubmitprompt": "UserPromptSubmit",
        "beforereadfile": "PreToolUse", "beforemcpexecution": "PreToolUse",
        "stop": "Stop", "sessionend": "Stop",
    },
}

# Each harness names the shell tool differently, and pre_bash only runs for "Bash".
TOOL_NAMES = {
    "bash": "Bash", "shell": "Bash", "command": "Bash", "terminal": "Bash",
    "run_shell_command": "Bash", "local_shell": "Bash", "exec": "Bash",
    # Codex unified exec. Codex matches it as Bash but the argument is `cmd`, not `command`.
    "exec_command": "Bash", "shell_command": "Bash",
    "read": "Read", "read_file": "Read", "view": "Read",
    "write": "Write", "write_file": "Write", "create_file": "Write",
    "edit": "Edit", "replace": "Edit", "str_replace": "Edit", "apply_patch": "Edit",
    "multiedit": "MultiEdit", "glob": "Glob", "grep": "Grep", "webfetch": "WebFetch",
}


def _first(data, *keys):
    """First non-empty value among keys. Harnesses disagree on spelling, not on meaning.

    A list collapses to its first entry: Cursor sends the working directory as
    `workspace_roots`, an array, where every other harness sends a plain string.
    """
    for key in keys:
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        if value not in (None, ""):
            return value
    return ""


def _mapping(value):
    return value if isinstance(value, dict) else {}


def detect_harness(data, requested=""):
    """Name the harness that sent this payload.

    An explicit NEVA_HARNESS always wins: every adapter Neva generates sets it, so
    sniffing is only the fallback for a hand-wired integration that forgot to.
    """
    value = (requested or env("NEVA_HARNESS")).strip().lower()
    if value:
        return value
    event = str(_first(data, "hook_event_name", "event", "type")).lower()
    if event.startswith(("tool.execute.", "command.execute.")) or event in ("session.created", "session.idle"):
        return "opencode"
    if "hook_event_name" in data or "transcript_path" in data:
        return "claude"
    if isinstance(data.get("tool"), dict):
        return "codex"
    return "claude"


SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
PATCH_HEADER = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)


def _normalize_shell(tool_input):
    """Give the Bash guards one command string, whatever the harness called it.

    Codex unified exec sends `cmd`; its shell tool sends an argv list, usually
    ["bash", "-lc", script], where the script is what the guards must read. A shape that
    yields no string leaves `command` absent, and the dispatcher fails that call closed.
    """
    command = tool_input.get("command")
    if command in (None, ""):
        command = tool_input.get("cmd")
    if isinstance(command, (list, tuple)) and all(isinstance(x, str) for x in command):
        argv = list(command)
        if len(argv) >= 3 and os.path.basename(argv[0]) in SHELLS and argv[1] in ("-c", "-lc", "-ic"):
            command = argv[2]
        else:
            command = " ".join(argv)
    if isinstance(command, str) and command.strip():
        tool_input["command"] = command
    else:
        tool_input.pop("command", None)


def patch_targets(patch, cwd=""):
    """Every path an apply_patch envelope adds, updates, deletes or moves to, absolute."""
    targets = []
    for raw in PATCH_HEADER.findall(patch or ""):
        path = os.path.expanduser(raw.strip())
        if not os.path.isabs(path) and cwd:
            path = os.path.join(cwd, path)
        if path not in targets:
            targets.append(path)
    return targets


def _normalize_patch(normalized, original, tool, cwd):
    """Codex edits files through apply_patch: the patch text in tool_input.command, or
    freeform text with no object around it. The write guards need the target paths."""
    ti = normalized["tool_input"]
    patch = ""
    for candidate in (ti.get("command"), ti.get("input"), ti.get("patch"), original.get("tool_input"),
                      original.get("input"), tool.get("input")):
        if isinstance(candidate, str) and candidate.strip():
            patch = candidate
            break
    targets = patch_targets(patch, cwd)
    new_input = {"command": patch} if patch else {}
    if targets:
        new_input["file_path"] = targets[0]
        new_input["edits"] = [{"file_path": t} for t in targets[1:]]
    normalized["tool_input"] = new_input
    normalized["neva_patch_targets"] = targets


def normalize_payload(event, data, harness=""):
    """Return (canonical_event, claude_shaped_data, harness_name).

    Unknown keys are carried through untouched so a harness-specific module could still
    read them, and so a future field does not need a change here to survive the trip.
    """
    original = data if isinstance(data, dict) else {}
    active = detect_harness(original, harness)
    if active == "claude":
        if original.get("neva_harness") != "claude":
            original = dict(original, neva_harness="claude")
        return event, original, "claude"

    normalized = dict(original)
    source_event = str(_first(original, "hook_event_name", "event", "type") or event)
    canonical = HARNESS_EVENTS.get(active, {}).get(source_event.lower(), event)
    tool = _mapping(original.get("tool"))
    session = _mapping(original.get("session"))
    context = _mapping(original.get("context"))

    name = _first(original, "tool_name", "toolName", "tool_id") or _first(tool, "name", "id", "tool_name")
    normalized["tool_name"] = TOOL_NAMES.get(str(name).lower(), str(name))
    normalized["neva_source_tool"] = str(name)
    cwd = str(_first(original, "cwd", "directory", "workspace", "worktree", "workspace_roots")
              or _first(session, "cwd", "directory", "workspace")
              or _first(context, "cwd", "directory") or "")

    tool_input = original.get("tool_input")
    for candidate in (tool_input, _first(tool, "input", "arguments", "args", "parameters"),
                      _first(original, "input", "arguments", "args", "parameters")):
        if isinstance(candidate, dict):
            tool_input = candidate
            break
    normalized["tool_input"] = dict(tool_input) if isinstance(tool_input, dict) else {}
    # OpenCode's read, write and edit tools name the path filePath. The write guards read
    # file_path, so without this every protected-path check passes on that harness.
    file_path = normalized["tool_input"].get("filePath")
    if isinstance(file_path, str) and file_path and not normalized["tool_input"].get("file_path"):
        normalized["tool_input"]["file_path"] = file_path
    # Cursor's beforeShellExecution sends a bare `command` string and names no tool at
    # all. Without this, tool_name stays empty, the Bash modules never match, and the
    # no-verify guard silently stops guarding on that harness.
    if not normalized["tool_input"]:
        command = _first(original, "command", "shell_command") or _first(tool, "command")
        if isinstance(command, str) and command:
            normalized["tool_input"] = {"command": command}
    if not normalized["tool_name"] and normalized["tool_input"].get("command"):
        normalized["tool_name"] = "Bash"
    if normalized["tool_name"] == "Bash":
        _normalize_shell(normalized["tool_input"])
    if str(name).lower() == "apply_patch":
        _normalize_patch(normalized, original, tool, cwd)

    normalized["cwd"] = cwd
    normalized["session_id"] = str(_first(original, "session_id", "sessionId", "sessionID",
                                          "conversation_id", "conversationId", "thread_id")
                                   or _first(session, "id", "session_id") or "")
    normalized["transcript_path"] = str(_first(original, "transcript_path", "transcriptPath",
                                               "rollout_path", "rolloutPath")
                                        or _first(session, "transcript_path", "transcriptPath") or "")
    normalized["neva_harness"] = active
    return canonical, normalized, active


# ---------------------------------------------------------------- environment

def env(name, default=""):
    v = os.environ.get(name)
    return default if v is None else v


def env_flag(name, default=False):
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in TRUE_VALUES


def env_int(name, default, lo=None, hi=None):
    try:
        v = int(str(os.environ.get(name, "")).strip())
    except ValueError:
        return default
    if lo is not None and v < lo:
        return default
    if hi is not None and v > hi:
        return default
    return v


def home():
    return os.path.expanduser("~")


def data_dir():
    d = env("NEVA_DATA_DIR")
    if not d:
        base = env("XDG_DATA_HOME") or os.path.join(home(), ".local", "share")
        d = os.path.join(base, "neva")
    return os.path.expanduser(d)


def sub_dir(*parts):
    p = os.path.join(data_dir(), *parts)
    ensure_dir(p)
    return p


def state_root():
    """NEVA_STATE_DIR, else $XDG_STATE_HOME/neva, else ~/.local/state/neva. Shared with the
    scheduled jobs, gateguard and safety-guard; never pruned wholesale."""
    d = env("NEVA_STATE_DIR")
    if not d:
        base = env("XDG_STATE_HOME") or os.path.join(home(), ".local", "state")
        d = os.path.join(base, "neva")
    return os.path.expanduser(d)


def state_dir():
    """Per-session hook state (counters, markers, caches). Files older than
    COMPACT_STATE_TTL_DAYS are pruned at session start, so nothing durable goes here."""
    return ensure_dir(os.path.join(state_root(), "hooks"))


def sessions_dir():
    return sub_dir("sessions")


def _abs_env_dir(name):
    v = env(name).strip()
    if v:
        v = os.path.expanduser(v)
        if os.path.isabs(v):
            return v
        log(f"[paths] {name}={v!r} is not an absolute path; ignoring it")
    return ""


def observations_dir():
    """Same resolution as the continuous-learning-v2 CLI and nightly job, so the hook writes
    exactly where the analyzer reads."""
    d = _abs_env_dir("NEVA_OBSERVATIONS_DIR") or os.path.join(data_dir(), "observations")
    return ensure_dir(d)


def metrics_dir():
    d = _abs_env_dir("NEVA_METRICS_DIR") or os.path.join(data_dir(), "metrics")
    return ensure_dir(d)


def costs_path():
    return os.path.join(metrics_dir(), "costs.jsonl")


def ensure_dir(p):
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


# ---------------------------------------------------------------- logging

def log(msg):
    """Append one line to hooks.log. Rotates at 1 MB. Never raises."""
    try:
        d = ensure_dir(data_dir())
        p = os.path.join(d, "hooks.log")
        try:
            if os.path.getsize(p) > 1024 * 1024:
                os.replace(p, p + ".1")
        except OSError:
            pass
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {msg}\n")
    except Exception:
        pass


def log_exception(where):
    log(f"[error] {where}: " + traceback.format_exc().strip().replace("\n", "\n    "))


# ---------------------------------------------------------------- config

@functools.lru_cache(maxsize=1)
def load_config():
    """Tiny vendored reader for the identity file (KEY="value" lines). Fails soft:
    a missing or malformed file yields {} and the hooks run without vault features."""
    path = os.path.expanduser(env("NEVA_CONFIG") or os.path.join(home(), ".config", "neva", "identity.env"))
    cfg = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                m = re.match(r'^([A-Z_][A-Z0-9_]*)="([^"]*)"\s*$', raw.rstrip("\n"))
                if m:
                    cfg[m.group(1)] = m.group(2)
    except OSError:
        return {}
    for k, v in list(cfg.items()):
        if v.startswith("$HOME"):
            cfg[k] = v.replace("$HOME", home(), 1)
    return cfg


def vault_path():
    v = env("NEVA_VAULT") or load_config().get("VAULT_PATH", "")
    if not v:
        return None
    v = os.path.realpath(os.path.expanduser(v))
    return v if os.path.isdir(v) else None


# ---------------------------------------------------------------- time

def now():
    tz = env("NEVA_TIMEZONE") or load_config().get("TIMEZONE", "")
    if tz and ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo(tz))
        except Exception:
            pass
    return datetime.datetime.now()


def today():
    """The working day. NEVA_DAY_ROLLOVER_HOUR (default 0) lets late nights count as the
    previous day: with 5, anything before 05:00 belongs to yesterday."""
    n = now()
    roll = env_int("NEVA_DAY_ROLLOVER_HOUR", 0, 0, 12)
    d = n.date()
    return d - datetime.timedelta(days=1) if n.hour < roll else d


def hhmm():
    return now().strftime("%H:%M")


# ---------------------------------------------------------------- text helpers

def read_text(path, limit=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit) if limit else fh.read()
    except OSError:
        return ""


def write_text(path, text):
    ensure_dir(os.path.dirname(path))
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v
    except Exception:
        return default


def write_json(path, obj):
    write_text(path, json.dumps(obj, indent=1, sort_keys=True))


def one_line(text, n=160):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 3].rstrip() + "..."


def frontmatter(text):
    """Return (dict, body). Flat `key: value` pairs only; lists like [a, b] become lists."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    meta, end = {}, None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", lines[i])
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            elif v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
            meta[m.group(1)] = v
    if end is None:
        return {}, text
    return meta, "\n".join(lines[end + 1:])


def section(text, heading, limit=40):
    """Lines of a `## heading` section, blank lines dropped."""
    m = re.search(r"^##\s+" + re.escape(heading) + r"\s*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M | re.I)
    if not m:
        return []
    return [ln for ln in m.group(1).strip().splitlines() if ln.strip() and not ln.startswith("---")][:limit]


SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|credentials?|auth)"
    r"([\"'\s:=]{1,8})"
    r"((?:bearer|basic|token|bot)\s+)?"
    r"([A-Za-z0-9_\-/.+=]{8,256})"
)
SECRET_SHAPES = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "OpenAI-style API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"), "GitHub fine-grained token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}"), "Stripe live key"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private key block"),
]


def scrub(text):
    if text is None:
        return None
    s = SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) or "") + "[REDACTED]", str(text))
    for rx, _ in SECRET_SHAPES:
        s = rx.sub("[REDACTED]", s)
    return s


# ---------------------------------------------------------------- git and project identity

def git(args, cwd, timeout=2):
    try:
        p = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else None
    except Exception:
        return None


def normalize_remote(url):
    """Identical to the continuous-learning-v2 CLI: drop credentials and scheme, turn scp form
    into host/path, drop .git and trailing slashes, lowercase network URLs so two clones hash
    the same."""
    if not url:
        return ""
    network = not url.startswith("file://") and ("://" in url or re.match(r"^[^@/:]+@[^:/]+:", url) is not None)
    u = re.sub(r"://[^@]+@", "://", url)
    u = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", u)
    u = re.sub(r"^[^@/:]+@([^:/]+):", r"\1/", u)
    u = re.sub(r"\.git/?$", "", u)
    u = re.sub(r"/+$", "", u)
    return u.lower() if network else u


def hash12(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


UNSCOPED_ID = "unscoped"


def _main_worktree_root(project_root):
    out = git(["worktree", "list", "--porcelain"], project_root, timeout=5)
    for line in (out or "").splitlines():
        if line.startswith("worktree "):
            return line.split(" ", 1)[1].strip() or project_root
    return project_root


def _detect_project(cwd):
    """The continuous-learning-v2 algorithm, line for line, so hook and CLI ids agree:
    CLAUDE_PROJECT_DIR (its git toplevel, else its real path), else the git toplevel of cwd,
    else the bucket `unscoped`. id = sha256[:12] of the normalized origin remote, else of the
    main worktree root, so linked worktrees and clones on other machines share one id."""
    root = None
    if env("NEVA_NO_PROJECT") != "1":
        env_dir = env("CLAUDE_PROJECT_DIR")
        if env_dir and os.path.isdir(env_dir):
            root = git(["rev-parse", "--show-toplevel"], env_dir, timeout=5) or os.path.realpath(env_dir)
        if not root:
            root = git(["rev-parse", "--show-toplevel"], cwd, timeout=5)
    if root:
        root = root.rstrip("/")
    if not root:
        return {"id": UNSCOPED_ID, "name": os.path.basename(cwd.rstrip("/")) or UNSCOPED_ID,
                "root": "", "remote": "", "scoped": False}
    remote = re.sub(r"://[^@]+@", "://", git(["remote", "get-url", "origin"], root, timeout=5) or "")
    fallback = _main_worktree_root(root) if not remote else root
    key = normalize_remote(remote) if remote else ""
    return {"id": hash12(key or remote or fallback), "name": os.path.basename(root), "root": root,
            "remote": remote, "scoped": True}


def update_registry(info):
    """projects.json next to the observations, under an exclusive lock, atomic replace. Same
    shape the CLI writes: {id, name, root, remote, created_at, last_seen}."""
    if not info.get("scoped"):
        return
    obs = observations_dir()
    reg_p = os.path.join(obs, "projects.json")
    lock_p = os.path.join(obs, ".projects.json.lock")
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        fcntl = None
    fd = None
    try:
        if fcntl:
            fd = open(lock_p, "w")
            fcntl.flock(fd, fcntl.LOCK_EX)
        reg = read_json(reg_p, {}) or {}
        if not isinstance(reg, dict):
            reg = {}
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        prev = reg.get(info["id"]) if isinstance(reg.get(info["id"]), dict) else {}
        reg[info["id"]] = {"id": info["id"], "name": info["name"], "root": info["root"],
                           "remote": info["remote"], "created_at": prev.get("created_at", stamp),
                           "last_seen": stamp}
        write_text(reg_p, json.dumps(reg, indent=2) + "\n")
    except Exception:
        log_exception("update_registry")
    finally:
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()


def project_info(cwd):
    """{id, name, root, remote, scoped}. Cached for 10 minutes per (CLAUDE_PROJECT_DIR, cwd);
    the registry is refreshed on each cache miss."""
    cwd = os.path.realpath(cwd or os.getcwd())
    key = f"{env('CLAUDE_PROJECT_DIR')}|{env('NEVA_NO_PROJECT')}|{cwd}"
    cache_p = os.path.join(state_dir(), "project-cache.json")
    cache = read_json(cache_p, {}) or {}
    hit = cache.get(key)
    if isinstance(hit, dict) and "scoped" in hit and time.time() - hit.get("ts", 0) < 600:
        return hit
    info = _detect_project(cwd)
    update_registry(info)
    info["ts"] = time.time()
    try:
        if len(cache) > 200:
            cache = dict(sorted(cache.items(), key=lambda kv: kv[1].get("ts", 0))[-100:])
        cache[key] = info
        write_json(cache_p, cache)
    except Exception:
        pass
    return info


def repo_identity(cwd):
    common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    return os.path.realpath(common) if common else ""


# ---------------------------------------------------------------- sessions and prompts

def sanitize_id(value):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:80]


def short_id(session_id):
    s = sanitize_id(session_id)
    return s[-8:] if s else "default"


NOT_PROMPT_PREFIXES = ("<", "Base directory for this skill", "Caveat:", "[Request interrupted",
                       "This session is being continued", "[Image", "<command-")


def is_real_prompt(text):
    t = (text or "").strip()
    return bool(t) and not t.startswith(NOT_PROMPT_PREFIXES)


def _text_of(content):
    if isinstance(content, str):
        return content, False
    if isinstance(content, list):
        parts, tool_result = [], False
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "tool_result":
                    tool_result = True
                elif c.get("type") == "text":
                    parts.append(str(c.get("text", "")))
        return "\n".join(parts), tool_result
    return "", False


_KEEP_INPUT_KEYS = ("file_path", "notebook_path", "command", "path", "pattern")


def _compact_input(inp):
    """Keep only the input fields hooks read (paths and commands), capped, so the cache stays small."""
    return {k: str(inp[k])[:2000] for k in _KEEP_INPUT_KEYS if k in inp}


def _prefix_sig(fh, offset):
    """Fingerprint of the bytes just before offset, to detect a rewritten (not appended) file."""
    start = max(0, offset - 512)
    fh.seek(start)
    return hashlib.sha1(fh.read(offset - start)).hexdigest()


def _transcript_cache_path(path):
    key = hashlib.sha1(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]
    return os.path.join(ensure_dir(os.path.join(state_dir(), "transcripts")), key + ".json")


def parse_transcript(path):
    """Claude Code JSONL transcript, parsed incrementally. Sidechain (subagent) entries skipped.

    A per-transcript cache in the hook state dir keeps the byte offset and the accumulated
    result, so each Stop reads only the lines appended since the last call instead of the
    whole file (large sessions took about 2 s per response before this)."""
    out = {"prompts": [], "tool_uses": [], "files": [], "usage": {}, "model": "", "ok": False}
    if not path or not os.path.exists(path):
        return out
    offset, synthetic = 0, 0
    cache = None
    try:
        cache = _transcript_cache_path(path)
        size = os.path.getsize(path)
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as fh:
                saved = json.load(fh)
            ok = isinstance(saved, dict) and 0 < saved.get("offset", 0) <= size
            if ok:
                with open(path, "rb") as fh:
                    ok = _prefix_sig(fh, saved["offset"]) == saved.get("sig")
            if ok:
                offset, synthetic = saved["offset"], saved.get("synthetic", 0)
                out.update(saved["out"])
                out["tool_uses"] = [tuple(x) for x in out["tool_uses"]]
    except Exception:
        offset, synthetic = 0, 0
        out = {"prompts": [], "tool_uses": [], "files": [], "usage": {}, "model": "", "ok": False}
    files_seen = set(out["files"])
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read()
            cut = data.rfind(b"\n") + 1  # only complete lines; a half-written last line waits for next time
            sig = _prefix_sig(fh, offset + cut) if cut else None
        for raw in data[:cut].splitlines():
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain"):
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            if o.get("type") == "user" and not o.get("isMeta"):
                text, is_result = _text_of(msg.get("content"))
                if not is_result and is_real_prompt(text):
                    out["prompts"].append(text.strip())
            elif o.get("type") == "assistant":
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            name = str(b.get("name", ""))
                            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                            out["tool_uses"].append((name, _compact_input(inp)))
                            fp = inp.get("file_path") or inp.get("notebook_path")
                            if fp and name in ("Write", "Edit", "MultiEdit", "NotebookEdit") and fp not in files_seen:
                                files_seen.add(fp)
                                out["files"].append(fp)
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    mid = msg.get("id")
                    if not mid:
                        synthetic += 1
                        mid = f"_line{synthetic}"
                    out["usage"][mid] = usage
                if msg.get("model") and msg.get("model") != "<synthetic>":
                    out["model"] = msg["model"]
        out["ok"] = True
        if cache and cut:
            tmp = cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"offset": offset + cut, "sig": sig, "synthetic": synthetic, "out": out}, fh)
            os.replace(tmp, cache)
    except Exception:
        log_exception(f"parse_transcript {path}")
    return out


def context_tokens(path, tail_bytes=256 * 1024):
    """(tokens, model) from the newest assistant usage record in the transcript tail."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            start = max(0, size - tail_bytes)
            fh.seek(start)
            data = fh.read().decode("utf-8", "ignore")
    except Exception:
        return 0, ""
    lines = data.split("\n")
    if start > 0:
        lines = lines[1:]
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        msg = o.get("message") if isinstance(o, dict) else None
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(usage, dict):
            total = sum(int(usage.get(k) or 0) for k in
                        ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if total > 0:
                return total, str(msg.get("model") or "")
    return 0, ""


# ---------------------------------------------------------------- vault: journal and inbox

def journal_pattern():
    return env("NEVA_JOURNAL_PATTERN") or "08 Journal/{date}.md"


def journal_rel(day=None):
    day = day or today()
    return journal_pattern().format(
        date=day.isoformat(), year=day.year, month=f"{day.month:02d}",
        month_name=MONTHS[day.month - 1], day=f"{day.day:02d}", weekday=day.strftime("%A"))


def journal_path(day=None):
    v = vault_path()
    return os.path.join(v, journal_rel(day)) if v else None


def journal_marker():
    """The fixed leading folder of the journal pattern, used to spot journal writes."""
    head = journal_pattern().split("{")[0].rstrip("/")
    return head or os.path.dirname(journal_rel())


def log_heading():
    return env("NEVA_JOURNAL_LOG_HEADING") or "## Log"


def ensure_journal(day=None):
    day = day or today()
    p = journal_path(day)
    if not p:
        return None, False
    if os.path.exists(p):
        return p, False
    v = vault_path()
    tpl = read_text(os.path.join(v, env("NEVA_JOURNAL_TEMPLATE") or "Templates/Daily Note.md"))
    title = f"{day.strftime('%A')}, {day.day} {MONTHS[day.month - 1]} {day.year}"
    if tpl:
        body = tpl.replace("{{date}}", day.isoformat()).replace("{{title}}", title)
    else:
        body = f"---\ntags: [journal]\ndate: {day.isoformat()}\n---\n\n# {title}\n"
    if log_heading() not in body:
        body = body.rstrip("\n") + f"\n\n{log_heading()}\n"
    write_text(p, body)
    return p, True


def append_journal_log(line, replace_key=None, day=None):
    """Add one line under the log heading. With replace_key, a line containing the key is
    updated in place (a resumed session keeps one audit line). Identical lines are skipped."""
    p, _ = ensure_journal(day)
    if not p:
        return None
    txt = read_text(p)
    if line.strip() in txt:
        return p
    if replace_key and replace_key in txt:
        txt = "\n".join(line if replace_key in ln else ln for ln in txt.split("\n"))
        write_text(p, txt)
        return p
    head = log_heading()
    if head in txt:
        before, tail = txt.split(head, 1)
        m = re.search(r"\n#{1,2} ", tail)
        if m:
            seg, rest = tail[: m.start()], tail[m.start():]
            txt = before + head + seg.rstrip("\n") + "\n" + line + "\n" + rest
        else:
            txt = txt.rstrip("\n") + "\n" + line + "\n"
    else:
        txt = txt.rstrip("\n") + f"\n\n{head}\n{line}\n"
    write_text(p, txt)
    return p


TEMPLATE_INBOX = os.path.join("00 Inbox", "inbox.md")


def inbox_path(vault=None):
    """The inbox note. NEVA_INBOX (absolute, or relative to the vault) wins; else the
    template's 00 Inbox/inbox.md; else a root inbox.md when only that exists (vaults that keep
    one root inbox with an `## Open actions` section). The instinct CLI resolves it the same way."""
    v = vault or vault_path()
    if not v:
        return None
    custom = env("NEVA_INBOX").strip()
    if custom:
        custom = os.path.expanduser(custom)
        return custom if os.path.isabs(custom) else os.path.join(v, custom)
    template = os.path.join(v, TEMPLATE_INBOX)
    root = os.path.join(v, "inbox.md")
    if os.path.exists(template) or not os.path.exists(root):
        return template
    return root


def proposals_dir(vault=None):
    """Where the nightly job files `Instinct promotions YYYY-MM-DD.md`: NEVA_PROPOSALS_DIR, else
    the inbox note's folder, else (inbox at the vault root) 06 Memory/instincts/proposals."""
    v = vault or vault_path()
    if not v:
        return None
    custom = env("NEVA_PROPOSALS_DIR").strip()
    if custom:
        custom = os.path.expanduser(custom)
        return custom if os.path.isabs(custom) else os.path.join(v, custom)
    folder = os.path.dirname(inbox_path(v))
    if os.path.realpath(folder) == os.path.realpath(v):
        return os.path.join(v, "06 Memory", "instincts", "proposals")
    return folder


def open_proposal_files(vault=None):
    d = proposals_dir(vault)
    out = []
    try:
        names = sorted(os.listdir(d)) if d else []
    except OSError:
        names = []
    for n in names:
        if n.startswith("Instinct promotions ") and n.endswith(".md"):
            if re.search(r"^status: open$", read_text(os.path.join(d, n), 400), re.M):
                out.append(os.path.join(d, n))
    return out


# ---------------------------------------------------------------- session files

def find_session_file(session_id):
    sid = short_id(session_id)
    d = sessions_dir()
    try:
        for name in sorted(os.listdir(d), reverse=True):
            if name.endswith(f"-{sid}-session.tmp"):
                return os.path.join(d, name)
    except OSError:
        pass
    return os.path.join(d, f"{today().isoformat()}-{sid}-session.tmp")


def summary_markdown(t, tag=""):
    prompts = [one_line(p, 200) for p in t["prompts"]][-10:]
    counts = {}
    for name, _ in t["tool_uses"]:
        counts[name] = counts.get(name, 0) + 1
    lines = [SUMMARY_START, "## Session Summary" + (f" ({tag})" if tag else ""), "", "### Tasks"]
    lines += [f"- {p.replace('`', chr(39))}" for p in prompts] or ["- (none)"]
    if t["files"]:
        lines += ["", "### Files Modified"] + [f"- {f}" for f in t["files"][-30:]]
    if counts:
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
        lines += ["", "### Tools Used", ", ".join(f"{k} x{v}" for k, v in top)]
    lines += ["", "### Stats", f"- User messages: {len(t['prompts'])}", f"- Tool calls: {len(t['tool_uses'])}",
              SUMMARY_END]
    return "\n".join(lines)


def update_session_file(ctx, block):
    """Create or refresh this session's state file; only the marked block is replaced, so
    notes the agent wrote below it survive."""
    path = find_session_file(ctx.session_id)
    existing = read_text(path)
    cwd = os.path.realpath(ctx.cwd)
    proj = ctx.project
    started = re.search(r"^\*\*Started:\*\*\s*(.+)$", existing, re.M)
    date = re.search(r"^\*\*Date:\*\*\s*(.+)$", existing, re.M)
    header = "\n".join([
        f"# Session: {date.group(1).strip() if date else today().isoformat()}",
        f"**Date:** {date.group(1).strip() if date else today().isoformat()}",
        f"**Started:** {started.group(1).strip() if started else hhmm()}",
        f"**Last Updated:** {hhmm()}",
        f"**Project:** {proj['name']}",
        f"**Branch:** {git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd) or 'unknown'}",
        f"**Worktree:** {cwd}",
        f"**Repo:** {repo_identity(cwd)}",
        f"**Session:** {ctx.session_id}",
        "",
    ])
    if existing and "\n---\n" in existing:
        body = existing.split("\n---\n", 1)[1]
        if SUMMARY_START in body and SUMMARY_END in body:
            body = re.sub(re.escape(SUMMARY_START) + r".*?" + re.escape(SUMMARY_END), lambda _m: block, body,
                          count=1, flags=re.S)
        else:
            body = block + "\n\n" + body.lstrip("\n")
    else:
        body = block + "\n\n### Notes for Next Session\n-\n\n### Context to Load\n```\n[relevant files]\n```\n"
    write_text(path, header + "\n---\n" + body)
    return path


# ---------------------------------------------------------------- instincts

INACTIVE_STATUSES = ("archived", "promoted")


def instincts_root(vault=None):
    v = vault or vault_path()
    return os.path.join(v, "06 Memory", "instincts") if v else None


def parse_instinct(path):
    """One instinct note as written by the continuous-learning-v2 CLI and analyzer."""
    text = read_text(path)
    meta, body = frontmatter(text)
    if not meta.get("id"):
        return None
    try:
        meta["confidence"] = float(meta.get("confidence", 0.5))
    except (TypeError, ValueError):
        meta["confidence"] = 0.5
    act = section(body, "Action", 5)
    meta["action"] = act[0].strip() if act else str(meta.get("trigger", ""))
    meta["_path"] = path
    meta["_body"] = body
    return meta


def load_instincts(root, project_id=None, include_global=True):
    """Canonical layout (continuous-learning-v2):
      global/<id>.md               every project
      project/<project-id>/<id>.md one project
    pending/ subfolders are never loaded, nor notes whose status is archived or promoted.
    Project instincts win over global ones with the same id."""
    found = []
    if not root or not os.path.isdir(root):
        return found

    def scan(d, scope):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return []
        out = []
        for n in names:
            p = os.path.join(d, n)
            if not (n.endswith(".md") and os.path.isfile(p)):
                continue
            i = parse_instinct(p)
            if not i or str(i.get("status", "active")).lower() in INACTIVE_STATUSES:
                continue
            i["_scope"] = scope
            out.append(i)
        return out

    if project_id:
        found += scan(os.path.join(root, "project", project_id), "project")
    if include_global:
        mine = {i["id"] for i in found}
        found += [i for i in scan(os.path.join(root, "global"), "global") if i["id"] not in mine]
    return found


# ---------------------------------------------------------------- context object

class Ctx:
    """Everything a module needs about the current hook call. Expensive parts are lazy."""

    def __init__(self, event, group, data, profile, raw="", parse_error=False, harness="claude"):
        self.event = event
        self.group = group
        self.data = data if isinstance(data, dict) else {}
        self.profile = profile
        self.raw = raw or ""
        self.parse_error = parse_error
        self.harness = str(harness or self.data.get("neva_harness") or "claude")
        self.session_id = str(self.data.get("session_id") or env("CLAUDE_SESSION_ID") or "")
        self.sid = sanitize_id(self.session_id) or "default"
        self.cwd = str(self.data.get("cwd") or env("CLAUDE_PROJECT_DIR") or os.getcwd())
        self.tool_name = str(self.data.get("tool_name") or "")
        ti = self.data.get("tool_input")
        self.tool_input = ti if isinstance(ti, dict) else {}
        self.transcript_path = str(self.data.get("transcript_path") or env("CLAUDE_TRANSCRIPT_PATH") or "")

    @functools.cached_property
    def vault(self):
        return vault_path()

    @functools.cached_property
    def project(self):
        return project_info(self.cwd)

    @functools.cached_property
    def transcript(self):
        return parse_transcript(self.transcript_path)

    def state_file(self, name):
        return os.path.join(state_dir(), f"{name}-{self.sid}")

    def file_path(self):
        return str(self.tool_input.get("file_path") or self.tool_input.get("notebook_path") or "")


def emit_stderr(text):
    try:
        sys.stderr.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass
