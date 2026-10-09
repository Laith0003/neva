#!/usr/bin/env python3
"""Tests for the W5 learning-engine work: instinct-cli.py stats, the same-day
SessionEnd trigger (neva_hooks/learning_trigger.py), and instinct-analyze.py's
model routing env vars.

Unlike test_instinct_cli.py (pytest, left alone), this suite is stdlib
unittest so build/verify.sh's `python3 -m unittest discover` picks it up.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
LEARNING_SCRIPTS = os.path.join(
    REPO, "plugins", "neva-core", "skills", "continuous-learning-v2", "scripts")
CLI = os.path.join(LEARNING_SCRIPTS, "instinct-cli.py")
ANALYZE = os.path.join(LEARNING_SCRIPTS, "instinct-analyze.py")
HOOKS_DIR = os.path.join(REPO, "plugins", "neva-core", "hooks")
PY = sys.executable

FAKE_CLAUDE = """#!__PY__
import sys
sys.stdout.write('{"status":"analysis_complete"}\\n')
sys.exit(0)
"""


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstinctSandbox:
    """A throwaway HOME, vault, XDG tree and two fake git repos, same shape as
    test_instinct_cli.py's pytest fixture but reimplemented for unittest."""

    def __init__(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="neva-instinct-learning-"))
        self.home = os.path.join(self.tmp, "home")
        self.vault = os.path.join(self.tmp, "vault")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.vault, "00 Inbox"))
        os.makedirs(self.home)
        os.makedirs(self.bin)
        # Host NEVA_*, CLAUDE_*, ANTHROPIC_* and XDG_* vars never reach the child: a developer's
        # own NEVA_INBOX or NEVA_HOOK_PROFILE would otherwise change what these tests see.
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("NEVA_", "CLAUDE_", "ANTHROPIC_", "XDG_"))}
        self.env = dict(base, HOME=self.home, NEVA_VAULT=self.vault,
                         XDG_DATA_HOME=os.path.join(self.tmp, "data"),
                         XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                         PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        self.repos = {}
        for name in ("repoA", "repoB"):
            repo = os.path.join(self.tmp, name)
            os.makedirs(repo)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", f"https://github.com/example/{name}.git"],
                            cwd=repo, check=True)
            self.repos[name] = repo

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_exe(self, name, source):
        path = os.path.join(self.bin, name)
        with open(path, "w") as fh:
            fh.write(source.replace("__PY__", PY))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def run(self, *args, cwd="repoA", check=True, env=None):
        e = dict(self.env)
        e.update(env or {})
        result = subprocess.run([PY, CLI, *args], cwd=self.repos.get(cwd, cwd), env=e,
                                 capture_output=True, text=True)
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def add(self, cwd, iid, conf, domain="code-style", trigger="when handling errors in services"):
        self.run("add", "--id", iid, "--trigger", trigger, "--action", "Do the thing.",
                  "--domain", domain, "--confidence", str(conf), cwd=cwd)

    def proposal_path(self):
        return os.path.join(self.vault, "00 Inbox", f"Instinct promotions {date.today().isoformat()}.md")

    def tick(self, path, block_id, box):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index(f"block_id: {block_id}")
        idx = text.index(f"- [ ] {box}", start)
        text = text[:idx] + f"- [x] {box}" + text[idx + len(f"- [ ] {box}"):]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def remove_block(self, path, block_id):
        """Delete a whole block section without ticking reject, simulating a human who just
        deletes the candidate they do not want instead of ticking the checkbox."""
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        matches = list(re.finditer(r'^## .*\n<!-- block_id: (\S+) -->\n', text, re.M))
        for i, m in enumerate(matches):
            if m.group(1) == block_id:
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                text = text[:m.start()] + text[end:]
                break
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def events_path(self):
        return os.path.join(self.tmp, "state", "neva", "instincts", "promotion-events.jsonl")


