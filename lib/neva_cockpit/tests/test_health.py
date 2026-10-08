import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import health, hooks_common  # noqa: E402

LAUNCHCTL_OUT = ("PID\tStatus\tLabel\n"
                 "-\t0\tcom.neva.cadence\n"
                 "123\t0\tcom.example.private-job\n"
                 "-\t78\tcom.apple.something\n")


class JobPrefixTests(unittest.TestCase):
    """Review H8: the default namespace is Neva's own; anything else comes from local config."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "identity.env")
        patcher = mock.patch.dict(os.environ, {"NEVA_CONFIG": self.config})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("NEVA_COCKPIT_JOB_PREFIXES", None)
        hooks_common.load_config.cache_clear()
        self.addCleanup(hooks_common.load_config.cache_clear)
        self.addCleanup(self.tmp.cleanup)

    def test_default_is_the_neva_namespace_only(self):
        self.assertEqual(health.job_prefixes(), ("com.neva.",))

    def test_env_adds_local_prefixes(self):
        with mock.patch.dict(os.environ, {"NEVA_COCKPIT_JOB_PREFIXES": "com.example., org.x."}):
            self.assertEqual(health.job_prefixes(), ("com.neva.", "com.example.", "org.x."))

    def test_identity_file_adds_local_prefixes(self):
        with open(self.config, "w", encoding="utf-8") as fh:
            fh.write('COCKPIT_JOB_PREFIXES="com.example."\n')
        self.assertEqual(health.job_prefixes(), ("com.neva.", "com.example."))

    def _probe(self):
        fake = subprocess.CompletedProcess(["launchctl", "list"], 0, LAUNCHCTL_OUT, "")
        with mock.patch.object(health.sys, "platform", "darwin"), \
             mock.patch.object(health.shutil, "which", return_value="/bin/launchctl"), \
             mock.patch.object(health.subprocess, "run", return_value=fake):
            return [job["label"] for job in health.scheduled_jobs()["jobs"]]

    def test_scheduled_jobs_shows_only_neva_jobs_by_default(self):
        self.assertEqual(self._probe(), ["com.neva.cadence"])

    def test_scheduled_jobs_includes_a_configured_prefix(self):
        with mock.patch.dict(os.environ, {"NEVA_COCKPIT_JOB_PREFIXES": "com.example."}):
            self.assertEqual(self._probe(), ["com.neva.cadence", "com.example.private-job"])


class OmniRouteKeyTests(unittest.TestCase):
    """Review M7: a malformed key file raised ValueError with the whole header in it."""

    SECRET = "fixture-secret"

    def probe(self, key_text):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "neva-builder.key")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(key_text)
            with mock.patch.object(health.urllib.request, "urlopen",
                                   side_effect=AssertionError("must not send a bad key")):
                return health.omniroute_health(url="http://127.0.0.1:9/v1/models",
                                               key_path=path)

    def assert_rejected_without_leaking(self, key_text):
        try:
            result = self.probe(key_text)
        except Exception as error:  # noqa: BLE001
            self.fail(f"probe raised {type(error).__name__}; leaked: {self.SECRET in str(error)}")
        self.assertFalse(result["ok"])
        self.assertNotIn(self.SECRET, repr(result))
        self.assertIn("fix:", result["detail"])

    def test_embedded_newline(self):
        self.assert_rejected_without_leaking(self.SECRET + "\nextra-line\n")

    def test_non_ascii(self):
        self.assert_rejected_without_leaking(self.SECRET + "-\u20ac")

    def test_transport_error_detail_never_carries_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "neva-builder.key")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.SECRET + "\n")
            boom = ValueError("Invalid header value b'Bearer " + self.SECRET + "'")
            with mock.patch.object(health.urllib.request, "urlopen", side_effect=boom):
                result = health.omniroute_health(url="http://127.0.0.1:9/v1/models",
                                                 key_path=path)
        self.assertFalse(result["ok"])
        self.assertNotIn(self.SECRET, repr(result))


class NightlyLogTests(unittest.TestCase):
    """Review L2: an unreadable log was reported as a missing start marker."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "instinct-analyze.log")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[2026-10-08 03:30] start (nightly)\n[2026-10-08 03:31] done\n")

    def test_a_readable_log_reports_the_finished_run(self):
        result = health.last_nightly_result(self.path)
        self.assertTrue(result["ok"], result)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode 000 files")
    def test_an_unreadable_log_names_the_file_and_the_fix(self):
        os.chmod(self.path, 0)
        self.addCleanup(os.chmod, self.path, 0o600)
        result = health.last_nightly_result(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("unreadable", result["detail"])
        self.assertIn(self.path, result["detail"])
        self.assertIn("fix:", result["detail"])
        self.assertNotIn("no start marker", result["detail"])


if __name__ == "__main__":
    unittest.main()
