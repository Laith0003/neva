"""Exercise the release harness negative control using its actual shell code."""
import json
import os
import shlex
import subprocess

from support import REPO, TreeCase


class VerifyTemporaryRoot(TreeCase):
    def test_negative_control_resolves_a_symlinked_temporary_root(self):
        """macOS reaches TMPDIR through /var and /tmp, which are system symlinks."""
        actual = self.root / "actual"
        actual.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        script = (REPO / "build/verify.sh").read_text()
        section = script.split("SHIELD_BAD_FLAG=", 1)[1].split('\nprintf "\\n%s\\n"', 1)[0]
        section = "SHIELD_BAD_FLAG=" + section
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; FAIL=1; }; FAIL=0\n"
        env = dict(os.environ, REPO=str(REPO), TMPDIR=str(alias), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", "-c", prelude + section + 'exit "$FAIL"'],
                              cwd=self.root, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("PASS negative control:", done.stdout)
        self.assertIn("PASS Shield emits SARIF", done.stdout)
        self.assertNotIn("FAIL", done.stdout)
        self.assertEqual([], list(actual.iterdir()))

    def test_negative_control_uses_real_temporary_root(self):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_BAD_FLAG=" + script.split("SHIELD_BAD_FLAG=", 1)[1].split('\nprintf "\\n%s\\n"', 1)[0]
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; FAIL=1; }; FAIL=0\n"
        env = dict(os.environ, REPO=str(REPO), TMPDIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", "-c", prelude + section + 'exit "$FAIL"'],
                              cwd=self.root, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("PASS negative control:", done.stdout)
        self.assertIn("PASS Shield emits SARIF", done.stdout)
        self.assertNotIn("FAIL", done.stdout)
        self.assertEqual([], list(self.root.iterdir()))

    def test_sarif_error_exit_cannot_pass_with_valid_output(self):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_BAD_FLAG=" + script.split("SHIELD_BAD_FLAG=", 1)[1].split('\nprintf "\\n%s\\n"', 1)[0]
        sarif = json.dumps({"version": "2.1.0", "runs": [{"results": [{"locations": [
            {"physicalLocation": {"region": {"startLine": 1}}}]}]}]})
        command = 'python3 bin/neva shield --path "$SHIELD_NEG" --format sarif 2>/dev/null'
        self.assertIn(command, section)
        section = section.replace(command, "printf '%s' " + shlex.quote(sarif) + "; exit 2")
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; FAIL=1; }; FAIL=0\n"
        env = dict(os.environ, REPO=str(REPO), TMPDIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", "-c", prelude + section + 'exit "$FAIL"'],
                              cwd=self.root, env=env, text=True, capture_output=True, check=False)
        self.assertNotEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("FAIL Shield SARIF output", done.stdout)
        self.assertNotIn("PASS Shield emits SARIF", done.stdout)
        self.assertEqual([], list(self.root.iterdir()))

    def test_negative_control_error_exit_cannot_pass_with_findings(self):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_BAD_FLAG=" + script.split("SHIELD_BAD_FLAG=", 1)[1].split('\nprintf "\\n%s\\n"', 1)[0]
        command = 'python3 bin/neva shield --path "$SHIELD_NEG" --fail-on high 2>&1'
        self.assertIn(command, section)
        section = section.replace(command, command + "; exit 2")
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; FAIL=1; }; FAIL=0\n"
        env = dict(os.environ, REPO=str(REPO), TMPDIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", "-c", prelude + section + 'exit "$FAIL"'],
                              cwd=self.root, env=env, text=True, capture_output=True, check=False)
        self.assertNotEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("FAIL Shield negative control", done.stdout)
        self.assertNotIn("PASS negative control:", done.stdout)
        self.assertEqual([], list(self.root.iterdir()))


class VerifySelfScanWording(TreeCase):
    def test_pass_line_does_not_call_a_low_grade_clean(self):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_RC=0" + script.split("SHIELD_RC=0", 1)[1].split("# The flag below", 1)[0]
        command = 'cd "$REPO" && python3 bin/neva shield --path . --fail-on high 2>&1'
        self.assertIn(command, section)
        section = section.replace(command, "printf 'Neva Shield  grade F  score 34/100'")
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; }\n"
        done = subprocess.run(["bash", "-c", prelude + section], cwd=self.root, text=True,
                              capture_output=True, check=False)
        self.assertIn("PASS", done.stdout)
        self.assertIn("no high or critical findings", done.stdout)
        self.assertNotIn("clean", done.stdout)


    def test_a_blocked_self_scan_prints_its_reason(self):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_RC=0" + script.split("SHIELD_RC=0", 1)[1].split("# The flag below", 1)[0]
        command = 'cd "$REPO" && python3 bin/neva shield --path . --fail-on high 2>&1'
        self.assertIn(command, section)
        reason = "shield: hooks: symlinked directory hides its contents from the scan"
        section = section.replace(command, "sh -c " + shlex.quote("printf '%s\\n' " + shlex.quote(reason) + "; exit 2"))
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s %s\\n' \"$1\" \"$2\"; }\n"
        done = subprocess.run(["bash", "-c", prelude + section], cwd=self.root, text=True,
                              capture_output=True, check=False)
        self.assertIn("FAIL Shield on this repo", done.stdout)
        self.assertIn(reason, done.stdout)


