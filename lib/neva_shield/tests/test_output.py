"""Output formats and grading."""
import json
import unittest

from support import TreeCase, fixture_result


class Grading(unittest.TestCase):
    def test_clean_scan_grades_a(self):
        self.assertEqual("A", fixture_result("clean", "repository").grade)

    def test_grade_falls_as_findings_accumulate(self):
        from neva_shield.model import Finding, ScanResult
        def grade(*severities):
            findings = [Finding("X", level, "f", index + 1, "m", "f") for index, level in enumerate(severities)]
            return ScanResult(root=".", findings=findings, files_scanned=1).grade
        self.assertEqual("A", grade())
        self.assertEqual("A", grade("medium"))
        self.assertEqual("B", grade("high"))
        self.assertEqual("C", grade("high", "high"))
        self.assertEqual("D", grade("critical", "high"))
        self.assertEqual("F", grade("critical", "critical", "high"))

    def test_score_never_goes_below_zero(self):
        from neva_shield.model import Finding, ScanResult
        result = ScanResult(root=".", findings=[Finding("X", "critical", "f", 1, "m", "f")] * 20)
        self.assertEqual(0, result.score)
        self.assertEqual("F", result.grade)


class TextOutput(unittest.TestCase):
    def test_text_names_rule_severity_location_and_fix(self):
        from neva_shield import render
        output = render.text(fixture_result("permissions", "positive"))
        self.assertIn("PERM001", output)
        self.assertIn("CRITICAL", output)
        self.assertIn(".claude/settings.json:4", output)
        self.assertIn("Fix: ", output)

    def test_clean_text_says_no_findings(self):
        from neva_shield import render
        self.assertIn("No findings", render.text(fixture_result("clean", "repository")))


class JsonOutput(unittest.TestCase):
    def test_json_carries_grade_counts_and_findings(self):
        from neva_shield import render
        document = json.loads(render.json_text(fixture_result("permissions", "positive")))
        self.assertEqual("neva-shield", document["tool"])
        self.assertEqual("F", document["grade"])
        self.assertEqual(1, document["counts"]["critical"])
        first = document["findings"][0]
        self.assertEqual({"rule_id", "severity", "path", "line", "message", "fix"}, set(first))


class SarifOutput(unittest.TestCase):
    def setUp(self):
        from neva_shield import render
        self.document = json.loads(render.sarif(fixture_result("permissions", "positive")))
        self.run = self.document["runs"][0]

    def test_log_header_is_sarif_2_1_0(self):
        self.assertEqual("2.1.0", self.document["version"])
        self.assertIn("sarif-schema-2.1.0", self.document["$schema"])
        self.assertEqual(1, len(self.document["runs"]))

    def test_driver_declares_itself_and_its_rules(self):
        driver = self.run["tool"]["driver"]
        self.assertEqual("Neva Shield", driver["name"])
        self.assertTrue(driver["informationUri"].startswith("https://"))
        for rule in driver["rules"]:
            self.assertEqual({"id", "name", "shortDescription", "fullDescription", "help",
                              "defaultConfiguration", "properties"}, set(rule))
            self.assertIn(rule["defaultConfiguration"]["level"], {"error", "warning", "note"})
            self.assertRegex(rule["properties"]["security-severity"], r"^\d+(\.\d+)?$")

    def test_every_result_has_the_fields_github_requires(self):
        ids = [rule["id"] for rule in self.run["tool"]["driver"]["rules"]]
        self.assertTrue(self.run["results"])
        for item in self.run["results"]:
            self.assertIn(item["ruleId"], ids)
            self.assertEqual(item["ruleId"], ids[item["ruleIndex"]])
            self.assertIn(item["level"], {"error", "warning", "note"})
            self.assertTrue(item["message"]["text"])
            location = item["locations"][0]["physicalLocation"]
            self.assertFalse(location["artifactLocation"]["uri"].startswith("/"),
                             "code scanning needs a repository relative uri")
            self.assertGreaterEqual(location["region"]["startLine"], 1)
            self.assertTrue(item["partialFingerprints"]["nevaShieldRuleLocation"])

    def test_rules_are_emitted_once_each(self):
        ids = [rule["id"] for rule in self.run["tool"]["driver"]["rules"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_clean_scan_is_still_a_valid_empty_log(self):
        from neva_shield import render
        document = json.loads(render.sarif(fixture_result("clean", "repository")))
        self.assertEqual([], document["runs"][0]["results"])
        self.assertEqual([], document["runs"][0]["tool"]["driver"]["rules"])


class PathsInOutput(TreeCase):
    def test_paths_are_relative_to_the_scan_root(self):
        self.write(".claude/settings.json", '{"permissions": {"allow": ["Bash(*)"]}}')
        self.assertEqual([".claude/settings.json"], sorted({item.path for item in self.scan().findings}))


if __name__ == "__main__":
    unittest.main()
