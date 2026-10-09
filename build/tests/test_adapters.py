#!/usr/bin/env python3
"""Tests for the generated harness adapter surfaces. Standard library unittest only.

The point of these tests is that a generated file is only useful if the harness can
actually parse it. So they do not merely check that bytes were written: they parse every
generated JSON and TOML file, and assert that YAML frontmatter is the first thing in every
markdown file that has any. That last one is a regression lock. An earlier generator put
its "do not edit" comment on line 1, above the frontmatter, which silently turned every
skill, agent and command in every adapter into a file the harness would not parse.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 and older
    tomllib = None


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("neva_adapters", ROOT / "build" / "adapters.py")
adapters = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapters)

MODES = ("copy", "symlink", "merge-json", "merge-toml", "append-block", "append-json")
KEYED_MODES = ("merge-json", "merge-toml", "append-block", "append-json")


# ---------------------------------------------------------------- reference installer
#
# The neva CLI that consumes install.json lives elsewhere. These tests apply each contract
# exactly as adapters/README.md documents the modes, so what they check is the installed
# destination a person ends up with, not the shape of the source files.

MARKER = "neva-core"
# The real installer's block lines (lib/neva_cli/core.py block_markers), so the reference
# application below writes exactly what `neva install` writes.
BLOCK_START = "# neva begin {key}"
BLOCK_END = "# neva end {key}"


class Installed:
    """A throwaway project, home and CODEX_HOME that one contract is applied into."""

    def __init__(self, tmp):
        self.root = Path(tmp)
        self.project = self.root / "project"
        self.home = self.root / "home"
        self.codex_home = self.home / ".codex"
        self.neva_root = self.root / "neva"
        for d in (self.project, self.home):
            d.mkdir(parents=True, exist_ok=True)

    def expand(self, value):
        value = value.replace("${CODEX_HOME}", str(self.codex_home))
        value = value.replace("${NEVA_ROOT}", str(self.neva_root))
        if value.startswith("~/"):
            value = str(self.home / value[2:])
        return value

    def dest(self, item):
        path = Path(self.expand(item["dest"]))
        return path if path.is_absolute() else self.project / path

    def apply(self, harness_dir):
        contract = json.loads((harness_dir / "install.json").read_text(encoding="utf-8"))
        for item in contract["entries"]:
            src, dest, mode, key = harness_dir / item["src"], self.dest(item), item["mode"], item["key"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if mode == "copy" and src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            elif mode == "copy":
                shutil.copy2(src, dest)
            elif mode == "append-block":
                self.append_block(src, dest, key)
            elif mode == "merge-json":
                self.merge_json(src, dest, key)
            elif mode == "merge-toml":
                self.merge_toml(src, dest, key)
            elif mode == "append-json":
                self.append_json(src, dest, key)
            else:
                raise AssertionError("no reference behaviour for mode " + mode)
        return contract

    @staticmethod
    def append_block(src, dest, key):
        start, end = BLOCK_START.format(key=key), BLOCK_END.format(key=key)
        block = start + "\n" + src.read_text(encoding="utf-8").rstrip("\n") + "\n" + end + "\n"
        text = dest.read_text(encoding="utf-8") if dest.exists() else ""
        if start in text and end in text:
            head, _, rest = text.partition(start)
            _, _, tail = rest.partition(end)
            text = head + block.rstrip("\n") + tail
        else:
            text = text + ("\n" if text and not text.endswith("\n") else "") + ("\n" if text else "") + block
        dest.write_text(text, encoding="utf-8")

    @staticmethod
    def merge_json(src, dest, key):
        value = json.loads(src.read_text(encoding="utf-8"))
        current = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
        parts = key.split(".")
        for part in parts:
            value = value[part]
        node = current
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        dest.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def json_lists(value, key):
        """The array at key, or each array under the object at key, as (path, list) pairs."""
        node = value
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, list):
            return [((), node)]
        if isinstance(node, dict):
            return [((sub,), items) for sub, items in node.items() if isinstance(items, list)]
        return []

    @staticmethod
    def neva_owned(item):
        return MARKER in json.dumps(item)

    @classmethod
    def owner_only(cls, items):
        return [x for x in (items if isinstance(items, list) else []) if not cls.neva_owned(x)]

    def append_json(self, src, dest, key):
        """Add Neva's marked entries to the array, or each array under the object, at key.
        Stale Neva entries are replaced; every other entry stays where it was."""
        parts = key.split(".")
        incoming = json.loads(src.read_text(encoding="utf-8"))
        for part in parts:
            incoming = incoming[part]
        current = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
        parent = current
        for part in parts[:-1]:
            parent = parent.setdefault(part, {})
        if isinstance(incoming, list):
            parent[parts[-1]] = self.owner_only(parent.get(parts[-1])) + incoming
        else:
            holder = parent.setdefault(parts[-1], {})
            for sub, items in incoming.items():
                holder[sub] = self.owner_only(holder.get(sub)) + items
        dest.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    def uninstall(self, harness_dir):
        """Remove every marked entry an append-json install added, and nothing else."""
        contract = json.loads((harness_dir / "install.json").read_text(encoding="utf-8"))
        for item in contract["entries"]:
            dest = self.dest(item)
            if item["mode"] != "append-json" or not dest.exists():
                continue
            parts = item["key"].split(".")
            current = json.loads(dest.read_text(encoding="utf-8"))
            parent = current
            for part in parts[:-1]:
                parent = parent.get(part, {})
            value = parent.get(parts[-1])
            if isinstance(value, list):
                value = self.owner_only(value)
            elif isinstance(value, dict):
                value = {sub: self.owner_only(items) for sub, items in value.items()
                         if self.owner_only(items) or not isinstance(items, list)}
            if value:
                parent[parts[-1]] = value
            else:
                parent.pop(parts[-1], None)
            dest.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    def merge_toml(self, src, dest, key):
        """Replace exactly the [key] table in dest with the one from src, nothing else."""
        header = "[" + key + "]"
        section = self.toml_section(src.read_text(encoding="utf-8"), header)
        if section is None:
            raise AssertionError(f"merge-toml key {key!r} is not a table in {src}")
        text = dest.read_text(encoding="utf-8") if dest.exists() else ""
        existing = self.toml_section(text, header)
        if existing is not None:
            text = text.replace(existing, "")
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + self.expand(section)
        dest.write_text(text, encoding="utf-8")

    @staticmethod
    def toml_section(text, header):
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip() == header:
                j = i + 1
                while j < len(lines) and not lines[j].lstrip().startswith("["):
                    j += 1
                return "".join(lines[i:j]).rstrip("\n") + "\n"
        return None


class AdapterTest(unittest.TestCase):
    """Each test generates into its own temporary tree, never into the repo's adapters/."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="neva-adapter-test-")
        cls.out = Path(cls.tmp.name) / "adapters"
        adapters.build_into(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def files(self, pattern="*"):
        return sorted(p for p in self.out.rglob(pattern) if p.is_file())


class TestDeterminism(AdapterTest):
    def test_two_builds_produce_identical_bytes(self):
        with tempfile.TemporaryDirectory(prefix="neva-adapter-again-") as other:
            second = Path(other) / "adapters"
            adapters.build_into(second)
            self.assertEqual(adapters.tree_bytes(self.out), adapters.tree_bytes(second))

    def test_build_is_not_empty(self):
        self.assertGreater(len(self.files()), 100)
        self.assertEqual(set(adapters.BUILDERS), {p.parent.name for p in self.files("install.json")})


class TestDriftCheck(unittest.TestCase):
    """--check must fail on a hand edit. A check that cannot fail is not a check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="neva-adapter-drift-")
        self.original = adapters.OUT
        adapters.OUT = Path(self.tmp.name) / "adapters"
        adapters.generate(verbose=False)

    def tearDown(self):
        adapters.OUT = self.original
        self.tmp.cleanup()

    def test_clean_tree_passes(self):
        self.assertEqual(0, adapters.check(verbose=False))

    def test_edited_file_is_caught(self):
        target = adapters.OUT / "codex" / "AGENTS.md"
        target.write_text(target.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
        self.assertEqual(1, adapters.check(verbose=False))

    def test_deleted_file_is_caught(self):
        (adapters.OUT / "codex" / "AGENTS.md").unlink()
        self.assertEqual(1, adapters.check(verbose=False))

    def test_added_file_is_caught(self):
        (adapters.OUT / "codex" / "stray.md").write_text("stray\n", encoding="utf-8")
        self.assertEqual(1, adapters.check(verbose=False))

    def test_check_does_not_rewrite_the_tree(self):
        before = adapters.tree_bytes(adapters.OUT)
        adapters.check(verbose=False)
        self.assertEqual(before, adapters.tree_bytes(adapters.OUT))


class TestInstallContract(AdapterTest):
    def test_every_harness_has_a_valid_install_json(self):
        contracts = self.files("install.json")
        self.assertEqual(len(adapters.BUILDERS), len(contracts))
        for path in contracts:
            with self.subTest(harness=path.parent.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(path.parent.name, value["harness"])
                self.assertIsInstance(value["detect"]["binaries"], list)
                self.assertIsInstance(value["detect"]["paths"], list)
                self.assertIsInstance(value["post"], list)
                self.assertTrue(value["entries"], "a harness with no entries installs nothing")
                for item in value["entries"]:
                    self.assertEqual({"src", "dest", "mode", "key"}, set(item))
                    self.assertIn(item["mode"], MODES)
                    self.assertTrue(item["dest"])
                    if item["mode"] in KEYED_MODES:
                        self.assertTrue(item["key"], "merge modes need a key")

    def test_every_entry_src_exists(self):
        """A contract that points at a file the generator never wrote installs nothing."""
        for path in self.files("install.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            for item in value["entries"]:
                with self.subTest(harness=value["harness"], src=item["src"]):
                    self.assertTrue((path.parent / item["src"]).exists())

    def test_no_entry_dest_escapes_upward(self):
        for path in self.files("install.json"):
            for item in json.loads(path.read_text(encoding="utf-8"))["entries"]:
                with self.subTest(dest=item["dest"]):
                    self.assertNotIn("..", item["dest"])


class TestGeneratedFilesParse(AdapterTest):
    def test_every_json_file_parses(self):
        for path in self.files("*.json"):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_every_toml_file_parses(self):
        """Gemini commands embed whole markdown bodies, so TOML escaping must be right."""
        found = self.files("*.toml")
        self.assertTrue(found)
        for path in found:
            with self.subTest(path=str(path.relative_to(self.out))):
                tomllib.loads(path.read_text(encoding="utf-8"))

    def test_gemini_commands_carry_a_prompt_and_the_gemini_placeholder(self):
        if tomllib is None:
            self.skipTest("tomllib needs Python 3.11")
        for path in sorted((self.out / "gemini" / "commands").glob("*.toml")):
            with self.subTest(command=path.stem):
                value = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(value["prompt"].strip())
                self.assertIn("{{args}}", value["prompt"])

    def test_no_generated_file_opens_a_comment_above_a_delimiter(self):
        """Regression lock for the exact bug: marker on line 1, frontmatter on line 2.

        A looser "contains ---" check cannot work, because '---' is also a markdown
        horizontal rule and the rule bodies are full of them. The bug has one shape: a
        leading comment line, then the frontmatter delimiter that should have been first.
        """
        for path in self.files("*.md") + self.files("*.mdc"):
            lines = path.read_text(encoding="utf-8").split("\n")
            with self.subTest(path=str(path.relative_to(self.out))):
                if lines and lines[0].startswith("<!--"):
                    self.assertNotEqual("---", lines[1].strip() if len(lines) > 1 else "",
                                        "the marker pushed the frontmatter off line 1")

    def test_sources_with_frontmatter_keep_it_after_generation(self):
        for path in sorted((self.out / "opencode" / "skills").rglob("SKILL.md")):
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                frontmatter, _ = adapters.split_frontmatter(text)
                self.assertTrue(adapters.field(frontmatter, "name"))
                self.assertTrue(adapters.field(frontmatter, "description"))

    def test_mdc_rules_carry_the_keys_cursor_requires(self):
        """Cursor ignores a rule file that lacks description/alwaysApply."""
        found = sorted((self.out / "cursor" / ".cursor" / "rules").glob("*.mdc"))
        self.assertTrue(found)
        for path in found:
            with self.subTest(rule=path.stem):
                frontmatter, _ = adapters.split_frontmatter(path.read_text(encoding="utf-8"))
                self.assertTrue(adapters.field(frontmatter, "description"))
                self.assertIn(adapters.field(frontmatter, "alwaysApply"), ("true", "false"))

    def test_kiro_steering_uses_a_documented_inclusion_value(self):
        """Kiro silently drops a steering file with an unrecognised inclusion."""
        found = sorted((self.out / "kiro" / ".kiro" / "steering").glob("*.md"))
        self.assertTrue(found)
        for path in found:
            with self.subTest(rule=path.stem):
                frontmatter, _ = adapters.split_frontmatter(path.read_text(encoding="utf-8"))
                self.assertIn(adapters.field(frontmatter, "inclusion"),
                              ("always", "fileMatch", "manual", "auto"))

    def test_antigravity_rules_use_a_documented_trigger(self):
        """Antigravity discards a rule whose trigger it does not recognise, without a word."""
        found = sorted((self.out / "antigravity" / ".agents" / "rules").glob("*.md"))
        self.assertTrue(found)
        for path in found:
            with self.subTest(rule=path.stem):
                frontmatter, _ = adapters.split_frontmatter(path.read_text(encoding="utf-8"))
                self.assertIn(adapters.field(frontmatter, "trigger"),
                              ("always_on", "model_decision", "glob", "manual"))


class TestGeneratedMarkers(AdapterTest):
    def test_text_formats_carry_the_do_not_edit_marker(self):
        for path in self.files("*"):
            if path.suffix.lower() not in (".md", ".mdc", ".toml", ".js", ".mjs", ".cjs"):
                continue
            with self.subTest(path=str(path.relative_to(self.out))):
                self.assertIn(adapters.MARK, path.read_text(encoding="utf-8"))

    # Manifests this generator authors. JSON assets copied verbatim out of a skill are
    # deliberately left alone: they belong to the skill, and injecting a key into one
    # could change what the skill's own code reads back.
    AUTHORED_JSON = ("install.json", "hooks.json", "opencode.json", "gemini-extension.json")

    def test_authored_json_carries_the_marker_as_a_key(self):
        found = [p for p in self.files("*.json") if p.name in self.AUTHORED_JSON]
        self.assertTrue(found)
        for path in found:
            with self.subTest(path=str(path.relative_to(self.out))):
                self.assertEqual(adapters.MARK,
                                 json.loads(path.read_text(encoding="utf-8"))["_generated"])

    def test_copied_skill_assets_are_left_byte_identical(self):
        """A copied asset must match its source exactly, marker included or not."""
        for path in self.files("*.json"):
            if path.name in self.AUTHORED_JSON or "skills" not in path.parts:
                continue
            source = adapters.CORE / "skills" / Path(*path.parts[path.parts.index("skills") + 1:])
            with self.subTest(path=str(path.relative_to(self.out))):
                self.assertTrue(source.exists(), "a copied asset has no source")
                self.assertEqual(source.read_bytes(), path.read_bytes())


class TestCodexUsesTheClaudeMarketplace(AdapterTest):
    def test_codex_does_not_duplicate_skills_or_commands(self):
        """Codex installs those from the Claude marketplace; a copy here would only drift."""
        codex = self.out / "codex"
        self.assertEqual([], list(codex.rglob("SKILL.md")))
        self.assertFalse((codex / "skills").exists())
        self.assertFalse((codex / "commands").exists())
        self.assertEqual({"AGENTS.md", "hooks.json", "config.toml", "install.json"},
                         {p.name for p in codex.iterdir() if p.is_file()})

    def test_codex_registers_every_agent_role_it_ships(self):
        """Codex auto-discovers no agents directory: an unregistered role file is dead."""
        if tomllib is None:
            self.skipTest("tomllib needs Python 3.11")
        codex = self.out / "codex"
        shipped = sorted(p.stem for p in (codex / "agents").glob("*.toml"))
        self.assertTrue(shipped)
        config = tomllib.loads((codex / "config.toml").read_text(encoding="utf-8"))
        registered = {Path(role["config_file"]).stem for role in config["agents"].values()}
        self.assertEqual(set(shipped), registered)
        for path in (codex / "agents").glob("*.toml"):
            with self.subTest(role=path.stem):
                role = tomllib.loads(path.read_text(encoding="utf-8"))
                # Codex rejects a role file missing any of these three.
                self.assertTrue(role["name"])
                self.assertTrue(role["description"])
                self.assertTrue(role["developer_instructions"].strip())

    def test_codex_hooks_call_the_shared_dispatcher(self):
        hooks = json.loads((self.out / "codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertIn("PreToolUse", hooks)
        for event, groups in hooks.items():
            with self.subTest(event=event):
                command = groups[0]["hooks"][0]["command"]
                self.assertIn("dispatch.py", command)
                self.assertTrue(command.endswith(" " + event), "the event is the argv")

    OWNER_CONFIG = ('model = "owner-model"\n\n'
                    '[agents.owner_reviewer]\n'
                    'description = "The owner\'s own role, not Neva\'s."\n'
                    'config_file = "/owner/roles/reviewer.toml"\n')

    def installed_codex(self, tmp, times=1):
        target = Installed(tmp)
        config = target.codex_home / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(self.OWNER_CONFIG, encoding="utf-8")
        for _ in range(times):
            target.apply(self.out / "codex")
        return target, tomllib.loads(config.read_text(encoding="utf-8"))

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_installed_codex_config_registers_every_role_and_the_plugin(self):
        """Checks the destination after applying install.json, not the source fragment."""
        shipped = sorted(p.stem for p in (self.out / "codex" / "agents").glob("*.toml"))
        with tempfile.TemporaryDirectory() as tmp:
            target, config = self.installed_codex(tmp)
            self.assertIn("neva", config.get("marketplaces", {}))
            self.assertTrue(config.get("plugins", {}).get("neva-core@neva", {}).get("enabled"),
                            "neva-core@neva is not enabled in the installed config")
            roles = config.get("agents", {})
            for stem in shipped:
                with self.subTest(role=stem):
                    role = roles.get(stem.replace("-", "_"))
                    self.assertIsNotNone(role, "role file installed but never registered")
                    self.assertTrue(Path(role["config_file"]).is_file(),
                                    "registered config_file does not exist after install")

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_installed_codex_config_keeps_the_owner_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, config = self.installed_codex(tmp, times=2)
            self.assertEqual("owner-model", config["model"])
            self.assertEqual("/owner/roles/reviewer.toml", config["agents"]["owner_reviewer"]["config_file"])
            text = (target.codex_home / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(1, text.count("[marketplaces.neva]"), "a repeat install duplicated a table")

    def test_every_merge_toml_key_names_a_table_in_its_source(self):
        """A key with no matching table in the source would install nothing, silently."""
        contract = json.loads((self.out / "codex" / "install.json").read_text(encoding="utf-8"))
        source = (self.out / "codex" / "config.toml").read_text(encoding="utf-8")
        for item in contract["entries"]:
            if item["mode"] == "merge-toml":
                with self.subTest(key=item["key"]):
                    self.assertIsNotNone(Installed.toml_section(source, "[" + item["key"] + "]"))

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_codex_config_registers_neva_as_a_marketplace(self):
        value = tomllib.loads((self.out / "codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertIn("neva", value["marketplaces"])
        self.assertTrue(value["plugins"]["neva-core@neva"]["enabled"])


OWNER_TEXT = "# My own rules\n\nAlways answer in French. This line belongs to the owner.\n"


def instruction_entries(contract, harness_dir):
    """Entries that install a single instruction file a person may also write in."""
    return [e for e in contract["entries"]
            if (harness_dir / e["src"]).is_file() and e["src"].endswith(".md")]


class TestInstructionInstallPreservesOwnerContent(AdapterTest):
    def test_every_instruction_entry_is_an_append_block(self):
        """copy onto AGENTS.md, QWEN.md and the rest would replace the owner's rules."""
        for path in self.files("install.json"):
            contract = json.loads(path.read_text(encoding="utf-8"))
            for item in instruction_entries(contract, path.parent):
                with self.subTest(harness=contract["harness"], dest=item["dest"]):
                    self.assertEqual("append-block", item["mode"])
                    self.assertEqual(adapters.BLOCK_KEY, item["key"])

    def test_install_twice_over_existing_instructions_keeps_the_owner_text(self):
        for path in self.files("install.json"):
            contract = json.loads(path.read_text(encoding="utf-8"))
            entries = instruction_entries(contract, path.parent)
            if not entries:
                continue
            with self.subTest(harness=contract["harness"]), tempfile.TemporaryDirectory() as tmp:
                target = Installed(tmp)
                for item in entries:
                    dest = target.dest(item)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(OWNER_TEXT, encoding="utf-8")
                target.apply(path.parent)
                target.apply(path.parent)
                for item in entries:
                    text = target.dest(item).read_text(encoding="utf-8")
                    self.assertTrue(text.startswith(OWNER_TEXT), "the owner's rules were replaced")
                    self.assertEqual(1, text.count(BLOCK_START.format(key=adapters.BLOCK_KEY)),
                                     "a repeat install must replace its block, not stack a second")
                    self.assertIn("# Process: the One Loop", text)

    def test_negative_control_a_copy_entry_destroys_the_owner_text(self):
        """Proves the test above can fail: the old copy mode loses the owner's rules."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Installed(tmp)
            harness = Path(tmp) / "fake"
            harness.mkdir()
            (harness / "AGENTS.md").write_text("neva\n", encoding="utf-8")
            (harness / "install.json").write_text(json.dumps(
                {"entries": [adapters.entry("AGENTS.md", "AGENTS.md")]}), encoding="utf-8")
            (target.project / "AGENTS.md").write_text(OWNER_TEXT, encoding="utf-8")
            target.apply(harness)
            self.assertNotIn("belongs to the owner", (target.project / "AGENTS.md").read_text(encoding="utf-8"))


class TestJsonInstallKeepsOwnerEntries(AdapterTest):
    """Codex hooks and OpenCode instructions are shared with the owner: add, never replace."""

    OWNER_HOOKS = {"description": "owner hooks",
                   "hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [
                       {"type": "command", "command": "python3 /owner/policy.py"}]}],
                             "Stop": [{"hooks": [{"type": "command", "command": "python3 /owner/stop.py"}]}]}}
    OWNER_OPENCODE = {"model": "owner/model", "instructions": ["docs/owner-rules.md"]}

    def round_trip(self, harness, rel, owner):
        with tempfile.TemporaryDirectory() as tmp:
            target = Installed(tmp)
            dest = Path(target.expand(rel))
            dest = dest if dest.is_absolute() else target.project / dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(owner), encoding="utf-8")
            target.apply(self.out / harness)
            target.apply(self.out / harness)
            installed = json.loads(dest.read_text(encoding="utf-8"))
            target.uninstall(self.out / harness)
            return installed, json.loads(dest.read_text(encoding="utf-8"))

    def test_codex_install_keeps_the_owner_hooks(self):
        installed, removed = self.round_trip("codex", "${CODEX_HOME}/hooks.json", self.OWNER_HOOKS)
        pre = installed["hooks"]["PreToolUse"]
        self.assertIn(self.OWNER_HOOKS["hooks"]["PreToolUse"][0], pre, "the owner's PreToolUse hook is gone")
        self.assertEqual(self.OWNER_HOOKS["hooks"]["Stop"][0], installed["hooks"]["Stop"][0])
        self.assertEqual(1, sum("dispatch.py" in json.dumps(g) for g in pre), "Neva's hook doubled on reinstall")
        self.assertEqual("owner hooks", installed["description"])
        self.assertEqual(self.OWNER_HOOKS, removed, "uninstall did not restore the owner's hooks")

    def test_opencode_install_keeps_the_owner_instructions(self):
        installed, removed = self.round_trip("opencode", "~/.config/opencode/opencode.json", self.OWNER_OPENCODE)
        self.assertEqual("docs/owner-rules.md", installed["instructions"][0])
        self.assertEqual(2, len(installed["instructions"]), installed["instructions"])
        self.assertEqual("owner/model", installed["model"])
        self.assertEqual(self.OWNER_OPENCODE, removed)

    def test_shared_json_keys_use_the_additive_mode(self):
        for harness, key in (("codex", "hooks"), ("opencode", "instructions")):
            contract = json.loads((self.out / harness / "install.json").read_text(encoding="utf-8"))
            with self.subTest(harness=harness):
                modes = [e["mode"] for e in contract["entries"] if e["key"] == key]
                self.assertEqual(["append-json"], modes)

    def test_every_appended_json_entry_carries_the_marker(self):
        """Uninstall and reinstall find Neva's entries by the marker; an unmarked one is orphaned."""
        for path in self.files("install.json"):
            contract = json.loads(path.read_text(encoding="utf-8"))
            for item in contract["entries"]:
                if item["mode"] != "append-json":
                    continue
                value = json.loads((path.parent / item["src"]).read_text(encoding="utf-8"))
                for sub, items in Installed.json_lists(value, item["key"]):
                    for entry in items:
                        with self.subTest(harness=contract["harness"], entry=str(entry)[:60]):
                            self.assertTrue(Installed.neva_owned(entry))

    def test_negative_control_merge_json_replaces_the_owner_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Installed(tmp)
            dest = target.codex_home / "hooks.json"
            dest.parent.mkdir(parents=True)
            dest.write_text(json.dumps(self.OWNER_HOOKS), encoding="utf-8")
            Installed.merge_json(self.out / "codex" / "hooks.json", dest, "hooks")
            self.assertNotIn("/owner/policy.py", dest.read_text(encoding="utf-8"))


class TestOpenCodeNamespaces(AdapterTest):
    def test_agents_commands_and_skills_install_into_a_neva_subfolder(self):
        """The global ~/.config/opencode holds the owner's own agents, commands and skills."""
        contract = json.loads((self.out / "opencode" / "install.json").read_text(encoding="utf-8"))
        dests = {item["src"]: item["dest"] for item in contract["entries"]}
        for src in ("agents", "commands", "skills"):
            with self.subTest(src=src):
                self.assertEqual("~/.config/opencode/" + src + "/neva", dests[src])


class TestOpenCodeBridge(AdapterTest):
    def test_bridge_forwards_to_dispatch_and_tags_the_harness(self):
        text = (self.out / "opencode" / "plugins" / "neva-hooks.js").read_text(encoding="utf-8")
        self.assertIn("dispatch.py", text)
        self.assertIn('NEVA_HARNESS: "opencode"', text)
        self.assertIn("tool.execute.before", text)
        self.assertIn("throw new Error", text)

    def test_opencode_config_is_schema_shaped(self):
        value = json.loads((self.out / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual("https://opencode.ai/config.json", value["$schema"])
        self.assertIsInstance(value["instructions"], list)


NODE = shutil.which("node")

FAKE_DISPATCH = """import json, os, signal, sys, time
event = sys.argv[1]
payload = json.loads(sys.stdin.read() or "{}")
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"event": event, "payload": payload}) + "\\n")
spec = json.loads(os.environ.get("FAKE_SPEC", "{}")).get(event, {})
if spec.get("sleep"):
    time.sleep(spec["sleep"])
if spec.get("signal"):
    os.kill(os.getpid(), signal.SIGKILL)
sys.stdout.write(spec.get("stdout", ""))
sys.stderr.write(spec.get("stderr", ""))
sys.exit(spec.get("code", 0))
"""

# Runs a list of hook calls against the generated bridge and prints what each returned.
DRIVER = """import { NevaHooks } from "./neva-hooks.mjs";
const hooks = await NevaHooks({ directory: process.env.FAKE_CWD });
const results = [];
for (const [name, input, output] of JSON.parse(process.argv[2])) {
  const out = output || {};
  try {
    if (name === "event") await hooks.event(input);
    else await hooks[name](input, out);
    results.push({ ok: true, output: out });
  } catch (error) {
    results.push({ ok: false, error: String(error.message || error) });
  }
}
console.log(JSON.stringify(results));
"""


@unittest.skipIf(NODE is None, "node is needed to run the OpenCode bridge")
class TestOpenCodeBridgeBehaviour(AdapterTest):
    """Runs the generated bridge under node against a dispatcher, fake or real."""

    def run_bridge(self, calls, spec=None, real=False, prepare=None, neva_root=True, env_extra=None):
        with tempfile.TemporaryDirectory(prefix="neva-bridge-") as tmp:
            tmp = Path(tmp)
            shutil.copy(self.out / "opencode" / "plugins" / "neva-hooks.js", tmp / "neva-hooks.mjs")
            (tmp / "driver.mjs").write_text(DRIVER, encoding="utf-8")
            log = tmp / "dispatch.log"
            env = {k: v for k, v in os.environ.items() if not k.startswith(("NEVA_", "CLAUDE_"))}
            env.update({"FAKE_LOG": str(log), "FAKE_SPEC": json.dumps(spec or {}), "FAKE_CWD": str(tmp),
                        "HOME": str(tmp / "home"), "PYTHONDONTWRITEBYTECODE": "1",
                        "NEVA_DATA_DIR": str(tmp / "data"), "NEVA_STATE_DIR": str(tmp / "state"),
                        "NEVA_CONFIG": str(tmp / "none.env")})
            if real:
                env["NEVA_ROOT"] = str(ROOT)
            else:
                hooks = tmp / "neva" / "plugins" / "neva-core" / "hooks"
                hooks.mkdir(parents=True)
                (hooks / "dispatch.py").write_text(FAKE_DISPATCH, encoding="utf-8")
                env["NEVA_ROOT"] = str(tmp / "neva")
            if not neva_root:
                env.pop("NEVA_ROOT")
            if prepare:
                prepare(tmp)
            env.update(env_extra or {})
            p = subprocess.run([NODE, str(tmp / "driver.mjs"), json.dumps(calls)], cwd=tmp, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(0, p.returncode, p.stderr)
            seen = ([json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
                    if log.exists() else [])
            return json.loads(p.stdout.strip().splitlines()[-1]), seen

    def before(self, tool="bash", args=None, session="s1"):
        return ["tool.execute.before", {"tool": tool, "sessionID": session, "callID": "c1"},
                {"args": args or {"command": "ls"}}]

    def system(self, session="s1"):
        return ["experimental.chat.system.transform", {"sessionID": session, "model": {}}, {"system": []}]

    def test_a_block_throws(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"code": 2, "stderr": "[guard] no"}})
        self.assertFalse(results[0]["ok"])
        self.assertIn("[guard] no", results[0]["error"])

    def test_an_ask_on_stdout_throws_instead_of_running(self):
        """The dispatcher's ask must never be dropped and the tool run anyway."""
        ask = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": "Vault write: GOALS.md"}})
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"stdout": ask}})
        self.assertFalse(results[0]["ok"], "an ask was discarded and the tool allowed")
        self.assertIn("Vault write: GOALS.md", results[0]["error"])
        self.assertIn("needs confirmation in an interactive session", results[0]["error"])

    def test_a_deny_on_stdout_throws(self):
        deny = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": "not here"}})
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"stdout": deny}})
        self.assertFalse(results[0]["ok"])
        self.assertIn("not here", results[0]["error"])

    def test_an_allow_lets_the_tool_run(self):
        """Negative control: an empty answer from the dispatcher blocks nothing."""
        results, seen = self.run_bridge([self.before()])
        self.assertTrue(results[0]["ok"])
        self.assertEqual("PreToolUse", seen[0]["event"])
        self.assertEqual({"name": "bash", "input": {"command": "ls"}}, seen[0]["payload"]["tool"])

    def test_session_start_context_reaches_the_system_prompt(self):
        ctx = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": "OPEN THREADS: ship the reader"}})
        results, seen = self.run_bridge(
            [["event", {"event": {"type": "session.created", "properties": {"info": {"id": "s1"}}}}],
             self.system(), self.system()],
            {"SessionStart": {"stdout": ctx}})
        self.assertEqual("SessionStart", seen[0]["event"])
        for turn in (1, 2):
            with self.subTest(turn=turn):
                self.assertIn("OPEN THREADS: ship the reader", "\n".join(results[turn]["output"]["system"]))

    def test_session_context_stays_in_its_own_session(self):
        ctx = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "S1 ONLY"}})
        results, _ = self.run_bridge(
            [["event", {"event": {"type": "session.created", "properties": {"info": {"id": "s1"}}}}],
             self.system(session="s2")],
            {"SessionStart": {"stdout": ctx}})
        self.assertNotIn("S1 ONLY", "\n".join(results[1]["output"]["system"]))

    def test_tool_context_is_delivered_once(self):
        ctx = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": "commit message is not conventional"}})
        results, _ = self.run_bridge([self.before(), self.system(), self.system()], {"PreToolUse": {"stdout": ctx}})
        self.assertTrue(results[0]["ok"])
        self.assertIn("not conventional", "\n".join(results[1]["output"]["system"]))
        self.assertNotIn("not conventional", "\n".join(results[2]["output"]["system"]))

    def test_post_tool_use_is_forwarded_with_the_edit(self):
        after = ["tool.execute.after",
                 {"tool": "edit", "sessionID": "s1", "callID": "c1", "args": {"filePath": "/w/a.py"}},
                 {"title": "edit", "output": "ok", "metadata": {}}]
        ctx = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": "edited a.py"}})
        results, seen = self.run_bridge([after, self.system()], {"PostToolUse": {"stdout": ctx}})
        self.assertEqual(["PostToolUse"], [c["event"] for c in seen])
        payload = seen[0]["payload"]
        self.assertEqual({"name": "edit", "input": {"filePath": "/w/a.py"}}, payload["tool"])
        self.assertEqual("ok", payload["tool_response"])
        self.assertEqual("s1", payload["session_id"])
        self.assertIn("edited a.py", "\n".join(results[1]["output"]["system"]))

    def assert_fails_closed(self, results, needle):
        self.assertFalse(results[0]["ok"], "a broken dispatcher let the tool run")
        self.assertIn(needle, results[0]["error"])
        self.assertIn("retry", results[0]["error"])

    def test_dispatcher_crash_fails_closed(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"code": 1, "stderr": "Traceback"}})
        self.assert_fails_closed(results, "exited with status 1")

    def test_malformed_dispatcher_output_fails_closed(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"stdout": "{not json"}})
        self.assert_fails_closed(results, "not a JSON object")

    def test_non_object_dispatcher_output_fails_closed(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"stdout": "[1, 2]"}})
        self.assert_fails_closed(results, "not a JSON object")

    def test_killed_dispatcher_fails_closed(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"signal": True}})
        self.assert_fails_closed(results, "SIGKILL")

    def test_dispatcher_timeout_fails_closed(self):
        results, _ = self.run_bridge([self.before()], {"PreToolUse": {"sleep": 5}},
                                     env_extra={"NEVA_BRIDGE_TIMEOUT_MS": "500"})
        self.assert_fails_closed(results, "timed out")

    def test_missing_python_fails_closed(self):
        with tempfile.TemporaryDirectory() as empty:
            results, _ = self.run_bridge([self.before()], env_extra={"PATH": empty})
        self.assert_fails_closed(results, "could not start python3")

    def test_a_broken_dispatcher_does_not_break_other_events(self):
        """Negative control: only guarded tool calls fail closed; session events carry on."""
        results, _ = self.run_bridge(
            [["event", {"event": {"type": "session.created", "properties": {"info": {"id": "s1"}}}}],
             self.system()],
            {"SessionStart": {"code": 1, "stdout": "{not json"}})
        self.assertTrue(all(r["ok"] for r in results))
        self.assertEqual([], results[1]["output"]["system"])

    def test_without_neva_root_the_bridge_is_silent(self):
        results, seen = self.run_bridge([self.before()], {"PreToolUse": {"code": 2, "stderr": "no"}},
                                        neva_root=False)
        self.assertTrue(results[0]["ok"])
        self.assertEqual([], seen)


    def shell_env(self, neva_root=True):
        results, _ = self.run_bridge([["shell.env", {"cwd": "/w"}, {"env": {}}]], neva_root=neva_root)
        return results[0]["output"]["env"]

    def test_shell_env_supplies_the_plugin_root_skills_refer_to(self):
        """Copied skills run ${CLAUDE_PLUGIN_ROOT}/skills/...; OpenCode never sets it."""
        env = self.shell_env()
        self.assertTrue(env.get("CLAUDE_PLUGIN_ROOT", "").endswith("/neva/plugins/neva-core"))
        self.assertTrue(env.get("NEVA_ROOT"))

    def test_shell_env_without_neva_root_sets_nothing(self):
        self.assertEqual({}, self.shell_env(neva_root=False))

    def test_skill_command_runs_with_claude_variables_unset(self):
        """The orch-pipeline command from SKILL.md, in the shell environment OpenCode builds."""
        results, _ = self.run_bridge([["shell.env", {"cwd": "/w"}, {"env": {}}]], real=True)
        injected = results[0]["output"]["env"]
        command = '"${CLAUDE_PLUGIN_ROOT}/skills/orch-pipeline/scripts/orch-workspace" plan.md'
        base = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (Path(tmp) / "plan.md").write_text("# plan\n", encoding="utf-8")
            bare = subprocess.run(["bash", "-c", command], cwd=tmp, env=base, capture_output=True, text=True)
            self.assertNotEqual(0, bare.returncode, "negative control: without the root the path is dead")
            ok = subprocess.run(["bash", "-c", command], cwd=tmp, env=dict(base, **injected),
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(0, ok.returncode, ok.stderr)

    def test_real_dispatcher_blocks_a_careful_command_through_the_bridge(self):
        """End to end with the shipped dispatcher: careful mode, rm -rf, OpenCode."""
        def careful(tmp):
            (tmp / "state" / "safety-guard").mkdir(parents=True)
            (tmp / "state" / "safety-guard" / "careful").write_text("", encoding="utf-8")
        results, _ = self.run_bridge([self.before(args={"command": "rm -rf src"}),
                                      self.before(args={"command": "git status"})],
                                     real=True, prepare=careful)
        self.assertFalse(results[0]["ok"], "careful-mode rm -rf ran on OpenCode")
        self.assertIn("needs confirmation in an interactive session", results[0]["error"])
        self.assertTrue(results[1]["ok"], "an ordinary command was blocked")


def executable(path):
    return bool(path.stat().st_mode & 0o111)


class TestExecutableBits(AdapterTest):
    """A copied script the skill tells the agent to run must still be runnable."""

    def copies_of_executables(self):
        for source in sorted((adapters.CORE / "skills").rglob("*")):
            if source.is_file() and executable(source) and "__pycache__" not in source.parts:
                rel = source.relative_to(adapters.CORE / "skills")
                for harness in ("opencode", "gemini"):
                    yield source, self.out / harness / "skills" / rel

    def test_executable_sources_stay_executable(self):
        pairs = list(self.copies_of_executables())
        self.assertTrue(pairs, "no executable skill scripts found to check")
        for source, copy in pairs:
            with self.subTest(path=str(copy.relative_to(self.out))):
                self.assertTrue(copy.is_file())
                self.assertTrue(executable(copy), "the executable bit was lost in generation")

    def test_plain_files_do_not_become_executable(self):
        skill = self.out / "opencode" / "skills" / "orch-pipeline" / "SKILL.md"
        self.assertFalse(executable(skill))

    def test_generated_orch_workspace_runs_directly(self):
        script = self.out / "opencode" / "skills" / "orch-pipeline" / "scripts" / "orch-workspace"
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (Path(tmp) / "plan.md").write_text("# plan\n", encoding="utf-8")
            p = subprocess.run([str(script), "plan.md"], cwd=tmp, capture_output=True, text=True, timeout=60)
            self.assertEqual(0, p.returncode, p.stderr)
            self.assertTrue(p.stdout.strip().endswith(os.path.join(".neva", "orch", "plan")))


class TestDriftCheckSeesModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="neva-adapter-mode-")
        self.original = adapters.OUT
        adapters.OUT = Path(self.tmp.name) / "adapters"
        adapters.generate(verbose=False)

    def tearDown(self):
        adapters.OUT = self.original
        self.tmp.cleanup()

    def test_a_removed_executable_bit_is_drift(self):
        """Negative control: byte-only comparison could not see this."""
        script = adapters.OUT / "opencode" / "skills" / "orch-pipeline" / "scripts" / "orch-workspace"
        self.assertEqual(0, adapters.check(verbose=False))
        script.chmod(0o644)
        self.assertEqual(1, adapters.check(verbose=False))


