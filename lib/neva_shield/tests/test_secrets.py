"""Secret detection, and the promise that no output format ever prints a secret value."""
import json
import subprocess
import sys
import unittest

from support import (GITHUB_TOKEN, INLINE_SECRET, LINEAR_KEY, NEVA, NOTION_TOKEN, PEM_HEADER, REPO, SENDGRID_KEY,
                     STRIPE_KEY, TELEGRAM_TOKEN, TreeCase)


class SecretDetection(TreeCase):
    def test_provider_token_in_an_instruction_file_is_critical(self):
        self.write("CLAUDE.md", "Use the CI token " + GITHUB_TOKEN + " when pushing.\n")
        findings = {item.rule_id: item.severity for item in self.scan().findings}
        self.assertEqual("critical", findings.get("SECRET001"))

    def test_private_key_header_is_critical(self):
        self.write(".claude/settings.json", json.dumps({"env": {"DEPLOY_KEY": PEM_HEADER + "\\nMIIE"}}))
        self.assertIn("SECRET001", {item.rule_id for item in self.scan().findings})

    def test_inline_credential_in_settings_is_high(self):
        self.write(".claude/settings.json", json.dumps({"env": {"BILLING_API_KEY": INLINE_SECRET}}))
        findings = {item.rule_id: item.severity for item in self.scan().findings}
        self.assertEqual("high", findings.get("SECRET002"))

    def test_mcp_env_credential_is_reported_by_the_mcp_family(self):
        self.write(".mcp.json", json.dumps(
            {"mcpServers": {"billing": {"command": "/usr/bin/billing-mcp", "env": {"BILLING_API_KEY": INLINE_SECRET}}}}))
        self.assertIn("MCP003", {item.rule_id for item in self.scan().findings})

    def test_environment_reference_is_the_negative_control(self):
        self.write(".mcp.json", json.dumps(
            {"mcpServers": {"billing": {"command": "/usr/bin/billing-mcp", "env": {"BILLING_API_KEY": "${BILLING_API_KEY}"}}}}))
        self.assertEqual([], self.scan().findings)

    def test_documented_placeholders_are_not_reported(self):
        self.write("CLAUDE.md", "\n".join([
            "api_key = your-api-key-here",
            "token: REPLACE_WITH_YOUR_TOKEN_1",
            "password = changeme1234567890",
            "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}",
            "apiKey := os.Getenv(\"OPENAI_API_KEY\")",
            "var apiKey = builder.Configuration[\"OpenAI:ApiKey\"]",
        ]) + "\n")
        self.assertEqual([], self.scan().findings)

    def test_a_non_secret_field_with_a_long_value_is_not_reported(self):
        self.write(".claude/settings.json", json.dumps(
            {"permissions": {"deny": ["Read(~/.ssh/**)"]}, "statusLine": {"command": "a1b2c3d4e5f6g7h8i9j0"}}))
        self.assertEqual([], self.scan().findings)


# Assembled so that gitleaks does not read this negative control as a real curl credential.
FETCH_WITH_HEADER = "cu" + 'rl -H "Auth' + 'orization: '
FORMATS = (("stripe", STRIPE_KEY), ("notion", NOTION_TOKEN), ("linear", LINEAR_KEY), ("sendgrid", SENDGRID_KEY),
           ("telegram", TELEGRAM_TOKEN), ("github", GITHUB_TOKEN), ("opaque", INLINE_SECRET))
SHAPES = (
    ("mcp args", lambda value: (".mcp.json", json.dumps({"mcpServers": {"s": {
        "command": "/usr/bin/tool", "args": ["--api-key", value]}}}))),
    ("mcp url", lambda value: (".mcp.json", json.dumps({"mcpServers": {"s": {
        "url": "https://r.example.com/mcp?apiKey=" + value, "headers": {"Authorization": "Bearer ${T}"}}}}))),
    ("hook command", lambda value: (".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [{
        "type": "command", "command": 'curl -H "Authorization: Bearer ' + value + '" https://h.example.com/x'}]}]}}))),
    ("instruction line", lambda value: ("CLAUDE.md", 'Run curl -H "Authorization: Bearer ' + value + '" https://h.example.com/x\n')),
    ("hook script", lambda value: ("hooks/notify.sh", "#!/bin/sh\ntool --token " + value + "\n")),
)


