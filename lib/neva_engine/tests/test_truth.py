"""Owed against due, unknown against zero, loud failure, the number gate, the deny gate."""
import json
import os
import sqlite3
import stat

from .world import NOW, World


class OwedAndDue(World):
    def test_owed_and_due_are_separate(self):
        money = self.today()["money"]
        self.assertEqual((money["owed"], money["due"], money["currency"]), (3400, 1900, "USD"))
        self.assertEqual(money["state"], "ok")

    def test_each_row_says_what_is_due(self):
        rows = {r["project"]: r for r in self.today()["money"]["rows"]}
        self.assertEqual((rows["Northwind"]["owed"], rows["Northwind"]["due"]), (3000, 1500))
        self.assertEqual((rows["Tailspin"]["owed"], rows["Tailspin"]["due"]), (400, 400))

    def test_a_new_payment_makes_due_unknown_never_stale(self):
        self.edit("money/Ledger.md", "received: 2000, remaining: 3000", "received: 2500, remaining: 2500")
        self.edit("money/Ledger.md", "received: 2600, remaining: 3400", "received: 3100, remaining: 2900")
        self.age("money/Ledger.md", "2026-03-20")
        money = self.today()["money"]
        self.assertEqual(money["owed"], 2900)
        self.assertIsNone(money["due"])
        self.assertIn("Northwind", money["due_note"])

    def test_a_quote_gone_from_its_file_makes_due_unknown(self):
        self.edit("money/Events.md", "500 is still owed on payment 2", "nothing here")
        self.assertIsNone(self.today()["money"]["due"])

    def test_no_schedule_means_due_unknown_not_zero(self):
        del self.config["sources"]["ledger_events"]["schedule"]
        self.save()
        money = self.today()["money"]
        self.assertEqual(money["owed"], 3400)
        self.assertIsNone(money["due"])


class Unknown(World):
    def test_an_absent_ledger_is_unknown_not_zero(self):
        self.remove("money/Ledger.md")
        today = self.today()
        self.assertEqual(today["money"]["state"], "unknown")
        self.assertIsNone(today["money"]["owed"])
        self.assertEqual({s["id"]: s["state"] for s in today["sources"]}["ledger"], "absent")
        self.assertEqual(today["run"]["state"], "degraded")

    def test_rules_on_an_absent_source_are_held(self):
        self.remove("money/Ledger.md")
        self.assertNotIn("money_open", self.rules())

    def test_an_empty_leads_folder_is_proven_empty(self):
        for name in ("Blue Yonder", "Fresh Co", "Done Co"):
            self.remove(f"leads/{name}.md")
        self.assertEqual({s["id"]: s["state"] for s in self.today()["sources"]}["leads"], "proven_empty")

    def test_every_read_logs_a_source_run(self):
        self.tick()
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        rows = dict(db.execute("SELECT source, status FROM source_runs"))
        self.assertEqual(set(rows), {"goals", "ledger", "ledger_events", "queue", "leads", "dates"})
        self.assertEqual(set(rows.values()), {"ok"})

    def test_a_quiet_world_is_silent_and_says_it_looked(self):
        for rel in ("leads/Blue Yonder.md", "projects/Skylark.md", "clients/Contoso.md"):
            self.remove(rel)
        self.edit("money/Ledger.md", "Northwind: { contract: 5000, received: 2000, remaining: 3000", "Northwind: { contract: 5000, received: 5000, remaining: 0")
        self.edit("money/Ledger.md", "Tailspin:  { contract: 900,  received: 500,  remaining: 400", "Tailspin:  { contract: 900,  received: 900,  remaining: 0")
        self.edit("money/Ledger.md", "received: 2600, remaining: 3400", "received: 6000, remaining: 0")
        self.age("money/Ledger.md", "2026-03-20")
        for name in ("build-one", "build-two"):
            self.write_job(name, reviewed=True)
        today = self.today()
        self.assertEqual((today["needs_you"], today["opportunities"]), ([], []))
        self.assertEqual(today["run"]["state"], "ok")
        self.assertEqual(today["money"]["owed"], 0)
        self.assertEqual(today["money"]["state"], "ok")


