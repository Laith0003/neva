# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Sandbox for the installer tests: a throwaway HOME, fake harness binaries, fixture adapters.

Nothing here touches the real home directory. HOME, NEVA_DATA_DIR and NEVA_ADAPTERS_DIR all
point inside one temporary tree, PATH is replaced by a directory of recording stubs, and every
fixture uses /home/user and example.com so no real identifier can reach the repo.
"""
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

LIB = Path(__file__).resolve().parents[2]
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from neva_cli import core  # noqa: E402
from neva_cli.commands import doctor, install, repair, uninstall  # noqa: E402
from neva_cli.commands import list as list_command  # noqa: E402

#: argv of every call to a fake binary lands here, one JSON object per line.
CALL_LOG = "calls.jsonl"

STUB = """#!{python}
import json, os, sys
with open(os.environ["NEVA_TEST_CALL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"binary": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
sys.stderr.write({stderr!r})
sys.exit({code})
"""


def stub_source(code=0, stderr=""):
    return STUB.format(python=sys.executable, code=code, stderr=stderr)


#: A fake `claude` that keeps marketplace and plugin registrations in a JSON file, the way the
#: real CLI keeps them under ~/.claude/plugins. It validates what the real one validates that
#: matters here: a marketplace source must hold .claude-plugin/marketplace.json, and a plugin
#: must be listed by a registered marketplace. Every call is logged like the plain stub.
CLAUDE_STUB = """#!{python}
import json, os, sys
with open(os.environ["NEVA_TEST_CALL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"binary": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
path = os.environ["NEVA_TEST_CLAUDE_STATE"]
try:
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
except FileNotFoundError:
    state = {{"marketplaces": [], "plugins": []}}

def save():
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)

def fail(message):
    sys.stderr.write(message + "\\n")
    sys.exit(1)

def manifest(source):
    try:
        with open(os.path.join(source, ".claude-plugin", "marketplace.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        fail("Marketplace file not found at " + os.path.join(source, ".claude-plugin", "marketplace.json"))

args = sys.argv[1:]
if args[:1] != ["plugin"]:
    sys.exit(0)
rest = args[1:]
if rest[:2] == ["marketplace", "list"]:
    print(json.dumps(state["marketplaces"]))
elif rest[:2] == ["marketplace", "add"]:
    source = rest[2]
    name = manifest(source)["name"]
    for market in state["marketplaces"]:
        if market["name"] == name:
            if market["source"] == source:
                sys.exit(0)
            fail("Marketplace '" + name + "' is already installed from " + market["source"])
    state["marketplaces"].append({{"name": name, "source": source}})
    save()
elif rest[:2] in (["marketplace", "remove"], ["marketplace", "rm"]):
    kept = [market for market in state["marketplaces"] if market["name"] != rest[2]]
    if len(kept) == len(state["marketplaces"]):
        fail("Marketplace '" + rest[2] + "' not found")
    state["marketplaces"] = kept
    save()
elif rest[:1] == ["list"]:
    print(json.dumps(state["plugins"]))
elif rest[:1] in (["install"], ["i"]):
    name, _, market_name = rest[1].partition("@")
    market = next((item for item in state["marketplaces"] if item["name"] == market_name), None)
    if market is None:
        fail("Marketplace '" + market_name + "' not found")
    if name not in [item["name"] for item in manifest(market["source"]).get("plugins", [])]:
        fail("Plugin '" + name + "' not found in marketplace '" + market_name + "'")
    if not any(item["id"] == rest[1] for item in state["plugins"]):
        state["plugins"].append({{"id": rest[1], "scope": "user", "enabled": True}})
        save()
elif rest[:1] in (["uninstall"], ["remove"]):
    kept = [item for item in state["plugins"] if item["id"] != rest[1]]
    if len(kept) == len(state["plugins"]):
        fail("Plugin '" + rest[1] + "' is not installed")
    state["plugins"] = kept
    save()
"""


def snapshot(root, skip=()):
    """Every path under root as {relative path: (mode, bytes or symlink target)}.

    Symlinks are recorded by target, never followed, so a symlink swapped for a copy of the
    same bytes still shows up as a difference.
    """
    root = Path(root)
    skipped = {str(Path(item)) for item in skip}
    result = {}
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories
                          if str(Path(current, name)) not in skipped]
        for name in sorted(directories) + sorted(files):
            path = Path(current, name)
            if str(path) in skipped:
                continue
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = ("symlink", os.readlink(path))
            elif path.is_dir():
                result[relative] = ("dir", "")
            else:
                result[relative] = ("file:" + oct(path.stat().st_mode & 0o777), path.read_bytes())
    return result


def difference(before, after):
    """Human readable list of what changed between two snapshots. Empty list means identical."""
    changes = []
    for key in sorted(set(before) | set(after)):
        if key not in after:
            changes.append("removed " + key)
        elif key not in before:
            changes.append("added " + key)
        elif before[key] != after[key]:
            changes.append("changed " + key)
    return changes


class Sandbox(unittest.TestCase):
    """Base class: a fresh HOME, fake binaries, and argparse-free access to each subcommand."""

    #: Binaries to put on PATH as recording stubs.
    binaries = ("claude", "codex", "opencode")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="neva-cli-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        # Neva's data directory sits OUTSIDE the sandbox HOME so the byte-identity assertion
        # after uninstall can be unconditional, with no excluded paths at all. Uninstall keeps
        # the backups it took, which in the default layout means ~/.local/share/neva survives
        # on purpose. test_lifecycle covers that default separately.
        self.data = self.root / "data"
        self.adapters = self.root / "adapters"
        self.binroot = self.root / "bin"
        self.calls = self.root / CALL_LOG
        for directory in (self.home, self.adapters, self.binroot):
            directory.mkdir(parents=True, exist_ok=True)
        self.calls.write_text("", encoding="utf-8")
        self.claude_state_path = self.root / "claude-state.json"
        for name in self.binaries:
            self.stub(name)
        if "claude" in self.binaries:
            self.stateful_claude()
        self.env({
            "HOME": str(self.home),
            "NEVA_DATA_DIR": str(self.data),
            "NEVA_ADAPTERS_DIR": str(self.adapters),
            "NEVA_TEST_CALL_LOG": str(self.calls),
            "NEVA_TEST_CLAUDE_STATE": str(self.claude_state_path),
            "PATH": str(self.binroot) + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
        })

    def env(self, values):
        for key, value in values.items():
            old = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(self._restore, key, old)

    @staticmethod
    def _restore(key, old):
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old

    def stub(self, name, code=0, stderr=""):
        """Put a recording fake binary on PATH. code and stderr make it fail on demand."""
        path = self.binroot / name
        path.write_text(stub_source(code, stderr), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def stateful_claude(self):
        """Put the registration-keeping fake claude on PATH (the default for every sandbox)."""
        path = self.binroot / "claude"
        path.write_text(CLAUDE_STUB.format(python=sys.executable), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def claude_state(self):
        """{"marketplaces": [...], "plugins": [...]} as the fake claude currently holds them."""
        try:
            return json.loads(self.claude_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"marketplaces": [], "plugins": []}

    def seed_claude(self, marketplaces=(), plugins=()):
        """Registrations the user already had before Neva arrived."""
        self.claude_state_path.write_text(json.dumps(
            {"marketplaces": list(marketplaces),
             "plugins": [{"id": item, "scope": "user", "enabled": True} for item in plugins]}),
            encoding="utf-8")

    def hide(self, *names):
        """Take binaries off PATH for one test by emptying the stub directory of them."""
        for name in names:
            (self.binroot / name).unlink(missing_ok=True)

    # -- running subcommands -------------------------------------------------

    def call(self, module, **options):
        """Run a subcommand's run() with argparse defaults overridden by keyword. (code, output)."""
        import argparse
        parser = argparse.ArgumentParser()
        if hasattr(module, "add_arguments"):
            module.add_arguments(parser)
        args = parser.parse_args([])
        for key, value in options.items():
            setattr(args, key, value)
        buffer = io.StringIO()
        # Pin stdin to a non-tty so the confirm gate behaves identically under a terminal test
        # run and under CI. A test that only passes when nothing is attached proves nothing.
        with contextlib.redirect_stdout(buffer), unittest.mock.patch("sys.stdin", io.StringIO("")):
            code = module.run(args)
        return int(code or 0), buffer.getvalue()

    def install(self, **options):
        options.setdefault("yes", True)
        return self.call(install, **options)

    def doctor(self, **options):
        options.setdefault("no_vault", True)
        return self.call(doctor, **options)

    def repair(self, **options):
        return self.call(repair, **options)

    def uninstall(self, **options):
        options.setdefault("yes", True)
        return self.call(uninstall, **options)

    def list(self, **options):
        return self.call(list_command, **options)

    # -- fixtures ------------------------------------------------------------

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_adapter(self, name, contract, sources=None):
        directory = self.adapters / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "install.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        for relative, body in (sources or {}).items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return directory

    def state(self):
        return core.load_state()

    def entries(self, harness=None):
        return [entry for entry in self.state()["entries"]
                if harness is None or entry.get("harness") == harness]

    def snapshot_home(self):
        return snapshot(self.home)

    def assertHomeUnchanged(self, before, message=""):
        changes = difference(before, self.snapshot_home())
        self.assertEqual(changes, [], (message + " " if message else "") +
                         "HOME is not byte identical: " + "; ".join(changes))
