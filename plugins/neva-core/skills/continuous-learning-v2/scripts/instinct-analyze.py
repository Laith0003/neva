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
                             oldest first, in batches of at most
                             max_analysis_lines, up to max_batches_per_run
                             batches; run the analyzer with claude --print per
                             batch, accept only an exact completion record,
                             then archive exactly that batch. Observations the
                             run did not reach stay in place for the next run;
                             nothing is archived unread.
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
  instinct-analyze.py [--dry-run] [--project ID] [--skip-analysis]
"""

import argparse
import json
import os
import re
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
COMPLETION_RECORD = '{"status":"analysis_complete"}'
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


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def load_config() -> dict:
    defaults = {"min_observations_to_analyze": 20, "max_analysis_lines": 500, "model": "haiku",
                "timeout_seconds": 120, "max_turns": 0, "max_batches_per_run": 4}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("analyze", {})
        defaults.update({k: v for k, v in data.items() if k in defaults})
    except (OSError, json.JSONDecodeError):
        pass
    env_map = {"NEVA_INSTINCT_MIN_OBSERVATIONS": ("min_observations_to_analyze", int),
               "NEVA_INSTINCT_MAX_ANALYSIS_LINES": ("max_analysis_lines", int),
               "NEVA_INSTINCT_MODEL": ("model", str),
               "NEVA_INSTINCT_TIMEOUT_SECONDS": ("timeout_seconds", int),
               "NEVA_INSTINCT_MAX_TURNS": ("max_turns", int),
               "NEVA_INSTINCT_MAX_BATCHES": ("max_batches_per_run", int)}
    for env, (key, cast) in env_map.items():
        if os.environ.get(env):
            try:
                defaults[key] = cast(os.environ[env])
            except ValueError:
                log(f"{env}={os.environ[env]!r} is not a valid {cast.__name__}; using {defaults[key]!r}")
    return defaults


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


def completion_ok(stdout: str) -> bool:
    """Exactly one completion record, and it is the last non-empty line."""
    lines = [ln.rstrip("\r") for ln in stdout.splitlines()]
    non_empty = [ln for ln in lines if ln.strip()]
    return (sum(1 for ln in lines if ln == COMPLETION_RECORD) == 1
            and bool(non_empty) and non_empty[-1] == COMPLETION_RECORD)


def plan_batches(lines: list, size: int, cap: int) -> list:
    """Split complete lines, oldest first, into ceil(len/size) near-equal batches of at most
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


def analyze_bucket(obs_dir: Path, name: str, vault: Path, cfg: dict, dry_run: bool) -> None:
    """Analyse a bucket oldest first: files the observe hook rotated into observations.pending/
    (never yet analysed), then the live file. One batch budget covers them all; each batch is
    archived only after it succeeds, and a rotated file disappears from pending once fully analysed."""
    pid = obs_dir.name
    root = obs_dir.parent
    live = obs_dir / "observations.jsonl"
    leftovers = interrupted_files(obs_dir)
    if leftovers and dry_run:
        log(f"{name} ({pid}): {len(leftovers)} file(s) from an interrupted run would be recovered")
    elif leftovers:
        for path in leftovers:
            back = _restore(path, root)
            log(f"{name} ({pid}): recovered {path.name} from an interrupted run as {back.name}")
    sources = learning_io.observation_sources(obs_dir)
    if not sources:
        return
    for src in sources:
        learning_io.check(root, src)
    per_file = [(src, _complete_lines(src)) for src in sources]
    count = sum(len(lines) for _, lines in per_file)
    if count < cfg["min_observations_to_analyze"]:
        log(f"{name} ({pid}): {count} observations < {cfg['min_observations_to_analyze']}, skipped")
        return
    budget = cfg["max_batches_per_run"]
    plan = []
    for src, lines in per_file:
        if budget <= 0:
            break
        batches = plan_batches(lines, cfg["max_analysis_lines"], budget)
        if batches:
            plan.append((src, batches))
            budget -= len(batches)
    total = sum(len(b) for _, bs in plan for b in bs)
    n_batches = sum(len(bs) for _, bs in plan)
    rotated = sum(len(lines) for src, lines in per_file if src != live)
    log(f"{name} ({pid}): analyzing {total} of {count} observations in {n_batches} batch(es), oldest first"
        + (f" ({rotated} from rotated files)" if rotated else "")
        + (f"; {count - total} left in place for the next run" if total < count else ""))
    if dry_run:
        return
    archive_dir = learning_io.ensure_dir(root, obs_dir / "observations.archive")
    tmp_dir = learning_io.ensure_dir(root, obs_dir / ".analyze-tmp")
    instincts_dir = vault / "06 Memory" / "instincts" / "project" / pid
    instincts_dir.mkdir(parents=True, exist_ok=True)
    number = 0
    for src, batches in plan:
        for batch in batches:
            number += 1
            label = f"{name} ({pid}) batch {number}/{n_batches}"
            if not analyze_batch(tmp_dir, pid, name, label, batch, instincts_dir, cfg):
                log(f"{name} ({pid}): stopping; this batch and every later observation stay in place")
                return
            chunk = b"".join(batch)
            if not archive_analyzed(src, chunk, archive_dir, root):
                log(f"{label}: {src.name} no longer starts with the analyzed batch (rotated or rewritten "
                    f"during the run); nothing archived, observations retained for the next run")
                return
            log(f"{label}: analysis complete; {len(batch)} analyzed observations archived")


