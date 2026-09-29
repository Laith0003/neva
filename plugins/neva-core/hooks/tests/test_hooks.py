#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""End-to-end tests for the neva-core hook runtime. Standard library unittest only.

Every test runs against a COPY of the hooks folder (the way an installed plugin lives in a cache),
with a temporary HOME, a temporary vault and realistic hook JSON on stdin.

Run:  python3 plugins/neva-core/hooks/tests/test_hooks.py
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_SRC = os.path.dirname(SRC)
CL2_SRC = os.path.join(PLUGIN_SRC, "skills", "continuous-learning-v2")
PY = sys.executable


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class Sandbox:
    """Temp HOME + vault + git project + copied plugin (hooks plus the continuous-learning-v2
    skill, which the instinct shim calls)."""

    def __init__(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="neva-hooks-test-"))
        self.home = os.path.join(self.tmp, "home")
        self.vault = os.path.join(self.tmp, "vault")
        self.work = os.path.join(self.tmp, "work", "proj")
        self.plugin = os.path.join(self.tmp, "cache", "neva-core")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.home, self.work, self.bin):
            os.makedirs(d)
        shutil.copytree(SRC, os.path.join(self.plugin, "hooks"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
        shutil.copytree(CL2_SRC, os.path.join(self.plugin, "skills", "continuous-learning-v2"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
        self.hooks = os.path.join(self.plugin, "hooks")
        self.data = os.path.join(self.home, ".local", "share", "neva")
        self.state = os.path.join(self.home, ".local", "state", "neva")
        subprocess.run(["git", "init", "-q", self.work], check=True)
        # no remote: the canonical id hashes the main worktree root
        self.pid = hashlib.sha256(self.work.encode()).hexdigest()[:12]
        self._vault()

    def _vault(self):
        w = self.write
        w("vault/Templates/Daily Note.md", "---\ntags: [journal]\ndate: {{date}}\nstatus: open\n---\n\n# {{date}}\n\n"
          "## Today\n-\n\n## Open threads\n-\n")
        w("vault/00 Inbox/README.md", "Quick captures land here.\n")
        w("vault/00 Inbox/inbox.md", "# Inbox\n\n## Open actions\n- [ ] Call the plumber about the leak\n\n"
          "## Someday\n- learn the cello\n")
        w("vault/00 Inbox/idea about bikes.md", "a capture\n")
        w("vault/GOALS.md", "# Goals\n\n## Ship the reader app\nwhy: it pays the rent\ndone means: 100 users\n")
        w("vault/01 Projects/README.md", "One note per project.\n")
        w("vault/01 Projects/Alpha.md", f"---\ntags: [project]\nstatus: active\ncode: {self.work}\n---\n\n# Alpha\n\n"
          "## Done means\n- beta in 20 hands\n\n## Current state\n- importer half built, blocked on auth\n")
        w("vault/01 Projects/Old.md", "---\nstatus: archived\n---\n\n## Current state\n- dead\n")
        os.makedirs(os.path.join(self.vault, "08 Journal"), exist_ok=True)

    def write(self, rel, text, mode=None):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode:
            os.chmod(p, mode)
        return p

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def env(self, **extra):
        keep = {k: v for k, v in os.environ.items()
                if not k.startswith(("NEVA_", "CLAUDE_", "COMPACT_", "GATEGUARD_", "XDG_")) and k != "TMUX"}
        keep.update({"HOME": self.home, "NEVA_VAULT": self.vault, "NEVA_CONFIG": os.path.join(self.home, "none.env"),
                     "CLAUDE_PLUGIN_ROOT": self.plugin, "NEVA_TIMEZONE": "UTC",
                     "PATH": self.bin + os.pathsep + os.environ.get("PATH", "")})
        for k, v in extra.items():
            if v is None:
                keep.pop(k, None)
            else:
                keep[k] = str(v)
        return keep

    def dispatch(self, event, payload, group=None, stdin=None, **env):
        argv = [PY, os.path.join(self.hooks, "dispatch.py"), event] + ([group] if group else [])
        data = stdin if stdin is not None else json.dumps(payload)
        p = subprocess.run(argv, input=data, capture_output=True, text=True, env=self.env(**env), cwd=self.work,
                           timeout=60)
        out = json.loads(p.stdout) if p.stdout.strip() else {}
        return Result(p.returncode, p.stdout, p.stderr, out)

    def cli(self, *args, cwd=None, **env):
        cwd = cwd or self.work
        p = subprocess.run([PY, os.path.join(self.hooks, "instincts.py"), "--cwd", cwd, *args],
                           capture_output=True, text=True, env=self.env(**env), cwd=cwd, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def obs_file(self, pid=None):
        return os.path.join(self.data, "observations", pid or self.pid, "observations.jsonl")

    def obs_lines(self, pid=None):
        p = self.obs_file(pid)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def transcript(self, name, entries):
        p = os.path.join(self.tmp, "transcripts", name + ".jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        return p

    def journal(self):
        return os.path.join(self.vault, "08 Journal", today_utc() + ".md")

    def instinct(self, rel, iid, conf, action, **meta):
        fm = [f"id: {iid}", f'trigger: "when {iid}"', f"confidence: {conf}", "domain: workflow",
              "source: session-observation"] + [f"{k}: {v}" for k, v in meta.items()]
        body = "---\n" + "\n".join(fm) + f"\n---\n\n# {iid}\n\n## Action\n{action}\n\n## Evidence\n- seen\n"
        return self.write(f"vault/06 Memory/instincts/{rel}", body)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Result:
    def __init__(self, code, stdout, stderr, out):
        self.code, self.stdout, self.stderr, self.out = code, stdout, stderr, out

    @property
    def context(self):
        return (self.out.get("hookSpecificOutput") or {}).get("additionalContext", "")

    @property
    def decision(self):
        return (self.out.get("hookSpecificOutput") or {}).get("permissionDecision", "")


# ---------------------------------------------------------------- transcript builders

def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool(name, inp, usage=None, model="claude-sonnet-4-5", mid=None):
    msg = {"role": "assistant", "model": model, "content": [{"type": "tool_use", "id": "t", "name": name, "input": inp}]}
    if usage:
        msg["usage"] = usage
        msg["id"] = mid or f"msg_{time.time_ns()}"
    return {"type": "assistant", "message": msg}


def usage_entry(tokens, model="claude-sonnet-4-5", mid="m1"):
    return {"type": "assistant", "message": {"id": mid, "role": "assistant", "model": model,
                                             "content": [{"type": "text", "text": "ok"}],
                                             "usage": {"input_tokens": 1000, "cache_read_input_tokens": tokens - 1000,
                                                       "cache_creation_input_tokens": 0, "output_tokens": 500}}}


class HookTest(unittest.TestCase):
    def setUp(self):
        self.s = Sandbox()

    def tearDown(self):
        self.s.cleanup()

    def base(self, **kw):
        d = {"session_id": "11111111-2222-3333-4444-555566667777", "cwd": self.s.work, "transcript_path": ""}
        d.update(kw)
        return d

    def assertBlocked(self, r, needle):
        self.assertEqual(r.code, 2, f"expected a block, got exit {r.code}; stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertIn(needle, r.stderr)

    def assertAllowed(self, r):
        self.assertEqual(r.code, 0, f"expected allow, got exit {r.code}; stderr={r.stderr!r}")


# ---------------------------------------------------------------- SessionStart

class TestSessionStart(HookTest):
    def seed(self):
        s = self.s
        s.instinct("global/tests-first.md", "tests-first", 0.9, "Run the tests before committing")
        s.instinct("global/weak-one.md", "weak-one", 0.5, "WEAK-ACTION-SHOULD-NOT-SHOW")
        for n in range(7):
            s.instinct(f"global/filler-{n}.md", f"filler-{n}", 0.75, f"filler action {n}")
        s.instinct(f"project/{s.pid}/proj-rule.md", "proj-rule", 0.8, "Use the repository script for migrations")
        s.instinct("project/otherproject1/foreign.md", "foreign", 0.95, "FOREIGN-PROJECT-ACTION")
        sd = os.path.join(s.data, "sessions")
        os.makedirs(sd)
        mine = s.write(f"home/.local/share/neva/sessions/{today_utc()}-aaaaaaaa-session.tmp",
                       f"# Session\n**Worktree:** {s.work}\n**Repo:** \n\n---\nPRIOR-SUMMARY-MARK\n")
        other = s.write(f"home/.local/share/neva/sessions/{today_utc()}-bbbbbbbb-session.tmp",
                        "# Session\n**Worktree:** /somewhere/else\n**Repo:** \n\n---\nOTHER-MARK\n")
        old = s.write("home/.local/share/neva/sessions/2020-01-01-cccccccc-session.tmp", "old\n")
        now = time.time()
        os.utime(mine, (now - 60, now - 60))
        os.utime(other, (now, now))
        os.utime(old, (now - 40 * 86400, now - 40 * 86400))
        s.write(f"vault/08 Journal/{today_utc()}.md", "---\ndate: x\n---\n\n# Today\n\n## Today\n- JOURNAL-LINE-MARK\n")
        return old

    def test_startup_injects_everything_and_prunes(self):
        old = self.seed()
        r = self.s.dispatch("SessionStart", self.base(source="startup", hook_event_name="SessionStart"))
        self.assertAllowed(r)
        ctx = r.context
        self.assertIn("Run the tests before committing", ctx)
        self.assertIn("[project 80%] Use the repository script", ctx)
        self.assertNotIn("WEAK-ACTION-SHOULD-NOT-SHOW", ctx)
        self.assertNotIn("FOREIGN-PROJECT-ACTION", ctx)
        self.assertEqual(ctx.count("] filler action") + ctx.count("] Run the tests") + ctx.count("] Use the repo"), 6)
        self.assertIn("JOURNAL-LINE-MARK", ctx)
        self.assertIn("Call the plumber about the leak", ctx)
        self.assertNotIn("learn the cello", ctx)
        self.assertIn("Unsorted inbox captures: 1", ctx)
        self.assertIn("PRIOR-SUMMARY-MARK", ctx)
        self.assertIn("HISTORICAL REFERENCE ONLY", ctx)
        self.assertNotIn("OTHER-MARK", ctx)
        self.assertLessEqual(len(ctx), 8000)
        self.assertFalse(os.path.exists(old), "session file older than 30 days should be pruned")

    def test_vault_off_keeps_instincts_and_prior_session_but_skips_journal(self):
        self.seed()
        r = self.s.dispatch("SessionStart", self.base(source="startup", hook_event_name="SessionStart"),
                            NEVA_SESSION_START_VAULT="off")
        ctx = r.context
        self.assertIn("Run the tests before committing", ctx)
        self.assertIn("PRIOR-SUMMARY-MARK", ctx)
        self.assertNotIn("JOURNAL-LINE-MARK", ctx)
        self.assertNotIn("Call the plumber about the leak", ctx)

    def test_resume_skips_prior_summary_and_journal(self):
        self.seed()
        r = self.s.dispatch("SessionStart", self.base(source="resume"))
        self.assertNotIn("PRIOR-SUMMARY-MARK", r.context)
        self.assertNotIn("JOURNAL-LINE-MARK", r.context)

    def test_compact_keeps_journal_but_not_prior(self):
        self.seed()
        r = self.s.dispatch("SessionStart", self.base(source="compact"))
        self.assertIn("JOURNAL-LINE-MARK", r.context)
        self.assertNotIn("PRIOR-SUMMARY-MARK", r.context)

    def test_char_cap_and_off_switch(self):
        self.seed()
        r = self.s.dispatch("SessionStart", self.base(source="startup"), NEVA_SESSION_START_MAX_CHARS=400)
        self.assertLessEqual(len(r.context), 400)
        self.assertIn("truncated", r.context)
        r = self.s.dispatch("SessionStart", self.base(source="startup"), NEVA_SESSION_START_CONTEXT="off")
        self.assertEqual(r.stdout, "")

    def test_no_vault_still_runs(self):
        r = self.s.dispatch("SessionStart", self.base(source="startup"), NEVA_VAULT=os.path.join(self.s.tmp, "nope"))
        self.assertAllowed(r)


# ---------------------------------------------------------------- UserPromptSubmit

class TestPromptContext(HookTest):
    def test_strategy_once_per_session(self):
        r = self.s.dispatch("UserPromptSubmit", self.base(prompt="What should I focus on this week?",
                                                          cwd=self.s.tmp))
        self.assertIn("Ship the reader app", r.context)
        self.assertIn("Alpha (active)", r.context)
        self.assertIn("importer half built", r.context)
        self.assertNotIn("Old", r.context.replace("Older", ""))
        r2 = self.s.dispatch("UserPromptSubmit", self.base(prompt="and my priorities?", cwd=self.s.tmp))
        self.assertEqual(r2.stdout, "")

    def test_project_block_on_first_prompt_in_code_dir(self):
        r = self.s.dispatch("UserPromptSubmit", self.base(prompt="fix the importer"))
        self.assertIn("PROJECT CONTEXT: Alpha", r.context)
        self.assertIn("beta in 20 hands", r.context)
        self.assertNotIn("Ship the reader app", r.context)

    def test_slash_and_system_prompts_ignored(self):
        for p in ("/compact", "<system-reminder>goals</system-reminder>"):
            r = self.s.dispatch("UserPromptSubmit", self.base(prompt=p, session_id="s-" + str(len(p))))
            self.assertEqual(r.stdout, "")


# ---------------------------------------------------------------- PreToolUse: Bash

class TestPreBash(HookTest):
    def bash(self, cmd, **env):
        return self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": cmd}), "bash", **env)

    def test_no_verify_variants_blocked(self):
        for cmd in ('git commit --no-verify -m "fix: x"', "git push --no-veri", 'git commit -anm "fix: x"',
                    'git -c core.hooksPath=/dev/null commit -m "fix: a"', "HUSKY=0 git push",
                    "cd sub && git commit -n -m 'fix: a'", "git config core.hooksPath /tmp/none"):
            with self.subTest(cmd=cmd):
                self.assertBlocked(self.bash(cmd), "skips the repository's git hooks")

    def test_no_verify_lookalikes_allowed(self):
        for cmd in ('git commit -m "fix: never use --no-verify"', 'git commit -am "-n is only text here"',
                    'echo "--no-verify"', "git log --oneline -n 5", "git push -n origin feature"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(self.bash(cmd))

    def test_commit_message_warnings(self):
        r = self.bash('git commit -m "Updated stuff."')
        self.assertAllowed(r)
        self.assertIn("not conventional", r.context)
        self.assertIn("ends with a period", r.context)

    def test_heredoc_conventional_message_passes(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfix(core): handle empty input\n\nLonger body.\nEOF\n)\""
        r = self.bash(cmd)
        self.assertAllowed(r)
        self.assertNotIn("not conventional", r.context)

    def test_push_reminder(self):
        r = self.bash("git push origin main")
        self.assertIn("shared branch", r.context)
        r = self.bash("git push --force origin feature/x")
        self.assertIn("force push", r.context)

    def test_dev_server_tmux(self):
        r = self.bash("npm run dev")
        self.assertAllowed(r)
        self.assertIn("tmux new-session -d -s proj", r.context)
        self.assertBlocked(self.bash("npm run dev", NEVA_HOOK_PROFILE="strict"), "dev server")
        self.assertEqual(self.bash("npm run dev", TMUX="/tmp/tmux-1/default,1,0").stdout, "")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "npm run dev",
                                                                                   "run_in_background": True}), "bash")
        self.assertEqual(r.stdout, "")

    def test_staged_diff_scanner(self):
        sys.path.insert(0, self.s.hooks)
        try:
            from neva_hooks import pre_bash
        finally:
            sys.path.remove(self.s.hooks)
        fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        diff = "\n".join([
            "+++ b/src/config.ts", "@@ -0,0 +1,4 @@", f"+const k = '{fake_key}';", "+debugger;",
            "+// debugger in a comment is fine", "+const x = 1;",
            "+++ b/src/log.js", "@@ -3,0 +4,2 @@", "+console.log('hi')", "+const api_key = 'your_api_key_here';",
            "+++ b/app/settings.py", "@@ -1,0 +10,1 @@", "+password = 'hunter2hunter2xyz'",
        ])
        errors, warns = pre_bash.scan_added_lines(diff)
        self.assertIn("src/config.ts:1: AWS access key id", errors)
        self.assertIn("src/config.ts:2: debugger statement", errors)
        self.assertEqual(len(errors), 2)
        self.assertIn("src/log.js:4: console.log", warns)
        self.assertIn("app/settings.py:10: possible hardcoded password", warns)
        self.assertFalse(any("log.js:5" in w for w in warns), "placeholder values must not warn")


# ---------------------------------------------------------------- PreToolUse: Write|Edit

class TestPreWrite(HookTest):
    def edit(self, path, old, new, tool_name="Edit", **env):
        ti = {"file_path": path, "old_string": old, "new_string": new}
        return self.s.dispatch("PreToolUse", self.base(tool_name=tool_name, tool_input=ti), "write", **env)

    def write(self, path, content="x", **env):
        return self.s.dispatch("PreToolUse", self.base(tool_name="Write",
                                                       tool_input={"file_path": path, "content": content}),
                               "write", **env)

    def test_vault_gate(self):
        r = self.write(os.path.join(self.s.vault, "GOALS.md"))
        self.assertEqual(r.decision, "ask")
        self.assertIn("GOALS.md", r.out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.write(os.path.join(self.s.vault, "08 Journal", "2026-01-01.md")).decision, "")
        self.assertEqual(self.write(os.path.join(self.s.vault, "00 Inbox", "inbox.md")).decision, "")
        r = self.write(os.path.join(self.s.vault, "GOALS.md"), NEVA_VAULT_WRITABLE="GOALS.md")
        self.assertEqual(r.decision, "")

    def test_config_protection(self):
        es = self.s.write("work/proj/.eslintrc.json", '{\n  "rules": {\n    "no-console": "error",\n    "eqeqeq": "warn"\n  }\n}\n')
        self.assertBlocked(self.edit(es, '"no-console": "error",', '"no-console": "off",'), "loosens .eslintrc.json")
        self.assertAllowed(self.edit(es, '"eqeqeq": "warn"', '"eqeqeq": "error"'))
        self.assertBlocked(self.edit(es, '    "no-console": "error",\n', ""), "removes a rule")
        ts = self.s.write("work/proj/tsconfig.json", '{\n  "compilerOptions": {\n    "strict": true\n  }\n}\n')
        self.assertBlocked(self.edit(ts, '"strict": true', '"strict": false'), "strictness flag")
        py = self.s.write("work/proj/pyproject.toml", '[project]\nname = "x"\n\n[tool.ruff.lint]\nselect = ["E", "F"]\n')
        self.assertAllowed(self.edit(py, 'name = "x"', 'name = "x"\nexclude = ["tests"]'))
        self.assertBlocked(self.edit(py, 'select = ["E", "F"]', 'select = ["E", "F"]\nignore = ["E501"]'), "ignore")
        new_cfg = os.path.join(self.s.work, "biome.json")
        self.assertAllowed(self.write(new_cfg, '{"linter": {"rules": {"all": "off"}}}'))

    def test_doc_file_warning(self):
        self.assertIn("Ad-hoc documentation file", self.write(os.path.join(self.s.work, "NOTES.md")).context)
        self.assertEqual(self.write(os.path.join(self.s.work, "docs", "NOTES.md")).context, "")

    def test_suggest_compact_context_tokens(self):
        f = os.path.join(self.s.work, "a.py")
        tp = self.s.transcript("c1", [user("go"), usage_entry(170_000)])
        run = lambda: self.s.dispatch("PreToolUse", self.base(tool_name="Edit", transcript_path=tp,
                                                              tool_input={"file_path": f, "old_string": "a",
                                                                          "new_string": "b"}), "write")
        self.assertIn("about 170k tokens (85% of a 200k window)", run().context)
        self.assertEqual(run().context, "")
        tp2 = self.s.transcript("c2", [user("go"), usage_entry(810_000, model="claude-opus-5-5")])
        run2 = lambda: self.s.dispatch("PreToolUse", self.base(session_id="big", tool_name="Edit", transcript_path=tp2,
                                                               tool_input={"file_path": f, "old_string": "a",
                                                                           "new_string": "b"}), "write")
        self.assertIn("1000k window", run2().context)
        self.assertEqual(run2().context, "")
        self.s.transcript("c2", [user("go"), usage_entry(875_000, model="claude-opus-5-5")])
        self.assertIn("about 875k tokens", run2().context)

    def test_suggest_compact_tool_count_fallback(self):
        f = os.path.join(self.s.work, "a.py")
        outs = [self.edit(f, "a", "b", COMPACT_THRESHOLD=3).context for _ in range(4)]
        self.assertEqual([bool(o) for o in outs], [False, False, True, False])
        self.assertIn("3 edits this session", outs[2])


# ---------------------------------------------------------------- observe and mcp_health

class TestObserveAndMcp(HookTest):
    def test_observe_pre_post_truncate_scrub(self):
        secret = "API_KEY=" + "abcd1234efgh5678"
        big = "y" * 6000
        self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": f"export {secret}; echo {big}"}))
        self.s.dispatch("PostToolUse", self.base(tool_name="Bash", tool_input={}, tool_response={"stdout": "done"}))
        self.s.dispatch("PostToolUseFailure", self.base(tool_name="Bash", tool_input={}, error="exit 1"))
        lines = self.s.obs_lines()
        self.assertEqual([x["event"] for x in lines], ["tool_start", "tool_complete", "tool_error"])
        self.assertEqual(lines[0]["project_id"], self.s.pid)
        self.assertEqual(lines[0]["project_name"], "proj")
        self.assertIn("[REDACTED]", lines[0]["input"])
        self.assertNotIn("abcd1234efgh5678", lines[0]["input"])
        self.assertIn("[truncated", lines[0]["input"])
        self.assertLess(len(lines[0]["input"]), 5200)
        self.assertNotIn("path", lines[0], "Bash has no file path")
        self.assertEqual(json.loads(lines[1]["output"]), {"stdout": "done"})

    def test_observe_writes_path_on_tool_start_for_file_tools(self):
        f = os.path.join(self.s.work, "src", "a.py")
        self.s.dispatch("PreToolUse", self.base(tool_name="Read", tool_input={"file_path": f}))
        self.s.dispatch("PreToolUse", self.base(tool_name="Edit", tool_input={"file_path": f, "old_string": "a",
                                                                               "new_string": "b"}))
        self.s.dispatch("PostToolUse", self.base(tool_name="Read", tool_input={"file_path": f}, tool_response="x"))
        lines = self.s.obs_lines()
        self.assertEqual([x.get("path") for x in lines], [f, f, None])

    def test_observe_parse_error_record(self):
        self.s.dispatch("PreToolUse", {}, stdin="{not json at all")
        lines = self.s.obs_lines()
        self.assertEqual(lines[-1]["event"], "parse_error")
        self.assertIn("not json", lines[-1]["raw"])

    def test_observe_skips(self):
        read = self.base(tool_name="Read", tool_input={})
        self.s.dispatch("PreToolUse", read, NEVA_SKIP_OBSERVE=1)
        self.s.dispatch("PreToolUse", dict(read, agent_id="sub1"))
        self.s.dispatch("PreToolUse", read, NEVA_HOOK_PROFILE="minimal")
        self.s.dispatch("PreToolUse", read, CLAUDE_CODE_ENTRYPOINT="some-batch-runner")
        self.s.dispatch("PreToolUse", read, NEVA_OBSERVE_SKIP_PATHS="work/proj")
        self.assertEqual(self.s.obs_lines(), [])
        self.s.dispatch("PreToolUse", read, CLAUDE_CODE_ENTRYPOINT="cli")
        self.assertEqual(len(self.s.obs_lines()), 1, "the cli entrypoint is observed")
        self.s.write("home/.local/share/neva/observations/disabled", "")
        self.s.dispatch("PreToolUse", read)
        self.assertEqual(len(self.s.obs_lines()), 1, "the disabled file stops observation")

    def test_observe_rotates_into_archive(self):
        live = self.s.obs_file()
        os.makedirs(os.path.dirname(live), exist_ok=True)
        with open(live, "w") as fh:
            fh.write("x" * (1024 * 1024 + 10) + "\n")
        self.s.dispatch("PreToolUse", self.base(tool_name="Read", tool_input={}), NEVA_OBSERVE_MAX_MB=1)
        arch = os.path.join(os.path.dirname(live), "observations.archive")
        self.assertEqual(len([n for n in os.listdir(arch) if n.startswith("observations-")]), 1)
        self.assertEqual(len(self.s.obs_lines()), 1)

    def test_observe_honors_observations_dir(self):
        alt = os.path.join(self.s.tmp, "obs-alt")
        self.s.dispatch("PreToolUse", self.base(tool_name="Read", tool_input={}), NEVA_OBSERVATIONS_DIR=alt)
        self.assertTrue(os.path.exists(os.path.join(alt, self.s.pid, "observations.jsonl")))

    def test_mcp_health_blocks_until_backoff_passes(self):
        fail = self.base(tool_name="mcp__demo__search", tool_input={}, error="connect ECONNREFUSED 127.0.0.1:3000")
        r = self.s.dispatch("PostToolUseFailure", fail)
        self.assertIn("marked unhealthy", r.context)
        call = self.base(tool_name="mcp__demo__search", tool_input={"q": "x"})
        self.assertBlocked(self.s.dispatch("PreToolUse", call, "any"), "MCP server 'demo'")
        self.assertAllowed(self.s.dispatch("PreToolUse", self.base(tool_name="mcp__other__x", tool_input={}), "any"))
        r = self.s.dispatch("PreToolUse", call, "any", NEVA_MCP_HEALTH_FAIL_OPEN=1)
        self.assertAllowed(r)
        self.assertIn("unhealthy", r.context)
        self.s.dispatch("PostToolUse", self.base(tool_name="mcp__demo__search", tool_input={}, tool_response="ok"))
        self.assertAllowed(self.s.dispatch("PreToolUse", call, "any"))
        self.s.dispatch("PostToolUseFailure", fail, NEVA_MCP_HEALTH_BACKOFF_MS=1)
        time.sleep(0.05)
        self.assertAllowed(self.s.dispatch("PreToolUse", call, "any"))

    def test_mcp_application_error_not_counted(self):
        self.s.dispatch("PostToolUseFailure", self.base(tool_name="mcp__demo__search", error="invalid query syntax"))
        self.assertAllowed(self.s.dispatch("PreToolUse", self.base(tool_name="mcp__demo__search", tool_input={}), "any"))


# ---------------------------------------------------------------- PreCompact, Stop, SessionEnd

class TestLifecycle(HookTest):
    def work_transcript(self, name, tools=6, journal=False, first="Base directory for this skill: /x"):
        entries = [user(first), user("Build the CSV importer"),
                   {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]}}]
        for n in range(tools):
            entries.append(tool("Edit", {"file_path": os.path.join(self.s.work, f"f{n}.py"), "old_string": "a",
                                         "new_string": "b"}, usage={"input_tokens": 100, "output_tokens": 50,
                                                                    "cache_read_input_tokens": 1000,
                                                                    "cache_creation_input_tokens": 10},
                                mid=f"m{n}"))
        if journal:
            entries.append(tool("Edit", {"file_path": os.path.join(self.s.vault, "08 Journal", "x.md")}))
        entries.append(user("now add tests"))
        return self.s.transcript(name, entries)

    def session_files(self):
        d = os.path.join(self.s.data, "sessions")
        return sorted(os.path.join(d, n) for n in os.listdir(d)) if os.path.isdir(d) else []

    def test_pre_compact_writes_session_file_and_journal(self):
        tp = self.work_transcript("pc")
        self.assertAllowed(self.s.dispatch("PreCompact", self.base(transcript_path=tp, trigger="auto")))
        files = self.session_files()
        self.assertEqual(len(files), 1)
        text = self.s.read(files[0])
        self.assertIn("<!-- NEVA:SUMMARY:START -->", text)
        self.assertIn("pre-compact", text)
        self.assertIn("- Build the CSV importer", text)
        self.assertIn("Edit x6", text)
        self.assertIn(f"**Worktree:** {self.s.work}", text)
        self.assertIn("compacted session 66667777", self.s.read(self.s.journal()))
        self.assertIn("last ask: now add tests", self.s.read(self.s.journal()))

    def test_stop_journal_nudge_once(self):
        tp = self.work_transcript("st")
        r = self.s.dispatch("Stop", self.base(transcript_path=tp))
        self.assertBlocked(r, "Before finishing: append 2 to 4 lines")
        self.assertAllowed(self.s.dispatch("Stop", self.base(transcript_path=tp)))
        tp2 = self.work_transcript("st2", journal=True)
        self.assertAllowed(self.s.dispatch("Stop", self.base(session_id="other-session", transcript_path=tp2)))
        tp3 = self.work_transcript("st3", tools=2)
        self.assertAllowed(self.s.dispatch("Stop", self.base(session_id="short-session", transcript_path=tp3)))
        self.assertAllowed(self.s.dispatch("Stop", self.base(session_id="active", transcript_path=tp,
                                                             stop_hook_active=True)))

    def test_stop_summary_markers_preserve_notes_and_cost(self):
        tp = self.work_transcript("sum")
        env = {"NEVA_DISABLED_HOOKS": "journal_nudge"}
        self.s.dispatch("Stop", self.base(transcript_path=tp), **env)
        f = self.session_files()[0]
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\nMY-OWN-NOTE\n")
        self.s.dispatch("Stop", self.base(transcript_path=tp), **env)
        text = self.s.read(f)
        self.assertEqual(text.count("<!-- NEVA:SUMMARY:START -->"), 1)
        self.assertIn("MY-OWN-NOTE", text)
        costs = os.path.join(self.s.data, "metrics", "costs.jsonl")
        with open(costs, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh]
        self.assertEqual(len(rows), 1, "unchanged usage must not add a second cost row")
        self.assertEqual(rows[0]["output_tokens"], 300)
        self.assertEqual(rows[0]["transcript_path"], tp)
        self.assertGreater(rows[0]["estimated_cost_usd"], 0)
        alt = os.path.join(self.s.tmp, "metrics-alt")
        self.s.dispatch("Stop", self.base(session_id="other-cost", transcript_path=tp), NEVA_METRICS_DIR=alt, **env)
        self.assertTrue(os.path.exists(os.path.join(alt, "costs.jsonl")), "NEVA_METRICS_DIR overrides the log folder")

    def fake_tools(self):
        s = self.s
        s.write("work/proj/package.json", '{"name": "p", "prettier": {}}')
        s.write("work/proj/tsconfig.json", "{}")
        plog = os.path.join(s.tmp, "prettier.log")
        tlog = os.path.join(s.tmp, "tsc.log")
        s.write("work/proj/node_modules/.bin/prettier", f'#!/bin/sh\necho "$@" >> "{plog}"\n', 0o755)
        s.write("work/proj/node_modules/.bin/tsc",
                f'#!/bin/sh\necho run >> "{tlog}"\necho "src/a.ts(1,7): error TS2322: bad type"\nexit 2\n', 0o755)
        src = s.write("work/proj/src/a.ts", "const a: number = 'x'\n")
        return plog, tlog, src

    def test_format_once_per_response_and_strict_typecheck(self):
        plog, tlog, src = self.fake_tools()
        env = {"NEVA_DISABLED_HOOKS": "journal_nudge"}
        self.s.dispatch("PostToolUse", self.base(tool_name="Edit", tool_input={"file_path": src}), **env)
        self.assertAllowed(self.s.dispatch("Stop", self.base(), **env))
        self.assertIn("src/a.ts", self.s.read(plog))
        self.assertFalse(os.path.exists(tlog), "standard profile must not typecheck")
        self.s.dispatch("Stop", self.base(), **env)
        self.assertEqual(len(self.s.read(plog).splitlines()), 1, "no edits since the last Stop: no format run")
        self.s.dispatch("PostToolUse", self.base(tool_name="Edit", tool_input={"file_path": src}), **env)
        r = self.s.dispatch("Stop", self.base(), NEVA_HOOK_PROFILE="strict", **env)
        self.assertBlocked(r, "error TS2322")
        self.assertTrue(os.path.exists(tlog))

    def test_session_end_audit_dedupes_on_resume(self):
        tp = self.work_transcript("end", tools=2)
        self.s.dispatch("SessionEnd", self.base(transcript_path=tp, reason="exit"))
        tp_more = self.work_transcript("end", tools=4)
        self.s.dispatch("SessionEnd", self.base(transcript_path=tp_more, reason="exit"))
        text = self.s.read(self.s.journal())
        lines = [ln for ln in text.splitlines() if "] session 66667777:" in ln]
        self.assertEqual(len(lines), 1, text)
        self.assertIn("Build the CSV importer (4 tool calls, no journal narrative)", lines[0])
        self.assertNotIn("Base directory", text)
        self.assertIn("## Log", text)
        self.assertIn("## Today", text, "the journal must be created from the vault's Daily Note template")

    def test_journal_pattern_configurable(self):
        tp = self.work_transcript("pat", tools=1)
        pattern = "08 Journal/{year}/{month} {month_name}/{date}.md"
        self.s.dispatch("SessionEnd", self.base(transcript_path=tp), NEVA_JOURNAL_PATTERN=pattern)
        d = datetime.date.fromisoformat(today_utc())
        expect = os.path.join(self.s.vault, "08 Journal", str(d.year), f"{d.month:02d} {d.strftime('%B')}", f"{d}.md")
        self.assertTrue(os.path.exists(expect), expect)


# ---------------------------------------------------------------- profiles, disabling, resilience

class TestControls(HookTest):
    def test_minimal_profile_runs_only_essentials(self):
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Write", tool_input={
            "file_path": os.path.join(self.s.work, "NOTES.md"), "content": "x"}), "write", NEVA_HOOK_PROFILE="minimal")
        self.assertEqual(r.context, "")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Write", tool_input={
            "file_path": os.path.join(self.s.vault, "GOALS.md"), "content": "x"}), "write", NEVA_HOOK_PROFILE="minimal")
        self.assertEqual(r.decision, "ask")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "git push --no-verify"}),
                            "bash", NEVA_HOOK_PROFILE="minimal")
        self.assertBlocked(r, "--no-verify")

    def test_strict_gateguard_first_edit_denied_then_allowed(self):
        f = self.s.write("work/proj/src/lib.py", "x = 1\n")
        call = self.base(tool_name="Edit", tool_input={"file_path": f, "old_string": "1", "new_string": "2"})
        self.assertAllowed(self.s.dispatch("PreToolUse", call, "write"))
        r = self.s.dispatch("PreToolUse", call, "write", NEVA_HOOK_PROFILE="strict")
        self.assertBlocked(r, "Fact-Forcing Gate")
        self.assertIn("Quote the user's current instruction verbatim", r.stderr)
        self.assertAllowed(self.s.dispatch("PreToolUse", call, "write", NEVA_HOOK_PROFILE="strict"))
        other = dict(call, tool_input={"file_path": os.path.join(self.s.work, "new.py"), "content": "x"},
                     tool_name="Write", agent_id="sub")
        self.assertAllowed(self.s.dispatch("PreToolUse", other, "write", NEVA_HOOK_PROFILE="strict"))
        self.assertAllowed(self.s.dispatch("PreToolUse", dict(other, agent_id=None), "write",
                                           NEVA_HOOK_PROFILE="strict", NEVA_GATEGUARD="off"))
        self.assertAllowed(self.s.dispatch("PreToolUse", dict(other, agent_id=None), "write",
                                           NEVA_HOOK_PROFILE="strict", GATEGUARD_EXEMPT_GLOBS="*.py"))

    def test_disabled_hooks(self):
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "git push --no-verify"}),
                            "bash", NEVA_DISABLED_HOOKS="push_reminder, no_verify")
        self.assertAllowed(r)
        self.assertEqual(r.stdout, "")

    def test_control_assertion_can_fail(self):
        """The block assertion is not vacuous: with the hook disabled the same check must fail."""
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "git push --no-verify"}),
                            "bash", NEVA_DISABLED_HOOKS="no_verify")
        with self.assertRaises(AssertionError):
            self.assertBlocked(r, "skips the repository's git hooks")

    def test_headless_is_silent(self):
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "git push --no-verify"}),
                            "bash", NEVA_HEADLESS=1)
        self.assertAllowed(r)

    def test_broken_module_never_breaks_the_session(self):
        mod = os.path.join(self.s.hooks, "neva_hooks", "broken.py")
        with open(mod, "w") as fh:
            fh.write("def run(ctx):\n    raise RuntimeError('boom from a broken module')\n")
        meta_p = os.path.join(self.s.hooks, "hooks.meta.json")
        with open(meta_p) as fh:
            meta = json.load(fh)
        meta["modules"].insert(0, {"id": "broken", "module": "broken", "function": "run",
                                   "events": ["PreToolUse", "SessionStart"],
                                   "profiles": ["minimal", "standard", "strict"], "description": "test"})
        meta["modules"].insert(0, {"id": "missing", "module": "does_not_exist", "function": "run",
                                   "events": ["PreToolUse"], "tools": ["Bash"], "profiles": ["standard"],
                                   "description": "test"})
        with open(meta_p, "w") as fh:
            json.dump(meta, fh)
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "git push origin main"}),
                            "bash")
        self.assertAllowed(r)
        self.assertIn("shared branch", r.context, "the healthy modules after the broken one must still run")
        log = self.s.read(os.path.join(self.s.data, "hooks.log"))
        self.assertIn("module broken on PreToolUse", log)
        self.assertIn("RuntimeError: boom from a broken module", log)
        self.assertIn("module missing", log)
        self.assertAllowed(self.s.dispatch("SessionStart", {}, stdin="this is not json"))
        self.assertAllowed(self.s.dispatch("Stop", {}, stdin=""))


