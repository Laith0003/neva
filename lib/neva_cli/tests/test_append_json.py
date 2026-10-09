"""append-json: Neva's entries go in beside the owner's, and only Neva's ever come back out.

A shared array (Codex hooks per event, OpenCode instruction globs) belongs to the owner as much
as to Neva. Neva's entries are the ones whose JSON carries the neva-core marker. Install adds
them, a reinstall replaces only them, uninstall removes only them, and the owner's entries keep
their content and their place. Every case here also holds the CLI's usual rules: a path outside
HOME, a broken file or a wrong shape is refused by name and nothing is written.
"""
import json
import os
import unittest

from neva_cli import core
from neva_cli.tests.harness import Sandbox

NEVA_GROUP = {"matcher": "*", "hooks": [{"type": "command",
                                         "command": "python3 /opt/neva/plugins/neva-core/hooks/dispatch.py PreToolUse"}]}
NEVA_STOP = {"hooks": [{"type": "command", "command": "python3 /opt/neva/plugins/neva-core/hooks/dispatch.py Stop"}]}
OWNER_GROUP = {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "python3 /home/user/policy.py"}]}
OWNER_STOP = {"hooks": [{"type": "command", "command": "python3 /home/user/stop.py"}]}

HOOKS_SOURCE = {"hooks": {"PreToolUse": [NEVA_GROUP], "Stop": [NEVA_STOP]}}
GLOBS_SOURCE = {"instructions": [".opencode/rules/neva-core/*.md"]}

OWNER_HOOKS = ('{\n  "description": "owner hooks",\n  "hooks": {\n    "PreToolUse": [\n'
               '      {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "python3 /home/user/policy.py"}]}\n'
               '    ]\n  }\n}\n')
OWNER_OPENCODE = '{"model": "owner/model", "instructions": ["docs/owner-rules.md"]}\n'


def contract(harness, src, dest, key):
    return {"harness": harness, "entries": [{"src": src, "dest": dest, "mode": "append-json", "key": key}]}


class AppendJson(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", contract("codex", "hooks.json", "~/.codex/hooks.json", "hooks"),
                           {"hooks.json": json.dumps(HOOKS_SOURCE)})
        self.write_adapter("opencode", contract("opencode", "opencode.json", "~/proj/opencode.json",
                                                "instructions"),
                           {"opencode.json": json.dumps(GLOBS_SOURCE)})
        self.hooks = self.home / ".codex" / "hooks.json"
        self.opencode = self.home / "proj" / "opencode.json"

    def seed(self):
        self.hooks.parent.mkdir(parents=True, exist_ok=True)
        self.hooks.write_text(OWNER_HOOKS, encoding="utf-8")
        self.opencode.parent.mkdir(parents=True, exist_ok=True)
        self.opencode.write_text(OWNER_OPENCODE, encoding="utf-8")

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))


class TestContract(AppendJson):
    def test_read_adapter_accepts_append_json(self):
        loaded, _ = core.read_adapter("codex")
        self.assertEqual("append-json", loaded["entries"][0]["mode"])

    def test_an_append_json_entry_without_a_key_is_refused(self):
        self.write_adapter("bad", contract("bad", "x.json", "~/x.json", ""), {"x.json": "{}"})
        with self.assertRaises(core.AdapterError) as caught:
            core.read_adapter("bad")
        self.assertIn("key", str(caught.exception))


