"""A reinstall removes the files an earlier install copied that the source no longer has.

The main-era OpenCode install copied skills to skills/neva/<name>; the current one copies them
to skills/neva/neva-<name>. Left behind, the old copies still shadow the owner's skills.
"""
import json
import shutil

from neva_cli import core
from neva_cli.tests.harness import Sandbox

SHIPPED = core.REPO_ROOT / "adapters"
SKILLS = ".config/opencode/skills/neva"


class TestStaleCopies(Sandbox):
    def fixture(self, files):
        directory = self.adapters / "fixture"
        shutil.rmtree(directory, ignore_errors=True)
        self.write_adapter("fixture", {"harness": "fixture", "entries": [
            {"src": "skills", "dest": "~/" + SKILLS, "mode": "copy"}]},
            {"skills/" + name: body for name, body in files.items()})

    def test_reinstall_removes_files_the_source_dropped(self):
        before = self.snapshot_home()
        self.fixture({"ck/SKILL.md": "old ck\n", "ck/commands/save.mjs": "old save\n", "plan/SKILL.md": "old plan\n"})
        code, output = self.install(harness="fixture")
        self.assertEqual(0, code, output)
        self.fixture({"neva-ck/SKILL.md": "new ck\n", "neva-plan/SKILL.md": "new plan\n"})
        code, output = self.install(harness="fixture")
        self.assertEqual(0, code, output)
        base = self.home / SKILLS
        self.assertFalse((base / "ck").exists(), output)
        self.assertFalse((base / "plan").exists(), output)
        self.assertEqual("new ck\n", (base / "neva-ck" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(sorted(["neva-ck", "neva-plan"]), sorted(p.name for p in base.iterdir()))
        self.assertIn("removed " + str(base / "ck" / "SKILL.md"), output)
        dests = [entry["dest"] for entry in self.entries("fixture")]
        self.assertNotIn(str(base / "ck" / "SKILL.md"), dests)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)

    def test_edited_stale_file_is_reported_and_kept(self):
        self.fixture({"ck/SKILL.md": "old ck\n", "plan/SKILL.md": "old plan\n"})
        code, output = self.install(harness="fixture")
        self.assertEqual(0, code, output)
        edited = self.home / SKILLS / "ck" / "SKILL.md"
        edited.write_text("old ck\nmy own note\n", encoding="utf-8")
        self.fixture({"neva-ck/SKILL.md": "new ck\n", "neva-plan/SKILL.md": "new plan\n"})
        code, output = self.install(harness="fixture")
        self.assertEqual(0, code, output)
        self.assertEqual("old ck\nmy own note\n", edited.read_text(encoding="utf-8"))
        self.assertIn("kept " + str(edited), output)
        self.assertIn("edited", output)
        self.assertFalse((self.home / SKILLS / "plan").exists())

    def test_dry_run_reports_and_removes_nothing(self):
        self.fixture({"ck/SKILL.md": "old ck\n"})
        self.assertEqual(0, self.install(harness="fixture")[0])
        self.fixture({"neva-ck/SKILL.md": "new ck\n"})
        code, output = self.install(harness="fixture", dry_run=True)
        self.assertEqual(0, code, output)
        self.assertTrue((self.home / SKILLS / "ck" / "SKILL.md").is_file())
        self.assertIn("would remove " + str(self.home / SKILLS / "ck" / "SKILL.md"), output)

    def test_file_another_entry_writes_inside_the_tree_is_not_stale(self):
        self.write_adapter("fixture", {"harness": "fixture", "entries": [
            {"src": "extra.md", "dest": "~/" + SKILLS + "/extra/SKILL.md", "mode": "copy"},
            {"src": "skills", "dest": "~/" + SKILLS, "mode": "copy"}]},
            {"skills/neva-ck/SKILL.md": "new ck\n", "extra.md": "extra\n"})
        for run in (1, 2):
            code, output = self.install(harness="fixture")
            self.assertEqual(0, code, output)
            self.assertEqual("extra\n", (self.home / SKILLS / "extra" / "SKILL.md").read_text(encoding="utf-8"),
                             "run " + str(run))


class TestOpenCodeUpgradeFromMain(Sandbox):
    """Start from a manifest that holds skills/neva/ck/SKILL.md, as the main-era install left it."""

    def test_upgrade_removes_unprefixed_skills(self):
        self.env({"NEVA_ADAPTERS_DIR": str(self.adapters)})
        owner = self.home / ".config/opencode/skills/ck/SKILL.md"
        owner.parent.mkdir(parents=True)
        owner.write_text("---\nname: ck\n---\nthe owner's ck\n", encoding="utf-8")
        before = self.snapshot_home()
        self.write_adapter("opencode", {"harness": "opencode", "entries": [
            {"src": "skills", "dest": "~/" + SKILLS, "mode": "copy"}]},
            {"skills/ck/SKILL.md": "---\nname: ck\n---\nNeva's old ck\n"})
        code, output = self.install(harness="opencode")
        self.assertEqual(0, code, output)
        stale = self.home / SKILLS / "ck" / "SKILL.md"
        self.assertIn(str(stale), [entry["dest"] for entry in self.entries("opencode")])
        self.env({"NEVA_ADAPTERS_DIR": str(SHIPPED)})
        code, output = self.install(harness="opencode")
        self.assertEqual(0, code, output)
        self.assertFalse(stale.parent.exists(), "the unprefixed ck still shadows the owner's skill")
        unprefixed = [p.name for p in (self.home / SKILLS).iterdir() if not p.name.startswith("neva-")]
        self.assertEqual([], unprefixed)
        self.assertTrue((self.home / SKILLS / "neva-ck" / "SKILL.md").is_file())
        self.assertEqual("---\nname: ck\n---\nthe owner's ck\n", owner.read_text(encoding="utf-8"))
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)
        self.assertFalse(core.state_path().exists())
