"""Front matter is read strictly and fails closed. Deny runs before any shape check, and no error names a denied thing."""
import json
import os
import sqlite3

from .world import PROPOSAL, World


def body(front):
    return f"---\n{front}\n---\n\n# Quiet\n\ndeliver by 2026-03-24\n"


DENIED_FRONTS = {
    "inline": "tags: [client, confidential]",
    "double_quoted": 'tags: [client, "confidential"]',
    "single_quoted": "tags: ['confidential']",
    "hash": "tags: [#confidential]",
    "quoted_hash": 'tags: ["#confidential"]',
    "case": "tags: [CONFIDENTIAL]",
    "scalar": "tags: confidential",
    "comma_scalar": "tags: client, confidential",
    "space_scalar": "tags: client confidential",
    "alias": "tag: confidential",
    "capital_key": "Tags: [confidential]",
    "quoted_key": '"tags": [confidential]',
    "block": "tags:\n  - client\n  - confidential",
    "block_flush": "tags:\n- confidential",
    "block_quoted": 'tags:\n  - "confidential"',
    "block_hash": "tags:\n  - '#confidential'",
    "nested_child": "tags: [client/confidential]",
    "nested_parent": "tags: [confidential/client]",
    "nested_block": "tags:\n  - a/confidential/b",
    "flag": "confidential: true",
}

UNPARSEABLE_FRONTS = {
    "unterminated": "tags: [client, confidential",
    "multi_line_flow": "tags: [client,\n  other]",
    "nested_list": "tags: [[client]]",
    "map": "tags: {a: b}",
    "block_scalar": "tags: |\n  client",
    "folded_scalar": "tags: >\n  client",
    "anchor": "tags: &x client",
    "alias_ref": "tags: *x",
    "open_quote": "tags: [\"client]",
    "block_map": "tags:\n  - {a: b}",
    "plain_multiline": "tags:\n  client",
    "bad_flag": "confidential: maybe",
}

ALLOWED_FRONTS = {
    "inline": "tags: [client, lead]",
    "empty": "tags:",
    "empty_list": "tags: []",
    "null": "tags: null",
    "block": "tags:\n  - client\n  - lead",
    "flag_off": "confidential: false",
    "near_word": "tags: [nonconfidential, confidentiality]",
    "no_tags": "status: active",
}


class Tags(World):
    def assert_denied(self, text, label):
        self.write("projects/Quiet.md", text)
        today = self.today()
        self.assertNotIn("Quiet", json.dumps(today), label)
        self.assertEqual({s["id"]: s for s in today["sources"]}["dates"]["denied"], 1, label)

    def test_every_written_form_of_a_tag_is_denied(self):
        for label, front in DENIED_FRONTS.items():
            self.assert_denied(body(front), label)

    def test_a_tags_key_that_cannot_be_parsed_is_denied(self):
        for label, front in UNPARSEABLE_FRONTS.items():
            self.assert_denied(body(front), label)

    def test_front_matter_with_no_closing_line_is_denied(self):
        self.assert_denied("---\ntags: [client]\n\n# Quiet\n\ndeliver by 2026-03-24\n", "unclosed")

    def test_front_matter_after_a_blank_line_is_denied(self):
        self.assert_denied("\n---\ntags: [client]\n---\n\n# Quiet\n\ndeliver by 2026-03-24\n", "offset")

    def test_crlf_is_read_the_same(self):
        self.assert_denied(body("tags:\n  - confidential").replace("\n", "\r\n"), "crlf")

    def test_a_bom_is_read_the_same(self):
        self.assert_denied("﻿" + body("tags: [confidential]"), "bom")

    def test_ordinary_front_matter_stays_readable(self):
        for label, front in ALLOWED_FRONTS.items():
            self.write("projects/Quiet.md", body(front))
            self.assertIn("Quiet due 24 Mar", json.dumps(self.today()), label)

    def test_a_note_with_no_front_matter_stays_readable(self):
        self.write("projects/Quiet.md", "# Quiet\n\ndeliver by 2026-03-24\n")
        self.assertIn("Quiet due 24 Mar", json.dumps(self.today()))

    def test_a_crlf_note_keeps_its_figures(self):
        self.write("projects/Quiet.md", "# Quiet\r\n\r\ndeliver by 2026-03-24\r\n")
        today = self.today()
        self.assertIn("Quiet due 24 Mar", json.dumps(today))
        self.assertEqual(today["dropped"]["number"], 0)


class Order(World):
    def source(self, today, name):
        return {s["id"]: s for s in today["sources"]}[name]

    def test_a_denied_lead_with_a_bad_shape_is_skipped_not_failed(self):
        self.write("leads/Zephyrcorp.md", "# no front matter at all\n")
        today = self.today()
        row = self.source(today, "leads")
        self.assertEqual((row["state"], row["denied"]), ("ok", 1))
        self.assertNotIn("Zephyrcorp", json.dumps(today))

    def test_a_tagged_lead_with_no_status_is_skipped_not_failed(self):
        self.write("leads/Quiet.md", "---\ntags: [confidential]\n---\n\n# Quiet\n")
        today = self.today()
        self.assertEqual(self.source(today, "leads")["state"], "ok")
        self.assertNotIn("Quiet", json.dumps(today))

    def test_a_denied_job_with_a_bad_shape_is_skipped_not_failed(self):
        self.write_json(self.queue + "/zephyrcorp-build.json", {"reason": "x"})
        today = self.today()
        row = self.source(today, "queue")
        self.assertEqual((row["state"], row["denied"]), ("ok", 1))
        self.assertNotIn("zephyrcorp", json.dumps(today).lower())

    def test_a_note_in_a_denied_folder_is_denied_by_its_folder_name(self):
        self.write("projects/ZPH/plan.md", "# Plan\n\ndeliver by 2026-03-24\n")
        self.config["sources"]["dates"]["globs"].append("projects/*/plan.md")
        self.save()
        today = self.today()
        self.assertNotIn("Plan due", json.dumps(today))
        self.assertEqual(self.source(today, "dates")["denied"], 1)