class LoudShape(World):
    def assert_failed(self, source, *words):
        code = self.tick()
        self.assertEqual(code, 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        row = {s["id"]: s for s in today["sources"]}[source]
        self.assertEqual(row["state"], "failed")
        for w in words:
            self.assertIn(w, row["error"])
        self.assertEqual(today["run"]["state"], "degraded")
        return today

    def test_a_ledger_with_no_yaml_block_fails(self):
        self.write("money/Ledger.md", "# Ledger\n\nNo block here.\n")
        self.assert_failed("ledger", "money/Ledger.md", "yaml")

    def test_a_ledger_row_without_remaining_names_the_field(self):
        self.edit("money/Ledger.md", "received: 500,  remaining: 400,", "received: 500,")
        self.assert_failed("ledger", "Tailspin", "remaining")

    def test_a_ledger_with_no_totals_fails(self):
        self.edit("money/Ledger.md", "totals:      {", "sums:      {")
        self.assert_failed("ledger", "totals")

    def test_goals_with_no_move_section_fails(self):
        self.write("GOALS.md", "# Goals\n\nNothing.\n")
        self.assert_failed("goals", "Current Move")

    def test_a_payment_with_no_date_fails(self):
        self.edit("money/Events.md", "amount: 1000, date: 2026-01-10,", "amount: 1000,")
        self.assert_failed("ledger_events", "date")

    def test_a_queue_file_with_no_status_fails(self):
        self.write_json(self.queue + "/broken.json", {"reason": "x"})
        self.assert_failed("queue", "broken", "status")

    def test_a_lead_with_no_front_matter_fails(self):
        self.write("leads/Bad.md", "# Bad\n")
        self.assert_failed("leads", "Bad", "front matter")

    def test_a_failed_source_holds_its_rules_and_the_rest_still_run(self):
        self.write("money/Ledger.md", "# Ledger\n")
        today = self.assert_failed("ledger")
        self.assertNotIn("money_open", self.rules(today))
        self.assertIn("deadline_near", self.rules(today))

    def test_a_failure_tops_needs_you_with_the_fix(self):
        self.write("money/Ledger.md", "# Ledger\n")
        self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            first = json.load(f)["needs_you"][0]
        self.assertEqual(first["kind"], "failure")
        self.assertIn("money/Ledger.md", first["why"])


class NumberGate(World):
    def plant(self):
        from neva_engine import rules
        real = rules.lead_cold

        def planted(facts, cfg, today):
            cards = real(facts, cfg, today)
            cards[0].title += ", worth 9,999 USD"
            return cards
        rules.lead_cold = planted
        self.addCleanup(setattr, rules, "lead_cold", real)

    def test_a_figure_with_no_source_line_drops_the_card(self):
        self.plant()
        today = self.today()
        self.assertNotIn("9,999", json.dumps(today))
        self.assertEqual(today["dropped"]["number"], 1)

    def test_with_no_plant_nothing_is_dropped(self):
        self.assertEqual(self.today()["dropped"], {"number": 0, "denied": 0})

    def test_removing_a_ledger_line_removes_its_number(self):
        self.edit("money/Ledger.md", "  Tailspin:  { contract: 900,  received: 500,  remaining: 400,  dev_owed: 0 }\n", "")
        self.edit("money/Ledger.md", "received: 2600, remaining: 3400", "received: 2100, remaining: 3000")
        self.age("money/Ledger.md", "2026-03-20")
        self.assertNotIn("Tailspin owes", json.dumps(self.today()))

    def test_a_changed_amount_follows_exactly(self):
        self.edit("money/Ledger.md", "received: 500,  remaining: 400", "received: 450,  remaining: 450")
        self.edit("money/Ledger.md", "received: 2600, remaining: 3400", "received: 2550, remaining: 3450")
        self.age("money/Ledger.md", "2026-03-20")
        self.assertIn("Tailspin owes 450 USD", json.dumps(self.today()))

    def test_every_card_keeps_a_source(self):
        for card in self.cards():
            self.assertTrue(card["sources"], card["key"])

    def test_a_name_with_digits_is_not_a_figure(self):
        from neva_engine.gate import Gate
        from neva_engine.model import Card
        card = Card("k", "r", "note", "needs_you", 1, "Apply to W27 and Q4", "", [], None, [])
        self.assertTrue(Gate(lambda p: True, NOW.date()).number_ok(card))

    def test_a_figure_with_a_unit_letter_is_still_a_figure(self):
        from neva_engine.gate import Gate
        from neva_engine.model import Card
        card = Card("k", "r", "note", "needs_you", 1, "Worth 10k", "", [], None, [])
        self.assertFalse(Gate(lambda p: True, NOW.date()).number_ok(card))

    def test_the_gate_unit_refuses_a_sum_that_does_not_add_up(self):
        from neva_engine.gate import Gate
        from neva_engine.model import Card, Figure
        path = os.path.join(self.root, "money/Ledger.md")
        a = Figure("3,000", "line", 3000, path, None)
        bad = Figure("9", "sum", 9, inputs=(a,))
        card = Card("k", "r", "note", "needs_you", 1, "Sum 9", "", [{"name": "x", "path": path, "line": 1}], None, [bad])
        self.assertFalse(Gate(lambda p: True, NOW.date()).number_ok(card))

    def test_the_gate_unit_refuses_a_line_that_lacks_the_value(self):
        from neva_engine.gate import Gate
        from neva_engine.model import Card, Figure
        path = os.path.join(self.root, "money/Ledger.md")
        fig = Figure("8,888", "line", 8888, path, 1)
        card = Card("k", "r", "note", "needs_you", 1, "Owed 8,888", "", [{"name": "x", "path": path, "line": 1}], None, [fig])
        self.assertFalse(Gate(lambda p: True, NOW.date()).number_ok(card))


class Deny(World):
    def test_a_denied_path_is_never_opened(self):
        self.write("clients/Zephyr Holdings.md", "---\nstatus: active\n---\n\n# Zephyr\n\ndeliver by 2026-03-24\n")
        today = self.today()
        self.assertNotIn("Zephyr", json.dumps(today))
        self.assertEqual({s["id"]: s for s in today["sources"]}["dates"]["denied"], 1)

    def test_a_case_variant_of_a_denied_path_is_denied(self):
        self.write("clients/zephyr note.md", "---\nstatus: active\n---\n\n# Zeph\n\ndeliver by 2026-03-24\n")
        self.assertNotIn("Zeph", json.dumps(self.today()))

    def test_a_symlink_into_a_denied_path_is_denied(self):
        self.write("clients/Zephyr Holdings.md", "---\nstatus: active\n---\n\n# Hidden\n\ndeliver by 2026-03-24\n")
        os.symlink(os.path.join(self.root, "clients/Zephyr Holdings.md"), os.path.join(self.root, "projects/Alias.md"))
        self.assertNotIn("Hidden", json.dumps(self.today()))

    def test_a_tagged_note_is_skipped(self):
        self.write("projects/Quiet.md", "---\ntags: [client, confidential]\n---\n\n# Quiet\n\ndeliver by 2026-03-24\n")
        self.assertNotIn("Quiet", json.dumps(self.today()))

    def test_a_term_in_a_note_never_reaches_the_output(self):
        self.write("projects/Partner.md", "# Partner\n\nThe Zephyrcorp launch is due by 2026-03-24.\n")
        today = self.today()
        self.assertNotIn("zephyrcorp", json.dumps(today).lower())

    def test_a_dotted_form_of_a_term_is_caught(self):
        self.write("projects/Partner.md", "# Partner\n\nThe Z.P.H launch is due by 2026-03-24.\n")
        self.assertNotIn("Z.P.H", json.dumps(self.today()))

    def test_a_term_inside_a_longer_word_is_not_a_hit(self):
        self.write("projects/Graphs.md", "# Graphs\n\nThe zphone launch is due by 2026-03-24.\n")
        self.assertIn("Graphs due 24 Mar", json.dumps(self.today()))

    def test_the_output_gate_catches_a_card_built_past_ingest(self):
        from neva_engine import rules
        real = rules.lead_cold

        def planted(facts, cfg, today):
            cards = real(facts, cfg, today)
            cards[0].title = "Follow up Zephyrcorp"
            cards[0].figures = []
            return cards
        rules.lead_cold = planted
        self.addCleanup(setattr, rules, "lead_cold", real)
        today = self.today()
        self.assertNotIn("Zephyrcorp", json.dumps(today))
        self.assertEqual(today["dropped"]["denied"], 1)

    def test_a_named_deny_file_that_is_missing_refuses_the_run(self):
        os.unlink(self.deny_path)
        self.assertEqual(self.tick(), 2)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "today.json")))