# ---------------------------------------------------------------- config files

class TestConfigFiles(unittest.TestCase):
    def test_hooks_json_matches_meta(self):
        with open(os.path.join(SRC, "hooks.json")) as fh:
            hooks = json.load(fh)["hooks"]
        with open(os.path.join(SRC, "hooks.meta.json")) as fh:
            meta = json.load(fh)
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                                      "PostToolUseFailure", "PreCompact", "Stop", "SessionEnd"})
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "startup|resume|clear|compact")
        for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            self.assertEqual([b["matcher"] for b in hooks[event]], ["*"], f"{event}: one * matcher, one process")
        keys = set()
        for event, blocks in hooks.items():
            self.assertEqual(len(blocks), 1, f"{event} must be registered once")
            for b in blocks:
                self.assertEqual(len(b["hooks"]), 1)
                for h in b["hooks"]:
                    cmd = h["command"]
                    self.assertEqual(cmd, 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" ' + event)
                    keys.add(event)
        ids = [m["id"] for m in meta["modules"]]
        self.assertEqual(len(ids), len(set(ids)))
        sys.path.insert(0, SRC)
        try:
            import importlib
            for m in meta["modules"]:
                for e in m["events"]:
                    self.assertIn(e, keys, f"{m['id']} listens on {e}, which hooks.json never calls")
                mod = importlib.import_module("neva_hooks." + m["module"])
                self.assertTrue(callable(getattr(mod, m["function"])), m["id"])
                self.assertTrue(set(m["profiles"]) <= {"minimal", "standard", "strict"})
                self.assertTrue(m["description"])
                self.assertIsInstance(m.get("tools", []), list)
        finally:
            sys.path.remove(SRC)

    def test_plugin_json_has_no_hooks_key(self):
        p = os.path.join(os.path.dirname(SRC), ".claude-plugin", "plugin.json")
        with open(p) as fh:
            self.assertNotIn("hooks", json.load(fh))

    def test_public_hygiene(self):
        bad = {chr(0x2014): "em dash", "/" + "Users/": "a user home path"}
        for dirpath, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in files:
                p = os.path.join(dirpath, n)
                with open(p, encoding="utf-8") as fh:
                    text = fh.read()
                for needle, what in bad.items():
                    self.assertNotIn(needle, text, f"{what} in {p}")
                self.assertFalse(any(ord(ch) >= 0x1F300 or 0x2600 <= ord(ch) <= 0x27BF for ch in text),
                                 f"emoji in {p}")
                if n.endswith((".py", ".json")) and n != "__init__.py":
                    self.assertIn("affaan-m/ECC (MIT), commit d3b8a3e", text, f"attribution missing in {p}")
                if n.endswith(".py"):
                    self.assertNotIn("../../" + "lib", text)
                    self.assertNotIn("from " + "lib", text)


# ---------------------------------------------------------------- dispatch: one process, filtered inside

class TestDispatchFiltering(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, SRC)
        import dispatch
        self.d = dispatch
        with open(os.path.join(SRC, "hooks.meta.json")) as fh:
            self.meta = json.load(fh)

    def tearDown(self):
        sys.path.remove(SRC)

    def ids(self, event, tool, profile="strict"):
        return [m["id"] for m in self.d.selected_modules(self.meta, event, profile, set(), tool)]

    def test_bash_call_runs_only_bash_and_all_tool_modules(self):
        ids = self.ids("PreToolUse", "Bash")
        for want in ("no_verify", "safety_careful", "commit_quality", "tmux_dev", "hookify_pre_tool", "observe"):
            self.assertIn(want, ids)
        for never in ("vault_gate", "gateguard", "suggest_compact", "safety_freeze", "mcp_health"):
            self.assertNotIn(never, ids)

    def test_write_call_runs_write_modules(self):
        ids = self.ids("PreToolUse", "Edit")
        for want in ("vault_gate", "safety_freeze", "config_protection", "gateguard", "suggest_compact", "observe"):
            self.assertIn(want, ids)
        self.assertNotIn("no_verify", ids)

    def test_mcp_health_only_for_mcp_tools(self):
        self.assertIn("mcp_health", self.ids("PreToolUse", "mcp__demo__search"))
        self.assertNotIn("mcp_health", self.ids("PostToolUse", "Read"))

    def test_profiles(self):
        self.assertNotIn("gateguard", self.ids("PreToolUse", "Edit", "standard"))
        self.assertNotIn("delivery_gate", self.ids("Stop", "", "standard"))
        self.assertIn("delivery_gate", self.ids("Stop", "", "strict"))
        self.assertEqual(self.ids("PreToolUse", "Bash", "minimal"),
                         ["no_verify", "safety_careful", "hookify_pre_tool"])


# ---------------------------------------------------------------- project identity: hook and CLI agree

class TestProjectIdentity(HookTest):
    def cli_id(self, cwd, **env):
        code, out = self.s.cli("stats", cwd=cwd, **env)
        self.assertEqual(code, 0, out)
        return out.split("Project: ", 1)[1].split("(", 1)[1].split(")", 1)[0]

    def hook_id(self, cwd, **env):
        self.s.dispatch("PreToolUse", self.base(cwd=cwd, tool_name="Read", tool_input={}), **env)
        obs = os.path.join(self.s.data, "observations")
        newest = max((os.path.join(obs, d, "observations.jsonl") for d in os.listdir(obs)
                      if os.path.exists(os.path.join(obs, d, "observations.jsonl"))), key=os.path.getmtime)
        with open(newest) as fh:
            return json.loads(fh.readlines()[-1])["project_id"]

    def test_no_remote_repo(self):
        self.assertEqual(self.hook_id(self.s.work), self.s.pid)
        self.assertEqual(self.cli_id(self.s.work), self.s.pid)

    def test_remote_repo_and_subdir(self):
        subprocess.run(["git", "-C", self.s.work, "remote", "add", "origin", "git@github.com:Example/Repo.git"],
                       check=True)
        want = hashlib.sha256(b"github.com/example/repo").hexdigest()[:12]
        sub = os.path.join(self.s.work, "pkg")
        os.makedirs(sub)
        self.assertEqual(self.hook_id(sub), want)
        self.assertEqual(self.cli_id(sub), want)
        reg = json.loads(self.s.read(os.path.join(self.s.data, "observations", "projects.json")))
        self.assertEqual(reg[want]["name"], "proj")
        self.assertEqual(reg[want]["remote"], "git@github.com:Example/Repo.git")

    def test_linked_worktree_shares_the_main_id(self):
        g = ["git", "-C", self.s.work, "-c", "user.email=t@t", "-c", "user.name=t"]
        self.s.write("work/proj/a.txt", "a")
        subprocess.run(g + ["add", "a.txt"], check=True, capture_output=True)
        subprocess.run(g + ["commit", "-q", "-m", "init"], check=True, capture_output=True)
        wt = os.path.join(self.s.tmp, "work", "proj-wt")
        subprocess.run(g + ["worktree", "add", "-q", wt], check=True, capture_output=True)
        self.assertEqual(self.hook_id(wt), self.s.pid)
        self.assertEqual(self.cli_id(wt), self.s.pid)

    def test_outside_git_is_unscoped_unless_project_dir_is_explicit(self):
        plain = os.path.join(self.s.tmp, "plain")
        os.makedirs(plain)
        self.assertEqual(self.hook_id(plain), "unscoped")
        cli = os.path.join(self.s.plugin, "skills", "continuous-learning-v2", "scripts", "instinct-cli.py")
        p = subprocess.run([PY, cli, "stats"], cwd=plain, env=self.s.env(), capture_output=True, text=True)
        self.assertIn("Project: unscoped (unscoped)", p.stdout, p.stderr)
        # Claude Code sets CLAUDE_PROJECT_DIR for hooks; the shim's --cwd sets it the same way
        want = hashlib.sha256(plain.encode()).hexdigest()[:12]
        self.assertEqual(self.hook_id(plain, CLAUDE_PROJECT_DIR=plain), want)
        self.assertEqual(self.cli_id(plain), want)


# ---------------------------------------------------------------- ck SessionStart

class TestCk(HookTest):
    def ck(self, projects, contexts):
        home = os.path.join(self.s.data, "ck")
        self.s.write("home/.local/share/neva/ck/projects.json", json.dumps(projects))
        for name, ctx in contexts.items():
            self.s.write(f"home/.local/share/neva/ck/contexts/{name}/context.json", json.dumps(ctx))
        return home

    def start(self, **kw):
        return self.s.dispatch("SessionStart", self.base(source="startup", **kw))

    def test_no_ck_data_is_silent_and_creates_nothing(self):
        r = self.start()
        self.assertNotIn("ck:", r.context)
        self.assertFalse(os.path.exists(os.path.join(self.s.data, "ck")))

    def test_registered_project_block_and_warnings(self):
        old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        home = self.ck({self.s.work: {"name": "proj", "contextDir": "proj"}}, {"proj": {
            "name": "proj", "goal": "Ship the importer",
            "sessions": [{"id": "s-old", "date": old, "summary": "built parser", "leftOff": "parser edge cases\nmore",
                          "nextSteps": ["write tests", "wire the CLI", "third step"]}]}})
        self.s.write("home/.local/share/neva/ck/current-session.json",
                     json.dumps({"sessionId": "never-saved", "projectPath": self.s.work}))
        self.s.write("work/proj/CLAUDE.md", "# P\n\n## Current Goal\nRewrite everything\n")
        r = self.start()
        ctx = r.context
        self.assertIn("ck: proj | 3 days ago | 1 sessions", ctx)
        self.assertIn("Goal: Ship the importer", ctx)
        self.assertIn("Left off: parser edge cases", ctx)
        self.assertIn("Next: write tests | wire the CLI", ctx)
        self.assertNotIn("third step", ctx)
        self.assertIn("WARNING Last session wasn't saved. Run /ck:save to capture it", ctx)
        self.assertIn("WARNING Goal mismatch", ctx)
        cur = json.loads(self.s.read(os.path.join(home, "current-session.json")))
        self.assertEqual(cur["sessionId"], "11111111-2222-3333-4444-555566667777")
        self.assertEqual(cur["projectPath"], self.s.work)
        self.assertEqual(cur["projectName"], "proj")

    def test_saved_session_no_warning(self):
        self.ck({self.s.work: {"name": "proj", "contextDir": "proj"}},
                {"proj": {"name": "proj", "sessions": [{"id": "saved", "date": datetime.date.today().isoformat()}]}})
        self.s.write("home/.local/share/neva/ck/current-session.json",
                     json.dumps({"sessionId": "saved", "projectPath": self.s.work}))
        ctx = self.start().context
        self.assertIn("ck: proj | today | 1 sessions", ctx)
        self.assertNotIn("WARNING", ctx)

    def test_unregistered_folder_lists_recent_projects(self):
        today = datetime.date.today().isoformat()
        self.ck({"/elsewhere/a": {"name": "alpha", "contextDir": "alpha"},
                 "/elsewhere/b": {"name": "beta", "contextDir": "beta"}},
                {"alpha": {"sessions": [{"date": today, "summary": "alpha work"}]},
                 "beta": {"sessions": [{"date": "2020-01-01", "summary": "beta work"}]}})
        ctx = self.start().context
        self.assertIn("| alpha | active | today | alpha work |", ctx)
        self.assertIn("| beta | stale |", ctx)
        self.assertIn("/ck:init to register this folder", ctx)
        self.assertLess(ctx.index("alpha"), ctx.index("beta"))


# ---------------------------------------------------------------- hookify rule engine

class TestHookify(HookTest):
    def rule(self, name, text):
        return self.s.write(f"work/proj/.claude/hookify.{name}.local.md", text)

    def bash(self, cmd, **env):
        return self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": cmd}), **env)

    def test_bash_block_and_control(self):
        self.rule("rmrf", "---\nname: block-rm-rf\nenabled: true\nevent: bash\naction: block\npattern: rm\\s+-rf\n---\n"
                          "Do not delete trees. Use trash instead.\n")
        self.assertBlocked(self.bash("rm -rf build/out"), "[hookify:block-rm-rf] Do not delete trees")
        self.assertAllowed(self.bash("ls -la"))
        r = self.bash("rm -rf build/out", NEVA_DISABLED_HOOKS="hookify_pre_tool")
        with self.assertRaises(AssertionError):
            self.assertBlocked(r, "hookify")

    def test_file_warn_by_path_and_conditions(self):
        self.rule("env", "---\nname: warn-env-keys\nenabled: true\nevent: file\nconditions:\n"
                         "  - field: file_path\n    operator: regex_match\n    pattern: \\.env$\n"
                         "  - field: new_text\n    operator: contains\n    pattern: API_KEY\n---\n"
                         "Keep .env out of git.\n")
        self.rule("debug", '---\nname: warn-console\nenabled: true\nevent: file\npattern: "console\\\\.log\\\\("\n---\n'
                           "Remove console.log.\n")
        env_file = os.path.join(self.s.work, ".env")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Write", tool_input={"file_path": env_file,
                                                                                   "content": "API_KEY=x"}))
        self.assertAllowed(r)
        self.assertIn("[hookify:warn-env-keys] Keep .env out of git.", r.context)
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Write", tool_input={"file_path": env_file,
                                                                                   "content": "OTHER=1"}))
        self.assertNotIn("warn-env-keys", r.context)
        js = os.path.join(self.s.work, "a.js")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Edit", tool_input={
            "file_path": js, "old_string": "a", "new_string": "console.log(a)"}))
        self.assertIn("[hookify:warn-console]", r.context)

    def test_prompt_and_stop_rules(self):
        self.rule("prompt", "---\nname: block-deploy\nenabled: true\nevent: prompt\naction: block\n"
                            "pattern: (?i)deploy to prod\n---\nProd deploys need the runbook.\n")
        self.rule("stop", "---\nname: require-tests\nenabled: true\nevent: stop\naction: block\npattern: .*\n---\n"
                          "Run the tests before stopping.\n")
        self.assertBlocked(self.s.dispatch("UserPromptSubmit", self.base(prompt="Deploy to prod now")),
                           "Prod deploys need the runbook")
        self.assertAllowed(self.s.dispatch("UserPromptSubmit", self.base(prompt="write docs")))
        env = {"NEVA_DISABLED_HOOKS": "journal_nudge"}
        self.assertBlocked(self.s.dispatch("Stop", self.base(), **env), "Run the tests before stopping")
        r = self.s.dispatch("Stop", self.base(stop_hook_active=True), **env)
        self.assertAllowed(r)
        self.assertIn("Run the tests before stopping", r.out.get("systemMessage", ""))

    def test_malformed_and_disabled_rules(self):
        self.rule("bad", "---\nname: broken\nenabled: true\nevent: bash\npattern: (unclosed\n---\nx\n")
        self.rule("noevent", "---\nname: noevent\nenabled: true\nevent: shell\npattern: x\n---\nx\n")
        self.rule("off", "---\nname: off-rule\nenabled: false\nevent: bash\naction: block\npattern: .*\n---\nx\n")
        r = self.bash("echo hi")
        self.assertAllowed(r)
        self.assertIn("hookify: skipped hookify.bad.local.md: `pattern` '(unclosed' is not a valid regex", r.context)
        self.assertIn("`event` is 'shell'. Fix: use one of bash, file, prompt, stop, all.", r.context)
        self.assertEqual(self.bash("echo again").context, "", "a malformed rule is reported once per session")

    def test_nearest_claude_dir_from_subdirectory(self):
        self.rule("rmrf", "---\nname: block-rm\nenabled: true\nevent: all\naction: block\npattern: rm -rf\n---\nNo.\n")
        sub = os.path.join(self.s.work, "deep", "er")
        os.makedirs(sub)
        r = self.s.dispatch("PreToolUse", self.base(cwd=sub, tool_name="Bash", tool_input={"command": "rm -rf x"}))
        self.assertBlocked(r, "[hookify:block-rm] No.")


