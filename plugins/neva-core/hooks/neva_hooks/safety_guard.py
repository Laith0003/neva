# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
# Merged with garrytan/gstack careful, guard and freeze (MIT, Garry Tan).
"""safety-guard skill hooks. Both are off until the skill turns them on, so every profile runs them.

safety_careful (PreToolUse, Bash): active while <NEVA_STATE_DIR>/safety-guard/careful exists
  (written by `/safety-guard careful` or `guard`, removed by `off`). A destructive command gets
  permissionDecision ask with a `[careful]` reason naming the risk; the user can approve it.
  `rm -r` whose every target is a build artifact (node_modules, .next, dist, __pycache__, .cache,
  build, .turbo, coverage) passes silently.
safety_freeze (PreToolUse, Edit, Write, MultiEdit): active while
  <NEVA_STATE_DIR>/safety-guard/freeze-dir.txt holds a directory. Edits outside it are denied.
  Paths are resolved (relative to the working directory, symlinks and .. collapsed) on both sides;
  `/src` never matches `/src-old`.
Every warn or deny appends {"event", "mode", "pattern", "ts", "repo"} to
<NEVA_STATE_DIR>/safety-guard.log: the rule name only, never the command text or file content.
"""
import datetime
import json
import os
import re
import shlex

from . import common as c

SAFE_RM_TARGETS = {"node_modules", ".next", "dist", "__pycache__", ".cache", "build", ".turbo", "coverage"}
PATTERNS = [
    ("drop", re.compile(r"(?i)\bdrop\s+(?:table|database)\b"),
     "Destructive: DROP TABLE or DROP DATABASE deletes data. Run a SELECT COUNT(*) or take a backup first."),
    ("truncate", re.compile(r"(?i)\btruncate\s+(?:table\s+)?[\w`\"'.]+"),
     "Destructive: TRUNCATE deletes every row. Check the table and take a backup first."),
    ("git-force-push", re.compile(r"\bgit\s+(?:-\S+\s+)*push\b[^;&|]*?(?:\s--force(?![-\w])|\s-f\b|\s\+\S)"),
     "History rewrite: a force push overwrites the remote branch. Prefer git push --force-with-lease."),
    ("git-reset-hard", re.compile(r"\bgit\s+(?:-\S+\s+)*reset\s+[^;&|]*--hard\b"),
     "Destructive: git reset --hard discards all uncommitted changes. Prefer git stash."),
    ("git-discard", re.compile(r"\bgit\s+(?:-\S+\s+)*(?:checkout|restore)\s+(?:--\s+)?\.(?:\s|$)"),
     "Destructive: this discards every uncommitted change in the tree. Prefer git stash."),
    ("kubectl-delete", re.compile(r"\bkubectl\s+(?:\S+\s+)*delete\b"),
     "Production impact: kubectl delete removes live resources. Confirm the context and namespace."),
    ("docker-force", re.compile(r"\bdocker\s+(?:rm\s+(?:\S+\s+)*(?:-\w*f\w*|--force)\b|system\s+prune\b)"),
     "Destructive: this removes containers or images. Check what is running first."),
    ("chmod-777", re.compile(r"\bchmod\s+(?:-\w+\s+)*0?777\b"),
     "Risky: chmod 777 makes files world-writable. Use the narrowest mode that works."),
    ("npm-publish", re.compile(r"\bnpm\s+publish\b"),
     "Public: npm publish releases this package to the registry. Confirm the version and the files."),
    ("no-verify", re.compile(r"(?:^|\s)--no-verify\b"),
     "Skips hooks and checks: --no-verify bypasses the repository's safety net."),
]


def _guard_dir():
    return os.path.join(c.state_root(), "safety-guard")


def _log(ctx, event, mode, pattern):
    try:
        rec = {"event": event, "mode": mode, "pattern": pattern,
               "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "repo": os.path.basename(os.path.realpath(ctx.cwd))}
        c.ensure_dir(c.state_root())
        with open(os.path.join(c.state_root(), "safety-guard.log"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _segments(cmd):
    return [s for s in re.split(r"\|\||&&|[;|\n]", cmd) if s.strip()]


def _tokens(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def rm_reason(cmd):
    """(rule, warning) for a recursive rm that touches anything but build artifacts."""
    for seg in _segments(cmd):
        toks = _tokens(seg)
        sudo = False
        while toks and (toks[0] in ("sudo", "command", "nice") or re.match(r"^\w+=", toks[0])):
            sudo = sudo or toks[0] == "sudo"
            toks = toks[1:]
        if not toks or os.path.basename(toks[0]) != "rm":
            continue
        flags = [t for t in toks[1:] if t.startswith("-")]
        targets = [t for t in toks[1:] if not t.startswith("-")]
        recursive = any(f == "--recursive" or (not f.startswith("--") and re.search(r"[rR]", f)) for f in flags)
        if sudo:
            return "sudo-rm", "Privileged delete: sudo rm removes files as root. Double-check every path."
        if not recursive:
            continue
        if targets and all(os.path.basename(t.rstrip("/")) in SAFE_RM_TARGETS for t in targets):
            continue
        shown = ", ".join(targets[:3]) or "(no target)"
        return "rm-recursive", f"Destructive: rm -r deletes {c.one_line(shown, 120)} recursively. Check the path."
    return None


def careful_reason(cmd):
    hit = rm_reason(cmd)
    if hit:
        return hit
    for name, rx, why in PATTERNS:
        if rx.search(cmd):
            return name, why
    return None


def careful(ctx):
    if not os.path.exists(os.path.join(_guard_dir(), "careful")):
        return None
    cmd = str(ctx.tool_input.get("command") or "")
    if not cmd:
        return None
    hit = careful_reason(cmd)
    if not hit:
        return None
    _log(ctx, "warn", "careful", hit[0])
    return {"ask": f"[careful] {hit[1]}"}


def freeze_dir():
    raw = c.read_text(os.path.join(_guard_dir(), "freeze-dir.txt")).strip()
    if not raw:
        return ""
    return os.path.realpath(os.path.expanduser(raw.replace("//", "/"))).rstrip("/") or "/"


def freeze(ctx):
    root = freeze_dir()
    if not root:
        return None
    paths = [ctx.file_path()] + [e.get("file_path") for e in ctx.tool_input.get("edits") or []
                                 if isinstance(e, dict) and e.get("file_path")]
    for fp in [p for p in paths if p]:
        full = fp if os.path.isabs(fp) else os.path.join(ctx.cwd, fp)
        real = os.path.realpath(full.replace("//", "/")).rstrip("/")
        if real == root or real.startswith(root.rstrip("/") + "/"):
            continue
        _log(ctx, "deny", "freeze", "outside-boundary")
        return {"block": (f"[freeze] Blocked: {real} is outside the freeze boundary ({root}/). Only edits within the "
                          "frozen directory are allowed. Run /safety-guard off to lift it, or /safety-guard freeze "
                          "<dir> to move it.")}
    return None
