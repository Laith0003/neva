import datetime, io, json, os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from neva_omni.sync import _thread_path, build_request, load_pack, push_pack, sync_threads, thread_markdown

PACK = {"version": 1, "generated_at": "2026-10-05T00:00:00+00:00",
        "tiers": {"small": {"text": "a", "chars": 1}}, "sources": [{"path": "x.md", "bytes": 1}]}

UPDATED_AT_MS = 1759708800000
THREAD_DATE = datetime.datetime.fromtimestamp(UPDATED_AT_MS / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")

THREAD = {
    "id": "t1",
    "title": "Plan the omni sync",
    "updated_at": UPDATED_AT_MS,
    "messages": [
        {"role": "user", "content": "كيف نزامن المحادثات؟", "model": None, "created_at": 1},
        {"role": "assistant", "content": "نزامنها عبر sync_threads.", "model": "groq:llama-3.1-8b", "created_at": 2},
        {"role": "assistant", "content": "تفصيل إضافي من نموذج آخر.", "model": "workers-ai:llama-3.1-70b", "created_at": 3},
    ],
}


class FakeOpener:
    """Stands in for urllib's opener so no test ever opens a socket."""

    def __init__(self, body=b'{"stored": true, "tiers": {"small": 1}}', error=None):
        self.body, self.error, self.seen = body, error, []

    def open(self, request, timeout=None):
        self.seen.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(self.body)


class BuildRequestTest(unittest.TestCase):
    def test_puts_the_pack_to_the_brainpack_endpoint(self):
        r = build_request("https://omni.example.com", "tok", PACK)
        self.assertEqual(r.get_method(), "PUT")
        self.assertEqual(r.full_url, "https://omni.example.com/brainpack")
        self.assertEqual(r.get_header("Authorization"), "Bearer tok")
        self.assertEqual(r.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(r.data)["tiers"]["small"]["chars"], 1)

    def test_a_trailing_slash_does_not_double_up(self):
        self.assertEqual(build_request("https://omni.example.com/", "tok", PACK).full_url,
                         "https://omni.example.com/brainpack")


class PushPackTest(unittest.TestCase):
    def test_returns_what_the_worker_answered(self):
        opener = FakeOpener()
        self.assertEqual(push_pack("https://omni.example.com", "tok", PACK, opener=opener),
                         {"stored": True, "tiers": {"small": 1}})
        self.assertEqual(len(opener.seen), 1)

    def test_an_acknowledgement_that_does_not_confirm_the_sent_tiers_is_a_failure(self):
        cases = [
            (b'{"stored": false, "tiers": {}}', "field stored"),
            (b'{"stored": false, "tiers": {"small": 1}}', "field stored"),
            (b'{}', "field stored"),
            (b'{"stored": "true", "tiers": {"small": 1}}', "field stored"),
            (b'[]', "JSON object"),
            (b'"ok"', "JSON object"),
            (b'null', "JSON object"),
            (b'{"stored": true}', "field tiers"),
            (b'{"stored": true, "tiers": []}', "field tiers"),
            (b'{"stored": true, "tiers": {}}', "field tiers"),
            (b'{"stored": true, "tiers": {"small": 2}}', "field tiers"),
            (b'{"stored": true, "tiers": {"small": 1, "large": 1}}', "field tiers"),
        ]
        for body, field in cases:
            with self.subTest(body=body):
                with self.assertRaises(RuntimeError) as e:
                    push_pack("https://omni.example.com", "tok", PACK, opener=FakeOpener(body=body))
                self.assertIn(field, str(e.exception))
                self.assertIn("omni.example.com", str(e.exception))

    def test_an_empty_url_names_the_flag_and_the_variable(self):
        with self.assertRaises(ValueError) as e:
            push_pack("", "tok", PACK, opener=FakeOpener())
        self.assertIn("--url", str(e.exception))
        self.assertIn("NEVA_OMNI_URL", str(e.exception))

    def test_an_empty_token_names_the_variable_and_the_worker_secret(self):
        with self.assertRaises(ValueError) as e:
            push_pack("https://omni.example.com", "", PACK, opener=FakeOpener())
        self.assertIn("NEVA_OMNI_TOKEN", str(e.exception))
        self.assertIn("DEVICE_TOKEN", str(e.exception))

    def test_a_pack_with_no_tiers_is_refused_before_the_request(self):
        opener = FakeOpener()
        with self.assertRaises(ValueError) as e:
            push_pack("https://omni.example.com", "tok", {"version": 1}, opener=opener)
        self.assertIn("neva brainpack", str(e.exception))
        self.assertEqual(opener.seen, [], "a pack with no tiers was still sent")

    def test_a_401_tells_the_user_which_two_values_must_match(self):
        err = urllib.error.HTTPError("https://omni.example.com/brainpack", 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error": "sign in"}'))
        with self.assertRaises(RuntimeError) as e:
            push_pack("https://omni.example.com", "tok", PACK, opener=FakeOpener(error=err))
        self.assertIn("401", str(e.exception))
        self.assertIn("DEVICE_TOKEN", str(e.exception))

    def test_an_unreachable_worker_is_reported_as_a_failure_not_an_empty_result(self):
        err = urllib.error.URLError("name or service not known")
        with self.assertRaises(RuntimeError) as e:
            push_pack("https://omni.example.com", "tok", PACK, opener=FakeOpener(error=err))
        self.assertIn("omni.example.com", str(e.exception))

    def test_a_reply_that_is_not_json_is_an_error_naming_what_came_back(self):
        with self.assertRaises(RuntimeError) as e:
            push_pack("https://omni.example.com", "tok", PACK, opener=FakeOpener(body=b"<html>502</html>"))
        self.assertIn("not JSON", str(e.exception))


class LoadPackTest(unittest.TestCase):
    def test_reads_a_compiled_pack(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "brainpack.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(PACK, f)
        self.assertEqual(load_pack(p)["tiers"]["small"]["chars"], 1)

    def test_a_missing_pack_names_the_command_that_makes_one(self):
        with self.assertRaises(FileNotFoundError) as e:
            load_pack(os.path.join(tempfile.mkdtemp(), "nope.json"))
        self.assertIn("neva brainpack", str(e.exception))


class ThreadFakeOpener:
    """Stands in for urllib's opener, routing GET /threads and GET /threads/:id by URL."""

    def __init__(self, threads_body, thread_bodies):
        self.threads_body, self.thread_bodies, self.seen = threads_body, thread_bodies, []

    def open(self, request, timeout=None):
        self.seen.append(request)
        url = request.full_url
        if url.endswith("/threads"):
            return io.BytesIO(self.threads_body)
        for tid, body in self.thread_bodies.items():
            if url.endswith(f"/threads/{tid}"):
                return io.BytesIO(body)
        raise AssertionError(f"unexpected request to {url}")


class ThreadMarkdownTest(unittest.TestCase):
    def test_thread_markdown_keeps_the_model_per_turn_and_keeps_arabic_intact(self):
        md = thread_markdown(THREAD)
        self.assertIn("tags: [content, conversation]", md)
        self.assertIn("### assistant (groq:llama-3.1-8b)", md)
        self.assertIn("### assistant (workers-ai:llama-3.1-70b)", md)
        self.assertIn("كيف نزامن المحادثات؟", md)
        self.assertIn("نزامنها عبر sync_threads.", md)
        self.assertIn("تفصيل إضافي من نموذج آخر.", md)


class SyncThreadsTest(unittest.TestCase):
    def _opener(self):
        threads_body = json.dumps({"threads": [{"id": "t1", "title": THREAD["title"], "updated_at": UPDATED_AT_MS}]}).encode("utf-8")
        thread_body = json.dumps(THREAD, ensure_ascii=False).encode("utf-8")
        return ThreadFakeOpener(threads_body, {"t1": thread_body})

    def test_writes_one_note_per_thread_and_is_idempotent_on_a_second_run(self):
        vault = os.path.join(os.path.realpath(tempfile.mkdtemp()), "Vault")
        expected = _thread_path(vault, THREAD)

        written = sync_threads("https://omni.example.com", "tok", vault, opener=self._opener())
        self.assertEqual(written, [expected])
        self.assertTrue(os.path.exists(expected))
        with open(expected, encoding="utf-8") as f:
            first = f.read()

        written2 = sync_threads("https://omni.example.com", "tok", vault, opener=self._opener())
        self.assertEqual(written2, [expected])
        with open(expected, encoding="utf-8") as f:
            second = f.read()
        self.assertEqual(first, second)

        files = os.listdir(os.path.dirname(expected))
        self.assertEqual(files, [os.path.basename(expected)], "a second run must not create a duplicate note")

    def test_symlink_leaf_and_parent_preserve_target(self):
        for component in ("leaf", "parent", "root"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as temporary:
                base = os.path.realpath(temporary)
                vault = os.path.join(base, "Vault")
                outside = os.path.join(base, "outside")
                os.mkdir(outside)
                target = os.path.join(outside, "owner.md")
                with open(target, "w") as f:
                    f.write("owner bytes")
                notes = os.path.join(vault, "06 Memory", "Conversations")
                if component == "root":
                    os.symlink(outside, vault)
                else:
                    os.makedirs(os.path.dirname(notes))
                    if component == "parent":
                        os.symlink(outside, notes)
                    else:
                        os.mkdir(notes)
                        os.symlink(target, _thread_path(vault, THREAD))
                with self.assertRaisesRegex(ValueError, "symlink"):
                    sync_threads("https://omni.example.com", "tok", vault, opener=self._opener())
                with open(target) as f:
                    self.assertEqual(f.read(), "owner bytes")
                self.assertEqual(os.listdir(outside), ["owner.md"])

    def test_stable_ids_preserve_collisions_dates_and_owner_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = os.path.realpath(temporary)
            other = dict(THREAD, id="t2")
            opener = ThreadFakeOpener(json.dumps({"threads": [{"id": "t1"}, {"id": "t2"}]}).encode(),
                                      {"t1": json.dumps(THREAD).encode(), "t2": json.dumps(other).encode()})
            paths = sync_threads("https://omni.example.com", "tok", vault, opener=opener)
            self.assertEqual(len(set(paths)), 2)
            later = dict(THREAD, updated_at=UPDATED_AT_MS + 86400000, title="Changed title")
            opener = ThreadFakeOpener(b'{"threads":[{"id":"t1"}]}', {"t1": json.dumps(later).encode()})
            self.assertEqual(sync_threads("https://omni.example.com", "tok", vault, opener=opener), [paths[0]])
            with open(paths[0], "w") as stream:
                stream.write("owner bytes")
            with self.assertRaisesRegex(ValueError, "ownership"):
                sync_threads("https://omni.example.com", "tok", vault, opener=self._opener())
            with open(paths[0]) as stream:
                self.assertEqual(stream.read(), "owner bytes")

    def test_invalid_response_shapes_preserve_existing_note(self):
        cases = [({}, THREAD, "threads"), ({"threads": [{}]}, THREAD, "id"),
                 ({"threads": [{"id": "t1"}]}, dict(THREAD, id="other"), "id"),
                 ({"threads": [{"id": "t1"}]}, {"id": "t1"}, "messages"),
                 ({"threads": [{"id": "t1"}]}, dict(THREAD, messages=[{"role": "user"}]), "content")]
        with tempfile.TemporaryDirectory() as temporary:
            vault = os.path.realpath(temporary)
            path = sync_threads("https://omni.example.com", "tok", vault, opener=self._opener())[0]
            with open(path, "rb") as stream:
                original = stream.read()
            for index, thread, field in cases:
                with self.subTest(field=field):
                    opener = ThreadFakeOpener(json.dumps(index).encode(), {"t1": json.dumps(thread).encode()})
                    with self.assertRaisesRegex(ValueError, field):
                        sync_threads("https://omni.example.com", "tok", vault, opener=opener)
                    with open(path, "rb") as stream:
                        self.assertEqual(stream.read(), original)

    def test_an_empty_vault_names_the_flag_and_the_variable(self):
        with self.assertRaises(ValueError) as e:
            sync_threads("https://omni.example.com", "tok", "", opener=self._opener())
        self.assertIn("--vault", str(e.exception))
        self.assertIn("NEVA_VAULT", str(e.exception))


if __name__ == "__main__":
    unittest.main()