# ---------------------------------------------------------------- safety-guard careful and freeze

class TestSafetyGuard(HookTest):
    def guard(self, name, text):
        return self.s.write(f"home/.local/state/neva/safety-guard/{name}", text)

    def bash(self, cmd):
        return self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": cmd}))

    def test_careful_off_by_default(self):
        self.assertEqual(self.bash("rm -rf src").decision, "")

    def test_careful_asks_on_destructive_commands(self):
        self.guard("careful", "")
        for cmd, needle in (("rm -rf src", "rm -r deletes src"), ("git reset --hard HEAD~2", "git reset --hard"),
                            ("psql -c 'DROP TABLE users'", "DROP TABLE"), ("git push -f origin main", "force push"),
                            ("sudo rm /etc/x", "sudo rm"), ("kubectl delete pod web", "kubectl delete"),
                            ("chmod -R 777 .", "chmod 777")):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.decision, "ask")
                self.assertIn("[careful]", r.out["hookSpecificOutput"]["permissionDecisionReason"])
                self.assertIn(needle, r.out["hookSpecificOutput"]["permissionDecisionReason"])
        for cmd in ("rm -rf node_modules dist", "rm -rf ./build/", "git push --force-with-lease origin feat",
                    "rm file.txt", "git status"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd).decision, "")
        log = self.s.read(os.path.join(self.s.state, "safety-guard.log"))
        self.assertIn('"pattern": "rm-recursive"', log)
        self.assertNotIn("users", log, "the log keeps rule names, never command text")

    def test_freeze_boundary(self):
        src = os.path.join(self.s.work, "src")
        os.makedirs(src)
        os.makedirs(os.path.join(self.s.work, "src-old"))
        self.guard("freeze-dir.txt", src + "/\n")
        edit = lambda p: self.s.dispatch("PreToolUse", self.base(tool_name="Edit", tool_input={
            "file_path": p, "old_string": "a", "new_string": "b"}))
        self.assertAllowed(edit(os.path.join(src, "a.py")))
        self.assertAllowed(edit("src/b.py"))
        self.assertBlocked(edit(os.path.join(self.s.work, "src-old", "a.py")), "outside the freeze boundary")
        self.assertBlocked(edit(os.path.join(src, "..", "README.md")), "[freeze] Blocked")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Edit", tool_input={
            "file_path": os.path.join(self.s.work, "README.md"), "old_string": "a", "new_string": "b"}),
            NEVA_HOOK_PROFILE="minimal")
        self.assertBlocked(r, "[freeze]")
        self.guard("freeze-dir.txt", "")
        self.assertAllowed(edit(os.path.join(self.s.work, "README.md")))

    def test_state_dir_override(self):
        alt = os.path.join(self.s.tmp, "state-alt")
        self.s.write("state-alt/safety-guard/careful", "")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Bash", tool_input={"command": "rm -rf src"}),
                            NEVA_STATE_DIR=alt)
        self.assertEqual(r.decision, "ask")


