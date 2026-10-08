# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""neva install: the Claude Code path, the adapter contract path, and the gates on both."""
import json
import os
import unittest
from pathlib import Path

from neva_cli import core
from neva_cli.commands import install
from neva_cli.tests.harness import Sandbox

SETTINGS = Path(".claude") / "settings.json"


def adapter(**overrides):
    """A fixture contract exercising all five modes. Every path stays inside the sandbox HOME."""
    contract = {
        "harness": "codex",
        "detect": {"binaries": ["codex"], "paths": ["~/.codex"]},
        "entries": [
            {"src": "AGENTS.md", "dest": "~/.codex/AGENTS.md", "mode": "copy"},
            {"src": "prompt.md", "dest": "~/.codex/prompts/neva.md", "mode": "symlink"},
            {"src": "settings.json", "dest": "~/.codex/settings.json",
             "mode": "merge-json", "key": "neva.profile"},
            {"src": "config.toml", "dest": "~/.codex/config.toml",
             "mode": "merge-toml", "key": "tool.neva"},
            {"src": "block.sh", "dest": "~/.profile", "mode": "append-block", "key": "codex"},
        ],
        "post": ["codex auth login"],
    }
    contract.update(overrides)
    return contract


SOURCES = {
    "AGENTS.md": "# Neva for codex\nGround every answer in the vault.\n",
    "prompt.md": "Ask for the note, not the memory.\n",
    "settings.json": json.dumps({"neva": {"profile": "standard"}}) + "\n",
    "config.toml": "[tool.neva]\nprofile = \"standard\"\nhooks = true\n",
    "block.sh": 'export NEVA_VAULT="$HOME/vault"\n',
}


class TestPluginSelection(Sandbox):
    def test_core_is_always_included_and_duplicates_collapse(self):
        self.assertEqual(install.plugins("web"), ["core", "web"])
        self.assertEqual(install.plugins("core,web,web"), ["core", "web"])
        self.assertEqual(install.plugins("neva-web, neva-ops"), ["core", "web", "ops"])
        self.assertEqual(install.plugins(""), ["core"])

    def test_an_unknown_plugin_is_named_and_skipped_without_losing_the_install(self):
        code, output = self.install(harness="claude", plugins="core,web,nonsuch")
        self.assertEqual(code, 0)
        self.assertIn("unknown plugin 'nonsuch', skipped", output)
        self.assertIn("fix: use any of", output)
        env = core.lookup(json.loads((self.home / SETTINGS).read_text(encoding="utf-8")), "env")
        self.assertEqual(env["NEVA_PLUGINS"], "core,web")
        self.assertTrue((self.home / ".claude" / "rules" / "neva" / "typescript").is_dir())


