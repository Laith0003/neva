#!/usr/bin/env python3
"""The analysis child's grant and launch (issue 27, B1 and B3).

B1: lessons the owner stated with `add` are out of the analyzer's reach. The child's Edit grant
covers the project instincts folder, where project `add` notes live, so every note recorded in
the add ledger (user-stated.json) inside that folder gets its own deny rule:
`--disallowedTools Edit(//<absolute note path>)`. Claude Code documents that deny rules win over
allow rules, so the grant to the folder no longer reaches those files.

No real model runs: NEVA_CLAUDE_BIN is a stub that records its argv and working directory.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import subprocess
import unittest

from test_instinct_learning import ANALYZE, PY, InstinctSandbox

ARGV_CLAUDE = """#!__PY__
import json, os, re, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
path = re.search(r"(\\S+\\.analyze-tmp/analysis\\.\\S+?\\.jsonl)", prompt).group(1)
last = json.loads([x for x in open(path) if x.strip()][-1])
with open(os.path.join(os.environ["FAKE_LOG_DIR"], "argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "cwd_listing": sorted(os.listdir("."))}) + "\\n")
sys.stdout.write(json.dumps({"status": "analysis_complete", "token": last["token"]}, separators=(",", ":")) + "\\n")
"""


def flag_values(argv, flag):
    """Every value passed after `flag` (a flag may repeat; each value is one argv item)."""
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


class AnalyzeChildBase(unittest.TestCase):
    """A sandbox with one observation bucket, its instincts folder, and a stub model."""
    PID = "p1"

    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.fake = self.sb.write_exe("fake-claude", ARGV_CLAUDE)
        self.log_dir = os.path.join(self.sb.tmp, "fake-log")
        os.makedirs(self.log_dir)
        bucket = os.path.join(self.sb.tmp, "data", "neva", "observations", self.PID)
        os.makedirs(bucket)
        with open(os.path.join(bucket, "observations.jsonl"), "w") as fh:
            for i in range(6):
                fh.write(json.dumps({"n": i}) + "\n")
        self.instincts_dir = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", self.PID)
        os.makedirs(self.instincts_dir)
        self.state = os.path.join(self.sb.tmp, "state", "neva", "instincts")

    def note(self, name):
        path = os.path.join(self.instincts_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"---\nid: {name[:-3]}\ntrigger: \"when x\"\nconfidence: 0.9\n---\n\n## Action\nDo x.\n")
        return path

    def record_stated(self, *paths):
        os.makedirs(self.state, exist_ok=True)
        rows = {"vault:" + os.path.relpath(p, self.sb.vault).replace(os.sep, "/"): {"date": "2026-01-01", "sha": "x"}
                for p in paths}
        with open(os.path.join(self.state, "user-stated.json"), "w") as fh:
            json.dump(rows, fh)

    def analyze(self):
        env = dict(self.sb.env, NEVA_CLAUDE_BIN=self.fake, FAKE_LOG_DIR=self.log_dir,
                   NEVA_INSTINCT_MIN_OBSERVATIONS="5")
        r = subprocess.run([PY, ANALYZE, "--project", self.PID], env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.log_dir, "argv.jsonl")) as fh:
            calls = [json.loads(x) for x in fh if x.strip()]
        self.assertTrue(calls, "the analysis child never ran")
        return calls[0]

    def denied(self, call):
        return [rule for v in flag_values(call["argv"], "--disallowedTools") for rule in v.split(",")]

class AnalyzeStatedDenyCase(AnalyzeChildBase):
    def test_every_stated_note_in_the_bucket_is_denied_to_the_child(self):
        mine = self.note("my-own-words.md")
        also = self.note("another-of-mine.md")
        analyzer = self.note("analyzer-wrote-this.md")
        self.record_stated(mine, also)
        denied = self.denied(self.analyze())
        for p in (mine, also):
            self.assertIn("Edit(//" + os.path.realpath(p).lstrip("/") + ")", denied)
        self.assertFalse(any(os.path.basename(analyzer) in r for r in denied),
                         "a note the analyzer wrote stays editable by it")

    def test_with_no_add_ledger_no_note_is_denied(self):
        self.note("analyzer-wrote-this.md")
        denied = self.denied(self.analyze())
        self.assertFalse(any("analyzer-wrote-this" in r for r in denied), denied)

    def test_a_stated_note_in_another_bucket_is_not_listed(self):
        other = os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "p2")
        os.makedirs(other)
        theirs = os.path.join(other, "elsewhere.md")
        with open(theirs, "w") as fh:
            fh.write("---\nid: elsewhere\n---\n")
        self.record_stated(theirs)
        self.assertFalse(any("elsewhere.md" in r for r in self.denied(self.analyze())))


class AnalyzeLaunchCase(AnalyzeChildBase):
    """B3: the analysis child cannot steer its own next run.

    It runs from an empty, engine-made folder outside its Edit grant (so a CLAUDE.md or
    .claude/settings.json it could write inside the grant is never in its working directory or
    above it), loads user settings only (--setting-sources user: no project or local settings),
    loads no MCP server (--strict-mcp-config), and is denied Edit on every .claude path,
    CLAUDE.md, CLAUDE.local.md, .mcp.json and settings file inside the grant. --bare is never
    passed: it accepts only API-key auth and would break subscription logins.

    Tested here: the argv and the working directory. Not testable without a live model: that
    Claude Code honours these flags as documented (see SKILL.md, nightly job step 2)."""

    def root(self):
        return "//" + os.path.realpath(self.instincts_dir).lstrip("/")

    def test_settings_and_mcp_flags_are_passed_and_bare_is_not(self):
        argv = self.analyze()["argv"]
        self.assertEqual(flag_values(argv, "--setting-sources"), ["user"])
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--bare", argv)
        self.assertEqual(flag_values(argv, "--allowedTools"), ["Read,Edit(" + self.root() + "/**)"],
                         "the grant itself is unchanged")
        self.assertEqual(argv[-2], "-p", "the prompt stays the last argument")

    def test_the_child_runs_from_an_empty_engine_folder_outside_the_grant_and_the_vault(self):
        # Files the analyzer could have planted inside its grant on an earlier run.
        os.makedirs(os.path.join(self.instincts_dir, ".claude"))
        with open(os.path.join(self.instincts_dir, ".claude", "settings.json"), "w") as fh:
            fh.write('{"hooks": {}}')
        with open(os.path.join(self.instincts_dir, "CLAUDE.md"), "w") as fh:
            fh.write("planted\n")
        call = self.analyze()
        cwd = os.path.realpath(call["cwd"])
        grant = os.path.realpath(self.instincts_dir)
        vault = os.path.realpath(self.sb.vault)
        self.assertFalse(cwd == grant or cwd.startswith(grant + os.sep), cwd)
        self.assertFalse(cwd == vault or cwd.startswith(vault + os.sep), cwd)
        self.assertFalse(grant.startswith(cwd + os.sep), "the grant must not sit below the child's cwd")
        obs = os.path.realpath(os.path.join(self.sb.tmp, "data", "neva", "observations"))
        self.assertTrue(cwd.startswith(obs + os.sep), f"{cwd} is not an engine-made folder under {obs}")
        self.assertEqual(call["cwd_listing"], [], "the child's folder starts empty")
        self.assertFalse(os.path.exists(cwd), "the engine removes the folder after the run")

    def test_config_files_inside_the_grant_are_denied(self):
        denied = self.denied(self.analyze())
        root = self.root()
        for rule in (f"Edit({root}/.claude/**)", f"Edit({root}/**/.claude/**)",
                     f"Edit({root}/CLAUDE.md)", f"Edit({root}/**/CLAUDE.md)",
                     f"Edit({root}/CLAUDE.local.md)", f"Edit({root}/**/CLAUDE.local.md)",
                     f"Edit({root}/.mcp.json)", f"Edit({root}/**/.mcp.json)",
                     f"Edit({root}/**/settings.json)", f"Edit({root}/**/settings.local.json)"):
            self.assertIn(rule, denied)

    def test_a_child_folder_inside_the_grant_is_refused(self):
        # Observations kept inside the instincts folder would put the child's folder in its grant.
        obs_root = os.path.join(self.instincts_dir, "obs")
        bucket = os.path.join(obs_root, self.PID)
        os.makedirs(bucket)
        with open(os.path.join(bucket, "observations.jsonl"), "w") as fh:
            for i in range(6):
                fh.write(json.dumps({"n": i}) + "\n")
        env = dict(self.sb.env, NEVA_CLAUDE_BIN=self.fake, FAKE_LOG_DIR=self.log_dir,
                   NEVA_INSTINCT_MIN_OBSERVATIONS="5", NEVA_OBSERVATIONS_DIR=obs_root)
        r = subprocess.run([PY, ANALYZE, "--project", self.PID], env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertIn("overlaps its Edit grant", r.stdout + r.stderr)
        self.assertIn("Fix:", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.log_dir, "argv.jsonl")), "the child must not start")
        with open(os.path.join(bucket, "observations.jsonl")) as fh:
            self.assertEqual(len(fh.readlines()), 6, "nothing unread is archived")


if __name__ == "__main__":
    unittest.main()
