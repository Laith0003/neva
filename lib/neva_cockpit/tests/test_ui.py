import curses
import os
import sys
import tempfile
import unittest
from unittest import mock

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import health, snapshot, ui  # noqa: E402
from neva_cockpit.store import Store  # noqa: E402


class FakeScreen:
    def __init__(self, size, keys):
        self.size = size
        self.keys = list(keys)
        self.written = []

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.written = []

    def addstr(self, y, x, text, attr=0):
        self.written.append((y, x, text))

    def refresh(self):
        pass

    def timeout(self, ms):
        pass

    def getch(self):
        return self.keys.pop(0) if self.keys else ord("q")


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        patcher = mock.patch.object(curses, "curs_set", lambda v: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # never probe the real launchctl, OmniRoute or vault from a unit test (review M6)
        patcher = mock.patch.object(health, "snapshot", return_value={
            "nightly": {"ok": False, "detail": "probe disabled in tests"}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.store.close()

    def test_quit_key_returns_zero(self):
        screen = FakeScreen((24, 100), [ord("q")])
        self.assertEqual(ui._loop(screen, self.store), 0)

    def test_small_terminal_shows_a_specific_resize_message(self):
        screen = FakeScreen((24, 70), [ord("q")])
        ui._loop(screen, self.store)
        text = " ".join(t for _, _, t in screen.written)
        self.assertIn("too small", text)
        self.assertIn("70x24", text)

    def test_normal_terminal_draws_the_session_table_and_health_panel(self):
        self.store.upsert_session({"id": "s1", "harness": "claude", "project": "neva",
                                    "branch": "main", "cost_usd": 1.23, "context_pct": 40.0,
                                    "risk_flags": ["destructive-bash"]})
        screen = FakeScreen((30, 160), [ord("q")])
        ui._loop(screen, self.store)
        text = " ".join(t for _, _, t in screen.written)
        self.assertIn("neva", text)
        self.assertIn("destructive-bash", text)
        self.assertIn("Health", text)
        self.assertIn("probe disabled in tests", text)


class PanelTests(unittest.TestCase):
    """Review M3: the hook-error panel the docs promise, with the health detail text."""

    def setUp(self):
        self.store = Store(":memory:")
        patcher = mock.patch.object(curses, "curs_set", lambda v: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.store.close)

    def test_hook_errors_and_health_details_are_drawn(self):
        self.store.add_notes("hook-error", ["[error] stop: transcript unreadable"])
        fake_health = {"omniroute": {"ok": False, "detail": "OmniRoute unreachable: refused"},
                       "nightly": {"ok": True, "detail": "last nightly run finished"}}
        snap = lambda: snapshot.build(self.store, health_fn=lambda: fake_health)  # noqa: E731
        screen = FakeScreen((40, 160), [ord("q")])
        ui._loop(screen, self.store, snapshot_fn=snap)
        text = "\n".join(t for _, _, t in screen.written)
        self.assertIn("Hook errors", text)
        self.assertIn("[error] stop: transcript unreadable", text)
        self.assertIn("OmniRoute unreachable: refused", text)
        self.assertIn("last nightly run finished", text)


class RunNonTtyTests(unittest.TestCase):
    def test_run_degrades_with_a_specific_message_when_stdout_is_not_a_tty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.txt")
            with open(path, "w") as redirected, mock.patch.object(sys, "stdout", redirected), \
                 mock.patch.object(sys, "stderr", redirected):
                rc = ui.run(store=Store(":memory:"))
            with open(path) as fh:
                output = fh.read()
        self.assertEqual(rc, 1)
        self.assertIn("not a tty", output)


if __name__ == "__main__":
    unittest.main()