class TestClaudeInstall(Sandbox):
    def test_rules_land_under_claude_rules_neva(self):
        code, _ = self.install(harness="claude", plugins="core")
        self.assertEqual(code, 0)
        common = self.home / ".claude" / "rules" / "neva" / "common"
        self.assertTrue(common.is_dir())
        self.assertTrue(list(common.glob("*.md")), "no rules were copied")

    def test_language_packs_follow_the_enabled_plugins_only(self):
        self.install(harness="claude", plugins="core,web")
        rules = self.home / ".claude" / "rules" / "neva"
        self.assertTrue((rules / "typescript").is_dir(), "neva-web language pack missing")
        self.assertFalse((rules / "flutter").exists(), "a pack from a plugin that is off was copied")

    def test_env_is_merged_without_disturbing_other_settings_keys(self):
        settings = self.home / SETTINGS
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"model": "opus", "env": {"MY_OWN": "keep"}}), encoding="utf-8")
        self.install(harness="claude", plugins="core,web", profile="strict")
        written = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(written["model"], "opus")
        self.assertEqual(written["env"]["MY_OWN"], "keep")
        self.assertEqual(written["env"]["NEVA_HOOK_PROFILE"], "strict")
        self.assertEqual(written["env"]["NEVA_PLUGINS"], "core,web")
        self.assertEqual(written["env"]["NEVA_CLAUDE_BIN"], str(self.binroot / "claude"))

    def test_the_marketplace_and_each_plugin_go_through_the_claude_cli(self):
        self.install(harness="claude", plugins="core,ops")
        # Read-only list queries come first; they decide what this run may claim as its own.
        argv = [" ".join(call["argv"]) for call in self.recorded()
                if call["binary"] == "claude" and "--json" not in call["argv"]]
        self.assertEqual(argv[0], "plugin marketplace add " + str(core.REPO_ROOT))
        self.assertIn("plugin install neva-core@neva", argv)
        self.assertIn("plugin install neva-ops@neva", argv)

    def test_without_the_claude_cli_the_commands_are_printed_and_the_install_still_succeeds(self):
        self.hide("claude")
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0)
        self.assertIn("CLI not on PATH", output)
        self.assertIn("plugin marketplace add", output)
        self.assertNotIn("NEVA_CLAUDE_BIN", json.dumps(core.load_state()))

    def test_a_failing_claude_cli_is_reported_as_a_failure_with_its_error(self):
        self.stub("claude", code=3, stderr="marketplace already exists\n")
        code, output = self.install(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("marketplace already exists", output)
        self.assertIn("fix:", output)

    def test_settings_json_that_is_not_an_object_is_refused_by_name(self):
        settings = self.home / SETTINGS
        settings.parent.mkdir(parents=True)
        settings.write_text("[1, 2, 3]", encoding="utf-8")
        code, output = self.install(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("must hold a JSON object", output)
        self.assertIn("fix:", output)


class TestAdapterInstall(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", adapter(), SOURCES)

    def test_every_mode_lands_where_the_contract_says(self):
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        codex = self.home / ".codex"
        self.assertEqual((codex / "AGENTS.md").read_text(encoding="utf-8"), SOURCES["AGENTS.md"])
        self.assertTrue((codex / "prompts" / "neva.md").is_symlink())
        self.assertEqual(json.loads((codex / "settings.json").read_text(encoding="utf-8")),
                         {"neva": {"profile": "standard"}})
        self.assertEqual(core.read_toml(codex / "config.toml"),
                         {"tool": {"neva": {"profile": "standard", "hooks": True}}})
        profile = (self.home / ".profile").read_text(encoding="utf-8")
        self.assertIn("# neva begin codex", profile)
        self.assertIn('export NEVA_VAULT="$HOME/vault"', profile)
        self.assertIn("# neva end codex", profile)

    def test_post_commands_are_printed_and_never_run(self):
        _, output = self.install(harness="codex")
        self.assertIn("run this yourself: codex auth login", output)
        self.assertEqual([call for call in self.recorded() if call["binary"] == "codex"], [])

    def test_the_manifest_records_every_entry_with_a_checksum(self):
        self.install(harness="codex")
        entries = self.entries("codex")
        self.assertEqual(len(entries), 5)
        self.assertEqual({entry["kind"] for entry in entries},
                         {"copy", "symlink", "merge-json", "merge-toml", "append-block"})
        for entry in entries:
            self.assertTrue(entry["checksum"], entry["dest"])
            self.assertEqual(core.entry_checksum(entry), entry["checksum"], entry["dest"])

    def test_a_second_install_is_idempotent(self):
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        first = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, "a re-install over Neva's own symlink failed:\n" + output)
        self.assertHomeUnchanged(first, "re-running install changed the machine:")
        self.assertEqual(len(self.entries("codex")), 5)

    def test_an_existing_file_is_backed_up_before_it_is_replaced(self):
        target = self.home / ".codex" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("mine, written by the user\n", encoding="utf-8")
        self.install(harness="codex")
        entry = next(item for item in self.entries("codex") if item["dest"] == str(target))
        self.assertTrue(entry["backup"], "no backup recorded for a file that already existed")
        self.assertEqual(Path(entry["backup"]).read_text(encoding="utf-8"), "mine, written by the user\n")
        self.assertTrue(entry["existed"])

    def test_a_missing_adapter_skips_that_harness_with_a_specific_message(self):
        code, output = self.install(harness="opencode")
        self.assertEqual(code, 0)
        self.assertIn("no adapter contract at", output)
        self.assertIn("opencode", output)
        self.assertNotIn("opencode", core.load_state()["harnesses"])

    def test_a_broken_adapter_is_reported_and_nothing_else_is_abandoned(self):
        self.write_adapter("opencode", {"harness": "opencode",
                                        "entries": [{"src": "x", "dest": "~/x", "mode": "beam"}]})
        code, output = self.install(harness="all")
        self.assertEqual(code, 1)
        self.assertIn("beam", output)
        self.assertEqual(len(self.entries("codex")), 5, "a broken adapter stopped a good one")

    def test_a_contract_that_escapes_home_is_refused_before_any_write(self):
        self.write_adapter("cursor", {"harness": "cursor",
                                      "entries": [{"src": "AGENTS.md", "dest": "~/../../etc/passwd",
                                                   "mode": "copy"}]})
        code, output = self.install(harness="cursor")
        self.assertEqual(code, 1)
        self.assertIn("resolves outside HOME", output)

    def test_an_instruction_only_harness_needs_no_binary_at_all(self):
        self.write_adapter("notebook", {
            "harness": "notebook",
            "detect": {"paths": ["~/.notebook"]},
            "entries": [{"src": "AGENTS.md", "dest": "~/.notebook/NEVA.md", "mode": "copy"}],
        }, {"AGENTS.md": SOURCES["AGENTS.md"]})
        code, output = self.install(harness="notebook")
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / ".notebook" / "NEVA.md").is_file())
        self.assertIn("notebook", install.all_harnesses())