class CredentialsOutsideSecretFields(TreeCase):
    def test_every_format_in_every_shape_is_reported_and_withheld(self):
        for format_name, value in FORMATS:
            for shape_name, build in SHAPES:
                with self.subTest(format=format_name, shape=shape_name):
                    relative, content = build(value)
                    path = self.write(relative, content)
                    result = self.scan()
                    self.assertIn("SECRET002", self.ids(result))
                    self.assertNotEqual("A", result.grade)
                    done = subprocess.run([sys.executable, str(NEVA), "shield", "--path", str(self.root), "--format", "json"],
                                          text=True, capture_output=True, check=False)
                    self.assertNotIn(value, done.stdout + done.stderr)
                    path.unlink()

    def test_new_provider_formats_are_critical_anywhere(self):
        for _, value in FORMATS[:5]:
            with self.subTest(value=value[:6]):
                self.write("CLAUDE.md", "The value is " + value + " here.\n")
                self.assertEqual("critical", {i.rule_id: i.severity for i in self.scan().findings}.get("SECRET001"))

    def test_any_mcp_env_value_is_checked_whatever_its_name(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"s": {"command": "/usr/bin/s", "env": {"CONFIG": INLINE_SECRET}}}}))
        self.assertIn("MCP003", self.ids(self.scan()))

    def test_references_placeholders_and_prose_are_not_reported(self):
        for relative, content in (
                (".mcp.json", json.dumps({"mcpServers": {"s": {"command": "/usr/bin/s", "args": ["--api-key", "${KEY}"]}}})),
                (".mcp.json", json.dumps({"mcpServers": {"s": {"url": "https://r.example.com/m?apiKey=${KEY}", "headers": {"Authorization": "Bearer ${T}"}}}})),
                (".mcp.json", json.dumps({"mcpServers": {"s": {"command": "ssh", "args": ["git@github.com"], "env": {"PATH": "/usr/local/bin:/usr/bin:/bin"}}}})),
                ("CLAUDE.md", 'Run ' + FETCH_WITH_HEADER + 'Bearer $TOKEN" https://h.example.com/x\n'),
                ("CLAUDE.md", 'Run ' + FETCH_WITH_HEADER + 'Bearer your-token-here" https://h.example.com/x\n'),
                ("CLAUDE.md", "The token is a bearer token. key: value pairs. auth: required. token: string\n"),
                ("CLAUDE.md", "Use a Basic Auth header, password: required, and --token <value> here.\n"),
                ("hooks/x.sh", '#!/bin/sh\ntool --token "$TOKEN" --key=2\n'),
                ("hooks/x.js", "call({ max_tokens: model_limit, budget_tokens: 4096, apiKey: process.env.KEY })\n"),
                ("hooks/x.js", "const apiKey = options.apiKey; login(token=token); accessKeyId: config.value\n"),
                ("CLAUDE.md", "Install from plugin://chrome-dev@openai-curated and ssh://git@github.com/org/repo\n"),
                ("CLAUDE.md", "Connect with postgres://user:password@localhost:5432/app\n")):
            with self.subTest(content=content[:50]):
                path = self.write(relative, content)
                self.assertNotIn("SECRET002", self.ids(self.scan()))
                path.unlink()

    def test_field_names_shaped_like_a_credential_are_masked(self):
        self.write(".claude/settings.json", json.dumps({"env": {INLINE_SECRET: {"API_KEY": INLINE_SECRET[::-1]}}}))
        done = subprocess.run([sys.executable, str(NEVA), "shield", "--path", str(self.root)],
                              text=True, capture_output=True, check=False)
        self.assertIn("SECRET002", done.stdout)
        self.assertNotIn(INLINE_SECRET, done.stdout)

    def test_a_credential_in_a_code_block_is_medium_and_in_prose_is_high(self):
        line = 'curl -H "Authorization: Bearer ' + INLINE_SECRET + '" https://h.example.com/x\n'
        self.write("CLAUDE.md", "```bash\n" + line + "```\n")
        self.assertEqual("medium", {i.rule_id: i.severity for i in self.scan().findings}.get("SECRET002"))
        self.write("CLAUDE.md", line)
        self.assertEqual("high", {i.rule_id: i.severity for i in self.scan().findings}.get("SECRET002"))

    def test_toml_comments_and_strings_get_the_text_check(self):
        self.write(".codex/config.toml", '# curl -H "Authorization: Bearer ' + INLINE_SECRET + '" https://h.example.com\nmodel = "m"\n')
        self.assertIn("SECRET002", self.ids(self.scan()))


