"""Read-only local web view of the cockpit, on the standard library's http.server.

Binds 127.0.0.1 only: anything else raises rather than being silently rewritten, because a
cockpit that shows session and cost data must never be reachable from the network by accident.
Every route sits under a random token in the path; a request that does not carry it gets 404
with no data, the same as a route that simply does not exist, so a wrong guess and a missing
route are indistinguishable from the outside. There is nothing here that writes: the only two
routes are a JSON snapshot and one HTML page rendered from that same snapshot, every value
escaped.
"""
import html
import http.server
import json
import secrets
import urllib.parse

from .formatting import context_label, format_cost, format_time, risk_summary

ALLOWED_HOST = "127.0.0.1"

PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Neva cockpit</title>
<style>
:root { color-scheme: light dark; --bg: #ffffff; --fg: #1b1f27; --muted: #5b6573;
  --line: #d9dde4; --head: #f3f5f8; --fail: #b4361b; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0b0d12; --fg: #e6e8ee; --muted: #9aa4b2; --line: #2a2e3a; --head: #141821;
    --fail: #e2795e; }
}
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 2rem;
  background: var(--bg); color: var(--fg); line-height: 1.45; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2.5rem; }
th, td { text-align: left; padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--line); }
thead th { position: sticky; top: 0; background: var(--head); color: var(--muted);
  font-weight: 600; z-index: 1; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }
h2 { font-size: 1rem; color: var(--muted); }
.fail { color: var(--fail); }
td.risk { white-space: normal; overflow-wrap: normal; word-break: normal; max-width: 22rem; }
</style>
</head>
<body>
<h1>Neva cockpit</h1>
<p id="status">refreshes every 5 seconds</p>
"""

PAGE_SCRIPT = """<script>
// The server renders and escapes every table; a refresh swaps in the tables of a fresh page
// instead of formatting values a second time here.
const REFRESH_MS = 5000;
async function refresh() {
  const status = document.querySelector("#status");
  try {
    const res = await fetch(window.location.pathname, {cache: "no-store"});
    if (!res.ok) throw new Error("page returned HTTP " + res.status);
    const fresh = new DOMParser().parseFromString(await res.text(), "text/html");
    for (const id of ["sessions", "hook-errors", "health"]) {
      const next = fresh.getElementById(id);
      if (next) document.getElementById(id).replaceWith(next);
    }
    status.textContent = "updated " + new Date().toLocaleTimeString();
  } catch (error) {
    status.textContent = "refresh failed: " + error.message +
      ". The page keeps the last data; check that neva cockpit --web is still running.";
  }
}
setInterval(refresh, REFRESH_MS);
</script>
</body>
</html>
"""

SESSION_HEADERS = ("harness", "project", "branch", "started", "last activity", "cost",
                   "context %", "risk flags")


NUMERIC_HEADERS = ("cost",)


def _cell(cell):
    """A cell is a plain value, or (text, title, class) for a tooltip or a CSS class."""
    text, title, cls = (cell if isinstance(cell, tuple) else (cell, "", ""))
    attrs = (f' title="{html.escape(str(title), quote=True).replace(chr(10), "&#10;")}"' if title else "") \
        + (f' class="{html.escape(cls, quote=True)}"' if cls else "")
    return f"<td{attrs}>{html.escape(str(text))}</td>"


def _table(table_id, headers, rows):
    """rows: [(cells, failed)]. Every value is escaped; the page carries no markup from data."""
    head = "".join(f'<th class="num">{html.escape(h)}</th>' if h in NUMERIC_HEADERS
                   else f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for cells, failed in rows:
        cls = ' class="fail"' if failed else ""
        body.append(f"<tr{cls}>" + "".join(_cell(c) for c in cells) + "</tr>")
    return (f'<table id="{table_id}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>\n')


def _time_cell(value, now, tz):
    return (format_time(value, now=now, tz=tz), value or "", "")


def _risk_cell(flags):
    text, full = risk_summary(flags)
    return (text, full, "risk")


def render_page(snap, now=None, tz=None):
    """The whole page with the current snapshot already in it, so it reads correctly before
    (or without) any script running; the script only swaps in a freshly rendered copy."""
    snap = snap if isinstance(snap, dict) else {}
    sessions = [([s.get("harness", ""), s.get("project", ""), (s.get("branch", ""), "", "mono"),
                  _time_cell(s.get("started_at"), now, tz),
                  _time_cell(s.get("last_activity"), now, tz),
                  (format_cost(s.get("cost_usd")), "", "num"), context_label(s.get("context_pct")),
                  _risk_cell(s.get("risk_flags"))], False)
                for s in snap.get("sessions") or []]
    errors = [([_time_cell(n.get("seen_at"), now, tz), (n.get("detail", ""), "", "mono")], False)
              for n in snap.get("hook_errors") or []]
    health_rows = [([h.get("name", ""), "OK" if h.get("ok") else "FAIL", h.get("detail", "")],
                    not h.get("ok")) for h in snap.get("health_rows") or []]
    return (PAGE_HEAD
            + "<h2>Sessions</h2>\n" + _table("sessions", SESSION_HEADERS, sessions)
            + "<h2>Hook errors</h2>\n" + _table("hook-errors", ("seen", "line"), errors)
            + "<h2>Health</h2>\n" + _table("health", ("check", "status", "detail"), health_rows)
            + PAGE_SCRIPT)


def generate_token():
    return secrets.token_urlsafe(24)


def default_snapshot():
    from . import snapshot
    from .store import Store

    store = Store()
    try:
        return snapshot.build(store)
    finally:
        store.close()


class CockpitHandler(http.server.BaseHTTPRequestHandler):
    server_version = "NevaCockpit/1"

    def log_message(self, format, *args):  # noqa: A002 (matches BaseHTTPRequestHandler's signature)
        pass  # the request path carries the capability token; never let it reach stderr

    def _send(self, status, body, content_type):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _not_found(self):
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler's naming)
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        try:
            token_ok = bool(parts) and secrets.compare_digest(parts[0], self.server.token)
        except (TypeError, UnicodeEncodeError):
            token_ok = False
        if not token_ok:
            self._not_found()
            return
        rest = parts[1:]
        if not rest:
            self._send(200, render_page(self.server.snapshot_fn()), "text/html; charset=utf-8")
        elif rest == ["api", "snapshot"]:
            self._send(200, json.dumps(self.server.snapshot_fn()), "application/json")
        else:
            self._not_found()


class CockpitServer(http.server.HTTPServer):
    def __init__(self, server_address, handler_cls, token, snapshot_fn):
        host = server_address[0]
        if host != ALLOWED_HOST:
            raise ValueError(
                f"cockpit web must bind {ALLOWED_HOST} only, refusing to bind {host!r}. "
                f"fix: pass host={ALLOWED_HOST!r}"
            )
        super().__init__(server_address, handler_cls)
        self.token = token
        self.snapshot_fn = snapshot_fn


def make_server(host=ALLOWED_HOST, port=0, token=None, snapshot_fn=None):
    return CockpitServer((host, port), CockpitHandler, token or generate_token(),
                         snapshot_fn or default_snapshot)


def serve(host=ALLOWED_HOST, port=0, token=None, snapshot_fn=None):
    server = make_server(host, port, token, snapshot_fn)
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/{server.token}/"
    print(f"cockpit web: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
