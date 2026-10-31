"""Shared test helpers: paths, temporary trees, and secret fixtures built at run time.

Credential fixtures are assembled here from fragments rather than stored in the tree. A
file holding a realistic token shape would be a finding in this repository's own leak scan
and in gitleaks, and a scanner that cannot be tested without planting one is a bad trade.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
LIB = HERE.parents[1]
REPO = LIB.parent
NEVA = REPO / "bin" / "neva"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

# Assembled so the literal never appears in a tracked file.
GITHUB_TOKEN = "gh" + "p_" + ("Ab3" * 12)
INLINE_SECRET = "Kq" + "7vR2" + "mT9x" + "Lz4N" + "pB6s" + "Wd1Y"
PEM_HEADER = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
STRIPE_KEY = "sk_" + "live_" + ("Ab3" * 8)
NOTION_TOKEN = "ntn_" + ("Ab3Cd" * 9)
LINEAR_KEY = "lin_" + "api_" + ("Ab3" * 12)
SENDGRID_KEY = "SG." + ("Ab3Cd" * 5) + "." + ("Ef4Gh" * 7)
TELEGRAM_TOKEN = "7204815" + "93:" + "AA" + ("Ab3Cd" * 7)


class TreeCase(unittest.TestCase):
    """A test case that can write a throwaway directory tree and scan it."""

    def setUp(self):
        scratch = REPO / "node_modules"
        if any(path.is_symlink() for path in (scratch, *scratch.parents)):
            raise RuntimeError("test scratch path contains a symlink; use a real repository directory")
        scratch.resolve().relative_to(REPO)
        scratch.mkdir(exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(prefix="neva-shield-test-", dir=scratch)
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def write(self, relative, content, mode=None):
        path = self.root / os.path.expandvars(relative)
        path = path.expanduser().absolute()
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("fixture path contains a symlink; choose a real path")
        try:
            path.resolve().relative_to(self.root.resolve(strict=True))
        except ValueError as exc:
            raise ValueError("fixture path is outside the temporary root") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if mode is not None:
            os.chmod(path, mode)
        return path

    def scan(self, subdirectory="", **kwargs):
        from neva_shield import scan_path
        return scan_path(self.root / subdirectory if subdirectory else self.root, **kwargs)

    def ids(self, result):
        return {item.rule_id for item in result.findings}


def fixture_ids(family, case):
    from neva_shield import scan_path
    return {item.rule_id for item in scan_path(FIXTURES / family / case).findings}


def fixture_result(family, case):
    from neva_shield import scan_path
    return scan_path(FIXTURES / family / case)
