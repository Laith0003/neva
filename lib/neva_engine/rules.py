"""Pure functions over facts. Each has a test proving it fires and one proving it stays silent. A rule never reads a
file and never picks between two numbers: a conflict is shown with both sides."""
from __future__ import annotations

import datetime
import os
import sys

from .model import Card, Figure

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def short(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]}"


def money_text(n):
    return f"{n:,}"


def of(facts, kind):
    return [f for f in facts if f.kind == kind]


def source(fact, name=None):
    return {"name": name or os.path.splitext(os.path.basename(fact.path))[0], "path": fact.path, "line": fact.line}


def amount_figure(fact, field="remaining"):
    value = fact.value[field]
    return Figure(money_text(value), "line", value, fact.path, fact.line)


def date_figure(iso, path, line, printed=None):
    return Figure(short(iso), "line", printed or iso, path, line, iso=iso)


def due_rows(facts):
    """(project: rows). A project whose rows do not add up to its balance, or whose quote left its file, has no due."""
    rows = {}
    for f in of(facts, "schedule"):
        rows.setdefault(f.value["project"], []).append(f)
    return rows


def due_of(project_fact, rows):
    """(amount, figure) or (None, why). Rows must cover the whole balance: anything else is out of date."""
    name, remaining = project_fact.subject, project_fact.value["remaining"]
    mine = rows.get(name)
    if not mine:
        return None, f"{name} has no payment schedule"
    if not all(r.value["found"] for r in mine):
        return None, f"a source line for {name}'s schedule changed"
    if sum(r.value["amount"] for r in mine) != remaining:
        return None, f"{name}'s schedule does not add up to its balance"
    inputs = tuple(Figure(money_text(r.value["amount"]), "line", r.value["amount"], r.path, r.line) for r in mine if r.value["due"])
    total = sum(i.value for i in inputs)
    return total, Figure(money_text(total), "sum", total, inputs=inputs)


def last_payment(project, facts):
    mine = [f for f in of(facts, "payment") if f.value["project"] == project]
    return max(mine, key=lambda f: f.value["date"]) if mine else None


def money_open(facts, cfg, today):
    rows, cards = due_rows(facts), []
    totals = next(iter(of(facts, "totals")), None)
    currency = totals.value["currency"] if totals else ""
    min_age = cfg.get("min_age_days", 14)
    for f in of(facts, "project"):
        remaining = f.value["remaining"]
        if remaining <= 0:
            continue
        paid = last_payment(f.subject, facts)
        age = (today - datetime.date.fromisoformat(paid.value["date"])).days if paid else None
        if age is not None and age <= min_age:
            continue
        figures = [amount_figure(f)]
        due, due_fig = due_of(f, rows)
        title = f"{f.subject} owes {money_text(remaining)} {currency}"
        if due is not None:
            figures.append(due_fig)
            title += f", {money_text(due)} due now" if due < remaining else ", all due now"
        srcs = [source(f)]
        if paid:
            when = date_figure(paid.value["date"], paid.path, paid.line)
            days = Figure(str(age), "days_since", age, inputs=(when,))
            figures += [when, days]
            why = f"Last payment {age} days ago, on {when.display}."
            srcs.append(source(paid))
        else:
            why = ("No dated payment on file, so its age is unknown." if "ledger_events" in cfg.get("sources_read", ("ledger_events",))
                   else "Payments not read, so its age is unknown.")
        cards.append(Card(f"money_open:{f.subject}", "money_open", "money", "needs_you", 70 + min(remaining / 1000, 9), title, why,
                          srcs, paid.value["date"] if paid else None, figures))
    return cards


def ledger_drift(facts, cfg, today):
    totals = next(iter(of(facts, "totals")), None)
    if not totals:
        return []
    projects = of(facts, "project")
    cards = []
    for field, word in (("remaining", "rows add up to"), ("received", "received rows add up to")):
        rows = sum(p.value[field] for p in projects)
        if rows != totals.value[field]:
            inputs = tuple(amount_figure(p, field) for p in projects)
            cards.append(Card(f"ledger_drift:{field}", "ledger_drift", "decision", "needs_you", 120,
                              f"Numbers disagree: {word} {money_text(rows)} {totals.value['currency']}, totals say {money_text(totals.value[field])}",
                              "Fix the ledger; Neva does not pick.", [source(totals)], totals.value["file_day"],
                              [Figure(money_text(rows), "sum", rows, inputs=inputs), amount_figure(totals, field)]))
    updated, file_day = totals.value["updated"], totals.value["file_day"]
    if updated and updated < file_day:
        when = date_figure(updated, totals.path, totals.value["updated_line"])
        cards.append(Card("ledger_drift:updated", "ledger_drift", "decision", "needs_you", 119,
                          f"The ledger says updated {when.display}, the file changed {short(file_day)}",
                          "Check the rows, then set the updated line.", [source(totals)], file_day,
                          [when, Figure(short(file_day), "mtime", file_day, totals.path)]))
    return cards


