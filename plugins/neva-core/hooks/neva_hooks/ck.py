# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""SessionStart hook for the ck (context keeper) skill.

Data: NEVA_CK_HOME, else $XDG_DATA_HOME/neva/ck, else ~/.local/share/neva/ck. When that folder
does not exist ck is not in use and this module does nothing (it never creates it).

1. Reads the previous current-session.json, then overwrites it with
   {sessionId, projectPath, projectName, startedAt} so /ck:save updates this session's entry.
2. Registered project (projects.json has the working directory): a compact block
     ck: <name> | <N days ago> | <N> sessions
     Goal: ...  /  Left off: <first line>  /  Next: <first two steps>
   plus, when they apply:
     WARNING Last session wasn't saved. Run /ck:save to capture it
     Git: N commits since last session
     WARNING Goal mismatch: CLAUDE.md `## Current Goal` differs from the saved goal. Run /ck:save
     with updated goal to sync
3. Unregistered directory with other ck projects: the 3 most recent (name, staleness, last
   seen, last summary) and `Run /ck:list, /ck:resume <name>, or /ck:init to register this folder`.
Output is additionalContext only (about 100 tokens); the skill body is not injected.
"""
import datetime
import json
import os
import re

from . import common as c


def ck_home():
    v = c.env("NEVA_CK_HOME").strip()
    if v and os.path.isabs(v):
        return v
    x = c.env("XDG_DATA_HOME").strip()
    if x and os.path.isabs(x):
        return os.path.join(x, "neva", "ck")
    return os.path.join(c.home(), ".local", "share", "neva", "ck")


def _days(date_str):
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None
    return (datetime.date.today() - d).days


def days_label(date_str):
    n = _days(date_str)
    if n is None:
        return "unknown"
    return "today" if n <= 0 else "1 day ago" if n == 1 else f"{n} days ago"


def staleness(date_str):
    n = _days(date_str)
    if n is None:
        return "stale"
    return "active" if n < 1 else "warm" if n <= 5 else "stale"


def _context(home, entry):
    return c.read_json(os.path.join(home, "contexts", str(entry.get("contextDir", "")), "context.json"), None)


def claude_md_goal(project_path):
    text = c.read_text(os.path.join(project_path, "CLAUDE.md"))
    m = re.search(r"^##\s+Current Goal\s*\n+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def registered_block(ctx, home, path, entry, prev):
    data = _context(home, entry) or {}
    sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
    latest = sessions[-1] if sessions else {}
    name = data.get("displayName") or data.get("name") or entry.get("name") or os.path.basename(path)
    lines = [f"ck: {name} | {days_label(latest.get('date'))} | {len(sessions)} sessions"]
    if data.get("goal"):
        lines.append(f"Goal: {c.one_line(data['goal'], 160)}")
    left = str(latest.get("leftOff") or "").strip().splitlines()
    if left:
        lines.append(f"Left off: {c.one_line(left[0], 160)}")
    steps = [str(x) for x in (latest.get("nextSteps") or [])][:2]
    if steps:
        lines.append("Next: " + " | ".join(c.one_line(x, 100) for x in steps))
    prev_id = str((prev or {}).get("sessionId") or "")
    same_project = (prev or {}).get("projectPath") == path
    if prev_id and same_project and prev_id != ctx.session_id and prev_id not in {s.get("id") for s in sessions}:
        lines.append("WARNING Last session wasn't saved. Run /ck:save to capture it")
    if latest.get("date"):
        log = c.git(["log", "--oneline", f"--since={latest['date']}"], path, timeout=3)
        n = len([x for x in (log or "").splitlines() if x.strip()])
        if n:
            lines.append(f"Git: {n} commit{'s' if n != 1 else ''} since last session")
    goal_md = claude_md_goal(path)
    if goal_md and data.get("goal") and goal_md.lower() != str(data["goal"]).strip().lower():
        lines.append("WARNING Goal mismatch: CLAUDE.md `## Current Goal` differs from the saved goal. "
                     "Run /ck:save with updated goal to sync")
    return lines


def recent_block(home, projects):
    rows = []
    for path, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        data = _context(home, entry) or {}
        sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
        latest = sessions[-1] if sessions else {}
        rows.append((str(latest.get("date") or entry.get("lastUpdated") or ""), entry.get("name") or path,
                     latest.get("summary") or "-"))
    if not rows:
        return []
    rows.sort(reverse=True)
    out = ["ck: this folder is not registered. Recent projects:", "| Project | State | Last seen | Last summary |",
           "| --- | --- | --- | --- |"]
    for date, name, summary in rows[:3]:
        out.append(f"| {name} | {staleness(date)} | {days_label(date)} | {c.one_line(summary, 60)} |")
    out.append("Run /ck:list, /ck:resume <name>, or /ck:init to register this folder")
    return out


def run(ctx):
    home = ck_home()
    if not os.path.isdir(home):
        return None
    cur_p = os.path.join(home, "current-session.json")
    prev = c.read_json(cur_p, None)
    projects = c.read_json(os.path.join(home, "projects.json"), {}) or {}
    if not isinstance(projects, dict):
        return {"context": f"ck: {os.path.join(home, 'projects.json')} is malformed. Fix: offer the user to "
                           "reset it to {} (the ck skill's rule)."}
    path = ctx.cwd
    if path not in projects and os.path.realpath(path) in projects:
        path = os.path.realpath(path)
    entry = projects.get(path)
    try:
        c.write_text(cur_p, json.dumps({
            "sessionId": ctx.session_id or "", "projectPath": path,
            "projectName": (entry or {}).get("name") or os.path.basename(path),
            "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }, indent=2) + "\n")
    except OSError:
        c.log_exception("ck: current-session.json")
    lines = registered_block(ctx, home, path, entry, prev) if isinstance(entry, dict) else recent_block(home, projects)
    if not lines:
        return None
    tail = " Mention any WARNING line in one sentence in your first reply." if any(
        x.startswith("WARNING") for x in lines) else ""
    return {"context": "\n".join(lines) + ("\n" + tail.strip() if tail else "")}
