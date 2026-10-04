# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""plan-canvas-pending (Stop): never let a turn end while canvas feedback sits undelivered.

Reads sessions.json and server.json in the plan-canvas state dir (NEVA_PLAN_CANVAS_STATE_DIR,
default <NEVA_STATE_DIR>/plan-canvas). Candidates: sessions not ended, with queued feedback,
whose artifact lives under the working directory (NEVA_PLAN_CANVAS_STOP_SCOPE=all widens it to
every session). Each candidate is drained through the running server's own long-poll endpoint
(GET /api/await?key=<key>&timeoutMs=0, 1 s timeout), so the server stays the single owner of
its state and the items are delivered exactly once. Up to 20 items become the block reason.
Any error, a missing state dir or an unreachable server allows the stop.
"""
import json
import os
import re
import urllib.request

from . import common as c

MAX_ITEMS = 20


def state_dir():
    v = c.env("NEVA_PLAN_CANVAS_STATE_DIR").strip()
    return os.path.abspath(v) if v else os.path.join(c.state_root(), "plan-canvas")


def _under(path, root):
    try:
        p, r = os.path.realpath(path), os.path.realpath(root)
    except (OSError, ValueError):
        return False
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def candidates(ctx, sessions):
    wide = c.env("NEVA_PLAN_CANVAS_STOP_SCOPE").strip().lower() == "all"
    root = c.env("CLAUDE_PROJECT_DIR") or ctx.cwd
    out = []
    for s in sessions.values():
        if not isinstance(s, dict) or s.get("status") == "ended":
            continue
        if not s.get("pendingFeedback"):
            continue
        key = str(s.get("key") or "")
        if not re.fullmatch(r"[a-f0-9]{12}", key):
            continue
        if wide or _under(str(s.get("file") or ""), root):
            out.append(s)
    return out


def drain(port, key, timeout=1.0):
    url = f"http://127.0.0.1:{int(port)}/api/await?key={key}&timeoutMs=0"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def describe(item):
    kind = item.get("kind")
    if kind == "verdict":
        return f"verdict: {item.get('verdict')}"
    if kind == "annotation":
        a = item.get("anchor") or {}
        where = a.get("snippet") or a.get("selector") or "an element"
        return f"annotation on \"{c.one_line(where, 80)}\": {c.one_line(item.get('text'), 300)}"
    return f"chat: {c.one_line(item.get('text'), 300)}"


def run(ctx):
    d = state_dir()
    sessions = (c.read_json(os.path.join(d, "sessions.json"), {}) or {}).get("sessions")
    server = c.read_json(os.path.join(d, "server.json"), {}) or {}
    if not isinstance(sessions, dict) or not server.get("port"):
        return None
    lines, total = [], 0
    for s in candidates(ctx, sessions):
        if total >= MAX_ITEMS:
            break
        try:
            res = drain(server["port"], s["key"])
        except Exception:
            continue
        items = [i for i in (res.get("items") or []) if isinstance(i, dict)] if res.get("status") == "feedback" else []
        if not items:
            continue
        items = items[: MAX_ITEMS - total]
        total += len(items)
        lines.append(f"{s.get('file')}:")
        lines += [f"  - {describe(i)}" for i in items]
        if res.get("sessionEnded"):
            lines.append("  (the user ended this review: do not reopen it)")
    if not lines:
        return None
    return {"block": ("Plan canvas feedback arrived with nothing listening. Answer it in the canvas "
                      "(`plan-canvas await <file> --reply \"...\"`), act on it, and keep an `await` running:\n"
                      + "\n".join(lines))}
