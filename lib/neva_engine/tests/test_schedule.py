"""The launchd template: every 15 minutes and on wake."""
import os
import plistlib
import unittest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "services", "launchd", "com.neva.engine.plist.tmpl")


class Template(unittest.TestCase):
    def load(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            return plistlib.loads(f.read().replace("@PREFIX@", "/p").replace("@HOME@", "/h").encode())

    def test_it_runs_every_fifteen_minutes(self):
        self.assertEqual([d["Minute"] for d in self.load()["StartCalendarInterval"]], [0, 15, 30, 45])

    def test_it_uses_the_form_launchd_runs_on_wake(self):
        self.assertNotIn("StartInterval", self.load())

    def test_it_runs_through_the_heartbeat_wrapper(self):
        args = self.load()["ProgramArguments"]
        self.assertEqual(args[:2], ["/p/services/heartbeat-wrap.sh", "engine"])

    def test_doctor_judges_its_heartbeat(self):
        with open(os.path.join(os.path.dirname(TEMPLATE), "..", "..", "bin", "doctor"), encoding="utf-8") as f:
            self.assertIn('"engine:', f.read())

    def test_it_runs_the_engine_on_the_user_config(self):
        args = self.load()["ProgramArguments"]
        self.assertEqual(args[4:7], ["-m", "neva_engine", "tick"])
        self.assertEqual(args[-1], "/h/.config/neva/engine/engine.json")

    def test_no_placeholder_is_left_for_the_installer_to_miss(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(set(__import__("re").findall(r"@[A-Z0-9_]+@", text)), {"@PREFIX@", "@HOME@"})
