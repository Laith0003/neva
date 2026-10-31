"""today.json, the one file the app reads. A section holds at most its cap and says how many it left out; every
candidate stays in `candidates`. A number comes from a verified figure or the field is null."""
from __future__ import annotations

import datetime
import re

from .collectors import LABELS
from .model import Card, Figure
from .rules import date_figure, due_of, due_rows, money_text, of, short

SCHEMA = 1
DENIED_ERROR = "a denied file"
NEEDS_YOU_CAP = 5
OPPORTUNITIES_CAP = 3


def public_card(c):
    return {"id": c.key, "key": c.key, "rule": c.rule, "kind": c.kind, "title": c.title, "why": c.why, "sources": c.sources,
            "confidence": confidence(c), "as_of": c.as_of}


def confidence(card):
    """A word with a rule, never a percent: two sources or more is high, one direct source is medium."""
    return "high" if len(card.sources) >= 2 else "medium"


def failure_cards(reads, errors, deny):
    cards = [Card(f"step_failed:{name}", "step_failed", "failure", "needs_you", 200, "Neva could not finish a check",
                  DENIED_ERROR if deny.hit(text) else text, [], None) for name, text in errors]
    for r in reads.values():
        if r.status == "failed":
            cards.append(Card(f"source_failed:{r.source}", "source_failed", "failure", "needs_you", 200,
                              f"Neva could not read {LABELS[r.source]}", r.error, [], None))
    return cards


def unknown_money():
    return {"state": "unknown", "owed": None, "due": None, "due_note": None, "currency": None, "as_of": None,
            "rows": [], "sources": []}


def money_block(facts, usable, gate):
    """Owed is the sum of the ledger rows. Due needs a schedule that adds up. Neither is ever zero by absence."""
    block = unknown_money()
    if "ledger" not in usable:
        return block
    projects, totals = of(facts, "project"), of(facts, "totals")[0]
    rows = due_rows(facts)
    block.update(currency=totals.value["currency"], as_of=totals.value["updated"] or None,
                 sources=[{"name": "Ledger", "path": totals.path, "line": totals.line}])
    owed = sum(p.value["remaining"] for p in projects)
    if owed != totals.value["remaining"]:
        block["state"] = "conflict"
        return block
    block.update(state="ok", owed=owed)
    due_total, notes = 0, []
    for p in projects:
        if p.value["remaining"] <= 0:
            continue
        amount, fig = due_of(p, rows)
        if amount is None:
            due_total, notes = None, notes + [fig]
        elif not gate.verified(fig):
            amount = None
            due_total, notes = None, notes + [f"{p.subject}'s due figure could not be verified"]
        elif due_total is not None:
            due_total += amount
        block["rows"].append({"project": p.subject, "owed": p.value["remaining"], "due": amount})
    block["due"] = due_total if notes == [] else None
    block["due_note"] = "; ".join(notes) or None
    return block


def unknown_hero():
    return {"state": "unknown", "title": "Move not read", "state_line": "The goals file could not be read.", "next": None,
            "why_now": None, "evidence": None, "leads_to": None, "not_sure": None, "sources": [], "expired": None,
            "stalled_days": None, "proposal": None}


def hero(facts, usable, block, gate, today):
    """One of the states in the spec. Nothing here is made up: no next step exists until something produces one."""
    base = unknown_hero()
    if "goals" not in usable:
        return base
    move = next(iter(of(facts, "move")), None)
    stall = next(iter(of(facts, "stall")), None)
    proposal = next(iter(of(facts, "proposal")), None)
    failed = next(iter(of(facts, "proposal_failed")), None)
    base["stalled_days"] = stall.value["days"] if stall else None
    title = move.memo["title"] if move else ""
    win_by = move.value.get("win_by") if move else None
    set_on = move.value.get("set_on") if move else None
    passed = bool(win_by) and win_by < today.isoformat()
    figures = []
    if passed:
        when = date_figure(win_by, move.path, move.value["win_line"])
        figures.append(when)
        days = (today - datetime.date.fromisoformat(win_by)).days
        base["expired"] = {"title": title, "date": win_by, "days": days}
        base["sources"].append({"name": "Goals", "path": move.path, "line": move.line})
    if title and not passed:
        line = f"Locked {short(set_on)}. " if set_on else ""
        if set_on:
            figures.append(date_figure(set_on, move.path, move.value["set_line"]))
        if win_by:
            figures.append(date_figure(win_by, move.path, move.value["win_line"]))
            line += f"Win by {short(win_by)}."
        base.update(state="locked", title=title, state_line=line.strip() or "Locked.",
                    sources=[{"name": "Goals", "path": move.path, "line": move.line}])
        return checked(base, figures, gate)
    if failed and (not proposal or failed.value["date"] > proposal.value["date"]):
        when = Figure(short(failed.value["date"]), "file", None, failed.path)
        line = f"The {when.display} proposal did not run."
        if passed:
            line += f" Your last move expired on {short(win_by)}."
        base.update(state="proposal_failed", title="Nothing is locked", state_line=line)
        return checked(base, figures + [when], gate)
    if proposal:
        when = Figure(short(proposal.value["date"]), "file", None, proposal.path)
        line = f"Proposed {when.display}. Not locked."
        if passed:
            line += f" Your last move expired on {short(win_by)}."
        link = {"name": proposal.memo["name"], "path": proposal.path, "line": proposal.line}
        base.update(state="proposed", title=proposal.memo["title"], state_line=line, next=proposal.memo.get("first"),
                    why_now=proposal.memo["why"] or None,
                    sources=[link] + base["sources"],
                    proposal={"title": proposal.memo["title"], "date": proposal.value["date"]})
        evidence, extra = money_evidence(proposal.memo["title"], block, facts)
        base["evidence"] = evidence
        return checked(base, figures + [when] + extra, gate)
    if passed:
        base.update(state="past_date", title=title, state_line=f"Win date passed on {short(win_by)}.")
        return checked(base, figures, gate)
    base.update(state="no_move", title="Nothing is locked", state_line="No proposal this week.", sources=[])
    return base