class TestNativeRuntimeRoot(AdapterTest):
    def test_every_adapter_using_the_plugin_root_supplies_or_documents_it(self):
        """A skill that runs ${CLAUDE_PLUGIN_ROOT}/... is dead unless something sets it.

        A documentation lock only. For OpenCode the bridge sets the root and the
        bridge tests run a skill command with it; for Gemini, Cursor and Codex this
        proves the export line is printed, not that an installed workflow runs.
        """
        for path in self.files("install.json"):
            harness = path.parent
            uses = any("CLAUDE_PLUGIN_ROOT" in p.read_text(encoding="utf-8", errors="replace")
                       for p in harness.rglob("*") if p.is_file() and p.name != "install.json")
            if not uses:
                continue
            with self.subTest(harness=harness.name):
                post = " ".join(json.loads(path.read_text(encoding="utf-8"))["post"])
                bridge = harness / "plugins" / "neva-hooks.js"
                supplied = bridge.exists() and "CLAUDE_PLUGIN_ROOT" in bridge.read_text(encoding="utf-8")
                self.assertTrue(supplied or "CLAUDE_PLUGIN_ROOT" in post,
                                "skills refer to CLAUDE_PLUGIN_ROOT and nothing sets or documents it")


class TestSourceContainment(unittest.TestCase):
    """Generation must never follow a source symlink to a file outside the plugin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="neva-adapter-link-")
        base = Path(self.tmp.name)
        self.core = base / "core"
        self.private = base / "private.txt"
        self.private.write_text("PRIVATE-FRAGMENT\n", encoding="utf-8")
        (self.core / "skills" / "demo").mkdir(parents=True)
        (self.core / "skills" / "demo" / "SKILL.md").write_text('---\nname: "demo"\n---\nbody\n', encoding="utf-8")
        self.original = adapters.CORE
        adapters.CORE = self.core
        self.out = base / "out"

    def tearDown(self):
        adapters.CORE = self.original
        self.tmp.cleanup()

    def generated_text(self):
        return "".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in self.out.rglob("*") if p.is_file())

    def test_a_symlinked_file_is_refused(self):
        (self.core / "skills" / "demo" / "notes.txt").symlink_to(self.private)
        with self.assertRaises(SystemExit) as caught:
            adapters.copy_tree(self.out, self.core / "skills", Path("skills"))
        self.assertIn("symlink", str(caught.exception))
        self.assertNotIn("PRIVATE-FRAGMENT", self.generated_text() if self.out.exists() else "")

    def test_a_symlinked_directory_is_refused(self):
        (self.core / "skills" / "linked").symlink_to(self.private.parent, target_is_directory=True)
        with self.assertRaises(SystemExit) as caught:
            adapters.copy_tree(self.out, self.core / "skills", Path("skills"))
        self.assertIn("symlink", str(caught.exception))

    def test_reading_a_source_outside_the_plugin_is_refused(self):
        (self.core / "rules").mkdir()
        (self.core / "rules" / "leak.md").symlink_to(self.private)
        with self.assertRaises(SystemExit):
            adapters.read(self.core / "rules" / "leak.md")
        with self.assertRaises(SystemExit):
            adapters.read(self.private)

    def test_a_destination_outside_the_output_root_is_refused(self):
        with self.assertRaises(SystemExit):
            adapters.write_text(self.out, Path("..") / "escaped.md", "x")
        self.assertFalse((self.out.parent / "escaped.md").exists())

    def test_a_plain_tree_still_copies(self):
        """Negative control: containment does not refuse an ordinary source."""
        adapters.copy_tree(self.out, self.core / "skills", Path("skills"))
        self.assertTrue((self.out / "skills" / "demo" / "SKILL.md").is_file())


def installer_core():
    """The real installer's core module, from lib/, so the README is checked against it."""
    lib = str(ROOT / "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    from neva_cli import core
    return core


def readme_modes(text):
    """The mode names in the README's Modes table, in order."""
    section = text.split("### Modes", 1)[1].split("\n\n`post`", 1)[0]
    return [line.split("`")[1] for line in section.splitlines() if line.startswith("| `")]


class TestReadmeMatchesTheInstaller(AdapterTest):
    """adapters/README.md describes the installer bin/neva really runs, mode for mode."""

    def readme(self):
        return (self.out / "README.md").read_text(encoding="utf-8")

    def test_readme_lists_exactly_the_installer_modes(self):
        self.assertEqual(sorted(installer_core().KINDS), sorted(readme_modes(self.readme())))

    def test_negative_control_a_missing_mode_row_is_detected(self):
        text = "\n".join(line for line in self.readme().splitlines() if not line.startswith("| `append-json`"))
        self.assertNotEqual(sorted(installer_core().KINDS), sorted(readme_modes(text)))

    def test_readme_shows_the_installer_block_markers(self):
        begin, end = installer_core().block_markers(adapters.BLOCK_KEY)
        self.assertIn(begin, self.readme())
        self.assertIn(end, self.readme())

    def test_readme_names_the_real_installer(self):
        readme = self.readme()
        self.assertIn("neva install --harness", readme)
        self.assertIn("neva uninstall", readme)
        self.assertNotIn("No installer reads it yet", readme)

    def test_no_post_note_says_the_installer_expands_values(self):
        """The installer expands placeholders in dest only, never inside merged values."""
        for path in self.files("install.json"):
            for line in json.loads(path.read_text(encoding="utf-8"))["post"]:
                with self.subTest(harness=path.parent.name, line=line[:50]):
                    self.assertNotIn("expanded by the installer", line)


class TestSourceGuards(unittest.TestCase):
    """The generator must refuse a source it cannot read correctly, not guess."""

    def test_multiline_description_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.md"
            with self.assertRaises(SystemExit) as caught:
                adapters.assert_single_line_fields(path, "name: x\ndescription: |\n  folded\n")
            self.assertIn("multi-line", str(caught.exception))

    def test_single_line_description_is_accepted(self):
        adapters.assert_single_line_fields(Path("ok.md"), 'name: x\ndescription: "fine"\n')

    def test_unknown_install_mode_is_rejected(self):
        with self.assertRaises(SystemExit):
            adapters.entry("a", "b", "teleport")

    def test_merge_mode_without_a_key_is_rejected(self):
        with self.assertRaises(SystemExit):
            adapters.entry("a", "b", "merge-json")

    def test_frontmatter_split_round_trips(self):
        frontmatter, body = adapters.split_frontmatter('---\nname: "a"\n---\nbody\n')
        self.assertEqual('name: "a"\n', frontmatter)
        self.assertEqual("body\n", body)
        self.assertEqual("a", adapters.field(frontmatter, "name"))

    def test_text_without_frontmatter_is_left_alone(self):
        self.assertEqual(("", "# title\n"), adapters.split_frontmatter("# title\n"))

    def test_marked_keeps_frontmatter_at_byte_zero(self):
        """The bug this locks: the marker above '---' makes the frontmatter unparseable."""
        source = '---\nname: "planner"\ndescription: "plans"\n---\n\n# Planner\n'
        result = adapters.marked(source, ".md")
        self.assertTrue(result.startswith("---\nname:"), "frontmatter must still be first")
        self.assertIn(adapters.MARK, result)
        frontmatter, body = adapters.split_frontmatter(result)
        self.assertEqual("planner", adapters.field(frontmatter, "name"))
        self.assertIn("# Planner", body)

    def test_marked_puts_the_marker_first_when_there_is_no_frontmatter(self):
        result = adapters.marked("# Process\n\ntext\n", ".md")
        self.assertTrue(result.startswith("<!-- " + adapters.MARK + " -->\n"))

    def test_negative_control_a_marker_above_frontmatter_is_detectable(self):
        """Proves the check above can fail: build the broken shape and assert it is caught."""
        broken = "<!-- " + adapters.MARK + ' -->\n---\nname: "planner"\n---\n\nbody\n'
        self.assertFalse(broken.startswith("---\n"))
        self.assertEqual(("", broken), adapters.split_frontmatter(broken))
        self.assertEqual("", adapters.field(adapters.split_frontmatter(broken)[0], "name"))

    def test_module_scripts_keep_the_shebang_first(self):
        result = adapters.marked("#!/usr/bin/env node\nimport x from 'y';\n", ".mjs")
        self.assertTrue(result.startswith("#!/usr/bin/env node\n// " + adapters.MARK + "\n"))

    def test_negative_control_an_unmarked_mjs_is_detectable(self):
        """Proves the marker check can fail: an unmarked module script lacks the marker."""
        self.assertNotIn(adapters.MARK, "#!/usr/bin/env node\nimport x from 'y';\n")
        self.assertIn(".mjs", adapters.TEXT_SUFFIXES)

    def test_comment_formats_match_the_file_type(self):
        self.assertTrue(adapters.marked("a = 1\n", ".toml").startswith("# "))
        self.assertTrue(adapters.marked("const a = 1\n", ".js").startswith("// "))
        self.assertTrue(adapters.marked("#!/bin/sh\necho\n", ".sh").startswith("#!/bin/sh\n# "))


if __name__ == "__main__":
    unittest.main(verbosity=1)
