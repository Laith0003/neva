#!/usr/bin/env python3
"""
Instinct CLI: manage instincts for continuous-learning-v2 (Neva).

Adapted from affaan-m/ECC (MIT), commit d3b8a3e, skills/continuous-learning-v2/
scripts/instinct-cli.py. Retargeted for Neva: markdown instincts in the vault,
observations under XDG data, human-approved promotion through inbox proposals.
Search, stats and manual add merged from garrytan/gstack learn (MIT, Garry Tan).

Storage
  Instincts (markdown, one per file, readable in Obsidian):
    $NEVA_VAULT/06 Memory/instincts/project/<project-id>/<id>.md
    $NEVA_VAULT/06 Memory/instincts/global/<id>.md
    <either dir>/pending/<id>.md        unreviewed imports, pruned after 30 days
  Observations (raw hook captures, JSONL, never in the vault):
    ${XDG_DATA_HOME:-~/.local/share}/neva/observations/<project-id>/observations.jsonl
    ${XDG_DATA_HOME:-~/.local/share}/neva/observations/projects.json   registry
  Machine state:
    ${NEVA_STATE_DIR:-${XDG_STATE_HOME:-~/.local/state}/neva}/instincts/promotions.json
  Human review:
    <proposals dir>/Instinct promotions YYYY-MM-DD.md, plus one pointer line under the
    inbox note's `## Open actions`. The inbox note is NEVA_INBOX (absolute or vault-relative;
    default 00 Inbox/inbox.md, or a root inbox.md when only that exists). The proposals dir is
    NEVA_PROPOSALS_DIR, else the inbox note's folder, else (root inbox) 06 Memory/instincts/proposals.
  Vault: NEVA_VAULT, else VAULT_PATH in the identity file (NEVA_CONFIG, default
    ~/.config/neva/identity.env).

Durable memory (a global instinct, a skill, a command, an agent, a rule, or a
retirement) is written only by apply-promotions, and only for blocks the human
ticked, or for every open block when the human said "apply instinct promotions".

Commands
  status            Show instincts (project + global)
  search QUERY      Search instincts by id, trigger, action, domain
  stats             Counts by scope, domain, source; average confidence
  add               Record a user-stated instinct
  import SOURCE     Import instincts from a file or https URL
  export            Export instincts to one file
  evolve            Cluster instincts into skill/command/agent candidates
  promote [ID]      Propose project to global promotion (writes proposals)
  propose           Write every qualifying candidate to today's proposal file
  apply-promotions  Apply ticked blocks (or, with --all, every open block)
  decay             Lower confidence 0.02 per full week without observation
  projects          List, delete, merge, gc known projects
  prune             Delete pending instincts older than 30 days (TTL)
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows: skip file locking


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _abs_env_path(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        print(f"[neva] {name}={value!r} is not an absolute path; ignoring it", file=sys.stderr)
        return None
    return path


def _resolve_observations_root() -> Path:
    """Same resolution as the hook runtime (neva_hooks/common.py observations_dir)."""
    override = _abs_env_path("NEVA_OBSERVATIONS_DIR")
    if override:
        return override
    data = _abs_env_path("NEVA_DATA_DIR")
    if data:
        return data / "observations"
    xdg = _abs_env_path("XDG_DATA_HOME")
    if xdg:
        return xdg / "neva" / "observations"
    return Path.home() / ".local" / "share" / "neva" / "observations"


def _resolve_state_dir() -> Path:
    override = _abs_env_path("NEVA_INSTINCT_STATE_DIR")
    if override:
        return override
    root = _abs_env_path("NEVA_STATE_DIR")
    if root:
        return root / "instincts"
    xdg = _abs_env_path("XDG_STATE_HOME")
    if xdg:
        return xdg / "neva" / "instincts"
    return Path.home() / ".local" / "state" / "neva" / "instincts"


def _vault_from_identity() -> Optional[Path]:
    """VAULT_PATH="..." from the Neva identity file, the same fallback the hooks use."""
    cfg = Path(os.environ.get("NEVA_CONFIG") or Path.home() / ".config" / "neva" / "identity.env").expanduser()
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^VAULT_PATH="([^"]*)"\s*$', text, re.M)
    if not m or not m.group(1):
        return None
    value = m.group(1)
    if value.startswith("$HOME"):
        value = str(Path.home()) + value[len("$HOME"):]
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


VAULT = _abs_env_path("NEVA_VAULT") or _vault_from_identity()
OBS_ROOT = _resolve_observations_root()
REGISTRY_FILE = OBS_ROOT / "projects.json"
STATE_DIR = _resolve_state_dir()
PROMOTIONS_LEDGER = STATE_DIR / "promotions.json"

INSTINCTS_REL = Path("06 Memory") / "instincts"
TEMPLATE_INBOX_REL = Path("00 Inbox") / "inbox.md"
INBOX_SECTION = os.environ.get("NEVA_INBOX_SECTION") or "Open actions"


def _vault_relative(name: str) -> Optional[Path]:
    value = (os.environ.get(name) or "").strip()
    if not value or VAULT is None:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else VAULT / path


def _resolve_inbox_note() -> Optional[Path]:
    """Same order as the hook runtime (neva_hooks/common.py inbox_path)."""
    if VAULT is None:
        return None
    custom = _vault_relative("NEVA_INBOX")
    if custom:
        return custom
    template, root = VAULT / TEMPLATE_INBOX_REL, VAULT / "inbox.md"
    return template if template.exists() or not root.exists() else root


def _resolve_proposals_dir() -> Optional[Path]:
    if VAULT is None:
        return None
    custom = _vault_relative("NEVA_PROPOSALS_DIR")
    if custom:
        return custom
    folder = _resolve_inbox_note().parent
    if os.path.realpath(folder) == os.path.realpath(VAULT):
        return VAULT / INSTINCTS_REL / "proposals"
    return folder


if VAULT is not None:
    INSTINCTS_ROOT = VAULT / INSTINCTS_REL
    GLOBAL_DIR = INSTINCTS_ROOT / "global"
    PROJECT_INSTINCTS_DIR = INSTINCTS_ROOT / "project"
    INBOX_NOTE = _resolve_inbox_note()
    INBOX_DIR = _resolve_proposals_dir()
else:
    INSTINCTS_ROOT = GLOBAL_DIR = PROJECT_INSTINCTS_DIR = INBOX_DIR = INBOX_NOTE = None

# Bucket for sessions outside any detectable project. It is treated as a
# project so the nightly analysis never writes into global/ directly.
UNSCOPED_ID = "unscoped"

INSTINCT_EXT = ".md"
ALLOWED_INSTINCT_EXTENSIONS = (".md", ".yaml", ".yml")  # .yaml only as import sources
INACTIVE_STATUSES = {"archived", "promoted"}

# Thresholds (from the upstream skill; see SKILL.md for the table)
PROMOTE_CONFIDENCE_THRESHOLD = 0.8     # project -> global: average across projects
PROMOTE_MIN_PROJECTS = 2               # project -> global: distinct projects
SCOPE_HINT_GLOBAL_THRESHOLD = 0.7      # analyzer flagged universal, single project
RULE_CONFIDENCE_THRESHOLD = 0.9        # global instinct -> rule ("near-certain, core behavior")
RETIRE_CONFIDENCE_THRESHOLD = 0.3      # below "tentative" after decay
DECAY_PER_WEEK = 0.02
PENDING_TTL_DAYS = 30
PENDING_EXPIRY_WARNING_DAYS = 7
PROPOSE_DEFAULT_LIMIT = 5

# User-level Claude Code config dir (honors CLAUDE_CONFIG_DIR, like Claude Code).
_cfg = _abs_env_path("CLAUDE_CONFIG_DIR")
CLAUDE_DIR_REF = str(_cfg) if _cfg else "~/.claude"


def _require_vault() -> None:
    if VAULT is None:
        print("NEVA_VAULT is not set (or not absolute) and the identity file has no VAULT_PATH. "
              "Fix: export NEVA_VAULT=/absolute/path/to/your/vault", file=sys.stderr)
        sys.exit(2)
    if not VAULT.is_dir():
        print(f"NEVA_VAULT points at {VAULT}, which is not a directory. Fix: point NEVA_VAULT at your vault root.",
              file=sys.stderr)
        sys.exit(2)


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _vault_ref(path: Path) -> str:
    """Render a vault path as vault:<relative>, anything else as-is."""
    try:
        rel = Path(path).resolve().relative_to(VAULT.resolve())
        return f"vault:{rel.as_posix()}"
    except (ValueError, AttributeError):
        home = str(Path.home())
        s = str(path)
        return "~" + s[len(home):] if s.startswith(home + os.sep) else s


def _resolve_ref(ref: str) -> Path:
    ref = ref.strip().strip("`").strip()
    if ref.startswith("vault:"):
        return VAULT / ref[len("vault:"):]
    path = Path(ref).expanduser()
    if not path.is_absolute():
        raise ValueError(f"not an absolute path or vault: reference: {ref}")
    return path


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _strip_remote_credentials(remote_url: str) -> str:
    return re.sub(r"://[^@]+@", "://", remote_url or "")


def _normalize_remote_url(remote_url: str) -> str:
    if not remote_url:
        return ""
    is_network = (
        not remote_url.startswith("file://")
        and ("://" in remote_url or re.match(r"^[^@/:]+@[^:/]+:", remote_url) is not None)
    )
    normalized = _strip_remote_credentials(remote_url)
    normalized = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", normalized)
    normalized = re.sub(r"^[^@/:]+@([^:/]+):", r"\1/", normalized)
    normalized = re.sub(r"\.git/?$", "", normalized)
    normalized = re.sub(r"/+$", "", normalized)
    return normalized.lower() if is_network else normalized


def _stream_can_encode(text: str, stream=None) -> bool:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or sys.getdefaultencoding()
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _confidence_bar(confidence, stream=None) -> str:
    try:
        filled = int(float(confidence) * 10)
    except (TypeError, ValueError):
        filled = 5
    filled = max(0, min(10, filled))
    full, empty = ("█", "░") if _stream_can_encode("█░", stream) else ("#", ".")
    return full * filled + empty * (10 - filled)


def _project_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _yaml_quote(value: str) -> str:
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def _write_text_atomic(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(prefix=f".{file_path.name}.", suffix=".tmp",
                                          dir=file_path.parent, text=True)
    temp_file = Path(temp_name)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, file_path)
    finally:
        try:
            temp_file.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def _validate_file_path(path_str: str, must_exist: bool = False) -> Path:
    """Resolve a user-supplied path, refusing system directories."""
    path = Path(path_str).expanduser().resolve()
    blocked_prefixes = [
        "/etc", "/usr", "/bin", "/sbin", "/proc", "/sys",
        "/var/log", "/var/run", "/var/lib", "/var/spool",
        "/private/etc", "/private/var/log", "/private/var/run", "/private/var/db",
    ]
    path_s = str(path)
    for prefix in blocked_prefixes:
        if path_s.startswith(prefix + "/") or path_s == prefix:
            raise ValueError(f"Path '{path}' targets a system directory")
    if must_exist and not path.exists():
        raise ValueError(f"Path does not exist: {path}")
    return path


def _validate_instinct_id(instinct_id: str) -> bool:
    if not instinct_id or len(instinct_id) > 128:
        return False
    if "/" in instinct_id or "\\" in instinct_id or ".." in instinct_id or instinct_id.startswith("."):
        return False
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", instinct_id))


def _validate_project_id(project_id: str) -> bool:
    if not project_id or len(project_id) > 128:
        return False
    if "/" in project_id or "\\" in project_id or ".." in project_id:
        return False
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", project_id))


def _validate_import_url(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme != "https":
        raise ValueError("remote instinct imports require https URLs")
    if not parsed.hostname:
        raise ValueError("remote import URL is missing a hostname")
    try:
        addr_infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"remote import host could not be resolved: {parsed.hostname}") from exc
    for _family, _, _, _, sockaddr in addr_infos:
        host = sockaddr[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"remote import host resolves to a non-public address: {host}")
    return urllib.parse.urlunparse(parsed)


def _fetch_import_url(source: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    url = _validate_import_url(source)
    req = urllib.request.Request(url, headers={"User-Agent": "neva-instinct-import/2"})
    with urllib.request.urlopen(req, timeout=15) as response:
        content_type = response.headers.get("Content-Type", "")
        if content_type and not any(a in content_type.lower()
                                    for a in ("text/", "markdown", "yaml", "json", "octet-stream")):
            raise ValueError(f"unsupported remote content type: {content_type}")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"remote import exceeds {max_bytes} bytes")
    return data.decode("utf-8")


# ---------------------------------------------------------------------------
# Project detection (the observation hook must use the same algorithm)
# ---------------------------------------------------------------------------

def _git_repo_root(cwd: Optional[str] = None) -> Optional[str]:
    args = ["git"]
    if cwd:
        args.extend(["-C", cwd])
    args.extend(["rev-parse", "--show-toplevel"])
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _main_worktree_root(project_root: str) -> str:
    try:
        result = subprocess.run(["git", "-C", project_root, "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return project_root
    if result.returncode != 0:
        return project_root
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return line.split(" ", 1)[1].strip() or project_root
    return project_root


def _project_paths(project_id: str) -> dict:
    instincts_dir = (PROJECT_INSTINCTS_DIR / project_id) if PROJECT_INSTINCTS_DIR else None
    return {
        "obs_dir": OBS_ROOT / project_id,
        "observations_file": OBS_ROOT / project_id / "observations.jsonl",
        "instincts_dir": instincts_dir,
        "pending_dir": instincts_dir / "pending" if instincts_dir else None,
    }


def detect_project() -> dict:
    """Detect the current project. Returns id, name, root, remote and paths."""
    project_root = None
    if os.environ.get("NEVA_NO_PROJECT") != "1":
        env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if env_dir and os.path.isdir(env_dir):
            project_root = _git_repo_root(env_dir) or os.path.realpath(env_dir)
        if not project_root:
            project_root = _git_repo_root()
    if project_root:
        project_root = project_root.rstrip("/")

    if not project_root:
        info = {"id": UNSCOPED_ID, "name": UNSCOPED_ID, "root": "", "remote": ""}
        info.update(_project_paths(UNSCOPED_ID))
        return info

    project_name = os.path.basename(project_root)
    remote_url = ""
    try:
        result = subprocess.run(["git", "-C", project_root, "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            remote_url = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    if remote_url:
        remote_url = _strip_remote_credentials(remote_url)

    fallback_root = _main_worktree_root(project_root) if not remote_url else project_root
    normalized_remote = _normalize_remote_url(remote_url) if remote_url else ""
    hash_source = normalized_remote or remote_url or fallback_root
    project_id = _project_hash(hash_source)

    _update_registry(project_id, project_name, project_root, remote_url)
    info = {"id": project_id, "name": project_name, "root": project_root, "remote": remote_url}
    info.update(_project_paths(project_id))
    return info


@contextmanager
def _registry_lock():
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = REGISTRY_FILE.parent / f".{REGISTRY_FILE.name}.lock"
    lock_fd = None
    try:
        if _HAS_FCNTL:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def _write_registry_unlocked(registry: dict) -> None:
    tmp_file = REGISTRY_FILE.parent / f".{REGISTRY_FILE.name}.tmp.{os.getpid()}"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, REGISTRY_FILE)


def _update_registry(pid: str, pname: str, proot: str, premote: str) -> None:
    with _registry_lock():
        try:
            with open(REGISTRY_FILE, encoding="utf-8") as f:
                registry = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            registry = {}
        if not isinstance(registry, dict):
            registry = {}
        now = _now_iso()
        existing = registry.get(pid, {})
        if not isinstance(existing, dict):
            existing = {}
        registry[pid] = {
            "id": pid, "name": pname, "root": proot, "remote": premote,
            "created_at": existing.get("created_at", now), "last_seen": now,
        }
        _write_registry_unlocked(registry)


def load_registry() -> dict:
    try:
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_registry(registry: dict) -> None:
    with _registry_lock():
        _write_registry_unlocked(registry)


# ---------------------------------------------------------------------------
# Instinct parsing, loading, writing
# ---------------------------------------------------------------------------

INT_FIELDS = {"evidence_count", "decay_weeks_applied"}


def parse_instinct_file(content: str) -> list[dict]:
    """Parse instinct markdown (or multi-block import files).

    Each instinct is delimited by a pair of ``---`` markers. Instinct bodies
    must use ``***`` or ``___`` for horizontal rules.
    """
    instincts = []
    current = {}
    in_frontmatter = False
    content_lines = []
    for line in content.split('\n'):
        if line.strip() == '---':
            if in_frontmatter:
                in_frontmatter = False
            else:
                in_frontmatter = True
                if current:
                    current['content'] = '\n'.join(content_lines).strip()
                    instincts.append(current)
                current = {}
                content_lines = []
        elif in_frontmatter:
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                    value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                    value = value[1:-1].replace("''", "'")
                if key == 'confidence':
                    try:
                        current[key] = float(value)
                    except ValueError:
                        current[key] = 0.5
                elif key in INT_FIELDS:
                    try:
                        current[key] = int(value)
                    except ValueError:
                        current[key] = 0
                else:
                    current[key] = value
        else:
            content_lines.append(line)
    if current:
        current['content'] = '\n'.join(content_lines).strip()
        instincts.append(current)
    return [i for i in instincts if i.get('id')]


def _load_instincts_from_dir(directory: Optional[Path], scope_label: str,
                             include_inactive: bool = False) -> list[dict]:
    """Load instincts from one directory (non-recursive, so pending/ is skipped)."""
    instincts = []
    if directory is None or not directory.is_dir():
        return instincts
    files = [f for f in sorted(directory.iterdir())
             if f.is_file() and f.suffix.lower() in ALLOWED_INSTINCT_EXTENSIONS]
    for file in files:
        try:
            parsed = parse_instinct_file(file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: failed to parse {file}: {e}", file=sys.stderr)
            continue
        for inst in parsed:
            if not include_inactive and str(inst.get('status', 'active')).lower() in INACTIVE_STATUSES:
                continue
            inst['_source_file'] = str(file)
            inst['_source_type'] = 'inherited' if inst.get('source') == 'inherited' else 'personal'
            inst['_scope_label'] = scope_label
            inst.setdefault('scope', scope_label)
            instincts.append(inst)
    return instincts


def load_all_instincts(project: dict, include_global: bool = True) -> list[dict]:
    """Project-scoped instincts plus global ones; project wins on id conflict."""
    instincts = list(_load_instincts_from_dir(project.get("instincts_dir"), "project"))
    if include_global:
        project_ids = {i.get('id') for i in instincts}
        for gi in _load_instincts_from_dir(GLOBAL_DIR, "global"):
            if gi.get('id') not in project_ids:
                instincts.append(gi)
    return instincts


def load_project_only_instincts(project: dict) -> list[dict]:
    return load_all_instincts(project, include_global=False)


def _evidence_count(inst: dict) -> int:
    if isinstance(inst.get('evidence_count'), int) and inst['evidence_count'] > 0:
        return inst['evidence_count']
    content = inst.get('content', '')
    counts = [int(n) for n in re.findall(r'Observed (\d+) times?', content)]
    if counts:
        return sum(counts)
    ev = re.search(r'## Evidence\s*\n(.*?)(?:\n## |\Z)', content, re.DOTALL)
    if ev:
        return len([ln for ln in ev.group(1).splitlines() if ln.strip().startswith('- ')])
    return 0


def _action_of(inst: dict) -> str:
    m = re.search(r'## Action\s*\n\s*(.+?)(?:\n\n|\n##|$)', inst.get('content', ''), re.DOTALL)
    return m.group(1).strip() if m else inst.get('id', 'unnamed')


def _title_of(inst: dict) -> str:
    m = re.search(r'^#\s+(.+)$', inst.get('content', ''), re.M)
    return m.group(1).strip() if m else inst.get('id', 'unnamed').replace('-', ' ').title()


FRONTMATTER_ORDER = [
    'id', 'trigger', 'confidence', 'domain', 'source', 'scope', 'scope_hint',
    'project_id', 'project_name', 'evidence_count', 'date', 'last_observed',
    'decay_weeks_applied', 'status', 'tags', 'files', 'imported_from', 'source_repo',
    'promoted_from', 'promoted_to',
]


def render_instinct(inst: dict, overrides: Optional[dict] = None) -> str:
    """Render one instinct note. Keys starting with _ and 'content' are internal."""
    data = {k: v for k, v in inst.items() if not k.startswith('_') and k != 'content'}
    data.update(overrides or {})
    domain = data.get('domain', 'general')
    data.setdefault('status', 'active')
    data.setdefault('date', _today())
    data.setdefault('tags', f"[instinct, {domain}]")
    lines = ["---"]
    keys = [k for k in FRONTMATTER_ORDER if k in data] + sorted(k for k in data if k not in FRONTMATTER_ORDER)
    for key in keys:
        value = data[key]
        if value is None or value == "":
            continue
        if key in ('trigger', 'imported_from', 'project_name'):
            lines.append(f"{key}: {_yaml_quote(value)}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    body = inst.get('content', '').strip()
    return "\n".join(lines) + "\n" + (body + "\n" if body else "")


def set_frontmatter_fields(path: Path, updates: dict) -> None:
    """Set or insert scalar frontmatter keys in the first frontmatter block."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} has no frontmatter block")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError(f"{path} has an unterminated frontmatter block")
    remaining = dict(updates)
    for i in range(1, end):
        if ':' in lines[i]:
            key = lines[i].split(':', 1)[0].strip()
            if key in remaining:
                lines[i] = f"{key}: {remaining.pop(key)}"
    insert = [f"{k}: {v}" for k, v in remaining.items()]
    lines[end:end] = insert
    _write_text_atomic(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# status / search / stats / add
# ---------------------------------------------------------------------------

def _print_instincts_by_domain(instincts: list[dict]) -> None:
    by_domain = defaultdict(list)
    for inst in instincts:
        by_domain[inst.get('domain', 'general')].append(inst)
    for domain in sorted(by_domain):
        items = by_domain[domain]
        print(f"  ### {domain.upper()} ({len(items)})\n")
        for inst in sorted(items, key=lambda x: -x.get('confidence', 0.5)):
            conf = inst.get('confidence', 0.5)
            print(f"    {_confidence_bar(conf)} {int(conf*100):3d}%  {inst.get('id', 'unnamed')} [{inst.get('scope', '?')}]")
            print(f"              trigger: {inst.get('trigger', 'unknown trigger')}")
            action = _action_of(inst).split('\n')[0]
            print(f"              action: {action[:60]}{'...' if len(action) > 60 else ''}")
            print()


def _count_lines(path: Path) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def cmd_status(args) -> int:
    project = detect_project()
    instincts = load_all_instincts(project)
    if not instincts:
        print("No instincts found.")
        print(f"\nProject: {project['name']} ({project['id']})")
        print(f"  Project instincts:  {project['instincts_dir']}")
        print(f"  Global instincts:   {GLOBAL_DIR}")
    else:
        project_instincts = [i for i in instincts if i.get('_scope_label') == 'project']
        global_instincts = [i for i in instincts if i.get('_scope_label') == 'global']
        print(f"\n{'='*60}\n  INSTINCT STATUS - {len(instincts)} total\n{'='*60}\n")
        print(f"  Project:  {project['name']} ({project['id']})")
        print(f"  Project instincts: {len(project_instincts)}")
        print(f"  Global instincts:  {len(global_instincts)}\n")
        if project_instincts:
            print(f"## PROJECT-SCOPED ({project['name']})\n")
            _print_instincts_by_domain(project_instincts)
        if global_instincts:
            print("## GLOBAL (apply to all projects)\n")
            _print_instincts_by_domain(global_instincts)
    obs_file = project["observations_file"]
    if obs_file.exists():
        print("-" * 60)
        print(f"  Observations: {_count_lines(obs_file)} events waiting for the nightly analysis")
        print(f"  File: {obs_file}")
    pending = _collect_pending_instincts()
    if pending:
        print(f"\n{'-'*60}\n  Pending instincts: {len(pending)} awaiting review")
        if len(pending) >= 5:
            print(f"\n  {len(pending)} pending instincts awaiting review. "
                  f"Unreviewed instincts auto-delete after {PENDING_TTL_DAYS} days.")
        threshold = PENDING_TTL_DAYS - PENDING_EXPIRY_WARNING_DAYS
        soon = [p for p in pending if threshold <= p["age_days"] < PENDING_TTL_DAYS]
        if soon:
            print(f"\n  Expiring within {PENDING_EXPIRY_WARNING_DAYS} days:")
            for item in soon:
                print(f"    - {item['name']} ({max(0, PENDING_TTL_DAYS - item['age_days'])}d remaining)")
    open_files = _open_proposal_files()
    if open_files:
        print(f"\n{'-'*60}\n  Open instinct proposals: {len(open_files)} file(s) in {INBOX_DIR}")
    print(f"\n{'='*60}\n")
    return 0


def cmd_search(args) -> int:
    project = detect_project()
    if args.scope == "global":
        instincts = _load_instincts_from_dir(GLOBAL_DIR, "global")
    elif args.scope == "project":
        instincts = load_project_only_instincts(project)
    else:
        instincts = load_all_instincts(project)
    query = args.query.lower()
    hits = [i for i in instincts
            if query in " ".join([str(i.get('id', '')), str(i.get('trigger', '')),
                                  str(i.get('domain', '')), i.get('content', '')]).lower()]
    hits.sort(key=lambda i: -i.get('confidence', 0.5))
    if not hits:
        print(f"No instincts match '{args.query}'.")
        return 0
    for inst in hits[:args.limit]:
        print(f"{inst.get('confidence', 0.5):.2f}  {inst.get('id')} [{inst.get('scope', '?')}] ({inst.get('domain', 'general')})")
        print(f"      trigger: {inst.get('trigger', '')}")
        print(f"      action:  {_action_of(inst).splitlines()[0][:100]}")
        print(f"      file:    {_vault_ref(Path(inst['_source_file']))}")
    if len(hits) > args.limit:
        print(f"... and {len(hits) - args.limit} more (raise --limit)")
    return 0


def cmd_stats(args) -> int:
    project = detect_project()
    instincts = load_all_instincts(project)
    by_scope, by_domain, by_source = defaultdict(int), defaultdict(int), defaultdict(int)
    total_conf = 0.0
    for inst in instincts:
        by_scope[inst.get('_scope_label', '?')] += 1
        by_domain[inst.get('domain', 'general')] += 1
        by_source[inst.get('source', 'unknown')] += 1
        total_conf += inst.get('confidence', 0.5)
    print(f"Project: {project['name']} ({project['id']})")
    print(f"UNIQUE: {len(instincts)}")
    print(f"BY_SCOPE: {json.dumps(dict(by_scope))}")
    print(f"BY_DOMAIN: {json.dumps(dict(sorted(by_domain.items())))}")
    print(f"BY_SOURCE: {json.dumps(dict(by_source))}")
    print(f"AVG_CONFIDENCE: {(total_conf / len(instincts)) if instincts else 0:.2f}")
    print(f"PENDING: {len(_collect_pending_instincts())}")
    print(f"OBSERVATIONS_WAITING: {_count_lines(project['observations_file'])}")
    return 0


def cmd_add(args) -> int:
    """Record a user-stated instinct. The human invoking this is the approval."""
    project = detect_project()
    if not _validate_instinct_id(args.id):
        print(f"Invalid --id '{args.id}'. Fix: use kebab-case letters, digits, '.', '_' or '-'.", file=sys.stderr)
        return 1
    conf = args.confidence
    if conf > 1:
        conf = conf / 10.0  # accept the 1-10 scale
    if not 0 < conf <= 1:
        print("Invalid --confidence. Fix: pass 0.1 to 1.0, or 1 to 10.", file=sys.stderr)
        return 1
    target_dir = GLOBAL_DIR if args.scope == "global" else project["instincts_dir"]
    target = target_dir / f"{args.id}{INSTINCT_EXT}"
    if target.exists():
        print(f"{_vault_ref(target)} already exists. Fix: pick another --id or edit that note.", file=sys.stderr)
        return 1
    inst = {
        'id': args.id, 'trigger': args.trigger, 'confidence': round(conf, 2),
        'domain': args.domain, 'source': 'user-stated', 'scope': args.scope,
        'evidence_count': 1, 'date': _today(), 'last_observed': _today(),
    }
    if args.scope == "project":
        inst['project_id'] = project['id']
        inst['project_name'] = project['name']
    if args.files:
        inst['files'] = "[" + ", ".join(args.files) + "]"
    title = args.id.replace('-', ' ').title()
    inst['content'] = (f"# {title}\n\n## Action\n{args.action}\n\n## Evidence\n"
                       f"- Stated by the user on {_today()}\n")
    _write_text_atomic(target, render_instinct(inst))
    print(f"Added {args.id} ({args.scope}, confidence {conf:.2f}) at {_vault_ref(target)}")
    return 0


# ---------------------------------------------------------------------------
# import / export
# ---------------------------------------------------------------------------

def cmd_import(args) -> int:
    project = detect_project()
    source = args.source
    target_scope = args.scope or "project"
    if source.startswith('http://') or source.startswith('https://'):
        print(f"Fetching from URL: {source}")
        try:
            content = _fetch_import_url(source)
        except Exception as e:
            print(f"Error fetching URL: {e}", file=sys.stderr)
            return 1
    else:
        try:
            path = _validate_file_path(source, must_exist=True)
        except ValueError as e:
            print(f"Invalid path: {e}", file=sys.stderr)
            return 1
        if not path.is_file():
            print(f"Error: '{path}' is not a regular file.", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8")

    new_instincts = [i for i in parse_instinct_file(content) if _validate_instinct_id(i.get('id', ''))]
    if not new_instincts:
        print("No valid instincts found in source.")
        return 1
    print(f"\nFound {len(new_instincts)} instincts to import.\nTarget scope: {target_scope}")
    if target_scope == "project":
        print(f"Target project: {project['name']} ({project['id']})")
    print()

    scope_dir = GLOBAL_DIR if target_scope == "global" else project["instincts_dir"]
    out_dir = scope_dir / "pending" if args.pending else scope_dir
    existing = _load_instincts_from_dir(scope_dir, target_scope, include_inactive=True)
    existing_by_id = {i.get('id'): i for i in existing}

    best_by_id = {}
    for inst in new_instincts:
        iid = inst.get('id')
        if iid not in best_by_id or inst.get('confidence', 0.5) > best_by_id[iid].get('confidence', 0.5):
            best_by_id[iid] = inst
    to_add, to_update, duplicates = [], [], []
    for inst in best_by_id.values():
        old = existing_by_id.get(inst['id'])
        if old is None:
            to_add.append(inst)
        elif inst.get('confidence', 0) > old.get('confidence', 0):
            to_update.append(inst)
        else:
            duplicates.append(inst)
    min_conf = args.min_confidence if args.min_confidence is not None else 0.0
    to_add = [i for i in to_add if i.get('confidence', 0.5) >= min_conf]
    to_update = [i for i in to_update if i.get('confidence', 0.5) >= min_conf]

    if to_add:
        print(f"NEW ({len(to_add)}):")
        for inst in to_add:
            print(f"  + {inst['id']} (confidence: {inst.get('confidence', 0.5):.2f})")
    if to_update:
        print(f"\nUPDATE ({len(to_update)}):")
        for inst in to_update:
            print(f"  ~ {inst['id']} (confidence: {inst.get('confidence', 0.5):.2f})")
    if duplicates:
        print(f"\nSKIP ({len(duplicates)} already exist with equal or higher confidence):")
        for inst in duplicates[:5]:
            print(f"  - {inst['id']}")
        if len(duplicates) > 5:
            print(f"  ... and {len(duplicates) - 5} more")
    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0
    if not to_add and not to_update:
        print("\nNothing to import.")
        return 0
    if not args.force:
        response = input(f"\nImport {len(to_add)} new, update {len(to_update)} into {_vault_ref(out_dir)}? [y/N] ")
        if response.lower() != 'y':
            print("Cancelled.")
            return 0

    written = []
    for inst in to_add + to_update:
        overrides = {'source': 'inherited', 'scope': target_scope, 'imported_from': source,
                     'date': _today(), 'status': 'active'}
        if target_scope == "project":
            overrides['project_id'] = project['id']
            overrides['project_name'] = project['name']
        target = out_dir / f"{inst['id']}{INSTINCT_EXT}"
        _write_text_atomic(target, render_instinct(inst, overrides))
        old = existing_by_id.get(inst['id'])
        if old and Path(old['_source_file']).resolve() != target.resolve() and not args.pending:
            set_frontmatter_fields(Path(old['_source_file']),
                                   {'status': 'archived', 'archived_reason': _yaml_quote(f"replaced by import {_today()}")})
        written.append(target)
    print(f"\nImport complete.\n   Scope: {target_scope}\n   Added: {len(to_add)}\n   Updated: {len(to_update)}")
    print(f"   Saved to: {_vault_ref(out_dir)}")
    if args.pending:
        print(f"   Pending: move a note out of pending/ to accept it. Unmoved notes are pruned after {PENDING_TTL_DAYS} days.")
    return 0


def cmd_export(args) -> int:
    project = detect_project()
    if args.scope == "project":
        instincts = load_project_only_instincts(project)
    elif args.scope == "global":
        instincts = _load_instincts_from_dir(GLOBAL_DIR, "global")
    else:
        instincts = load_all_instincts(project)
    if args.domain:
        instincts = [i for i in instincts if i.get('domain') == args.domain]
    if args.min_confidence:
        instincts = [i for i in instincts if i.get('confidence', 0.5) >= args.min_confidence]
    if not instincts:
        print("No instincts match the criteria.")
        return 1

    if args.format == "claude-md":
        output = _render_claude_md_section(instincts)
    else:
        output = f"# Instincts export\n# Date: {datetime.now().isoformat()}\n# Total: {len(instincts)}\n"
        if args.scope:
            output += f"# Scope: {args.scope}\n"
        output += f"# Project: {project['name']} ({project['id']})\n\n"
        for inst in instincts:
            output += "---\n"
            for key in ['id', 'trigger', 'confidence', 'domain', 'source', 'scope',
                        'project_id', 'project_name', 'evidence_count', 'source_repo']:
                if inst.get(key) not in (None, ""):
                    value = inst[key]
                    output += f"{key}: {_yaml_quote(value)}\n" if key == 'trigger' else f"{key}: {value}\n"
            output += "---\n\n" + inst.get('content', '') + "\n\n"

    if args.output:
        try:
            out_path = _validate_file_path(args.output)
        except ValueError as e:
            print(f"Invalid output path: {e}", file=sys.stderr)
            return 1
        if out_path.is_dir():
            print(f"Error: '{out_path}' is a directory, not a file.", file=sys.stderr)
            return 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Exported {len(instincts)} instincts to {out_path}")
    else:
        print(output)
    return 0


DOMAIN_SECTIONS = [
    ("Patterns", {"code-style", "file-patterns", "workflow"}),
    ("Pitfalls", {"debugging", "testing", "security"}),
    ("Preferences", {"git", "tooling"}),
]


def _render_claude_md_section(instincts: list[dict]) -> str:
    """Markdown section for CLAUDE.md or project docs (format from gstack learn)."""
    buckets = defaultdict(list)
    for inst in sorted(instincts, key=lambda i: -i.get('confidence', 0.5)):
        section = next((name for name, domains in DOMAIN_SECTIONS if inst.get('domain') in domains), "Other")
        buckets[section].append(inst)
    out = ["## Project Learnings", ""]
    for name in [s for s, _ in DOMAIN_SECTIONS] + ["Other"]:
        if not buckets.get(name):
            continue
        out.append(f"### {name}")
        for inst in buckets[name]:
            out.append(f"- **{inst['id']}**: {_action_of(inst).splitlines()[0]} "
                       f"(confidence: {round(inst.get('confidence', 0.5) * 10)}/10)")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# evolve (clustering; unchanged mechanics)
# ---------------------------------------------------------------------------

TRIGGER_STOP_WORDS = {
    'when', 'while', 'the', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'with',
    'that', 'this', 'from', 'into', 'at', 'by', 'as', 'is', 'are', 'be', 'it',
    'its', 'they', 'them', 'their', 'you', 'your', 'new', 'any', 'all', 'about',
    'after', 'before', 'over', 'via', 'use', 'using', 'need', 'needs', 'not',
}
# Overlap coefficient (shared / smaller set). Jaccard is too strict for ~7-word triggers.
TRIGGER_SIMILARITY_THRESHOLD = 0.5
TRIGGER_MIN_SHARED_KEYWORDS = 2
EVOLVED_SKILL_SLUG_LENGTH = 30
EVOLVED_COMMAND_SLUG_LENGTH = 20
EVOLVED_AGENT_SLUG_LENGTH = 20
PREVIEW_LIMIT = 5


def _truncate_slug(slug: str, max_length: int) -> str:
    if len(slug) <= max_length:
        return slug
    head = slug[:max_length]
    if slug[max_length] == '-':
        return head.rstrip('-')
    boundary = head.rfind('-')
    return head[:boundary] if boundary > 0 else head.strip('-')


def _evolved_skill_name(trigger: str) -> str:
    return _truncate_slug(re.sub(r'[^a-z0-9]+', '-', str(trigger or '').lower()).strip('-'),
                          EVOLVED_SKILL_SLUG_LENGTH)


def _evolved_command_name(trigger: str) -> str:
    stripped = str(trigger or 'unknown').lower().replace('when ', '').replace('implementing ', '')
    return _truncate_slug(re.sub(r'[^a-z0-9]+', '-', stripped).strip('-'), EVOLVED_COMMAND_SLUG_LENGTH)


def _evolved_agent_name(trigger: str) -> str:
    return _truncate_slug(re.sub(r'[^a-z0-9]+', '-', str(trigger or '').lower()).strip('-'),
                          EVOLVED_AGENT_SLUG_LENGTH)


def _print_preview_remainder(total: int, shown: int, noun: str) -> None:
    if total > shown:
        print(f"  ... and {total - shown} more {noun} not shown\n")


def _assign_unique_slugs(items: list, slug_fn) -> list:
    used, assigned = set(), []
    for item in items:
        base = slug_fn(item)
        if not base:
            assigned.append((item, ''))
            continue
        name, suffix = base, 2
        while name in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add(name)
        assigned.append((item, name))
    return assigned


def _trigger_keywords(trigger: str) -> set:
    words = re.findall(r'[a-z0-9]+', str(trigger or '').lower())
    return {w for w in words if len(w) > 2 and w not in TRIGGER_STOP_WORDS}


def _cluster_by_keyword_overlap(instincts: list) -> dict:
    clusters = []
    for inst in instincts:
        keywords = _trigger_keywords(inst.get('trigger', ''))
        if not keywords:
            continue
        best_index, best_score, best_shared = -1, 0.0, 0
        for index, (cluster_keywords, _members) in enumerate(clusters):
            shared = len(keywords & cluster_keywords)
            smaller = min(len(keywords), len(cluster_keywords))
            score = shared / smaller if smaller else 0.0
            if score > best_score:
                best_index, best_score, best_shared = index, score, shared
        if (best_index >= 0 and best_score >= TRIGGER_SIMILARITY_THRESHOLD
                and best_shared >= TRIGGER_MIN_SHARED_KEYWORDS):
            cluster_keywords, members = clusters[best_index]
            members.append(inst)
            clusters[best_index] = (cluster_keywords & keywords, members)
        else:
            clusters.append((keywords, [inst]))
    grouped = {}
    for cluster_keywords, members in clusters:
        label = ' '.join(sorted(cluster_keywords)[:4]) or 'general'
        while label in grouped:
            label += ' +'
        grouped[label] = members
    return grouped


def _evolve_candidates(instincts: list[dict]) -> tuple[list, list, list]:
    """Skill clusters (2+), command candidates (workflow >= 0.7), agent clusters (3+, avg >= 0.75)."""
    skill_candidates = []
    for trigger, cluster in _cluster_by_keyword_overlap(instincts).items():
        if len(cluster) >= 2:
            avg_conf = sum(i.get('confidence', 0.5) for i in cluster) / len(cluster)
            skill_candidates.append({
                'trigger': trigger, 'instincts': cluster, 'avg_confidence': avg_conf,
                'domains': sorted(set(i.get('domain', 'general') for i in cluster)),
                'scopes': sorted(set(i.get('scope', 'project') for i in cluster)),
            })
    skill_candidates.sort(key=lambda x: (-len(x['instincts']), -x['avg_confidence']))
    workflow_instincts = [i for i in instincts
                          if i.get('domain') == 'workflow' and i.get('confidence', 0) >= 0.7]
    agent_candidates = [c for c in skill_candidates
                        if len(c['instincts']) >= 3 and c['avg_confidence'] >= 0.75]
    return skill_candidates, workflow_instincts, agent_candidates


def cmd_evolve(args) -> int:
    project = detect_project()
    instincts = load_all_instincts(project)
    if len(instincts) < 3:
        print(f"Need at least 3 instincts to analyze patterns.\nCurrently have: {len(instincts)}")
        return 1
    project_instincts = [i for i in instincts if i.get('_scope_label') == 'project']
    global_instincts = [i for i in instincts if i.get('_scope_label') == 'global']
    print(f"\n{'='*60}\n  EVOLVE ANALYSIS - {len(instincts)} instincts")
    print(f"  Project: {project['name']} ({project['id']})")
    print(f"  Project-scoped: {len(project_instincts)} | Global: {len(global_instincts)}\n{'='*60}\n")
    high_conf = [i for i in instincts if i.get('confidence', 0) >= 0.8]
    print(f"High confidence instincts (>=80%): {len(high_conf)}")
    skill_candidates, workflow_instincts, agent_candidates = _evolve_candidates(instincts)

    print(f"\nPotential skill clusters found: {len(skill_candidates)}")
    if skill_candidates:
        print(f"\n## SKILL CANDIDATES ({len(skill_candidates)})\n")
        for i, cand in enumerate(skill_candidates[:PREVIEW_LIMIT], 1):
            print(f"{i}. Cluster: \"{cand['trigger']}\"")
            print(f"   Instincts: {len(cand['instincts'])}")
            print(f"   Avg confidence: {cand['avg_confidence']:.0%}")
            print(f"   Domains: {', '.join(cand['domains'])}")
            print(f"   Scopes: {', '.join(cand['scopes'])}")
            print("   Instincts:")
            for inst in cand['instincts'][:3]:
                print(f"     - {inst.get('id')} [{inst.get('scope', '?')}]")
            print()
        _print_preview_remainder(len(skill_candidates), PREVIEW_LIMIT, 'skill clusters')
    if workflow_instincts:
        print(f"\n## COMMAND CANDIDATES ({len(workflow_instincts)})\n")
        for inst, cmd_name in _assign_unique_slugs(
                workflow_instincts, lambda i: _evolved_command_name(i.get('trigger', 'unknown')))[:PREVIEW_LIMIT]:
            print(f"  /{cmd_name}\n    From: {inst.get('id')} [{inst.get('scope', '?')}]")
            print(f"    Confidence: {inst.get('confidence', 0.5):.0%}\n")
        _print_preview_remainder(len(workflow_instincts), PREVIEW_LIMIT, 'command candidates')
    if agent_candidates:
        print(f"\n## AGENT CANDIDATES ({len(agent_candidates)})\n")
        for cand, agent_name in _assign_unique_slugs(
                agent_candidates, lambda c: _evolved_agent_name(str(c.get('trigger', '')).strip()))[:PREVIEW_LIMIT]:
            print(f"  {agent_name}\n    Covers {len(cand['instincts'])} instincts")
            print(f"    Avg confidence: {cand['avg_confidence']:.0%}\n")
        _print_preview_remainder(len(agent_candidates), PREVIEW_LIMIT, 'agent candidates')
    _show_promotion_candidates()

    if args.propose:
        blocks = _evolve_blocks(project, skill_candidates, workflow_instincts, agent_candidates,
                                limit=max(0, args.limit or 0))
        return _emit_blocks(blocks, dry_run=args.dry_run)
    print(f"\n{'='*60}\n  Nothing written. Run `evolve --propose` to file these for human review.\n")
    return 0


# ---------------------------------------------------------------------------
# Promotion candidates
# ---------------------------------------------------------------------------

def _all_project_dirs() -> list[Path]:
    if PROJECT_INSTINCTS_DIR is None or not PROJECT_INSTINCTS_DIR.is_dir():
        return []
    return [d for d in sorted(PROJECT_INSTINCTS_DIR.iterdir()) if d.is_dir()]


def _find_cross_project_instincts() -> dict:
    """Instinct id -> [(project_id, project_name, instinct)] for ids in 2+ projects."""
    registry = load_registry()
    cross = defaultdict(list)
    for pdir in _all_project_dirs():
        pid = pdir.name
        seen = set()
        for inst in _load_instincts_from_dir(pdir, "project"):
            iid = inst.get('id')
            if iid and iid not in seen:
                seen.add(iid)
                cross[iid].append((pid, registry.get(pid, {}).get('name', inst.get('project_name', pid)), inst))
    return {iid: entries for iid, entries in cross.items() if len({e[0] for e in entries}) >= PROMOTE_MIN_PROJECTS}


def _global_ids() -> set:
    return {i.get('id') for i in _load_instincts_from_dir(GLOBAL_DIR, "global", include_inactive=True)}


def _promotion_candidates() -> list[dict]:
    global_ids = _global_ids()
    candidates = []
    for iid, entries in _find_cross_project_instincts().items():
        if iid in global_ids:
            continue
        avg_conf = sum(e[2].get('confidence', 0.5) for e in entries) / len(entries)
        if avg_conf >= PROMOTE_CONFIDENCE_THRESHOLD:
            candidates.append({'id': iid, 'entries': entries, 'avg_confidence': avg_conf,
                               'why': f"seen in {len(entries)} projects, average confidence "
                                      f"{avg_conf:.2f} >= {PROMOTE_CONFIDENCE_THRESHOLD:.2f}"})
    seen = {c['id'] for c in candidates}
    registry = load_registry()
    for pdir in _all_project_dirs():
        for inst in _load_instincts_from_dir(pdir, "project"):
            iid = inst.get('id')
            if (iid in seen or iid in global_ids or inst.get('scope_hint') != 'global'
                    or inst.get('confidence', 0) < SCOPE_HINT_GLOBAL_THRESHOLD):
                continue
            seen.add(iid)
            name = registry.get(pdir.name, {}).get('name', inst.get('project_name', pdir.name))
            candidates.append({'id': iid, 'entries': [(pdir.name, name, inst)],
                               'avg_confidence': inst.get('confidence', 0.5),
                               'why': f"analyzer flagged it universal (scope_hint: global), confidence "
                                      f"{inst.get('confidence', 0.5):.2f} >= {SCOPE_HINT_GLOBAL_THRESHOLD:.2f}"})
    return candidates


def _show_promotion_candidates() -> None:
    candidates = _promotion_candidates()
    if not candidates:
        return
    print("\n## PROMOTION CANDIDATES (project -> global)\n")
    for cand in candidates[:10]:
        names = ', '.join(pname for _, pname, _ in cand['entries'])
        print(f"  * {cand['id']} (avg: {cand['avg_confidence']:.0%})\n    Found in: {names}\n    Why: {cand['why']}\n")
    print("  Run `instinct-cli.py promote` to file these for human review.\n")


# ---------------------------------------------------------------------------
# Proposal blocks
# ---------------------------------------------------------------------------

def _block(kind: str, slug: str, fields: list[tuple[str, str]], text: str, text_lang: str = "markdown") -> dict:
    return {'block_id': f"{kind}:{slug}", 'kind': kind, 'slug': slug, 'fields': fields,
            'text': text.rstrip("\n") + "\n", 'lang': text_lang}


def _projects_field(entries) -> str:
    seen, parts = set(), []
    for pid, pname, _ in entries:
        if pid not in seen:
            seen.add(pid)
            parts.append(f"{pname} ({pid})")
    return "; ".join(parts) or "none"


def _promote_block(cand: dict) -> dict:
    best = max(cand['entries'], key=lambda e: e[2].get('confidence', 0.5))[2]
    dest = GLOBAL_DIR / f"{cand['id']}{INSTINCT_EXT}"
    evidence = sum(_evidence_count(e[2]) for e in cand['entries'])
    overrides = {
        'confidence': round(cand['avg_confidence'], 2), 'scope': 'global', 'source': best.get('source', 'promoted'),
        'promoted_from': ", ".join(sorted({e[0] for e in cand['entries']})), 'date': _today(),
        'evidence_count': evidence, 'status': 'active',
        'project_id': None, 'project_name': None, 'scope_hint': None,
    }
    text = render_instinct(best, overrides)
    sources = "; ".join(f"`{_vault_ref(Path(e[2]['_source_file']))}`" for e in cand['entries'])
    return _block("promote-global", cand['id'], [
        ("Kind", "promote-global"),
        ("Instinct", f"`{cand['id']}`"),
        ("Confidence", f"{cand['avg_confidence']:.2f}"),
        ("Evidence count", str(evidence)),
        ("Projects seen in", _projects_field(cand['entries'])),
        ("Why", cand['why']),
        ("Proposed destination", f"`{_vault_ref(dest)}`"),
        ("Write mode", "create"),
        ("Source notes", sources),
        ("Then set on source notes", f"`status: promoted`; `promoted_to: {_vault_ref(dest)}`"),
    ], text)


def _cluster_destination(project: dict, kind: str, name: str, cluster: list[dict]) -> str:
    registry = load_registry()
    pids = {i.get('project_id') for i in cluster if i.get('scope', 'project') == 'project'}
    all_project = all(i.get('scope', 'project') == 'project' for i in cluster)
    root = registry.get(next(iter(pids)), {}).get('root') if (all_project and len(pids) == 1) else None
    rel = {"skill": f"skills/{name}/SKILL.md", "command": f"commands/{name}.md", "agent": f"agents/{name}.md"}[kind]
    return str(Path(root) / ".claude" / rel) if root else f"{CLAUDE_DIR_REF}/{rel}"


def _evolved_description(trigger: str, instincts: list, kind: str) -> str:
    ids = ', '.join(i.get('id', 'unnamed') for i in instincts[:6])
    trig = (trigger or '').strip().rstrip('.') or 'a recurring situation'
    description = (f"Evolved {kind} covering {len(instincts)} learned instinct(s). "
                   f"Use {trig}. Source instincts - {ids}.")
    return description.replace(': ', ' - ').replace('<', '(').replace('>', ')')


def _cluster_fields(kind: str, name: str, members: list[dict], dest: str, why: str) -> list:
    entries = [(i.get('project_id') or 'global', i.get('project_name') or 'global', i) for i in members]
    avg = sum(i.get('confidence', 0.5) for i in members) / len(members)
    return [
        ("Kind", f"evolve-{kind}"),
        ("Instinct", ", ".join(f"`{i.get('id')}`" for i in members)),
        ("Confidence", f"{avg:.2f} (average)"),
        ("Evidence count", str(sum(_evidence_count(i) for i in members))),
        ("Projects seen in", _projects_field(entries)),
        ("Why", why),
        ("Proposed destination", f"`{dest}`"),
        ("Write mode", "create"),
    ]


def _evolve_blocks(project: dict, skill_candidates, workflow_instincts, agent_candidates, limit: int) -> list[dict]:
    blocks = []

    def bounded(assigned, kind):
        if limit and len(assigned) > limit:
            print(f"Note: proposing {limit} of {len(assigned)} {kind} candidates (--limit {limit}); "
                  f"{len(assigned) - limit} not proposed this run.")
            return assigned[:limit]
        return assigned

    for cand, name in bounded(_assign_unique_slugs(
            skill_candidates, lambda c: _evolved_skill_name(str(c.get('trigger', '')).strip())), 'skill'):
        if not name:
            continue
        trigger = cand['trigger'].strip()
        content = "---\n"
        content += f"name: {name}\n"
        content += f"description: {_yaml_quote(_evolved_description(trigger, cand['instincts'], 'skill'))}\n"
        content += "---\n\n"
        content += f"# {name}\n\n"
        content += f"Evolved from {len(cand['instincts'])} instincts (avg confidence: {cand['avg_confidence']:.0%})\n\n"
        content += f"## When to Apply\n\nTrigger: {trigger}\n\n## Actions\n\n"
        for inst in cand['instincts']:
            content += f"- {_action_of(inst)}\n"
        dest = _cluster_destination(project, "skill", name, cand['instincts'])
        blocks.append(_block("evolve-skill", name, _cluster_fields(
            "skill", name, cand['instincts'], dest,
            f"{len(cand['instincts'])} instincts share trigger keywords '{trigger}'"), content))

    for inst, cmd_name in bounded(_assign_unique_slugs(
            workflow_instincts, lambda i: _evolved_command_name(i.get('trigger', 'unknown'))), 'command'):
        if not cmd_name:
            continue
        content = "---\n"
        content += f"description: {_yaml_quote(_evolved_description(inst.get('trigger', ''), [inst], 'command'))}\n"
        content += "---\n\n"
        content += f"# {cmd_name}\n\nEvolved from instinct: {inst.get('id', 'unnamed')}\n"
        content += f"Confidence: {inst.get('confidence', 0.5):.0%}\n\n"
        content += inst.get('content', '')
        dest = _cluster_destination(project, "command", cmd_name, [inst])
        blocks.append(_block("evolve-command", cmd_name, _cluster_fields(
            "command", cmd_name, [inst], dest,
            f"workflow instinct with confidence {inst.get('confidence', 0.5):.2f} >= 0.70"), content))

    for cand, agent_name in bounded(_assign_unique_slugs(
            agent_candidates, lambda c: _evolved_agent_name(str(c.get('trigger', '')).strip())), 'agent'):
        if not agent_name:
            continue
        content = "---\n"
        content += f"name: {agent_name}\n"
        content += f"description: {_yaml_quote(_evolved_description(str(cand.get('trigger', '')), cand['instincts'], 'agent'))}\n"
        content += "model: sonnet\ntools: Read, Grep, Glob\n---\n"
        content += f"# {agent_name}\n\nEvolved from {len(cand['instincts'])} instincts "
        content += f"(avg confidence: {cand['avg_confidence']:.0%})\nDomains: {', '.join(cand['domains'])}\n\n"
        content += "## Source Instincts\n\n"
        for inst in cand['instincts']:
            content += f"- {inst.get('id', 'unnamed')}: {_action_of(inst).splitlines()[0]}\n"
        dest = _cluster_destination(project, "agent", agent_name, cand['instincts'])
        blocks.append(_block("evolve-agent", agent_name, _cluster_fields(
            "agent", agent_name, cand['instincts'], dest,
            f"{len(cand['instincts'])} instincts, average confidence {cand['avg_confidence']:.2f} >= 0.75"), content))
    return blocks


def _rule_blocks() -> list[dict]:
    blocks = []
    for inst in _load_instincts_from_dir(GLOBAL_DIR, "global"):
        if inst.get('confidence', 0) < RULE_CONFIDENCE_THRESHOLD:
            continue
        domain = re.sub(r'[^a-z0-9-]+', '-', str(inst.get('domain', 'general')).lower()).strip('-') or 'general'
        dest = f"{CLAUDE_DIR_REF}/rules/instincts-{domain}.md"
        text = (f"## {_title_of(inst)}\n\n{_action_of(inst)}\n\n"
                f"Trigger: {inst.get('trigger', '')}. Source: instinct `{inst['id']}` "
                f"(confidence {inst.get('confidence', 0):.2f}, {_evidence_count(inst)} observations).\n")
        blocks.append(_block("rule", inst['id'], [
            ("Kind", "rule"),
            ("Instinct", f"`{inst['id']}`"),
            ("Confidence", f"{inst.get('confidence', 0):.2f}"),
            ("Evidence count", str(_evidence_count(inst))),
            ("Projects seen in", inst.get('promoted_from', 'global')),
            ("Why", f"global instinct at confidence >= {RULE_CONFIDENCE_THRESHOLD:.2f} (near-certain, core behavior)"),
            ("Proposed destination", f"`{dest}`"),
            ("Write mode", "append"),
            ("Source notes", f"`{_vault_ref(Path(inst['_source_file']))}`"),
        ], text))
    return blocks


def _retire_blocks() -> list[dict]:
    blocks = []
    dirs = [(GLOBAL_DIR, "global")] + [(d, "project") for d in _all_project_dirs()]
    for directory, label in dirs:
        for inst in _load_instincts_from_dir(directory, label):
            conf = inst.get('confidence', 0.5)
            if conf >= RETIRE_CONFIDENCE_THRESHOLD:
                continue
            ref = _vault_ref(Path(inst['_source_file']))
            text = f"status: archived\narchived_reason: \"confidence {conf:.2f} below {RETIRE_CONFIDENCE_THRESHOLD:.2f} after decay\"\n"
            blocks.append(_block("retire", inst['id'] if label == "global" else f"{directory.name}-{inst['id']}", [
                ("Kind", "retire"),
                ("Instinct", f"`{inst['id']}`"),
                ("Confidence", f"{conf:.2f}"),
                ("Evidence count", str(_evidence_count(inst))),
                ("Projects seen in", inst.get('project_name', 'global') if label == "project" else "global"),
                ("Why", f"confidence decayed below {RETIRE_CONFIDENCE_THRESHOLD:.2f} (not observed recently, or contradicted)"),
                ("Proposed destination", f"`{ref}`"),
                ("Write mode", "set-frontmatter"),
            ], text, text_lang="yaml"))
    return blocks


def _render_block(block: dict) -> str:
    title = f"{block['kind']}: {block['slug']}"
    out = [f"## {title}", f"<!-- block_id: {block['block_id']} -->", "",
           "- [ ] approve", "- [ ] reject", "", "| Field | Value |", "| --- | --- |"]
    for key, value in block['fields']:
        cell = str(value).replace('|', '\\|')
        out.append(f"| {key} | {cell} |")
    out += ["", "Text to write:", "", f"~~~~{block['lang']}", block['text'].rstrip("\n"), "~~~~", ""]
    return "\n".join(out)


PROPOSAL_HEADER = """---
tags: [inbox, instinct-promotions]
date: {date}
status: open
generated_by: instinct-analyze
---

# Instinct promotions {date}

Each block below is a candidate to become durable memory. Nothing in this file has been written anywhere yet.

- Tick `approve` to accept a block. The next nightly run (or `instinct-cli.py apply-promotions`) writes exactly the text in its fence to its destination.
- Tick `reject` to decline it. It will not be proposed again.
- Edit the fenced text or the destination row before ticking if you want a different result.
- Say "apply instinct promotions" to accept every block in this file that is not ticked `reject`.

"""


def _proposal_path(day: Optional[str] = None) -> Path:
    return INBOX_DIR / f"Instinct promotions {day or _today()}.md"


def _load_ledger() -> dict:
    try:
        with open(PROMOTIONS_LEDGER, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_ledger(ledger: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(PROMOTIONS_LEDGER, json.dumps(ledger, indent=2) + "\n")


def _emit_blocks(blocks: list[dict], dry_run: bool = False, repropose: bool = False) -> int:
    ledger = _load_ledger()
    fresh = []
    for block in blocks:
        prior = ledger.get(block['block_id'])
        if prior and not repropose:
            if prior.get('status') in ('applied', 'rejected'):
                continue
            if prior.get('status') == 'proposed' and Path(prior.get('file', '')).exists():
                continue
        fresh.append(block)
    if not fresh:
        print("No new instinct candidates to propose.")
        return 0
    if dry_run:
        for block in fresh:
            print(_render_block(block))
        print(f"[DRY RUN] {len(fresh)} block(s) not written.")
        return 0
    path = _proposal_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else PROPOSAL_HEADER.format(date=_today())
    already = set(re.findall(r'<!-- block_id: (\S+) -->', existing))
    fresh = [b for b in fresh if b['block_id'] not in already]
    if not fresh:
        print(f"Every candidate is already in {_vault_ref(path)}.")
        return 0
    content = existing.rstrip("\n") + "\n\n" + "\n".join(_render_block(b) for b in fresh)
    if path.exists():
        content = re.sub(r'^status: done$', 'status: open', content, count=1, flags=re.M)
    _write_text_atomic(path, content)
    for block in fresh:
        ledger[block['block_id']] = {'status': 'proposed', 'file': str(path), 'date': _today()}
    _save_ledger(ledger)
    _inbox_pointer(path, done=False)
    kinds = defaultdict(int)
    for b in fresh:
        kinds[b['kind']] += 1
    print(f"Proposed {len(fresh)} block(s) in {_vault_ref(path)}: {dict(kinds)}")
    return 0


def cmd_promote(args) -> int:
    """Propose project -> global promotion. Writes proposal blocks, never the global note."""
    project = detect_project()
    if args.instinct_id:
        if not _validate_instinct_id(args.instinct_id):
            print(f"Invalid instinct ID: '{args.instinct_id}'.", file=sys.stderr)
            return 1
        target = next((i for i in load_project_only_instincts(project) if i.get('id') == args.instinct_id), None)
        if not target:
            print(f"Instinct '{args.instinct_id}' not found in project {project['name']}.")
            return 1
        if args.instinct_id in _global_ids():
            print(f"Instinct '{args.instinct_id}' already exists in global scope.")
            return 1
        cand = {'id': args.instinct_id, 'entries': [(project['id'], project['name'], target)],
                'avg_confidence': target.get('confidence', 0.5), 'why': "requested by the human with `promote <id>`"}
        blocks = [_promote_block(cand)]
    else:
        candidates = _promotion_candidates()
        if not candidates:
            print("No instincts qualify for promotion.")
            print(f"  Criteria: {PROMOTE_MIN_PROJECTS}+ projects with average confidence >= "
                  f"{PROMOTE_CONFIDENCE_THRESHOLD:.0%}, or scope_hint: global at >= {SCOPE_HINT_GLOBAL_THRESHOLD:.0%}")
            return 0
        blocks = [_promote_block(c) for c in candidates]
    rc = _emit_blocks(blocks, dry_run=args.dry_run, repropose=bool(args.instinct_id))
    if rc == 0 and args.apply and not args.dry_run:
        return _apply_files([_proposal_path()], mode="ids", only_ids={b['block_id'] for b in blocks})
    return rc


def cmd_propose(args) -> int:
    """Collect every qualifying candidate and file it for human review."""
    project = detect_project()
    limit = PROPOSE_DEFAULT_LIMIT if args.limit is None else max(0, args.limit)
    blocks = [_promote_block(c) for c in _promotion_candidates()]
    # Evolve per project bucket plus global, so clusters stay inside one scope.
    for pdir in _all_project_dirs():
        pinfo = {'id': pdir.name, 'instincts_dir': pdir}
        instincts = _load_instincts_from_dir(pdir, "project")
        if len(instincts) >= 3:
            blocks += _evolve_blocks(pinfo, *_evolve_candidates(instincts), limit=limit)
    global_instincts = _load_instincts_from_dir(GLOBAL_DIR, "global")
    if len(global_instincts) >= 3:
        blocks += _evolve_blocks(project, *_evolve_candidates(global_instincts), limit=limit)
    blocks += _rule_blocks()
    blocks += _retire_blocks()
    return _emit_blocks(blocks, dry_run=args.dry_run)


# ---------------------------------------------------------------------------
# apply-promotions
# ---------------------------------------------------------------------------

BLOCK_SPLIT = re.compile(r'^## .*\n<!-- block_id: (\S+) -->\n', re.M)


def _parse_blocks(text: str) -> list[dict]:
    blocks = []
    matches = list(BLOCK_SPLIT.finditer(text))
    for n, m in enumerate(matches):
        start = m.start()
        end = matches[n + 1].start() if n + 1 < len(matches) else len(text)
        body = text[start:end]
        fields = {}
        for line in body.splitlines():
            row = re.match(r'^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$', line)
            if row and row.group(1) not in ("Field", "---"):
                fields[row.group(1)] = row.group(2).replace('\\|', '|')
        fence = re.search(r'^~~~~[a-z]*\n(.*?)^~~~~\s*$', body, re.S | re.M)
        blocks.append({
            'block_id': m.group(1), 'start': start, 'end': end, 'body': body, 'fields': fields,
            'text': fence.group(1) if fence else None,
            'approve': bool(re.search(r'^- \[[xX]\] approve', body, re.M)),
            'reject': bool(re.search(r'^- \[[xX]\] reject', body, re.M)),
            'resolved': bool(re.search(r'^(Applied|Rejected) \d{4}-\d{2}-\d{2}', body, re.M)),
        })
    return blocks


def _allowed_destination(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    roots = [VAULT.resolve(), Path(CLAUDE_DIR_REF).expanduser().resolve()]
    for info in load_registry().values():
        if info.get('root'):
            roots.append((Path(info['root']) / ".claude").resolve())
    return any(resolved == r or r in resolved.parents for r in roots)


def _apply_block(block: dict) -> str:
    """Apply one block. Returns '' on success or an error naming the field and the fix."""
    f = block['fields']
    kind = f.get('Kind', '')
    bid = block['block_id']
    if block['text'] is None:
        return f"block {bid}: the ~~~~ text fence is missing. Fix: restore the fenced text under 'Text to write:'."
    try:
        dest = _resolve_ref(f.get('Proposed destination', ''))
    except ValueError as e:
        return f"block {bid}: 'Proposed destination' is invalid ({e}). Fix: use vault:<path>, ~/<path>, or an absolute path."
    if not _allowed_destination(dest):
        return (f"block {bid}: destination {dest} is outside the vault, ~/.claude, and registered project .claude "
                f"dirs. Fix: edit the 'Proposed destination' row to one of those.")
    mode = f.get('Write mode', '')
    text = block['text']
    if mode == 'create':
        if dest.exists():
            if dest.read_text(encoding="utf-8") == text:
                return ''
            return f"block {bid}: destination exists: {dest}. Fix: rename or remove it, or edit the 'Proposed destination' row."
        _write_text_atomic(dest, text)
    elif mode == 'append':
        dest.parent.mkdir(parents=True, exist_ok=True)
        existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
        if text.strip() in existing:
            return ''
        _write_text_atomic(dest, existing.rstrip("\n") + ("\n\n" if existing else "") + text)
    elif mode == 'set-frontmatter':
        if not dest.exists():
            return f"block {bid}: {dest} no longer exists. Fix: tick reject, or point the destination at the moved note."
        updates = {}
        for line in text.splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                updates[k.strip()] = v.strip()
        set_frontmatter_fields(dest, updates)
    else:
        return f"block {bid}: 'Write mode' is '{mode}'. Fix: set it to create, append, or set-frontmatter."
    if kind == 'promote-global':
        for ref in re.findall(r'`([^`]+)`', f.get('Source notes', '')):
            try:
                src = _resolve_ref(ref)
            except ValueError:
                continue
            if src.exists():
                set_frontmatter_fields(src, {'status': 'promoted', 'promoted_to': _vault_ref(dest)})
    return ''


def _mark_block(text: str, block: dict, outcome: str, tick_approve: bool) -> str:
    body = block['body']
    new_body = body
    if tick_approve:
        new_body = new_body.replace("- [ ] approve", "- [x] approve", 1)
    new_body = re.sub(r'^Failed \d{4}-\d{2}-\d{2}: .*\n', '', new_body, flags=re.M)
    new_body = new_body.replace("- [ ] reject\n", f"- [ ] reject\n\n{outcome}\n", 1) if "- [ ] reject\n" in new_body \
        else new_body.replace("- [x] reject\n", f"- [x] reject\n\n{outcome}\n", 1).replace(
            "- [X] reject\n", f"- [X] reject\n\n{outcome}\n", 1)
    return text.replace(body, new_body, 1)


def _inbox_pointer(proposal: Path, done: bool) -> None:
    """One checkbox line per proposal file under the inbox note's `## Open actions` (the
    section session start injects), ticked once every block in the file is resolved. Never
    fails the command: a pointer is a convenience, the proposal file is the record."""
    note = INBOX_NOTE
    if note is None:
        return
    link = f"[[{proposal.stem}]]"
    line = f"- [{'x' if done else ' '}] Review instinct proposals: {link} (tick approve or reject in each block)"
    try:
        text = note.read_text(encoding="utf-8") if note.exists() else ""
        if link in text:
            new = re.sub(r'^- \[[ xX]\] Review instinct proposals: ' + re.escape(link) + r'.*$',
                         lambda _m: line, text, count=1, flags=re.M)
        elif done:
            return
        else:
            heading = f"## {INBOX_SECTION}"
            m = re.search(r'^' + re.escape(heading) + r'[ \t]*$', text, re.M)
            if m:
                nxt = re.search(r'^#{1,2} ', text[m.end():], re.M)
                at = m.end() + (nxt.start() if nxt else len(text) - m.end())
                head, tail = text[:at].rstrip("\n"), text[at:]
                new = head + "\n" + line + "\n" + ("\n" + tail.lstrip("\n") if tail.strip() else "")
            else:
                new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + f"{heading}\n{line}\n"
        if new != text:
            _write_text_atomic(note, new)
    except OSError as e:
        print(f"Warning: could not update the inbox pointer in {note}: {e}. Fix: check NEVA_INBOX.", file=sys.stderr)


def _open_proposal_files() -> list[Path]:
    if INBOX_DIR is None or not INBOX_DIR.is_dir():
        return []
    out = []
    for p in sorted(INBOX_DIR.glob("Instinct promotions *.md")):
        try:
            head = p.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if re.search(r'^status: open$', head, re.M):
            out.append(p)
    return out


def _apply_files(files: list[Path], mode: str, only_ids: Optional[set] = None) -> int:
    ledger = _load_ledger()
    applied = rejected = failed = 0
    for path in files:
        if not path.exists():
            print(f"{path} does not exist. Fix: pass --file with an existing proposal file.", file=sys.stderr)
            failed += 1
            continue
        text = path.read_text(encoding="utf-8")
        for block in _parse_blocks(text):
            if block['resolved']:
                continue
            bid = block['block_id']
            if only_ids is not None and bid not in only_ids:
                continue
            if block['approve'] and block['reject']:
                msg = f"block {bid}: both approve and reject are ticked. Fix: untick one."
                print(msg, file=sys.stderr)
                text = _mark_block(text, block, f"Failed {_today()}: {msg}", False)
                failed += 1
                continue
            if block['reject']:
                text = _mark_block(text, block, f"Rejected {_today()}.", False)
                ledger[bid] = {'status': 'rejected', 'file': str(path), 'date': _today()}
                rejected += 1
                continue
            go = block['approve'] or mode in ("all", "ids")
            if not go:
                continue
            err = _apply_block(block)
            if err:
                print(err, file=sys.stderr)
                text = _mark_block(text, block, f"Failed {_today()}: {err}", False)
                failed += 1
                continue
            dest = block['fields'].get('Proposed destination', '')
            text = _mark_block(text, block, f"Applied {_today()} to {dest}.", not block['approve'])
            ledger[bid] = {'status': 'applied', 'file': str(path), 'date': _today()}
            applied += 1
        finished = all(b['resolved'] for b in _parse_blocks(text))
        if finished:
            text = re.sub(r'^status: open$', 'status: done', text, count=1, flags=re.M)
        _write_text_atomic(path, text)
        if finished:
            _inbox_pointer(path, done=True)
    _save_ledger(ledger)
    print(f"Applied {applied}, rejected {rejected}, failed {failed}.")
    return 1 if failed else 0


def cmd_apply_promotions(args) -> int:
    files = [Path(args.file).expanduser()] if args.file else _open_proposal_files()
    if not files:
        print("No open instinct proposal files.")
        return 0
    return _apply_files(files, mode="all" if args.all else "ticked")


# ---------------------------------------------------------------------------
# decay
# ---------------------------------------------------------------------------

def _reference_date(inst: dict) -> Optional[date]:
    for key in ('last_observed', 'date', 'created'):
        value = str(inst.get(key, '')).strip()[:10]
        try:
            return date.fromisoformat(value)
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(Path(inst['_source_file']).stat().st_mtime).date()
    except (OSError, KeyError):
        return None


def cmd_decay(args) -> int:
    """-0.02 per full week since last_observed; idempotent via decay_weeks_applied."""
    today = date.today()
    changed = 0
    dirs = [(GLOBAL_DIR, "global")] + [(d, "project") for d in _all_project_dirs()]
    for directory, label in dirs:
        for inst in _load_instincts_from_dir(directory, label):
            ref = _reference_date(inst)
            if ref is None:
                continue
            weeks = max(0, (today - ref).days // 7)
            applied = int(inst.get('decay_weeks_applied', 0) or 0)
            if weeks <= applied:
                continue
            old = float(inst.get('confidence', 0.5))
            new = max(0.0, round(old - DECAY_PER_WEEK * (weeks - applied), 2))
            if not args.quiet:
                print(f"{inst['id']}: {old:.2f} -> {new:.2f} ({weeks - applied} week(s) without observation)")
            if not args.dry_run:
                set_frontmatter_fields(Path(inst['_source_file']),
                                       {'confidence': new, 'decay_weeks_applied': weeks})
            changed += 1
    if not args.quiet:
        print(f"{'[DRY RUN] ' if args.dry_run else ''}Decayed {changed} instinct(s).")
    return 0


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def _project_counts(project_id: str) -> dict:
    paths = _project_paths(project_id)
    instincts = len(_load_instincts_from_dir(paths['instincts_dir'], "project"))
    observations = _count_lines(paths['observations_file'])
    return {"instincts": instincts, "observations": observations, "total": instincts + observations}


def _remove_observation_storage(project_id: str) -> None:
    root = OBS_ROOT.resolve()
    target = (OBS_ROOT / project_id).resolve()
    if target == root or root not in target.parents:
        raise ValueError(f"refusing to remove {target}: escapes {root}")
    if target.exists():
        shutil.rmtree(target)


def cmd_projects(args) -> int:
    action = getattr(args, "project_action", None)
    if action == "delete":
        return _cmd_projects_delete(args)
    if action == "merge":
        return _cmd_projects_merge(args)
    if action == "gc":
        return _cmd_projects_gc(args)
    registry = load_registry()
    if not registry:
        print("No projects registered yet.\nProjects are registered when a session runs inside a git repo.")
        return 0
    print(f"\n{'='*60}\n  KNOWN PROJECTS - {len(registry)} total\n{'='*60}\n")
    for pid, pinfo in sorted(registry.items(), key=lambda x: x[1].get('last_seen', ''), reverse=True):
        counts = _project_counts(pid)
        print(f"  {pinfo.get('name', pid)} [{pid}]")
        print(f"    Root: {pinfo.get('root', 'unknown')}")
        if pinfo.get('remote'):
            print(f"    Remote: {pinfo['remote']}")
        print(f"    Instincts: {counts['instincts']}")
        print(f"    Observations waiting: {counts['observations']}")
        print(f"    Last seen: {pinfo.get('last_seen', 'unknown')}\n")
    print(f"  GLOBAL\n    Instincts: {len(_load_instincts_from_dir(GLOBAL_DIR, 'global'))}\n\n{'='*60}\n")
    return 0


def _cmd_projects_delete(args) -> int:
    registry = load_registry()
    pid = args.project_id
    if not _validate_project_id(pid):
        print(f"Invalid project ID: {pid}", file=sys.stderr)
        return 1
    if pid not in registry and not (OBS_ROOT / pid).exists():
        print(f"Project '{pid}' not found.", file=sys.stderr)
        return 1
    counts = _project_counts(pid)
    print(f"Project: {pid}\n  Instincts: {counts['instincts']}\n  Observations: {counts['observations']}")
    if args.dry_run:
        print(f"\n[DRY RUN] Would remove '{pid}' from the registry and delete its observations.")
        return 0
    if not args.force:
        response = input(f"Remove project '{pid}' and delete its observations? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0
    registry.pop(pid, None)
    _write_registry(registry)
    _remove_observation_storage(pid)
    print(f"\nRemoved project '{pid}' and its observations.")
    idir = _project_paths(pid)['instincts_dir']
    if idir and idir.exists():
        print(f"Instinct notes were kept at {_vault_ref(idir)}. Delete them in your vault if you want them gone.")
    return 0


def _cmd_projects_gc(args) -> int:
    registry = load_registry()
    candidates = [p for p in sorted(registry) if _validate_project_id(p) and _project_counts(p)["total"] == 0]
    if not candidates:
        print("No zero-value project entries found.")
        return 0
    print(f"Zero-value project entries: {len(candidates)}")
    for pid in candidates:
        print(f"  - {registry.get(pid, {}).get('name', pid)} [{pid}]")
    if args.dry_run:
        print(f"\n[DRY RUN] Would remove {len(candidates)} entr{'y' if len(candidates) == 1 else 'ies'}.")
        return 0
    if not args.force:
        response = input(f"\nRemove {len(candidates)} zero-value entr{'y' if len(candidates) == 1 else 'ies'}? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0
    for pid in candidates:
        registry.pop(pid, None)
        _remove_observation_storage(pid)
        idir = _project_paths(pid)['instincts_dir']
        if idir and idir.is_dir() and not any(idir.iterdir()):
            idir.rmdir()
    _write_registry(registry)
    print(f"\nRemoved {len(candidates)} zero-value entr{'y' if len(candidates) == 1 else 'ies'}.")
    return 0


def _cmd_projects_merge(args) -> int:
    from_id, into_id = args.from_id, args.into_id
    if not _validate_project_id(from_id) or not _validate_project_id(into_id):
        print("Invalid project ID.", file=sys.stderr)
        return 1
    if from_id == into_id:
        print("Cannot merge a project into itself.", file=sys.stderr)
        return 1
    registry = load_registry()
    for pid, label in ((from_id, "Source"), (into_id, "Destination")):
        if pid not in registry:
            print(f"{label} project '{pid}' not found.", file=sys.stderr)
            return 1
    fc, ic = _project_counts(from_id), _project_counts(into_id)
    print(f"Merge: {from_id} -> {into_id}")
    print(f"  Source: {fc['instincts']} instincts, {fc['observations']} observations")
    print(f"  Destination before merge: {ic['instincts']} instincts, {ic['observations']} observations")
    if args.dry_run:
        print("\n[DRY RUN] Would move source instinct notes and observations into the destination.")
        return 0
    if not args.force:
        response = input(f"\nMerge '{from_id}' into '{into_id}'? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0
    src_dir, dst_dir = _project_paths(from_id)['instincts_dir'], _project_paths(into_id)['instincts_dir']
    existing = {i.get('id') for i in _load_instincts_from_dir(dst_dir, "project", include_inactive=True)}
    moved = skipped = 0
    if src_dir and src_dir.is_dir():
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in ALLOWED_INSTINCT_EXTENSIONS:
                continue
            ids = [i.get('id') for i in parse_instinct_file(f.read_text(encoding="utf-8"))]
            if any(i in existing for i in ids):
                skipped += 1
                continue
            target = dst_dir / f.name
            f.rename(target)
            set_frontmatter_fields(target, {'project_id': into_id,
                                            'project_name': _yaml_quote(registry[into_id].get('name', into_id))})
            existing.update(ids)
            moved += 1
    src_obs, dst_obs = _project_paths(from_id)['observations_file'], _project_paths(into_id)['observations_file']
    appended = 0
    if src_obs.exists():
        lines = [ln for ln in src_obs.read_text(encoding="utf-8").splitlines() if ln.strip()]
        dst_obs.parent.mkdir(parents=True, exist_ok=True)
        with open(dst_obs, "a", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(ln + "\n")
        appended = len(lines)
    registry.pop(from_id, None)
    registry[into_id]["last_seen"] = _now_iso()
    _write_registry(registry)
    _remove_observation_storage(from_id)
    print(f"\nMerged. Moved instinct notes: {moved}. Skipped duplicates: {skipped}. Appended observations: {appended}.")
    return 0


# ---------------------------------------------------------------------------
# pending + prune
# ---------------------------------------------------------------------------

def _collect_pending_dirs() -> list[Path]:
    dirs = []
    if GLOBAL_DIR is not None and (GLOBAL_DIR / "pending").is_dir():
        dirs.append(GLOBAL_DIR / "pending")
    for pdir in _all_project_dirs():
        if (pdir / "pending").is_dir():
            dirs.append(pdir / "pending")
    return dirs


def _parse_created_date(file_path: Path) -> Optional[datetime]:
    try:
        insts = parse_instinct_file(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    for key in ('created', 'date'):
        value = str(insts[0].get(key, '')).strip() if insts else ''
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    try:
        return datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _collect_pending_instincts() -> list[dict]:
    now = datetime.now(timezone.utc)
    results = []
    for pending_dir in _collect_pending_dirs():
        for file_path in sorted(pending_dir.iterdir()):
            if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_INSTINCT_EXTENSIONS:
                continue
            created = _parse_created_date(file_path)
            if created is None:
                print(f"Warning: could not parse age for pending instinct: {file_path.name}", file=sys.stderr)
                continue
            results.append({"path": file_path, "created": created, "age_days": (now - created).days,
                            "name": file_path.stem, "parent_dir": str(pending_dir)})
    return results


def cmd_prune(args) -> int:
    pending = _collect_pending_instincts()
    expired = [p for p in pending if p["age_days"] >= args.max_age]
    remaining = [p for p in pending if p["age_days"] < args.max_age]
    if args.dry_run:
        if not args.quiet:
            if expired:
                print(f"\n[DRY RUN] Would prune {len(expired)} pending instinct(s) older than {args.max_age} days:\n")
                for item in expired:
                    print(f"  - {item['name']} (age: {item['age_days']}d): {item['path']}")
            else:
                print(f"No pending instincts older than {args.max_age} days.")
            print(f"\nSummary: {len(expired)} would be pruned, {len(remaining)} remaining")
        return 0
    pruned = []
    for item in expired:
        try:
            item["path"].unlink()
            pruned.append(item)
        except OSError as e:
            if not args.quiet:
                print(f"Warning: failed to delete {item['path']}: {e}", file=sys.stderr)
    if not args.quiet:
        if pruned:
            print(f"\nPruned {len(pruned)} pending instinct(s) older than {args.max_age} days.")
            for item in pruned:
                print(f"  - {item['name']} (age: {item['age_days']}d)")
        else:
            print(f"No pending instincts older than {args.max_age} days.")
        print(f"\nSummary: {len(pruned)} pruned, {len(remaining) + len(expired) - len(pruned)} remaining")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Instinct CLI for continuous-learning-v2 (Neva)')
    sub = parser.add_subparsers(dest='command', help='Available commands')

    sub.add_parser('status', help='Show instinct status (project + global)')

    p = sub.add_parser('search', help='Search instincts')
    p.add_argument('query')
    p.add_argument('--scope', choices=['project', 'global', 'all'], default='all')
    p.add_argument('--limit', type=int, default=20)

    sub.add_parser('stats', help='Summary statistics')

    p = sub.add_parser('add', help='Record a user-stated instinct')
    p.add_argument('--id', required=True, help='kebab-case id, 2-5 words')
    p.add_argument('--trigger', required=True, help='"when <specific condition>"')
    p.add_argument('--action', required=True, help='one clear sentence')
    p.add_argument('--domain', default='workflow')
    p.add_argument('--confidence', type=float, default=0.7, help='0.1-1.0, or 1-10')
    p.add_argument('--scope', choices=['project', 'global'], default='project')
    p.add_argument('--files', nargs='*', help='related files (checked by prune for staleness)')

    p = sub.add_parser('import', help='Import instincts')
    p.add_argument('source', help='File path or https URL')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--force', action='store_true', help='Skip confirmation')
    p.add_argument('--min-confidence', type=float)
    p.add_argument('--scope', choices=['project', 'global'], default='project')
    p.add_argument('--pending', action='store_true', help='Stage in pending/ for later review')

    p = sub.add_parser('export', help='Export instincts')
    p.add_argument('--output', '-o')
    p.add_argument('--domain')
    p.add_argument('--min-confidence', type=float)
    p.add_argument('--scope', choices=['project', 'global', 'all'], default='all')
    p.add_argument('--format', choices=['instincts', 'claude-md'], default='instincts')

    p = sub.add_parser('evolve', help='Analyze and evolve instincts')
    p.add_argument('--propose', '--generate', dest='propose', action='store_true',
                   help='File candidates as proposal blocks (never writes skills directly)')
    p.add_argument('--limit', type=int, default=0, metavar='N', help='Max candidates per kind (0 = all)')
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser('promote', help='Propose project instincts for global scope')
    p.add_argument('instinct_id', nargs='?')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--apply', action='store_true',
                   help='Apply the proposed block now. Only when the human asked for this promotion.')

    p = sub.add_parser('propose', help='File every qualifying candidate for human review')
    p.add_argument('--limit', type=int, default=None, metavar='N',
                   help=f'Max evolve candidates per kind per scope (default {PROPOSE_DEFAULT_LIMIT}, 0 = all)')
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser('apply-promotions', help='Apply proposal blocks')
    p.add_argument('--file', help='One proposal file (default: every open one in the inbox)')
    p.add_argument('--all', action='store_true',
                   help='Apply every open block not ticked reject ("apply instinct promotions")')

    p = sub.add_parser('decay', help='Apply confidence decay')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--quiet', action='store_true')

    p = sub.add_parser('projects', help='List known projects')
    psub = p.add_subparsers(dest='project_action')
    d = psub.add_parser('delete', help='Remove a project entry and its observations')
    d.add_argument('project_id')
    d.add_argument('--dry-run', action='store_true')
    d.add_argument('--force', action='store_true')
    m = psub.add_parser('merge', help='Merge one project into another')
    m.add_argument('from_id')
    m.add_argument('into_id')
    m.add_argument('--dry-run', action='store_true')
    m.add_argument('--force', action='store_true')
    g = psub.add_parser('gc', help='Remove zero-value project entries')
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--force', action='store_true')

    p = sub.add_parser('prune', help='Delete pending instincts older than TTL')
    p.add_argument('--max-age', type=int, default=PENDING_TTL_DAYS)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--quiet', action='store_true')
    return parser


COMMANDS = {
    'status': cmd_status, 'search': cmd_search, 'stats': cmd_stats, 'add': cmd_add,
    'import': cmd_import, 'export': cmd_export, 'evolve': cmd_evolve, 'promote': cmd_promote,
    'propose': cmd_propose, 'apply-promotions': cmd_apply_promotions, 'decay': cmd_decay,
    'projects': cmd_projects, 'prune': cmd_prune,
}


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    _require_vault()
    return handler(args)


if __name__ == '__main__':
    sys.exit(main())
