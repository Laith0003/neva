"""Display formatting shared by the web view and the terminal view, so both read the same."""
import datetime

from .store import parse_instant

DASH = "–"
UNKNOWN = "unknown"
RECENT_DAYS = 6  # within this many days a time shows its weekday, older ones show the date


def format_time(value, now=None, tz=None):
    """'Today 00:51', 'Thu 22:29' or '2 Oct 13:49' in the display zone (local by default).
    Blank is a dash. A value that is not an ISO timestamp is returned as recorded."""
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        return DASH
    instant = parse_instant(text)
    if instant is None:
        return text
    moment = datetime.datetime.fromtimestamp(instant, tz=tz).astimezone(tz)
    today = (now or datetime.datetime.now().astimezone()).astimezone(tz).date()
    age = (today - moment.date()).days
    clock = f"{moment:%H:%M}"
    if age == 0:
        return f"Today {clock}"
    if 0 < age <= RECENT_DAYS:
        return f"{moment:%a} {clock}"
    return f"{moment.day} {moment:%b} {clock}"


def context_label(pct):
    """'15%', or 'unknown' when the share was never measured or is above 100, which means
    the assumed window was wrong. Never clamped."""
    if pct is None:
        return UNKNOWN
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return UNKNOWN
    if pct < 0 or pct > 100:
        return UNKNOWN
    return f"{pct:.0f}%"


def format_cost(cost):
    """'USD 1.50': two decimals, the currency as recorded (cost_usd is always USD)."""
    try:
        return f"USD {float(cost or 0):.2f}"
    except (TypeError, ValueError):
        return f"USD {0:.2f}"


def _severity(flag):
    if flag.startswith("destructive-bash"):
        return 3
    if flag == "bash-input-truncated":
        return 2
    if flag.startswith("tool-error"):
        return 1
    return 0


def risk_summary(flags):
    """(text, full list). One flag is shown as is; several show the count and the most severe
    (the first of equals), and the full list is returned for a tooltip. Nothing is cut."""
    flags = [str(f) for f in flags or []]
    if len(flags) <= 1:
        return (flags[0] if flags else ""), ""
    worst = max(flags, key=_severity)  # max keeps the first of equals
    return f"{len(flags)} flags, worst: {worst}", "\n".join(flags)