class Store(World):
    def test_the_folder_and_files_are_private(self):
        self.tick()
        self.assertEqual(stat.S_IMODE(os.stat(self.runtime).st_mode), 0o700)
        for name in ("engine.db", "today.json"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.runtime, name)).st_mode), 0o600)

    def test_facts_are_pointers_with_no_line_text(self):
        self.tick()
        with open(os.path.join(self.runtime, "engine.db"), "rb") as f:
            raw = f.read()
        self.assertNotIn(b"Balance, at completion", raw)
        self.assertNotIn(b"Launch: submit by", raw)

    def test_a_candidate_keeps_its_first_seen(self):
        self.tick()
        import datetime
        self.tick(now=NOW + datetime.timedelta(minutes=15))
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        first, last = db.execute("SELECT first_seen, last_seen FROM candidates WHERE key='lead_cold:Blue Yonder'").fetchone()
        self.assertLess(first, last)

    def test_no_row_doubles_on_a_second_tick(self):
        self.tick(); self.tick()
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        keys = [r[0] for r in db.execute("SELECT source||kind||subject FROM facts")]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_run_never_writes_to_the_notes(self):
        before = self.tree_hash()
        self.tick()
        self.assertEqual(before, self.tree_hash())

    def test_a_vault_env_cannot_redirect_a_run(self):
        os.environ["NEVA_VAULT"] = "/nonexistent"
        self.addCleanup(os.environ.pop, "NEVA_VAULT", None)
        self.assertEqual(self.tick(), 0)
