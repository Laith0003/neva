"""Each rule proves it fires and proves it stays silent."""
from .world import World


class MoneyOpen(World):
    def test_fires_on_remaining_money_and_an_old_payment(self):
        card = next(c for c in self.cards() if c["key"] == "money_open:Northwind")
        self.assertEqual(card["title"], "Northwind owes 3,000 USD, 1,500 due now")
        self.assertIn("Last payment 28 days ago", card["why"])

    def test_no_dated_payment_is_unknown_age_not_zero(self):
        card = next(c for c in self.cards() if c["key"] == "money_open:Tailspin")
        self.assertIn("age is unknown", card["why"])

    def test_silent_on_a_recent_payment(self):
        self.edit("money/Events.md", "2026-02-20: Northwind paid", "2026-03-18: Northwind paid")
        self.assertNotIn("money_open:Northwind", [c["key"] for c in self.cards()])

    def test_silent_when_nothing_remains(self):
        self.assertNotIn("money_open:Paid_Co", [c["key"] for c in self.cards()])

    def test_a_dated_bullet_beats_the_older_yaml_row(self):
        self.assertIn("20 Feb", next(c for c in self.cards() if c["key"] == "money_open:Northwind")["why"])

    def test_a_bullet_without_paid_is_not_a_payment(self):
        self.edit("money/Events.md", "2026-02-20: Northwind paid 1,000 USD against", "2026-02-20: Northwind asked about")
        self.assertIn("10 Jan", next(c for c in self.cards() if c["key"] == "money_open:Northwind")["why"])


class LedgerDrift(World):
    def test_fires_when_totals_differ_from_rows(self):
        self.edit("money/Ledger.md", "remaining: 3400", "remaining: 4400")
        self.age("money/Ledger.md", "2026-03-20")
        card = next(c for c in self.cards() if c["rule"] == "ledger_drift")
        self.assertEqual(card["title"], "Numbers disagree: rows add up to 3,400 USD, totals say 4,400")

    def test_a_conflict_blocks_the_headline_and_picks_nothing(self):
        self.edit("money/Ledger.md", "remaining: 3400", "remaining: 4400")
        self.age("money/Ledger.md", "2026-03-20")
        money = self.today()["money"]
        self.assertEqual(money["state"], "conflict")
        self.assertIsNone(money["owed"])

    def test_fires_when_the_updated_line_is_older_than_the_file(self):
        self.age("money/Ledger.md", "2026-03-20")
        self.edit("money/Ledger.md", "updated: 2026-03-20", "updated: 2026-01-01")
        self.age("money/Ledger.md", "2026-03-20")
        self.assertIn("ledger_drift", self.rules())

    def test_silent_when_the_ledger_agrees(self):
        self.assertNotIn("ledger_drift", self.rules())


class DeadlineNear(World):
    def keys(self):
        return [c["key"] for c in self.cards() if c["rule"] == "deadline_near"]

    def test_fires_on_a_dated_line_inside_the_window(self):
        card = next(c for c in self.cards() if c["key"] == "deadline_near:Skylark:2026-03-22")
        self.assertEqual(card["title"], "Skylark launch due 22 Mar")

    def test_fires_on_a_table_row(self):
        self.assertIn("deadline_near:Contoso:2026-03-28", self.keys())

    def test_the_source_is_named_after_the_note_not_its_file(self):
        self.write("projects/Delta/CLAUDE.md", "# Delta\n\nship by 2026-03-24\n")
        self.config["sources"]["dates"]["globs"].append("projects/*/CLAUDE.md")
        self.config["sources"]["dates"]["folder_named"] = ["CLAUDE"]
        self.save()
        card = next(c for c in self.cards() if c["key"] == "deadline_near:Delta:2026-03-24")
        self.assertEqual(card["sources"][0]["name"], "Delta")

    def test_a_table_row_reads_as_words_with_no_date_cell(self):
        today = self.today()
        card = next(c for c in self.cards(today) if c["key"] == "deadline_near:Contoso:2026-03-28")
        self.assertEqual(card["why"], "Balance, at completion. Due on delivery.")
        self.assertEqual(today["dropped"]["number"], 0)

    def test_a_table_row_with_only_a_date_cell_has_no_why(self):
        self.write("projects/Bare.md", "# Bare\n\n| 2026-03-24 | Due |\n")
        card = next(c for c in self.cards() if c["key"] == "deadline_near:Bare:2026-03-24")
        self.assertEqual(card["why"], "Due.")

    def test_reads_a_month_name_with_no_year(self):
        self.edit("projects/Skylark.md", "Launch: submit by 2026-03-22, the board", "Launch: submit by Mar 21, the board")
        self.assertIn("deadline_near:Skylark:2026-03-21", self.keys())

    def test_silent_on_a_date_in_the_past(self):
        self.assertNotIn("deadline_near:Skylark:2026-03-01", self.keys())

    def test_silent_past_the_window(self):
        self.assertNotIn("deadline_near:Skylark:2026-09-01", self.keys())
        self.assertNotIn("deadline_near:Skylark:2026-04-20", self.keys())

    def test_silent_without_a_deadline_word(self):
        self.assertNotIn("deadline_near:Skylark:2026-03-25", self.keys())

    def test_silent_on_a_ticked_line(self):
        self.assertNotIn("deadline_near:Skylark:2026-03-23", self.keys())

    def test_silent_on_an_archived_note(self):
        self.assertNotIn("deadline_near:Old:2026-03-24", self.keys())

    def test_a_deadline_word_far_from_the_date_does_not_count(self):
        self.write("projects/Far.md", "# Far\n\nThe inquiry arrived 2026-03-21 in writing, and the rest of this long line talks about what is due.\n")
        self.assertNotIn("deadline_near:Far:2026-03-21", self.keys())

    def test_one_line_is_one_card_on_its_earliest_date(self):
        self.write("projects/Two.md", "# Two\n\nApply by 2026-03-26 (submit by Mar 24) with numbers.\n")
        self.assertEqual([k for k in self.keys() if ":Two:" in k], ["deadline_near:Two:2026-03-24"])

    def test_a_word_just_after_the_date_counts(self):
        self.write("projects/Near.md", "# Near\n\nThe 2026-03-24 deadline holds.\n")
        self.assertIn("deadline_near:Near:2026-03-24", self.keys())

    def test_a_table_row_counts_the_whole_row(self):
        self.write("projects/Row.md", "# Row\n\n| 2026-03-24 | A very long description cell that runs on and on | Due on delivery |\n")
        self.assertIn("deadline_near:Row:2026-03-24", self.keys())

    def test_a_skipped_note_is_not_read_for_dates(self):
        self.config["sources"]["dates"]["skip_notes"] = ["Skylark"]
        self.save()
        self.assertNotIn("deadline_near:Skylark:2026-03-22", self.keys())

    def test_a_word_inside_a_word_does_not_count(self):
        self.write("projects/Words.md", "# Words\n\nthe bypass work on 2026-03-24\n")
        self.assertNotIn("deadline_near:Words:2026-03-24", self.keys())