def money_evidence(title, block, facts):
    """Only a move that names a debtor gets the money beside it: the link is a whole word in the title, not a guess."""
    rows = [r for r in block["rows"] if re.search(rf"(?<!\w){re.escape(r['project'])}(?!\w)", title)]
    if not rows or block["state"] != "ok":
        return None, []
    projects = {p.subject: p for p in of(facts, "project")}
    figs = [Figure(money_text(r["owed"]), "line", r["owed"], projects[r["project"]].path, projects[r["project"]].line) for r in rows]
    owed = sum(r["owed"] for r in rows)
    figs.append(Figure(money_text(owed), "sum", owed, inputs=tuple(figs)))
    parts = ", ".join(f"{r['project']} {money_text(r['owed'])}" for r in rows)
    text = f"{money_text(owed)} {block['currency']} owed: {parts}."
    if all(r["due"] is not None for r in rows):
        due = sum(r["due"] for r in rows)
        schedule = due_rows(facts)
        inputs = tuple(due_of(projects[r["project"]], schedule)[1] for r in rows)
        figs.append(Figure(money_text(due), "sum", due, inputs=inputs))
        text += f" {money_text(due)} due now."
    return text, figs


def checked(base, figures, gate):
    """The hero goes through the same number gate as a card. If it fails, the state says so instead of showing it."""
    text = " ".join(str(base[k] or "") for k in ("title", "state_line", "why_now", "evidence"))
    probe = Card("hero", "hero", "move", "hero", 0, text, "", base["sources"], None, figures)
    if gate.number_ok(probe):
        return base
    base.update(state="unknown", title="Move not verified", state_line="A figure on this move has no source line.",
                why_now=None, evidence=None)
    return base


def attempt(name, errors, fallback, step):
    """One part of the file. A part that raises gives its fallback and a failure row, never a run with no output."""
    try:
        return step()
    except Exception as e:
        errors.append((name, f"{name}: {type(e).__name__}: {e}"))
        return fallback


def build(reads, facts, cards, errors, gate, deny, now, today, gap_hours):
    """Failures first, then by severity. A card that fails a gate is gone whole, and only a count stays."""
    usable = {name for name, r in reads.items() if r.status in ("ok", "proven_empty")}
    dropped = {"number": 0, "denied": 0}
    block = attempt("money", errors, unknown_money(), lambda: money_block(facts, usable, gate))
    move = attempt("move", errors, unknown_hero(), lambda: hero(facts, usable, block, gate, today))
    kept = []
    for card in failure_cards(reads, errors, deny) + cards:
        text = f"{card.title}\n{card.why}"
        if deny.hit(text):
            dropped["denied"] += 1
        elif card.kind != "failure" and not gate.number_ok(card):
            dropped["number"] += 1
        else:
            kept.append(card)
    kept.sort(key=lambda c: (-c.severity, c.key))
    needs = [c for c in kept if c.section == "needs_you"]
    opps = [c for c in kept if c.section == "opportunities"]
    failed = [r for r in reads.values() if r.status in ("failed", "absent")]
    state = "down" if len(failed) == len(reads) else "degraded" if failed or errors else "ok"
    return kept, {
        "schema": SCHEMA,
        "looked_at": now.astimezone().isoformat(timespec="seconds"),
        "day": today.isoformat(),
        "reasoned": False,
        "run": {"state": state, "gap_hours": gap_hours},
        "move": move,
        "money": block,
        "needs_you": [public_card(c) for c in needs[:NEEDS_YOU_CAP]],
        "needs_you_more": max(0, len(needs) - NEEDS_YOU_CAP),
        "then": [],
        "opportunities": [public_card(c) for c in opps[:OPPORTUNITIES_CAP]],
        "opportunities_more": max(0, len(opps) - OPPORTUNITIES_CAP),
        "candidates": [public_card(c) for c in kept],
        "sources": [{"id": r.source, "label": LABELS[r.source], "state": r.status, "records": len(r.facts), "denied": r.denied,
                     "error": r.error or None} for r in reads.values()],
        "dropped": dropped,
    }