class Errors(World):
    def row(self, name):
        code = self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        return code, {s["id"]: s for s in today["sources"]}[name], today

    def test_a_denied_ledger_fails_with_a_generic_error(self):
        self.edit("money/Ledger.md", "tags: [money]", "tags: [confidential]")
        code, row, today = self.row("ledger")
        self.assertEqual((code, row["state"]), (1, "failed"))
        self.assertEqual(row["error"], "a denied file")
        self.assertNotIn("Ledger.md", json.dumps(today))

    def test_a_denied_path_in_config_fails_with_a_generic_error(self):
        self.write("clients/Zephyr Ledger.md", "# x\n")
        self.config["sources"]["ledger"]["path"] = "clients/Zephyr Ledger.md"
        self.save()
        code, row, today = self.row("ledger")
        self.assertEqual(row["error"], "a denied file")
        self.assertNotIn("Zephyr", json.dumps(today))

    def test_a_term_in_error_text_is_replaced_before_it_is_stored(self):
        self.edit("money/Events.md", "amount: 1000, date: 2026-01-10,", "amount: 1000, date: Zephyrcorp,")
        code, row, today = self.row("ledger_events")
        self.assertEqual(code, 1, "the run is not refused whole for a scrubbed error")
        self.assertEqual(row["error"], "a denied file")
        self.assertNotIn("Zephyrcorp", json.dumps(today))
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        self.assertNotIn("Zephyrcorp", json.dumps(db.execute("SELECT error FROM source_runs").fetchall()))

    def test_a_clean_error_keeps_its_field_and_fix(self):
        self.write("leads/Bad.md", "# Bad\n")
        code, row, _ = self.row("leads")
        self.assertIn("Bad", row["error"])
        self.assertIn("status", row["error"])

    def test_a_denied_note_never_lands_in_source_runs(self):
        self.write("projects/A Quiet.md", body("tags: [confidential]"))
        self.config["sources"]["dates"]["globs"] = ["projects/*.md"]
        self.save()
        self.tick()
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        self.assertNotIn("A Quiet", json.dumps(db.execute("SELECT path FROM source_runs").fetchall()))


class GoalsAndProposals(World):
    def goals_row(self, today):
        return {s["id"]: s for s in today["sources"]}["goals"]

    def test_a_tagged_proposal_is_skipped_and_counted(self):
        self.write("reviews/Move proposal 2026-03-19.md", PROPOSAL.replace("status: done", "tags: [confidential]").replace("Collect Northwind and Tailspin", "Secret plan"))
        today = self.today()
        self.assertEqual(today["move"]["title"], "Collect Northwind and Tailspin")
        self.assertEqual(self.goals_row(today)["denied"], 1)
        self.assertNotIn("Secret plan", json.dumps(today))

    def test_a_denied_proposal_with_no_pick_does_not_fail_the_source(self):
        self.write("reviews/Move proposal 2026-03-19.md", "---\ntags: [confidential]\n---\n\nNo table.\n")
        self.assertEqual(self.goals_row(self.today())["state"], "ok")

    def test_a_denied_proposal_cannot_mark_a_failed_week(self):
        self.write("reviews/Move proposal 2026-03-19.md", "---\ntags: [confidential]\n---\n\nModel call unavailable.\n")
        self.assertEqual(self.today()["move"]["state"], "proposed")

    def test_a_proposal_named_with_a_term_is_skipped(self):
        self.write("reviews/Move proposal Zephyrcorp 2026-03-19.md", PROPOSAL.replace("Collect Northwind and Tailspin", "Secret plan"))
        today = self.today()
        self.assertNotIn("Secret plan", json.dumps(today))
        self.assertEqual(self.goals_row(today)["denied"], 1)

    def test_a_tagged_goals_file_fails_with_a_generic_error(self):
        self.write("GOALS.md", "---\ntags: [confidential]\n---\n\n## Current Move\n\n- Move: Secret\n")
        self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        self.assertEqual(self.goals_row(today)["error"], "a denied file")
        self.assertNotIn("Secret", json.dumps(today))
        self.assertEqual(today["move"]["state"], "unknown")

    def test_a_tagged_failure_file_is_not_read(self):
        self.write("inbox.md", "---\ntags: [confidential]\n---\n\nweek failed 2026-03-20\n")
        self.config["sources"]["goals"].update(failure_file="inbox.md", failure_pattern=r"week failed (\d{4}-\d\d-\d\d)")
        self.save()
        self.assertEqual(self.today()["move"]["state"], "proposed")


class ScheduleSource(World):
    def test_a_quote_in_a_denied_file_makes_due_unknown(self):
        self.edit("money/Events.md", "# Events\n", "# Events\n")
        self.write("money/Events.md", "---\ntags: [confidential]\n---\n" + open(os.path.join(self.root, "money/Events.md"), encoding="utf-8").read())
        today = self.today()
        self.assertIsNone(today["money"]["due"])
        self.assertEqual({s["id"]: s for s in today["sources"]}["ledger_events"]["error"], "a denied file")
