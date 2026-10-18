"""Concurrent observe appends must survive analyzer renames."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from test_instinct_learning import _load_module, ANALYZE, HOOKS_DIR

sys.path.insert(0, HOOKS_DIR)
from neva_hooks import observe


class AppendRaceCase(unittest.TestCase):
    def test_open_before_rename_retries_the_live_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            live = root / "observations.jsonl"
            live.write_bytes(b'{"n": 0}\n')
            analyzer = _load_module(ANALYZE, "analyzer_append_race")
            opened, resume = threading.Event(), threading.Event()
            errors = []
            original_open = observe._open_live
            first = True

            def delayed_open(path):
                nonlocal first
                fh = original_open(path)
                if str(path) == str(live) and first:
                    first = False
                    opened.set()
                    if not resume.wait(5):
                        raise RuntimeError("writer was not resumed")
                return fh

            def writer():
                try:
                    observe._append(str(live), {"n": 1})
                except BaseException as exc:
                    errors.append(exc)

            logged = []
            with mock.patch.object(observe, "_open_live", side_effect=delayed_open), \
                 mock.patch.object(observe.c, "log", side_effect=logged.append), \
                 mock.patch.object(observe.c, "observations_dir", return_value=str(root)):
                thread = threading.Thread(target=writer)
                thread.start()
                try:
                    self.assertTrue(opened.wait(5))
                    self.assertTrue(analyzer.archive_analyzed(live, b'{"n": 0}\n', root / "archive", root))
                finally:
                    resume.set()
                    thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(logged, [])
            records = [json.loads(line)["n"] for path in root.rglob("*.jsonl")
                       for line in path.read_text().splitlines()]
            self.assertEqual(sorted(records), [0, 1])

    def test_write_after_inode_check_lands_before_the_analyzer_reads(self):
        """The hook has passed its inode check and holds the lock when the analyzer renames the
        file aside. Only the analyzer's own flock on the moving file makes it wait for that write;
        without it the line goes into the unlinked moving file and is lost."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            live = root / "observations.jsonl"
            live.write_bytes(b'{"n": 0}\n')
            analyzer = _load_module(ANALYZE, "analyzer_delayed_fstat")
            checked, resume = threading.Event(), threading.Event()
            errors, logged, result = [], [], []
            real_fstat = os.fstat
            writer_thread = []

            def delayed_fstat(fd):
                st = real_fstat(fd)
                if threading.current_thread() is writer_thread[0] and not checked.is_set():
                    checked.set()
                    if not resume.wait(5):
                        raise RuntimeError("writer was not resumed")
                return st

            def writer():
                try:
                    observe._append(str(live), {"n": 1})
                except BaseException as exc:
                    errors.append(exc)

            def archiver():
                try:
                    result.append(analyzer.archive_analyzed(live, b'{"n": 0}\n', root / "archive", root))
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(observe.os, "fstat", side_effect=delayed_fstat), \
                 mock.patch.object(observe.c, "log", side_effect=logged.append), \
                 mock.patch.object(observe.c, "observations_dir", return_value=str(root)):
                thread = threading.Thread(target=writer)
                writer_thread.append(thread)
                thread.start()
                archive_thread = threading.Thread(target=archiver)
                try:
                    self.assertTrue(checked.wait(5))
                    archive_thread.start()
                    deadline = time.monotonic() + 5
                    while not list(root.glob(analyzer.MOVING_PREFIX + "*")) and archive_thread.is_alive() \
                            and time.monotonic() < deadline:
                        time.sleep(0.005)
                    # Long enough for an unlocked analyzer to read, re-append and unlink.
                    time.sleep(0.3)
                finally:
                    resume.set()
                    thread.join(5)
                    if archive_thread.ident:
                        archive_thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(archive_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(logged, [])
            self.assertEqual(result, [True])
            records = [json.loads(line)["n"] for path in root.rglob("*.jsonl")
                       for line in path.read_text().splitlines()]
            self.assertEqual(sorted(records), [0, 1])
            self.assertEqual([json.loads(x)["n"] for x in live.read_text().splitlines()], [1])

    def test_writer_and_archiver_loop_lose_no_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            live = root / "observations.jsonl"
            live.touch()
            analyzer = _load_module(ANALYZE, "analyzer_append_stress")
            errors = []

            def writer():
                try:
                    for n in range(4000):
                        observe._append(str(live), {"n": n})
                except BaseException as exc:
                    errors.append(exc)

            logged = []
            for patcher in (mock.patch.object(observe.c, "observations_dir", return_value=str(root)),
                            mock.patch.object(observe.c, "log", side_effect=logged.append)):
                patcher.start()
                self.addCleanup(patcher.stop)
            thread = threading.Thread(target=writer)
            thread.start()
            while thread.is_alive():
                try:
                    chunk = live.read_bytes()
                except FileNotFoundError:
                    continue
                # Archive only whole records, as the real analyzer does.
                chunk = chunk[:chunk.rfind(b"\n") + 1]
                if chunk:
                    analyzer.archive_analyzed(live, chunk, root / "archive", root)
            thread.join(5)
            self.assertEqual(errors, [])
            records = [json.loads(line)["n"] for path in root.rglob("*.jsonl")
                       for line in path.read_text().splitlines()]
            self.assertEqual(logged, [], "no observation was skipped under normal contention")
            self.assertEqual(sorted(records), list(range(4000)))


class BoundedAppendCase(unittest.TestCase):
    """observe runs on every tool call: it must never wait without limit (lesson 21)."""

    def run_bounded(self, root, live, extra_patch=None):
        logged, errors = [], []

        def writer():
            try:
                observe._append(str(live), {"n": 1})
            except BaseException as exc:
                errors.append(exc)

        patches = [mock.patch.object(observe.c, "observations_dir", return_value=str(root)),
                   mock.patch.object(observe.c, "log", side_effect=logged.append)]
        if extra_patch:
            patches.append(extra_patch)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        start = time.monotonic()
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        thread.join(1.0)
        elapsed = time.monotonic() - start
        self.assertFalse(thread.is_alive(), "observe._append did not return within 1 s")
        self.assertEqual(errors, [])
        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(logged), 1, logged)
        self.assertIn("observation skipped", logged[0])
        self.assertIn(str(live), logged[0])
        return logged

    def test_lock_held_by_another_process_skips_within_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            live = root / "observations.jsonl"
            live.write_bytes(b'{"n": 0}\n')
            holder = subprocess.Popen(
                [sys.executable, "-c", "import fcntl, sys, time\n"
                                       "fh = open(sys.argv[1], 'a')\n"
                                       "fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n"
                                       "print('locked', flush=True)\n"
                                       "time.sleep(60)\n", str(live)],
                stdout=subprocess.PIPE, text=True)
            self.addCleanup(holder.stdout.close)
            self.addCleanup(holder.wait)
            self.addCleanup(holder.kill)
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            logged = self.run_bounded(root, live)
            self.assertIn("locked", logged[0])
            self.assertEqual(live.read_bytes(), b'{"n": 0}\n')

    def test_inode_that_never_settles_stops_after_bounded_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            live = root / "observations.jsonl"
            live.write_bytes(b"")
            real_stat = os.stat

            def shifting_stat(path, *args, **kwargs):
                st = real_stat(path, *args, **kwargs)
                if str(path) != str(live):
                    return st
                fields = list(st)
                fields[stat.ST_INO] = st.st_ino + 1
                return os.stat_result(fields)

            logged = self.run_bounded(root, live, mock.patch.object(observe.os, "stat", side_effect=shifting_stat))
            self.assertIn("attempts", logged[0])
            self.assertEqual(live.read_bytes(), b"")


class LearningIoLoadCase(unittest.TestCase):
    def test_learning_io_is_loaded_once_per_process(self):
        """observe calls _learning_io() three times per observation; re-executing the module
        each time was most of the hook's cost."""
        # observe's own reference: other suites re-import neva_hooks, so the module object
        # imported here may differ from a fresh neva_hooks.learning_trigger.
        load = observe._learning_io
        import importlib.util
        with mock.patch.object(importlib.util, "spec_from_file_location",
                               wraps=importlib.util.spec_from_file_location) as spec:
            load.cache_clear()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with mock.patch.object(observe.c, "observations_dir", return_value=str(root)), \
                     mock.patch.object(observe.c, "log"):
                    for n in range(3):
                        observe._append(observe.live_file("bucket"), {"n": n})
        self.assertEqual(spec.call_count, 1)
        self.assertIs(load(), load())
