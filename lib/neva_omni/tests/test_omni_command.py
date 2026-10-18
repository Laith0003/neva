import argparse, contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))  # test_sync, under any discovery top level
from neva_cli.commands import omni
from test_sync import PACK, FakeOpener

TOKEN_ENV = "NEVA_OMNI_TOKEN_FOR_TESTS"


class OmniPushCommandTest(unittest.TestCase):
    """Runs the real command with only the network opener replaced."""

    def _push(self, reply, pack=PACK, opener=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "brainpack.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(pack, f)
            args = argparse.Namespace(action="push", url="https://omni.example.com", pack=path,
                                      vault="", token_env=TOKEN_ENV)
            out = io.StringIO()
            with mock.patch.dict(os.environ, {TOKEN_ENV: "tok"}), \
                    mock.patch("urllib.request.build_opener", return_value=opener or FakeOpener(body=reply)), \
                    contextlib.redirect_stdout(out):
                code = omni.run(args)
        return code, out.getvalue()

    def test_a_confirmed_push_reports_the_acknowledged_tiers(self):
        code, out = self._push(b'{"stored": true, "generated_at": null, "tiers": {"small": 1}}')
        self.assertEqual(code, 0)
        self.assertIn("omni push: small 1 chars", out)

    def test_false_missing_and_wrong_shaped_acknowledgements_exit_nonzero(self):
        cases = [
            (b'{"stored": false, "tiers": {}}', "field stored"),
            (b'{}', "field stored"),
            (b'[]', "JSON object"),
            (b'{"stored": true, "tiers": {}}', "field tiers"),
            (b'{"stored": true, "tiers": {"small": 7}}', "field tiers"),
        ]
        for reply, field in cases:
            with self.subTest(reply=reply):
                code, out = self._push(reply)
                self.assertNotEqual(code, 0)
                self.assertIn(field, out)
                self.assertNotIn("chars ->", out)
                self.assertNotIn("reported no tiers", out)

    def test_push_lists_the_sources_and_the_providers_before_sending(self):
        pack = dict(PACK, sources=[{"path": "/notes/a.md", "bytes": 12}])
        code, out = self._push(b'{"stored": false}', pack=pack)
        self.assertNotEqual(code, 0)
        self.assertIn("/notes/a.md (12 bytes)", out)
        for name in ("workers-ai", "groq", "gemini"):
            self.assertIn(name, out)
        self.assertLess(out.index("/notes/a.md"), out.index("field stored"))

    def test_a_pack_that_does_not_list_its_sources_is_not_sent(self):
        for sources in (None, [], "x.md", [{"path": "x.md"}], [3]):
            with self.subTest(sources=sources):
                pack = {k: v for k, v in PACK.items() if k != "sources"}
                if sources is not None:
                    pack["sources"] = sources
                opener = FakeOpener()
                code, out = self._push(b"", pack=pack, opener=opener)
                self.assertEqual(code, 2)
                self.assertIn("field sources", out)
                self.assertIn("neva brainpack", out)
                self.assertEqual(opener.seen, [])


if __name__ == "__main__":
    unittest.main()
