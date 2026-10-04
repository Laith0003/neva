# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""SessionEnd: one audit line per session in today's journal log, whatever the model did.

A resumed session updates its own line in place (keyed by the short session id) instead of
adding a second one. Skill bodies, command wrappers and continuation notices are never taken
as the first prompt.
"""

from . import common as c


def journal_written(t):
    marker = c.journal_marker()
    for name, inp in t["tool_uses"]:
        if name in ("Write", "Edit", "MultiEdit", "Bash", "NotebookEdit"):
            blob = str(inp)
            if marker and marker in blob:
                return True
    return False


def audit(ctx):
    if not ctx.vault:
        return None
    t = ctx.transcript
    tools = len(t["tool_uses"])
    first = c.one_line(t["prompts"][0], 140) if t["prompts"] else ""
    if not first and tools == 0:
        return None
    sid = c.short_id(ctx.session_id)
    line = (f"- {c.hhmm()} [{ctx.project['name']}] session {sid}: {first or '(no prompt)'} "
            f"({tools} tool calls{'' if journal_written(t) else ', no journal narrative'})")
    c.append_journal_log(line, replace_key=f"] session {sid}:")
    return None
