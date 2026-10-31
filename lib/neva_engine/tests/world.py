"""A fictional company on disk. Nothing here reads the owner's real vault: every path sits in a temp dir and the
environment variables that point at a real vault are refused."""
import datetime
import hashlib
import json
import os
import shutil
import tempfile
import unittest

NOW = datetime.datetime(2026, 3, 20, 15, 10, 0)

GOALS = """# Goals

## Current Move

- Move: [[Win the harbour account]]. The 12 people who asked twice.
- Win condition: two signed orders by 2026-03-01.
- Set on: 2026-02-01
- Status: active. Next: call them.

## Later
"""

LEDGER = """---
tags: [money]
updated: 2026-03-20
---

# Ledger

| Project | Contract |
|---|---|
| Northwind | 5,000 |

```yaml
currency: USD
projects:
  Northwind: { contract: 5000, received: 2000, remaining: 3000, dev_owed: 100 }
  Tailspin:  { contract: 900,  received: 500,  remaining: 400,  dev_owed: 0 }
  Paid_Co:   { contract: 100,  received: 100,  remaining: 0,    dev_owed: 0 }
totals:      { contract: 6000, received: 2600, remaining: 3400, dev_owed: 100 }
```
"""

EVENTS = """# Events

```yaml
payments:
  - { project: Northwind, amount: 1000, date: 2026-01-10, note: "first" }
  - { project: Paid_Co, amount: 100, date: 2026-01-11, note: "all of it" }
deliverables:
```

- 2026-02-02: Northwind unrelated note about the contract.
- 2026-02-20: Northwind paid 1,000 USD against payment 2. 500 is still owed on payment 2; payment 3 (1,000) and the 3 x 500 tail are unpaid.
"""

SCHEDULE = {
    "currency": "USD",
    "items": [
        {"project": "Tailspin", "label": "balance", "amount": 400, "due": True, "path": "money/Ledger.md", "quote": "remaining: 400"},
        {"project": "Northwind", "label": "rest of payment 2", "amount": 500, "due": True, "path": "money/Events.md", "quote": "500 is still owed on payment 2"},
        {"project": "Northwind", "label": "payment 3", "amount": 1000, "due": True, "path": "money/Events.md", "quote": "payment 3 (1,000)"},
        {"project": "Northwind", "label": "monthly tail", "amount": 1500, "due": False, "path": "money/Events.md", "quote": "3 x 500 tail"},
    ],
}

PROPOSAL = """---
status: done
---
# Move proposal 2026-03-13

| Rank | Move | Cash | Total |
|---|---|---|---|
| 1 | Collect Northwind and Tailspin | 5 | 13 |
| 2 | Something else | 3 | 10 |

**Recommendation: collect.** It needs no build.
"""

FAILED_PROPOSAL = "# Move proposal 2026-03-06\n\nModel call unavailable this week.\n"

LEAD_COLD = "---\ndate: 2026-01-01\nupdated: 2026-01-05\nstatus: new\n---\n\n# Blue Yonder\n\nA lead.\n"
LEAD_WARM = "---\ndate: 2026-03-19\nstatus: proposal\n---\n\n# Fresh Co\n\nA lead.\n"
LEAD_WON = "---\ndate: 2026-01-01\nstatus: won\n---\n\n# Done Co\n"

PROJECT = """# Skylark

## Plan

Launch: submit by 2026-03-22, the board closes 2026-04-20.
Old line: delivered by 2026-03-01.
Far line: deliver by 2026-09-01.
A note that names 2026-03-25 and nothing else.
- [x] deliver the logo by 2026-03-23
"""

CLIENT = """---
status: active
---

# Contoso

| Date | Item | Status |
|---|---|---|
| 2026-03-28 | Balance, at completion | Due on delivery |
"""

ARCHIVED = "---\nstatus: archived\n---\n\n# Old\n\ndeliver by 2026-03-24\n"


def job(status="done", reason="done, needs owner review", **extra):
    return json.dumps(dict(status=status, reason=reason, finished=1773900000, **extra))


