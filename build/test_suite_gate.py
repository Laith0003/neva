"""Negative controls for verification suite acceptance."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class SuiteGateTests(unittest.TestCase):
    def gate(self, kind, status, output):
        result = subprocess.run(["python3", str(ROOT / "suite_gate.py"), kind, str(status)], input=output, text=True, capture_output=True)
        return result

    def test_python_positive(self):
        result = self.gate("python", 0, "Ran 2 tests in 0.001s\n\nOK\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted", result.stdout)

    def test_python_empty_failure_and_forged_success(self):
        for status, output in [(0, "Ran 0 tests in 0s\nOK\n"), (1, "Ran 1 tests in 0s\nFAILED (failures=1)\n"), (1, "Ran 1 tests in 0s\nOK\n")]:
            result = self.gate("python", status, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refused", result.stderr)

    def test_real_empty_and_failing_suites(self):
        parent = Path(tempfile.gettempdir()).resolve()  # /private/tmp on macOS, /tmp on Linux
        with tempfile.TemporaryDirectory(prefix="neva-gate-", dir=str(parent)) as name:
            directory = Path(name)
            self.assertTrue(directory.resolve().is_relative_to(parent))
            self.assertFalse(directory.is_symlink())
            for failing in (False, True):
                if failing:
                    path = directory / "test_failure.py"
                    self.assertFalse(path.is_symlink())
                    path.write_text("import unittest\nclass Failure(unittest.TestCase):\n def test_failure(self): self.fail('intentional negative control')\n")
                run = subprocess.run(["/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3", "-B", "-m", "unittest", "discover", "-s", name], capture_output=True, text=True)
                result = self.gate("python", run.returncode, run.stdout + run.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refused", result.stderr)
                # an empty suite exits 0 on Python up to 3.11 and 5 ("no tests ran") from 3.12; the gate refuses both
                self.assertIn(run.returncode, (1,) if failing else (0, 5))
            if not shutil.which("node"):
                return
            for failing in (False, True):
                path = directory / ("gate.test.mjs" if failing else "gate.fixture.mjs")
                self.assertFalse(path.is_symlink())
                path.write_text("import test from 'node:test';\n" + ("test('intentional failure', () => { throw Error('negative control'); });\n" if failing else ""))
                run = subprocess.run(["node", "--test", "--test-reporter=tap", str(path)] if failing else ["node", "--test", "--test-reporter=tap"], cwd=name, capture_output=True, text=True)
                result = self.gate("node", run.returncode, run.stdout + run.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refused", result.stderr)
                self.assertEqual(run.returncode, 1 if failing else 0)

    def test_malformed_and_duplicate_summaries_refuse(self):
        for kind, output in [
            ("python", "Ran 1 test in 0s\nRan 2 tests in 0s\nOK\n"),
            ("python", "Ran 1 test in 0s\nFAILED (failures=1)\nOK\n"),
            ("python", "Ran 1 test in 0s\nOK (skipped=1)\n"),
            ("node", "# tests 1\n# pass 1\n# fail 1\n# fail 0\n# cancelled 0\n"),
            ("node", "# tests 1\n# pass 1\n# fail 0\n"),
            ("node", "# tests 2\n# pass 1\n# fail 0\n# cancelled 0\n"),
        ]:
            result = self.gate(kind, 0, output)
            self.assertEqual(result.returncode, 1)
            self.assertIn("refused", result.stderr)
        result = self.gate("python", 0, "Ran 2 tests in 0s\nOK (skipped=1)\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted", result.stdout)

    def test_node_positive(self):
        result = self.gate("node", 0, "# tests 2\n# pass 2\n# fail 0\n# cancelled 0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted", result.stdout)

    def test_node_empty_failure_and_forged_success(self):
        for status, output in [(0, "# tests 0\n# pass 0\n# fail 0\n"), (1, "# tests 1\n# pass 0\n# fail 1\n"), (1, "# tests 1\n# pass 1\n# fail 0\n")]:
            result = self.gate("node", status, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refused", result.stderr)

if __name__ == "__main__":
    unittest.main()
