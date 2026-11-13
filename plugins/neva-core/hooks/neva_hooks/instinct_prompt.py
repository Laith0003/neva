# Written for Neva; not adapted from ECC.
"""UserPromptSubmit: instincts matched to the first real prompt of a session.

Once per session. The first prompt that is not system text (starts with `<`) or a slash command
(starts with `/`) is scored against each instinct's trigger, id and tags by instinct_match.py.
Up to NEVA_INSTINCT_PROMPT_MAX (default 3) qualifying instincts are injected, skipping any id the
session start block already showed and any near-duplicate of one. Rarity is judged over the
whole instinct corpus (common.corpus_idf, cached in the state dir). Nothing qualifies: nothing is
injected. Later prompts: nothing.

Each injection appends one line to <state>/instinct-injections.jsonl. Any error is logged to
hooks.log and the hook returns nothing; it never blocks the prompt.

The state is keyed by session id. Resume and compact keep the id, so nothing shown at start or on
the first prompt repeats. A harness that starts a new session id on resume gets a fresh first
prompt pass for that id.

Controls: NEVA_INSTINCT_PROMPT_MAX (default 3, 0 = off), NEVA_INSTINCT_MIN_CONFIDENCE (0.7),
NEVA_INSTINCT_PROMPT_MAX_CHARS (cap on the block; default NEVA_SESSION_START_MAX_CHARS when that
is above 0, else 8000; an explicit 0 means no cap). Lines that do not fit are left out whole, never cut.
"""
from . import common as c


def _real_prompt(prompt):
    t = prompt.strip()
    return bool(t) and not t.startswith("/") and c.is_real_prompt(t)


def run(ctx):
    try:
        prompt = str(ctx.data.get("prompt") or "")
        if not _real_prompt(prompt) or not ctx.vault:
            return None
        marks_p = ctx.state_file("instinct-prompt") + ".json"
        if (c.read_json(marks_p, {}) or {}).get("done"):
            return None
        # Mark first: a crash below must not turn every later prompt into a retry.
        c.write_json(marks_p, {"done": True})
        limit = c.env_int("NEVA_INSTINCT_PROMPT_MAX", 3, 0, 50)
        if limit == 0:
            return None
        m = c.instinct_match()
        items, idf = c.recall_inputs(ctx.vault, ctx.project["id"], m)
        if not items:
            return None
        shown = set(c.shown_instincts(ctx))
        fresh = [i for i in items if i["id"] not in shown]
        picked = m.rank(prompt, fresh, limit, idf=idf, seen=[i for i in items if i["id"] in shown])
        if not picked:
            return None
        # Lines first, then the cap, then the records: only what is shown is marked and logged.
        head = c.INSTINCT_HEADER.format(what="matched to this prompt")
        start_cap = c.env_int("NEVA_SESSION_START_MAX_CHARS", 8000, 0) or 8000
        max_chars = c.env_int("NEVA_INSTINCT_PROMPT_MAX_CHARS", start_cap, 0)
        out, used = [], len(head)
        for i, match in picked:
            line = c.instinct_line(i)
            if max_chars and used + 1 + len(line) > max_chars:
                break
            out.append((i, match, line))
            used += 1 + len(line)
        if not out:
            return None
        shown_now = [(i, match) for i, match, _ in out]
        c.mark_instincts_shown(ctx, [i["id"] for i, _ in shown_now])
        c.log_injection(ctx, "prompt", shown_now)
        return {"context": head + "\n" + "\n".join(line for _, _, line in out)}
    except Exception:
        c.log_exception("[instinct_prompt] run")
        return None
