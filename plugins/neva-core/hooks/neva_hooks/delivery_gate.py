# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
# Optional pattern set derived from obra/superpowers verification-before-completion (MIT, Jesse Vincent).
"""Delivery gate (Stop, strict profile): the delivery-gate skill's mechanical checks.

Deterministic only: disk usage, file modification dates, regex on the transcript. No model.
Order: disk first (can block even on short sessions); transcripts under 40 chars skip the rest;
rationalization phrases (warn only); learning capture (block only when the task was complex).

  disk free < NEVA_DELIVERY_DISK_REMIND_GB (50)  reminder
  disk free < NEVA_DELIVERY_DISK_WARN_GB (30)    warning
  disk free < NEVA_DELIVERY_DISK_CRIT_GB (15)    block
  complex task = 3 or more structured Edit or Write tool calls in the transcript
  learning libraries (in the memory dir) not touched today:
    3 or more stale, or growth-log stale        block (complex tasks only)
    some stale                                   warning
  no memory dir                                  warning on complex tasks, never a block

Memory dir: NEVA_MEMORY_DIR, else the Claude Code project memory dir for CLAUDE_PROJECT_DIR (or
the working directory). NEVA_DELIVERY_GATE_EXTENDED=1 adds the success-without-evidence phrases.
A stop that is already a retry (stop_hook_active) is never blocked again, so the gate cannot loop.
"""
import datetime
import os
import re
import shutil

from . import common as c

RATIONALIZE = [
    r"(?:this|that)\s+is\s+a\s+pre[- ]existing\s+(?:issue|bug)\b(?!\s+(?:that|which|and))",
    r"skipping\s+(?:tests?|lint|coverage|type[- ]check)\s+for\s+now",
    r"(?:tests?|coverage)\s+(?:are|is)\s+(?:failing|broken)\s+but\s+(?:I|we)\s+(?:'ll|can|will)\s+"
    r"(?:fix|address|resolve|handle)",
    r"(?:not\s+addressing|won't\s+fix|leaving)\s+the\s+(?:failing|broken)\s+(?:tests?|builds?|integration\s+tests?)",
]
EXTENDED = [
    r"\b(?:should|probably|seems to) (?:work|pass|be fixed)\b",
    r"\b(?:tests?|build|lint) (?:should|will) pass\b",
    r"\bagent (?:said|reported) (?:success|done)\b",
    r"\bjust this once\b",
]
LIBS = {
    "ratings-tracker": "ratings-tracker.md",
    "decisions-log": "decisions/log.md",
    "growth-log": "growth-log/",
    "output-index": "output-index.md",
    "tooling-capabilities": "tooling_capabilities.md",
}
MIN_CHARS = 40
COMPLEX_THRESHOLD = 3


def memory_dir(cwd=None):
    override = c.env("NEVA_MEMORY_DIR").strip()
    if override:
        override = os.path.expanduser(override)
        return override if os.path.isdir(override) else None
    cwd = c.env("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    safe = cwd.replace(":", "-").replace("\\", "-").replace("/", "-")
    base = c.env("CLAUDE_CONFIG_DIR").strip() or os.path.join(c.home(), ".claude")
    mem = os.path.join(os.path.expanduser(base), "projects", safe, "memory")
    return mem if os.path.isdir(mem) else None


def _touched_today(path, today):
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(path)) == today
    except OSError:
        return False


def stale_libs(mem):
    today = datetime.date.today()
    stale = []
    for name, rel in LIBS.items():
        full = os.path.join(mem, rel)
        if os.path.isdir(full):
            hit = any(_touched_today(os.path.join(dp, f), today) for dp, _, fs in os.walk(full) for f in fs)
            if not hit:
                stale.append(name)
        elif not _touched_today(full, today):
            stale.append(name)
    return stale


def disk_free_gb():
    try:
        return shutil.disk_usage(c.home()).free // (2 ** 30)
    except OSError:
        return None


def run(ctx):
    notes, blocks = [], []
    free = disk_free_gb()
    crit = c.env_int("NEVA_DELIVERY_DISK_CRIT_GB", 15, 0)
    warn = c.env_int("NEVA_DELIVERY_DISK_WARN_GB", 30, 0)
    remind = c.env_int("NEVA_DELIVERY_DISK_REMIND_GB", 50, 0)
    if free is not None:
        if free < crit:
            blocks.append(f"Blocked: disk space at {free}GB (<{crit}GB). Free space before continuing.")
        elif free < warn:
            notes.append(f"Disk space at {free}GB (<{warn}GB).")
        elif free < remind:
            notes.append(f"Reminder: disk space at {free}GB (<{remind}GB).")
    text = c.read_text(ctx.transcript_path) if ctx.transcript_path else ""
    if len(text) >= MIN_CHARS:
        tail = text[-8000:]
        pats = RATIONALIZE + (EXTENDED if c.env_flag("NEVA_DELIVERY_GATE_EXTENDED") else [])
        hits = [m.group(0)[:80] for m in (re.search(p, tail, re.I) for p in pats) if m]
        if hits:
            notes.append("Rationalization phrases in this response: " + "; ".join(f'"{h}"' for h in hits)
                         + ". Check that the work was actually finished, not argued away.")
        edits = len(re.findall(r'"name":\s*"(?:Edit|Write)"', text))
        if edits >= COMPLEX_THRESHOLD:
            mem = memory_dir(ctx.cwd)
            if not mem:
                notes.append("No project memory directory found, so learning capture cannot be verified. "
                             "Fix: create it per the delivery-gate skill, or set NEVA_MEMORY_DIR.")
            else:
                stale = stale_libs(mem)
                if len(stale) >= 3:
                    blocks.append(f"Blocked: complex task ({edits} edits) but {len(stale)} learning libraries are "
                                  f"stale: {', '.join(stale)}. Update them in {mem} before stopping.")
                elif "growth-log" in stale:
                    blocks.append("Blocked: code changes made but no growth-log update today. Write a growth-log "
                                  f"entry in {os.path.join(mem, 'growth-log')} before stopping, even if it says "
                                  "no new learnings.")
                elif stale:
                    notes.append(f"Stale learning libraries ({len(stale)}): {', '.join(stale)}.")
    if blocks and ctx.data.get("stop_hook_active"):
        notes = blocks + notes
        blocks = []
    out = {}
    if blocks:
        out["block"] = "\n".join(blocks)
    if notes:
        out["system"] = "Delivery gate: " + " ".join(notes)
    return out or None
