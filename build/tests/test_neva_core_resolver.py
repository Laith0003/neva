"""Tests for plugins/neva-library/scripts/neva_core.py, the library's way back into neva-core."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins" / "neva-library" / "scripts" / "neva_core.py"
TEXT = {".md", ".py", ".js", ".mjs", ".cjs", ".sh", ".json", ".txt", ".toml", ".yaml", ".yml", ""}
SPEC = importlib.util.spec_from_file_location("neva_core_resolver", SCRIPT)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


def plugin(path, name):
    (path / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (path / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return path


class TestResolver(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neva-core-resolver-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repo_layout_finds_the_sibling(self):
        self.assertEqual(resolver.core_root(ROOT / "plugins" / "neva-library", env={}),
                         (ROOT / "plugins" / "neva-core").resolve())

    def test_cache_layout_prefers_the_same_version(self):
        cache = self.tmp / "cache" / "neva"
        for v in ("0.9.0", "0.11.0", "0.12.0"):
            plugin(cache / "neva-core" / v, "neva-core")
        lib = plugin(cache / "neva-library" / "0.11.0", "neva-library")
        self.assertEqual(resolver.core_root(lib, env={}).name, "0.11.0")

    def test_cache_layout_falls_back_to_the_highest_numeric_version(self):
        cache = self.tmp / "cache" / "neva"
        for v in ("0.9.0", "0.10.2"):
            plugin(cache / "neva-core" / v, "neva-core")
        lib = plugin(cache / "neva-library" / "0.11.0", "neva-library")
        self.assertEqual(resolver.core_root(lib, env={}).name, "0.10.2")

    def test_env_override_wins_only_when_it_is_core(self):
        core = plugin(self.tmp / "elsewhere", "neva-core")
        lib = plugin(self.tmp / "lib", "neva-library")
        self.assertEqual(resolver.core_root(lib, env={"NEVA_CORE_ROOT": str(core)}), core)
        not_core = plugin(self.tmp / "other", "neva-web")
        with self.assertRaises(SystemExit) as caught:
            resolver.core_root(lib, env={"NEVA_CORE_ROOT": str(not_core)})
        self.assertIn("NEVA_CORE_ROOT", str(caught.exception))

    def test_missing_core_names_the_fix(self):
        lib = plugin(self.tmp / "lonely" / "neva-library", "neva-library")
        with self.assertRaises(SystemExit) as caught:
            resolver.core_root(lib, env={})
        self.assertIn("claude plugin install neva-core@neva", str(caught.exception))

    def test_paths_outside_core_are_refused(self):
        core = resolver.core_root(ROOT / "plugins" / "neva-library", env={})
        for bad in ("../neva-web/.claude-plugin/plugin.json", "/etc/hosts", "", "scripts/missing.py"):
            with self.subTest(path=bad), self.assertRaises(SystemExit):
                resolver.inside(core, bad)

    def test_cli_path_and_run_reach_core_scripts(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "path", "scripts/loop_status.py"],
                             capture_output=True, text=True, check=True)
        self.assertEqual(Path(out.stdout.strip()), (ROOT / "plugins/neva-core/scripts/loop_status.py").resolve())
        ran = subprocess.run([sys.executable, str(SCRIPT), "run", "scripts/harness_audit.py", "--help"],
                             capture_output=True, text=True)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("usage", ran.stdout.lower())


class TestLibraryRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neva-library-resolver-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_from_the_library_it_is_itself(self):
        lib = ROOT / "plugins" / "neva-library"
        self.assertEqual(resolver.library_root(lib, env={}), lib.resolve())

    def test_from_core_in_a_checkout_it_is_the_sibling(self):
        self.assertEqual(resolver.library_root(ROOT / "plugins" / "neva-core", env={}),
                         (ROOT / "plugins" / "neva-library").resolve())

    def test_from_core_in_the_cache_it_prefers_the_same_version(self):
        cache = self.tmp / "cache" / "neva"
        for v in ("0.9.0", "0.11.0", "0.12.0"):
            plugin(cache / "neva-library" / v, "neva-library")
        core = plugin(cache / "neva-core" / "0.11.0", "neva-core")
        self.assertEqual(resolver.library_root(core, env={}).name, "0.11.0")

    def test_core_is_itself_from_core(self):
        core = ROOT / "plugins" / "neva-core"
        self.assertEqual(resolver.core_root(core, env={}), core.resolve())

    def test_missing_library_names_the_fix(self):
        core = plugin(self.tmp / "lonely" / "neva-core", "neva-core")
        with self.assertRaises(SystemExit) as caught:
            resolver.library_root(core, env={})
        self.assertIn("claude plugin install neva-library@neva", str(caught.exception))


class TestBothRoots(unittest.TestCase):
    """Claude Code sets CLAUDE_PLUGIN_ROOT to the library; Codex reads the library's files with it
    exported as plugins/neva-core. Every path a library file runs or reads must work under both."""

    ROOTS = (ROOT / "plugins" / "neva-core", ROOT / "plugins" / "neva-library")
    RAW = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/([A-Za-z0-9_./-]+)"
                     r"|process\.env\.CLAUDE_PLUGIN_ROOT\s*\+\s*['\"]/([^'\"]+)")
    HELPER = re.compile(r"neva_core\.py\"?\s+(library|path|run)\s+([A-Za-z0-9_./-]+)")

    def refs(self):
        raw, helper = set(), set()
        for kind in ("skills", "commands", "agents"):
            for path in (ROOT / "plugins" / "neva-library" / kind).rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix not in TEXT:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                raw.update((a or b).rstrip(".,:;)") for a, b in self.RAW.findall(text))
                helper.update((m, r.rstrip(".,:;)")) for m, r in self.HELPER.findall(text))
        return raw, helper

    def test_the_two_helper_copies_are_identical(self):
        self.assertEqual((self.ROOTS[0] / "scripts" / "neva_core.py").read_bytes(),
                         (self.ROOTS[1] / "scripts" / "neva_core.py").read_bytes())

    def test_every_raw_plugin_root_path_exists_under_both_roots(self):
        raw, _ = self.refs()
        self.assertIn("scripts/neva_core.py", raw)
        for root in self.ROOTS:
            for ref in sorted(raw):
                with self.subTest(root=root.name, ref=ref):
                    self.assertTrue((root / ref).exists(), ref)

    def test_every_helper_path_resolves_under_both_roots(self):
        _, helper = self.refs()
        self.assertGreater(len(helper), 25)
        for root in self.ROOTS:
            for mode, ref in sorted(helper):
                with self.subTest(root=root.name, mode=mode, ref=ref):
                    out = subprocess.run([sys.executable, str(root / "scripts" / "neva_core.py"),
                                          "library" if mode == "library" else "path", ref],
                                         capture_output=True, text=True)
                    self.assertEqual(out.returncode, 0, out.stderr)
                    owner = "neva-library" if mode == "library" else "neva-core"
                    self.assertEqual(Path(out.stdout.strip()), (ROOT / "plugins" / owner / ref).resolve())

    def test_the_shell_form_runs_under_both_roots(self):
        command = 'test -d "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/neva_core.py" library skills/ck/commands)"'
        for root in self.ROOTS:
            with self.subTest(root=root.name):
                ran = subprocess.run(["bash", "-c", command], env={"PATH": os.environ["PATH"],
                                                                   "CLAUDE_PLUGIN_ROOT": str(root)})
                self.assertEqual(ran.returncode, 0)


if __name__ == "__main__":
    unittest.main()