# ---------------------------------------------------------------- gateguard state location

class TestGateGuardState(HookTest):
    def test_state_lives_under_state_dir(self):
        f = self.s.write("work/proj/src/lib.py", "x = 1\n")
        call = self.base(tool_name="Edit", tool_input={"file_path": f, "old_string": "1", "new_string": "2"})
        self.assertBlocked(self.s.dispatch("PreToolUse", call, NEVA_HOOK_PROFILE="strict"), "Fact-Forcing Gate")
        self.assertTrue(os.path.exists(os.path.join(self.s.state, "gateguard", "11111111-2222-3333-4444-555566667777.json")))
        alt = os.path.join(self.s.tmp, "st")
        r = self.s.dispatch("PreToolUse", dict(call, session_id="s2"), NEVA_HOOK_PROFILE="strict", NEVA_STATE_DIR=alt)
        self.assertBlocked(r, "Fact-Forcing Gate")
        self.assertTrue(os.path.exists(os.path.join(alt, "gateguard", "s2.json")))
        settings = self.s.write("work/proj/.claude/settings.local.json", "{}")
        r = self.s.dispatch("PreToolUse", self.base(tool_name="Edit", tool_input={
            "file_path": settings, "old_string": "{", "new_string": "{ "}), NEVA_HOOK_PROFILE="strict")
        self.assertAllowed(r)


