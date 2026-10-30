"""The neva shield command: arguments, output selection, and exit codes."""
import json
import subprocess
import sys
import unittest

from support import FIXTURES, NEVA, REPO, TreeCase


def shield(*arguments):
    return subprocess.run([sys.executable, str(NEVA), "shield"] + list(arguments),
                          text=True, capture_output=True, check=False, cwd=str(REPO))


class ExitCodes(unittest.TestCase):
    def test_high_findings_fail_the_default_threshold(self):
        done = shield("--path", str(FIXTURES / "permissions" / "positive"))
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)

    def test_a_clean_tree_passes(self):
        done = shield("--path", str(FIXTURES / "clean" / "repository"))
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("grade A", done.stdout)

    def test_this_repository_passes_the_ci_gate(self):
        done = shield("--path", str(REPO), "--fail-on", "high")
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)


class Thresholds(TreeCase):
    def setUp(self):
        super().setUp()
        self.write(".mcp.json", '{"mcpServers": {"a": {"command": "npx", "args": ["a-mcp@latest"]}}}')

    def test_a_medium_only_tree_passes_at_high_and_fails_at_medium(self):
        self.assertEqual(0, shield("--path", str(self.root), "--fail-on", "high").returncode)
        self.assertEqual(1, shield("--path", str(self.root), "--fail-on", "medium").returncode)


class Arguments(unittest.TestCase):
    def test_a_missing_path_names_the_problem_and_exits_2(self):
        done = shield("--path", "/no/such/directory")
        self.assertEqual(2, done.returncode)
        self.assertIn("--path must name an existing directory", done.stderr)

    def test_machine_and_path_together_are_refused(self):
        done = shield("--machine", "--path", str(REPO))
        self.assertEqual(2, done.returncode)
        self.assertIn("mutually exclusive", done.stderr)

    def test_an_unknown_format_is_refused_by_the_parser(self):
        done = shield("--path", str(REPO), "--format", "yaml")
        self.assertEqual(2, done.returncode)
        self.assertIn("--format", done.stderr)


class Formats(unittest.TestCase):
    def test_json_output_parses(self):
        done = shield("--path", str(FIXTURES / "permissions" / "positive"), "--format", "json")
        self.assertEqual("F", json.loads(done.stdout)["grade"])

    def test_sarif_output_parses(self):
        done = shield("--path", str(FIXTURES / "permissions" / "positive"), "--format", "sarif")
        self.assertEqual("2.1.0", json.loads(done.stdout)["version"])


class OutFile(TreeCase):
    def test_out_writes_the_report_and_keeps_the_exit_code(self):
        self.write(".claude/settings.json", '{"permissions": {"allow": ["Bash(*)"]}}')
        target = self.root / "shield.sarif"
        done = shield("--path", str(self.root),
                      "--format", "sarif", "--out", str(target))
        self.assertEqual(1, done.returncode, done.stderr)
        self.assertEqual("2.1.0", json.loads(target.read_text(encoding="utf-8"))["version"])
        self.assertEqual("", done.stdout.strip())

    def test_out_rejects_symlink_leaf_parent_escape_and_config_collision(self):
        owner = self.write("owner.txt", "owner content")
        (self.root / "linked.txt").symlink_to(owner)
        config = self.write(".claude/settings.json", "{}")
        scanroot = self.root / "scan"
        scanroot.mkdir()
        for target, root in ((self.root / "linked.txt", self.root),
                             (owner, scanroot), (config, self.root)):
            with self.subTest(target=target):
                before = owner.read_bytes(), config.read_bytes()
                done = shield("--path", str(root), "--out", str(target))
                self.assertEqual(2, done.returncode, done.stderr)
                self.assertIn("--out could not be written", done.stderr)
                self.assertEqual("", done.stdout)
                self.assertEqual(before, (owner.read_bytes(), config.read_bytes()))

    def test_report_parent_symlink_is_rejected(self):
        from neva_cli.commands.shield import _write_report
        real = self.root / "real"
        real.mkdir()
        (self.root / "linked-dir").symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            _write_report(str(self.root / "linked-dir/report.txt"), self.root, "replacement")
        self.assertEqual([], list(real.iterdir()))

    def test_report_creation_rejects_a_symlink_inserted_after_validation(self):
        import os
        from unittest.mock import patch
        from neva_cli.commands.shield import _write_report
        owner = self.write("owner.txt", "owner content")
        target = self.root / "report.txt"
        original = os.open

        def raced_open(path, flags, *args, **kwargs):
            if path == target.name and flags & os.O_CREAT:
                target.symlink_to(owner)
            return original(path, flags, *args, **kwargs)

        with patch("neva_cli.commands.shield.os.open", side_effect=raced_open):
            with self.assertRaises(OSError):
                _write_report(str(target), self.root, "replacement")
        self.assertEqual("owner content", owner.read_text())

    def test_an_unwritable_out_path_names_the_problem(self):
        done = shield("--path", str(FIXTURES / "clean" / "repository"),
                      "--out", str(self.root / "missing" / "report.txt"))
        self.assertEqual(2, done.returncode)
        self.assertIn("--out could not be written", done.stderr)


class IncompleteScan(TreeCase):
    def test_malformed_settings_exit_with_error_and_no_clean_report(self):
        self.write(".claude/settings.json", '{"permissions": {"allow": [')
        done = shield("--path", str(self.root))
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertIn("settings.json", done.stderr)
        self.assertIn("repair", done.stderr)
        self.assertEqual("", done.stdout)


class InvalidMcpTransport(TreeCase):
    def test_non_string_remote_url_blocks_instead_of_reporting_clean(self):
        for filename, table in ((".mcp.json", "mcpServers"),
                                (".codex/config.toml", "mcp_servers")):
            for field in ("url", "endpoint", "serverUrl", "httpUrl", "sse_url"):
                with self.subTest(filename=filename, field=field):
                    if filename.endswith("toml"):
                        content = '[' + table + '.remote]\n' + field + ' = ["http://remote.example.com/mcp"]\n'
                    else:
                        content = json.dumps({table: {"remote": {
                            field: ["http://remote.example.com/mcp"]}}})
                    config = self.write(filename, content)
                    done = shield("--path", str(self.root))
                    self.assertEqual(2, done.returncode, done.stdout + done.stderr)
                    self.assertEqual("", done.stdout)
                    self.assertIn(config.name, done.stderr)
                    self.assertIn(table + ".<server>." + field, done.stderr)
                    self.assertIn("expected a string", done.stderr)
                    self.assertIn("repair", done.stderr)
                    self.write(filename, '{}' if filename.endswith("json") else '')



class Registration(unittest.TestCase):
    def test_shield_is_listed_in_neva_help(self):
        done = subprocess.run([sys.executable, str(NEVA), "--help"], text=True, capture_output=True, check=False)
        self.assertIn("shield", done.stdout)


if __name__ == "__main__":
    unittest.main()
