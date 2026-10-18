import argparse, contextlib, io, json, os, shutil, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from neva_cli.commands import brainpack


class BrainPackCommandTest(unittest.TestCase):
    """Runs the real command on synthetic files in a temporary HOME."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.out = os.path.join(self.root, "state", "brainpack.json")

    def write(self, relative, text):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(text)
        return path

    def run_command(self, config=None):
        parser = argparse.ArgumentParser()
        brainpack.add_arguments(parser)
        argv = ["--out", self.out] + (["--config", config] if config else [])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": self.root}), contextlib.redirect_stdout(out):
            os.environ.pop("NEVA_OMNI_CONFIG", None)
            code = brainpack.run(parser.parse_args(argv))
        return code, out.getvalue()

    def test_with_no_config_nothing_is_compiled_and_the_fix_is_named(self):
        self.write(".claude/rules/writing.md", "synthetic rule\n")
        self.write("vault/06 Memory/Claude Code/MEMORY.md", "synthetic memory\n")
        code, out = self.run_command()
        self.assertEqual(code, 2)
        self.assertIn(os.path.join(self.root, ".config", "neva", "omni.json"), out)
        self.assertIn('"include"', out)
        self.assertFalse(os.path.exists(self.out))

    def test_every_source_and_its_size_is_printed_before_the_pack_is_written(self):
        note = self.write("notes/a.md", "# A\nsynthetic note\n")
        skipped = self.write("notes/MEMORY.md", "synthetic memory\n")
        config = self.write("omni.json", json.dumps({"include": ["notes/*.md"]}))
        code, out = self.run_command(config)
        self.assertEqual(code, 0, out)
        self.assertIn("{} ({} bytes)".format(note, os.path.getsize(note)), out)
        self.assertIn(skipped, out)
        self.assertIn("exact path", out)
        for name in ("workers-ai", "groq", "gemini"):
            self.assertIn(name, out)
        with open(self.out) as stream:
            pack = json.load(stream)
        self.assertEqual(pack["sources"], [{"path": note, "bytes": os.path.getsize(note)}])
        self.assertNotIn("synthetic memory", json.dumps(pack))

    def test_a_refused_file_is_named_after_the_list_and_nothing_is_written(self):
        bad = self.write("notes/b.md", "key " + "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0\n")
        config = self.write("omni.json", json.dumps({"include": ["notes/*.md"]}))
        code, out = self.run_command(config)
        self.assertEqual(code, 2)
        self.assertIn("{} ({} bytes)".format(bad, os.path.getsize(bad)), out)
        self.assertIn("secret-shaped", out)
        self.assertLess(out.index("bytes)"), out.index("secret-shaped"))
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
