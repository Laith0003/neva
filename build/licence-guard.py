#!/usr/bin/env python3
"""licence-guard: refuse a commit that makes the repo lie about its own licence.

Why this runs at COMMIT time and not only in the harness. On 2026-08-14 this repo was found to be
publicly Apache-2.0 while everyone believed it was FSL 1.1. The relicense commit was real and
correct; its effect was undone weeks later as collateral inside a commit about something else
entirely ("Claude Code as the default path, interview depth, and a graph with meaning"). Nobody
was careless. The change simply passed through the one place nothing was watching.

The harness catches it, but the harness runs when someone remembers. This runs on every commit,
which is where the damage happens.

It asserts CONSISTENCY, never a particular licence: which licence to ship is a commercial choice
and hardcoding one here would only move the drift somewhere else. It also prints the licence it
detected, so the answer is never assumed.
"""
import os
import re
import subprocess
import sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True).stdout.strip()

FUTURE = re.compile(r"future licen[cs]e|becomes Apache|second anniversary|two years|ALv2", re.I)


def read(name):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return None
    try:
        return open(p, encoding="utf8", errors="replace").read()
    except Exception:
        return None


def detect(text):
    if not text:
        return None
    if re.search(r"Functional Source License", text, re.I):
        return "FSL"
    if re.search(r"Apache License", text, re.I):
        return "Apache-2.0"
    if re.search(r"\bMIT License\b", text, re.I):
        return "MIT"
    return "unknown"


def claimed(text):
    """Which licence a prose file NAMES as the current terms. Mentions of a future licence are
    ignored on purpose: FSL-1.1-ALv2 says the code becomes Apache-2.0 after two years, so a
    correct FSL document mentions Apache. A guard that fires on the correct state gets ignored."""
    if not text:
        return None
    names = set()
    for line in text.splitlines():
        if FUTURE.search(line):
            continue
        if re.search(r"Functional Source License|FSL-1|FSL 1", line, re.I):
            names.add("FSL")
        if re.search(r"Apache", line, re.I):
            names.add("Apache-2.0")
    if not names:
        return None
    return "+".join(sorted(names))


def main():
    files = [n for n in ("LICENSE", "LICENSE.md", "LICENSE.txt") if read(n) is not None]
    if len(files) == 0:
        print("licence-guard: no licence file. The repo would state no terms at all.")
        return 1
    if len(files) > 1:
        print("licence-guard: %d licence files (%s). Which one governs is ambiguous, and a "
              "half-finished relicense looks exactly like this." % (len(files), ", ".join(files)))
        return 1

    actual = detect(read(files[0]))
    if actual in (None, "unknown"):
        print("licence-guard: %s matches no known licence text. A reader cannot tell what they "
              "are agreeing to." % files[0])
        return 1

    bad = []
    for doc in ("README.md", "NOTICE", "TRADEMARK.md"):
        says = claimed(read(doc))
        if says and says != actual:
            bad.append("%s says %s, %s is %s" % (doc, says, files[0], actual))

    if bad:
        print("licence-guard: the repo contradicts itself about its own licence.")
        for b in bad:
            print("  " + b)
        print("Fix the wording, or the licence file, before committing. This is how the FSL "
              "relicense was silently undone on this repo once already.")
        return 1

    print("licence-guard: %s (from %s), and README/NOTICE/TRADEMARK agree." % (actual, files[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
