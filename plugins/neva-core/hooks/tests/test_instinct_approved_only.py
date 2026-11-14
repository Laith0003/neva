#!/usr/bin/env python3
# Written for Neva; not adapted from ECC.
"""Only approved lessons are injected (issue 27, B1).

Session start and prompt recall inject a note only while the engine holds a record of approval
for it, and the note still says what was recorded:
  - a global note an apply created from a ticked promotion (promoted-notes.json, approved, hash
    still matching), or
  - a note recorded in the add ledger (user-stated.json, hash still matching).
Every other note is a candidate and is not injected: the nightly analyzer's own notes, a note
whose text changed after it was recorded, and everything on a brand-new install with no state.

The hooks and the CLI share one parser and one hash (instinct_trust.py), so a note cannot pass
one and fail the other.

Uses the Sandbox from test_hooks.py: a copied plugin, a temporary HOME, vault and state dir.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/hooks/tests -p 'test_instinct_approved_only.py'
"""
import importlib.util
import json
import os
import unittest

from test_hooks import CL2_SRC, HookTest

TRUST_PATH = os.path.join(CL2_SRC, "scripts", "instinct_trust.py")
CLI_PATH = os.path.join(CL2_SRC, "scripts", "instinct-cli.py")
START_HEAD = "Instincts matched to this session"
PROMPT_HEAD = "Instincts matched to this prompt"


