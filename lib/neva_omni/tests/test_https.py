import os
import sys
import unittest
import urllib.error
import urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))  # test_sync, under any discovery top level
from neva_omni import sync
from test_sync import PACK, FakeOpener


class TransportSafetyTest(unittest.TestCase):
    def test_unsafe_base_urls_never_send_credentials(self):
        for url in ("http://omni.example.com", "https://user:secret@omni.example.com",
                    "https://omni.example.com/path", "https://omni.example.com?x=1",
                    "https://omni.example.com#fragment", "https://", "https://omni.example.com:bad"):
            with self.subTest(url=url):
                opener = FakeOpener()
                with self.assertRaisesRegex(ValueError, "url"):
                    sync.push_pack(url, "tok", PACK, opener=opener)
                self.assertEqual(opener.seen, [])

    def test_redirect_policy_blocks_other_origin_and_downgrade(self):
        handler = sync.SafeRedirectHandler()
        request = urllib.request.Request("https://omni.example.com/threads", headers={"Authorization": "Bearer tok"})
        for target in ("https://other.example.com/threads", "http://omni.example.com/threads",
                       "https://user:secret@omni.example.com/threads", "https://omni.example.com:444/threads", "https://omni.example.com:0/threads"):
            with self.subTest(target=target), self.assertRaises(urllib.error.URLError):
                handler.redirect_request(request, None, 302, "redirect", {}, target)
        redirected = handler.redirect_request(request, None, 302, "redirect", {}, "https://omni.example.com/next")
        self.assertEqual(redirected.get_header("Authorization"), "Bearer tok")
