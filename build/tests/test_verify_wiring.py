"""verify.sh must run every hook and build test file, not a hand-picked subset."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = (ROOT / "build" / "verify.sh").read_text(encoding="utf-8")
HOOK_TESTS = ROOT / "plugins" / "neva-core" / "hooks" / "tests"


class TestVerifyWiring(unittest.TestCase):
    def test_hook_tests_run_by_discovery(self):
        self.assertTrue("python3 -m unittest discover -s plugins/neva-core/hooks/tests -p 'test_*.py'" in VERIFY,
                        "verify.sh does not discover plugins/neva-core/hooks/tests")

    def test_build_tests_run_by_discovery(self):
        self.assertTrue(re.search(r"python3 -m unittest discover -s build/tests(\s|$|\))", VERIFY),
                        "verify.sh does not discover build/tests")

    def test_every_hook_test_file_runs_standalone(self):
        for path in sorted(HOOK_TESTS.glob("test_*.py")):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(re.search(r'^if __name__ == "__main__":\n    unittest\.main\(', text, re.M),
                                f"{path.name} needs an `if __name__ == \"__main__\": unittest.main()` block")


if __name__ == "__main__":
    unittest.main()
