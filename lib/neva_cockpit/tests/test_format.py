import datetime
import os
import sys
import unittest

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import web  # noqa: E402
from neva_cockpit.formatting import context_label, format_time  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # a Thursday


class FormatTimeTests(unittest.TestCase):
    def label(self, value):
        return format_time(value, now=NOW, tz=UTC)

    def test_today(self):
        self.assertEqual(self.label("2026-10-15T00:51:00Z"), "Today 00:51")

    def test_this_week_uses_the_weekday(self):
        self.assertEqual(self.label("2026-10-13T22:29:00Z"), "Tue 22:29")

    def test_older_uses_day_and_month(self):
        self.assertEqual(self.label("2026-10-02T13:49:00Z"), "2 Oct 13:49")

    def test_blank_is_a_dash(self):
        self.assertEqual(self.label(""), "–")

    def test_offsets_are_converted_to_the_display_zone(self):
        self.assertEqual(self.label("2026-10-15T03:51:00+03:00"), "Today 00:51")

    def test_unparseable_is_shown_as_recorded(self):
        self.assertEqual(self.label("yesterday-ish"), "yesterday-ish")


class ContextLabelTests(unittest.TestCase):
    def test_none_is_unknown(self):
        self.assertEqual(context_label(None), "unknown")

    def test_above_100_is_unknown_not_clamped(self):
        self.assertEqual(context_label(140.0), "unknown")

    def test_value(self):
        self.assertEqual(context_label(15.04), "15%")

    def test_zero_is_a_real_zero(self):
        self.assertEqual(context_label(0.0), "0%")


def page(session):
    return web.render_page({"sessions": [session]}, now=NOW, tz=UTC)


class WebContextAndTimeTests(unittest.TestCase):
    def test_null_context_renders_unknown(self):
        html_ = page({"id": "s1", "context_pct": None})
        table = html_[html_.index('<table id="sessions"'):html_.index("</table>")]
        self.assertIn(">unknown<", table)
        self.assertNotIn("0%", table)
        self.assertNotIn("100%", table)

    def test_time_has_iso_in_title(self):
        html_ = page({"id": "s1", "last_activity": "2026-10-15T00:51:00Z", "started_at": ""})
        self.assertIn('<td title="2026-10-15T00:51:00Z">Today 00:51</td>', html_)

    def test_blank_started_is_a_dash(self):
        self.assertIn("<td>–</td>", page({"id": "s1", "started_at": ""}))


class CostTests(unittest.TestCase):
    def cell(self, cost):
        html_ = page({"id": "s1", "cost_usd": cost})
        table = html_[html_.index('<table id="sessions"'):html_.index("</table>")]
        return table

    def test_two_decimals_with_currency_right_aligned(self):
        self.assertIn('<td class="num">USD 1.50</td>', self.cell(1.5))

    def test_rounds_to_two_decimals(self):
        self.assertIn("USD 0.01<", self.cell(0.0123456))

    def test_zero_cost_is_shown(self):
        self.assertIn("USD 0.00<", self.cell(0))
class RiskFlagTests(unittest.TestCase):
    FLAGS = ["tool-error:Bash", "bash-input-truncated", "destructive-bash:rm-rf",
             "destructive-bash:force-push"]

    def table(self, flags):
        html_ = page({"id": "s1", "risk_flags": flags})
        return html_[html_.index('<table id="sessions"'):html_.index("</table>")]

    def test_count_and_most_severe_flag(self):
        self.assertIn("4 flags, worst: destructive-bash:rm-rf", self.table(self.FLAGS))

    def test_full_list_is_in_a_title_untruncated(self):
        full = "&#10;".join(self.FLAGS)
        self.assertIn(f'title="{full}"', self.table(self.FLAGS))

    def test_single_flag_is_shown_as_is(self):
        self.assertIn(">tool-error:Bash<", self.table(["tool-error:Bash"]))

    def test_no_flags_is_empty(self):
        self.assertIn('<td class="risk"></td>', self.table([]))

    def test_truncated_beats_tool_error(self):
        self.assertIn("worst: bash-input-truncated",
                      self.table(["tool-error:Read", "bash-input-truncated"]))


class HookErrorTimeTests(unittest.TestCase):
    def test_seen_at_is_local_time_with_iso_in_title(self):
        html_ = web.render_page({"hook_errors": [{"seen_at": "2026-10-15T00:51:00Z", "detail": "boom"}]},
                                now=NOW, tz=UTC)
        table = html_[html_.index('<table id="hook-errors"'):]
        table = table[:table.index("</table>")]
        self.assertIn('<td title="2026-10-15T00:51:00Z">Today 00:51</td>', table)
        self.assertNotIn(">2026-10-15T00:51:00Z<", table)


class LongRiskFlagTests(unittest.TestCase):
    LONG = "destructive-bash:" + "very-long-flag-name-" * 6 + "end"

    def test_long_flag_renders_in_full_and_css_wraps_on_word_boundaries(self):
        html_ = page({"id": "s1", "risk_flags": [self.LONG]})
        self.assertIn(f'<td class="risk">{self.LONG}</td>', html_)
        self.assertNotIn("…", html_)
        self.assertNotIn("...", html_)
        self.assertIn("td.risk { white-space: normal; overflow-wrap: normal; "
                      "word-break: normal; max-width: 22rem; }", html_)


class StyleTests(unittest.TestCase):
    HTML = page({"id": "s1"})

    def test_no_external_requests(self):
        self.assertNotIn("http://", self.HTML)
        self.assertNotIn("https://", self.HTML)
        self.assertNotIn("@import", self.HTML)

    def test_system_font_light_dark_and_sticky_header(self):
        for needle in ("system-ui", "prefers-color-scheme: dark", "position: sticky",
                       "color-scheme: light dark"):
            self.assertIn(needle, self.HTML)

    def test_body_is_not_monospace(self):
        body_rule = self.HTML[self.HTML.index("body {"):self.HTML.index("}", self.HTML.index("body {"))]
        self.assertNotIn("monospace", body_rule)
        self.assertIn(".mono", self.HTML)