class World(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="neva-engine-test-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "notes")
        self.runtime = os.path.join(self.base, "runtime")
        self.queue = os.path.join(self.base, "queue", "state")
        self.config_path = os.path.join(self.base, "engine.json")
        self.deny_path = os.path.join(self.base, "deny.json")
        self.write("GOALS.md", GOALS)
        self.write("money/Ledger.md", LEDGER)
        self.write("money/Events.md", EVENTS)
        self.write("reviews/Move proposal 2026-03-13.md", PROPOSAL)
        self.write("reviews/Move proposal 2026-03-06.md", FAILED_PROPOSAL)
        self.write("leads/Blue Yonder.md", LEAD_COLD)
        self.write("leads/Fresh Co.md", LEAD_WARM)
        self.write("leads/Done Co.md", LEAD_WON)
        self.write("projects/Skylark.md", PROJECT)
        self.write("clients/Contoso.md", CLIENT)
        self.write("clients/Old.md", ARCHIVED)
        for name in ("Blue Yonder", "Done Co"):
            self.age(f"leads/{name}.md", "2026-01-05")
        self.age("leads/Fresh Co.md", "2026-03-19")
        self.age("money/Ledger.md", "2026-03-20")
        self.write_job("build-one")
        self.write_job("build-two")
        self.write_job("build-merged", note="merged in PR 3")
        self.write_job("build-running", status="running", reason="")
        self.write_json(self.queue + "/_budget.json", {"not": "a job"})
        self.write_json(os.path.join(self.base, "stall.json"), {"move": "x", "stalled_days": 5})
        self.write_json(os.path.join(self.base, "schedule.json"), SCHEDULE)
        self.write_json(self.deny_path, {"terms": ["Zephyrcorp", "ZPH", "Omega Vault"], "paths": ["clients/Zephyr*", "*/secret/*"], "tags": ["confidential"]})
        self.config = {
            "root": self.root,
            "runtime": self.runtime,
            "day_rollover_hour": 5,
            "deny_file": self.deny_path,
            "sources": {
                "goals": {"path": "GOALS.md", "stall_state": os.path.join(self.base, "stall.json"),
                          "proposals": "reviews", "proposal_glob": "Move proposal *.md",
                          "failed_markers": ["call unavailable"]},
                "ledger": {"path": "money/Ledger.md"},
                "ledger_events": {"path": "money/Events.md", "schedule": os.path.join(self.base, "schedule.json")},
                "queue": {"state_dir": self.queue, "review_pattern": "needs owner review"},
                "leads": {"dir": "leads", "closed": ["won", "lost"]},
                "dates": {"globs": ["projects/*.md", "clients/*.md", "leads/*.md"],
                          "words": ["by", "due", "deadline", "closes", "submit", "deliver", "delivery"],
                          "done_words": ["received", "signed"], "closed_status": ["archived", "done"],
                          "titles": {"Skylark": "Skylark launch"}},
            },
            "rules": {"money_open": {"min_age_days": 14}, "deadline_near": {"window_days": 14},
                      "lead_cold": {"silent_days": 21}, "move_stalled": {"stall_days": 3}},
        }
        self.save()

    def save(self):
        self.write_json(self.config_path, self.config)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def write_json(self, path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)

    def write_job(self, name, **fields):
        path = os.path.join(self.queue, name + ".json")
        os.makedirs(self.queue, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(job(**fields))

    def age(self, rel, day):
        t = datetime.datetime.fromisoformat(day + "T12:00:00").timestamp()
        os.utime(os.path.join(self.root, rel), (t, t))

    def edit(self, rel, old, new):
        path = os.path.join(self.root, rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(old, text)
        self.write(rel, text.replace(old, new))

    def remove(self, rel):
        os.unlink(os.path.join(self.root, rel))

    def tree_hash(self):
        h = hashlib.sha256()
        for root, dirs, files in sorted(os.walk(self.root)):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(root, f)
                h.update(p.encode())
                with open(p, "rb") as fh:
                    h.update(fh.read())
                h.update(str(os.stat(p).st_mtime_ns).encode())
        return h.hexdigest()

    def tick(self, now=NOW, **kw):
        from neva_engine import tick
        return tick.run(self.config_path, now=now, **kw)

    def today(self, now=NOW):
        self.tick(now=now)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            return json.load(f)

    def cards(self, today=None):
        t = today or self.today()
        return t["needs_you"] + t["opportunities"]

    def rules(self, today=None):
        return [c["rule"] for c in (today or self.today())["candidates"]]
