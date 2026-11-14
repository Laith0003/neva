#!/usr/bin/env python3
"""Two late fixes: the skip section is removed only where the engine put it, and the analyzer credits
a note only with the batch sessions it cites.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from test_instinct_learning import ANALYZE, InstinctSandbox

TRIG = "when two jobs append to the same ledger file"
ACTION = "Take an exclusive file lock before appending, and release it in a finally block."
BID = "promote-global:lock-before-write"


class SkipSectionCase(unittest.TestCase):
    def test_block_text_that_looks_like_the_skip_section_is_never_removed(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        for repo in ("repoA", "repoB"):
            sb.run("add", "--id", "lock-before-write", "--trigger", TRIG, "--action",
                   ACTION + "\n\n## Not proposed this run\n\nkeep this line", "--domain", "code-style",
                   "--confidence", "0.9", cwd=repo)
        sb.run("propose")
        before = open(sb.proposal_path(), encoding="utf-8").read()
        self.assertIn("keep this line", before)
        for repo in ("repoA", "repoB"):
            sb.run("add", "--id", "name-migrations", "--trigger", "when naming a database migration",
                   "--action", "Name each migration after the change it makes.", "--domain", "code-style",
                   "--confidence", "0.9", cwd=repo)
        sb.run("propose")
        after = open(sb.proposal_path(), encoding="utf-8").read()
        self.assertIn("keep this line", after, "part of a proposed block was deleted")


class SessionCreditCase(unittest.TestCase):
    def test_a_note_is_credited_only_with_sessions_it_cites_from_the_batch(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        vault = tmp / "vault"
        notes = vault / "06 Memory" / "instincts" / "project" / "p1"
        notes.mkdir(parents=True)
        state = tmp / "state"
        os.environ_backup = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(os.environ_backup)))
        os.environ["NEVA_INSTINCT_STATE_DIR"] = str(state)
        spec = importlib.util.spec_from_file_location("analyze_credit", ANALYZE)
        an = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(an)
        s1, s2, s3 = ("aaaaaaaa-1111-2222-3333-444444444444", "bbbbbbbb-1111-2222-3333-444444444444",
                      "cccccccc-1111-2222-3333-444444444444")
        before = an._note_hashes(notes)
        (notes / "cites-one.md").write_text(f"---\nid: cites-one\n---\n\n## Evidence\n- session {s1}\n- session {s3}\n")
        (notes / "cites-none.md").write_text("---\nid: cites-none\n---\n\n## Evidence\n- seen often\n")
        lines = [json.dumps({"session": s, "timestamp": f"2026-11-1{n}T10:00:00Z"}).encode() + b"\n"
                 for n, s in enumerate((s1, s2))]
        an.record_note_sessions(vault, notes, before, lines)
        data = json.loads((state / "note-sessions.json").read_text())
        self.assertEqual(sorted(data.get("vault:06 Memory/instincts/project/p1/cites-one.md", {})), [s1])
        self.assertNotIn("vault:06 Memory/instincts/project/p1/cites-none.md", data)


if __name__ == "__main__":
    unittest.main()
