"""Curses TUI for the cockpit: a live table of sessions, a hook-error panel and a health panel.

Read-only and local: everything it draws comes from one snapshot.build() call per refresh.
Degrades with a specific message instead of a traceback in the two cases curses cannot handle:
stdout is not a terminal at all, or the terminal is attached but too small to draw the table in.
"""
import curses
import sys

from . import snapshot
from .store import Store

MIN_COLS = 80
MIN_LINES = 10
REFRESH_MS = 2000
HOOK_ERROR_LINES = 3


def _safe_addstr(stdscr, y, x, text, attr=curses.A_NORMAL):
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass  # writing to the terminal's last cell raises in curses; never fatal


def _draw(stdscr, snap, width, height):
    sessions = snap.get("sessions") or []
    hook_errors = (snap.get("hook_errors") or [])[:HOOK_ERROR_LINES]
    health_rows = snap.get("health_rows") or []
    row = 0
    _safe_addstr(stdscr, row, 0, "Neva cockpit"[:width - 1], curses.A_BOLD)
    row += 2
    header = (f"{'HARNESS':<8} {'PROJECT':<14} {'BRANCH':<14} {'STARTED':<16} "
              f"{'LAST ACTIVITY':<16} {'COST':>8} {'CTX%':>6}  RISK")
    _safe_addstr(stdscr, row, 0, header[:width - 1], curses.A_UNDERLINE)
    row += 1
    # bottom panels: hook errors (title + lines), health (title + rows), the quit hint
    bottom = (1 + max(1, len(hook_errors))) + (1 + len(health_rows)) + 1 + 1
    for s in sessions:
        if row >= height - bottom - 1:
            break
        risk = ",".join(s.get("risk_flags") or [])
        line = (f"{str(s.get('harness', ''))[:8]:<8} {str(s.get('project', ''))[:14]:<14} "
                f"{str(s.get('branch', ''))[:14]:<14} {str(s.get('started_at', ''))[:16]:<16} "
                f"{str(s.get('last_activity', ''))[:16]:<16} {float(s.get('cost_usd') or 0):>8.2f} "
                f"{float(s.get('context_pct') or 0):>5.1f}%  {risk}")
        _safe_addstr(stdscr, row, 0, line[:width - 1], curses.A_BOLD if risk else curses.A_NORMAL)
        row += 1
    if not sessions:
        _safe_addstr(stdscr, row, 0, "(no sessions ingested yet)"[:width - 1], curses.A_DIM)

    row = max(row + 1, height - bottom)
    _safe_addstr(stdscr, row, 0, "Hook errors"[:width - 1], curses.A_BOLD)
    row += 1
    if not hook_errors:
        _safe_addstr(stdscr, row, 0, "(none recorded)"[:width - 1], curses.A_DIM)
        row += 1
    for note in hook_errors:
        if row >= height - 1:
            break
        text = f"{note.get('seen_at', '')[:19]:<19} {note.get('detail', '')}"
        _safe_addstr(stdscr, row, 0, text[:width - 1])
        row += 1
    _safe_addstr(stdscr, row, 0, "Health"[:width - 1], curses.A_BOLD)
    row += 1
    for info in health_rows:
        if row >= height - 1:
            break
        status = "OK" if info.get("ok") else "FAIL"
        text = f"{info.get('name', ''):<18} {status:<4} {info.get('detail', '')}"
        _safe_addstr(stdscr, row, 0, text[:width - 1])
        row += 1
    _safe_addstr(stdscr, height - 1, 0, "q to quit"[:width - 1], curses.A_DIM)


def _loop(stdscr, store, snapshot_fn=None):
    snapshot_fn = snapshot_fn or (lambda: snapshot.build(store))
    curses.curs_set(0)
    stdscr.timeout(REFRESH_MS)
    while True:
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        if width < MIN_COLS or height < MIN_LINES:
            msg = (f"terminal too small for the cockpit: need at least {MIN_COLS}x{MIN_LINES}, "
                   f"have {width}x{height}. Resize it, or press q to quit.")
            _safe_addstr(stdscr, 0, 0, msg[:max(0, width - 1)])
        else:
            _draw(stdscr, snapshot_fn(), width, height)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):
            return 0


def run(store=None, snapshot_fn=None):
    """Blocking. Returns an exit code; never raises for an unusable terminal."""
    if not sys.stdout.isatty():
        print("cockpit: no interactive terminal attached (stdout is not a tty). "
              "Run this in a terminal, or use --json or --web instead.", file=sys.stderr)
        return 1
    owns_store = store is None
    store = store or Store()
    try:
        return curses.wrapper(_loop, store, snapshot_fn)
    finally:
        if owns_store:
            store.close()
