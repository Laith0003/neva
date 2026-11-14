#!/usr/bin/env python3
"""`add` records "these are his own words" under the ledger lock.

The record lives in user-stated.json, which propose, apply and confirm rewrite under the ledger lock.
An `add` that read, changed and rewrote it outside the lock lost rows when runs overlapped, and a
lesson with no row is no longer treated as his: it is parked as thin.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest

from test_instinct_learning import CLI, PY, InstinctSandbox

RUNS = 40

# Forty processes forked after the import all call main(["add", ...]) from one barrier, so their
# read-modify-write windows overlap for certain; separate interpreters start too far apart.
RACE = textwrap.dedent("""
    import contextlib, importlib.util, io, multiprocessing as mp, os, sys
    cli, runs = sys.argv[1], int(sys.argv[2])
    spec = importlib.util.spec_from_file_location("icli", cli)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    barrier = mp.get_context("fork").Barrier(runs)
    def one(n):
        barrier.wait()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = module.main(["add", "--id", f"lesson-{n}", "--trigger", f"when case {n} of the batch comes up",
                              "--action", f"Apply the lesson {n} practice in every change.",
                              "--domain", "code-style", "--confidence", "0.9"])
        os._exit(rc)
    procs = [mp.get_context("fork").Process(target=one, args=(n,)) for n in range(runs)]
    [p.start() for p in procs]
    [p.join() for p in procs]
    sys.exit(max(p.exitcode for p in procs))
""")


@unittest.skipUnless(hasattr(os, "fork"), "needs fork")
class AddLockCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def test_overlapping_adds_keep_every_row(self):
        self.sb.add("repoA", "first-lesson", 0.9)  # the state folder exists before the race
        r = subprocess.run([PY, "-c", RACE, CLI, str(RUNS)], cwd=self.sb.repos["repoA"], env=self.sb.env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "user-stated.json")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        missing = [n for n in range(RUNS) if not any(ref.endswith(f"/lesson-{n}.md") for ref in rows)]
        self.assertEqual(missing, [], f"{len(missing)} of {RUNS} rows lost")


if __name__ == "__main__":
    unittest.main()
