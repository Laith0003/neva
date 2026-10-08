"""Claude plugin and marketplace registrations are owned, recorded and undone like files.

install registers the neva marketplace and the selected plugins through the claude CLI. Those
registrations persist in Claude Code's own state, so uninstall has to remove the ones this
install created and leave every registration the user already had. The fake claude in the
harness keeps that state in a JSON file, so these tests assert on what is actually registered,
not on which commands were printed.
"""
from neva_cli import core
from neva_cli.tests.harness import Sandbox

MARKET = "neva"


def registered(state):
    return (sorted(item["name"] for item in state["marketplaces"]),
            sorted(item["id"] for item in state["plugins"]))


class TestFreshMachine(Sandbox):
    def test_uninstall_removes_the_marketplace_and_plugins_install_added(self):
        code, output = self.install(harness="claude", plugins="core,web")
        self.assertEqual(code, 0, output)
        self.assertEqual(registered(self.claude_state()),
                         ([MARKET], ["neva-core@neva", "neva-web@neva"]))
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(registered(self.claude_state()), ([], []),
                         "plugins or the marketplace stayed registered after uninstall:\n" + output)

    def test_registrations_are_in_the_manifest(self):
        self.install(harness="claude", plugins="core,web")
        kinds = sorted((entry["kind"], entry["key"]) for entry in self.entries("claude")
                       if entry["kind"].startswith("claude-"))
        self.assertEqual(kinds, [("claude-marketplace", "neva"), ("claude-plugin", "neva-core@neva"),
                                 ("claude-plugin", "neva-web@neva")])

    def test_a_second_install_registers_nothing_twice(self):
        self.install(harness="claude", plugins="core")
        self.calls.write_text("", encoding="utf-8")
        code, output = self.install(harness="claude", plugins="core")
        self.assertEqual(code, 0, output)
        mutations = [call["argv"] for call in self.recorded()
                     if call["binary"] == "claude" and "list" not in call["argv"]]
        self.assertEqual(mutations, [], "a re-run registered again")
        self.assertEqual(len([entry for entry in self.entries("claude")
                              if entry["kind"].startswith("claude-")]), 2)
        self.uninstall()
        self.assertEqual(registered(self.claude_state()), ([], []))

    def test_dry_run_registers_nothing(self):
        code, output = self.install(harness="claude", dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(registered(self.claude_state()), ([], []))

    def test_uninstall_dry_run_unregisters_nothing(self):
        self.install(harness="claude")
        before = self.claude_state()
        code, output = self.uninstall(dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn("would uninstall plugin neva-core@neva", output)
        self.assertEqual(self.claude_state(), before)


class TestPreexistingRegistrations(Sandbox):
    def setUp(self):
        super().setUp()
        self.seeded = {"marketplaces": [{"name": MARKET, "source": str(core.REPO_ROOT)},
                                        {"name": "elsewhere", "source": "/home/user/market"}],
                       "plugins": ["neva-core@neva", "other@elsewhere"]}
        self.seed_claude(self.seeded["marketplaces"], self.seeded["plugins"])
        self.before = self.claude_state()

    def test_only_what_install_added_is_recorded(self):
        code, output = self.install(harness="claude", plugins="core,web")
        self.assertEqual(code, 0, output)
        owned = [entry["key"] for entry in self.entries("claude") if entry["kind"].startswith("claude-")]
        self.assertEqual(owned, ["neva-web@neva"],
                         "install claimed registrations the user already had")

    def test_uninstall_restores_exactly_the_registrations_the_user_had(self):
        self.install(harness="claude", plugins="core,web")
        self.assertIn("neva-web@neva", registered(self.claude_state())[1])
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.claude_state(), self.before,
                         "uninstall changed registrations it did not create:\n" + output)

    def test_negative_control_the_comparison_sees_a_missing_preexisting_plugin(self):
        self.install(harness="claude", plugins="core,web")
        self.uninstall()
        state = self.claude_state()
        state["plugins"] = [item for item in state["plugins"] if item["id"] != "neva-core@neva"]
        self.assertNotEqual(state, self.before)


class TestDoctorAndRepair(Sandbox):
    def test_a_removed_plugin_is_reported_and_repaired(self):
        self.install(harness="claude", plugins="core,web")
        state = self.claude_state()
        state["plugins"] = [item for item in state["plugins"] if item["id"] != "neva-web@neva"]
        self.seed_claude(state["marketplaces"], [item["id"] for item in state["plugins"]])
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1, output)
        self.assertIn("neva-web@neva", output)
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertIn("neva-web@neva", registered(self.claude_state())[1])
        self.assertEqual(self.doctor(harness="claude")[0], 0)

    def test_doctor_is_green_while_every_registration_is_present(self):
        self.install(harness="claude")
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertIn("marketplace is registered", output)


class TestUninstallWithoutTheCli(Sandbox):
    def test_a_missing_claude_cli_fails_by_name_and_keeps_the_entries_for_a_retry(self):
        self.install(harness="claude")
        self.hide("claude")
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn("claude plugin uninstall neva-core@neva", output)
        self.assertIn("fix:", output)
        self.assertTrue(any(entry["kind"] == "claude-plugin" for entry in self.entries("claude")),
                        "registration entries were dropped although nothing was unregistered")
        self.stateful_claude()
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(registered(self.claude_state()), ([], []))

    def test_a_failing_unregister_is_reported_with_its_error(self):
        self.install(harness="claude")
        self.stub("claude", code=4, stderr="permission denied on plugin cache\n")
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn("permission denied on plugin cache", output)


class TestScopedUninstall(Sandbox):
    def test_uninstalling_another_harness_keeps_claude_registrations(self):
        from neva_cli.tests.test_install import SOURCES, adapter
        self.write_adapter("codex", adapter(), SOURCES)
        self.install(harness="all")
        self.uninstall(harness="codex")
        self.assertEqual(registered(self.claude_state()), ([MARKET], ["neva-core@neva"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
