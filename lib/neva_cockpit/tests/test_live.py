"""Review M2: a record written after the cockpit starts shows up without a restart."""
import argparse
import curses
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cli.commands import cockpit as command  # noqa: E402
from neva_cockpit import health, ui, web  # noqa: E402

QUIET_HEALTH = {"omniroute": {"ok": False, "detail": "probe disabled in tests"}}


def cost_line(session_id, cost):
    return json.dumps({"session_id": session_id, "project": session_id,
                       "timestamp": "2026-10-08T10:00:00", "estimated_cost_usd": cost}) + "\n"


class LiveRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        env = {"HOME": root, "NEVA_DATA_DIR": os.path.join(root, "data"),
               "NEVA_STATE_DIR": os.path.join(root, "state"),
               "NEVA_CONFIG": os.path.join(root, "none.env")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("NEVA_METRICS_DIR", "NEVA_OBSERVATIONS_DIR", "NEVA_VAULT"):
            os.environ.pop(name, None)
        patcher = mock.patch.object(health, "snapshot", return_value=QUIET_HEALTH)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.costs = os.path.join(root, "data", "metrics", "costs.jsonl")
        os.makedirs(os.path.dirname(self.costs))
        with open(self.costs, "w", encoding="utf-8") as fh:
            fh.write(cost_line("before-start", 1.0))

    def append(self, session_id):
        with open(self.costs, "a", encoding="utf-8") as fh:
            fh.write(cost_line(session_id, 2.0))

    def captured_snapshot_fn(self, flag, target):
        captured = {}

        def fake(*args, **kwargs):
            captured["fn"] = kwargs["snapshot_fn"]
            captured["first"] = {s["id"] for s in kwargs["snapshot_fn"]()["sessions"]}
            self.append("after-start")
            captured["second"] = {s["id"] for s in kwargs["snapshot_fn"]()["sessions"]}
            return 0

        args = argparse.Namespace(json=False, web=False)
        if flag:
            setattr(args, flag, True)
        with mock.patch.object(target[0], target[1], side_effect=fake):
            self.assertEqual(command.run(args), 0)
        return captured

    def test_tui_sees_a_record_appended_after_start(self):
        captured = self.captured_snapshot_fn(None, (ui, "run"))
        self.assertEqual(captured["first"], {"before-start"})
        self.assertEqual(captured["second"], {"before-start", "after-start"})

    def test_web_snapshot_sees_a_record_appended_after_start(self):
        captured = self.captured_snapshot_fn("web", (web, "serve"))
        self.assertEqual(captured["second"], {"before-start", "after-start"})

    def test_tui_loop_redraws_with_the_new_record(self):
        from neva_cockpit import snapshot
        from neva_cockpit.store import Store

        store = Store(":memory:")
        self.addCleanup(store.close)
        drawn = []

        class Screen:
            def __init__(screen):
                screen.keys = [-1, ord("q")]
                screen.frame = []

            def getmaxyx(screen):
                return (40, 160)

            def erase(screen):
                screen.frame = []

            def addstr(screen, y, x, text, attr=0):
                screen.frame.append(text)

            def refresh(screen):
                drawn.append("\n".join(screen.frame))

            def timeout(screen, ms):
                pass

            def getch(screen):
                key = screen.keys.pop(0)
                if key == -1:
                    self.append("after-start")
                return key

        with mock.patch.object(curses, "curs_set", lambda v: None):
            ui._loop(Screen(), store, lambda: snapshot.build(store, refresh=True))
        self.assertNotIn("after-start", drawn[0])
        self.assertIn("after-start", drawn[1])
        self.assertEqual(len(store.sessions()), 2)

    def test_web_page_polls_the_snapshot(self):
        page = web.render_page({})
        self.assertIn("setInterval(refresh, REFRESH_MS)", page)


if __name__ == "__main__":
    unittest.main()
