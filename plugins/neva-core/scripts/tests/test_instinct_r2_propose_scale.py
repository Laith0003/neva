#!/usr/bin/env python3
"""Propose reads each instincts folder once per run, not once per block.

_content_from_fields re-read the whole folder for every block, so 1,200 retire candidates took 45 s.
The bound below is generous for a slow CI machine; the quadratic version took about 20 s here.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import time
import unittest

from test_instinct_learning import InstinctSandbox

COUNT = 800
BOUND_SECONDS = 15

NOTE = """---
id: faded-{n}
trigger: "when handling faded case {n}"
confidence: 0.1
domain: workflow
source: session-observation
scope: global
status: active
---

# Faded {n}

## Action
Handle faded case {n} the old way.
"""


class ProposeScaleCase(unittest.TestCase):
    def test_many_retire_candidates_propose_in_bounded_time(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        sb.add("repoA", "seed", 0.9)
        folder = os.path.join(sb.vault, "06 Memory", "instincts", "global")
        os.makedirs(folder, exist_ok=True)
        for n in range(COUNT):
            with open(os.path.join(folder, f"faded-{n}.md"), "w", encoding="utf-8") as fh:
                fh.write(NOTE.format(n=n))
        start = time.monotonic()
        r = sb.run("propose")
        took = time.monotonic() - start
        self.assertIn("retire", r.stdout)
        self.assertLess(took, BOUND_SECONDS, f"propose took {took:.1f}s for {COUNT} retire candidates")


if __name__ == "__main__":
    unittest.main()
