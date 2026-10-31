"""today.json: the contract the app reads."""
import datetime
import json
import os

from .world import NOW, World


class Hero(World):
    def test_proposed_when_the_move_expired_and_a_proposal_ran(self):
        move = self.today()["move"]
        self.assertEqual(move["state"], "proposed")
        self.assertEqual(move["title"], "Collect Northwind and Tailspin")
        self.assertEqual(move["state_line"], "Proposed 13 Mar. Not locked. Your last move expired on 1 Mar.")
        self.assertEqual(move["why_now"], "It needs no build.")

    def test_a_newer_failed_proposal_shows_failed(self):
        self.write("reviews/Move proposal 2026-03-20.md", "# x\n\nModel call unavailable this week.\n")
        move = self.today()["move"]
        self.assertEqual(move["state"], "proposal_failed")
        self.assertEqual(move["title"], "Nothing is locked")
        self.assertIn("20 Mar", move["state_line"])

    def test_past_its_date_with_no_proposal(self):
        self.remove("reviews/Move proposal 2026-03-13.md")
        self.remove("reviews/Move proposal 2026-03-06.md")
        move = self.today()["move"]
        self.assertEqual((move["state"], move["title"]), ("past_date", "Win the harbour account"))

    def test_locked_while_the_date_runs(self):
        self.edit("GOALS.md", "by 2026-03-01", "by 2026-12-01")
        move = self.today()["move"]
        self.assertEqual(move["state"], "locked")
        self.assertEqual(move["state_line"], "Locked 1 Feb. Win by 1 Dec.")

    def test_no_move_no_proposal(self):
        self.edit("GOALS.md", "- Move: [[Win the harbour account]]. The 12 people who asked twice.\n", "")
        self.remove("reviews/Move proposal 2026-03-13.md")
        self.remove("reviews/Move proposal 2026-03-06.md")
        move = self.today()["move"]
        self.assertEqual((move["state"], move["title"]), ("no_move", "Nothing is locked"))

    def test_no_next_step_is_said_never_invented(self):
        self.assertIsNone(self.today()["move"]["next"])

    def test_the_first_step_a_proposal_names_is_the_next_step(self):
        self.edit("reviews/Move proposal 2026-03-13.md", "**Recommendation", "Start with Northwind, because Tailspin clears nothing.\n\n**Recommendation")
        self.assertEqual(self.today()["move"]["next"], "Start with Northwind, because Tailspin clears nothing.")

    def test_a_first_step_with_a_figure_is_left_out_not_gated(self):
        self.edit("reviews/Move proposal 2026-03-13.md", "**Recommendation", "Start with Northwind, it owes 9,000.\n\n**Recommendation")
        move = self.today()["move"]
        self.assertEqual(move["state"], "proposed")
        self.assertIsNone(move["next"])

    def test_evidence_links_the_proposal_to_money_it_names(self):
        move = self.today()["move"]
        self.assertEqual(move["evidence"], "3,400 USD owed: Northwind 3,000, Tailspin 400. 1,900 due now.")

    def test_evidence_is_absent_for_a_move_with_no_money(self):
        self.edit("reviews/Move proposal 2026-03-13.md", "Collect Northwind and Tailspin", "Ship the kiosk")
        self.assertIsNone(self.today()["move"]["evidence"])

    def test_a_failed_goals_read_is_unknown_not_empty(self):
        self.write("GOALS.md", "# Goals\n")
        self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["move"]["state"], "unknown")


class Limits(World):
    def test_needs_you_caps_at_five_and_counts_the_rest(self):
        for i in range(8):
            self.write(f"projects/P{i}.md", f"# P{i}\n\nship by 2026-03-2{i % 8 + 1}, due then\n")
        today = self.today()
        self.assertEqual(len(today["needs_you"]), 5)
        self.assertGreater(today["needs_you_more"], 0)

    def test_opportunities_cap_at_three(self):
        for i in range(5):
            self.write(f"leads/Old{i}.md", "---\ndate: 2026-01-01\nstatus: new\n---\n\n# Old\n")
            self.age(f"leads/Old{i}.md", "2026-01-05")
        today = self.today()
        self.assertEqual(len(today["opportunities"]), 3)
        self.assertEqual(today["opportunities_more"], 3)

    def test_nearest_deadline_ranks_first_among_deadlines(self):
        keys = [c["key"] for c in self.today()["needs_you"] if c["rule"] == "deadline_near"]
        self.assertEqual(keys[0], "deadline_near:Skylark:2026-03-22")

    def test_all_candidates_stay_in_the_file(self):
        today = self.today()
        self.assertGreaterEqual(len(today["candidates"]), len(today["needs_you"]) + len(today["opportunities"]))


class Contract(World):
    def test_shape(self):
        today = self.today()
        self.assertEqual(today["schema"], 1)
        self.assertEqual(today["reasoned"], False)
        self.assertEqual(set(today) >= {"looked_at", "day", "run", "move", "money", "needs_you", "then", "opportunities", "sources", "dropped"}, True)
        self.assertEqual(today["then"], [])

    def test_a_card_has_the_fields_the_app_needs(self):
        for card in self.cards():
            self.assertEqual(set(card) >= {"id", "key", "rule", "kind", "title", "why", "sources", "confidence", "as_of"}, True)
            for s in card["sources"]:
                self.assertEqual(set(s), {"name", "path", "line"})

    def test_the_day_rolls_at_the_configured_hour(self):
        early = datetime.datetime(2026, 3, 21, 4, 30)
        self.assertEqual(self.today(now=early)["day"], "2026-03-20")

    def test_the_gap_since_the_last_look_is_measured(self):
        self.tick()
        later = self.today(now=NOW + datetime.timedelta(hours=6))
        self.assertEqual(later["run"]["gap_hours"], 6)

    def test_a_first_run_has_no_gap(self):
        self.assertIsNone(self.today()["run"]["gap_hours"])

    def test_the_file_is_replaced_whole(self):
        self.tick()
        self.assertEqual([f for f in os.listdir(self.runtime) if ".tmp" in f], [])

    def test_a_dry_run_prints_and_keeps_nothing(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(self.tick(dry_run=True), 0)
        self.assertEqual(json.loads(buf.getvalue())["schema"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "today.json")))
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "engine.db")))
