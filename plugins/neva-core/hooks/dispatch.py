#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""One process per hook event. Reads the hook JSON on stdin, runs every module registered
for the event in hooks.meta.json under the active profile, and merges their results.

Usage (from hooks.json):  python3 dispatch.py <Event>
  Every event is registered once with matcher `*`, so one tool call spawns one process per
  event. Tool filtering happens here: a module with a `tools` list in hooks.meta.json runs
  only for those tool names (fnmatch patterns, so `mcp__*` works). A trailing argument from an
  older hooks.json is accepted and ignored.

Controls:
  NEVA_HOOK_PROFILE    minimal | standard (default) | strict
  NEVA_DISABLED_HOOKS  comma list of module ids to skip
  NEVA_HEADLESS=1      skip everything (set by tools that call `claude -p` themselves)

Contract with Claude Code:
  exit 0, optional JSON on stdout (additionalContext, permissionDecision ask, systemMessage)
  exit 2, reason on stderr, only when a module deliberately blocks
A module that raises is logged to <data dir>/hooks.log and skipped; it never breaks the session.
"""
import fnmatch
import importlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from neva_hooks import common  # noqa: E402

PROFILES = ("minimal", "standard", "strict")
CONTEXT_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure")
MAX_STDIN = 8 * 1024 * 1024


def load_meta():
    with open(os.path.join(HERE, "hooks.meta.json"), encoding="utf-8") as fh:
        return json.load(fh)


def active_profile():
    p = common.env("NEVA_HOOK_PROFILE", "standard").strip().lower() or "standard"
    if p not in PROFILES:
        common.log(f"[dispatch] unknown NEVA_HOOK_PROFILE '{p}', using standard")
        p = "standard"
    return p


def disabled_ids():
    return {x.strip() for x in common.env("NEVA_DISABLED_HOOKS").split(",") if x.strip()}


def tool_matches(m, tool):
    tools = m.get("tools")
    if not tools:
        return True
    return bool(tool) and any(fnmatch.fnmatchcase(tool, pat) for pat in tools)


def selected_modules(meta, event, profile, disabled, tool=""):
    return [m for m in meta.get("modules", [])
            if event in m.get("events", []) and profile in m.get("profiles", [])
            and m.get("id") not in disabled and tool_matches(m, tool)]


def run_modules(ctx, mods):
    results = []
    for m in mods:
        t0 = time.time()
        try:
            mod = importlib.import_module("neva_hooks." + m["module"])
            fn = getattr(mod, m.get("function", "run"))
            r = fn(ctx)
            if isinstance(r, dict) and r:
                results.append((m["id"], r))
        except Exception:
            common.log_exception(f"module {m.get('id')} on {ctx.event}")
        dt = time.time() - t0
        if dt > 1.5:
            common.log(f"[slow] {m.get('id')} took {dt:.2f}s on {ctx.event}")
    return results


def merge(event, results):
    """Return (stdout_text, stderr_text, exit_code)."""
    blocks = [f"[{mid}] {r['block']}" for mid, r in results if r.get("block")]
    if blocks:
        return "", "\n\n".join(blocks), 2
    asks = [r["ask"] for _, r in results if r.get("ask")]
    ctx_parts = [r["context"] for _, r in results if r.get("context")]
    systems = [r["system"] for _, r in results if r.get("system")]
    out = {}
    if event == "PreToolUse" and asks:
        hso = {"hookEventName": event, "permissionDecision": "ask",
               "permissionDecisionReason": "\n".join(asks)}
        if ctx_parts:
            hso["additionalContext"] = "\n\n".join(ctx_parts)
        out["hookSpecificOutput"] = hso
    elif ctx_parts and event in CONTEXT_EVENTS:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": "\n\n".join(ctx_parts)}
    elif ctx_parts:
        systems = ctx_parts + systems
    if systems:
        out["systemMessage"] = "\n".join(systems)
    return (json.dumps(out) if out else ""), "", 0


def main(argv):
    event = argv[1] if len(argv) > 1 else ""
    try:
        raw = sys.stdin.read(MAX_STDIN)
    except Exception:
        raw = ""
    if common.env_flag("NEVA_HEADLESS") or not event:
        return 0
    parse_error = False
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        common.log(f"[dispatch] {event}: stdin was not JSON ({len(raw)} bytes); running with empty input")
        data, parse_error = {}, True
    if not isinstance(data, dict):
        data, parse_error = {}, True
    tool = str(data.get("tool_name") or "")
    profile = active_profile()
    try:
        mods = selected_modules(load_meta(), event, profile, disabled_ids(), tool)
    except Exception:
        common.log_exception("dispatch: hooks.meta.json unreadable")
        return 0
    if not mods:
        return 0
    ctx = common.Ctx(event, "", data, profile, raw=raw, parse_error=parse_error)
    stdout, stderr, code = merge(event, run_modules(ctx, mods))
    try:
        if stdout:
            sys.stdout.write(stdout)
            sys.stdout.flush()
        if stderr:
            common.emit_stderr(stderr)
    except Exception:
        pass
    return code


if __name__ == "__main__":
    try:
        rc = main(sys.argv)
    except Exception:
        common.log_exception("dispatch: unexpected")
        rc = 0
    sys.exit(rc)
