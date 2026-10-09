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
import subprocess
import sys

# ---- tier 1: the enumerated denylist (case-insensitive) ----
def _load_tier1():
    """Personal identifiers live OUTSIDE the repo, in a gitignored file.

    A tier-1 denylist is a list of the exact strings you most need to keep private. Shipping
    it inside a public repository publishes them. This is not theoretical: the real list sat
    in this file, in plain text, through fifteen commits, and was caught by a pre-publication
    audit rather than by this scanner, because SKIP_DIRS excluded the directory this file is
    in. Both halves of that are fixed now.

    If the local file is absent, tier 1 is INACTIVE and main() says so loudly. It must never
    print "clean" while silently checking nothing.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "leak-scan.local")
    if not os.path.isfile(local):
        return [], False
    pats = []
    for line in open(local, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(line)
    return pats, True


TIER1, TIER1_ACTIVE = _load_tier1()

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
_RFC2606 = re.compile(r"@(?:[a-z0-9.-]+\.)?example(?:\.(?:com|net|org))?\b", re.I)

TIER2_ALLOW = {
    # verify.sh asserts that an unreachable token fails honestly. This value is all zeros
    # and cannot authenticate against anything; it is a fixture, not a secret.
    "000000000:AA_a_deliberately_fake_unreachable_token",
    "+9990000000",                 # documented fake phone
    "you@example.com",             # documented fake email
    "agent@node", "owner@local",   # ported commit identities (note: install.sh actually
                                    # writes "agent@local"; .git is skip-dir'd either way,
                                    # so this has not been reachable -- left as-is, flagged
                                    # in the security audit rather than silently changed)
    "/Users/you/",                 # the documented placeholder path (docs/CONFIGURATION.md)
    # Plugin fixtures and docs (ECC-derived, reviewed 2026-09-29): generic placeholders only.
    "/home/user/", "/home/username/",
    "/home/resolve/",              # DaVinci Resolve's documented Linux install path
    "+447700900123",               # Ofcom-reserved fictional UK drama number, test fixture
    "eutilities@ncbi.nlm.nih.gov", # NCBI's published E-utilities contact, required by their API terms
    "git@github.com",              # SSH remote host, not a person
    "existing@2x.png", "HomePage-Default@3x.png", "HomePage-List-Default@3x.png",  # retina asset names
    "-@dev.md",                    # markdown anchor fragment
    "/users/by/", "/users/migrations/", "/users/tests/",  # URL path segments, not home dirs
}
# "build" used to be here too. That is exactly why a real leak survived: a person's name in
# build/verify.sh was invisible to the tool meant to catch them. A scanner that does not scan
# itself is not a scanner, so "build" is not skipped.
#
# Interpreter and test caches (__pycache__, .pytest_cache, any .pyc) are NOT skipped by name.
# A .pyc bakes the compiler's absolute source path into co_filename, so it is exactly where a
# home path hides. They are skipped only when they are demonstrably disposable: the scan root
# is a git checkout and git does not track the file. Such a file cannot ship, because releases
# and CI start from a fresh checkout. Outside a checkout (an export, an unzipped artifact, a
# directory git cannot read) they are scanned like everything else, and a cache file forced
# into the index with `git add -f` is scanned too. PYTHONDONTWRITEBYTECODE=1 in build/verify.sh
# and the documented test commands keeps most of them from being written in the first place,
# but that is hygiene, not the guarantee. The controls in build/verify.sh (section 11) plant
# leaks in a cache directory and a .pyc, in an export and as a force-added file.
SKIP_DIRS = {".git", "node_modules", ".obsidian"}
CACHE_DIRS = {"__pycache__", ".pytest_cache"}
CACHE_EXT = {".pyc"}
# The personal denylist is gitignored and never ships. Scanning it would report every
# pattern it contains as a leak, which is noise that teaches people to ignore this tool.
SKIP_FILES = {"leak-scan.local",
              # In a git worktree, .git is a FILE holding "gitdir: /absolute/path/to/.git/...".
              # The SKIP_DIRS entry above only ever matched the directory form, so every scan
              # run inside a worktree reported that pointer as a home-path leak and the
              # pre-commit hook refused every commit. It is git plumbing, never shipped content.
              ".git"}
SKIP_EXT = {".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".zip"}

# An empty alternation matches the empty string at every position, so guard it: with no
# local denylist, tier 1 must match NOTHING rather than everything.
T1 = re.compile("|".join(f"({p})" for p in TIER1), re.I) if TIER1 else None



# The ONE place the author's real name must appear: the copyright and trademark lines.
# A licence without a named holder grants nothing, and a trademark notice without an owner
# names no owner. This exemption is scoped to those two files AND to lines that actually
# carry an attribution keyword. It is deliberately NOT a substring allowlist: that design
# is what let a real secret hide beside a placeholder and it is not coming back. A real
# leak anywhere else in these files, or on any other line in them, still fails the scan.
def tracked_files(root):
    """Paths git tracks under `root`, relative to it, or None when `root` is not a readable git
    checkout. None means nothing can be shown to be disposable, so every cache file is scanned."""
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {p.decode("utf-8", "surrogateescape") for p in r.stdout.split(b"\0") if p}


def _is_cache(rel):
    parts = rel.replace(os.sep, "/").split("/")
    return any(p in CACHE_DIRS for p in parts[:-1]) or os.path.splitext(parts[-1])[1].lower() in CACHE_EXT


def scan(root):
    findings = []
    tracked = tracked_files(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            if tracked is not None and _is_cache(rel) and rel.replace(os.sep, "/") not in tracked:
                continue  # an untracked cache artifact in a git checkout: it cannot ship
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                m = T1.search(line) if T1 else None
                if m:
                    findings.append(("TIER1", rel, n, m.group(0)))
                for label, rx in TIER2:
                    for m2 in rx.finditer(line):
                        if m2.group(0) in TIER2_ALLOW:
                            continue
                        # RFC 2606 reserves example.com, example.net, example.org and the
                        # .example TLD for documentation. An address there cannot reach a
                        # real person, so it is a false positive by construction.
                        if _RFC2606.search(m2.group(0)):
                            continue
                        findings.append((f"TIER2:{label}", rel, n, m2.group(0)))
    return findings


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    findings = scan(root)
    if not TIER1_ACTIVE:
        # Never print "clean" while silently checking nothing. A scanner that appears to pass
        # because it was never configured is worse than one that is absent, because it is
        # trusted.
        print("leak-scan: TIER 1 INACTIVE. No build/leak-scan.local found, so NO personal "
              "identifiers are being checked, only the generic patterns below.\n"
              "fix: cp build/leak-scan.local.example build/leak-scan.local and put your own "
              "names, numbers, paths and client names in it. That file is gitignored.",
              file=sys.stderr)
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
