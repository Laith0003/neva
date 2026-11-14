#!/usr/bin/env python3
"""Only git work trees are projects, and only two of them make a lesson global.

Any folder used to count as a project: the home folder, scratch and temp folders, a download
folder. A lesson seen in one repo and one scratch folder then looked like a two-project lesson,
and the analyzer's own `scope_hint: global` could promote a lesson from a single project. These
tests prove a folder outside git is unscoped, that a bucket whose root is not a git work tree
never counts toward promotion, that the model's flag alone promotes nothing, and that the same
lesson in two git repos still does.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

LESSON = """---
id: {iid}
trigger: "when handling errors in services"
confidence: {conf}
domain: code-style
source: session-observation
scope: project
{hint}project_id: {pid}
project_name: "{name}"
evidence_count: 9
date: 2026-11-01
last_observed: 2026-11-02
decay_weeks_applied: 0
status: active
tags: [instinct, code-style]
---

# Explicit errors

## Action
Return a typed error naming the field and the fix.

## Evidence
- Observed 5 times in session aaaaaaaa-1111-2222-3333-444444444444 on 2026-11-01
- Observed 4 times in session bbbbbbbb-1111-2222-3333-444444444444 on 2026-11-02
"""


class GitProjectsCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.registry_path = os.path.join(self.sb.tmp, "data", "neva", "observations", "projects.json")

    def _register(self, pid, name, root):
        reg = {}
        if os.path.exists(self.registry_path):
            with open(self.registry_path) as fh:
                reg = json.load(fh)
        reg[pid] = {"id": pid, "name": name, "root": root, "remote": "",
                    "created_at": "2026-11-01T00:00:00Z", "last_seen": "2026-11-02T00:00:00Z"}
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        with open(self.registry_path, "w") as fh:
            json.dump(reg, fh)

    def _lesson(self, pid, name, root, iid="explicit-errors", conf=0.9, hint=False):
        self._register(pid, name, root)
        d = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", pid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{iid}.md"), "w") as fh:
            fh.write(LESSON.format(iid=iid, conf=conf, pid=pid, name=name,
                                   hint="scope_hint: global\n" if hint else ""))

    def _ids(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

    def _plain(self, name):
        path = os.path.join(self.sb.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    def test_a_folder_outside_git_is_unscoped_even_as_the_project_dir(self):
        plain = self._plain("scratch-folder")
        self.sb.run("add", "--id", "a-lesson", "--trigger", "when x", "--action", "Do y.",
                    cwd=plain, env={"CLAUDE_PROJECT_DIR": plain})
        unscoped = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "unscoped", "a-lesson.md")
        self.assertTrue(os.path.exists(unscoped), "a non-git project dir became a project bucket")

    def test_a_repo_and_a_non_git_bucket_do_not_make_two_projects(self):
        self._lesson("aaaaaaaaaaa1", "repoA", self.sb.repos["repoA"])
        self._lesson("bbbbbbbbbbb2", "scratch", self._plain("scratch-folder"))
        self.sb.run("propose", cwd=self.sb.home)
        self.assertNotIn("promote-global:explicit-errors", self._ids())

    def test_the_model_flag_alone_never_promotes(self):
        self._lesson("aaaaaaaaaaa1", "repoA", self.sb.repos["repoA"], hint=True)
        self.sb.run("propose", cwd=self.sb.home)
        self.assertNotIn("promote-global:explicit-errors", self._ids())

    def test_two_git_repos_still_promote(self):
        self._lesson("aaaaaaaaaaa1", "repoA", self.sb.repos["repoA"])
        self._lesson("bbbbbbbbbbb2", "repoB", self.sb.repos["repoB"])
        r = self.sb.run("propose", cwd=self.sb.home)
        self.assertIn("promote-global:explicit-errors", self._ids(), r.stdout + r.stderr)

    def test_the_unscoped_bucket_never_counts_as_a_project(self):
        self._lesson("aaaaaaaaaaa1", "repoA", self.sb.repos["repoA"])
        d = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "unscoped")
        os.makedirs(d)
        with open(os.path.join(d, "explicit-errors.md"), "w") as fh:
            fh.write(LESSON.format(iid="explicit-errors", conf=0.9, pid="unscoped", name="unscoped", hint=""))
        self.sb.run("propose", cwd=self.sb.home)
        self.assertNotIn("promote-global:explicit-errors", self._ids())


if __name__ == "__main__":
    unittest.main()