class PromotionStatsCase(unittest.TestCase):
    """Ported from test_instinct_cli.py so verify.sh's unittest discovery sees it."""

    def setUp(self):
        self.sb = InstinctSandbox()

    def tearDown(self):
        self.sb.close()

    def test_stats_reports_the_promotion_approve_reject_rate(self):
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:prefer-explicit-errors", "approve")
        sb.run("apply-promotions")

        sb.add("repoA", "avoid-mocks", 0.9)
        sb.add("repoB", "avoid-mocks", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:avoid-mocks", "reject")
        sb.run("apply-promotions")

        out = sb.run("stats").stdout
        self.assertIn("PROMOTIONS_APPLIED: 1", out)
        self.assertIn("PROMOTIONS_REJECTED: 1", out)
        self.assertIn("PROMOTIONS_APPROVE_RATE: 0.50", out)

    def test_stats_reports_no_rate_before_any_decision(self):
        out = self.sb.run("stats").stdout
        self.assertIn("PROMOTIONS_APPLIED: 0", out)
        self.assertIn("PROMOTIONS_REJECTED: 0", out)
        self.assertIn("PROMOTIONS_APPROVE_RATE: n/a", out)


class PromotionEventsCase(unittest.TestCase):
    """The promotion-events.jsonl engine metric: one line per made/approved/rejected event,
    and instinct-cli.py stats's by-week breakdown over it."""

    def setUp(self):
        self.sb = InstinctSandbox()

    def tearDown(self):
        self.sb.close()

    def _week_key(self):
        y, w, _ = date.today().isocalendar()
        return f"{y}-W{w:02d}"

    def test_stats_reports_made_approved_rejected_and_by_week(self):
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:prefer-explicit-errors", "approve")
        sb.run("apply-promotions")

        sb.add("repoA", "avoid-mocks", 0.9)
        sb.add("repoB", "avoid-mocks", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:avoid-mocks", "reject")
        sb.run("apply-promotions")

        out = sb.run("stats").stdout
        self.assertIn("PROPOSALS_MADE: 2", out)
        self.assertIn("PROPOSALS_APPROVED: 1", out)
        self.assertIn("PROPOSALS_REJECTED: 1", out)
        self.assertIn("PROPOSALS_APPROVE_RATE: 0.50", out)
        m = re.search(r"PROPOSALS_BY_WEEK: (\{.*\})", out)
        self.assertIsNotNone(m, f"no PROPOSALS_BY_WEEK line in:\n{out}")
        by_week = json.loads(m.group(1))
        week = self._week_key()
        self.assertEqual(by_week[week]["made"], 2)
        self.assertEqual(by_week[week]["approved"], 1)
        self.assertEqual(by_week[week]["rejected"], 1)

    def test_block_removal_counts_as_rejected(self):
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        sb.remove_block(sb.proposal_path(), "promote-global:prefer-explicit-errors")
        sb.run("apply-promotions")
        out = sb.run("stats").stdout
        self.assertIn("PROPOSALS_REJECTED: 1", out)

    def _malform(self, block_id, how):
        path = self.sb.proposal_path()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        marker = f"<!-- block_id: {block_id} -->"
        head_end = text.rindex("\n", 0, text.index(marker))
        head_start = text.rindex("\n", 0, head_end) + 1
        if how == "blank line":
            text = text[:head_end] + "\n" + text[head_end:]
        else:
            text = text[:head_start] + "#" + text[head_start:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _assert_malformed_is_not_rejected(self, how):
        sb = self.sb
        bid = "promote-global:prefer-explicit-errors"
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        path = self._malform(bid, how)
        r = sb.run("apply-promotions", check=False)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(bid, r.stderr)
        self.assertIn("Fix:", r.stderr)
        out = sb.run("stats").stdout
        self.assertIn("PROPOSALS_REJECTED: 0", out, f"a {how} turned a pending block into a rejection")
        with open(path, encoding="utf-8") as fh:
            self.assertIn("status: open", fh.read(), "the proposal file must stay open")

    def test_blank_line_after_heading_is_an_error_not_a_rejection(self):
        self._assert_malformed_is_not_rejected("blank line")

    def test_demoted_heading_is_an_error_not_a_rejection(self):
        self._assert_malformed_is_not_rejected("demoted heading")

    def _outside(self):
        outside = os.path.join(self.sb.tmp, "outside")
        os.makedirs(outside)
        target = os.path.join(outside, "promotion-events.jsonl")
        with open(target, "wb") as fh:
            fh.write(b"owner data\n")
        return outside, target

    def _propose_one(self):
        self.sb.add("repoA", "prefer-explicit-errors", 0.9)
        self.sb.add("repoB", "prefer-explicit-errors", 0.85)
        return self.sb.run("propose", check=False)

    def test_event_log_leaf_symlink_is_refused(self):
        outside, target = self._outside()
        events = self.sb.events_path()
        os.makedirs(os.path.dirname(events))
        os.symlink(target, events)
        r = self._propose_one()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(events, r.stderr)
        self.assertIn("symlink", r.stderr)
        self.assertIn("Fix:", r.stderr)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"owner data\n", "the event was appended outside the state dir")

    def test_event_log_parent_symlink_is_refused(self):
        outside, target = self._outside()
        instincts = os.path.dirname(self.sb.events_path())
        os.makedirs(os.path.dirname(instincts))
        os.symlink(outside, instincts)
        r = self._propose_one()
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(instincts, r.stderr)
        self.assertIn("symlink", r.stderr)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"owner data\n", "the event was appended through a symlinked dir")
        self.assertEqual(sorted(os.listdir(outside)), ["promotion-events.jsonl"])

    def _assert_stats_fails_on_line(self, bad_line):
        """A damaged event history must fail stats loudly, naming the file, the line and the
        repair, and leave the file exactly as it was: never silently drop events."""
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        events_path = sb.events_path()
        with open(events_path, "a", encoding="utf-8") as fh:
            fh.write(bad_line + "\n")
        with open(events_path, "rb") as fh:
            before = fh.read()
        r = sb.run("stats", check=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(events_path, r.stderr)
        self.assertIn("line 2", r.stderr)
        self.assertIn("Fix:", r.stderr)
        self.assertNotIn("PROPOSALS_MADE", r.stdout, "stats printed partial metrics")
        with open(events_path, "rb") as fh:
            self.assertEqual(fh.read(), before, "stats changed the event file")

    def _vault_snapshot(self):
        snap = {}
        for dirpath, _, files in os.walk(self.sb.vault):
            for name in files:
                p = os.path.join(dirpath, name)
                with open(p, "rb") as fh:
                    snap[os.path.relpath(p, self.sb.vault)] = fh.read()
        return snap

    def _relocate_instincts_by_symlink(self):
        """The owner moved the instincts state dir elsewhere and left a symlink behind."""
        instincts = os.path.dirname(self.sb.events_path())
        elsewhere = os.path.join(self.sb.tmp, "elsewhere", "instincts")
        os.makedirs(os.path.dirname(elsewhere))
        if os.path.isdir(instincts):
            shutil.move(instincts, elsewhere)
        else:
            os.makedirs(elsewhere)
            os.makedirs(os.path.dirname(instincts), exist_ok=True)
        os.symlink(elsewhere, instincts)
        return instincts, elsewhere

    def _dir_snapshot(self, d):
        out = {}
        for name in sorted(os.listdir(d)):
            with open(os.path.join(d, name), "rb") as fh:
                out[name] = fh.read()
        return out

    def _assert_refused_cleanly(self, r, instincts, before_vault, elsewhere, before_elsewhere):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(self._vault_snapshot()), sorted(before_vault), "files appeared in the vault")
        self.assertEqual(self._vault_snapshot(), before_vault, "the vault (proposal, inbox, notes) changed")
        self.assertEqual(self._dir_snapshot(elsewhere), before_elsewhere, "state was written through the link")
        self.assertIn(instincts, r.stderr)
        self.assertIn("NEVA_INSTINCT_STATE_DIR", r.stderr, "the error must name the supported relocation")

    def test_refused_state_dir_leaves_propose_with_no_side_effects(self):
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        instincts, elsewhere = self._relocate_instincts_by_symlink()
        before_vault, before_elsewhere = self._vault_snapshot(), self._dir_snapshot(elsewhere)
        r = sb.run("propose", check=False)
        self._assert_refused_cleanly(r, instincts, before_vault, elsewhere, before_elsewhere)
        self.assertFalse(os.path.exists(sb.proposal_path()), "a proposal file was written")

    def test_refused_state_dir_leaves_apply_with_no_side_effects(self):
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:prefer-explicit-errors", "approve")
        instincts, elsewhere = self._relocate_instincts_by_symlink()
        before_vault, before_elsewhere = self._vault_snapshot(), self._dir_snapshot(elsewhere)
        r = sb.run("apply-promotions", check=False)
        self._assert_refused_cleanly(r, instincts, before_vault, elsewhere, before_elsewhere)

    def test_stats_fails_on_an_unparseable_event_line(self):
        self._assert_stats_fails_on_line("not valid json")

    def test_stats_fails_on_an_event_with_the_wrong_shape(self):
        self._assert_stats_fails_on_line('{"ts": "2026-10-01T00:00:00Z", "event": "liked", "block_id": "x"}')

    def test_stats_fails_on_an_event_missing_its_block_id(self):
        self._assert_stats_fails_on_line('{"ts": "2026-10-01T00:00:00Z", "event": "made"}')


class LearningTriggerCase(unittest.TestCase):
    """neva_hooks.learning_trigger: the same-day SessionEnd trigger. Fixtures use /home/user
    and example.com only, never a real path."""

    ENV_KEYS = ("HOME", "NEVA_DATA_DIR", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "NEVA_STATE_DIR", "NEVA_OBSERVATIONS_DIR", "NEVA_HEADLESS", "NEVA_INSTINCT_SAMEDAY",
                "NEVA_INSTINCT_SAMEDAY_MIN", "NEVA_INSTINCT_SAMEDAY_HOURS",
                "NEVA_INSTINCT_MIN_OBSERVATIONS")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="neva-sameday-trigger-")
        self.state_root = os.path.join(self.tmp, "state")
        self.obs_root = os.path.join(self.tmp, "observations")
        os.makedirs(self.state_root)
        os.makedirs(self.obs_root)
        self.marker = os.path.join(self.tmp, "fired.marker")
        self.stub = os.path.join(self.tmp, "fake-analyze.py")
        with open(self.stub, "w") as fh:
            fh.write(f"#!{PY}\nimport pathlib\npathlib.Path({self.marker!r}).write_text('fired')\n")
        os.chmod(self.stub, 0o755)

        self._saved_env = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)
        # HOME and NEVA_DATA_DIR too: c.log() writes hooks.log under the data dir, and a test
        # must never touch the real ~/.local/share/neva.
        self.data_dir = os.path.join(self.tmp, "data")
        os.environ["HOME"] = os.path.join(self.tmp, "home")
        os.environ["NEVA_DATA_DIR"] = self.data_dir
        os.environ["NEVA_STATE_DIR"] = self.state_root
        os.environ["NEVA_OBSERVATIONS_DIR"] = self.obs_root
        # The trigger is opt-in (review H1). Every test below that expects a launch opts in
        # here; the opt-in tests remove it again to prove the default is off.
        os.environ["NEVA_INSTINCT_SAMEDAY"] = "1"

        if HOOKS_DIR not in sys.path:
            sys.path.insert(0, HOOKS_DIR)
        sys.modules.pop("neva_hooks.learning_trigger", None)
        sys.modules.pop("neva_hooks", None)
        sys.modules.pop("neva_hooks.common", None)
        import importlib
        self.module = importlib.import_module("neva_hooks.learning_trigger")
        self.module.ANALYZE = Path(self.stub)
        # Record every child the trigger launches so tearDown can reap it: an unreaped stub
        # prints a ResourceWarning into output that verify.sh captures and greps.
        self.children = []
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            self.children.append(proc)
            return proc

        patcher = mock.patch.object(self.module.subprocess, "Popen", spawn)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for proc in self.children:
            proc.wait(timeout=10)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_observations(self, pid, n):
        d = os.path.join(self.obs_root, pid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "observations.jsonl"), "w") as fh:
            for _ in range(n):
                fh.write('{"x":1}\n')

    def _fired(self, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(self.marker):
                return True
            time.sleep(0.05)
        return os.path.exists(self.marker)

    def test_fires_when_threshold_met_and_hours_elapsed(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "6"
        self.module.run(None)
        self.assertTrue(self._fired(), "expected instinct-analyze.py to be launched")

    def test_no_analysis_starts_without_the_opt_in(self):
        """Fail closed: enough observations and no cooldown, but NEVA_INSTINCT_SAMEDAY unset, so
        no analysis job (and no paid model call) may start."""
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        os.environ.pop("NEVA_INSTINCT_SAMEDAY", None)
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.5), "the same-day trigger launched analysis without opt-in")

    def test_opt_in_must_be_exactly_1(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        for value in ("", "0", "no", "off", "false", "yes", "true"):
            os.environ["NEVA_INSTINCT_SAMEDAY"] = value
            self.module.run(None)
            self.assertFalse(self._fired(timeout=0.3), f"NEVA_INSTINCT_SAMEDAY={value!r} launched analysis")

    def test_sub_threshold_buckets_never_fire_however_many(self):
        """20 projects with 15 observations each: 300 in total, but the analyzer skips every
        bucket under its own minimum (20), so a launch could never make progress."""
        for i in range(20):
            self._write_observations(f"p{i}", 15)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.5), "fired on buckets the analyzer would skip")

    def test_only_eligible_buckets_count_toward_the_minimum(self):
        self._write_observations("big", 150)
        for i in range(10):
            self._write_observations(f"small{i}", 15)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.5), "150 eligible plus 150 ineligible must not reach 200")
        self._write_observations("big2", 60)
        self.module.run(None)
        self.assertTrue(self._fired(), "150 + 60 eligible observations reach 200")

    def test_uses_the_analyzer_minimum_override(self):
        for i in range(20):
            self._write_observations(f"p{i}", 15)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        os.environ["NEVA_INSTINCT_MIN_OBSERVATIONS"] = "10"
        self.module.run(None)
        self.assertTrue(self._fired(), "with an analyzer minimum of 10 every bucket qualifies")

    def _write_pending(self, pid, n, name="observations-20261001-000000-1.jsonl"):
        d = os.path.join(self.obs_root, pid, "observations.pending")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as fh:
            for _ in range(n):
                fh.write('{"x":1}\n')

    def test_pending_only_bucket_fires(self):
        """The observe hook rotated a big unread backlog into observations.pending and no live
        file exists yet: the analyzer would process it, so the trigger must count it."""
        self._write_pending("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        self.module.run(None)
        self.assertTrue(self._fired(), "a pending-only backlog of 250 must reach 200")

    def test_pending_and_live_combine_within_a_bucket(self):
        # p1: 12 pending + 12 live, each under the analyzer minimum of 20, together 24 (eligible).
        # p2: 180 live. Only p1's combined count takes the total to 204.
        self._write_pending("p1", 12)
        self._write_observations("p1", 12)
        self._write_observations("p2", 180)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        self.module.run(None)
        self.assertTrue(self._fired(), "180 + (12 pending + 12 live) is 204 eligible observations")

    def test_line_count_stops_once_the_answer_is_known(self):
        """SessionEnd must not read a whole 5 MB file to compare it with 300: instrument every
        byte read through open() (builtins and io, so Path.read_bytes is seen too) and bound it."""
        line = b'{"x":"' + b"a" * 1000 + b'"}\n'
        d = Path(self.obs_root) / "p1"
        d.mkdir(parents=True)
        path = d / "observations.jsonl"
        path.write_bytes(line * 5000)
        counted = [0]

        class Counting:
            def __init__(self, fh):
                self._fh = fh

            def _add(self, data):
                counted[0] += len(data or b"")
                return data

            def read(self, *a):
                return self._add(self._fh.read(*a))

            def readline(self, *a):
                return self._add(self._fh.readline(*a))

            def readlines(self, *a):
                lines = self._fh.readlines(*a)
                counted[0] += sum(len(x) for x in lines)
                return lines

            def readinto(self, buf):
                n = self._fh.readinto(buf)
                counted[0] += n or 0
                return n

            def __iter__(self):
                for item in self._fh:
                    counted[0] += len(item)
                    yield item

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._fh.__exit__(*exc)

            def __getattr__(self, name):
                return getattr(self._fh, name)

        import builtins
        import io
        real_open = io.open

        def counting_open(*a, **k):
            return Counting(real_open(*a, **k))

        with mock.patch.object(builtins, "open", counting_open), mock.patch.object(io, "open", counting_open):
            n = self.module._count_lines(path, stop_at=300)
        self.assertEqual(n, 300)
        self.assertGreater(counted[0], 0, "the instrumentation saw no reads at all")
        bound = 300 * len(line) + self.module._CHUNK
        self.assertLessEqual(counted[0], bound,
                             f"read {counted[0]} bytes of {len(line) * 5000} to count 300 lines (bound {bound})")
        self.assertEqual(self.module._count_lines(path, stop_at=10 ** 9), 5000)

    def test_no_trigger_below_observation_threshold(self):
        self._write_observations("p1", 10)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.3))

    def test_no_trigger_within_hours_window(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "6"
        lock_path = Path(self.state_root) / "instinct-analyze.lock"
        lock_path.touch()
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.3))

    def test_second_trigger_blocked_by_held_lock(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        lock_path = Path(self.state_root) / "instinct-analyze.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = open(lock_path, "a+")
        import fcntl
        fcntl.flock(held, fcntl.LOCK_EX)
        try:
            self.module.run(None)
            self.assertFalse(self._fired(timeout=0.3))
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
            held.close()

    def test_log_lines_land_in_the_sandbox_data_dir(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        self.module.ANALYZE = Path(self.tmp) / "missing-analyze.py"
        self.module.run(None)
        log = Path(self.data_dir) / "hooks.log"
        self.assertTrue(log.exists(), "hooks.log must be written under the sandbox NEVA_DATA_DIR")
        self.assertIn("[learning_trigger]", log.read_text())

    def _run_real_analyzer(self):
        vault = os.path.join(self.tmp, "vault")
        os.makedirs(os.path.join(vault, "00 Inbox"), exist_ok=True)
        fake = os.path.join(self.tmp, "fake-claude")
        with open(fake, "w") as fh:
            fh.write(FAKE_CLAUDE.replace("__PY__", PY))
        os.chmod(fake, 0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ANTHROPIC_", "XDG_"))}
        env.update(NEVA_VAULT=vault, NEVA_CLAUDE_BIN=fake, NEVA_INSTINCT_MIN_OBSERVATIONS="5")
        r = subprocess.run([PY, ANALYZE], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_a_real_analyzer_run_rearms_the_cooldown(self):
        """The cooldown reads the lock's mtime, so a real run must refresh it. Age the lock, run
        the real analyzer, then a SessionEnd with fresh observations must not launch again."""
        lock_path = os.path.join(self.state_root, "instinct-analyze.lock")
        with open(lock_path, "w"):
            pass
        aged = time.time() - 7 * 3600
        os.utime(lock_path, (aged, aged))
        self._write_observations("p1", 30)
        out = self._run_real_analyzer()
        self.assertIn("archived", out)
        self.assertGreater(os.stat(lock_path).st_mtime, aged + 3600, "the analyzer run left the lock aged")
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "6"
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.5), "fired again right after a real analyzer run")
        # control: the same state with the lock aged again does fire, so the cooldown was the reason
        os.utime(lock_path, (aged, aged))
        self.module.run(None)
        self.assertTrue(self._fired(), "the control never fires, so the test proves nothing")

    def _symlinked_lock(self, target):
        lock_path = os.path.join(self.state_root, "instinct-analyze.lock")
        os.symlink(target, lock_path)
        return lock_path

    def test_symlinked_lock_is_refused_and_the_target_untouched(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        outside = os.path.join(self.tmp, "owner-file.txt")
        with open(outside, "wb") as fh:
            fh.write(b"owner data\n")
        os.utime(outside, (time.time() - 86400, time.time() - 86400))
        lock_path = self._symlinked_lock(outside)
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.5), "launched through a symlinked lock")
        with open(outside, "rb") as fh:
            self.assertEqual(fh.read(), b"owner data\n")
        log = (Path(self.data_dir) / "hooks.log").read_text()
        self.assertIn(lock_path, log)
        self.assertIn("symlink", log)

    def test_dangling_lock_symlink_creates_nothing_outside(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        outside = os.path.join(self.tmp, "not-yet-there.txt")
        self._symlinked_lock(outside)
        self.module.run(None)
        self.assertFalse(os.path.exists(outside), "the probe created a file outside the state root")
        self.assertFalse(self._fired(timeout=0.5))

    def test_no_op_under_headless(self):
        self._write_observations("p1", 250)
        os.environ["NEVA_INSTINCT_SAMEDAY_MIN"] = "200"
        os.environ["NEVA_INSTINCT_SAMEDAY_HOURS"] = "0"
        os.environ["NEVA_HEADLESS"] = "1"
        self.module.run(None)
        self.assertFalse(self._fired(timeout=0.3))


class ModelRoutingEnvCase(unittest.TestCase):
    """instinct-analyze.py's child env gains ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN only when
    NEVA_INSTINCT_BASE_URL/NEVA_INSTINCT_AUTH_TOKEN are set (env construction originally at
    instinct-analyze.py:200, now factored into _child_env())."""

    def setUp(self):
        self.analyze = _load_module(ANALYZE, "neva_instinct_analyze_test")
        self._saved = {k: os.environ.get(k) for k in
                       ("NEVA_INSTINCT_BASE_URL", "NEVA_INSTINCT_AUTH_TOKEN",
                        "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unset_leaves_the_child_env_unchanged(self):
        os.environ["ANTHROPIC_API_KEY"] = "sentinel-key-not-real"
        env = self.analyze._child_env()
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), "sentinel-key-not-real",
                         "an existing API key must reach the child untouched when no routing var is set")

    def test_base_url_and_token_route_to_anthropic_vars(self):
        os.environ["NEVA_INSTINCT_BASE_URL"] = "https://example.com/v1"
        os.environ["NEVA_INSTINCT_AUTH_TOKEN"] = "test-token-no-real-secret"
        env = self.analyze._child_env()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://example.com/v1")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "test-token-no-real-secret")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")

    def test_base_url_alone_keeps_the_existing_api_key(self):
        """A gateway that forwards the owner's own key: setting only the base URL must not leave
        the child with no credential at all."""
        os.environ["NEVA_INSTINCT_BASE_URL"] = "https://example.com/v1"
        os.environ["ANTHROPIC_API_KEY"] = "sentinel-key-not-real"
        env = self.analyze._child_env()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://example.com/v1")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sentinel-key-not-real")

    def test_auth_token_alone_clears_the_api_key(self):
        os.environ["NEVA_INSTINCT_AUTH_TOKEN"] = "test-token-no-real-secret"
        os.environ["ANTHROPIC_API_KEY"] = "sentinel-key-not-real"
        env = self.analyze._child_env()
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "test-token-no-real-secret")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")


RECORDING_CLAUDE = """#!__PY__
import json, os, re, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
path = re.search(r"(\\S+\\.analyze-tmp/analysis\\.\\S+?\\.jsonl)", prompt).group(1)
log_dir = os.environ["FAKE_LOG_DIR"]
calls = os.path.join(log_dir, "calls.jsonl")
n = sum(1 for _ in open(calls)) + 1 if os.path.exists(calls) else 1
with open(path) as fh:
    lines = [json.loads(x)["n"] for x in fh if x.strip()]
env = {k: os.environ.get(k) for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")}
with open(calls, "a") as fh:
    fh.write(json.dumps({"call": n, "lines": lines, "env": env}) + "\\n")
if os.environ.get("FAKE_FAIL_ON_CALL") == str(n):
    sys.stderr.write("simulated model failure\\n")
    sys.exit(1)
sys.stdout.write('{"status":"analysis_complete"}\\n')
"""


class AnalyzeBatchCase(unittest.TestCase):
    """instinct-analyze.py must never archive an observation it did not send to the model. It
    analyses a bucket oldest first in batches of at most max_analysis_lines, archives each batch
    only after that batch succeeds, and leaves anything it did not reach in place."""

    PID = "p1"

    def setUp(self):
        self.sb = InstinctSandbox()
        self.fake = self.sb.write_exe("fake-claude", RECORDING_CLAUDE)
        self.log_dir = os.path.join(self.sb.tmp, "fake-log")
        os.makedirs(self.log_dir)
        self.bucket = os.path.join(self.sb.tmp, "data", "neva", "observations", self.PID)
        os.makedirs(self.bucket)
        self.obs = os.path.join(self.bucket, "observations.jsonl")

    def tearDown(self):
        self.sb.close()

    def write_obs(self, n, start=0):
        with open(self.obs, "a") as fh:
            for i in range(start, start + n):
                fh.write(json.dumps({"n": i}) + "\n")

    def analyze(self, **env):
        e = dict(self.sb.env, NEVA_CLAUDE_BIN=self.fake, FAKE_LOG_DIR=self.log_dir,
                 NEVA_INSTINCT_MAX_ANALYSIS_LINES="10", NEVA_INSTINCT_MIN_OBSERVATIONS="5")
        e.update(env)
        r = subprocess.run([PY, ANALYZE, "--project", self.PID], env=e, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def calls(self):
        path = os.path.join(self.log_dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def pending(self):
        if not os.path.exists(self.obs):
            return []
        with open(self.obs) as fh:
            return [json.loads(x)["n"] for x in fh if x.strip()]

    def archived(self):
        arch = os.path.join(self.bucket, "observations.archive")
        out = []
        for name in sorted(os.listdir(arch)) if os.path.isdir(arch) else []:
            with open(os.path.join(arch, name)) as fh:
                out += [json.loads(x)["n"] for x in fh if x.strip()]
        return sorted(out)

    def write_pending(self, name, numbers):
        pend = os.path.join(self.bucket, "observations.pending")
        os.makedirs(pend, exist_ok=True)
        with open(os.path.join(pend, name), "w") as fh:
            for i in numbers:
                fh.write(json.dumps({"n": i}) + "\n")

    def pending_files(self):
        pend = os.path.join(self.bucket, "observations.pending")
        return sorted(os.listdir(pend)) if os.path.isdir(pend) else []

    def test_a_rotated_file_is_analysed_before_it_is_archived(self):
        # the observe hook moved a full file aside at its size limit; it was never analysed
        self.write_pending("observations-20261001-000000-1.jsonl", range(0, 12))
        self.write_obs(8, start=12)
        self.analyze()
        analysed = sorted(n for call in self.calls() for n in call["lines"])
        self.assertEqual(analysed, list(range(20)), "rotated observations reach the model too")
        self.assertEqual(self.archived(), list(range(20)))
        self.assertEqual(self.pending_files(), [], "a fully analysed rotated file is gone from pending")

    def test_rotated_files_go_first_and_the_cap_leaves_the_rest(self):
        self.write_pending("observations-20261001-000000-1.jsonl", range(0, 10))
        self.write_obs(10, start=10)
        self.analyze(NEVA_INSTINCT_MAX_BATCHES="1")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(calls[0]["lines"]), list(range(10)), "oldest (rotated) first")
        self.assertEqual(self.pending(), list(range(10, 20)), "live file untouched, nothing lost")

    def test_negative_control_a_failed_batch_keeps_the_rotated_file(self):
        self.write_pending("observations-20261001-000000-1.jsonl", range(0, 10))
        self.analyze(FAKE_FAIL_ON_CALL="1")
        self.assertEqual(self.archived(), [], "nothing archived when the model call failed")
        self.assertEqual(self.pending_files(), ["observations-20261001-000000-1.jsonl"])

    def test_every_archived_observation_was_analysed(self):
        self.write_obs(25)
        self.analyze()
        analysed = sorted(n for call in self.calls() for n in call["lines"])
        self.assertEqual(analysed, list(range(25)), "every observation reaches the model exactly once")
        self.assertTrue(all(len(call["lines"]) <= 10 for call in self.calls()), "no batch exceeds N")
        self.assertEqual(self.archived(), list(range(25)))
        self.assertEqual(self.pending(), [])

    def test_batch_cap_leaves_the_rest_in_place(self):
        self.write_obs(25)
        self.analyze(NEVA_INSTINCT_MAX_BATCHES="1")
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.archived(), sorted(calls[0]["lines"]), "only what the model saw is archived")
        self.assertEqual(sorted(self.pending() + self.archived()), list(range(25)), "nothing is lost")
        self.assertEqual(calls[0]["lines"], list(range(len(calls[0]["lines"]))), "oldest first")

    def test_failed_batch_keeps_it_and_everything_after(self):
        self.write_obs(25)
        out = self.analyze(FAKE_FAIL_ON_CALL="2")
        calls = self.calls()
        self.assertEqual(len(calls), 2, out)
        self.assertEqual(self.archived(), sorted(calls[0]["lines"]))
        self.assertEqual(self.pending(), [n for n in range(25) if n not in calls[0]["lines"]])
        self.assertIn("observations retained for retry", out)

    def discovered(self):
        """Every observation number the analyzer's own source discovery would read next run."""
        mod = _load_module(ANALYZE, "neva_instinct_analyze_discovery")
        out = []
        for src in mod.learning_io.observation_sources(Path(self.bucket)):
            with open(src) as fh:
                out += [json.loads(x)["n"] for x in fh if x.strip()]
        return sorted(out)

    def _archive_with_failure(self, target):
        """Call archive_analyzed in-process with `target` (a learning_io function) raising
        ENOSPC, the way a full disk or a denied write would."""
        mod = _load_module(ANALYZE, "neva_instinct_analyze_fail")
        obs = Path(self.obs)
        chunk = b"".join(mod._complete_lines(obs)[:6])
        root = Path(self.bucket).parent
        archive = Path(self.bucket) / "observations.archive"
        with mock.patch.object(mod.learning_io, target, side_effect=OSError(28, "No space left on device")):
            try:
                mod.archive_analyzed(obs, chunk, archive, root)
            except OSError:
                pass

    def test_archive_write_failure_keeps_every_line_discoverable(self):
        self.write_obs(20)
        self._archive_with_failure("write_new")
        self.assertEqual(self.discovered(), list(range(20)), "a failed archive write stranded observations")
        self.analyze()
        self.assertEqual(self.archived(), list(range(20)), "the retry did not reach every observation")

    def test_tail_write_failure_keeps_every_line_discoverable(self):
        self.write_obs(20)
        self._archive_with_failure("open_append")
        self.assertEqual(sorted(set(self.discovered())), list(range(20)),
                         "a failed write after the move stranded observations")
        self.analyze()
        self.assertEqual(sorted(set(self.archived())), list(range(20)))

    def test_interrupted_run_leftover_is_recovered_with_later_appends(self):
        # a run renamed the live file aside and died: the leftover holds 0..11, and the observe
        # hook has since started a new live file with 12..19
        leftover = os.path.join(self.bucket, ".observations.analyzing-20261001-000000-000000-999.jsonl")
        with open(leftover, "w") as fh:
            for i in range(12):
                fh.write(json.dumps({"n": i}) + "\n")
        self.write_obs(8, start=12)
        self.analyze()
        analysed = sorted(n for call in self.calls() for n in call["lines"])
        self.assertEqual(analysed, list(range(20)), "the interrupted run's observations were never read")
        self.assertEqual(self.archived(), list(range(20)))
        self.assertFalse(os.path.exists(leftover))

    def test_failed_archive_of_a_pending_file_restores_its_own_name(self):
        name = "observations-20261001-000000-1.jsonl"
        self.write_pending(name, range(10))
        src = Path(self.bucket) / "observations.pending" / name
        before = src.read_bytes()
        mod = _load_module(ANALYZE, "neva_instinct_analyze_restore")
        chunk = b"".join(mod._complete_lines(src)[:6])
        with mock.patch.object(mod.learning_io, "open_append", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                mod.archive_analyzed(src, chunk, Path(self.bucket) / "observations.archive",
                                     Path(self.bucket).parent)
        self.assertEqual(self.pending_files(), [name], "the restored file lost its place in the order")
        self.assertEqual(src.read_bytes(), before)

    def test_recovered_pending_leftover_keeps_its_place_in_the_order(self):
        # the crashed run (stamp 2026-10-05) was archiving the oldest pending file (2026-10-01);
        # a newer one (2026-10-02) waits behind it and must still come second
        old = "observations-20261001-000000-1.jsonl"
        self.write_pending(".observations.analyzing-20261005-000000-000000-999--" + old, range(0, 10))
        self.write_pending("observations-20261002-000000-1.jsonl", range(10, 20))
        self.analyze(NEVA_INSTINCT_MAX_BATCHES="1")
        self.assertEqual(sorted(self.calls()[0]["lines"]), list(range(10)), "the recovered file jumped the queue")

    def test_interrupted_pending_leftover_is_recovered(self):
        pend = os.path.join(self.bucket, "observations.pending")
        os.makedirs(pend)
        leftover = os.path.join(pend, ".observations.analyzing-20261001-000000-000000-999.jsonl")
        with open(leftover, "w") as fh:
            for i in range(12):
                fh.write(json.dumps({"n": i}) + "\n")
        self.analyze()
        self.assertEqual(self.archived(), list(range(12)))
        self.assertEqual(os.listdir(pend), [], "nothing hidden is left behind in pending")

    def outside_dir(self):
        outside = os.path.join(self.sb.tmp, "outside")
        os.makedirs(outside)
        sentinel = os.path.join(outside, "owner.txt")
        with open(sentinel, "wb") as fh:
            fh.write(b"owner data\n")
        return outside, sentinel

    def assert_outside_untouched(self, outside, sentinel):
        self.assertEqual(sorted(os.listdir(outside)), ["owner.txt"], "something was written outside the root")
        with open(sentinel, "rb") as fh:
            self.assertEqual(fh.read(), b"owner data\n")

    def test_symlinked_archive_dir_is_refused(self):
        outside, sentinel = self.outside_dir()
        link = os.path.join(self.bucket, "observations.archive")
        os.symlink(outside, link)
        self.write_obs(12)
        out = self.analyze()
        self.assert_outside_untouched(outside, sentinel)
        self.assertIn(link, out)
        self.assertIn("symlink", out)
        self.assertEqual(self.calls(), [], "the model ran although its batch could never be archived")
        self.assertEqual(self.pending(), list(range(12)), "every observation stays in place")

    def test_symlinked_temp_dir_is_refused(self):
        outside, sentinel = self.outside_dir()
        link = os.path.join(self.bucket, ".analyze-tmp")
        os.symlink(outside, link)
        self.write_obs(12)
        out = self.analyze()
        self.assert_outside_untouched(outside, sentinel)
        self.assertIn(link, out)
        self.assertIn("symlink", out)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.pending(), list(range(12)))

    def test_symlinked_observation_file_is_refused(self):
        outside, sentinel = self.outside_dir()
        os.remove(sentinel)
        with open(sentinel, "w") as fh:
            for i in range(12):
                fh.write(json.dumps({"n": i}) + "\n")
        with open(sentinel, "rb") as fh:
            before = fh.read()
        os.symlink(sentinel, self.obs)
        out = self.analyze()
        with open(sentinel, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertTrue(os.path.islink(self.obs), "the managed symlink was replaced")
        self.assertIn(self.obs, out)
        self.assertIn("symlink", out)
        self.assertEqual(self.calls(), [])
        self.assertEqual(sorted(os.listdir(outside)), ["owner.txt"])

    def test_symlinked_analyzer_lock_is_refused(self):
        outside, sentinel = self.outside_dir()
        lock = os.path.join(self.sb.tmp, "state", "neva", "instinct-analyze.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        os.symlink(sentinel, lock)
        self.write_obs(12)
        e = dict(self.sb.env, NEVA_CLAUDE_BIN=self.fake, FAKE_LOG_DIR=self.log_dir,
                 NEVA_INSTINCT_MIN_OBSERVATIONS="5")
        r = subprocess.run([PY, ANALYZE, "--project", self.PID], env=e, capture_output=True, text=True,
                           timeout=120)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(lock, r.stdout + r.stderr)
        self.assertIn("symlink", r.stdout + r.stderr)
        self.assert_outside_untouched(outside, sentinel)
        self.assertEqual(self.calls(), [])

    def test_routing_env_reaches_the_real_child(self):
        self.write_obs(6)
        self.analyze(NEVA_INSTINCT_BASE_URL="https://example.com/v1",
                     NEVA_INSTINCT_AUTH_TOKEN="test-token-no-real-secret",
                     ANTHROPIC_API_KEY="sentinel-key-not-real")
        env = self.calls()[0]["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://example.com/v1")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "test-token-no-real-secret")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")


if __name__ == "__main__":
    unittest.main()