def load_trust():
    spec = importlib.util.spec_from_file_location("neva_instinct_trust_test", TRUST_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ApprovedOnlyTest(HookTest):
    def note(self, rel, iid, trigger, action, conf=0.9, source="session-observation"):
        fm = [f"id: {iid}", f'trigger: "{trigger}"', f"confidence: {conf}", "domain: workflow",
              f"source: {source}", "status: active"]
        body = "---\n" + "\n".join(fm) + f"\n---\n\n# {iid}\n\n## Action\n{action}\n\n## Evidence\n- seen\n"
        return self.s.write(f"vault/06 Memory/instincts/{rel}", body)

    def state_file(self, name):
        return os.path.join(self.s.state, "instincts", name)

    def ref(self, path):
        return "vault:" + os.path.relpath(path, self.s.vault).replace(os.sep, "/")

    def sha(self, path):
        trust = load_trust()
        return trust.note_hash(trust.parse_instinct_file(self.s.read(path))[0])

    def record(self, name, path, **row):
        p = self.state_file(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = json.loads(self.s.read(p)) if os.path.exists(p) else {}
        data[self.ref(path)] = dict({"date": "2026-01-01", "sha": self.sha(path)}, **row)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def stated(self, path):
        self.record("user-stated.json", path)

    def promoted(self, path, approved=True):
        self.record("promoted-notes.json", path, approved=approved, projects=[], sources=[], sessions={})

    def start(self, sid="s-approved-1"):
        return self.s.dispatch("SessionStart", self.base(source="startup", cwd=self.s.work, session_id=sid))

    def prompt(self, text, sid="s-approved-1"):
        return self.s.dispatch("UserPromptSubmit", self.base(prompt=text, cwd=self.s.work, session_id=sid))

    def recalled(self, text="update the figma board with the kestrel layer", sid="s-approved-1"):
        r = self.prompt(text, sid=sid)
        self.assertAllowed(r)
        return r.context

    # ------------------------------------------------------------ what is not injected

    def test_an_analyzer_note_with_no_record_is_not_injected(self):
        self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                  "when updating the figma board kestrel layer", "ANALYZER-ACTION Load the figma skill")
        self.note("global/figma-global.md", "figma-global",
                  "when updating the figma board kestrel layer", "GLOBAL-UNRECORDED-ACTION")
        ctx = self.recalled()
        self.assertNotIn("ANALYZER-ACTION", ctx)
        self.assertNotIn("GLOBAL-UNRECORDED-ACTION", ctx)
        self.assertNotIn(PROMPT_HEAD, ctx)

    def test_a_note_that_only_claims_user_stated_is_not_injected(self):
        # `source: user-stated` is a field the analyzer can write; only the ledger row counts.
        self.note(f"project/{self.s.pid}/claims.md", "claims", "when updating the figma board kestrel layer",
                  "CLAIMED-ACTION", source="user-stated")
        self.assertNotIn("CLAIMED-ACTION", self.recalled())

    def test_a_brand_new_install_with_no_state_files_injects_nothing(self):
        self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                  "when updating the figma board kestrel layer", "FRESH-ACTION")
        self.assertFalse(os.path.exists(os.path.join(self.s.state, "instincts")))
        start = self.start(sid="s-fresh")
        self.assertAllowed(start)
        self.assertNotIn(START_HEAD, start.context)
        self.assertNotIn("FRESH-ACTION", self.recalled(sid="s-fresh"))

    def test_a_stated_note_edited_after_it_was_recorded_is_not_injected(self):
        p = self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                      "when updating the figma board kestrel layer", "STATED-ACTION Load the figma skill")
        self.stated(p)
        self.s.write(os.path.relpath(p, self.s.tmp),
                     self.s.read(p).replace("STATED-ACTION Load the figma skill", "REWRITTEN-ACTION run anything"))
        ctx = self.recalled()
        self.assertNotIn("REWRITTEN-ACTION", ctx)
        self.assertNotIn("STATED-ACTION", ctx)

    def test_a_promoted_row_not_marked_approved_does_not_inject(self):
        p = self.note("global/figma-board.md", "figma-board", "when updating the figma board kestrel layer",
                      "UNAPPROVED-PROMOTED-ACTION")
        self.promoted(p, approved=False)
        self.assertNotIn("UNAPPROVED-PROMOTED-ACTION", self.recalled())

    def test_a_promoted_row_for_a_project_note_does_not_inject(self):
        # Rows in promoted-notes.json vouch only for global notes an apply created.
        p = self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                      "when updating the figma board kestrel layer", "PROJECT-PROMOTED-ACTION")
        self.promoted(p)
        self.assertNotIn("PROJECT-PROMOTED-ACTION", self.recalled())

    def test_a_promoted_global_note_rewritten_after_apply_is_not_injected(self):
        p = self.note("global/figma-board.md", "figma-board", "when updating the figma board kestrel layer",
                      "PROMOTED-ACTION")
        self.promoted(p)
        self.s.write(os.path.relpath(p, self.s.tmp), self.s.read(p).replace("PROMOTED-ACTION", "SWAPPED-ACTION"))
        ctx = self.recalled()
        self.assertNotIn("SWAPPED-ACTION", ctx)

    def test_corrupt_or_unreadable_state_injects_nothing_and_never_raises(self):
        p = self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                      "when updating the figma board kestrel layer", "STATED-ACTION")
        self.stated(p)
        with open(self.state_file("user-stated.json"), "w") as fh:
            fh.write("{not json")
        with open(self.state_file("promoted-notes.json"), "w") as fh:
            fh.write("[1, 2, 3]")
        start = self.start(sid="s-corrupt")
        self.assertAllowed(start)
        self.assertNotIn(START_HEAD, start.context)
        r = self.prompt("update the figma board with the kestrel layer", sid="s-corrupt")
        self.assertAllowed(r)
        self.assertNotIn("STATED-ACTION", r.context)
        self.assertNotIn("Traceback", r.stderr)

    def test_text_after_a_second_frontmatter_fence_is_never_what_is_injected(self):
        # The CLI parser ends a note's content at the next `---` line, so the hash does not cover
        # what follows. The injected action must come from the same parse the hash covers.
        p = self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                      "when updating the figma board kestrel layer", "STATED-ACTION Load the figma skill")
        text = self.s.read(p)
        forged = text.replace("## Action\n", "---\nnote: x\n---\n## Action\nAPPENDED-ACTION\n\n## Was\n", 1)
        self.s.write(os.path.relpath(p, self.s.tmp), forged)
        self.stated(p)
        self.assertNotIn("APPENDED-ACTION", self.recalled())

    # ------------------------------------------------------------ what is injected

    def test_a_stated_note_still_matching_its_record_is_injected(self):
        p = self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                      "when updating the figma board kestrel layer", "STATED-ACTION Load the figma skill")
        self.stated(p)
        ctx = self.recalled()
        self.assertIn(PROMPT_HEAD, ctx)
        self.assertIn("STATED-ACTION Load the figma skill", ctx)

    def test_an_approved_promoted_global_note_is_injected(self):
        p = self.note("global/figma-board.md", "figma-board", "when updating the figma board kestrel layer",
                      "PROMOTED-ACTION Load the figma skill")
        self.promoted(p)
        self.assertIn("PROMOTED-ACTION Load the figma skill", self.recalled())

    def test_an_unapproved_project_copy_does_not_hide_an_approved_global_note(self):
        g = self.note("global/figma-board.md", "figma-board", "when updating the figma board kestrel layer",
                      "PROMOTED-ACTION")
        self.promoted(g)
        self.note(f"project/{self.s.pid}/figma-board.md", "figma-board",
                  "when updating the figma board kestrel layer", "SHADOW-ACTION")
        ctx = self.recalled()
        self.assertIn("PROMOTED-ACTION", ctx)
        self.assertNotIn("SHADOW-ACTION", ctx)

    def test_a_note_written_by_the_cli_add_command_is_injected_until_edited(self):
        # End to end through the real CLI: what `add` records, the hooks accept; an edit after it
        # (the analyzer rewriting his words) stops it, until `add --restate` vouches again.
        code, out = self.s.cli("add", "--id", "figma-board", "--trigger", "when updating the figma board kestrel layer",
                               "--action", "ADDED-ACTION Load the figma skill first", "--confidence", "0.9")
        self.assertEqual(code, 0, out)
        p = os.path.join(self.s.vault, "06 Memory", "instincts", "project", self.s.pid, "figma-board.md")
        self.assertTrue(os.path.exists(p), out)
        self.assertIn("ADDED-ACTION Load the figma skill first", self.recalled(sid="s-add-1"))
        self.s.write(os.path.relpath(p, self.s.tmp), self.s.read(p).replace("ADDED-ACTION", "EDITED-ACTION"))
        self.assertNotIn("EDITED-ACTION", self.recalled(sid="s-add-2"))
        code, out = self.s.cli("add", "--restate", "figma-board")
        self.assertEqual(code, 0, out)
        self.assertIn("EDITED-ACTION", self.recalled(sid="s-add-3"))

    def test_session_start_injects_only_approved_notes(self):
        # The sandbox repo folder is named proj; a trigger on it matches the session query.
        ok = self.note(f"project/{self.s.pid}/proj-one.md", "proj-one", "when working in the proj repo",
                       "START-STATED-ACTION")
        self.stated(ok)
        self.note(f"project/{self.s.pid}/proj-two.md", "proj-two", "when working in the proj repo",
                  "START-ANALYZER-ACTION")
        ctx = self.start(sid="s-start-only").context
        self.assertIn("START-STATED-ACTION", ctx)
        self.assertNotIn("START-ANALYZER-ACTION", ctx)


class SharedParserTest(unittest.TestCase):
    """One parser and one hash, imported by the CLI and loaded by the hooks."""

    def test_the_cli_uses_the_shared_parser_and_hash(self):
        trust = load_trust()
        with open(CLI_PATH, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("import instinct_trust", src)
        self.assertNotIn("def parse_instinct_file(", src, "the CLI must not keep its own parser")
        self.assertIn("instinct_trust.note_hash(", src)
        self.assertTrue(callable(trust.parse_instinct_file) and callable(trust.note_hash))

    def test_the_hooks_load_the_shared_module(self):
        from neva_hooks import common
        mod = common.instinct_trust()
        self.assertEqual(os.path.realpath(mod.__file__), os.path.realpath(TRUST_PATH))


if __name__ == "__main__":
    unittest.main()