class TestInstallAndUninstall(AppendJson):
    def test_owner_entries_survive_two_installs_and_uninstall_restores_the_bytes(self):
        self.seed()
        before = self.snapshot_home()
        for run in (1, 2):
            code, output = self.install(harness="all")
            self.assertEqual(code, 0, output)
        hooks = self.read(self.hooks)
        self.assertEqual([OWNER_GROUP, NEVA_GROUP], hooks["hooks"]["PreToolUse"])
        self.assertEqual([NEVA_STOP], hooks["hooks"]["Stop"])
        self.assertEqual("owner hooks", hooks["description"])
        self.assertEqual(["docs/owner-rules.md", ".opencode/rules/neva-core/*.md"],
                         self.read(self.opencode)["instructions"])
        self.assertEqual("owner/model", self.read(self.opencode)["model"])
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "uninstall did not hand the owner's files back:")

    def test_a_second_install_changes_nothing(self):
        self.seed()
        self.install(harness="all")
        first = self.snapshot_home()
        code, output = self.install(harness="all")
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(first, "a reinstall changed the files:")

    def test_a_version_bump_replaces_the_entry_neva_wrote(self):
        """Neva's entry is the one it recorded writing, so a changed source replaces exactly that."""
        self.seed()
        self.install(harness="codex")
        bumped = {"matcher": "*", "hooks": [{"type": "command",
                                             "command": "python3 /opt/neva/plugins/neva-core/hooks/dispatch.py v2"}]}
        self.write_adapter("codex", contract("codex", "hooks.json", "~/.codex/hooks.json", "hooks"),
                           {"hooks.json": json.dumps({"hooks": {"PreToolUse": [bumped], "Stop": [NEVA_STOP]}})})
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertEqual([OWNER_GROUP, bumped], self.read(self.hooks)["hooks"]["PreToolUse"])

    def test_a_file_neva_created_is_removed_on_uninstall(self):
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertEqual(HOOKS_SOURCE["hooks"], self.read(self.hooks)["hooks"])
        self.uninstall()
        self.assertHomeUnchanged(before)

    def test_owner_edits_after_install_survive_uninstall(self):
        self.seed()
        self.install(harness="codex")
        data = self.read(self.hooks)
        data["hooks"]["Stop"].insert(0, OWNER_STOP)
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        hooks = self.read(self.hooks)["hooks"]
        self.assertEqual([OWNER_GROUP], hooks["PreToolUse"])
        self.assertEqual([OWNER_STOP], hooks["Stop"])
        self.assertNotIn("neva-core", self.hooks.read_text(encoding="utf-8"))

    def test_the_manifest_checksum_tracks_only_nevas_entries(self):
        self.seed()
        self.install(harness="codex")
        entry = self.entries("codex")[0]
        self.assertEqual("append-json", entry["kind"])
        self.assertEqual(entry["checksum"], core.entry_checksum(entry))
        data = self.read(self.hooks)
        data["hooks"]["PreToolUse"].insert(0, OWNER_STOP)
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(entry["checksum"], core.entry_checksum(entry), "an owner edit counted as Neva's")

    def test_repair_puts_back_a_removed_neva_entry_only(self):
        self.seed()
        self.install(harness="codex")
        data = self.read(self.hooks)
        data["hooks"]["PreToolUse"] = [OWNER_GROUP]
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertIn("repaired", output)
        self.assertEqual([OWNER_GROUP, NEVA_GROUP], self.read(self.hooks)["hooks"]["PreToolUse"])

    def test_dry_run_writes_nothing(self):
        self.seed()
        before = self.snapshot_home()
        code, output = self.install(harness="all", dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before)


class TestOwnershipByIdentity(AppendJson):
    """Only an entry Neva recorded writing is Neva's. Mentioning neva-core does not make it so."""

    def lifecycle(self, harness, path):
        """install, reinstall, repair, uninstall; the owner's original file must come back byte for byte."""
        original = path.read_bytes()
        before = self.snapshot_home()
        outputs = []
        for step in ("install", "reinstall"):
            code, output = self.install(harness=harness)
            self.assertEqual(code, 0, step + " failed:\n" + output)
            outputs.append(output)
            yield step
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertIn("nothing to repair", output, "repair did not settle:\n" + output)
        yield "repair"
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(original, path.read_bytes(), "uninstall did not hand the owner's file back")
        self.assertHomeUnchanged(before)
        self.reports = outputs

    def test_an_owner_hook_beside_a_hand_wired_neva_hook_survives(self):
        hand_wired = {"matcher": "*", "hooks": [
            {"type": "command", "command": "python3 /home/user/audit.py"},
            {"type": "command", "command": "python3 /home/user/neva/plugins/neva-core/hooks/dispatch.py PreToolUse"}]}
        self.hooks.parent.mkdir(parents=True)
        self.hooks.write_text(json.dumps({"hooks": {"PreToolUse": [hand_wired]}}, indent=2) + "\n", encoding="utf-8")
        for step in self.lifecycle("codex", self.hooks):
            pre = self.read(self.hooks)["hooks"]["PreToolUse"]
            self.assertEqual(hand_wired, pre[0], "the owner's group changed at " + step)
            self.assertEqual(1, pre.count(NEVA_GROUP), step)
        self.assertIn("hooks.PreToolUse[0]", self.reports[0], "the owner's marked entry was not named")

    def test_an_owner_glob_into_the_neva_checkout_survives(self):
        glob = "~/Code/neva/plugins/neva-core/rules/common/*.md"
        self.opencode.parent.mkdir(parents=True)
        self.opencode.write_text(json.dumps({"instructions": [glob]}) + "\n", encoding="utf-8")
        for step in self.lifecycle("opencode", self.opencode):
            self.assertEqual(glob, self.read(self.opencode)["instructions"][0], step)
        self.assertIn("instructions[0]", self.reports[0])

    def test_an_owner_array_the_source_never_covers_is_never_touched(self):
        self.write_adapter("codex", contract("codex", "hooks.json", "~/.codex/hooks.json", "hooks"),
                           {"hooks.json": json.dumps({"hooks": {"PreToolUse": [NEVA_GROUP]}})})
        owner_stop = {"c": "owner neva-core-notes stop"}
        self.hooks.parent.mkdir(parents=True)
        self.hooks.write_text(json.dumps({"hooks": {"Stop": [owner_stop]}}) + "\n", encoding="utf-8")
        for step in self.lifecycle("codex", self.hooks):
            self.assertEqual([owner_stop], self.read(self.hooks)["hooks"]["Stop"], step)

    def test_an_identical_entry_the_owner_already_had_stays_theirs(self):
        self.hooks.parent.mkdir(parents=True)
        self.hooks.write_text(json.dumps({"hooks": {"PreToolUse": [NEVA_GROUP]}}) + "\n", encoding="utf-8")
        for step in self.lifecycle("codex", self.hooks):
            self.assertEqual(1, self.read(self.hooks)["hooks"]["PreToolUse"].count(NEVA_GROUP), step)


