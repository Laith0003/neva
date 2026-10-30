"""Package launcher controls exercise every explicit install operand."""
import json

from support import TreeCase


class PackageLaunchers(TreeCase):
    def test_multiple_packages_in_json_and_toml(self):
        for fmt in ("json", "toml"):
            for command, flags in (("npx", ("-p", "-p")), ("npx", ("--package=", "--package=")),
                                   ("npm", ("--package=", "--package=")),
                                   ("uvx", ("--from=", "--with=")),
                                   ("uvx", ("--from", "--with")),
                                   ("uvx", ("--from", "-w")),
                                   ("uvx", ("--from=", "-w=")),
                                   ("uv", ("--from", "-w"))):
                for second, unsafe in (("unsafe@latest", True), ("safe-too@2.3.4", False)):
                    with self.subTest(format=fmt, command=command, flags=flags, second=second):
                        specs = ("safe@1.2.3", second)
                        if command in {"uv", "uvx"}:
                            specs = ("safe==1.2.3", "unsafe" if unsafe else "safe-too==2.3.4")
                        args = ["exec"] if command == "npm" else ["tool", "run"] if command == "uv" else []
                        for flag, spec in zip(flags, specs):
                            args.extend([flag + spec] if flag.endswith("=") else [flag, spec])
                        args.append("tool")
                        if fmt == "json":
                            self.write(".mcp.json", json.dumps({"mcpServers": {"a": {"command": command, "args": args}}}))
                        else:
                            self.write(".codex/config.toml", '[mcp_servers.a]\ncommand = ' + json.dumps(command) + '\nargs = ' + json.dumps(args) + '\n')
                        findings = [item for item in self.scan().findings if item.rule_id == "MCP001"]
                        self.assertEqual(1 if unsafe else 0, len(findings), findings)
                        if unsafe:
                            self.assertIn(specs[1], findings[0].message)

    def test_launcher_option_values_are_not_packages(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"a": {
            "command": "npx", "args": ["--registry", "https://registry.example.com", "safe@1.2.3"]}}}))
        self.assertNotIn("MCP001", self.ids(self.scan()))

    def test_dependency_option_keeps_implicit_uvx_package(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"a": {
            "command": "uvx", "args": ["--with=safe==1.2.3", "unsafe"]}}}))
        findings = [item for item in self.scan().findings if item.rule_id == "MCP001"]
        self.assertEqual(1, len(findings))
        self.assertIn("unsafe", findings[0].message)

    def test_application_package_flags_do_not_select_launcher_packages(self):
        for command, package in (("npx", "safe@1.2.3"), ("uvx", "safe==1.2.3")):
            with self.subTest(command=command):
                self.write(".mcp.json", json.dumps({"mcpServers": {"a": {
                    "command": command,
                    "args": [package, "--package", "application-data", "--with", "application-data"]}}}))
                self.assertNotIn("MCP001", self.ids(self.scan()))

    def test_application_flags_cannot_hide_unpinned_launcher_package(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"a": {
            "command": "npx", "args": ["unsafe", "--package", "safe@1.2.3"]}}}))
        findings = [item for item in self.scan().findings if item.rule_id == "MCP001"]
        self.assertEqual(1, len(findings), findings)
        self.assertIn("launches unsafe without", findings[0].message)

    def test_npm_exec_parses_package_options_after_positionals(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"a": {
            "command": "npm", "args": ["exec", "safe@1.2.3", "--package=unsafe"]}}}))
        findings = [item for item in self.scan().findings if item.rule_id == "MCP001"]
        self.assertEqual(1, len(findings), findings)
        self.assertIn("launches unsafe without", findings[0].message)
