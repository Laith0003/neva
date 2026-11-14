#!/usr/bin/env python3
"""The analysis child's grant and launch (issue 27).

B1: lessons the owner stated with `add` are out of the analyzer's reach. The child's Edit grant
covers the project instincts folder, where project `add` notes live, so every note recorded in
the add ledger (user-stated.json) inside that folder gets its own deny rule:
`--disallowedTools Edit(//<absolute note path>)`. Claude Code documents that deny rules win over
allow rules, so the grant to the folder no longer reaches those files.

No real model runs: NEVA_CLAUDE_BIN is a stub that records its argv and working directory.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import subprocess
import unittest

from test_instinct_learning import ANALYZE, PY, InstinctSandbox

ARGV_CLAUDE = """#!__PY__
import json, os, re, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
path = re.search(r"(\\S+\\.analyze-tmp/analysis\\.\\S+?\\.jsonl)", prompt).group(1)
last = json.loads([x for x in open(path) if x.strip()][-1])
with open(os.path.join(os.environ["FAKE_LOG_DIR"], "argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "cwd_listing": sorted(os.listdir("."))}) + "\\n")
sys.stdout.write(json.dumps({"status": "analysis_complete", "token": last["token"]}, separators=(",", ":")) + "\\n")
"""


def flag_values(argv, flag):
    """Every value passed after `flag` (a flag may repeat; each value is one argv item)."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


class AnalyzeIsolationCase(unittest.TestCase):
    PID = "p1"

    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.fake = self.sb.write_exe("fake-claude", ARGV_CLAUDE)
        self.log_dir = os.path.join(self.sb.tmp, "fake-log")
        os.makedirs(self.log_dir)
        bucket = os.path.join(self.sb.tmp, "data", "neva", "observations", self.PID)
        os.makedirs(bucket)
        with open(os.path.join(bucket, "observations.jsonl"), "w") as fh:
            for i in range(6):
                fh.write(json.dumps({"n": i}) + "\n")
        self.instincts_dir = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", self.PID)
        os.makedirs(self.instincts_dir)
        self.state = os.path.join(self.sb.tmp, "state", "neva", "instincts")

    def note(self, name):
        path = os.path.join(self.instincts_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"---\nid: {name[:-3]}\ntrigger: \"when x\"\nconfidence: 0.9\n---\n\n## Action\nDo x.\n")
        return path

    def record_stated(self, *paths):
        os.makedirs(self.state, exist_ok=True)
        rows = {"vault:" + os.path.relpath(p, self.sb.vault).replace(os.sep, "/"): {"date": "2026-01-01", "sha": "x"}
                for p in paths}
        with open(os.path.join(self.state, "user-stated.json"), "w") as fh:
            json.dump(rows, fh)

    def analyze(self):
        env = dict(self.sb.env, NEVA_CLAUDE_BIN=self.fake, FAKE_LOG_DIR=self.log_dir,
                   NEVA_INSTINCT_MIN_OBSERVATIONS="5")
        r = subprocess.run([PY, ANALYZE, "--project", self.PID], env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.log_dir, "argv.jsonl")) as fh:
            calls = [json.loads(x) for x in fh if x.strip()]
        self.assertTrue(calls, "the analysis child never ran")
        return calls[0]

    def denied(self, call):
        return [rule for v in flag_values(call["argv"], "--disallowedTools") for rule in v.split(",")]

    def test_every_stated_note_in_the_bucket_is_denied_to_the_child(self):
        mine = self.note("my-own-words.md")
        also = self.note("another-of-mine.md")
        analyzer = self.note("analyzer-wrote-this.md")
        self.record_stated(mine, also)
        denied = self.denied(self.analyze())
        for p in (mine, also):
            self.assertIn("Edit(//" + os.path.realpath(p).lstrip("/") + ")", denied)
        self.assertFalse(any(os.path.basename(analyzer) in r for r in denied),
                         "a note the analyzer wrote stays editable by it")

    def test_with_no_add_ledger_no_note_is_denied(self):
        self.note("analyzer-wrote-this.md")
        denied = self.denied(self.analyze())
        self.assertFalse(any(r.endswith(".md)") and "/project/" in r for r in denied), denied)

    def test_a_stated_note_in_another_bucket_is_not_listed(self):
        other = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "p2")
        os.makedirs(other)
        theirs = os.path.join(other, "elsewhere.md")
        with open(theirs, "w") as fh:
            fh.write("---\nid: elsewhere\n---\n")
        self.record_stated(theirs)
        self.assertFalse(any("elsewhere.md" in r for r in self.denied(self.analyze())))


if __name__ == "__main__":
    unittest.main()
