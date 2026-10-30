"""Tests for build/check-plugin-refs.py. Every rule is shown to fail on a planted defect."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_plugin_refs", ROOT / "build" / "check-plugin-refs.py")
refs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refs)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FixtureRepo(unittest.TestCase):
    """A two-plugin marketplace: core with one skill, library with one skill and one agent."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="neva-refs-"))
        write(self.root / ".claude-plugin" / "marketplace.json", json.dumps({"name": "neva", "plugins": [
            {"name": "neva-core", "source": "./plugins/neva-core"},
            {"name": "neva-library", "source": "./plugins/neva-library"},
            {"name": "neva-web", "source": "./plugins/neva-web"}]}))
        for name in ("neva-core", "neva-library", "neva-web"):
            write(self.root / "plugins" / name / ".claude-plugin" / "plugin.json", json.dumps({"name": name}))
        self.core = self.root / "plugins" / "neva-core"
        self.lib = self.root / "plugins" / "neva-library"
        write(self.core / "skills" / "tdd-workflow" / "SKILL.md", "---\nname: tdd-workflow\n---\nbody\n")
        write(self.core / "scripts" / "tool.py", "print(1)\n")
        write(self.core / "scripts" / "neva_core.py", "# resolver\n")
        write(self.lib / "skills" / "plan-canvas" / "SKILL.md", "---\nname: plan-canvas\n---\nbody\n")
        write(self.lib / "agents" / "planner.md", "---\nname: planner\n---\nbody\n")
        write(self.lib / "scripts" / "neva_core.py", "# resolver\n")
        self.web = self.root / "plugins" / "neva-web"
        write(self.web / "skills" / "react-testing" / "SKILL.md", "---\nname: react-testing\n---\nbody\n")
        # A name both the library and a domain plugin ship is not library-only.
        write(self.lib / "skills" / "shared-name" / "SKILL.md", "---\nname: shared-name\n---\nbody\n")
        write(self.web / "skills" / "shared-name" / "SKILL.md", "---\nname: shared-name\n---\nbody\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def findings(self):
        return refs.check(self.root)


class TestCheckPluginRefs(FixtureRepo):
    def test_clean_fixture_passes(self):
        write(self.core / "rules" / "a.md", "Use `neva-core:tdd-workflow`, then the opt-in `neva-library:planner`.\n")
        write(self.lib / "commands" / "go.md",
              'Run `neva-core:tdd-workflow`; `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/neva_core.py" run scripts/tool.py`.\n')
        self.assertEqual(self.findings(), [])

    def test_r1_namespaced_name_that_moved(self):
        write(self.lib / "skills" / "plan-canvas" / "SKILL.md", "Dispatch `neva-core:planner`.\n")
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn("R1 namespaced", found[0])
        self.assertIn("neva-library:planner", found[0])

    def test_r1_namespaced_name_that_does_not_exist(self):
        write(self.root / "docs" / "x.md", "See `neva-library:nothing-here`.\n")
        self.assertIn("ships no skill", self.findings()[0])

    def test_r2_core_slash_reference_to_library(self):
        write(self.core / "commands" / "plan.md", "Then run /plan-canvas to approve.\n")
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn("R2 opt-in", found[0])

    def test_r2_core_subagent_and_backtick_references(self):
        write(self.core / "rules" / "agents.md", 'subagent_type: "planner"\nuse the `plan-canvas` skill\n')
        self.assertEqual(len(self.findings()), 2)

    def test_r2_does_not_apply_inside_the_library(self):
        write(self.lib / "commands" / "x.md", "Run /plan-canvas and the `planner` agent.\n")
        self.assertEqual(self.findings(), [])

    def test_r2_ignores_paths_and_urls(self):
        write(self.core / "rules" / "p.md", "See docs/plan-canvas, <STATE_DIR>/plan-canvas, ${ROOT}/plan-canvas and https://x.test/planner.\n")
        self.assertEqual(self.findings(), [])

    def test_r2_applies_to_domain_plugins(self):
        write(self.web / "commands" / "react-build.md", "If the build fails run /plan-canvas.\n")
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn("plugins/neva-web/commands/react-build.md:1: R2", found[0])

    def test_r2_names_shipped_by_another_plugin_are_not_library_only(self):
        write(self.web / "rules" / "a.md", "Use the `shared-name` skill.\n")
        write(self.core / "rules" / "b.md", "Use the `shared-name` skill.\n")
        self.assertEqual(self.findings(), [])

    def test_r2_prose_form(self):
        write(self.web / "skills" / "react-testing" / "SKILL.md", "Use the planner agent, then the plan-canvas skill.\n")
        found = self.findings()
        self.assertEqual(len(found), 2, found)

    def test_r2_skill_call_form(self):
        write(self.core / "rules" / "c.md", 'Skill("plan-canvas") then Skill(plan-canvas)\n')
        self.assertEqual(len(self.findings()), 2)

    def test_r2_python_skill_path_form(self):
        write(self.core / "hooks" / "x.py",
              'p = os.path.join(root, "skills", "plan-canvas")\nq = ROOT / "skills" / "plan-canvas"\n')
        self.assertEqual(len(self.findings()), 2)

    def test_r2_namespaced_and_prose_negatives(self):
        write(self.web / "rules" / "ok.md", "Use the `neva-library:planner` agent (opt-in). Planning is hard.\n")
        self.assertEqual(self.findings(), [])

    def test_r3_unbraced_plugin_root(self):
        write(self.lib / "commands" / "y.md", 'python3 "$CLAUDE_PLUGIN_ROOT/scripts/tool.py"\n')
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn("R3 paths", found[0])

    def test_r3_plugin_root_path_must_exist_in_own_plugin(self):
        write(self.lib / "commands" / "x.md", 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tool.py"\n')
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn("R3 paths", found[0])

    def test_r3_core_resolver_target_must_exist_in_core(self):
        write(self.lib / "commands" / "x.md",
              'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/neva_core.py" run scripts/gone.py\n')
        self.assertIn("does not exist in neva-core", self.findings()[0])

    def test_r3_a_library_path_must_resolve_under_both_roots(self):
        write(self.lib / "skills" / "plan-canvas" / "run.js", "x\n")
        write(self.lib / "commands" / "z.md", 'node "${CLAUDE_PLUGIN_ROOT}/skills/plan-canvas/run.js"\n')
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn('library skills/plan-canvas/run.js', found[0])

    def test_r3_js_env_form(self):
        write(self.lib / "commands" / "j.md", "require(process.env.CLAUDE_PLUGIN_ROOT + '/skills/plan-canvas/lib')\n")
        self.assertIn("R3 paths", self.findings()[0])

    def test_r3_library_helper_target_must_exist_in_the_library(self):
        write(self.core / "commands" / "k.md",
              'node "$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/neva_core.py" library skills/gone/x.js)"\n')
        self.assertIn("does not exist in neva-library", self.findings()[0])

    def test_r3_the_helper_copies_must_match(self):
        write(self.core / "scripts" / "neva_core.py", "# drifted\n")
        self.assertIn("neva_core.py", self.findings()[0])

    def test_r2_bold_table_and_pair_with_forms(self):
        write(self.web / "rules" / "b.md", "- **planner** - plans\n| x | plan-canvas | y |\nPair with plan-canvas first.\n")
        self.assertEqual(len(self.findings()), 3)
        write(self.web / "rules" / "b.md", 'ROLE: <analyzer|planner|reviewer>\n')
        self.assertEqual(self.findings(), [])

    def test_tests_and_changelog_are_not_scanned(self):
        write(self.core / "hooks" / "tests" / "test_x.py", "'neva-core:planner'\n")
        write(self.root / "CHANGELOG.md", "Moved neva-core:planner to the library.\n")
        self.assertEqual(self.findings(), [])

    def test_cli_exit_codes(self):
        self.assertEqual(refs.main(["--root", str(self.root)]), 0)
        write(self.core / "rules" / "a.md", "Run /plan-canvas.\n")
        self.assertEqual(refs.main(["--root", str(self.root)]), 1)


class TestRealRepo(unittest.TestCase):
    def test_repository_is_clean(self):
        self.assertEqual(refs.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()
