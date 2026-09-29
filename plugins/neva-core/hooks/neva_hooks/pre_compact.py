# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""PreCompact: save state before the context is summarized away.

Writes the session summary block (last user asks, files touched, tools used) into this
session's state file, and one line into today's journal log so the day shows where the
conversation was compacted and what it was doing.
"""
from . import common as c


def run(ctx):
    t = ctx.transcript
    if not t["ok"]:
        return None
    trigger = str(ctx.data.get("trigger") or "auto")
    c.update_session_file(ctx, c.summary_markdown(t, tag=f"pre-compact {c.hhmm()}, {trigger}"))
    if ctx.vault:
        last = c.one_line(t["prompts"][-1], 100) if t["prompts"] else "(no prompt)"
        c.append_journal_log(
            f"- {c.hhmm()} [{ctx.project['name']}] compacted session {c.short_id(ctx.session_id)} ({trigger}, "
            f"{len(t['tool_uses'])} tool calls, {len(t['files'])} files): last ask: {last}")
    return None
