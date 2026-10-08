# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Primitives: path expansion, the small TOML reader and writer, backups, dotted keys."""
import os
import unittest
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox


class TestPaths(Sandbox):
    def test_data_dir_defaults_under_home(self):
        os.environ.pop("NEVA_DATA_DIR")
        self.assertEqual(core.data_dir(), self.home / ".local" / "share" / "neva")
        self.assertEqual(core.state_path().name, "install-state.json")

    def test_tilde_and_variables_expand(self):
        self.env({"NEVA_TEST_TARGET": str(self.home / "target")})
        self.assertEqual(core.expand_destination("~/.config/x"), self.home / ".config" / "x")
        self.assertEqual(core.expand_destination("${NEVA_TEST_TARGET}/y"), self.home / "target" / "y")

    def test_unset_variable_is_an_error_that_names_the_fix(self):
        with self.assertRaises(core.AdapterError) as caught:
            core.expand_destination("${NEVA_DEFINITELY_UNSET_VAR}/x")
        self.assertIn("fix:", str(caught.exception))

    def test_relative_and_traversing_destinations_are_refused(self):
        for raw in ("relative/path", "~/.config/../../escape"):
            with self.assertRaises(core.AdapterError, msg=raw):
                core.expand_destination(raw)

    def test_symlink_destination_outside_home_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.home / "link"
        link.symlink_to(outside)
        with self.assertRaises(core.AdapterError) as caught:
            core.expand_destination("~/link/something")
        self.assertIn("fix:", str(caught.exception))
        self.assertIn("HOME", str(caught.exception).upper())

    def test_symlink_destination_with_dotdot_outside_home_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.home / "link"
        link.symlink_to(outside)
        with self.assertRaises(core.AdapterError) as caught:
            core.expand_destination("~/link/../escape")
        self.assertIn("fix:", str(caught.exception))
        self.assertIn("HOME", str(caught.exception).upper())


