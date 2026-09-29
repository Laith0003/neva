#!/usr/bin/env python3
"""
memory-doctor: validate the markdown memory vault used by the unified-memory skill.

Adapted from affaan-m/ECC (MIT), commit d3b8a3e: the `memory doctor` checks of the
upstream Memory Vault runtime, reimplemented over plain markdown, stdlib only.

Usage:
  memory-doctor.py doctor [--team-root <repo>]   validate every memory document
  memory-doctor.py id                           print the current project id and a fresh memory id

The doctor reports and never rewrites or deletes anything. Exit 1 when it finds errors.
"""

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path

SCHEMA = "neva.memory.v1"
KINDS = {"context": "contexts", "decision": "decisions", "fact": "facts", "handoff": "handoffs",
         "lesson": "lessons", "note": "notes", "preference": "preferences", "runbook": "runbooks"}
SCOPES = {"project", "team", "user"}
STATUSES = {"active", "rejected", "superseded"}
REQUIRED = ["schema", "id", "title", "kind", "scope", "trust", "status", "source_harness",
            "target_harnesses", "tags", "links", "created_at", "updated_at"]
ID_RE = re.compile(r"^mem_[a-z0-9][a-z0-9_-]{2,127}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|credentials?|auth)"
    r"([\"'\s:=]{1,8})((?:bearer|basic|token|bot)\s+)?([A-Za-z0-9_\-/.+=]{8,256})")
BODY_MAX_BYTES = 65536


def vault_root() -> Path:
    value = os.environ.get("NEVA_VAULT")
    if not value or not Path(value).is_absolute() or not Path(value).is_dir():
        print("NEVA_VAULT is not set to an existing absolute path. Fix: export NEVA_VAULT=/absolute/path/to/your/vault",
              file=sys.stderr)
        sys.exit(2)
    return Path(value) / "06 Memory" / "handoffs"


