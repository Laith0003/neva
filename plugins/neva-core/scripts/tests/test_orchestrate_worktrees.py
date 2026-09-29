#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Tests for orchestrate_worktrees.py: a real temp git repo, a fake tmux on PATH.

Run:  python3 plugins/neva-core/scripts/tests/test_orchestrate_worktrees.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

sys.path.insert(0, support.SCRIPTS)
import orchestrate_worktrees as ow  # noqa: E402


class OrchCase(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-orch-test-")
        self.repo = os.path.join(self.sb.work, "app")
        os.makedirs(self.repo)
        self.sb.git("init", "-q", "-b", "main", cwd=self.repo)
        self.sb.write(os.path.join(self.repo, "README.md"), "app\n")
        self.sb.write(os.path.join(self.repo, "local", "secret.env"), "TOKEN=x\n")
        self.sb.git("add", "README.md", cwd=self.repo)
        self.sb.git("commit", "-q", "-m", "init", cwd=self.repo)
        support.write_exe(os.path.join(self.sb.bin, "tmux"), support.FAKE_TMUX)
        self.tmux_log = self.sb.path("tmux.jsonl")
        self.sessions = self.sb.path("tmux-sessions")
        os.makedirs(self.sessions)
        open(self.tmux_log, "w").close()
        self.sb.env.update({"FAKE_TMUX_LOG": self.tmux_log, "FAKE_TMUX_SESSIONS": self.sessions})

    def tearDown(self):
        self.sb.close()

    def plan(self, **over):
        cfg = {
            "sessionName": "Auth Refactor",
            "repoRoot": self.repo,
            "worktreeRoot": self.sb.path("trees"),
            "launcherCommand": "run-worker --task {task_file_sh} --out {handoff_file_sh}",
            "seedPaths": ["local/secret.env"],
            "workers": [{"name": "API", "task": "Build the API"}, {"name": "Docs", "task": "Write docs"}],
        }
        cfg.update(over)
        return self.sb.write("plan.json", cfg)

    def run_orch(self, *args, env=None):
        return self.sb.run("orchestrate_worktrees.py", *args, cwd=self.repo, env=env)

    def branches(self):
        out = self.sb.git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=self.repo)
        return sorted(x.strip() for x in out.splitlines() if x.strip())

    def tmux_calls(self):
        with open(self.tmux_log) as fh:
            return [json.loads(x) for x in fh if x.strip()]


