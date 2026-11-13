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

Controls: NEVA_INSTINCT_PROMPT_MAX (default 3, 0 = off), NEVA_INSTINCT_MIN_CONFIDENCE (0.7).
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
        items = c.recall_candidates(ctx.vault, ctx.project["id"])
        if not items:
            return None
        shown = set(c.shown_instincts(ctx))
        idf = c.corpus_idf(ctx.vault, m)
        fresh = [i for i in items if i["id"] not in shown]
        picked = m.rank(prompt, fresh, limit, idf=idf, seen=[i for i in items if i["id"] in shown])
        if not picked:
            return None
        c.mark_instincts_shown(ctx, [i["id"] for i, _ in picked])
        c.log_injection(ctx, "prompt", picked)
        lines = [c.instinct_line(i) for i, _ in picked]
        return {"context": "Instincts matched to this prompt (learned from past sessions; apply when relevant):\n"
                           + "\n".join(lines)}
    except Exception:
        c.log_exception("[instinct_prompt] run")
        return None
