"""The adapters this checkout ships, run through the real installer: not samples.

Every adapters/<harness>/install.json must load through read_adapter, so a mode the installer
does not know can never ship again. Codex and OpenCode, the two whose contracts merge into files
the owner also writes, are installed twice into a HOME that already holds the owner's hooks,
config and instructions, then uninstalled: the owner's content must be intact throughout and
HOME must end byte identical, with nothing of Neva's left behind.
"""
import json
import shutil
import unittest

from neva_cli import core
from neva_cli.tests.harness import Sandbox

SHIPPED = core.REPO_ROOT / "adapters"

OWNER_HOOKS = ('{\n  "hooks": {\n    "PreToolUse": [\n      {"matcher": "^Bash$", "hooks": '
               '[{"type": "command", "command": "python3 /home/user/policy.py"}]}\n    ]\n  }\n}\n')
OWNER_CONFIG = ('# my codex settings\nmodel = "owner-model"\n\n[agents.owner_reviewer]\n'
                'description = "The owner\'s own role"\nconfig_file = "/home/user/roles/reviewer.toml"\n')
OWNER_RULES = "# My rules\n\nAnswer in French. This line belongs to the owner.\n"
OWNER_OPENCODE = '{\n  "model": "owner/model",\n  "instructions": ["~/notes/owner-rules.md"]\n}\n'


def shipped_harnesses():
    return sorted(path.parent.name for path in SHIPPED.glob("*/install.json"))


def load_all(directory):
    """read_adapter every contract under ``directory``; returns the names it loaded."""
    loaded = []
    for path in sorted(directory.glob("*/install.json")):
        contract, _ = core.read_adapter(path.parent.name)
        loaded.append(contract["harness"])
    return loaded


class TestEveryShippedContractLoads(Sandbox):
    def test_every_shipped_contract_loads_through_read_adapter(self):
        self.env({"NEVA_ADAPTERS_DIR": str(SHIPPED)})
        self.assertGreaterEqual(len(shipped_harnesses()), 10)
        self.assertEqual(shipped_harnesses(), load_all(SHIPPED))

    def test_negative_control_an_unknown_mode_fails_the_same_check(self):
        copy = self.root / "adapters-copy"
        shutil.copytree(SHIPPED / "codex", copy / "codex")
        path = copy / "codex" / "install.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["entries"][0]["mode"] = "teleport"
        path.write_text(json.dumps(contract), encoding="utf-8")
        self.env({"NEVA_ADAPTERS_DIR": str(copy)})
        with self.assertRaises(core.AdapterError) as caught:
            load_all(copy)
        self.assertIn("teleport", str(caught.exception))


class ShippedInstall(Sandbox):
    def setUp(self):
        super().setUp()
        self.env({"NEVA_ADAPTERS_DIR": str(SHIPPED), "CODEX_HOME": str(self.home / ".codex"),
                  "NEVA_ROOT": str(core.REPO_ROOT)})

    def put(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def round_trip(self, harness):
        before = self.snapshot_home()
        for run in (1, 2):
            code, output = self.install(harness=harness)
            self.assertEqual(code, 0, "install run " + str(run) + " failed:\n" + output)
        yield
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "uninstall left Neva behind or changed the owner's files:")
        self.assertFalse(core.state_path().exists(), "the manifest still lists entries")


class TestShippedCodex(ShippedInstall):
    def test_codex_install_twice_and_uninstall_keeps_the_owner(self):
        hooks = self.put(".codex/hooks.json", OWNER_HOOKS)
        config = self.put(".codex/config.toml", OWNER_CONFIG)
        agents = self.put(".codex/AGENTS.md", OWNER_RULES)
        for _ in self.round_trip("codex"):
            pre = json.loads(hooks.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
            self.assertEqual("python3 /home/user/policy.py", pre[0]["hooks"][0]["command"])
            self.assertEqual(1, sum("dispatch.py" in json.dumps(group) for group in pre))
            text = config.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(OWNER_CONFIG), "the owner's config bytes moved")
            parsed = core.read_toml(config)
            self.assertTrue(parsed["plugins"]["neva-core@neva"]["enabled"])
            self.assertIn("neva", parsed["marketplaces"])
            shipped = sorted(p.stem.replace("-", "_") for p in (SHIPPED / "codex" / "agents").glob("*.toml"))
            for role in shipped:
                self.assertIn(role, parsed["agents"])
            self.assertEqual("/home/user/roles/reviewer.toml", parsed["agents"]["owner_reviewer"]["config_file"])
            self.assertTrue((self.home / ".codex" / "neva" / "agents" / "architect.toml").is_file())
            rules = agents.read_text(encoding="utf-8")
            self.assertTrue(rules.startswith(OWNER_RULES))
            self.assertEqual(1, rules.count("# neva begin neva-core"))


class TestShippedOpenCode(ShippedInstall):
    def test_opencode_install_twice_and_uninstall_keeps_the_owner(self):
        config = self.put(".config/opencode/opencode.json", OWNER_OPENCODE)
        owned = [self.put(".config/opencode/agents/architect.md", "the owner's architect\n"),
                 self.put(".config/opencode/commands/plan.md", "the owner's plan\n"),
                 self.put(".config/opencode/skills/plan/SKILL.md", "the owner's skill\n")]
        agents = self.put(".config/opencode/AGENTS.md", OWNER_RULES)
        for _ in self.round_trip("opencode"):
            value = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual("owner/model", value["model"])
            self.assertEqual("~/notes/owner-rules.md", value["instructions"][0])
            self.assertEqual(2, len(value["instructions"]), value["instructions"])
            self.assertTrue(agents.read_text(encoding="utf-8").startswith(OWNER_RULES))
            base = self.home / ".config" / "opencode"
            self.assertTrue((base / "plugins" / "neva-hooks.js").is_file())
            self.assertTrue((base / "skills" / "neva" / "ck" / "SKILL.md").is_file())
            self.assertTrue((base / "rules" / "neva-core" / "process.md").is_file())
            self.assertTrue((base / "agents" / "neva" / "architect.md").is_file())
            self.assertTrue((base / "commands" / "neva" / "plan.md").is_file())
            for path in owned:
                self.assertTrue(path.read_text(encoding="utf-8").startswith("the owner's"), str(path))


if __name__ == "__main__":
    unittest.main()