class TestPlan(OrchCase):
    def test_dry_run_prints_plan_and_touches_nothing(self):
        r = self.run_orch(self.plan())
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["sessionName"], "auth-refactor")
        self.assertEqual([w["branchName"] for w in out["workers"]],
                         ["orchestrator-auth-refactor-api", "orchestrator-auth-refactor-docs"])
        self.assertTrue(out["workers"][0]["launchCommand"].startswith("run-worker --task '"))
        self.assertTrue(out["commands"][0].startswith("git 'worktree' 'add' '-b' 'orchestrator-auth-refactor-api'"))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".orchestration")))
        self.assertEqual(self.branches(), ["main"])
        self.assertEqual(self.tmux_calls(), [])

    def test_write_only_materializes_files(self):
        r = self.run_orch(self.plan(), "--write-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.repo, ".orchestration", "auth-refactor", "api")
        self.assertEqual(sorted(os.listdir(d)), ["handoff.md", "status.md", "task.md"])
        with open(os.path.join(d, "task.md")) as fh:
            task = fh.read()
        self.assertIn("## Objective\nBuild the API", task)
        self.assertIn("- `local/secret.env`", task)
        self.assertEqual(self.branches(), ["main"])

    def test_validation_errors(self):
        cases = [
            ({"workers": []}, "at least one worker"),
            ({"workers": [{"name": "a"}]}, "workers[0].task: missing"),
            ({"workers": [{"name": "A", "task": "x"}, {"name": "a", "task": "y"}]}, "Duplicate: a"),
            ({"seedPaths": ["../outside"]}, "must stay inside repoRoot"),
            ({"launcherCommand": "go {nope}"}, "Unknown template variable: nope"),
            ({"launcherCommand": ""}, "missing a launcherCommand"),
        ]
        for over, msg in cases:
            r = self.run_orch(self.plan(**over))
            self.assertEqual(r.returncode, 1, over)
            self.assertIn(msg, r.stderr, over)

    def test_cli_errors(self):
        r = self.run_orch(self.sb.path("missing.json"))
        self.assertIn("plan file not found", r.stderr)
        r = self.run_orch(self.plan(), "--execute", "--write-only")
        self.assertIn("conflict", r.stderr)
        r = self.run_orch(self.plan(), "--force")
        self.assertIn("Unknown option: --force", r.stderr)


class TestExecute(OrchCase):
    def test_execute_creates_worktrees_branches_and_panes(self):
        r = self.run_orch(self.plan(), "--execute")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Started tmux session 'auth-refactor' with 2 worker panes.", r.stdout)
        self.assertEqual(self.branches(), ["main", "orchestrator-auth-refactor-api", "orchestrator-auth-refactor-docs"])
        tree = self.sb.path("trees", "app-auth-refactor-api")
        self.assertTrue(os.path.isfile(os.path.join(tree, "README.md")))
        with open(os.path.join(tree, "local", "secret.env")) as fh:
            self.assertEqual(fh.read(), "TOKEN=x\n", "seed path overlaid into the worktree")
        calls = self.tmux_calls()
        verbs = [c[0] for c in calls]
        self.assertEqual(verbs.count("split-window"), 2)
        sends = [c for c in calls if c[0] == "send-keys" and c[2].startswith("%")]
        self.assertEqual(len(sends), 2)
        self.assertIn("run-worker --task", sends[0][3])
        self.assertTrue(sends[0][3].startswith("cd '"))

    def test_existing_session_is_refused(self):
        open(os.path.join(self.sessions, "auth-refactor"), "w").close()
        r = self.run_orch(self.plan(), "--execute")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tmux session already exists: auth-refactor", r.stderr)
        self.assertEqual(self.branches(), ["main"])

    def test_failure_rolls_back_everything_this_run_created(self):
        r = self.run_orch(self.plan(), "--execute", env={"FAKE_TMUX_FAIL_ON": "split-window"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("split-window", r.stderr)
        self.assertEqual(self.branches(), ["main"])
        self.assertFalse(os.path.exists(self.sb.path("trees", "app-auth-refactor-api")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".orchestration", "auth-refactor")))
        self.assertFalse(os.path.exists(os.path.join(self.sessions, "auth-refactor")), "tmux session killed")

    def test_replace_existing_needs_the_cli_flag(self):
        self.assertEqual(self.run_orch(self.plan(), "--execute").returncode, 0)
        os.remove(os.path.join(self.sessions, "auth-refactor"))
        plan = self.plan(replaceExisting=True)
        r = self.run_orch(plan, "--execute")
        self.assertEqual(r.returncode, 1)
        self.assertIn("replaceExisting:", r.stderr)
        self.assertIn("--replace-existing", r.stderr)
        r = self.run_orch(plan, "--execute", "--replace-existing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branches(), ["main", "orchestrator-auth-refactor-api", "orchestrator-auth-refactor-docs"])

    def test_missing_tmux_is_explained(self):
        os.remove(os.path.join(self.sb.bin, "tmux"))
        env = {"PATH": self.sb.bin + os.pathsep + "/usr/bin:/bin"}
        r = self.run_orch(self.plan(), "--execute", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("tmux not found on PATH", r.stderr)
        self.assertEqual(self.branches(), ["main"])


class TestUnits(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(ow.slugify("  Hello World!! "), "hello-world")
        self.assertEqual(ow.slugify("!!!", "x"), "x")
        self.assertEqual(ow.shell_quote("it's"), "'it'\\''s'")
        v = ow.build_template_variables({"a": "x y"})
        self.assertEqual((v["a"], v["a_raw"], v["a_sh"]), ("x y", "x y", "'x y'"))
        self.assertEqual(ow.normalize_seed_paths(["a", "./a", "b/../c", ""], "/r"), ["a", "c"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
