#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Tests for harness_audit.py. A fixture Neva repo (repo mode) and a fixture machine with the
plugin installed (consumer mode), each fully healthy, then one defect at a time.

Run:  python3 plugins/neva-core/scripts/tests/test_harness_audit.py
"""
import datetime
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

sys.path.insert(0, support.SCRIPTS)
import harness_audit as ha  # noqa: E402

NOW = "2026-09-29T12:00:00Z"
NOW_TS = datetime.datetime(2026, 9, 29, 12, tzinfo=datetime.timezone.utc).timestamp()
DAY = 86400
REPO_ROOT = os.path.dirname(os.path.dirname(support.PLUGIN))

HOOKS_JSON = {"hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" SessionStart'}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" PreToolUse bash'}]},
                   {"matcher": "Write", "hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" PreToolUse write'}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" PostToolUse'}]}],
    "Stop": [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/dispatch.py" Stop'}]}],
}}
META = {"modules": [
    {"id": "session_start", "module": "session_start", "function": "run", "events": ["SessionStart"]},
    {"id": "no_verify", "module": "pre_bash", "function": "no_verify", "events": ["PreToolUse:bash"]},
    {"id": "suggest_compact", "module": "pre_write", "function": "suggest_compact", "events": ["PreToolUse:write"]},
    {"id": "observe", "module": "observe", "function": "observe", "events": ["PostToolUse"]},
    {"id": "session_summary", "module": "stop", "function": "session_summary", "events": ["Stop"]},
    {"id": "cost_tracker", "module": "stop", "function": "cost_tracker", "events": ["Stop"]},
]}
MODULES = {"session_start": ["run"], "pre_bash": ["no_verify"], "pre_write": ["suggest_compact"],
           "observe": ["observe"], "stop": ["session_summary", "cost_tracker"]}


def skill(desc):
    return f"---\nname: s\ndescription: {desc}\n---\n\nbody\n"


def agent(model):
    return f"---\nname: a\ndescription: d\ntools: Read\n" + (f"model: {model}\n" if model else "") + "---\n\nbody\n"


def build_core(sb, root):
    """A healthy neva-core plugin at root."""
    w = lambda rel, c: sb.write(os.path.join(root, rel), c)  # noqa: E731
    w(".claude-plugin/plugin.json", {"name": "neva-core", "version": "0.0.1"})
    w("hooks/hooks.json", HOOKS_JSON)
    w("hooks/hooks.meta.json", META)
    w("hooks/dispatch.py", "# dispatcher\n")
    w("hooks/instincts.py", "# cli\n")
    for mod, fns in MODULES.items():
        w(f"hooks/neva_hooks/{mod}.py", "".join(f"def {f}(ctx):\n    return None\n\n" for f in fns))
    w("hooks/tests/test_hooks.py", "import unittest\n" + "".join(f"def test_{i}():\n    pass\n" for i in range(6)))
    w("scripts/tests/test_scripts.py", "".join(f"def test_{i}():\n    pass\n" for i in range(6)))
    w("scripts/ok.py", "print(1)\n")
    for i in range(10):
        w(f"agents/agent-{i}.md", agent("opus" if i % 2 else "sonnet"))
    w("agents/security-reviewer.md", agent("opus"))
    for name in ("strategic-compact", "continuous-learning-v2", "eval-harness", "verification-loop",
                 "security-review", "cost-aware-llm-pipeline", "security-scan"):
        w(f"skills/{name}/SKILL.md", skill("Use when testing the audit."))
    for i in range(16):
        w(f"skills/extra-{i}/SKILL.md", skill('"Use when a quoted description: with a colon."'))
    for name in ("checkpoint", "model-route"):
        w(f"commands/{name}.md", "---\ndescription: x\n---\n")
    w("commands/runner.md", '---\ndescription: x\n---\n\n```bash\npython3 "${CLAUDE_PLUGIN_ROOT}/scripts/ok.py" --flag\n```\n')
    for r in ("coding-style.md", "security.md", "testing.md"):
        w(f"rules/{r}", "# rule\n")
    w("rules/README.md", "# how to install\n")
    w(".mcp.json", {"mcpServers": {"chrome-devtools": {"command": "npx"}}})


def build_repo(sb):
    root = sb.path("neva")
    build_core(sb, os.path.join(root, "plugins", "neva-core"))
    sb.write(os.path.join(root, "plugins", "neva-web", ".claude-plugin", "plugin.json"), {"name": "neva-web"})
    sb.write(os.path.join(root, ".claude-plugin", "marketplace.json"), {"name": "neva", "plugins": [
        {"name": "neva-core", "source": "./plugins/neva-core"}, {"name": "neva-web", "source": "./plugins/neva-web"}]})
    for rel in ("build/verify.sh", "build/leak-scan.py", "bin/doctor", "vault/.keep", "docs/harness/02-token-economy.md",
                ".github/workflows/ci.yml", ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/bug.md",
                ".github/CODEOWNERS", ".github/dependabot.yml"):
        sb.write(os.path.join(root, rel), "x\n")
    return root


def audit(sb, *args, env=None):
    r = sb.run("harness_audit.py", "--format", "json", "--now", NOW, *args, env=env)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


class TestRepoMode(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-audit-repo-")
        self.root = build_repo(self.sb)
        self.core = os.path.join(self.root, "plugins", "neva-core")

    def tearDown(self):
        self.sb.close()

    def run_audit(self, *args):
        return audit(self.sb, "--root", self.root, *args)

    def test_healthy_repo_scores_full(self):
        r = self.run_audit()
        self.assertEqual(r["target_mode"], "repo")
        failing = [c["id"] for c in r["checks"] if not c["pass"]]
        self.assertEqual(failing, [])
        self.assertEqual(r["overall_score"], r["max_score"])
        self.assertEqual(r["top_actions"], [])
        self.assertEqual(r["rubric_version"], ha.RUBRIC_VERSION)
        self.assertEqual(set(r), {"scope", "root_dir", "target_mode", "deterministic", "rubric_version", "generated_for",
                                  "overall_score", "max_score", "categories", "applicable_categories", "category_count",
                                  "checks", "top_actions"})
        self.assertNotIn("Vercel Integration", r["applicable_categories"])

    def test_defects_fail_their_own_check(self):
        sb, core = self.sb, self.core
        sb.write(os.path.join(core, "agents/agent-0.md"), agent(None))
        sb.write(os.path.join(core, "skills/extra-0/SKILL.md"), skill("x" * 301))
        sb.write(os.path.join(core, "skills/extra-1/SKILL.md"), "---\nname: s\n---\n")
        sb.write(os.path.join(core, "commands/broken.md"), 'run `node "${CLAUDE_PLUGIN_ROOT}/scripts/gone.js"`.\n')
        meta = json.loads(json.dumps(META))
        meta["modules"].append({"id": "ghost", "module": "ghost", "function": "run", "events": ["SessionEnd"]})
        meta["modules"][1]["function"] = "renamed"
        sb.write(os.path.join(core, "hooks/hooks.meta.json"), meta)
        os.remove(os.path.join(self.root, "plugins/neva-web/.claude-plugin/plugin.json"))
        c = by_id(self.run_audit())
        self.assertFalse(c["cost-model-pins"]["pass"])
        self.assertIn("neva-core/agent-0 (none)", c["cost-model-pins"]["detail"])
        self.assertFalse(c["skill-description-length"]["pass"])
        self.assertIn("extra-0 (301)", c["skill-description-length"]["detail"])
        self.assertIn("extra-1 (no description)", c["skill-description-length"]["detail"])
        self.assertFalse(c["plugin-root-refs"]["pass"])
        self.assertIn("commands/broken.md -> scripts/gone.js", c["plugin-root-refs"]["detail"])
        self.assertFalse(c["hooks-modules-resolve"]["pass"])
        self.assertIn("ghost: event SessionEnd has no dispatch.py entry", c["hooks-modules-resolve"]["detail"])
        self.assertIn("renamed() not defined", c["hooks-modules-resolve"]["detail"])
        self.assertFalse(c["marketplace-plugins"]["pass"])
        self.assertIn("neva-web (no manifest", c["marketplace-plugins"]["detail"])

    def test_300_characters_is_inside_budget(self):
        self.sb.write(os.path.join(self.core, "skills/extra-0/SKILL.md"), skill("y" * 300))
        folded = "---\nname: s\ndescription: >\n  " + "word " * 30 + "\n  " + "more " * 20 + "\n---\n"
        self.sb.write(os.path.join(self.core, "skills/extra-2/SKILL.md"), folded)
        self.assertTrue(by_id(self.run_audit())["skill-description-length"]["pass"])

    def test_scope_filters_checks_and_score(self):
        r = self.run_audit("agents")
        ids = {c["id"] for c in r["checks"]}
        self.assertEqual(ids, {"tool-agent-count", "plugin-root-refs", "security-agent", "cost-model-pins"})
        self.assertEqual(r["max_score"], 1 + 1 + 3 + 4)

    def test_category_scores_round_half_up_and_top_actions_by_points(self):
        os.remove(os.path.join(self.root, ".github/workflows/ci.yml"))
        os.remove(os.path.join(self.root, ".github/CODEOWNERS"))
        r = self.run_audit()
        gh = r["categories"]["GitHub Integration"]
        self.assertEqual((gh["earned"], gh["max"], gh["score"]), (6, 10, 6))
        self.assertEqual(r["top_actions"][0]["points"], 3)
        self.assertEqual(r["overall_score"], r["max_score"] - 4)
        os.remove(os.path.join(self.root, ".github/dependabot.yml"))
        os.remove(os.path.join(self.root, ".github/pull_request_template.md"))
        os.remove(os.path.join(self.root, ".github/ISSUE_TEMPLATE/bug.md"))
        self.assertEqual(self.run_audit()["categories"]["GitHub Integration"]["score"], 0)
        self.assertEqual(ha.js_round(2.5), 3)
        self.assertEqual(ha.js_round(3.5), 4)

    def test_text_output_lists_failing_checks(self):
        os.remove(os.path.join(self.root, "bin/doctor"))
        r = self.sb.run("harness_audit.py", "--root", self.root, "--now", NOW)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Harness Audit (repo, repo): ", r.stdout)
        self.assertIn("Top 3 Actions:\n1) [Quality Gates] Add bin/doctor", r.stdout)
        self.assertIn("- quality-doctor (2 pts) bin/doctor", r.stdout)

    def test_same_inputs_same_report(self):
        self.assertEqual(self.run_audit(), self.run_audit())


class TestConsumerMode(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-audit-consumer-")
        sb = self.sb
        self.core = sb.path("home", ".claude", "plugins", "cache", "neva", "neva-core", "0.0.1")
        build_core(sb, self.core)
        sb.write("home/.claude/plugins/installed_plugins.json",
                 {"version": 2, "plugins": {"neva-core@neva": [{"scope": "user", "installPath": self.core}]}})
        sb.write("home/.claude/settings.json", {"enabledPlugins": {"neva-core@neva": True}})
        for r in ("coding-style.md", "security.md", "testing.md"):
            sb.write(f"home/.claude/rules/neva/common/{r}", "# rule\n")
        self.data = sb.path("home", ".local", "share", "neva")
        self.touch(os.path.join(self.data, "sessions", "a-session.tmp"), NOW_TS - DAY)
        self.touch(os.path.join(self.data, "costs.jsonl"), NOW_TS - DAY)
        sb.write(os.path.join(self.data, "hooks.log"), "2026-09-01 10:00:00 [error] module observe on Stop: old\n"
                                                        "2026-09-28 10:00:00 [slow] observe took 2.00s on Stop\n")
        self.vault = sb.path("vault")
        sb.write("vault/06 Memory/instincts/global/prefer-tests.md",
                 "---\nid: prefer-tests\nconfidence: 0.8\nupdated: 2026-09-20\n---\n\n## Action\nx\n")
        sb.write("home/.config/neva/identity.env", f'VAULT_PATH="{self.vault}"\n')
        sb.write("home/.claude.json", {"mcpServers": {"a": {}, "b": {}}, "projects": {}})
        self.proj = sb.path("work", "proj")
        for rel, content in (("CLAUDE.md", "# p\n"), (".mcp.json", {"mcpServers": {"p1": {}}}),
                             ("tests/test_app.py", "def test_x():\n    pass\n"), (".github/workflows/ci.yml", "on: push\n"),
                             (".gitignore", ".env\n"), ("SECURITY.md", "x\n"), (".claude/memory.md", "x\n"),
                             (".claude/settings.json", {"hooks": {}}), ("evals/checkout.json", "{}\n")):
            sb.write(os.path.join(self.proj, rel), content)

    def tearDown(self):
        self.sb.close()

    def touch(self, path, ts):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "a").close()
        os.utime(path, (ts, ts))

    def run_audit(self, *args, env=None):
        return audit(self.sb, "--root", self.proj, "--mcp-tools", "40", *args, env=env)

    NEVA_IDS = ("neva-core-installed", "neva-core-enabled", "hooks-registered", "mcp-server-budget", "mcp-tool-budget",
                "skill-description-length", "hooks-firing", "hooks-log-clean", "vault-configured", "instincts-fresh",
                "consumer-hook-guardrails", "rules-installed", "cost-model-pins", "cost-tracking-active")

    def test_healthy_machine_passes_every_neva_check(self):
        r = self.run_audit()
        self.assertEqual(r["target_mode"], "consumer")
        c = by_id(r)
        for cid in self.NEVA_IDS:
            self.assertTrue(c[cid]["pass"], f"{cid}: {c[cid]['detail']}")
        self.assertEqual(c["neva-core-installed"]["detail"], "neva-core@neva via installed_plugins.json")
        self.assertEqual(c["mcp-server-budget"]["detail"], "4 enabled: a (user), b (user), p1 (project), "
                                                           "chrome-devtools (plugin neva-core)")
        failing = sorted(x["id"] for x in r["checks"] if not x["pass"])
        self.assertEqual(failing, ["github-codeowners", "github-dep-updates", "github-issue-templates",
                                   "github-pr-template"])

    def test_nothing_installed(self):
        shutil.rmtree(self.sb.path("home", ".claude"))
        c = by_id(self.run_audit())
        self.assertFalse(c["neva-core-installed"]["pass"])
        self.assertEqual(c["hooks-registered"]["detail"], "neva-core not installed")
        self.assertFalse(c["rules-installed"]["pass"])
        self.assertFalse(c["cost-model-pins"]["pass"], "no agents is not a pass")

    def test_cache_layout_and_plugin_root_fallbacks(self):
        os.remove(self.sb.path("home/.claude/plugins/installed_plugins.json"))
        c = by_id(self.run_audit())
        self.assertEqual(c["neva-core-installed"]["detail"], "neva-core@neva via plugin cache")
        shutil.rmtree(self.sb.path("home/.claude/plugins/cache"))
        elsewhere = self.sb.path("elsewhere", "neva-core")
        build_core(self.sb, elsewhere)
        c = by_id(self.run_audit(env={"CLAUDE_PLUGIN_ROOT": elsewhere}))
        self.assertEqual(c["neva-core-installed"]["detail"], "neva-core via CLAUDE_PLUGIN_ROOT")

    def test_disabled_plugin_and_disabled_hooks(self):
        self.sb.write(os.path.join(self.proj, ".claude/settings.local.json"),
                      {"enabledPlugins": {"neva-core@neva": False}, "disableAllHooks": True})
        c = by_id(self.run_audit())
        self.assertFalse(c["neva-core-enabled"]["pass"])
        self.assertFalse(c["hooks-registered"]["pass"])
        self.assertEqual(c["hooks-registered"]["detail"], "disableAllHooks is true")
        self.assertFalse(c["consumer-hook-guardrails"]["pass"])
        self.assertNotIn("chrome-devtools", c["mcp-server-budget"]["detail"], "disabled plugin ships no servers")

    def test_hooks_not_firing_and_log_errors(self):
        self.touch(os.path.join(self.data, "sessions", "a-session.tmp"), NOW_TS - 10 * DAY)
        self.touch(os.path.join(self.data, "costs.jsonl"), NOW_TS - 10 * DAY)
        with open(os.path.join(self.data, "hooks.log"), "a") as fh:
            fh.write("2026-09-28 09:00:00 [error] module observe on PostToolUse: Traceback\n")
        c = by_id(self.run_audit())
        self.assertFalse(c["hooks-firing"]["pass"])
        self.assertEqual(c["hooks-firing"]["detail"], "last activity 2026-09-19T12:00:00Z")
        self.assertFalse(c["cost-tracking-active"]["pass"])
        self.assertFalse(c["hooks-log-clean"]["pass"])
        self.assertIn("1 errors, last: 2026-09-28 09:00:00 [error] module observe", c["hooks-log-clean"]["detail"])

    def test_neva_data_dir_override(self):
        moved = self.sb.path("data")
        shutil.move(self.data, moved)
        self.assertFalse(by_id(self.run_audit())["hooks-firing"]["pass"])
        self.assertTrue(by_id(self.run_audit(env={"NEVA_DATA_DIR": moved}))["hooks-firing"]["pass"])

    def test_mcp_budget_counts_every_source_and_honours_disables(self):
        self.sb.write("home/.claude.json", {"mcpServers": {k: {} for k in "abcdef"},
                                            "projects": {self.proj: {"mcpServers": {"l1": {}, "l2": {}}}}})
        c = by_id(self.run_audit())
        self.assertFalse(c["mcp-server-budget"]["pass"])
        self.assertTrue(c["mcp-server-budget"]["detail"].startswith("10 enabled"))
        self.sb.write("home/.claude.json", {"mcpServers": {k: {} for k in "abcdef"},
                                            "projects": {self.proj: {"mcpServers": {"l1": {}, "l2": {}},
                                                                     "disabledMcpServers": ["a"]}}})
        self.assertTrue(by_id(self.run_audit())["mcp-server-budget"]["pass"])
        c = by_id(self.run_audit(env={"NEVA_DISABLED_MCPS": "chrome-devtools"}))
        self.assertTrue(c["mcp-server-budget"]["detail"].startswith("8 enabled"))

    def test_mcp_tool_budget_needs_a_measurement(self):
        r = audit(self.sb, "--root", self.proj)
        c = by_id(r)["mcp-tool-budget"]
        self.assertEqual((c["pass"], c["detail"]), (False, "not measured (pass --mcp-tools)"))
        self.assertIn("--mcp-tools", " ".join(a["action"] for a in r["top_actions"]) +
                      json.dumps(r["checks"]))
        self.assertFalse(by_id(audit(self.sb, "--root", self.proj, "--mcp-tools", "80"))["mcp-tool-budget"]["pass"])
        self.assertTrue(by_id(audit(self.sb, "--root", self.proj, "--mcp-tools", "79"))["mcp-tool-budget"]["pass"])

    def test_rules_and_instincts(self):
        os.remove(self.sb.path("home/.claude/rules/neva/common/security.md"))
        self.sb.write("vault/06 Memory/instincts/pending/proj/maybe.md", "---\nid: maybe\ncreated: 2026-08-01\n---\n")
        self.sb.write("vault/06 Memory/instincts/project/proj/old.md", "---\nid: old\nupdated: 2026-05-01\n---\n")
        c = by_id(self.run_audit())
        self.assertFalse(c["rules-installed"]["pass"])
        self.assertEqual(c["rules-installed"]["detail"], "missing security.md")
        self.assertFalse(c["instincts-fresh"]["pass"])
        self.assertIn("pending/proj/maybe.md (59d)", c["instincts-fresh"]["detail"])
        self.assertIn("project/proj/old.md (151d)", c["instincts-fresh"]["detail"])

    def test_vault_from_env_wins_and_missing_vault_fails(self):
        c = by_id(self.run_audit(env={"NEVA_VAULT": self.sb.path("nope")}))
        self.assertEqual((c["vault-configured"]["pass"], c["vault-configured"]["detail"]), (False, "path missing"))
        self.assertEqual(c["instincts-fresh"]["detail"], "vault not configured")

    def test_provider_checks_appear_only_when_detected(self):
        self.assertNotIn("Cloudflare Integration", self.run_audit()["applicable_categories"])
        self.sb.write(os.path.join(self.proj, "wrangler.toml"), "name = 'x'\n")
        r = self.run_audit()
        self.assertIn("Cloudflare Integration", r["applicable_categories"])
        self.assertFalse(by_id(r)["cloudflare-workflow-uses"]["pass"])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-audit-cli-")

    def tearDown(self):
        self.sb.close()

    def test_errors_name_the_field(self):
        for args, msg in ((["bogus"], "scope: 'bogus' is not valid"), (["--format", "xml"], "--format: 'xml'"),
                          (["--root", "/nonexistent-neva"], "--root: /nonexistent-neva is not a directory"),
                          (["--mcp-tools", "many"], "--mcp-tools: 'many' is not a whole number"),
                          (["--now", "soon"], "--now: 'soon' is not a date"), (["--wat"], "Unknown argument: --wat")):
            r = self.sb.run("harness_audit.py", *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(msg, r.stderr)

    def test_equals_forms(self):
        r = self.sb.run("harness_audit.py", "--scope=hooks", "--format=json", f"--root={self.sb.work}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["scope"], "hooks")


class TestShippedCommands(unittest.TestCase):
    """The commands and agent this port serves must point at scripts that exist."""

    OWNED = ["commands/harness-audit.md", "commands/loop-status.md", "commands/loop-start.md",
             "commands/multi-workflow.md", "commands/multi-plan.md", "commands/multi-execute.md",
             "commands/multi-backend.md", "agents/harness-optimizer.md", "commands/epic-claim.md",
             "commands/epic-sync.md", "commands/epic-validate.md", "commands/epic-publish.md",
             "commands/epic-review.md", "commands/epic-unblock.md", "commands/epic-decompose.md"]

    def test_owned_files_reference_only_shipped_scripts(self):
        refs = 0
        for rel in self.OWNED:
            with open(os.path.join(support.PLUGIN, rel), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("node ", text.replace("node_modules", ""), f"{rel} still calls node")
            self.assertNotIn("not found under the neva-core plugin root", text, f"{rel} still has the stop text")
            for ref in __import__("re").findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)", text):
                refs += 1
                self.assertTrue(os.path.exists(os.path.join(support.PLUGIN, ref.rstrip(".,:;)"))), f"{rel} -> {ref}")
        self.assertGreater(refs, 10)

    def test_real_repo_audit_runs(self):
        if not os.path.exists(os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")):
            self.skipTest("not inside the Neva repo")
        sb = support.Sandbox("neva-audit-real-")
        try:
            r = audit(sb, "--root", REPO_ROOT)
        finally:
            sb.close()
        self.assertEqual(r["target_mode"], "repo")
        _, missing = ha.plugin_root_refs({"neva-core": support.PLUGIN})
        for rel in self.OWNED:
            self.assertEqual([m for m in missing if m.startswith(f"neva-core/{rel} ->")], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
