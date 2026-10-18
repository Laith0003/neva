"""Negative controls for managed learning writes, including direct helper callers."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "plugins/neva-core/skills/continuous-learning-v2/scripts"
HOOKS = ROOT / "plugins/neva-core/hooks"

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class LearningWriteGuardsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.managed = self.base / "managed"
        self.managed.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.owner = self.outside / "owner"
        self.owner.write_bytes(b"owner data\n")
        sys.path.insert(0, str(HOOKS))
        self.addCleanup(sys.path.remove, str(HOOKS))
        from neva_hooks import observe
        self.observe = observe
        self.cli = load("neva_guard_cli", "instinct-cli.py")
        self.analyze = load("neva_guard_analyze", "instinct-analyze.py")

    def assert_refused(self, operation, link):
        before = {p.name: p.read_bytes() for p in self.outside.iterdir()}
        with self.assertRaisesRegex(Exception, "refusing to write.*symlink") as caught:
            operation()
        self.assertIn(str(link), str(caught.exception))
        self.assertIn("Fix:", str(caught.exception))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.outside.iterdir()})
        self.assertTrue(link.is_symlink())

    def test_observe_live_leaf_and_parent(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                bucket = self.managed / ("parent" if parent else "leaf")
                if parent:
                    bucket.symlink_to(self.outside, target_is_directory=True)
                    path = bucket / "owner"
                    link = bucket
                else:
                    bucket.mkdir()
                    path = bucket / "observations.jsonl"
                    path.symlink_to(self.owner)
                    link = path
                with mock.patch.object(self.observe.c, "observations_dir", return_value=str(self.managed)):
                    self.assert_refused(lambda: self.observe._append(path, {"event": "tool_start"}), link)

    def test_configured_root_symlink_is_trusted_after_realpath(self):
        """The configured root is trusted input: a dotfile manager may symlink it. Writes land in
        its real target; a symlink below the root is still refused."""
        link = self.base / "linked-root"
        link.symlink_to(self.outside, target_is_directory=True)
        io = self.analyze.learning_io
        self.assertEqual(io.ensure_dir(link, link / "new-directory"), self.outside / "new-directory")
        with io.open_append(link, link / "appended") as fh:
            fh.write("a\n")
        io.open_lock(link, link / "new-lock").close()
        io.write_new(link, link / "new-file", b"new")
        io.write_text_atomic(link, link / "atomic", "replacement")
        self.assertTrue((self.outside / "new-directory").is_dir())
        self.assertEqual((self.outside / "appended").read_text(), "a\n")
        self.assertTrue((self.outside / "new-lock").is_file())
        self.assertEqual((self.outside / "new-file").read_bytes(), b"new")
        self.assertEqual((self.outside / "atomic").read_text(), "replacement")
        self.assertEqual(self.owner.read_bytes(), b"owner data\n")
        inner = self.outside / "inner"
        inner.symlink_to(self.managed, target_is_directory=True)
        with self.assertRaisesRegex(Exception, "refusing to write.*symlink.*Fix:") as caught:
            io.write_new(link, link / "inner" / "escaped", b"x")
        self.assertIn(str(inner), str(caught.exception))
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_root_under_symlinked_parent_is_used_unresolved(self):
        link = self.base / "linked-parent"
        link.symlink_to(self.outside, target_is_directory=True)
        root = link / "new-root"
        io = self.analyze.learning_io
        io.ensure_dir(root, root / "bucket")
        self.assertTrue((self.outside / "new-root" / "bucket").is_dir())
        bucket = root / "bucket"
        (self.outside / "new-root" / "bucket" / "escape").symlink_to(self.managed, target_is_directory=True)
        with self.assertRaisesRegex(Exception, "refusing to write.*symlink"):
            io.ensure_dir(root, bucket / "escape" / "deeper")
        self.assertEqual(list(self.managed.iterdir()), [])

    def test_observe_records_under_the_unresolved_system_temp_dir(self):
        """The system temp dir is used as returned, never resolved: on macOS it sits under the
        /var -> /private/var symlink, as any root under /tmp or /var does."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "observations"
            with mock.patch.object(self.observe.c, "observations_dir", return_value=str(root)), \
                 mock.patch.object(self.observe.c, "log") as logged:
                for n in range(3):
                    self.observe._append(self.observe.live_file("bucket"), {"n": n})
            logged.assert_not_called()
            lines = (Path(os.path.realpath(raw)) / "observations" / "bucket" / "observations.jsonl").read_text()
            self.assertEqual(lines.splitlines(), ['{"n": 0}', '{"n": 1}', '{"n": 2}'])

    def test_literal_dollar_in_a_path_is_never_expanded(self):
        """Callers read and write the literal path; check() expanding $NAME would move the
        write somewhere the reader never looks."""
        io = self.analyze.learning_io
        literal = self.base / "data-$NEVA_GUARD_ROOT"
        with mock.patch.dict("os.environ", {"NEVA_GUARD_ROOT": str(self.outside)}):
            io.write_text_atomic(literal, literal / "kept.json", "safe")
            self.assertEqual(io.check(literal, literal / "kept.json"), literal / "kept.json")
        self.assertEqual((literal / "kept.json").read_text(), "safe")
        self.assertEqual([p.name for p in self.outside.iterdir()], ["owner"])

    def test_observe_bucket_symlink_is_refused_before_creation(self):
        bucket = self.managed / "linked-bucket"
        bucket.symlink_to(self.outside, target_is_directory=True)
        with mock.patch.object(self.observe.c, "observations_dir", return_value=str(self.managed)):
            self.assert_refused(lambda: self.observe.live_file("linked-bucket"), bucket)

    def test_managed_writes_succeed(self):
        with mock.patch.object(self.observe.c, "observations_dir", return_value=str(self.managed)):
            live = Path(self.observe.live_file("bucket"))
            self.observe._append(live, {"event": "tool_start"})
        self.assertEqual(live.read_text(), '{"event": "tool_start"}\n')
        ledger = self.managed / "instincts" / "promotions.json"
        with mock.patch.object(self.cli, "STATE_ROOT", self.managed), \
             mock.patch.object(self.cli, "PROMOTIONS_LEDGER", ledger):
            self.cli._write_text_atomic(ledger, '{"processed": true}\n')
        self.assertEqual(ledger.read_text(), '{"processed": true}\n')
        self.assertEqual(list(ledger.parent.glob(".*.tmp")), [])
        log = self.managed / "instinct-analyze.log"
        with mock.patch.object(self.analyze, "_state_root", return_value=self.managed), \
             mock.patch.object(self.analyze, "LOG_FILE", log), mock.patch("builtins.print") as output:
            self.analyze.log("managed append")
        self.assertIn("managed append", log.read_text())
        output.assert_called_once()

    def test_observe_rotation_pending_symlink(self):
        bucket = self.managed / "bucket"
        bucket.mkdir()
        live = bucket / "observations.jsonl"
        live.write_bytes(b"backlog\n")
        pending = bucket / "observations.pending"
        pending.symlink_to(self.outside, target_is_directory=True)
        with mock.patch.object(self.observe.c, "observations_dir", return_value=str(self.managed)), \
             mock.patch.object(self.observe.c, "env_int", return_value=0):
            self.assert_refused(lambda: self.observe._rotate(live), pending)
        self.assertEqual(live.read_bytes(), b"backlog\n")

    def test_observe_rotation_target_leaf_symlink(self):
        bucket = self.managed / "rotation-leaf"
        bucket.mkdir()
        live = bucket / "observations.jsonl"
        live.write_bytes(b"backlog\n")
        pending = bucket / "observations.pending"
        pending.mkdir()
        stamp = "fixed"
        target = pending / f"observations-{stamp}-{self.observe.os.getpid()}.jsonl"
        target.symlink_to(self.owner)
        with mock.patch.object(self.observe.c, "observations_dir", return_value=str(self.managed)), \
             mock.patch.object(self.observe.c, "env_int", return_value=0), \
             mock.patch.object(self.observe.datetime, "datetime") as clock:
            clock.now.return_value.strftime.return_value = stamp
            self.assert_refused(lambda: self.observe._rotate(live), target)
        self.assertEqual(live.read_bytes(), b"backlog\n")

    def test_ledger_atomic_leaf_and_parent(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                directory = self.managed / ("ledger-parent" if parent else "ledger-leaf")
                if parent:
                    directory.symlink_to(self.outside, target_is_directory=True)
                    target, link = directory / "owner", directory
                else:
                    directory.mkdir()
                    target = directory / "promotions.json"
                    target.symlink_to(self.owner)
                    link = target
                with mock.patch.object(self.cli, "STATE_ROOT", self.managed), \
                     mock.patch.object(self.cli, "PROMOTIONS_LEDGER", target):
                    self.assert_refused(lambda: self.cli._write_text_atomic(target, "replacement"), link)

    def test_analyzer_log_leaf_and_parent(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                directory = self.managed / ("log-parent" if parent else "log-leaf")
                if parent:
                    directory.symlink_to(self.outside, target_is_directory=True)
                    target, link = directory / "owner", directory
                else:
                    directory.mkdir()
                    target = directory / "instinct-analyze.log"
                    target.symlink_to(self.owner)
                    link = target
                with mock.patch.object(self.analyze, "_state_root", return_value=self.managed), \
                     mock.patch.object(self.analyze, "LOG_FILE", target):
                    self.assert_refused(lambda: self.analyze.log("guard probe"), link)
