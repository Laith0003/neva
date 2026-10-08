import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import web  # noqa: E402


def fake_snapshot():
    return {"sessions": [{"id": "s1", "project": "neva"}], "health": {"ok": True}}


class ServerLifecycle:
    """Starts web.CockpitServer on a background thread for the duration of a test."""

    def __init__(self, token="test-token-123"):
        self.server = web.make_server(host="127.0.0.1", port=0, token=token, snapshot_fn=fake_snapshot)
        self.token = self.server.token
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    @property
    def base_url(self):
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.getcode(), response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        finally:
            error.close()


class BindRestrictionTests(unittest.TestCase):
    def test_binding_0_0_0_0_raises_instead_of_silently_rewriting(self):
        with self.assertRaises(ValueError):
            web.make_server(host="0.0.0.0", port=0, token="x", snapshot_fn=fake_snapshot)

    def test_binding_a_hostname_other_than_127_0_0_1_raises(self):
        with self.assertRaises(ValueError):
            web.make_server(host="localhost", port=0, token="x", snapshot_fn=fake_snapshot)

    def test_binding_127_0_0_1_is_accepted(self):
        server = web.make_server(host="127.0.0.1", port=0, token="x", snapshot_fn=fake_snapshot)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()


class TokenAuthTests(unittest.TestCase):
    def test_request_without_token_gets_404_and_no_data(self):
        with ServerLifecycle() as srv:
            code, body = get(f"{srv.base_url}/api/snapshot")
            self.assertIn(code, (403, 404))
            self.assertNotIn(b"neva", body)

    def test_request_with_wrong_token_gets_404_and_no_data(self):
        with ServerLifecycle() as srv:
            code, body = get(f"{srv.base_url}/not-the-token/api/snapshot")
            self.assertIn(code, (403, 404))
            self.assertNotIn(b"neva", body)

    def test_request_with_correct_token_returns_the_snapshot(self):
        with ServerLifecycle() as srv:
            code, body = get(f"{srv.base_url}/{srv.token}/api/snapshot")
            self.assertEqual(code, 200)
            data = json.loads(body)
            self.assertEqual(data["sessions"][0]["id"], "s1")

    def test_html_page_served_at_token_root(self):
        with ServerLifecycle() as srv:
            code, body = get(f"{srv.base_url}/{srv.token}/")
            self.assertEqual(code, 200)
            self.assertIn(b"<html", body.lower())

    def test_page_renders_health_and_hook_errors_escaped(self):
        """Review M3: the page rendered only sessions; health and hook errors were dropped."""
        snap = {"sessions": [{"id": "s1", "project": "neva"}],
                "health_rows": [{"name": "omniroute", "ok": False,
                                 "detail": "OmniRoute at x timed out after 3s"}],
                "hook_errors": [{"detail": "[error] <script>alert(1)</script>", "seen_at": "t"}]}
        server = web.make_server(host="127.0.0.1", port=0, token="tok", snapshot_fn=lambda: snap)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            code, body = get(f"http://{host}:{port}/tok/")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        page = body.decode("utf-8")
        self.assertEqual(code, 200)
        self.assertIn("OmniRoute at x timed out after 3s", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn('id="health"', page)
        self.assertIn('id="hook-errors"', page)

    def test_correct_token_but_unknown_subpath_gets_404(self):
        with ServerLifecycle() as srv:
            code, body = get(f"{srv.base_url}/{srv.token}/../etc/passwd")
            self.assertIn(code, (403, 404))


if __name__ == "__main__":
    unittest.main()