def wording(fact, iso):
    """(text, figures) for a dated line. A table row becomes its cells as sentences, without the date the title already
    gives; prose stays a quote, cut at a word. Every piece is checked against the line it came from."""
    line = fact.quote.strip()
    if line.startswith("|"):
        cells = [c.strip(" *`") for c in line.strip("|").split("|")]
        cells = [c for c in cells if c and c.strip("-: ") and c != iso and c != fact.memo["printed"]]
        return " ".join(f"{c.rstrip('.')}." for c in cells), [Figure(c.rstrip("."), "line", c.rstrip("."), fact.path, fact.line) for c in cells]
    text = line.lstrip("-# ").strip(" *`")
    text = text[:200].rsplit(" ", 1)[0] if len(text) > 200 else text
    return text, [Figure(text, "line", text, fact.path, fact.line)]


def deadline_near(facts, cfg, today):
    window = cfg.get("window_days", 14)
    earliest, best = {}, {}
    for f in of(facts, "deadline"):  # a line naming two dates is one deadline, the nearer one
        left = (datetime.date.fromisoformat(f.value["date"]) - today).days
        if 0 <= left <= window:
            key = (f.value["note"], f.line)
            if key not in earliest or f.value["date"] < earliest[key].value["date"]:
                earliest[key] = f
    for f in earliest.values():
        key = (f.value["note"], f.value["date"])
        if key not in best or f.line < best[key].line:
            best[key] = f
    cards = []
    for (note, iso), f in best.items():
        left = (datetime.date.fromisoformat(iso) - today).days
        when = Figure(short(iso), "line", f.memo["printed"], f.path, f.line, iso=iso)
        why, proof = wording(f, iso)
        cards.append(Card(f"deadline_near:{note}:{iso}", "deadline_near", "deadline", "needs_you", 100 - left,
                          f"{f.memo['title']} due {when.display}", why, [source(f, note)], iso, [when] + proof))
    return cards


def move_stalled(facts, cfg, today):
    move = next(iter(of(facts, "move")), None)
    if not move or not move.memo["title"]:
        return []
    stall = next(iter(of(facts, "stall")), None)
    win_by = move.value.get("win_by")
    passed = bool(win_by) and win_by < today.isoformat()
    over = bool(stall) and stall.value["days"] > cfg.get("stall_days", 3)
    if not passed and not over:
        return []
    title = f"{move.memo['title']}: past its date" if passed else f"{move.memo['title']}: stalled"
    return [Card("move_stalled:current", "move_stalled", "move", "hero", 110, title, "", [source(move)], win_by)]


def build_unreviewed(facts, cfg, today):
    jobs = [f for f in of(facts, "job") if f.value["waits_review"]]
    if not jobs:
        return []
    count = Figure(str(len(jobs)), "count", len(jobs), inputs=tuple(Figure("", "file", None, j.path) for j in jobs))
    newest = max((j.value["finished"] or "" for j in jobs), default="")
    title = f"{len(jobs)} finished build{'s wait' if len(jobs) != 1 else ' waits'} for your review"
    figures, why = [count], "Each one is done and has not been read."
    if newest:
        job = next(j for j in jobs if j.value["finished"] == newest)
        why = f"The newest finished {short(newest)}."
        figures.append(Figure(short(newest), "job_day", newest, job.path))
    return [Card("build_unreviewed", "build_unreviewed", "build", "needs_you", 60, title, why,
                 [{"name": "Build queue", "path": jobs[0].path.rsplit("/", 1)[0], "line": None}], newest or None, figures)]


def lead_cold(facts, cfg, today):
    cards = []
    limit = cfg.get("silent_days", 21)
    for f in of(facts, "lead"):
        if f.value["closed"]:
            continue
        last = datetime.date.fromisoformat(f.value["last"])
        days = (today - last).days
        if days <= limit:
            continue
        if f.value["by_file"]:
            when = Figure(short(f.value["last"]), "mtime", f.value["last"], f.path, iso=f.value["last"])
        else:
            when = date_figure(f.value["last"], f.path, f.line)
        cards.append(Card(f"lead_cold:{f.subject}", "lead_cold", "lead", "opportunities", 40 + min(days / 100, 9),
                          f"Follow up {f.subject}: silent {days} days", f"Last touched {when.display}. Status {f.value['status']}.",
                          [source(f)], f.value["last"], [when, Figure(str(days), "days_since", days, inputs=(when,))]))
    return cards


RULES = (
    ("money_open", ("ledger",)),
    ("ledger_drift", ("ledger",)),
    ("deadline_near", ("dates",)),
    ("move_stalled", ("goals",)),
    ("build_unreviewed", ("queue",)),
    ("lead_cold", ("leads",)),
)


def evaluate(facts, usable, cfg, today):
    """(cards, failed). Every rule whose sources were read. A rule on a source that failed is held, never run on half the
    picture, and a rule that raises stops only itself. Failed is (rule, text)."""
    cards, failed = [], []
    module = sys.modules[__name__]
    for name, needs in RULES:
        if all(s in usable for s in needs):
            try:
                cards.extend(getattr(module, name)(facts, dict(cfg.get(name, {}), sources_read=usable), today))
            except Exception as e:
                failed.append((name, f"{name}: {type(e).__name__}: {e}"))
    return cards, failed