class TestGates(Sandbox):
    def test_dry_run_writes_absolutely_nothing(self):
        self.write_adapter("codex", adapter(), SOURCES)
        before = self.snapshot_home()
        code, output = self.install(harness="codex", dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("would manage 5 entries", output)
        self.assertHomeUnchanged(before, "dry run wrote to HOME:")
        self.assertFalse(core.state_path().exists(), "dry run wrote an install-state manifest")

    def test_a_non_interactive_run_without_yes_is_refused_by_flag_name(self):
        code, output = self.install(harness="claude", yes=False)
        self.assertEqual(code, 64)
        self.assertIn("--yes", output)
        self.assertFalse((self.home / ".claude").exists())

    def test_negative_control_the_gate_can_be_passed(self):
        # Proves the check above fails for the right reason: the same call with --yes installs.
        code, _ = self.install(harness="claude", yes=True)
        self.assertEqual(code, 0)
        self.assertTrue((self.home / ".claude").exists())


class TestList(Sandbox):
    def test_detected_installed_and_plugins_are_all_reported(self):
        self.write_adapter("codex", adapter(), SOURCES)
        self.install(harness="codex", plugins="core,web")
        _, output = self.list()
        line = next(row for row in output.splitlines() if row.startswith("codex:"))
        self.assertIn("detected=yes", line)
        self.assertIn("installed=yes", line)
        self.assertIn("plugins=core,web", line)
        self.assertIn("entries=5", line)

    def test_a_harness_with_no_adapter_says_so(self):
        _, output = self.list()
        line = next(row for row in output.splitlines() if row.startswith("gemini:"))
        self.assertIn("installed=no", line)
        self.assertIn("no adapter at", line)

    def test_installed_only_hides_the_rest(self):
        self.install(harness="claude")
        _, output = self.list(installed=True)
        self.assertEqual(output.strip().splitlines()[0].split(":")[0], "claude")
        self.assertNotIn("gemini:", output)


if __name__ == "__main__":
    unittest.main()
