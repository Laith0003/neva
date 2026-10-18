"""Reviewed shared-array upgrade regressions."""
import copy
import json
import unittest

from neva_cli.tests.test_append_json import AppendJson, NEVA_GROUP, OWNER_GROUP, HOOKS_SOURCE


class TestOlderHandWiredEntry(AppendJson):
    def test_upgrade_warns_about_exact_old_owner_entry_without_removing_it(self):
        self.seed()
        data = self.read(self.hooks)
        data["hooks"]["PreToolUse"].append(NEVA_GROUP)
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        source = copy.deepcopy(HOOKS_SOURCE)
        source["hooks"]["PreToolUse"][0]["hooks"][0]["command"] += " v2"
        (self.adapters / "codex" / "hooks.json").write_text(json.dumps(source), encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertIn("an older Neva entry you added by hand; remove it to avoid running twice", output)
        self.assertEqual([OWNER_GROUP, NEVA_GROUP, source["hooks"]["PreToolUse"][0]],
                         self.read(self.hooks)["hooks"]["PreToolUse"])
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertEqual([OWNER_GROUP, NEVA_GROUP], self.read(self.hooks)["hooks"]["PreToolUse"])


class TestUnrelatedMarkedEntry(AppendJson):
    def test_deleted_neva_entry_does_not_claim_unrelated_owner_helper(self):
        self.seed()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        data = self.read(self.hooks)
        helper = {"c": "my own neva-core helper"}
        data["hooks"]["PreToolUse"] = [OWNER_GROUP, helper]
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertIn("does not match Neva's recorded entry; kept as yours", output)
        self.assertEqual([OWNER_GROUP, helper], self.read(self.hooks)["hooks"]["PreToolUse"])
        self.assertEqual([], self.entries())

    def test_repair_keeps_unrelated_helper_and_restores_missing_entry(self):
        self.seed()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        data = self.read(self.hooks)
        helper = {"c": "my own neva-core helper"}
        data["hooks"]["PreToolUse"] = [OWNER_GROUP, helper]
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("repaired", output)
        self.assertEqual([OWNER_GROUP, helper, NEVA_GROUP], self.read(self.hooks)["hooks"]["PreToolUse"])


class TestAbandonedCreatedArray(AppendJson):
    def test_still_required_empty_slots_survive_reinstall(self):
        from neva_cli import core
        for value, data, created in (
            ({"Stop": []}, {"hooks": {"Stop": []}}, ["hooks", "hooks.Stop"]),
            ([], {"hooks": []}, ["hooks"]),
        ):
            with self.subTest(value=value):
                before = copy.deepcopy(data)
                core.append_into(data, "hooks", value, "fixture.json", previous=value,
                                 created_parents=created)
                self.assertEqual(before, data)

    def test_upgrade_prunes_only_neva_created_empty_arrays(self):
        self.seed()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        source = {"hooks": {"PreToolUse": [NEVA_GROUP]}}
        (self.adapters / "codex" / "hooks.json").write_text(json.dumps(source), encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertNotIn("Stop", self.read(self.hooks)["hooks"])
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertEqual([OWNER_GROUP], self.read(self.hooks)["hooks"]["PreToolUse"])

    def test_owner_empty_array_survives_upgrade(self):
        self.seed()
        data = self.read(self.hooks)
        data["hooks"]["Stop"] = []
        self.hooks.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        (self.adapters / "codex" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [NEVA_GROUP]}}), encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertEqual([], self.read(self.hooks)["hooks"]["Stop"])


class TestUnrelatedMarkedString(AppendJson):
    """String arrays (OpenCode instructions, plugin): an unrelated marked string is not an edit."""

    NEVA = ".opencode/rules/neva-core/*.md"

    def replace_instructions(self, items):
        data = self.read(self.opencode)
        data["instructions"] = items
        self.opencode.write_text(json.dumps(data), encoding="utf-8")

    def test_uninstall_keeps_an_unrelated_marked_string(self):
        self.seed()
        code, output = self.install(harness="opencode")
        self.assertEqual(0, code, output)
        self.replace_instructions(["docs/owner-rules.md", "notes/my-neva-core-notes.md"])
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertNotIn("was edited", output)
        self.assertEqual(["docs/owner-rules.md", "notes/my-neva-core-notes.md"],
                         self.read(self.opencode)["instructions"])
        self.assertEqual([], self.entries())

    def test_repair_restores_the_missing_string_beside_an_unrelated_one(self):
        self.seed()
        self.install(harness="opencode")
        self.replace_instructions(["docs/owner-rules.md", "notes/my-neva-core-notes.md"])
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("repaired", output)
        self.assertEqual(["docs/owner-rules.md", "notes/my-neva-core-notes.md", self.NEVA],
                         self.read(self.opencode)["instructions"])

    def test_negative_control_an_edited_neva_string_is_still_refused(self):
        self.seed()
        self.install(harness="opencode")
        edited = ".opencode/rules/neva-core/process.md"
        self.replace_instructions(["docs/owner-rules.md", edited])
        code, output = self.uninstall()
        self.assertEqual(1, code, output)
        self.assertIn("was edited after Neva installed it", output)
        self.assertIn(edited, self.read(self.opencode)["instructions"])


if __name__ == "__main__":
    unittest.main()