def _git(args, cwd=None):
    try:
        r = subprocess.run(["git", *(["-C", cwd] if cwd else []), *args], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def project_id() -> str:
    """Same algorithm as continuous-learning-v2, so handoffs and instincts share ids."""
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    root = ""
    if env_dir and os.path.isdir(env_dir):
        root = _git(["rev-parse", "--show-toplevel"], env_dir) or os.path.realpath(env_dir)
    root = (root or _git(["rev-parse", "--show-toplevel"])).rstrip("/")
    if not root:
        return "unscoped"
    remote = re.sub(r"://[^@]+@", "://", _git(["remote", "get-url", "origin"], root))
    if remote:
        net = not remote.startswith("file://") and ("://" in remote or re.match(r"^[^@/:]+@[^:/]+:", remote))
        norm = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", remote)
        norm = re.sub(r"^[^@/:]+@([^:/]+):", r"\1/", norm)
        norm = re.sub(r"/+$", "", re.sub(r"\.git/?$", "", norm))
        source = norm.lower() if net else norm
    else:
        wt = _git(["worktree", "list", "--porcelain"], root)
        source = next((ln.split(" ", 1)[1] for ln in wt.splitlines() if ln.startswith("worktree ")), root)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def parse(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return None, text, "no frontmatter block (--- ... ---) at the top"
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            return None, text, f"frontmatter line is not 'key: value': {line[:60]}"
        key, raw = line.split(":", 1)
        try:
            meta[key.strip()] = json.loads(raw.strip())
        except json.JSONDecodeError:
            return None, text, f"field '{key.strip()}' is not a JSON value (quote strings, use [..] for lists)"
    return meta, m.group(2), None


def check(path: Path, meta: dict, body: str, expected_scope: str) -> list:
    errs = []
    for key in REQUIRED:
        if key not in meta:
            errs.append(f"missing field '{key}'")
    extra = set(meta) - set(REQUIRED)
    if extra:
        errs.append(f"unknown field(s) {sorted(extra)}: the schema allows no extra fields")
    if meta.get("schema") != SCHEMA:
        errs.append(f"schema must be \"{SCHEMA}\"")
    if not ID_RE.match(str(meta.get("id", ""))):
        errs.append("id must match mem_[a-z0-9][a-z0-9_-]{2,127}")
    elif path.stem != meta["id"]:
        errs.append(f"file name must be <id>.md ({meta['id']}.md)")
    title = str(meta.get("title", ""))
    if not title.strip() or len(title) > 200:
        errs.append("title must be 1 to 200 characters")
    if meta.get("kind") not in KINDS:
        errs.append(f"kind must be one of {sorted(KINDS)}")
    elif path.parent.name != KINDS[meta["kind"]]:
        errs.append(f"kind '{meta['kind']}' belongs in a '{KINDS[meta['kind']]}/' folder")
    if meta.get("scope") not in SCOPES:
        errs.append(f"scope must be one of {sorted(SCOPES)}")
    elif meta["scope"] != expected_scope:
        errs.append(f"scope is '{meta['scope']}' but the file lives under the {expected_scope} root")
    if meta.get("trust") != "unreviewed":
        errs.append("trust must be \"unreviewed\" (reviewed knowledge is promoted into a governed doc instead)")
    if meta.get("status") not in STATUSES:
        errs.append(f"status must be one of {sorted(STATUSES)}")
    if not SLUG_RE.match(str(meta.get("source_harness", ""))):
        errs.append("source_harness must be a lowercase slug")
    for key, lo, hi in (("target_harnesses", 1, 32), ("tags", 0, 32), ("links", 0, 64)):
        val = meta.get(key)
        if not isinstance(val, list) or not lo <= len(val) <= hi or len(set(map(str, val))) != len(val):
            errs.append(f"{key} must be a list of {lo} to {hi} unique items")
    for key in ("target_harnesses", "tags"):
        if isinstance(meta.get(key), list) and not all(SLUG_RE.match(str(v)) for v in meta[key]):
            errs.append(f"every {key} entry must be a lowercase slug")
    for key in ("created_at", "updated_at"):
        if not TS_RE.match(str(meta.get(key, ""))):
            errs.append(f"{key} must look like 2026-07-26T20:00:00.000Z")
    if not body.strip():
        errs.append("body is empty")
    if len(body.encode("utf-8")) > BODY_MAX_BYTES:
        errs.append(f"body exceeds {BODY_MAX_BYTES} bytes")
    if SECRET_RE.search(body):
        errs.append("body contains a secret-shaped value. Fix: remove it; memories never hold credentials")
    return errs


def doctor(team_repo: str) -> int:
    root = vault_root()
    roots = [(root / "project", "project"), (root / "user", "user")]
    if team_repo:
        roots.append((Path(team_repo) / ".neva" / "memory" / "team", "team"))
    ids, docs, errors, skipped = {}, [], 0, []
    for base, scope in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                skipped.append(path)
                continue
            if not path.is_file() or path.suffix != ".md":
                continue
            meta, body, perr = parse(path)
            problems = [perr] if perr else check(path, meta, body, scope)
            if meta and meta.get("id"):
                ids.setdefault(meta["id"], []).append(path)
                docs.append((path, meta))
            for p in problems:
                print(f"ERROR {path}: {p}")
                errors += 1
    for mid, paths in ids.items():
        if len(paths) > 1:
            print(f"ERROR duplicate id {mid}: " + ", ".join(str(p) for p in paths))
            errors += 1
    for path, meta in docs:
        for link in meta.get("links") or []:
            if link not in ids:
                print(f"ERROR {path}: broken link {link} (no document has that id)")
                errors += 1
    for path in skipped:
        print(f"SKIPPED symlink {path} (memory readers never follow symlinks)")
    print(f"Checked {len(docs)} document(s): {errors} error(s), {len(skipped)} symlink(s) skipped. Nothing was changed.")
    return 1 if errors else 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] not in ("doctor", "id"):
        print(__doc__)
        return 1
    if args[0] == "id":
        print(f"project_id: {project_id()}")
        print(f"memory_id:  mem_{date.today().strftime('%Y%m%d')}_{secrets.token_hex(5)}")
        return 0
    team = args[args.index("--team-root") + 1] if "--team-root" in args else ""
    return doctor(team)


if __name__ == "__main__":
    sys.exit(main())