# ---------------------------------------------------------------- delivery gate

class TestDeliveryGate(HookTest):
    def transcript(self, edits, text="done"):
        entries = [user("do it")]
        entries += [tool("Edit", {"file_path": f"/x/{n}.py"}) for n in range(edits)]
        entries.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text",
                                                                                            "text": text}]}})
        return self.s.transcript(f"dg{edits}{len(text)}", entries)

    def stop(self, tp, **env):
        env.setdefault("NEVA_DISABLED_HOOKS", "journal_nudge,format_typecheck")
        env.setdefault("NEVA_HOOK_PROFILE", "strict")
        return self.s.dispatch("Stop", self.base(transcript_path=tp), **env)

    def mem(self, touched=()):
        mem = os.path.join(self.s.tmp, "mem")
        for rel in ("ratings-tracker.md", "decisions/log.md", "growth-log/2026.md", "output-index.md",
                    "tooling_capabilities.md"):
            p = self.s.write(f"mem/{rel}", "x")
            if not any(rel.startswith(t) for t in touched):
                os.utime(p, (time.time() - 3 * 86400,) * 2)
        return mem

    def test_disk_critical_blocks_only_in_strict(self):
        tp = self.transcript(0)
        self.assertBlocked(self.stop(tp, NEVA_DELIVERY_DISK_CRIT_GB=10 ** 9), "Blocked: disk space at")
        self.assertAllowed(self.stop(tp, NEVA_DELIVERY_DISK_CRIT_GB=10 ** 9, NEVA_HOOK_PROFILE="standard"))

    def test_complex_task_without_learning_blocks(self):
        tp = self.transcript(4)
        mem = self.mem()
        self.assertBlocked(self.stop(tp, NEVA_MEMORY_DIR=mem), "learning libraries are stale")
        mem = self.mem(touched=("ratings", "decisions", "output", "tooling"))
        self.assertBlocked(self.stop(tp, NEVA_MEMORY_DIR=mem), "no growth-log update today")
        mem = self.mem(touched=("growth-log", "ratings", "decisions"))
        r = self.stop(tp, NEVA_MEMORY_DIR=mem)
        self.assertAllowed(r)
        self.assertIn("Stale learning libraries (2)", r.out.get("systemMessage", ""))

    def test_simple_task_and_missing_memory_never_block(self):
        self.assertAllowed(self.stop(self.transcript(1), NEVA_MEMORY_DIR=self.mem()))
        r = self.stop(self.transcript(5), NEVA_MEMORY_DIR=os.path.join(self.s.tmp, "none"))
        self.assertAllowed(r)
        self.assertIn("No project memory directory", r.out.get("systemMessage", ""))

    def test_rationalization_warns_and_retry_never_blocks(self):
        tp = self.transcript(0, "That is a pre-existing issue. Skipping tests for now.")
        r = self.stop(tp)
        self.assertAllowed(r)
        self.assertIn("Rationalization phrases", r.out.get("systemMessage", ""))
        r = self.s.dispatch("Stop", self.base(transcript_path=self.transcript(4), stop_hook_active=True),
                            NEVA_HOOK_PROFILE="strict", NEVA_MEMORY_DIR=self.mem(),
                            NEVA_DISABLED_HOOKS="journal_nudge,format_typecheck")
        self.assertAllowed(r)


