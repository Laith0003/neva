# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""MCP server health with backoff. No network probes: state comes from real call outcomes.

PostToolUseFailure on an mcp__<server>__<tool> call whose error looks like a transport, auth,
  rate-limit or availability failure marks the server unhealthy for a backoff window
  (NEVA_MCP_HEALTH_BACKOFF_MS, default 30000, doubling per consecutive failure, capped at
  NEVA_MCP_HEALTH_MAX_BACKOFF_MS, default 600000). Application errors do not count.
PreToolUse on that server blocks with the reason and the time it clears, until the window passes.
  NEVA_MCP_HEALTH_FAIL_OPEN=1 turns the block into a warning.
PostToolUse success on the server clears its state.
"""
import os
import re
import time

from . import common as c

FAILURE_PATTERNS = [
    ("401", re.compile(r"\b401\b|unauthori[sz]ed|auth(?:entication)?\s+(?:failed|expired|invalid)", re.I)),
    ("403", re.compile(r"\b403\b|forbidden", re.I)),
    ("429", re.compile(r"\b429\b|rate.?limit|too many requests", re.I)),
    ("503", re.compile(r"\b503\b|service unavailable|overloaded|temporarily unavailable", re.I)),
    ("transport", re.compile(r"ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ECONNRESET|timed? ?out|socket hang up|"
                             r"connection (?:failed|lost|reset|closed|refused)|not connected|server disconnected",
                             re.I)),
]


def _server(tool_name):
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name[5:].split("__")
    return parts[0] if len(parts) >= 2 and parts[0] else None


def _state_path():
    return os.path.join(c.state_dir(), "mcp-health.json")


def _failure_text(data):
    bits = []
    for k in ("error", "message", "tool_response", "tool_output"):
        v = data.get(k)
        if isinstance(v, str):
            bits.append(v)
        elif isinstance(v, dict):
            bits += [str(v.get(x)) for x in ("error", "output", "stderr", "message") if v.get(x)]
    return "\n".join(bits)


def detect(text):
    for code, rx in FAILURE_PATTERNS:
        if rx.search(text or ""):
            return code
    return None


def run(ctx):
    server = _server(ctx.tool_name)
    if not server:
        return None
    path = _state_path()
    state = c.read_json(path, {}) or {}
    servers = state.setdefault("servers", {})
    now_ms = int(time.time() * 1000)
    entry = servers.get(server) or {}

    if ctx.event == "PreToolUse":
        if entry.get("status") == "unhealthy" and int(entry.get("next_retry", 0)) > now_ms:
            left = max(1, (int(entry["next_retry"]) - now_ms) // 1000)
            until = time.strftime("%H:%M:%S", time.localtime(int(entry["next_retry"]) / 1000))
            msg = (f"MCP server '{server}' failed {entry.get('failures', 1)} time(s) in a row "
                   f"({entry.get('code')}: {c.one_line(entry.get('last_error', ''), 160)}). It is marked unhealthy "
                   f"until {until} ({left}s). Wait for that, reconnect it with /mcp, or use another route.")
            if c.env_flag("NEVA_MCP_HEALTH_FAIL_OPEN"):
                return {"context": msg}
            return {"block": "Blocked: " + msg + " (NEVA_MCP_HEALTH_FAIL_OPEN=1 warns instead of blocking.)"}
        return None

    if ctx.event == "PostToolUseFailure":
        text = _failure_text(ctx.data)
        code = detect(text)
        if not code:
            return None
        failures = int(entry.get("failures", 0)) + 1
        base = c.env_int("NEVA_MCP_HEALTH_BACKOFF_MS", 30_000, 1)
        cap = c.env_int("NEVA_MCP_HEALTH_MAX_BACKOFF_MS", 600_000, 1)
        delay = min(base * (2 ** (failures - 1)), cap)
        servers[server] = {"status": "unhealthy", "failures": failures, "code": code,
                           "last_error": text[:500], "checked": now_ms, "next_retry": now_ms + delay}
        c.write_json(path, state)
        return {"context": (f"MCP server '{server}' marked unhealthy for {max(1, delay // 1000)}s after a {code} "
                            "failure. Calls to it are blocked until then; do not retry in a loop.")}

    if ctx.event == "PostToolUse" and entry:
        servers.pop(server, None)
        c.write_json(path, state)
    return None