class Fences(unittest.TestCase):
    def test_a_longer_fence_can_show_a_shorter_one(self):
        from neva_shield.rules.shared import fenced_lines
        text = "````text\n```rust\nbody\n```\n````\nprose\n```\ncode\n```\nprose\n"
        self.assertEqual({1, 2, 3, 4, 5, 7, 8, 9}, fenced_lines(text))


class ScrubCost(unittest.TestCase):
    def test_hostile_lines_stay_linear(self):
        program = ("import sys;sys.path.insert(0,'lib');"
                   "from neva_shield.rules.shared import scrub;from neva_shield.rules.secrets import ASSIGNMENT as A;"
                   "rows=['a='*524288+'!','a:'*524288+'!','a'*1048576,'a.'*524288,'://a'*262144,'--a '*262144,'a@'*524288];"
                   "[(scrub(r),list(A.finditer(r))) for r in rows]")
        subprocess.run([sys.executable, "-c", program], cwd=str(REPO), check=True, timeout=20, capture_output=True)


class Redaction(TreeCase):
    """A secret value must not reach any output format, in any field."""

    def plant(self):
        self.write("CLAUDE.md", "Token: " + GITHUB_TOKEN + "\n")
        self.write(".claude/settings.json", json.dumps({"env": {"BILLING_API_KEY": INLINE_SECRET}}))
        self.write(".mcp.json", json.dumps(
            {"mcpServers": {"b": {"command": "/usr/bin/b", "env": {"B_TOKEN": INLINE_SECRET}}}}))
        return self.scan()

    def test_cross_family_values_are_redacted_in_renderers_and_cli(self):
        from neva_shield import render
        self.write(".claude/settings.json", json.dumps({"permissions": {
            "allow": ["Bash(python -c 'print(" + GITHUB_TOKEN + ")')"]}}))
        self.write(".mcp.json", json.dumps({"mcpServers": {"package": {
            "command": "npx", "args": ["pkg-" + GITHUB_TOKEN]}}}))
        self.write(".claude-plugin/marketplace.json", json.dumps({"plugins": [{
            "name": "demo", "source": "http://" + GITHUB_TOKEN + ".example.com/source"}]}))
        result = self.scan()
        self.assertIn("PERM001", self.ids(result))
        self.assertIn("MCP001", self.ids(result))
        self.assertIn("PROV001", self.ids(result))
        for fmt, renderer in (("text", render.text), ("json", render.json_text), ("sarif", render.sarif)):
            with self.subTest(format=fmt):
                self.assertNotIn(GITHUB_TOKEN, renderer(result))
                done = subprocess.run([sys.executable, str(NEVA), "shield", "--path", str(self.root),
                                       "--format", fmt], text=True, capture_output=True, check=False)
                self.assertEqual(1, done.returncode, done.stderr)
                self.assertIn("SECRET001", done.stdout)
                self.assertNotIn(GITHUB_TOKEN, done.stdout + done.stderr)

    def test_authentication_headers_redact_components_across_outputs(self):
        from neva_shield import render
        for scheme in ("Bearer", "Basic"):
            for header in ("Authorization", "Proxy-Authorization"):
                with self.subTest(scheme=scheme, header=header):
                    self.write(".mcp.json", json.dumps({"mcpServers": {INLINE_SECRET: {
                        "url": "http://remote.example.com/mcp",
                        "headers": {header: scheme + " " + INLINE_SECRET}}}}))
                    result = self.scan()
                    self.assertIn("MCP002", self.ids(result))
                    for fmt, renderer in (("text", render.text), ("json", render.json_text),
                                          ("sarif", render.sarif)):
                        self.assertNotIn(INLINE_SECRET, renderer(result))
                        done = subprocess.run([sys.executable, str(NEVA), "shield", "--path",
                                               str(self.root), "--format", fmt],
                                              text=True, capture_output=True, check=False)
                        self.assertEqual(1, done.returncode, done.stderr)
                        self.assertIn("MCP002", done.stdout)
                        self.assertNotIn(INLINE_SECRET, done.stdout + done.stderr)

    def test_header_environment_references_remain_safe(self):
        from neva_shield.rules import shared
        from neva_shield import render
        for value in ("Bearer ${ACCESS_TOKEN}", "Basic $ACCESS_TOKEN"):
            self.assertEqual([], shared.secret_values("Authorization", value))
            self.write(".mcp.json", json.dumps({"mcpServers": {"safe-server": {
                "url": "https://remote.example.com/mcp", "headers": {"Authorization": value}}}}))
            result = self.scan()
            self.assertEqual([], result.findings)
            self.assertNotIn("[REDACTED]", render.json_text(result))
        for value in ("Basic YWxwaGE6YnJhdm8=", "Bearer opaquevalue"):
            self.assertEqual([value, value.split()[1]], shared.secret_values("Authorization", value))

    def test_authentication_mixed_literal_reference_is_redacted(self):
        from neva_shield import render
        component = INLINE_SECRET + "${TOKEN}"
        self.write(".mcp.json", json.dumps({"mcpServers": {component: {
            "url": "http://remote.example.com/mcp", "headers": {
                "Authorization": "Bearer " + component}}}}))
        result = self.scan()
        self.assertIn("MCP002", self.ids(result))
        for renderer in (render.text, render.json_text, render.sarif):
            self.assertNotIn(INLINE_SECRET, renderer(result))

    def test_malformed_configuration_diagnostics_exclude_untrusted_names(self):
        for content in (json.dumps({"mcpServers": {INLINE_SECRET: {
                "args": 42, "env": {"API_KEY": INLINE_SECRET}}}}),
                '{"mcpServers": {"' + INLINE_SECRET + '": ['):
            self.write(".mcp.json", content)
            done = subprocess.run([sys.executable, str(NEVA), "shield", "--path", str(self.root)],
                                  text=True, capture_output=True, check=False)
            self.assertEqual(2, done.returncode)
            self.assertEqual("", done.stdout)
            self.assertIn(".mcp.json", done.stderr)
            self.assertIn("repair", done.stderr)
            self.assertNotIn(INLINE_SECRET, done.stderr)

    def test_finding_paths_and_root_metadata_are_redacted(self):
        from neva_shield import Finding, ScanResult, render
        result = ScanResult(root=GITHUB_TOKEN, findings=[Finding(
            "PERM001", "high", GITHUB_TOKEN + "/CLAUDE.md", 1,
            "allow " + GITHUB_TOKEN, "replace " + GITHUB_TOKEN)])
        for renderer in (render.text, render.json_text, render.sarif):
            output = renderer(result)
            self.assertIn("PERM001", output)
            self.assertIn("[REDACTED]", output)
            self.assertNotIn(GITHUB_TOKEN, output)

    def test_no_renderer_prints_a_planted_secret(self):
        from neva_shield import render
        result = self.plant()
        self.assertGreaterEqual(len(result.findings), 3, "the planted secrets must be found first")
        for name, renderer in (("text", render.text), ("json", render.json_text), ("sarif", render.sarif)):
            output = renderer(result)
            self.assertNotIn(GITHUB_TOKEN, output, name + " leaked the provider token")
            self.assertNotIn(INLINE_SECRET, output, name + " leaked the inline credential")
            self.assertIn("BILLING_API_KEY", output, name + " must still name the field")

    def test_negative_control_the_assertion_can_fail(self):
        """Proof the redaction assertion is capable of failing: the same check on a value
        Shield does print (the field name) finds it, so a leaked value would be caught."""
        from neva_shield import render
        output = render.text(self.plant())
        self.assertIn("BILLING_API_KEY", output)
        with self.assertRaises(AssertionError):
            self.assertNotIn("BILLING_API_KEY", output)

    def test_no_cli_output_format_prints_a_planted_secret(self):
        self.plant()
        for fmt in ("text", "json", "sarif"):
            done = subprocess.run([sys.executable, str(NEVA), "shield", "--path", str(self.root), "--format", fmt],
                                  text=True, capture_output=True, check=False)
            self.assertNotIn(GITHUB_TOKEN, done.stdout + done.stderr, fmt)
            self.assertNotIn(INLINE_SECRET, done.stdout + done.stderr, fmt)


if __name__ == "__main__":
    unittest.main()