# ---------------------------------------------------------------- plan-canvas pending feedback

class TestPlanCanvasStop(HookTest):
    def serve(self, payload):
        import http.server
        import threading
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1], calls

    def state(self, port, file, pending=True, status="feedback"):
        key = "abcdef012345"
        self.s.write("home/.local/state/neva/plan-canvas/sessions.json", json.dumps({"sessions": {key: {
            "key": key, "file": file, "status": status, "pendingFeedback": [{"kind": "chat"}] if pending else []}}}))
        self.s.write("home/.local/state/neva/plan-canvas/server.json", json.dumps({"port": port}))
        return key

    def stop(self, **env):
        return self.s.dispatch("Stop", self.base(), NEVA_DISABLED_HOOKS="journal_nudge", **env)

    def test_pending_feedback_blocks_with_items(self):
        port, calls = self.serve({"status": "feedback", "items": [
            {"kind": "annotation", "text": "Split this", "anchor": {"selector": "h2", "snippet": "Phase 2"}},
            {"kind": "verdict", "verdict": "request-changes"}]})
        key = self.state(port, os.path.join(self.s.work, "plan.md"))
        r = self.stop()
        self.assertBlocked(r, 'annotation on "Phase 2": Split this')
        self.assertIn("verdict: request-changes", r.stderr)
        self.assertEqual(calls, [f"/api/await?key={key}&timeoutMs=0"])

    def test_outside_cwd_ignored_unless_scope_all(self):
        port, calls = self.serve({"status": "feedback", "items": [{"kind": "chat", "text": "hi"}]})
        self.state(port, "/somewhere/else/plan.md")
        self.assertAllowed(self.stop())
        self.assertEqual(calls, [])
        self.assertBlocked(self.stop(NEVA_PLAN_CANVAS_STOP_SCOPE="all"), "chat: hi")

    def test_server_down_or_nothing_pending_allows(self):
        self.state(1, os.path.join(self.s.work, "plan.md"))
        self.assertAllowed(self.stop())
        port, calls = self.serve({"status": "feedback", "items": []})
        self.state(port, os.path.join(self.s.work, "plan.md"), pending=False)
        self.assertAllowed(self.stop())
        self.assertEqual(calls, [])