class VerifyPaidModel(TreeCase):
    def run_live_section(self, enabled=None):
        script = (REPO / "build/verify.sh").read_text()
        section = script.split('# 39d. The live agent.', 1)[1].split('rm -f "$VNOTE"', 1)[0]
        marker = self.root / "called"
        prelude = """
command() { printf '/fake/openclaw'; }
timeout() { printf called > MARKER; printf '%s' '{"payloads":[{"text":"planted Aldebaran"}]}'; }
ok() { printf 'PASS %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; exit 1; }
skip_() { printf 'SKIP %s\n' "$2"; }
VTOKEN=planted
""".replace("MARKER", shlex.quote(str(marker)))
        env = dict(os.environ, HOME=str(self.root), CLAUDE_CODE_OAUTH_TOKEN="test-only",
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("NEVA_VERIFY_LIVE_MODEL", None)
        if enabled is not None:
            env["NEVA_VERIFY_LIVE_MODEL"] = enabled
        done = subprocess.run(["bash", "-c", prelude + section], cwd=self.root,
                              env=env, text=True, capture_output=True, check=False)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        return done, marker

    def test_credentials_alone_do_not_call_a_paid_model(self):
        done, marker = self.run_live_section()
        self.assertIn("SKIP", done.stdout)
        self.assertIn("NEVA_VERIFY_LIVE_MODEL=1", done.stdout)
        self.assertNotIn("PASS", done.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / ".openclaw").exists())

    def test_explicit_opt_in_exercises_the_model_command(self):
        done, marker = self.run_live_section("1")
        self.assertIn("PASS live agent answered", done.stdout)
        self.assertNotIn("SKIP", done.stdout)
        self.assertEqual("called", marker.read_text())
        self.assertTrue((self.root / ".openclaw/openclaw.json").is_file())

    def test_non_opt_in_values_do_not_enable_the_model(self):
        for value in ("0", "true", "yes"):
            with self.subTest(value=value):
                done, marker = self.run_live_section(value)
                self.assertIn("SKIP", done.stdout)
                self.assertFalse(marker.exists())
                self.assertFalse((self.root / ".openclaw").exists())


class VerifySuiteStatus(TreeCase):
    def run_summary(self, summary, status):
        script = (REPO / "build/verify.sh").read_text()
        section = "SHIELD_SUITE_RC=" + script.split("SHIELD_SUITE_RC=", 1)[1].split("SHIELD_RC=", 1)[0]
        command = 'cd "$REPO" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=lib:lib/neva_shield/tests python3 -m unittest discover -s lib/neva_shield/tests -t lib/neva_shield/tests 2>&1'
        self.assertIn(command, section)
        section = section.replace(command, "printf '%s' " + shlex.quote(summary) + "; exit " + str(status))
        prelude = "ok() { printf 'PASS %s\\n' \"$1\"; }; bad() { printf 'FAIL %s\\n' \"$1\"; FAIL=1; }; FAIL=0\n"
        done = subprocess.run(["bash", "-c", prelude + section + 'exit "$FAIL"'], cwd=self.root,
                              env=dict(os.environ, REPO=str(REPO)), text=True, capture_output=True, check=False)
        return done

    def test_success_output_with_nonzero_exit_blocks(self):
        done = self.run_summary("Ran 5 tests in 0.1s\n\nOK\n", 7)
        self.assertNotEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("FAIL Shield suite", done.stdout)
        self.assertNotIn("PASS", done.stdout)

    def test_empty_suite_blocks(self):
        done = self.run_summary("Ran 0 tests in 0.1s\n\nOK\n", 0)
        self.assertNotEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("FAIL Shield suite", done.stdout)

    def test_successful_nonempty_suite_passes(self):
        done = self.run_summary("Ran 5 tests in 0.1s\n\nOK\n", 0)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("PASS Shield suite", done.stdout)
        self.assertNotIn("FAIL", done.stdout)
