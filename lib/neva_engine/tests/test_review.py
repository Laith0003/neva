"""Fresh review findings. Each test is the failure the review named."""
import datetime
import json
import os
import sqlite3

from neva_engine import rules, tick
from neva_engine.collectors import dates_on
from neva_engine.gate import Deny
from neva_engine.model import ConfigError

from .world import NOW, World

TERMS = ["Zephyrcorp", "ZPH", "Omega Vault", "زيفير", "آريا"]


class TermForms(World):
    deny = None

    def setUp(self):
        super().setUp()
        self.deny = Deny(TERMS)

    def test_a_symbol_glued_to_a_term_is_caught(self):
        for text in ("ZPH™", "ZPH®", "the ZPH™ deal", "Zephyrcorp℠"):
            self.assertTrue(self.deny.hit(text), text)

    def test_words_of_a_term_join_any_way(self):
        for text in ("OmegaVault", "Omega-Vault", "Omega_Vault", "omega   vault", "Omega.Vault"):
            self.assertTrue(self.deny.hit(text), text)

    def test_every_arabic_prefix_is_caught(self):
        for text in ("زيفير", "الزيفير", "للزيفير", "والزيفير", "بالزيفير", "وزيفير", "بزيفير", "لزيفير", "فزيفير", "كزيفير",
                     "لآريا", "وآريا", "الآريا"):
            self.assertTrue(self.deny.hit(text), text)

    def test_a_longer_word_is_not_a_hit(self):
        for text in ("zphone", "the zephyrcorpus", "زيفيرات", "مزيفير", "omegavaults"):
            self.assertFalse(self.deny.hit(text), text)

    def test_a_term_in_a_note_is_caught_in_each_form(self):
        for form in ("ZPH™", "للزيفير"):
            self.write("projects/Partner.md", f"# Partner\n\nThe {form} launch is due by 2026-03-24.\n")
            self.config_terms()
            self.assertNotIn("Partner due", json.dumps(self.today()), form)

    def config_terms(self):
        self.write_json(self.deny_path, {"terms": TERMS, "paths": [], "tags": []})


class DenyFile(World):
    def refused(self, value):
        self.write_json(self.deny_path, value)
        self.assertEqual(self.tick(), 2, value)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "today.json")), value)

    def test_an_empty_or_mistyped_list_refuses_the_run(self):
        for value in ({}, {"terms": []}, {"terms": "Zephyrcorp"}, {"terms": [1]}, {"terms": [""]}, {"terms": ["  "]}, ["Zephyrcorp"],
                      {"term": ["Zephyrcorp"]}, {"terms": ["x"], "paths": "clients/*"}, {"terms": ["x"], "tags": [1]}):
            self.refused(value)

    def test_the_key_is_required(self):
        del self.config["deny_file"]
        self.save()
        self.assertEqual(self.tick(), 2)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "today.json")))

    def test_an_empty_string_is_not_a_path(self):
        self.config["deny_file"] = ""
        self.save()
        self.assertEqual(self.tick(), 2)

    def test_an_explicit_null_means_no_list(self):
        self.config["deny_file"] = None
        self.save()
        self.assertEqual(self.tick(), 0)

    def test_the_error_names_the_field(self):
        with self.assertRaises(ConfigError) as caught:
            self.write_json(self.deny_path, {"terms": []})
            Deny.load(self.deny_path)
        self.assertIn("terms", str(caught.exception))


