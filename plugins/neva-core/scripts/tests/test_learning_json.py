"""Malformed learning state must stop processing and retain its bytes."""
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from test_instinct_learning import InstinctSandbox, ANALYZE, PY, _load_module


class LearningJsonCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.analyzer = _load_module(ANALYZE, "neva_json_analyzer")

    def test_bad_config_blocks_before_model_or_state_writes(self):
        config = Path(self.sb.tmp) / "config.json"
        for bad in ("{broken", "[]", '{"analyze": []}',
                    '{"analyze": {"max_analysis_lines": "500"}}',
                    '{"analyze": {"min_observations_to_analyze": true}}',
                    '{"analyze": {"timeout_seconds": 0}}',
                    '{"analyze": {"max_batches_per_run": -1}}',
                    '{"analyze": {"max_turns": -1}}',
                    '{"analyze": {"model": ""}}'):
            with self.subTest(bad=bad):
                config.write_text(bad)
                script = ("import runpy, sys; m=runpy.run_path(sys.argv[1], run_name='test'); "
                          "m['main'].__globals__['CONFIG_FILE']=__import__('pathlib').Path(sys.argv[2]); "
                          "sys.argv=[sys.argv[1]]; sys.exit(m['main']())")
                result = subprocess.run([PY, "-c", script, ANALYZE, str(config)],
                                        env=self.sb.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(str(config), result.stderr)
                self.assertIn("Fix:", result.stderr)
                if bad.startswith('{"analyze": {'):
                    field = next(iter(json.loads(bad)["analyze"]))
                    self.assertIn(f"analyze.{field}", result.stderr)
                self.assertEqual(config.read_text(), bad)
                self.assertFalse((Path(self.sb.tmp) / "state").exists())

    def test_bad_environment_blocks_without_writes(self):
        bucket = Path(self.sb.tmp) / "data/neva/observations/bucket"
        bucket.mkdir(parents=True)
        observations = bucket / "observations.jsonl"
        original = '{"event":"tool_start"}\n' * 250
        observations.write_text(original)
        self.sb.write_exe("claude", "#!__PY__\nraise SystemExit('MODEL MUST NOT RUN')\n")
        for field, value in (("NEVA_INSTINCT_MIN_OBSERVATIONS", "bad"),
                             ("NEVA_INSTINCT_MAX_ANALYSIS_LINES", "0"),
                             ("NEVA_INSTINCT_TIMEOUT_SECONDS", "-1"),
                             ("NEVA_INSTINCT_MAX_BATCHES", "0"),
                             ("NEVA_INSTINCT_MAX_TURNS", "-1"),
                             ("NEVA_INSTINCT_MODEL", "   ")):
            with self.subTest(field=field):
                result = subprocess.run([PY, ANALYZE],
                                        env=dict(self.sb.env, **{field: value}),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(field, result.stderr)
                self.assertIn("Fix:", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(observations.read_text(), original)
                self.assertFalse((Path(self.sb.tmp) / "state").exists())

    def test_valid_config_accepts_boundary_values(self):
        config = Path(self.sb.tmp) / "config.json"
        values = dict(min_observations_to_analyze=1, max_analysis_lines=1,
                      timeout_seconds=1, max_batches_per_run=1, max_turns=0, model="haiku")
        config.write_text(json.dumps({"analyze": values}))
        with mock.patch.object(self.analyzer, "CONFIG_FILE", config), \
             mock.patch.dict(os.environ, self.sb.env, clear=True):
            self.assertEqual(self.analyzer.load_config(), values)

    def test_missing_config_uses_defaults(self):
        with mock.patch.object(self.analyzer, "CONFIG_FILE", Path(self.sb.tmp) / "absent.json"), \
             mock.patch.dict(os.environ, self.sb.env, clear=True):
            self.assertEqual(self.analyzer.load_config()["min_observations_to_analyze"], 20)

    def test_bad_registry_blocks_cli_without_replacement(self):
        registry = Path(self.sb.tmp) / "data/neva/observations/projects.json"
        registry.parent.mkdir(parents=True)
        for bad in ("{broken", "[]"):
            with self.subTest(bad=bad):
                registry.write_text(bad)
                result = self.sb.run("stats", check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(str(registry), result.stderr)
                self.assertIn("Fix:", result.stderr)
                self.assertEqual(registry.read_text(), bad)

    def test_bad_ledger_blocks_proposals_without_replacement(self):
        ledger = Path(self.sb.tmp) / "state/neva/instincts/promotions.json"
        ledger.parent.mkdir(parents=True)
        for bad in ("{broken", "[]"):
            with self.subTest(bad=bad):
                ledger.write_text(bad)
                result = self.sb.run("propose", check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(str(ledger), result.stderr)
                self.assertIn("Fix:", result.stderr)
                self.assertEqual(ledger.read_text(), bad)
                self.assertFalse(Path(self.sb.proposal_path()).exists())

    def test_bad_config_never_schedules_paid_analysis(self):
        import sys
        from test_instinct_learning import HOOKS_DIR
        sys.path.insert(0, HOOKS_DIR)
        self.addCleanup(sys.path.remove, HOOKS_DIR)
        from neva_hooks import learning_trigger as trigger
        config = Path(self.sb.tmp) / "config.json"
        config.write_text("{broken")
        bucket = Path(self.sb.tmp) / "observations/bucket"
        bucket.mkdir(parents=True)
        (bucket / "observations.jsonl").write_text('{"event":"tool_start"}\n' * 250)
        with mock.patch.dict(os.environ, dict(self.sb.env, NEVA_INSTINCT_SAMEDAY="1"), clear=True), \
             mock.patch.object(trigger, "CL2_CONFIG", config), \
             mock.patch.object(trigger.c, "observations_dir", return_value=str(bucket.parent)), \
             mock.patch.object(trigger.c, "log") as logger, \
             mock.patch.object(trigger.subprocess, "Popen") as child:
            self.assertIsNone(trigger.run({}))
        child.assert_not_called()
        self.assertIn(str(config), logger.call_args[0][0])
        self.assertIn("Fix:", logger.call_args[0][0])
        self.assertEqual(config.read_text(), "{broken")

    def test_registry_symlink_is_refused_without_owner_write(self):
        registry = Path(self.sb.tmp) / "data/neva/observations/projects.json"
        registry.parent.mkdir(parents=True)
        owner = Path(self.sb.tmp) / "owner.json"
        owner.write_text('{"owner": true}\n')
        registry.symlink_to(owner)
        result = self.sb.run("stats", check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(registry), result.stderr)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(owner.read_text(), '{"owner": true}\n')
        self.assertTrue(registry.is_symlink())