class MoveStalled(World):
    def test_fires_when_the_date_passed(self):
        move = self.today()["move"]
        self.assertEqual(move["expired"], {"title": "Win the harbour account", "date": "2026-03-01", "days": 19})
        self.assertIn("move_stalled", self.rules())

    def test_fires_when_the_counter_is_over_the_limit(self):
        self.edit("GOALS.md", "by 2026-03-01", "by 2026-12-01")
        self.assertIn("move_stalled", self.rules())

    def test_silent_on_a_live_move_under_the_limit(self):
        self.edit("GOALS.md", "by 2026-03-01", "by 2026-12-01")
        self.write_json(self.config["sources"]["goals"]["stall_state"], {"stalled_days": 1})
        self.assertNotIn("move_stalled", self.rules())

    def test_an_absent_counter_is_unknown_and_a_live_move_stays_silent(self):
        import os
        self.edit("GOALS.md", "by 2026-03-01", "by 2026-12-01")
        os.unlink(self.config["sources"]["goals"]["stall_state"])
        today = self.today()
        self.assertNotIn("move_stalled", self.rules(today))
        self.assertIsNone(today["move"]["stalled_days"])


class BuildUnreviewed(World):
    def card(self):
        return next(c for c in self.cards() if c["rule"] == "build_unreviewed")

    def test_fires_and_counts_only_builds_that_wait(self):
        self.assertEqual(self.card()["title"], "2 finished builds wait for your review")

    def test_a_merged_build_does_not_count(self):
        self.write_job("build-one", note="merged in PR 3")
        self.assertEqual(self.card()["title"], "1 finished build waits for your review")

    def test_no_job_name_reaches_the_card(self):
        self.assertNotIn("build-one", str(self.card()["title"]) + str(self.card()["why"]))

    def test_silent_with_nothing_waiting(self):
        self.write_job("build-one", note="merged in PR 3")
        self.write_job("build-two", reviewed=True)
        self.assertNotIn("build_unreviewed", self.rules())


class LeadCold(World):
    def test_fires_on_a_silent_open_lead(self):
        card = next(c for c in self.today()["opportunities"] if c["key"] == "lead_cold:Blue Yonder")
        self.assertEqual(card["title"], "Follow up Blue Yonder: silent 74 days")

    def test_silent_on_a_warm_lead(self):
        self.assertNotIn("lead_cold:Fresh Co", [c["key"] for c in self.today()["opportunities"]])

    def test_silent_on_a_closed_lead(self):
        self.assertNotIn("lead_cold:Done Co", [c["key"] for c in self.today()["opportunities"]])

    def test_a_later_file_change_warms_a_lead(self):
        self.age("leads/Blue Yonder.md", "2026-03-18")
        self.assertNotIn("lead_cold:Blue Yonder", [c["key"] for c in self.today()["opportunities"]])

    def test_confidence_is_a_word_never_a_percent(self):
        card = self.today()["opportunities"][0]
        self.assertEqual(card["confidence"], "medium")
        self.assertEqual(len(card["sources"]), 1)