# ---------------------------------------------------------------- inbox target

class TestInboxTarget(HookTest):
    def test_root_inbox_with_open_actions(self):
        self.s.write("vault/inbox.md", "# Inbox\n\n## Open actions\n- [ ] ROOT-INBOX-ACTION\n\n## Later\n- nope\n")
        r = self.s.dispatch("SessionStart", self.base(source="startup"), NEVA_INBOX="inbox.md")
        self.assertIn("ROOT-INBOX-ACTION", r.context)
        self.assertNotIn("Call the plumber", r.context)
        r = self.s.dispatch("SessionStart", self.base(source="startup"))
        self.assertIn("Call the plumber", r.context, "default is the template's 00 Inbox/inbox.md")


# ---------------------------------------------------------------- instinct round trip

FAKE_CLAUDE = r'''#!{py}
import json, os, re, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
log_dir = os.environ["FAKE_LOG_DIR"]
analysis = re.search(r"Read (.+?) and identify patterns", prompt).group(1)
idir = re.search(r"directly to (.+?)/<id>\.md", prompt).group(1)
pid = re.search(r"project_id: (\S+)", prompt).group(1)
lines = [json.loads(x) for x in open(analysis) if x.strip()]
with open(os.path.join(log_dir, "claude-calls.log"), "a") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "skip": os.environ.get("NEVA_SKIP_OBSERVE"),
                         "headless": os.environ.get("NEVA_HEADLESS"), "profile": os.environ.get("NEVA_HOOK_PROFILE"),
                         "events": [x.get("event") for x in lines], "paths": [x.get("path") for x in lines]}}) + "\n")
if os.environ.get("FAKE_CLAUDE_MODE") == "fail":
    sys.stderr.write("model unavailable\n"); sys.exit(1)
reads = sum(1 for x in lines if x.get("tool") == "Read" and x.get("event") == "tool_start")
os.makedirs(idir, exist_ok=True)
open(os.path.join(idir, "read-before-edit.md"), "w").write(
    "---\nid: read-before-edit\ntrigger: \"when changing a file\"\nconfidence: 0.85\ndomain: workflow\n"
    "source: session-observation\nscope: project\nscope_hint: global\nproject_id: " + pid + "\n"
    "project_name: \"proj\"\nevidence_count: " + str(reads) + "\ndate: 2026-01-01\nlast_observed: "
    + __import__("datetime").date.today().isoformat() + "\ndecay_weeks_applied: 0\nstatus: active\n"
    "tags: [instinct, workflow]\n---\n\n# Read before edit\n\n## Action\nRead the whole file before editing it.\n\n"
    "## Evidence\n- Observed " + str(reads) + " times\n")
print('{{"status":"analysis_complete"}}')
'''


