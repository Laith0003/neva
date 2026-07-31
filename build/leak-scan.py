#!/usr/bin/env python3
"""leak-scan: the release gate. Zero personal identifiers leave this repo, enforced.

Tier 1: enumerated denylist of the author's real identifiers. ZERO tolerance, no allowlist,
any hit fails the build. This list is the whole point: for a template derived from a
personal system, the dangerous leaks are known and finite, so we enumerate them instead of
hoping a generic PII regex catches them.

Tier 2: generic shapes (phones, emails, chat ids, home paths, token shapes). Allowlisted
only for the documented fake placeholders.

Runs on a directory tree (pre-commit, staging export, or an unzipped release artifact):
    python3 build/leak-scan.py [path]        default: repo root
Exit 0 clean, exit 1 on any finding.
"""
import os
import re
import sys

# ---- tier 1: the enumerated denylist (case-insensitive) ----
TIER1 = [
    r"laith", r"aljunaidy", r"junaidy",
    r"962\s?7\s?9\s?7\s?8\s?6\s?8\s?3\s?3\s?5",      # owner phone, any spacing
    r"962798224081", r"9647503730862", r"9647740847301",
    r"5177115582",                                     # telegram chat id
    r"laith\.aljunaidy\.laith", r"laithjunaidy\.com", r"laithaljunaidy\.me",
    r"brainof\.", r"thedotwallet",
    r"mercato", r"bayazid", r"hakki", r"bashiti", r"\bares\b", r"expora",
    r"qaddumi", r"qaddomi", r"\btiq\b", r"milagros", r"capsula",
    r"branders", r"nouran", r"aswad", r"mutasim", r"kusrin",
    r"164\.90\.188\.187", r"82\.212\.84\.211", r"192\.168\.1\.86",
    r"676767",
    r"/root/", r"/Users/laithaljunaidy",
    r"jarvis",                                          # the private product name
    r"8913245203:",                                     # bot token prefix
]

# ---- tier 2: generic shapes ----
TIER2 = [
    ("phone-shaped", re.compile(r"\+\d{7,15}")),
    ("email-shaped", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ("bot-token-shaped", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}")),
    ("home-path", re.compile(r"/home/[a-z]+/|/Users/[a-z]+/", re.I)),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
TIER2_ALLOW = {
    "+9990000000",                # documented fake phone
    "you@example.com",            # documented fake email
    "lucy@jarvis",                # never present; kept for safety
    "agent@node", "owner@local",  # ported commit identities
    "/Users/[a-z]+/",             # the regex source itself in this file
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".obsidian", "build"}
SKIP_EXT = {".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".zip"}

T1 = re.compile("|".join(f"({p})" for p in TIER1), re.I)


def scan(root):
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                m = T1.search(line)
                if m:
                    findings.append(("TIER1", rel, n, m.group(0)))
                for label, rx in TIER2:
                    for m2 in rx.finditer(line):
                        if any(a in m2.group(0) or a in line for a in TIER2_ALLOW):
                            continue
                        findings.append((f"TIER2:{label}", rel, n, m2.group(0)))
    return findings


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    findings = scan(root)
    if findings:
        print(f"leak-scan: {len(findings)} finding(s) in {root}")
        for tier, rel, n, frag in findings[:60]:
            print(f"  {tier:22s} {rel}:{n}  {frag[:50]}")
        if len(findings) > 60:
            print(f"  ... and {len(findings)-60} more")
        return 1
    print(f"leak-scan: clean ({root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