def analyze_batch(tmp_dir: Path, pid: str, name: str, label: str, batch: list,
                  instincts_dir: Path, cfg: dict) -> bool:
    """Run the analysis child on one batch. True only on an exact completion record. `tmp_dir`
    was checked by learning_io.ensure_dir; mkstemp creates its file with O_EXCL."""
    fd, analysis_path = tempfile.mkstemp(prefix="analysis.", suffix=".jsonl", dir=tmp_dir)
    with os.fdopen(fd, "wb") as f:
        f.write(b"".join(batch))
    analysis_file = Path(analysis_path)
    try:
        prompt = render_prompt(analysis_file, pid, name, instincts_dir)
        max_turns = cfg["max_turns"] or min(100, max(20, len(batch) // 10))
        if max_turns < 4:
            max_turns = 20
        env = _child_env()
        cmd = [claude_bin(), "--model", cfg["model"], "--max-turns", str(max_turns), "--print",
               "--allowedTools", "Read,Write", "-p", prompt]
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
            return False
        if stderr.strip():
            log(f"{label}: stderr: {stderr.strip()[-2000:]}")
        if proc.returncode != 0:
            log(f"{label}: analysis failed (exit {proc.returncode}); observations retained for retry")
            return False
        if not completion_ok(stdout):
            log(f"{label}: completion record missing; observations retained for retry")
            return False
        return True
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
    the hook may have recreated since: it becomes a pending file, which is analysed before the
    live one, so order is kept. A pending file gets its own name back (carried after the "--"
    in the moving name), so it keeps its place among the other pending files. Its lines may be
    analysed twice; none are lost."""
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


def archive_analyzed(obs_file: Path, chunk: bytes, archive: Path, root: Path) -> bool:
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
    archived = archive / f"processed-{stamp}.jsonl"
    learning_io.write_new(root, archived, chunk)
    moving = obs_file.parent / f"{MOVING_PREFIX}{stamp}--{obs_file.name}"
    try:
        os.rename(obs_file, moving)
    except BaseException:
        _discard(archived)
        raise
    try:
        data = moving.read_bytes()
        if not data.startswith(chunk):  # changed between the check and the rename
            _discard(archived)
            _restore(moving, root)
            return False
        tail = data[len(chunk):]
        if tail:
            with learning_io.open_append(root, obs_file, binary=True) as f:
                f.write(tail)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly instinct analysis (Neva)")
    parser.add_argument("--dry-run", action="store_true", help="Log what would run; call nothing")
    parser.add_argument("--project", help="Analyze one project id only")
    parser.add_argument("--skip-analysis", action="store_true", help="Run apply, decay, prune, propose only")
    args = parser.parse_args()

    vault = vault_root()
    if vault is None or not vault.is_dir():
        log("NEVA_VAULT is not set to an existing absolute path and the identity file has no usable VAULT_PATH. "
            "Fix: set NEVA_VAULT in the timer's environment, or VAULT_PATH in ~/.config/neva/identity.env.")
        return 2
    os.environ["NEVA_VAULT"] = str(vault)

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

    cfg = load_config()
    log(f"start (model={cfg['model']}, min={cfg['min_observations_to_analyze']}, "
        f"max_lines={cfg['max_analysis_lines']}, dry_run={args.dry_run})")

    if not args.dry_run:
        run_cli("apply-promotions")

    if not args.skip_analysis:
        exe = claude_bin()
        if not (os.path.isabs(exe) and os.access(exe, os.X_OK)) and shutil.which(exe) is None:
            log("claude CLI not found on PATH; analysis skipped. Fix: add the claude binary's directory to the "
                "timer's PATH, or set NEVA_CLAUDE_BIN.")
        else:
            obs_root = _obs_root()
            try:
                registry = json.loads((obs_root / "projects.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                registry = {}
            if obs_root.is_dir():
                for obs_dir in sorted(p for p in obs_root.iterdir() if p.is_dir()):
                    if args.project and obs_dir.name != args.project:
                        continue
                    name = registry.get(obs_dir.name, {}).get("name", obs_dir.name)
                    try:
                        analyze_bucket(obs_dir, name, vault, cfg, args.dry_run)
                    except learning_io.ManagedPathError as exc:
                        log(f"{name} ({obs_dir.name}): {exc} Observations retained.")
                    except Exception as exc:  # one bad bucket must not stop the night
                        log(f"{name} ({obs_dir.name}): error {exc!r}; observations retained")

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