class TestInstinctRoundTrip(HookTest):
    def setUp(self):
        super().setUp()
        self.s.write("bin/claude", FAKE_CLAUDE.format(py=PY), 0o755)
        self.root = os.path.join(self.s.vault, "06 Memory", "instincts")

    def observe_session(self, n=11):
        f = os.path.join(self.s.work, "app.py")
        for i in range(n):
            self.s.dispatch("PreToolUse", self.base(tool_name="Read", tool_input={"file_path": f}))
            self.s.dispatch("PostToolUse", self.base(tool_name="Read", tool_input={"file_path": f},
                                                     tool_response=f"line {i}"))

    def proposal(self, folder):
        return os.path.join(folder, f"Instinct promotions {datetime.date.today().isoformat()}.md")

    def tick(self, path, block_id, box="approve"):
        text = self.s.read(path)
        i = text.index(f"- [ ] {box}", text.index(f"block_id: {block_id}"))
        with open(path, "w") as fh:
            fh.write(text[:i] + f"- [x] {box}" + text[i + len(f"- [ ] {box}"):])

    def run_round_trip(self, inbox_note, proposals_dir, **env):
        self.observe_session()
        self.assertEqual(len(self.s.obs_lines()), 22)
        code, out = self.s.cli("analyze", FAKE_LOG_DIR=self.s.tmp, **env)
        self.assertEqual(code, 0, out)
        call = json.loads(self.s.read(os.path.join(self.s.tmp, "claude-calls.log")).splitlines()[0])
        self.assertEqual((call["skip"], call["headless"], call["profile"]), ("1", "1", "minimal"))
        self.assertIn("tool_start", call["events"])
        self.assertIn(os.path.join(self.s.work, "app.py"), call["paths"], "observe must write the path field")
        note = os.path.join(self.root, "project", self.s.pid, "read-before-edit.md")
        self.assertTrue(os.path.exists(note), out)
        self.assertEqual(self.s.obs_lines(), [], "analyzed observations move to the archive")
        arch = os.path.join(os.path.dirname(self.s.obs_file()), "observations.archive")
        self.assertEqual(len(os.listdir(arch)), 1)

        r = self.s.dispatch("SessionStart", self.base(source="startup", session_id="next-session"), **env)
        self.assertIn("[project 85%] Read the whole file before editing it.", r.context)

        prop = self.proposal(proposals_dir)
        self.assertTrue(os.path.exists(prop), out)
        text = self.s.read(prop)
        self.assertIn("block_id: promote-global:read-before-edit", text)
        self.assertIn("status: open", text)
        inbox = self.s.read(inbox_note)
        link = f"[[Instinct promotions {datetime.date.today().isoformat()}]]"
        self.assertIn(f"- [ ] Review instinct proposals: {link}", inbox)
        acts = inbox.split("## Open actions", 1)[1].split("\n## ", 1)[0]
        self.assertIn(link, acts, "the pointer lands inside the Open actions section")
        self.assertIn("Instinct proposals awaiting the owner's review: 1 file(s)", r.context)
        self.assertIn("Review instinct proposals", r.context, "session start shows the pointer as an open action")

        code, out = self.s.cli("apply-promotions", **env)
        self.assertEqual(code, 0, out)
        global_note = os.path.join(self.root, "global", "read-before-edit.md")
        self.assertFalse(os.path.exists(global_note), "nothing is applied until the owner ticks approve")

        self.tick(prop, "promote-global:read-before-edit")
        code, out = self.s.cli("apply-promotions", **env)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(global_note))
        self.assertIn("status: promoted", self.s.read(note))
        self.assertIn("status: done", self.s.read(prop))
        self.assertIn(f"- [x] Review instinct proposals: {link}", self.s.read(inbox_note))

        r = self.s.dispatch("SessionStart", self.base(source="startup", session_id="third-session"), **env)
        self.assertIn("[global 85%] Read the whole file before editing it.", r.context)
        self.assertNotIn("Instinct proposals awaiting", r.context)

    def test_round_trip_template_inbox(self):
        inbox_dir = os.path.join(self.s.vault, "00 Inbox")
        self.run_round_trip(os.path.join(inbox_dir, "inbox.md"), inbox_dir)
        self.assertIn("Call the plumber about the leak", self.s.read(os.path.join(inbox_dir, "inbox.md")))

    def test_round_trip_root_inbox(self):
        self.s.write("vault/inbox.md", "# Inbox\n\n## Open actions\n- [ ] existing action\n\n## Waiting\n- x\n")
        self.run_round_trip(os.path.join(self.s.vault, "inbox.md"),
                            os.path.join(self.root, "proposals"), NEVA_INBOX="inbox.md")
        text = self.s.read(os.path.join(self.s.vault, "inbox.md"))
        self.assertLess(text.index("existing action"), text.index("Review instinct proposals"))
        self.assertLess(text.index("Review instinct proposals"), text.index("## Waiting"))

    def test_analysis_failure_keeps_observations(self):
        self.observe_session()
        code, out = self.s.cli("analyze", FAKE_LOG_DIR=self.s.tmp, FAKE_CLAUDE_MODE="fail")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "project", self.s.pid)) and
                         os.listdir(os.path.join(self.root, "project", self.s.pid)))
        self.assertEqual(len(self.s.obs_lines()), 22, "a failed analysis retains every observation")
        self.assertIn("observations retained for retry", out)

    def test_shim_resolves_vault_from_identity_file(self):
        cfg = self.s.write("home/.config/neva/identity.env", f'VAULT_PATH="{self.s.vault}"\n')
        code, out = self.s.cli("status", NEVA_VAULT=None, NEVA_CONFIG=cfg)
        self.assertEqual(code, 0, out)
        self.assertIn(self.s.pid, out)
        code, out = self.s.cli("status", NEVA_VAULT=None, NEVA_CONFIG=os.path.join(self.s.tmp, "none"))
        self.assertEqual(code, 2)
        self.assertIn("export NEVA_VAULT=", out)

# ---------------------------------------------------------------- repo integration: docs, templates, installer

REPO_ROOT = os.path.dirname(os.path.dirname(PLUGIN_SRC))


class TestRepoIntegration(unittest.TestCase):
    def test_hooks_doc_lists_every_module(self):
        with open(os.path.join(REPO_ROOT, "docs", "harness", "hooks.md"), encoding="utf-8") as fh:
            doc = fh.read()
        with open(os.path.join(SRC, "hooks.meta.json")) as fh:
            meta = json.load(fh)
        for m in meta["modules"]:
            self.assertIn(f"| `{m['id']}` |", doc, f"docs/harness/hooks.md is missing {m['id']}")

    def test_docs_state_the_real_thresholds(self):
        with open(os.path.join(REPO_ROOT, "docs", "harness", "02-token-economy.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("800k on a 1M window", text)
        self.assertNotIn("250k", text)
        with open(os.path.join(REPO_ROOT, "docs", "harness", "03-memory-and-learning.md"), encoding="utf-8") as fh:
            mem = fh.read()
        self.assertIn("project/<project-id>/<id>.md", mem)
        self.assertIn("| `NEVA_SESSION_RETENTION_DAYS` | 30 |", mem)

    def test_vault_template_seeds_inbox_and_instincts(self):
        with open(os.path.join(REPO_ROOT, "vault", "00 Inbox", "inbox.md"), encoding="utf-8") as fh:
            self.assertIn("\n## Open actions\n", fh.read())
        self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, "vault", "06 Memory", "instincts", "README.md")))

    def test_instinct_timer_templates(self):
        svc = os.path.join(REPO_ROOT, "services")
        plist = os.path.join(svc, "launchd", "com.neva.instinct-analyze.plist.tmpl")
        unit = os.path.join(svc, "systemd", "neva-instinct-analyze.service.tmpl")
        timer = os.path.join(svc, "systemd", "neva-instinct-analyze.timer.tmpl")
        for p in (plist, unit, timer):
            self.assertTrue(os.path.exists(p), p)
        with open(plist) as fh:
            text = fh.read()
        self.assertIn("heartbeat-wrap.sh</string><string>instinct-analyze", text)
        self.assertIn("@PREFIX@/plugins/neva-core/skills/continuous-learning-v2/scripts/instinct-analyze.py", text)
        with open(unit) as fh:
            self.assertIn("heartbeat-wrap.sh instinct-analyze", fh.read())
        with open(timer) as fh:
            self.assertIn("OnCalendar=*-*-* 03:30:00", fh.read())

    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "install.sh supports macOS and Linux")
    def test_install_is_idempotent_and_installs_rules(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="neva-install-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = {"HOME": home, "PATH": os.environ.get("PATH", ""), "TERM": "dumb", "NEVA_NONINTERACTIVE": "1",
               "NEVA_SKIP_SCHEDULE_ENABLE": "1", "OWNER_NAME": "Tester", "VAULT_PATH": os.path.join(home, "Vault"),
               "WORKSPACE_PATH": os.path.join(home, "ws"), "NEVA_PLUGINS": "core,mobile,bogus"}
        outs = []
        for _ in range(2):
            p = subprocess.run(["bash", os.path.join(REPO_ROOT, "install.sh")], env=env, capture_output=True,
                               text=True, stdin=subprocess.DEVNULL, timeout=300)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            outs.append(p.stdout)
        out = outs[1]
        self.assertIn(f'claude plugin marketplace add "{REPO_ROOT}"', out)
        self.assertIn("claude plugin install neva-core@neva", out)
        self.assertIn("claude plugin install neva-mobile@neva", out)
        self.assertNotIn("neva-web@neva", out)
        self.assertIn("unknown plugin 'bogus' in NEVA_PLUGINS, skipped. fix:", out)
        rules = os.path.join(home, ".claude", "rules", "neva")
        self.assertTrue(os.path.exists(os.path.join(rules, "common", "process.md")))
        self.assertTrue(os.path.isdir(os.path.join(rules, "swift")), "enabled plugin language packs are copied")
        self.assertFalse(os.path.isdir(os.path.join(rules, "python")), "disabled plugins add no rules")
        rendered = os.path.join(home, ".local", "neva", "services",
                                "com.neva.instinct-analyze.plist" if sys.platform == "darwin"
                                else "neva-instinct-analyze.service")
        with open(rendered) as fh:
            text = fh.read()
        for token in ("@PREFIX@", "@HOME@", "@SERVICE_PATH@"):
            self.assertNotIn(token, text, f"unrendered {token} in {rendered}")
        self.assertIn(os.path.join(home, ".local", "bin"), text, "the service PATH is baked in")
        engine = os.path.join(home, ".local", "neva", "plugins", "neva-core", "skills", "continuous-learning-v2",
                              "scripts", "instinct-analyze.py")
        self.assertTrue(os.path.exists(engine))
        self.assertTrue(os.path.exists(os.path.join(home, "Vault", "00 Inbox", "inbox.md")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
