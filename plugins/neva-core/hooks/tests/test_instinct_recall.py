#!/usr/bin/env python3
# Written for Neva; not adapted from ECC.
"""Instinct recall: the session start block and the first prompt pick instincts by how well their
trigger matches the session, never by confidence rank and id.

Uses the Sandbox from test_hooks.py: a copied plugin, a temporary HOME, a temporary vault and a
temporary state dir. Nothing here reads or writes a real vault.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/hooks/tests -p 'test_instinct_recall.py'
"""
import importlib.util
import json
import os
import unittest

from test_hooks import CL2_SRC, HookTest, today_utc

MATCH_PATH = os.path.join(CL2_SRC, "scripts", "instinct_match.py")
PROMPT_HEAD = "Instincts matched to this prompt"


def load_match():
    spec = importlib.util.spec_from_file_location("neva_instinct_match_test", MATCH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecallTest(HookTest):
    def setUp(self):
        super().setUp()
        # A subfolder of the sandbox repo: same project id, but its name is part of the query.
        self.kestrel = os.path.join(self.s.work, "kestrel")
        os.makedirs(self.kestrel)

    def note(self, rel, iid, trigger, action, conf=0.9, **meta):
        fm = [f"id: {iid}", f'trigger: "{trigger}"', f"confidence: {conf}", "domain: workflow",
              "status: active"] + [f"{k}: {v}" for k, v in meta.items()]
        body = "---\n" + "\n".join(fm) + f"\n---\n\n# {iid}\n\n## Action\n{action}\n\n## Evidence\n- seen\n"
        return self.s.write(f"vault/06 Memory/instincts/{rel}", body)

    def start(self, cwd=None, sid="s-start-1", **env):
        return self.s.dispatch("SessionStart", self.base(source="startup", cwd=cwd or self.kestrel,
                                                         session_id=sid), **env)

    def prompt(self, text, cwd=None, sid="s-start-1", **env):
        return self.s.dispatch("UserPromptSubmit", self.base(prompt=text, cwd=cwd or self.kestrel,
                                                             session_id=sid), **env)

    def sub(self, *parts):
        """A folder below kestrel/: its name joins kestrel in the query, a two stem match."""
        d = os.path.join(self.kestrel, *parts)
        os.makedirs(d, exist_ok=True)
        return d

    def corpus(self, n, pid="otherproject1", trigger="when filler widget {n} turns", start=0):
        """`n` instincts in another project: part of the corpus, never a candidate here."""
        for k in range(start, start + n):
            self.note(f"project/{pid}/c-{k}.md", f"c-{k}", trigger.format(n=k), f"CORPUS-{k}")

    def df_cache(self):
        return os.path.join(self.s.state, "hooks", "instinct-df.json")

    def injections(self):
        p = os.path.join(self.s.state, "instinct-injections.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def instinct_lines(self, ctx):
        return [ln for ln in ctx.splitlines() if ln.startswith("- [project ") or ln.startswith("- [global ")]


# ---------------------------------------------------------------- pure matcher

class TestMatcher(unittest.TestCase):
    def test_tokens_stem_and_drop_stop_words(self):
        m = load_match()
        toks = m.tokens("When the tests are failing, rerun the Figma boards")
        self.assertIn("test", toks)
        self.assertIn("figma", toks)
        self.assertIn("board", toks)
        self.assertNotIn("when", toks)
        self.assertNotIn("the", toks)

    def test_arabic_matches_nothing(self):
        m = load_match()
        self.assertEqual(list(m.tokens("حدث اللوحة في فيجما")), [])

    def test_score_needs_two_shared_or_one_rare(self):
        m = load_match()
        common_item = set(m.tokens("when editing a file in the repo"))
        figma_item = set(m.tokens("when about to call use_figma on a board"))
        filler = [set(m.tokens("sorting widget batch")) for _ in range(200)]
        idf = m.Idf([common_item, figma_item] + [set(m.tokens("editing a file %d" % n)) for n in range(6)] + filler)
        one_common = m.score(m.tokens("editing"), common_item, idf)
        self.assertFalse(one_common.qualifies, "one shared stem found in many instincts is not enough")
        two = m.score(m.tokens("editing the repo"), common_item, idf)
        self.assertTrue(two.qualifies)
        rare = m.score(m.tokens("figma"), figma_item, idf)
        self.assertTrue(rare.qualifies, "one rare stem is enough")
        self.assertEqual(m.score(m.tokens("xylophone"), figma_item, idf).score, 0)

    def test_rare_needs_three_or_fewer_and_two_percent(self):
        m = load_match()
        small = m.Idf([{"figma"}, {"board"}, {"git"}])
        self.assertFalse(small.rare("figma"), "1 of 3 is 33 percent of the corpus: not rare")
        big = m.Idf([{"figma"}] + [{"widget"}] * 99)
        self.assertTrue(big.rare("figma"))
        self.assertEqual(m.Idf.from_counts({"figma": 1}, 100).rare("figma"), True)

    def test_near_duplicate(self):
        m = load_match()
        a = {"trigger": "when a bash command needs to cd into the project folder",
             "action": "Start each Bash command with cd to an absolute path"}
        b = {"trigger": "when a bash command needs to cd into a project folder first",
             "action": "Start every Bash command with cd to an absolute path"}
        other = {"trigger": "when about to call use_figma", "action": "Load the figma skill first"}
        self.assertTrue(m.near_duplicate(a, b))
        self.assertFalse(m.near_duplicate(a, other))


# ---------------------------------------------------------------- session start

class TestSessionStartRecall(RecallTest):
    def test_relevance_beats_id_among_forty_tied(self):
        for n in range(39):
            self.note(f"global/aa-{n:02d}.md", f"aa-{n:02d}", f"when sorting widget batch {n}",
                      f"FILLER-ACTION-{n:02d}")
        self.note("global/zz-kestrel.md", "zz-kestrel", "when editing the kestrel dashboard layout",
                  "KESTREL-ACTION")
        r = self.start(cwd=self.sub("dashboard"))
        self.assertAllowed(r)
        self.assertIn("KESTREL-ACTION", r.context)
        self.assertNotIn("FILLER-ACTION-00", r.context, "a global instinct with no match must not show")

    def test_default_max_is_three(self):
        rows = [("apple orchard", "prune the branches"), ("brick kiln", "stack by heat"),
                ("cloud ledger", "sync the totals"), ("delta river", "map the silt"),
                ("ember stove", "bank the coals"), ("fjord ferry", "check the tide")]
        for n, (where, act) in enumerate(rows):
            self.note(f"global/k-{n}.md", f"k-{n}", f"when the kestrel panel shows the {where}",
                      f"KESTREL-{n} {act}")
        # "kestrel" is in all six, so it is not rare: the cwd also names "panel" for a 2 stem match.
        cwd = os.path.join(self.kestrel, "panel")
        os.makedirs(cwd)
        r = self.start(cwd=cwd)
        self.assertEqual(len(self.instinct_lines(r.context)), 3, r.context)

    def test_near_duplicates_take_one_slot(self):
        self.note("global/cd-a.md", "cd-a", "when a kestrel bash command needs to cd into the folder",
                  "CD-ONE Start each Bash command with cd to an absolute path")
        self.note("global/cd-b.md", "cd-b", "when a kestrel bash command needs to cd into the folder first",
                  "CD-TWO Start each Bash command with cd to an absolute path")
        self.note("global/cd-c.md", "cd-c", "when a kestrel bash command needs a cd into the folder",
                  "CD-THREE Start every Bash command with cd to an absolute path")
        self.note("global/other.md", "other", "when the kestrel dashboard folder needs a new chart",
                  "CHART-ACTION")
        cwd = os.path.join(self.kestrel, "folder")
        os.makedirs(cwd)
        r = self.start(cwd=cwd)
        shown = sum(r.context.count(x) for x in ("CD-ONE", "CD-TWO", "CD-THREE"))
        self.assertEqual(shown, 1, r.context)
        self.assertIn("CHART-ACTION", r.context)

    def test_ties_fall_to_recency_then_evidence_never_id(self):
        self.note("global/aaa-old.md", "aaa-old", "when the kestrel import fails", "OLD-ACTION",
                  last_observed="2026-01-01", evidence_count=50)
        self.note("global/zzz-new.md", "zzz-new", "when the kestrel import fails", "NEW-ACTION",
                  last_observed="2026-11-01", evidence_count=1)
        r = self.start(cwd=self.sub("import"), NEVA_INSTINCT_MAX=1)
        self.assertIn("NEW-ACTION", r.context, "last_observed breaks the tie, not id")
        self.assertNotIn("OLD-ACTION", r.context)

    def test_ties_fall_to_evidence_when_recency_equal(self):
        self.note("global/aaa-thin.md", "aaa-thin", "when the kestrel import fails", "THIN-ACTION",
                  last_observed="2026-11-01", evidence_count=2)
        self.note("global/zzz-thick.md", "zzz-thick", "when the kestrel import fails", "THICK-ACTION",
                  last_observed="2026-11-01", evidence_count=9)
        r = self.start(cwd=self.sub("import"), NEVA_INSTINCT_MAX=1)
        self.assertIn("THICK-ACTION", r.context)

    def test_no_match_injects_no_instinct_block(self):
        pid = self.s.pid
        for n, w in enumerate(["backlog", "roadmap", "garden", "invoice", "harbor"]):
            self.note(f"project/{pid}/p-{n}.md", f"p-{n}", f"when grooming the {w}", f"PROJ-{n}",
                      last_observed="2026-11-01", evidence_count=40)
        r = self.start()
        self.assertAllowed(r)
        self.assertEqual(self.instinct_lines(r.context), [], r.context)
        self.assertNotIn("Active instincts", r.context)
        self.assertEqual(self.injections(), [])

    def test_home_cwd_never_queries_the_username(self):
        home = os.path.join(self.s.tmp, "Users", "zorba-dine")
        os.makedirs(home)
        self.note("global/zorba.md", "zorba", "when zorba dine edits a file", "USERNAME-ACTION")
        r = self.s.dispatch("SessionStart", self.base(source="startup", cwd=home, session_id="s-home"),
                            HOME=home, USER="zorba-dine", LOGNAME="zorba-dine")
        self.assertAllowed(r)
        self.assertNotIn("USERNAME-ACTION", r.context)
        self.assertEqual(self.injections(), [])

    def test_injection_log_gets_one_line(self):
        self.note("global/zz-kestrel.md", "zz-kestrel", "when editing the kestrel dashboard layout",
                  "KESTREL-ACTION")
        self.start(cwd=self.sub("dashboard"))
        lines = self.injections()
        self.assertEqual(len(lines), 1, lines)
        rec = lines[0]
        self.assertEqual(rec["source"], "session_start")
        self.assertEqual(rec["ids"], ["zz-kestrel"])
        self.assertEqual(len(rec["scores"]), 1)
        self.assertEqual(rec["session"], "s-start-1")

    def test_char_cap_and_line_budget_hold(self):
        words = ["apple", "brick", "cloud", "delta", "ember", "fjord", "grove", "harbor"]
        for n, w in enumerate(words):
            self.note(f"global/long-{n}.md", f"long-{n}", f"when the kestrel {w} report is long",
                      f"LONG-{n} {w} " + f"{w}word " * 400)
        self.s.write(f"vault/08 Journal/{today_utc()}.md", "---\ndate: x\n---\n\n## Today\n" + "- line\n" * 60)
        r = self.start(cwd=self.sub("report"))
        self.assertLessEqual(len(r.context), 8000)
        lines = self.instinct_lines(r.context)
        self.assertLessEqual(len(lines), 3)
        for ln in lines:
            self.assertLessEqual(len(ln), 220, ln)


# ---------------------------------------------------------------- corpus rarity and cache

class TestCorpusRarity(RecallTest):
    def seed(self):
        # 300 instincts corpus-wide; "test" is in 40 of them, but only one is a candidate here.
        self.corpus(260)
        self.corpus(39, pid="otherproject2", trigger="when the test {n} suite is slow")
        self.note("global/flaky.md", "flaky", "when the test harness flakes", "TEST-ACTION")
        self.note("global/zep.md", "zep", "when a zeppelin config loads", "ZEPPELIN-ACTION")
        self.note("project/otherproject3/zep2.md", "zep2", "when the zeppelin cache warms", "OTHER-ZEP")

    def test_common_stem_corpus_wide_is_not_rare(self):
        self.seed()
        r = self.prompt("run the test again", cwd=self.s.tmp, sid="c-1")
        self.assertAllowed(r)
        self.assertNotIn("TEST-ACTION", r.context, "test is in 40 of 300 instincts corpus-wide")

    def test_stem_in_two_instincts_is_rare(self):
        self.seed()
        r = self.prompt("zeppelin please", cwd=self.s.tmp, sid="c-2")
        self.assertIn("ZEPPELIN-ACTION", r.context)
        self.assertNotIn("OTHER-ZEP", r.context, "another project's instinct is corpus, not a candidate")

    def test_cache_is_used_then_rebuilt_when_a_note_changes(self):
        self.seed()
        self.prompt("zeppelin please", cwd=self.s.tmp, sid="c-3")
        self.assertTrue(os.path.exists(self.df_cache()))
        with open(self.df_cache(), encoding="utf-8") as fh:
            cache = json.load(fh)
        cache["df"]["zeppelin"] = 250  # same key: a hook that reads the cache now sees zeppelin as common
        with open(self.df_cache(), "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        r = self.prompt("zeppelin please", cwd=self.s.tmp, sid="c-4")
        self.assertNotIn("ZEPPELIN-ACTION", r.context, "the second call must read the cache")
        note = os.path.join(self.s.vault, "06 Memory", "instincts", "global", "zep.md")
        future = os.path.getmtime(note) + 60
        os.utime(note, (future, future))
        r = self.prompt("zeppelin please", cwd=self.s.tmp, sid="c-5")
        self.assertIn("ZEPPELIN-ACTION", r.context, "a changed note rebuilds the cache")

    def test_corrupt_cache_is_rebuilt(self):
        self.seed()
        os.makedirs(os.path.dirname(self.df_cache()), exist_ok=True)
        with open(self.df_cache(), "w") as fh:
            fh.write("{not json")
        r = self.prompt("zeppelin please", cwd=self.s.tmp, sid="c-6")
        self.assertAllowed(r)
        self.assertIn("ZEPPELIN-ACTION", r.context)
        with open(self.df_cache(), encoding="utf-8") as fh:
            self.assertIn("zeppelin", json.load(fh)["df"])


# ---------------------------------------------------------------- first prompt

class TestPromptRecall(RecallTest):
    def seed_figma(self):
        self.note("global/figma-load.md", "figma-load", "when about to call use_figma on a figma board",
                  "FIGMA-ACTION Load the figma skill first", tags="[instinct, figma]")
        self.note("global/git-rebase.md", "git-rebase", "when rebasing a git branch onto main",
                  "GIT-ACTION Rebase only a branch nobody else pulled")

    def test_figma_prompt_pulls_figma_not_git(self):
        self.seed_figma()
        r = self.prompt("update the figma board frames for the hero", cwd=self.s.tmp)
        self.assertAllowed(r)
        self.assertIn(PROMPT_HEAD, r.context)
        self.assertIn("FIGMA-ACTION", r.context)
        self.assertNotIn("GIT-ACTION", r.context)

    def test_no_match_injects_nothing(self):
        self.seed_figma()
        r = self.prompt("xylophone quartz meadow", cwd=self.s.tmp)
        self.assertAllowed(r)
        self.assertNotIn(PROMPT_HEAD, r.context)
        self.assertEqual([x for x in self.injections() if x["source"] == "prompt"], [])

    def test_second_prompt_injects_nothing(self):
        self.seed_figma()
        r1 = self.prompt("update the figma board", cwd=self.s.tmp, sid="s-two")
        self.assertIn("FIGMA-ACTION", r1.context)
        r2 = self.prompt("now the figma board again", cwd=self.s.tmp, sid="s-two")
        self.assertNotIn(PROMPT_HEAD, r2.context)

    def test_slash_and_system_prompts_do_not_use_the_turn(self):
        self.seed_figma()
        for p in ("/figma board", "<system-reminder>figma board</system-reminder>"):
            r = self.prompt(p, cwd=self.s.tmp, sid="s-three")
            self.assertNotIn(PROMPT_HEAD, r.context)
        r = self.prompt("fix the figma board", cwd=self.s.tmp, sid="s-three")
        self.assertIn("FIGMA-ACTION", r.context)

    def test_shown_at_start_does_not_repeat_on_prompt(self):
        self.note("global/kestrel-figma.md", "kestrel-figma", "when the kestrel figma board changes",
                  "START-FIGMA-ACTION")
        self.note("global/figma-load.md", "figma-load", "when about to call use_figma on a figma board",
                  "PROMPT-FIGMA-ACTION")
        r = self.start(cwd=self.sub("figma"), sid="s-four")
        self.assertIn("START-FIGMA-ACTION", r.context)
        r2 = self.prompt("update the figma board", sid="s-four")
        self.assertIn("PROMPT-FIGMA-ACTION", r2.context)
        self.assertNotIn("START-FIGMA-ACTION", r2.context)
        logged = [x for x in self.injections() if x["source"] == "prompt"]
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["ids"], ["figma-load"])

    def test_prompt_max_env(self):
        rows = [("apple orchard", "prune the branches"), ("brick kiln", "stack by heat"),
                ("cloud ledger", "sync the totals"), ("delta river", "map the silt"),
                ("ember stove", "bank the coals")]
        for n, (where, act) in enumerate(rows):
            self.note(f"global/f-{n}.md", f"f-{n}", f"when a figma frame shows the {where}",
                      f"FIGMA-{n} {act}")
        r = self.prompt("figma frame", cwd=self.s.tmp, sid="s-five")
        self.assertEqual(len(self.instinct_lines(r.context)), 3, r.context)
        r = self.prompt("figma frame", cwd=self.s.tmp, sid="s-six", NEVA_INSTINCT_PROMPT_MAX=1)
        self.assertEqual(len(self.instinct_lines(r.context)), 1, r.context)

    def test_broken_matcher_never_blocks_the_prompt(self):
        self.seed_figma()
        os.remove(os.path.join(self.s.plugin, "skills", "continuous-learning-v2", "scripts", "instinct_match.py"))
        r = self.prompt("update the figma board", cwd=self.s.tmp, sid="s-seven")
        self.assertAllowed(r)
        self.assertNotIn(PROMPT_HEAD, r.context)
        log = self.s.read(os.path.join(self.s.data, "hooks.log"))
        self.assertIn("[instinct_prompt]", log)

    def test_broken_vault_never_blocks_the_prompt(self):
        root = os.path.join(self.s.vault, "06 Memory", "instincts")
        os.makedirs(os.path.dirname(root), exist_ok=True)
        with open(root, "w") as fh:
            fh.write("not a folder")
        r = self.prompt("update the figma board", cwd=self.s.tmp, sid="s-eight")
        self.assertAllowed(r)
        self.assertNotIn(PROMPT_HEAD, r.context)


if __name__ == "__main__":
    unittest.main()
