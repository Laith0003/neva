#!/usr/bin/env python3
"""A deterministic quality gate runs before anything is proposed.

Most of what the engine proposed was already written down, named a tool instead of a behaviour,
rested on one session, or was about a project nobody had touched in weeks. These tests prove each
of those is parked with its reason instead of proposed, that the parked list keeps it, that a
candidate that later earns its evidence is proposed, and that a good candidate passes untouched.
The rules, memory index and skills the gate reads are fixtures in a temporary folder.

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

NOTE = """---
id: {iid}
trigger: "{trigger}"
confidence: 0.9
domain: code-style
source: session-observation
scope: project
project_id: {pid}
project_name: "{name}"
evidence_count: 9
date: {first}
last_observed: {last}
decay_weeks_applied: 0
status: active
tags: [instinct, code-style]
---

# Lesson

## Action
{action}

## Evidence
{evidence}
"""

TWO_SESSIONS = (f"- Observed 5 times in session aaaaaaaa-1111-2222-3333-444444444444 on {YESTERDAY}\n"
                f"- Observed 4 times in session bbbbbbbb-1111-2222-3333-444444444444 on {TODAY}\n")
ONE_SESSION = f"- Observed 9 times in session aaaaaaaa-1111-2222-3333-444444444444\n"


class QualityGateCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.config = os.path.join(self.sb.tmp, "claude-config")
        self.memory = os.path.join(self.sb.tmp, "memory")
        self._file(os.path.join(self.config, "rules", "house.md"),
                   "# House rules\n\n- Errors name the field and the fix: return a typed error that names "
                   "the field and how to fix it.\n")
        self._file(os.path.join(self.config, "skills", "release", "SKILL.md"),
                   "---\nname: release\ndescription: Tag the release, write the changelog entry and publish "
                   "the package after the checks pass.\n---\n")
        self._file(os.path.join(self.memory, "MEMORY.md"),
                   "# Index\n- [Migrations](m.md): run database migrations inside a transaction and back up first\n")
        self.env = {"CLAUDE_CONFIG_DIR": self.config, "NEVA_MEMORY_DIR": self.memory}
        self.registry_path = os.path.join(self.sb.tmp, "data", "neva", "observations", "projects.json")

    def _file(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _register(self, pid, name, root, last_seen):
        reg = {}
        if os.path.exists(self.registry_path):
            with open(self.registry_path) as fh:
                reg = json.load(fh)
        reg[pid] = {"id": pid, "name": name, "root": root, "remote": "",
                    "created_at": "2026-01-01T00:00:00Z", "last_seen": last_seen}
        self._file(self.registry_path, json.dumps(reg))

    def _lesson(self, iid, trigger, action, evidence=TWO_SESSIONS, idle_days=0):
        stamp = (datetime.now(timezone.utc) - timedelta(days=idle_days)).isoformat().replace("+00:00", "Z")
        for pid, repo in (("aaaaaaaaaaa1", "repoA"), ("bbbbbbbbbbb2", "repoB")):
            self._register(pid, repo, self.sb.repos[repo], stamp)
            # The gate counts sessions and days from the records the hooks wrote, so the sessions the
            # evidence names are recorded on the days it names.
            self.sb.observe(pid, [("aaaaaaaa-1111-2222-3333-444444444444", str(YESTERDAY)),
                                  ("bbbbbbbb-1111-2222-3333-444444444444", str(TODAY))])
            self._file(os.path.join(self.sb.vault, "06 Memory", "instincts", "project", pid, f"{iid}.md"),
                       NOTE.format(iid=iid, trigger=trigger, action=action, pid=pid, name=repo,
                                   first=YESTERDAY, last=TODAY, evidence=evidence))

    def _propose(self):
        return self.sb.run("propose", cwd=self.sb.home, env=self.env)

    def _ids(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

    def _parked(self):
        return self.sb.run("list", "--parked", env=self.env).stdout

    def _assert_parked(self, bid, reason_fragment):
        self.assertNotIn(bid, self._ids())
        listing = self._parked()
        self.assertIn(bid, listing)
        self.assertIn(reason_fragment, listing)

    def test_a_good_candidate_is_proposed(self):
        self._lesson("lock-before-write", "when two jobs append to the same ledger file",
                     "Take an exclusive file lock before appending, and release it in a finally block.")
        self._propose()
        self.assertIn("promote-global:lock-before-write", self._ids())

    def test_a_restated_rule_is_parked(self):
        self._lesson("typed-errors", "when an error reaches the user",
                     "Return a typed error that names the field and how to fix it.")
        self._propose()
        self._assert_parked("promote-global:typed-errors", "restates rule house.md")

    def test_a_restated_skill_description_and_memory_line_are_parked(self):
        self._lesson("release-steps", "when shipping a release",
                     "Tag the release, write the changelog entry, then publish the package once checks pass.")
        self._lesson("safe-migrations", "when changing the database schema",
                     "Back up first, then run the database migrations inside a transaction.")
        self._propose()
        self._assert_parked("promote-global:release-steps", "restates skill or command")
        self._assert_parked("promote-global:safe-migrations", "restates memory index")

    def test_a_tool_name_is_not_a_behaviour(self):
        self._lesson("grep-first", "when searching the code base", "Use Grep.")
        self._propose()
        self._assert_parked("promote-global:grep-first", "names a tool")

    def test_one_session_is_not_enough_evidence(self):
        self._lesson("lock-before-write", "when two jobs append to the same ledger file",
                     "Take an exclusive file lock before appending, and release it in a finally block.",
                     evidence=ONE_SESSION)
        self._propose()
        self._assert_parked("promote-global:lock-before-write", "1 session(s)")

    def test_a_dormant_project_is_parked(self):
        self._lesson("lock-before-write", "when two jobs append to the same ledger file",
                     "Take an exclusive file lock before appending, and release it in a finally block.",
                     idle_days=45)
        self._propose()
        self._assert_parked("promote-global:lock-before-write", "last 30 days")

    def test_parked_is_kept_and_a_candidate_that_earns_its_evidence_is_proposed(self):
        args = ("lock-before-write", "when two jobs append to the same ledger file",
                "Take an exclusive file lock before appending, and release it in a finally block.")
        self._lesson(*args, evidence=ONE_SESSION)
        self._propose()
        self._propose()
        self.assertIn("promote-global:lock-before-write", self._parked())
        self._lesson(*args, evidence=TWO_SESSIONS)
        self._propose()
        self.assertIn("promote-global:lock-before-write", self._ids())
        self.assertIn("promote-global:lock-before-write", self._parked(), "a parked record was deleted")


if __name__ == "__main__":
    unittest.main()
