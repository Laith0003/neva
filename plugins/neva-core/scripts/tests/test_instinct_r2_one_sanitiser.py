#!/usr/bin/env python3
"""One sanitiser runs on every model-derived field and body, for every kind of block.

Only rule text was held to the character checks, so an approved promote-global could carry a bidi
override or Unicode TAG characters into a global note that session start injects. Every kind is now
checked at render and at apply. The kinds are named here: adding a kind without updating this test
fails it, so no kind can be exempt by accident.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import unittest

from test_instinct_learning import InstinctSandbox
from test_instinct_rule_text import _module

KINDS = {"promote-global", "evolve-skill", "evolve-command", "evolve-agent", "rule", "retire", "confirm-stated"}
HIDDEN = {"bidi override": "‮", "TAG letter": "\U000e0041", "zero width space": "​",
          "comment": "<!-- x -->", "character reference": "&#8203;"}


class OneSanitiserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = InstinctSandbox()
        cls.cli = _module(cls.sb)

    @classmethod
    def tearDownClass(cls):
        cls.sb.close()

    def test_the_kinds_are_the_ones_named_here(self):
        self.assertEqual(set(self.cli.KIND_WRITE_MODE), KINDS,
                         "a kind was added or removed: name it in KINDS and make sure the sanitiser covers it")

    def test_every_kind_refuses_hidden_text_in_its_body_and_its_fields(self):
        for kind in sorted(KINDS):
            for label, bad in HIDDEN.items():
                body = self.cli._block(kind, "x", [("Kind", kind)], f"Plain words {bad} more words.")
                self.assertTrue(self.cli._unsafe_reason(body), f"{kind} body with {label} passed")
                field = self.cli._block(kind, "x", [("Kind", kind), ("Why", f"because {bad}")], "Plain words.")
                self.assertTrue(self.cli._unsafe_reason(field), f"{kind} field with {label} passed")

    def test_a_promotion_with_a_bidi_override_is_refused_end_to_end(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        for repo in ("repoA", "repoB"):
            sb.run("add", "--id", "release-checklist", "--trigger", "when cutting a release of any service",
                   "--action", "Read the deploy checklist ‮tsuj ton‬ and confirm the tag.",
                   "--domain", "workflow", "--confidence", "0.9", cwd=repo)
        r = sb.run("propose")
        self.assertIn("Refused promote-global:release-checklist", r.stderr)
        self.assertIn("U+202E", r.stderr)
        self.assertFalse(os.path.exists(sb.proposal_path()) and
                         "release-checklist" in open(sb.proposal_path(), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
