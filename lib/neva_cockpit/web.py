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

ALLOWED_HOST = "127.0.0.1"

PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Neva cockpit</title>
<style>
body { font-family: ui-monospace, monospace; margin: 2rem; background: #0b0d12; color: #e6e8ee; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; }
th, td { text-align: left; padding: 0.3rem 0.6rem; border-bottom: 1px solid #2a2e3a; }
th { color: #9aa4b2; font-weight: 600; }
h2 { font-size: 1rem; color: #9aa4b2; }
.fail { color: #e2795e; }
</style>
</head>
<body>
<h1>Neva cockpit</h1>
<p id="status">refreshes every 5 seconds</p>
"""

PAGE_SCRIPT = """<script>
function fill(id, rows) {
  const body = document.querySelector("#" + id + " tbody");
  body.innerHTML = "";
  for (const r of rows) {
    const row = document.createElement("tr");
    for (const value of r.cells) {
      const cell = document.createElement("td");
      cell.textContent = value == null ? "" : value;
      if (r.fail) cell.className = "fail";
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
}
function render(data) {
  fill("sessions", (data.sessions || []).map(s => ({cells: [s.harness, s.project, s.branch,
    s.started_at, s.last_activity, (s.cost_usd || 0).toFixed(2), (s.context_pct || 0) + "%",
    (s.risk_flags || []).join(", ")]})));
  fill("hook-errors", (data.hook_errors || []).map(n => ({cells: [n.seen_at, n.detail]})));
  fill("health", (data.health_rows || []).map(h => ({fail: !h.ok,
    cells: [h.name, h.ok ? "OK" : "FAIL", h.detail]})));
}
const REFRESH_MS = 5000;
async function refresh() {
  const status = document.querySelector("#status");
  try {
    const base = window.location.pathname.replace(/\\/$/, "");
    const res = await fetch(base + "/api/snapshot");
    if (!res.ok) throw new Error("snapshot returned HTTP " + res.status);
    render(await res.json());
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


def _table(table_id, headers, rows):
    """rows: [(cells, failed)]. Every value is escaped; the page carries no markup from data."""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for cells, failed in rows:
        cls = ' class="fail"' if failed else ""
        body.append("<tr>" + "".join(f"<td{cls}>{html.escape(str(c))}</td>" for c in cells)
                    + "</tr>")
    return (f'<table id="{table_id}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>\n')


def render_page(snap):
    """The whole page with the current snapshot already in it, so it reads correctly before
    (or without) any script running; the script only refreshes the same three tables."""
    snap = snap if isinstance(snap, dict) else {}
    sessions = [([s.get("harness", ""), s.get("project", ""), s.get("branch", ""),
                  s.get("started_at", ""), s.get("last_activity", ""),
                  f"{float(s.get('cost_usd') or 0):.2f}", f"{s.get('context_pct') or 0}%",
                  ", ".join(s.get("risk_flags") or [])], False)
                for s in snap.get("sessions") or []]
    errors = [([n.get("seen_at", ""), n.get("detail", "")], False)
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