class BadDates(World):
    def test_an_impossible_date_in_a_note_is_not_a_deadline(self):
        self.write("projects/Bad.md", "# Bad\n\ndeliver by 2026-13-45\n")
        self.assertEqual(self.tick(), 0)
        self.assertNotIn("Bad due", json.dumps(self.today()))

    def test_an_impossible_payment_date_fails_only_that_source(self):
        self.edit("money/Events.md", "date: 2026-01-10", "date: 2026-13-45")
        self.assertEqual(self.tick(), 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        row = {s["id"]: s for s in today["sources"]}["ledger_events"]
        self.assertEqual(row["state"], "failed")
        self.assertIn("2026-13-45", row["error"])
        self.assertIn("deadline_near", self.rules(today))

    def test_an_impossible_bullet_date_fails_only_that_source(self):
        self.edit("money/Events.md", "2026-02-20: Northwind paid", "2026-02-31: Northwind paid")
        self.assertEqual(self.tick(), 1)

    def test_an_impossible_win_date_fails_goals_only(self):
        self.edit("GOALS.md", "by 2026-03-01", "by 2026-13-01")
        self.assertEqual(self.tick(), 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        self.assertEqual(today["move"]["state"], "unknown")
        self.assertEqual(today["money"]["owed"], 3400)

    def test_an_impossible_updated_date_fails_the_ledger_only(self):
        self.edit("money/Ledger.md", "updated: 2026-03-20", "updated: 2026-13-20")
        self.assertEqual(self.tick(), 1)

    def test_an_impossible_lead_date_does_not_stop_the_look(self):
        self.edit("leads/Blue Yonder.md", "updated: 2026-01-05", "updated: 2026-13-05")
        self.assertIn(self.tick(), (0, 1))
        self.assertTrue(os.path.exists(os.path.join(self.runtime, "today.json")))

    def test_an_impossible_proposal_date_is_skipped(self):
        self.write("reviews/Move proposal 2026-13-45.md", "# x\n\n| 1 | Not a real week | 5 |\n")
        self.assertEqual(self.today()["move"]["title"], "Collect Northwind and Tailspin")


class OneBadPart(World):
    def boom(self, name, text="boom"):
        real = getattr(rules, name)

        def broken(*a):
            raise RuntimeError(text)
        setattr(rules, name, broken)
        self.addCleanup(setattr, rules, name, real)

    def test_a_rule_that_raises_stops_only_itself(self):
        self.boom("lead_cold")
        self.assertEqual(self.tick(), 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        self.assertEqual(today["needs_you"][0]["kind"], "failure")
        self.assertIn("deadline_near", self.rules(today))
        self.assertEqual(today["run"]["state"], "degraded")

    def test_a_rule_error_passes_the_deny_list(self):
        self.boom("lead_cold", "Zephyrcorp broke it")
        self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("Zephyrcorp", text)
        self.assertIn("a denied file", text)

    def test_a_collector_that_raises_stops_only_itself(self):
        from neva_engine import collectors
        real = collectors.COLLECTORS["leads"]

        def broken(*a):
            raise KeyError("oops")
        collectors.COLLECTORS["leads"] = broken
        self.addCleanup(collectors.COLLECTORS.__setitem__, "leads", real)
        self.assertEqual(self.tick(), 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            today = json.load(f)
        self.assertEqual({s["id"]: s for s in today["sources"]}["leads"]["state"], "failed")
        self.assertIn("deadline_near", self.rules(today))

    def test_a_hero_that_raises_is_unknown_and_the_look_finishes(self):
        from neva_engine import today as today_mod
        real = today_mod.hero

        def broken(*a):
            raise ValueError("bad")
        today_mod.hero = broken
        self.addCleanup(setattr, today_mod, "hero", real)
        self.assertEqual(self.tick(), 1)
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["move"]["state"], "unknown")


class MonthWords(World):
    day = NOW.date()

    def iso(self, text):
        return [d for d, _ in dates_on(text, self.day)]

    def test_a_word_starting_like_a_month_is_not_a_date(self):
        for text in ("deliver 8 Novel ideas", "by 3 Marching bands", "due 2 Decks", "Augustus 4", "Janet 12"):
            self.assertEqual(self.iso(text), [], text)

    def test_a_following_year_is_read_not_ignored(self):
        self.assertEqual(self.iso("deliver by 5 Nov 2024"), ["2024-11-05"])
        self.assertEqual(self.iso("due Nov 5, 2024"), ["2024-11-05"])
        self.assertEqual(self.iso("due November 5 2027"), ["2027-11-05"])

    def test_an_old_year_never_becomes_a_future_deadline(self):
        self.write("projects/Old.md", "# Old\n\ndelivered by 25 Mar 2024\n")
        self.assertNotIn("Old due", json.dumps(self.today()))

    def test_full_names_and_short_forms_both_read(self):
        self.assertEqual(self.iso("by March 24"), ["2026-03-24"])
        self.assertEqual(self.iso("by 24 March"), ["2026-03-24"])
        self.assertEqual(self.iso("by Mar 24"), ["2026-03-24"])
        self.assertEqual(self.iso("by Sept 24"), ["2026-09-24"])

    def test_may_as_a_verb_is_not_a_date(self):
        self.assertEqual(self.iso("due 5 may be late"), [])
        self.assertEqual(self.iso("due 5 May"), ["2026-05-05"])

    def test_an_impossible_day_is_rejected(self):
        self.assertEqual(self.iso("by Feb 31"), [])
        self.assertEqual(self.iso("by 2026-02-31"), [])


class PaymentsNotRead(World):
    def card(self, key):
        return next(c for c in self.cards() if c["key"] == key)

    def test_an_absent_events_file_says_so(self):
        self.remove("money/Events.md")
        self.assertEqual(self.card("money_open:Tailspin")["why"], "Payments not read, so its age is unknown.")

    def test_a_failed_events_file_says_so(self):
        self.write("money/Events.md", "# no block\n")
        self.tick()
        with open(os.path.join(self.runtime, "today.json"), encoding="utf-8") as f:
            cards = json.load(f)["needs_you"]
        self.assertEqual(next(c for c in cards if c["key"] == "money_open:Northwind")["why"], "Payments not read, so its age is unknown.")

    def test_a_read_file_with_no_row_keeps_the_other_words(self):
        self.assertEqual(self.card("money_open:Tailspin")["why"], "No dated payment on file, so its age is unknown.")


class Lows(World):
    def test_a_row_whose_amount_fails_verification_has_no_due(self):
        schedule = {"currency": "USD", "items": [
            {"project": "Tailspin", "label": "a", "amount": 300, "due": True, "path": "money/Ledger.md", "quote": "remaining: 400"},
            {"project": "Tailspin", "label": "b", "amount": 100, "due": False, "path": "money/Ledger.md", "quote": "remaining: 400"},
        ]}
        self.write_json(self.config["sources"]["ledger_events"]["schedule"], schedule)
        money = self.today()["money"]
        row = next(r for r in money["rows"] if r["project"] == "Tailspin")
        self.assertIsNone(row["due"])
        self.assertIsNone(money["due"])

    def test_no_text_is_stored_in_a_fact(self):
        self.tick()
        db = sqlite3.connect(os.path.join(self.runtime, "engine.db"))
        self.addCleanup(db.close)
        values = json.dumps(db.execute("SELECT value FROM facts").fetchall(), ensure_ascii=False)
        for text in ("Win the harbour account", "Collect Northwind", "It needs no build", "Move proposal", "Skylark launch"):
            self.assertNotIn(text, values)


class FirstLook(World):
    def test_a_real_run_needs_no_module_state(self):
        self.assertEqual(tick.run(self.config_path, now=NOW + datetime.timedelta(days=1)), 0)
