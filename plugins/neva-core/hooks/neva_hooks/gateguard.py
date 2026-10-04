# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""GateGuard fact-forcing gate (strict profile only).

The first Edit, Write or MultiEdit of each file in a session is denied until the model presents
facts: who imports the file, which public API changes, the data shapes it touches, and the
user's instruction verbatim. Asking "are you sure?" gets "yes"; demanding facts makes the model
actually look. A retry of the same file is allowed.

The first GATEGUARD_FACT_FORCE_FULL_DENIALS denials (default 3) carry the full block; later ones
are one line with an ordinal, so identical blocks do not pile up in long sessions.

Controls: NEVA_GATEGUARD=off (or GATEGUARD_DISABLED=1), GATEGUARD_EXEMPT_GLOBS (comma globs,
project-relative unless they start with /), GATEGUARD_FACT_FORCE_FULL_DENIALS, GATEGUARD_STATE_DIR
(default <NEVA_STATE_DIR>/gateguard, <session>.json, at most 500 checked paths). Subagent calls
and .claude/settings*.json are allowed. If the state cannot be saved the edit is allowed with a
warning, so the gate never loops. Bash is not gated.
"""
import os
import re

from . import common as c

MAX_ENTRIES = 500


def _disabled():
    if c.env("NEVA_GATEGUARD").strip().lower() in c.FALSE_VALUES:
        return True
    return c.env("GATEGUARD_DISABLED").strip() == "1"


def _glob_rx(glob):
    out, i = "", 0
    while i < len(glob):
        ch = glob[i]
        if glob[i:i + 3] == "**/":
            out += "(?:.*/)?"
            i += 3
            continue
        if glob[i:i + 2] == "**":
            out += ".*"
            i += 2
            continue
        out += "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch)
        i += 1
    return re.compile("^" + out + "$")


def exempt(path, root):
    globs = [g.strip() for g in c.env("GATEGUARD_EXEMPT_GLOBS").split(",") if g.strip()]
    if not globs:
        return False
    real = os.path.realpath(path)
    rel = os.path.relpath(real, os.path.realpath(root)).replace(os.sep, "/")
    for g in globs:
        target = real.replace(os.sep, "/") if g.startswith("/") else rel
        if _glob_rx(g).match(target):
            return True
    return False


def _state_path(ctx):
    d = c.env("GATEGUARD_STATE_DIR") or os.path.join(c.state_root(), "gateguard")
    c.ensure_dir(d)
    return os.path.join(d, f"{ctx.sid}.json")


INVISIBLE = {chr(cp) for cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF)}


def _clean(p):
    return "".join(ch for ch in str(p) if ch.isprintable() and ch not in INVISIBLE)[:500]


def full_msg(action, path):
    p = _clean(path)
    if action == "edit":
        facts = ["1. List ALL files that import or require this file (search the tree with Grep or Glob)",
                 "2. List the public functions, classes or endpoints this change affects"]
    else:
        facts = ["1. Name the file(s) and line(s) that will call or load this new file",
                 "2. Confirm no existing file already serves this purpose (search the tree with Grep or Glob)"]
    return "\n".join([
        f"[Fact-Forcing Gate] Before the first {action} of {p}, present these facts:",
        *facts,
        "3. If the file reads or writes data, show the field names, structure and date format "
        "(synthetic values, never real records)",
        "4. Quote the user's current instruction verbatim",
        "",
        "Then retry the same operation. If this call came in a parallel batch, other edits to this file may "
        "already be applied: re-read it before building on them.",
        "Scope out low-value trees with GATEGUARD_EXEMPT_GLOBS; NEVA_GATEGUARD=off disables the gate.",
    ])


def short_msg(action, path, n):
    return (f"[Fact-Forcing Gate] (denial #{n} this session) First {action} of {_clean(path)}: state importers or "
            "callers, affected API, data shapes if any, and the user's verbatim instruction, then retry.")


def run(ctx):
    if _disabled() or ctx.data.get("agent_id"):
        return None
    targets = []
    if ctx.tool_name in ("Edit", "Write"):
        targets = [(ctx.file_path(), "edit" if ctx.tool_name == "Edit" or os.path.exists(ctx.file_path()) else "creation")]
    elif ctx.tool_name == "MultiEdit":
        targets = [(ctx.file_path(), "edit")] + [(e.get("file_path"), "edit") for e in ctx.tool_input.get("edits") or []
                                                if isinstance(e, dict) and e.get("file_path")]
    root = c.env("CLAUDE_PROJECT_DIR") or ctx.cwd
    path = _state_path(ctx)
    state = c.read_json(path, {}) or {}
    checked = state.get("checked", [])
    for fp, action in targets:
        if not fp:
            continue
        key = os.path.realpath(fp if os.path.isabs(fp) else os.path.join(ctx.cwd, fp))
        if key in checked or (os.sep + ".claude" + os.sep in key
                              and re.match(r"settings.*\.json$", os.path.basename(key))):
            continue
        if exempt(key, root):
            continue
        checked.append(key)
        denials = int(state.get("denials", 0)) + 1
        state.update({"checked": checked[-MAX_ENTRIES:], "denials": denials})
        try:
            c.write_json(path, state)
        except OSError:
            return {"system": "GateGuard could not save its state, so it allowed this edit to avoid a retry loop. "
                              "Check GATEGUARD_STATE_DIR permissions."}
        budget = c.env_int("GATEGUARD_FACT_FORCE_FULL_DENIALS", 3, 0)
        return {"block": full_msg(action, fp) if denials <= budget else short_msg(action, fp, denials)}
    return None
