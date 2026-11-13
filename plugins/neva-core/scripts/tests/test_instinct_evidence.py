#!/usr/bin/env python3
"""The quality gate trusts what the engine recorded, never what the model wrote about itself.

`source: user-stated` is honoured only for a note the `add` subcommand wrote (a small ledger in the
state folder records each one), so the analyzer cannot exempt its own lesson by writing that field.
Sessions and days are counted from the observation records the hooks wrote: a session the note
names but the records do not hold does not count, and days come from the records' timestamps. When
the records cannot give a count the candidate is thin, never passing. A lesson the human stated is
exempt from the vague check too, and a lesson with no readable words is parked with that reason.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone

from test_instinct_learning import InstinctSandbox

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
S1 = "aaaaaaaa-1111-2222-3333-444444444444"
S2 = "bbbbbbbb-1111-2222-3333-444444444444"

NOTE = """---
id: lock-before-write
trigger: "when two jobs append to the same ledger file"
confidence: 0.9
domain: code-style
source: {source}
scope: project
project_id: {pid}
project_name: "{name}"
evidence_count: 9
date: {first}
last_observed: {last}
status: active
---

# Lock before write

## Action
{action}

## Evidence
- Observed 5 times in session {s1} on {first}
- Observed 4 times in session {s2} on {last}
"""
ACTION = "Take an exclusive file lock before appending, and release it in a finally block."
BID = "promote-global:lock-before-write"


class EvidenceCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.registry_path = os.path.join(self.sb.tmp, "data", "neva", "observations", "projects.json")
        self.pids = (("aaaaaaaaaaa1", "repoA"), ("bbbbbbbbbbb2", "repoB"))

    def _register(self):
        reg = {}
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for pid, repo in self.pids:
            reg[pid] = {"id": pid, "name": repo, "root": self.sb.repos[repo], "remote": "",
                        "created_at": now, "last_seen": now}
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        with open(self.registry_path, "w") as fh:
            json.dump(reg, fh)

    def _notes(self, source="session-observation", action=ACTION):
        self._register()
        for pid, repo in self.pids:
            d = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", pid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "lock-before-write.md"), "w", encoding="utf-8") as fh:
                fh.write(NOTE.format(source=source, pid=pid, name=repo, first=YESTERDAY, last=TODAY,
                                     s1=S1, s2=S2, action=action))

    def _propose(self):
        return self.sb.run("propose", cwd=self.sb.home)

    def _proposed(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

    def _parked(self):
        return self.sb.run("list", "--parked").stdout

    def test_a_model_written_user_stated_field_is_not_trusted(self):
        self._notes(source="user-stated")
        self._propose()
        self.assertNotIn(BID, self._proposed())
        self.assertIn("no observation records", self._parked())

    def test_sessions_the_records_do_not_hold_do_not_count(self):
        self._notes()
        self._propose()
        self.assertNotIn(BID, self._proposed())
        self.assertIn(BID, self._parked())

    def test_days_come_from_the_records_not_the_note(self):
        self._notes()
        for pid, _ in self.pids:
            self.sb.observe(pid, [(S1, str(TODAY)), (S2, str(TODAY))])
        self._propose()
        self.assertNotIn(BID, self._proposed())
        self.assertIn("on 1 day(s)", self._parked())

    def test_sessions_on_two_days_in_the_records_pass(self):
        self._notes()
        for pid, _ in self.pids:
            self.sb.observe(pid, [(S1, str(YESTERDAY)), (S2, str(TODAY))])
        r = self._propose()
        self.assertIn(BID, self._proposed(), r.stdout + r.stderr)

    def test_a_lesson_added_by_the_human_still_passes_with_no_records(self):
        self.sb.add("repoA", "lock-before-write", 0.9)
        self.sb.add("repoB", "lock-before-write", 0.9)
        r = self.sb.run("propose")
        self.assertIn(BID, self._proposed(), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
