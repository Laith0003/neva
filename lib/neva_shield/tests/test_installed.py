"""Run the actual installer and installed CLI from outside the source tree."""
import json
import os
import subprocess
import sys

from support import GITHUB_TOKEN, INLINE_SECRET, REPO, TreeCase


class InstalledLayout(TreeCase):
    def test_installed_entry_point_preserves_security_checks(self):
        home = self.root / "home"
        home.mkdir()
        env = {
            "PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(self.root),
            "OWNER_NAME": "Test Buyer", "AGENT_NAME": "Vera", "TIMEZONE": "UTC",
            "VAULT_PATH": str(home / "Vault"), "WORKSPACE_PATH": str(home / "workspace"),
            "NEVA_NONINTERACTIVE": "1", "NEVA_SKIP_SCHEDULE_ENABLE": "1",
            "NEVA_PLUGINS": "core", "PYTHONDONTWRITEBYTECODE": "1",
        }
        installed = subprocess.run(["bash", str(REPO / "install.sh")], cwd=self.root,
                                   env=env, text=True, capture_output=True, check=False)
        self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
        self.assertIn("tools installed", installed.stdout)
        entry = home / ".local/neva/bin/neva"
        self.assertTrue(entry.is_file())
        scan = self.root / "scan"
        config = self.write("scan/.claude/settings.json", json.dumps({"permissions": {
            "allow": ["Bash(python -c 'print(" + GITHUB_TOKEN + ")')"]}}))

        def run(*args):
            return subprocess.run([sys.executable, str(entry), "shield", "--path", str(scan), *args],
                                  cwd=self.root, env=env, text=True, capture_output=True, check=False)

        for fmt in ("text", "json", "sarif"):
            done = run("--format", fmt)
            self.assertEqual(1, done.returncode, done.stderr)
            self.assertIn("PERM001", done.stdout)
            self.assertIn("SECRET001", done.stdout)
            self.assertNotIn(GITHUB_TOKEN, done.stdout + done.stderr)
        owner = self.write("scan/owner.txt", "owner content")
        link = scan / "report.txt"
        link.symlink_to(owner)
        done = run("--out", str(link))
        self.assertEqual(2, done.returncode)
        self.assertIn("--out could not be written", done.stderr)
        self.assertEqual("", done.stdout)
        self.assertEqual("owner content", owner.read_text())
        config.write_text('{"permissions": {"allow": [')
        done = run()
        self.assertEqual(2, done.returncode)
        self.assertIn("settings.json", done.stderr)
        self.assertIn("repair", done.stderr)
        self.assertEqual("", done.stdout)
        config.write_text("{}")
        self.write("scan/.codex/config.toml", '[mcp_servers.remote]\nurl = "http://remote.example.com/mcp"\n')
        done = run()
        self.assertEqual(1, done.returncode, done.stderr)
        self.assertIn("MCP002", done.stdout)

        for package, flagged in (("safe@1.2.3", False), ("unsafe", True)):
            self.write("scan/.mcp.json", json.dumps({"mcpServers": {"launcher": {
                "command": "npx", "args": [package, "--package", "safe@1.2.3"]}}}))
            done = run("--format", "json")
            self.assertEqual(1, done.returncode, done.stderr)  # Existing remote transport finding.
            self.assertEqual("", done.stderr)
            findings = json.loads(done.stdout)["findings"]
            package_findings = [item for item in findings if item["rule_id"] == "MCP001"]
            self.assertEqual(1 if flagged else 0, len(package_findings), done.stdout)

        for scheme in ("Bearer", "Basic"):
            self.write("scan/.mcp.json", json.dumps({"mcpServers": {INLINE_SECRET: {
                "url": "http://remote.example.com/mcp",
                "headers": {"Authorization": scheme + " " + INLINE_SECRET}}}}))
            for fmt in ("text", "json", "sarif"):
                done = run("--format", fmt)
                self.assertEqual(1, done.returncode, done.stderr)
                self.assertIn("MCP002", done.stdout)
                self.assertNotIn(INLINE_SECRET, done.stdout + done.stderr)
        self.write("scan/.mcp.json", json.dumps({"mcpServers": {INLINE_SECRET: {
            "args": 42, "env": {"API_KEY": INLINE_SECRET}}}}))
        done = run()
        self.assertEqual(2, done.returncode)
        self.assertEqual("", done.stdout)
        self.assertIn("repair", done.stderr)
        self.assertNotIn(INLINE_SECRET, done.stderr)
        self.write("scan/.mcp.json", '{"' + INLINE_SECRET + '": [')
        done = run()
        self.assertEqual(2, done.returncode)
        self.assertEqual("", done.stdout)
        self.assertIn("repair", done.stderr)
        self.assertNotIn(INLINE_SECRET, done.stderr)
        self.write("scan/.mcp.json", "{}")
        config.resolve().relative_to(self.root.resolve())
        self.assertFalse(any(part.is_symlink() for part in (config, *config.parents)))
        config.unlink()
        config.symlink_to(owner)
        done = run()
        self.assertEqual(2, done.returncode)
        self.assertEqual("", done.stdout)
        self.assertIn("settings.json", done.stderr)
        self.assertIn("restore a regular", done.stderr)
        self.assertEqual("owner content", owner.read_text())
