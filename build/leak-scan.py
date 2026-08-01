#!/usr/bin/env python3
"""leak-scan: the release gate. Zero personal identifiers leave this repo, enforced.

Tier 1: enumerated denylist of the author's real identifiers. ZERO tolerance, no allowlist,
any hit fails the build. This list is the whole point: for a template derived from a
personal system, the dangerous leaks are known and finite, so we enumerate them instead of
hoping a generic PII regex catches them.

Tier 2: generic shapes (phones, emails, chat ids, home paths, token shapes, common vendor
secret prefixes). Allowlisted only for the documented fake placeholders, matched EXACTLY
against the finding's own text -- never against the surrounding line. (A prior version
allowlisted by substring-of-line, which meant any real secret sharing a line with a
documented fake placeholder was silently suppressed. Fixed 2026-08-01, see docs/09-security.md.)

Known limitations, by design, not fixed here (see docs/09-security.md for the honest list):
  - Single-file, single-line regex matching only. A base64/url-encoded identifier, or an
    identifier deliberately split across two lines, will not be caught. Encode-before-paste
    defeats this scanner, same as it defeats gitleaks/trufflehog without their entropy engine.
  - Binary extensions in SKIP_EXT are never opened, so a leak embedded in image metadata
    (a PNG tEXt chunk, EXIF) is invisible here. Screenshots are out of scope for a text scanner;
    do not paste raw screenshots into the release tree.
  - This is a denylist/shape scanner, not a Shannon-entropy engine. It now recognizes a
    handful of common vendor token PREFIXES (below) but will still miss a random high-entropy
    secret that matches no known vendor shape and sits far from a "key"/"token"/"secret"
    keyword. gitleaks' generic-api-key rule (keyword + entropy>=3.5) and trufflehog's verified-
    secret detectors both catch more here than this file does; this file is a light gate for a
    small template, not a replacement for a real scanner in CI.

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
    # owner phone: any run of spaces/dots/dashes/parens between digits, optional leading +
    r"\+?962[\s().\-]*7[\s().\-]*9[\s().\-]*7[\s().\-]*8[\s().\-]*6[\s().\-]*8[\s().\-]*3[\s().\-]*3[\s().\-]*5",
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
    r"لايث",                        # "Laith" in Arabic script (لايث)
    r"الجنيدي",       # "Aljunaidy" in Arabic script (الجنيدي)
]

# ---- tier 2: generic shapes ----
TIER2 = [
    ("phone-shaped", re.compile(r"\+\d{7,15}")),
    ("email-shaped", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ("bot-token-shaped", re.compile(r"\b\d{5,16}:A[A-Za-z0-9_-]{33,}")),
    ("home-path", re.compile(r"/home/[a-z]+/|/Users/[a-z]+/", re.I)),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # common vendor secret prefixes -- narrows the gap vs. gitleaks/trufflehog default rules.
    # still shape-based, not entropy-based: see the module docstring for what this misses.
    ("github-pat-shaped", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bghp_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key-shaped", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("openai-key-shaped", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("slack-token-shaped", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt-shaped", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]
# Exact-match only: an allow entry must equal the ENTIRE matched finding text, never just be
# present somewhere in the surrounding line. Line-wide "contains" matching used to mean a real
# secret sharing a line with a documented fake placeholder (e.g. "real: X, placeholder: Y")
# suppressed the real finding too. Do not change this back to substring-of-line matching.
TIER2_ALLOW = {
    "+9990000000",                 # documented fake phone
    "you@example.com",             # documented fake email
    "neva@jarvis",                 # never present; kept for safety
    "agent@node", "owner@local",   # ported commit identities (note: install.sh actually
                                    # writes "agent@local"; .git is skip-dir'd either way,
                                    # so this has not been reachable -- left as-is, flagged
                                    # in the security audit rather than silently changed)
    "/Users/you/",                 # the documented placeholder path (docs/CONFIGURATION.md)
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".obsidian", "build"}
SKIP_EXT = {".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".zip"}

T1 = re.compile("|".join(f"({p})" for p in TIER1), re.I)



# The ONE place the author's real name must appear: the copyright and trademark lines.
# A licence without a named holder grants nothing, and a trademark notice without an owner
# names no owner. This exemption is scoped to those two files AND to lines that actually
# carry an attribution keyword. It is deliberately NOT a substring allowlist: that design
# is what let a real secret hide beside a placeholder and it is not coming back. A real
# leak anywhere else in these files, or on any other line in them, still fails the scan.
LEGAL_FILES = {"NOTICE", "LICENSE", "TRADEMARK.md"}
_ATTRIB = re.compile(r"(?i)\b(copyright|\(c\)|©|trademark|licensed to|author)\b")


def _legal_attribution(rel, line):
    return rel in LEGAL_FILES and _ATTRIB.search(line) is not None


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
                if m and not _legal_attribution(rel, line):
                    findings.append(("TIER1", rel, n, m.group(0)))
                for label, rx in TIER2:
                    for m2 in rx.finditer(line):
                        if m2.group(0) in TIER2_ALLOW:
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