class TestEditedNevaEntry(AppendJson):
    """An owner edit to an entry Neva wrote is the owner's work: refused by name, never discarded."""

    def edit_neva_group(self):
        data = self.read(self.hooks)
        group = data["hooks"]["PreToolUse"][1]
        group["hooks"].append({"type": "command", "command": "python3 /home/user/extra.py"})
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        return self.hooks.read_bytes()

    def test_uninstall_refuses_the_edited_entry_and_finishes_the_rest(self):
        self.seed()
        opencode_before = self.opencode.read_bytes()
        self.install(harness="all")
        edited = self.edit_neva_group()
        code, output = self.uninstall()
        self.assertEqual(1, code, output)
        self.assertIn("hooks.PreToolUse", output)
        self.assertIn("was edited after Neva installed it", output)
        self.assertEqual(edited, self.hooks.read_bytes(), "the owner's edit was discarded")
        self.assertEqual(opencode_before, self.opencode.read_bytes(), "the rest of the uninstall stopped")
        self.assertEqual(["codex"], [entry["harness"] for entry in self.entries()])

    def test_dry_run_uninstall_reports_the_refusal(self):
        self.seed()
        self.install(harness="codex")
        self.edit_neva_group()
        code, output = self.uninstall(dry_run=True)
        self.assertEqual(1, code, output)
        self.assertIn("was edited after Neva installed it", output)

    def test_repair_refuses_rather_than_adding_a_second_neva_entry(self):
        self.seed()
        self.install(harness="codex")
        edited = self.edit_neva_group()
        code, output = self.repair()
        self.assertEqual(1, code, output)
        self.assertIn("was edited after Neva installed it", output)
        self.assertEqual(edited, self.hooks.read_bytes())

    def test_negative_control_a_deleted_neva_entry_is_not_an_edit(self):
        self.seed()
        self.install(harness="codex")
        data = self.read(self.hooks)
        data["hooks"]["PreToolUse"] = [OWNER_GROUP]
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertNotIn("neva-core", self.hooks.read_text(encoding="utf-8"))


class TestRefusals(AppendJson):
    def assertRefused(self, harness, path, needle):
        before = path.read_bytes() if path.exists() else None
        code, output = self.install(harness=harness)
        self.assertEqual(1, code, output)
        self.assertIn(needle, output)
        self.assertEqual(before, path.read_bytes() if path.exists() else None, "the file was written")

    def test_malformed_destination_is_refused_unchanged(self):
        self.hooks.parent.mkdir(parents=True)
        self.hooks.write_text('{"hooks": ', encoding="utf-8")
        self.assertRefused("codex", self.hooks, "not valid JSON")

    def test_a_key_holding_the_wrong_type_is_refused_unchanged(self):
        self.hooks.parent.mkdir(parents=True)
        self.hooks.write_text('{"hooks": {"PreToolUse": "not a list"}}', encoding="utf-8")
        self.assertRefused("codex", self.hooks, "hooks.PreToolUse")
        self.opencode.parent.mkdir(parents=True)
        self.opencode.write_text('{"instructions": "docs/x.md"}', encoding="utf-8")
        self.assertRefused("opencode", self.opencode, "instructions")

    def test_a_source_entry_without_the_marker_is_refused(self):
        """An unmarked entry could never be told apart from the owner's, so uninstall would strand it."""
        self.write_adapter("codex", contract("codex", "hooks.json", "~/.codex/hooks.json", "hooks"),
                           {"hooks.json": json.dumps({"hooks": {"Stop": [OWNER_STOP]}})})
        self.assertRefused("codex", self.hooks, "neva-core")

    def test_a_destination_linked_outside_home_is_refused(self):
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        self.hooks.parent.mkdir(parents=True)
        self.hooks.symlink_to(outside)
        code, output = self.install(harness="codex")
        self.assertEqual(1, code, output)
        self.assertIn("outside HOME", output)
        self.assertEqual("{}", outside.read_text(encoding="utf-8"))

    def test_a_dotfiles_link_inside_home_is_written_through_and_kept(self):
        dots = self.home / "dotfiles"
        dots.mkdir()
        target = dots / "codex-hooks.json"
        target.write_text(OWNER_HOOKS, encoding="utf-8")
        self.hooks.parent.mkdir(parents=True)
        self.hooks.symlink_to(target)
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertTrue(self.hooks.is_symlink())
        self.assertIn("neva-core", target.read_text(encoding="utf-8"))
        self.uninstall()
        self.assertHomeUnchanged(before)

    def test_a_manifest_append_json_entry_without_its_value_is_refused(self):
        self.seed()
        self.install(harness="codex")
        state = json.loads(core.state_path().read_text(encoding="utf-8"))
        state["entries"][0].pop("value")
        core.state_path().write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(core.ConfigError) as caught:
            core.load_state()
        self.assertIn("value", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
