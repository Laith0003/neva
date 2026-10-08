"""Neva cockpit: a read-only, local-only dashboard over what the hooks runtime already writes.

Shared helpers for the sqlite store, the ingester, health probes, the TUI and the web view live
here. Nothing in this package reimplements the hooks runtime's data dir resolution: it imports
plugins/neva-core/hooks/neva_hooks/common.py directly, so the cockpit always points at the same
NEVA_DATA_DIR the hooks write into.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = REPO_ROOT / "plugins" / "neva-core" / "hooks"


class HooksRuntimeMissing(ImportError):
    """The hooks runtime is not beside this lib/ folder. Raised with the path and the fix, so
    the CLI can print one line instead of a ModuleNotFoundError traceback."""


if not (_HOOKS_DIR / "neva_hooks" / "common.py").is_file():
    raise HooksRuntimeMissing(
        f"cockpit: the hooks runtime is missing at {_HOOKS_DIR / 'neva_hooks'} "
        "(plugins/neva-core/hooks is not installed beside lib/). "
        "fix: re-run install.sh from a Neva checkout so it copies plugins/ into the prefix")
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

from neva_hooks import common as hooks_common  # noqa: E402

__all__ = ["REPO_ROOT", "HooksRuntimeMissing", "hooks_common"]
