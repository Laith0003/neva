import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from neva_omni.safe_write import atomic_write
from neva_cli.commands import brainpack


class SafeWriteTest(unittest.TestCase):
    def test_escape_refused_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = os.path.realpath(temporary)
            with self.assertRaisesRegex(ValueError, "escapes root"):
                atomic_write(os.path.join(base, "allowed"), os.path.join(base, "owner"), "bad")
            self.assertEqual(os.listdir(base), [])

    def test_brainpack_refuses_leaf_and_parent_symlinks(self):
        for component in ("leaf", "parent"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as temporary:
                base = os.path.realpath(temporary)
                outside = os.path.join(base, "owner")
                os.mkdir(outside)
                target = os.path.join(outside, "pack.json")
                with open(target, "w") as stream:
                    stream.write("owner bytes")
                output = os.path.join(base, "output")
                if component == "parent":
                    os.symlink(outside, output)
                else:
                    os.mkdir(output)
                    os.symlink(target, os.path.join(output, "pack.json"))
                note = os.path.join(base, "note.md")
                with open(note, "w") as stream:
                    stream.write("synthetic note")
                config = os.path.join(base, "omni.json")
                with open(config, "w") as stream:
                    stream.write('{"include": ["note.md"]}')
                args = SimpleNamespace(config=config, out=os.path.join(output, "pack.json"))
                with patch.object(brainpack, "compile_pack", return_value={"tiers": {}}):
                    capture = io.StringIO()
                    with contextlib.redirect_stdout(capture):
                        self.assertEqual(brainpack.run(args), 2)
                    self.assertIn("symlink", capture.getvalue())
                with open(target) as stream:
                    self.assertEqual(stream.read(), "owner bytes")
                self.assertEqual(os.listdir(outside), ["pack.json"])

    def test_atomic_replace_and_expansion_leave_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = os.path.realpath(temporary)
            with patch.dict(os.environ, {"NEVA_TEST_OUTPUT": base}):
                atomic_write("$NEVA_TEST_OUTPUT", "$NEVA_TEST_OUTPUT/pack.json", "first")
                atomic_write(base, os.path.join(base, "pack.json"), "second")
            with open(os.path.join(base, "pack.json")) as stream:
                self.assertEqual(stream.read(), "second")
            self.assertEqual(os.listdir(base), ["pack.json"])

    def test_installed_layout_entry_point_and_brainpack(self):
        source = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        with tempfile.TemporaryDirectory() as temporary:
            base = os.path.realpath(temporary)
            prefix = os.path.join(base, "prefix")
            os.mkdir(prefix)
            # Match install.sh's bin/lib copies. No source-tree imports in the child.
            for directory in ("bin", "lib"):
                shutil.copytree(os.path.join(source, directory), os.path.join(prefix, directory),
                                ignore=shutil.ignore_patterns("__pycache__"))
            entry = os.path.join(prefix, "bin", "neva")
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            env.pop("PYTHONPATH", None)
            for python in (sys.executable, "/usr/bin/python3"):
                if not os.path.isfile(python):
                    continue
                result = subprocess.run([python, entry, "--help"], cwd=base, env=env,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("brainpack", result.stdout)
                output = os.path.join(base, "pack.json")
                if os.path.exists(output):
                    os.remove(output)
                # The default config is empty: nothing is compiled and nothing is written.
                result = subprocess.run([python, entry, "brainpack", "--out", output],
                                        cwd=base, env=dict(env, HOME=base, NEVA_OMNI_CONFIG=""),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('"include" list', result.stdout)
                self.assertFalse(os.path.exists(output))
                with open(os.path.join(base, "note.md"), "w") as stream:
                    stream.write("synthetic note")
                with open(os.path.join(base, "omni.json"), "w") as stream:
                    stream.write('{"include": ["note.md"]}')
                result = subprocess.run([python, entry, "brainpack", "--config",
                                         os.path.join(base, "omni.json"), "--out", output],
                                        cwd=base, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("brainpack:", result.stdout)
                with open(output) as stream:
                    self.assertIn("tiers", json.load(stream))
