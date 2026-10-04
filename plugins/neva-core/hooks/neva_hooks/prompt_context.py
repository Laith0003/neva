# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""UserPromptSubmit: inject what this chat needs, not everything every time.

- A prompt about direction (goals, priorities, plans, decisions), or a session opened in the
  vault root, gets the strategy block once per session: GOALS.md plus each project's status.
- The first prompt of a session whose working directory sits under a project's `code:` path
  (frontmatter of a note in 01 Projects) gets that project's block once.
- Anything else: nothing.
System-injected text and slash commands are ignored.

Controls: NEVA_STRATEGY_KEYWORDS (regex), NEVA_GOALS_FILE (default GOALS.md),
NEVA_PROJECTS_DIR (default "01 Projects").
"""
import os
import re

from . import common as c

DEFAULT_KEYWORDS = (
    r"\b(goals?|priorit|strateg|plan for|what should i|what do i do|focus|income|revenue|next steps?|roadmap|"
    r"this week|weekly|review|north star|decide|decision|trade-?off|chess move)"
    r"|هدف|أهداف|خطة|أولوي|استراتيج|قرار"
)


def _keywords():
    try:
        return re.compile(c.env("NEVA_STRATEGY_KEYWORDS") or DEFAULT_KEYWORDS, re.I)
    except re.error:
        c.log("[prompt_context] NEVA_STRATEGY_KEYWORDS is not a valid regex; using the default")
        return re.compile(DEFAULT_KEYWORDS, re.I)


def _project_notes(vault):
    d = os.path.join(vault, c.env("NEVA_PROJECTS_DIR") or "01 Projects")
    notes = []
    try:
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if name.endswith(".md") and name.lower() != "readme.md" and os.path.isfile(p):
                notes.append((name[:-3], p))
            elif os.path.isdir(p) and not name.startswith((".", "(")):
                for cand in ("CLAUDE.md", f"{name}.md", "README.md"):
                    q = os.path.join(p, cand)
                    if os.path.isfile(q):
                        notes.append((name, q))
                        break
    except OSError:
        pass
    return notes


def _status_line(text):
    meta, body = c.frontmatter(text)
    state = c.section(body, "Current state", 3) or c.section(body, "Current Status", 3)
    first = ""
    for ln in state:
        s = ln.strip().lstrip("-* ").strip()
        if s:
            m = re.match(r"(?i)status:\s*(.+)", s)
            first = m.group(1) if m else s
            break
    updated = meta.get("updated") or meta.get("date") or ""
    m = re.search(r"Last updated:?\s*(\d{4}-\d{2}-\d{2})", body)
    if m:
        updated = m.group(1)
    return meta.get("status", ""), updated, first


def strategy_block(vault):
    out = ["STRATEGY CONTEXT (from the vault, injected because this prompt is about direction)"]
    goals = c.read_text(os.path.join(vault, c.env("NEVA_GOALS_FILE") or "GOALS.md"))
    if goals:
        _, body = c.frontmatter(goals)
        lines = [ln for ln in body.strip().splitlines() if ln.strip()][:40]
        if lines:
            out += ["", "## Goals", *lines]
    rows = []
    for name, p in _project_notes(vault):
        status, updated, first = _status_line(c.read_text(p))
        if status in ("archived", "done"):
            continue
        bits = ", ".join(x for x in (status, f"updated {updated}" if updated else "") if x)
        rows.append(f"- {name}{f' ({bits})' if bits else ''}: {c.one_line(first, 160) or '(no current state written)'}")
    if rows:
        out += ["", "## Projects, current state", *rows[:20]]
    if len(out) == 1:
        return ""
    out += ["", "If a project state above is older than 14 days, say so before advising on it."]
    return "\n".join(out)


def _code_paths(meta):
    v = meta.get("code") or meta.get("repo") or []
    vals = v if isinstance(v, list) else [v]
    return [os.path.realpath(os.path.expanduser(x)) for x in vals if isinstance(x, str) and x.strip()]


def project_block(vault, cwd):
    cwd = os.path.realpath(cwd)
    best = None
    for name, p in _project_notes(vault):
        text = c.read_text(p)
        meta, body = c.frontmatter(text)
        for root in _code_paths(meta):
            if cwd == root or cwd.startswith(root + os.sep):
                if not best or len(root) > len(best[0]):
                    best = (root, name, p, body)
    if not best:
        return ""
    _, name, p, body = best
    out = [f"PROJECT CONTEXT: {name} (from {os.path.relpath(p, vault)})"]
    for heading in ("Done means", "Current state", "Current Status", "Open threads", "Claude's Role"):
        lines = c.section(body, heading, 6)
        if lines:
            out += ["", f"## {heading}", *lines]
    out += ["", "You are executing for this project. If the session drifts from a shipped outcome, say so."]
    return "\n".join(out)


def run(ctx):
    prompt = str(ctx.data.get("prompt") or "")
    if not prompt.strip() or prompt.lstrip().startswith(("<", "/")):
        return None
    vault = ctx.vault
    if not vault:
        return None
    marks_p = ctx.state_file("prompt-context") + ".json"
    marks = c.read_json(marks_p, {}) or {}
    n = int(marks.get("n", 0))
    out = []
    want = bool(_keywords().search(prompt)) or os.path.realpath(ctx.cwd) == vault
    if want and not marks.get("strategy"):
        blk = strategy_block(vault)
        if blk:
            out.append(blk)
            marks["strategy"] = True
    if n == 0 and not marks.get("project"):
        blk = project_block(vault, ctx.cwd)
        if blk:
            out.append(blk)
            marks["project"] = True
    marks["n"] = n + 1
    c.write_json(marks_p, marks)
    return {"context": "\n\n".join(out)} if out else None