class TestToml(unittest.TestCase):
    def test_reads_tables_scalars_and_arrays(self):
        parsed = core.parse_toml(
            'title = "neva"\n'
            "count = 3\n"
            "ratio = 1.5\n"
            "enabled = true\n"
            "names = [\"a\", \"b\"]\n"
            "\n"
            "[tool.neva]\n"
            "profile = 'standard'\n"
        )
        self.assertEqual(parsed["title"], "neva")
        self.assertEqual(parsed["count"], 3)
        self.assertEqual(parsed["ratio"], 1.5)
        self.assertIs(parsed["enabled"], True)
        self.assertEqual(parsed["names"], ["a", "b"])
        self.assertEqual(parsed["tool"]["neva"]["profile"], "standard")

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        parsed = core.parse_toml('tag = "release #7"  # a real comment\n')
        self.assertEqual(parsed["tag"], "release #7")

    def test_a_comma_inside_a_string_does_not_split_an_array(self):
        parsed = core.parse_toml('items = ["a,b", "c"]\n')
        self.assertEqual(parsed["items"], ["a,b", "c"])

    def test_round_trip_through_write_toml(self):
        import tempfile
        original = {"root": "yes", "tool": {"neva": {"profile": "strict", "limit": 4}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            core.write_toml(path, original)
            self.assertEqual(core.read_toml(path), original)

    def test_array_of_tables_is_refused_with_a_fix(self):
        with self.assertRaises(ValueError) as caught:
            core.parse_toml("[[servers]]\nname = \"a\"\n")
        self.assertIn("fix:", str(caught.exception))

    def test_an_unsupported_value_names_what_is_supported(self):
        with self.assertRaises(ValueError) as caught:
            core.parse_toml("when = 1979-05-27T07:32:00Z\n")
        self.assertIn("fix:", str(caught.exception))

    def test_read_toml_of_a_missing_file_is_empty(self):
        self.assertEqual(core.read_toml("/nonexistent/neva/config.toml"), {})


try:
    import tomllib
except ImportError:  # Python before 3.11: the standards check below is skipped, never faked
    tomllib = None

#: Documents whose meaning depends on key quoting. tomllib is the reference reading of each.
QUOTED_KEYS = [
    '"model.name" = "gpt"\n',
    "'literal.key' = 1\n",
    '"has space" = true\n',
    'a.b = 1\n',
    'plain = 1\n[tool."x.y"]\nz = 2\n',
    '[tool]\n"dotted.inside" = "v"\nsub.leaf = 3\n',
    '"equals=sign" = "x"\n',
    '"" = "empty key"\n',
]


def write_and_read_text(value):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.toml"
        core.write_toml(path, value)
        return path.read_text(encoding="utf-8")


@unittest.skipIf(tomllib is None, "tomllib needs Python 3.11 or later")
class TestTomlAgainstTheStandard(unittest.TestCase):
    """Neva's reader and writer must agree with a standards-compliant parser, not with itself."""

    def test_the_reader_agrees_with_tomllib_on_quoted_and_dotted_keys(self):
        for document in QUOTED_KEYS:
            with self.subTest(document=document):
                self.assertEqual(core.parse_toml(document), tomllib.loads(document))

    def test_the_writer_output_means_the_same_to_tomllib(self):
        for document in QUOTED_KEYS:
            with self.subTest(document=document):
                value = tomllib.loads(document)
                self.assertEqual(tomllib.loads(write_and_read_text(value)), value)

    def test_a_quoted_literal_key_is_not_rewritten_as_a_dotted_key(self):
        text = write_and_read_text({"model.name": "gpt"})
        self.assertEqual(tomllib.loads(text), {"model.name": "gpt"})
        self.assertNotIn("\nmodel.name =", "\n" + text)

    def test_strings_outside_the_basic_plane_stay_valid_toml(self):
        value = {"clef": "\U0001D11E", "arabic": "\u0646\u064a\u0641\u0627"}
        self.assertEqual(tomllib.loads(write_and_read_text(value)), value)

    def test_negative_control_tomllib_reads_a_dotted_key_as_nesting(self):
        # Proves the comparisons above can fail: the two spellings really do differ.
        self.assertNotEqual(tomllib.loads('"model.name" = 1\n'), tomllib.loads("model.name = 1\n"))


class TestTomlMergeKeepsQuotedKeys(Sandbox):
    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11 or later")
    def test_a_merge_leaves_a_quoted_key_meaning_what_it_meant(self):
        from neva_cli.tests.test_install import SOURCES, adapter
        self.write_adapter("codex", adapter(), SOURCES)
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('"model.name" = "gpt"\n"my key" = 1\n', encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        merged = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(merged["model.name"], "gpt")
        self.assertEqual(merged["my key"], 1)
        self.assertNotIn("model", merged, "a quoted key was rewritten as a nested table")
        self.assertEqual(merged["tool"]["neva"]["profile"], "standard")

    def test_an_unsupported_key_is_refused_before_the_file_is_touched(self):
        from neva_cli.tests.test_install import SOURCES, adapter
        self.write_adapter("codex", adapter(), SOURCES)
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        original = 'bad key = 1\n'
        config.write_text(original, encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn(str(config), output)
        self.assertEqual(config.read_text(encoding="utf-8"), original)


#: Documents tomllib rejects. Neva's reader must reject each one too, never pick a winner.
INVALID_TOML = [
    'model = "a"\nmodel = "b"\n',
    '[tool]\nx = 1\n[tool]\ny = 2\n',
    'a.b = 1\na.b = 2\n',
    '[a]\nb = 1\n\n[a.b]\nc = 2\n',
]

#: Valid TOML that Neva cannot round-trip, so it must refuse rather than rewrite it.
UNSUPPORTED_TOML = [
    "p = \'\'\'abc\'\'\'\n",
    'p = """abc"""\n',
    'p = """\nline one\nline two"""\n',
]


class TestTomlRefusesWhatItCannotRoundTrip(unittest.TestCase):
    def test_duplicates_are_refused_like_tomllib_refuses_them(self):
        for document in INVALID_TOML:
            with self.subTest(document=document):
                if tomllib is not None:
                    with self.assertRaises(tomllib.TOMLDecodeError):
                        tomllib.loads(document)
                with self.assertRaises(ValueError) as caught:
                    core.parse_toml(document)
                self.assertIn("line", str(caught.exception))
                self.assertIn("fix:", str(caught.exception))

    def test_multiline_strings_are_refused_by_name(self):
        for document in UNSUPPORTED_TOML:
            with self.subTest(document=document):
                with self.assertRaises(ValueError) as caught:
                    core.parse_toml(document)
                self.assertIn("fix:", str(caught.exception))

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11 or later")
    def test_negative_control_the_valid_neighbours_still_parse_like_tomllib(self):
        for document in ('[a]\nb = 1\n[a.c]\nd = 2\n', 'x = "a"\ny = "b"\n', "p = 'abc'\n"):
            with self.subTest(document=document):
                self.assertEqual(core.parse_toml(document), tomllib.loads(document))


class TestTomlMergePreservesOrRefuses(Sandbox):
    """A TOML merge keeps every byte it does not own, comments included, or refuses."""

    def setUp(self):
        super().setUp()
        from neva_cli.tests.test_install import SOURCES, adapter
        only_toml = [entry for entry in adapter()["entries"] if entry["mode"] == "merge-toml"]
        self.write_adapter("codex", adapter(entries=only_toml, post=[]), SOURCES)
        self.config = self.home / ".codex" / "config.toml"
        self.config.parent.mkdir(parents=True)

    def test_invalid_or_unsupported_toml_is_refused_and_left_alone(self):
        for document in INVALID_TOML + UNSUPPORTED_TOML:
            with self.subTest(document=document):
                self.config.write_text(document, encoding="utf-8")
                code, output = self.install(harness="codex")
                self.assertEqual(code, 1, output)
                self.assertIn(str(self.config), output)
                self.assertEqual(self.config.read_text(encoding="utf-8"), document)

    def test_comments_survive_install_and_uninstall_byte_for_byte(self):
        original = '# keep this comment\nmodel = "a" # why a\n\n[tool.other]\nkeep = true # mine\n'
        self.config.write_text(original, encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        text = self.config.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(original), "install rewrote the lines it does not own")
        if tomllib is not None:
            self.assertEqual(tomllib.loads(text)["tool"]["neva"], {"profile": "standard", "hooks": True})
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_an_edit_made_while_installed_keeps_the_comments_on_uninstall(self):
        original = '# keep this comment\nmodel = "a"\n'
        self.config.write_text(original, encoding="utf-8")
        self.install(harness="codex")
        self.config.write_text(self.config.read_text(encoding="utf-8") + "\n[later]\nmine = 1\n",
                               encoding="utf-8")
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.config.read_text(encoding="utf-8"),
                         original + "\n[later]\nmine = 1\n")

    def test_a_merge_that_would_drop_comments_is_refused(self):
        # tool.neva already exists, so Neva would have to rewrite the file; the comment forbids it.
        original = '# keep this comment\n[tool.neva]\nprofile = "mine"\n'
        self.config.write_text(original, encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("comment", output)
        self.assertIn("fix:", output)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_negative_control_a_file_without_comments_may_still_be_rewritten(self):
        self.config.write_text('[tool.neva]\nprofile = "mine"\n', encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.uninstall(harness="codex")
        self.assertEqual(core.read_toml(self.config), {"tool": {"neva": {"profile": "mine"}}})


class TestDottedKeys(unittest.TestCase):
    def test_missing_parents_reports_only_what_is_absent(self):
        self.assertEqual(core.missing_parents({}, "env.NEVA_PLUGINS"), ["env"])
        self.assertEqual(core.missing_parents({"env": {}}, "env.NEVA_PLUGINS"), [])
        self.assertEqual(core.missing_parents({}, "a.b.c"), ["a", "a.b"])

    def test_prune_keys_removes_only_empty_containers(self):
        data = {"env": {}, "other": {"keep": 1}}
        core.prune_keys(data, ["env", "other"])
        self.assertEqual(data, {"other": {"keep": 1}})

    def test_lookup_distinguishes_absent_from_none(self):
        self.assertIs(core.lookup({"a": None}, "a", core.MISSING), None)
        self.assertIs(core.lookup({}, "a", core.MISSING), core.MISSING)


class TestBackups(Sandbox):
    def test_a_file_is_restored_byte_for_byte(self):
        target = self.home / "notes.md"
        target.write_text("original\n", encoding="utf-8")
        saved = core.backup(target)
        target.write_text("clobbered\n", encoding="utf-8")
        self.assertTrue(core.restore_backup(target, saved))
        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_a_symlink_is_restored_as_a_symlink(self):
        link = self.home / "link"
        os.symlink("/home/user/elsewhere", link)
        saved = core.backup(link)
        link.unlink()
        self.assertTrue(core.restore_backup(link, saved))
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "/home/user/elsewhere")

    def test_a_file_whose_text_looks_like_a_symlink_marker_stays_a_file(self):
        # A previous version tagged symlink backups with a SYMLINK: prefix inside the file, so a
        # real file starting with that text came back as a broken symlink. The marker is the
        # backup's .symlink suffix now, which no file content can forge.
        target = self.home / "tricky.txt"
        target.write_text("SYMLINK:/home/user/evil\n", encoding="utf-8")
        saved = core.backup(target)
        target.unlink()
        self.assertTrue(core.restore_backup(target, saved))
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "SYMLINK:/home/user/evil\n")

    def test_two_backups_of_one_path_do_not_collide(self):
        target = self.home / "notes.md"
        target.write_text("first\n", encoding="utf-8")
        first = core.backup(target)
        target.write_text("second\n", encoding="utf-8")
        second = core.backup(target)
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_text(encoding="utf-8"), "first\n")

    def test_backing_up_a_missing_path_returns_none(self):
        self.assertIsNone(core.backup(self.home / "never-existed"))


class TestAdapterContracts(Sandbox):
    def test_a_missing_adapter_is_reported_as_absent_not_broken(self):
        contract, path = core.read_adapter("codex")
        self.assertIsNone(contract)
        self.assertEqual(path, self.adapters / "codex" / "install.json")

    def test_invalid_json_names_the_file_and_the_fix(self):
        self.write_adapter("codex", {})
        (self.adapters / "codex" / "install.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(core.AdapterError) as caught:
            core.read_adapter("codex")
        self.assertIn("install.json", str(caught.exception))
        self.assertIn("fix:", str(caught.exception))

    def test_an_unknown_mode_is_refused_before_anything_is_written(self):
        self.write_adapter("codex", {"harness": "codex",
                                     "entries": [{"src": "a", "dest": "~/a", "mode": "teleport"}]})
        with self.assertRaises(core.AdapterError) as caught:
            core.read_adapter("codex")
        self.assertIn("teleport", str(caught.exception))

    def test_an_append_block_entry_without_a_key_is_refused(self):
        self.write_adapter("codex", {"entries": [{"src": "a", "dest": "~/a", "mode": "append-block"}]})
        with self.assertRaises(core.AdapterError) as caught:
            core.read_adapter("codex")
        self.assertIn("key", str(caught.exception))

    def test_a_harness_name_that_contradicts_its_directory_is_refused(self):
        self.write_adapter("codex", {"harness": "opencode", "entries": []})
        with self.assertRaises(core.AdapterError):
            core.read_adapter("codex")

    def test_detection_uses_binaries_then_paths(self):
        contract = {"harness": "codex", "detect": {"binaries": ["codex"], "paths": []}, "entries": []}
        self.assertTrue(core.detected(contract))
        self.hide("codex")
        self.assertFalse(core.detected(contract))
        contract["detect"]["paths"] = ["~/.codex"]
        self.assertFalse(core.detected(contract))
        (self.home / ".codex").mkdir()
        self.assertTrue(core.detected(contract))


class TestPruneEmptyParents(Sandbox):
    def test_prune_stops_at_boundary(self):
        nested = self.home / "a" / "b" / "c"
        nested.mkdir(parents=True)
        core.prune_empty_parents(nested, boundary=self.home)
        self.assertTrue((self.home / "a").exists())
        self.assertTrue((self.home / "a" / "b").exists())
        self.assertTrue((self.home / "a" / "b" / "c").exists())

    def test_prune_removes_empty_parents_inside_boundary(self):
        nested = self.home / "a" / "b" / "c"
        nested.mkdir(parents=True)
        nested.rmdir()
        core.prune_empty_parents(nested, boundary=self.home)
        self.assertFalse((self.home / "a" / "b").exists())
        self.assertFalse((self.home / "a").exists())

    def test_prune_does_not_follow_symlinked_parent(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.home / "link"
        link.symlink_to(outside)
        nested = link / "a" / "b" / "c"
        nested.mkdir(parents=True)
        nested.rmdir()
        core.prune_empty_parents(nested, boundary=self.home)
        self.assertTrue(link.exists())
        self.assertTrue(link.is_symlink())
        self.assertTrue(outside.exists())
        self.assertTrue((outside / "a" / "b").exists())
        self.assertTrue((outside / "a").exists())

    def test_prune_does_not_remove_beyond_boundary_via_symlink(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.home / "link"
        link.symlink_to(outside)
        nested = link / "a" / "b" / "c"
        nested.mkdir(parents=True)
        nested.rmdir()
        (link / "a" / "b").rmdir()
        core.prune_empty_parents(nested, boundary=self.home)
        self.assertTrue(outside.exists())
        self.assertTrue((outside / "a").exists())


if __name__ == "__main__":
    unittest.main()
