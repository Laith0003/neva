import hashlib, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from neva_omni.brainpack import compile_pack, load_config, select_sources, PROVIDERS, TIERS
from unittest.mock import patch

class BrainPackTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.d = os.path.realpath(self.temporary.name)
        def w(name, text):
            p = os.path.join(self.d, name)
            with open(p, "w") as stream:
                stream.write(text)
            return p
        self.rules = [w("writing.md", "# Writing\n- No emojis.\n" * 50)]
        self.lessons = [w("l1.md", "---\nconfidence: 0.9\n---\n# Lesson\nDo the step yourself.\n")]
        self.taste = [w("taste.md", "# Taste\nOne accent.\n" * 400)]
        self.secret = [w("bad.md", "token sk-ant-" + "api03-ABCDEFGHIJKLMNOPQRSTUVWX0123456789\n")]

    def _tree(self, files):
        """Synthetic files under a fresh root; never real rules or vault notes."""
        root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root)
        for relative, text in files.items():
            path = os.path.join(root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(text)
        return root

    def test_default_pack_holds_no_rules_memory_or_taste(self):
        home = self._tree({
            ".claude/rules/writing.md": "# Writing\nsynthetic rule\n",
            ".claude/rules/confidentiality.md": "synthetic confidential rule\n",
            ".claude/skills/taste/SKILL.md": "synthetic taste\n",
            "vault/06 Memory/Claude Code/MEMORY.md": "synthetic memory index\n",
            "vault/06 Memory/instincts/global/one.md": "synthetic lesson\n",
        })
        with patch.dict(os.environ, {"HOME": home, "NEVA_VAULT": os.path.join(home, "vault")}):
            config = load_config(os.path.join(home, ".config", "neva", "omni.json"))
            self.assertEqual(config["include"], [])
            included, skipped = select_sources(config, home)
        self.assertEqual(included, [])
        self.assertEqual(skipped, [])

    def test_the_include_list_is_honoured_in_order(self):
        root = self._tree({
            "notes/b.md": "# B\nsecond note\n",
            "notes/a.md": "# A\nfirst note\n",
            "rules/kept.md": "# Kept\nlisted rule\n",
            "rules/other.md": "# Other\nunlisted rule\n",
        })
        config_file = os.path.join(root, "omni.json")
        with open(config_file, "w") as stream:
            stream.write('{"include": ["rules/kept.md", "notes/*.md"]}')
        included, skipped = select_sources(load_config(config_file), root)
        self.assertEqual(included, [os.path.join(root, "rules", "kept.md"),
                                    os.path.join(root, "notes", "a.md"),
                                    os.path.join(root, "notes", "b.md")])
        self.assertEqual(skipped, [])
        pack = compile_pack({"include": included}, TIERS)
        text = pack["tiers"]["large"]["text"]
        self.assertIn("listed rule", text)
        self.assertIn("first note", text)
        self.assertNotIn("unlisted rule", text)
        self.assertLess(text.index("listed rule"), text.index("first note"))
        self.assertEqual([source["path"] for source in pack["sources"]], included)
        for source in pack["sources"]:
            self.assertEqual(source["bytes"], os.path.getsize(source["path"]))

    def test_confidential_and_memory_files_need_an_exact_path(self):
        root = self._tree({
            "notes/plain.md": "plain\n",
            "notes/MEMORY.md": "memory index\n",
            "notes/Client (Confidential).md": "client note\n",
            "notes/confidential/deal.md": "deal note\n",
            "notes/Confidential Deals/upper.md": "upper note\n",
            "elsewhere/confidential/real.md": "behind a link\n",
        })
        os.symlink(os.path.join(root, "elsewhere", "confidential", "real.md"),
                   os.path.join(root, "notes", "linked.md"))
        included, skipped = select_sources({"include": ["notes/**/*.md"]}, root)
        self.assertEqual(included, [os.path.join(root, "notes", "plain.md")])
        names = sorted(os.path.relpath(path, root) for path, _ in skipped)
        self.assertEqual(names, ["notes/Client (Confidential).md", "notes/Confidential Deals/upper.md",
                                 "notes/MEMORY.md", "notes/confidential/deal.md", "notes/linked.md"])
        for _, reason in skipped:
            self.assertIn("exact path", reason)
        exact = ["notes/MEMORY.md", "notes/confidential/deal.md"]
        included, skipped = select_sources({"include": exact}, root)
        self.assertEqual(included, [os.path.join(root, p) for p in exact])
        self.assertEqual(skipped, [])

    def test_bad_config_and_bad_entries_name_the_field_and_the_fix(self):
        root = self._tree({"notes/a.md": "a\n", "omni.json": "{not json"})
        with self.assertRaisesRegex(ValueError, "omni.json.*not JSON"):
            load_config(os.path.join(root, "omni.json"))
        for body, field in (('{"include": "notes/a.md"}', "include"), ('{"include": [1]}', "include"),
                            ('[]', "JSON object")):
            with open(os.path.join(root, "omni.json"), "w") as stream:
                stream.write(body)
            with self.assertRaisesRegex(ValueError, field):
                load_config(os.path.join(root, "omni.json"))
        for entry, problem in (("notes/missing.md", "no such file"), ("notes/*.txt", "matched no files"),
                               ("notes", "directory")):
            with self.assertRaisesRegex(ValueError, problem) as caught:
                select_sources({"include": [entry]}, root)
            self.assertIn(entry, str(caught.exception))

    def test_provider_names_match_the_worker_registry(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        with open(os.path.join(root, "omni", "worker", "src", "providers.js")) as stream:
            registered = __import__("re").findall(r'(?m)^\s*\{ id: "([^"]+)", kind:', stream.read())
        self.assertTrue(registered)
        self.assertEqual(sorted(name for name, _ in PROVIDERS), sorted(registered))

    def test_public_source_rejects_personal_identifiers(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        forbidden = ((11, 'a544089189a721bc08a2863ac22d33146e0eadd5877b2c1553068d6243836906'), (13, '6abdb70cad3bdeef33df9a9ba16cc87359dc5c7c1b02d2719bd73cff3624fbf4'), (25, 'e8dbc659e933fa38f6124130ae6113689398e2f93b93b72a520b9835aad867a3'))
        def check(text):
            for width, digest in forbidden:
                for offset in range(len(text) - width + 1):
                    if hashlib.sha256(text[offset:offset + width].encode()).hexdigest() == digest:
                        raise ValueError("public source contains a personal identifier")
        with self.assertRaisesRegex(ValueError, "personal identifier"):
            check("synthetic forbidden label")
        for relative in ("lib/neva_omni/brainpack.py", "omni/worker/test/router.test.js"):
            with open(os.path.join(root, relative)) as stream:
                check(stream.read())

    def test_tiers_respect_caps_and_priority(self):
        pack = compile_pack({"rules": self.rules, "lessons": self.lessons, "taste": self.taste}, TIERS)
        for name, cap in TIERS.items():
            self.assertLessEqual(pack["tiers"][name]["chars"], cap)
        small = pack["tiers"]["small"]["text"]
        self.assertIn("No emojis", small)          # rules always first
        self.assertIn("Do the step yourself", small)  # lessons before taste

    def test_secret_shaped_text_is_rejected(self):
        with self.assertRaises(ValueError) as e:
            compile_pack({"rules": self.secret}, TIERS)
        self.assertIn("secret-shaped", str(e.exception))

# Built by concatenation so no full key shape sits in this file for the leak scan to flag.
def _samples():
    tail = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    return {
        "groq key": "gsk_" + tail,
        "google api key": "AIza" + "Sy" + tail[:33],
        "telegram bot token": "123456789" + ":AA" + tail[:33],
        "telegram bot URL": "https://api.telegram.org/bot" + "123456789" + ":AA" + tail[:33] + "/sendMessage",
        "anthropic key": "sk-ant-" + "api03-" + tail,
        "openai key": "sk-" + "proj-" + tail,
        "jwt": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "sig_" + tail[:20],
        "unsigned jwt": "eyJ" + "hbGciOiJub25lIn0" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + ".",
        "github token": "ghp_" + tail[:36],
        "github fine-grained token": "github_pat_" + tail[:30],
        "aws access key": "AKIA" + "ABCDEFGHIJKLMNOP",
        "aws session key": "ASIA" + "ABCDEFGHIJKLMNOP",
        "slack token": "xoxa" + "-1234567890-abcdef",
        "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }


# The leak scanner's own token patterns, each paired with a sample of that shape.
LEAK_SCAN_PARITY = {
    "bot-token-shaped": "telegram bot token", "private-key": "private key",
    "github-pat-shaped": "github fine-grained token", "aws-access-key-shaped": "aws session key",
    "openai-key-shaped": "openai key", "slack-token-shaped": "slack token", "jwt-shaped": "jwt",
}
NOT_SECRETS = {"phone-shaped", "email-shaped", "home-path"}


class SecretPatternTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.d = os.path.realpath(self.temporary.name)

    def _file(self, name, text):
        path = os.path.join(self.d, name)
        with open(path, "w") as stream:
            stream.write(text)
        return path

    def test_each_provider_key_shape_refuses_the_file_by_name(self):
        for label, sample in _samples().items():
            with self.subTest(label=label):
                path = self._file("note.md", "# Note\nkey: " + sample + "\nmore text\n")
                with self.assertRaises(ValueError) as caught:
                    compile_pack({"include": [path]}, TIERS)
                message = str(caught.exception)
                named = {"telegram bot URL": "telegram bot token", "unsigned jwt": "jwt", "openai key": "openai-style key", "aws session key": "aws access key",
                         "github fine-grained token": "github token"}.get(label, label)
                self.assertIn("secret-shaped text ({})".format(named), message)
                self.assertIn(path, message)
                self.assertNotIn(sample, message)

    def test_near_misses_are_not_refused(self):
        text = ("the gsk_ prefix, AIzaShort, 1234:AA short, sk-ant- alone, eyJ.eyJ.,"
                " ghp_ and AKIA mentioned in prose\n")
        pack = compile_pack({"include": [self._file("prose.md", text)]}, TIERS)
        self.assertIn("gsk_ prefix", pack["tiers"]["small"]["text"])

    def test_every_leak_scan_token_shape_is_also_refused(self):
        import importlib.util
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        spec = importlib.util.spec_from_file_location("leak_scan_for_tests", os.path.join(root, "build", "leak-scan.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        shapes = dict(module.TIER2)
        self.assertEqual(set(shapes) - NOT_SECRETS, set(LEAK_SCAN_PARITY),
                         "the leak scanner gained a token pattern: mirror it in brainpack.SECRETS")
        samples = _samples()
        for label, ours in LEAK_SCAN_PARITY.items():
            with self.subTest(label=label):
                sample = samples[ours]
                self.assertTrue(shapes[label].search(sample), "sample does not have the scanner's shape")
                with self.assertRaises(ValueError):
                    compile_pack({"include": [self._file("note.md", sample + "\n")]}, TIERS)


if __name__ == "__main__":
    unittest.main()
