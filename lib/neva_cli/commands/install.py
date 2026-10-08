# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Install Neva into one or more coding harnesses.

Claude Code is installed natively: this repo is added as a plugin marketplace, the selected
plugins go in through the `claude plugin` CLI, the rules are copied to ~/.claude/rules/neva/,
and NEVA_* variables are merged into the env object of ~/.claude/settings.json without
disturbing any other key.

Every other harness, including instruction-only ones that have no CLI of their own, is driven
by a data contract at adapters/<harness>/install.json:

    {"harness": "codex",
     "detect": {"binaries": ["codex"], "paths": ["~/.codex"]},
     "entries": [{"src": "...", "dest": "~/...", "mode": "copy", "key": "..."}],
     "post": ["commands to print, never run"]}

mode is copy, symlink, merge-json, merge-toml or append-block. Adding a directory under
adapters/ is the whole of adding a harness: no code changes here.

Everything written is recorded in the install-state manifest so repair and uninstall can put
the machine back exactly as it was found.
"""
import json
import os
import sys
from pathlib import Path

from neva_cli import core

HELP = "install Neva into one or more coding harnesses"

#: Harnesses Neva names in its own help. Any other adapters/<name>/install.json works too.
KNOWN = ("claude", "codex", "opencode", "cursor", "gemini")
PROFILES = ("minimal", "standard", "strict")


def add_arguments(parser):
    parser.add_argument("--harness", default="claude",
                        help="claude, codex, opencode, cursor, gemini, any adapters/<name>, or all")
    parser.add_argument("--plugins", default="core",
                        help="comma-separated Neva plugins, core is always included")
    parser.add_argument("--profile", default="standard", choices=PROFILES,
                        help="hook profile written as NEVA_HOOK_PROFILE")
    parser.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    parser.add_argument("--yes", action="store_true", help="confirm a non-interactive install")
    parser.add_argument("--no-claude-settings", action="store_true",
                        help="leave ~/.claude/settings.json and the claude plugin registry untouched; "
                             "only the rules are installed")


def plugins(raw):
    selected = []
    for item in str(raw).replace(",", " ").split():
        name = item.strip()
        name = name[len("neva-"):] if name.startswith("neva-") else name
        if name and name not in selected:
            selected.append(name)
    if "core" not in selected:
        selected.insert(0, "core")
    return selected


def known_plugins():
    root = core.REPO_ROOT / "plugins"
    if not root.is_dir():
        return []
    return sorted(item.name[len("neva-"):] for item in root.iterdir()
                  if item.is_dir() and item.name.startswith("neva-"))


def adapter_harnesses():
    directory = core.adapters_dir()
    if not directory.is_dir():
        return []
    return sorted(item.name for item in directory.iterdir() if (item / "install.json").is_file())


def all_harnesses():
    return sorted(set(KNOWN) | set(adapter_harnesses()))


def confirm(question, assume_yes):
    """Ask once. Non-interactive without --yes is an error that names the flag, never a hang."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(question)
        print("fix: re-run with --yes to confirm a non-interactive run")
        return False
    answer = input(question + " [y/N]: ").strip().lower()
    return answer in ("y", "yes")


class Installer:
    """Applies adapter entries and records every one of them in the install-state manifest.

    Holds two per-run caches so that several entries pointing at one file compose correctly:
    ``data`` is the in-progress content of each merge destination, and ``backups`` makes sure a
    destination is copied aside exactly once per run.
    """

    def __init__(self, state, dry_run=False):
        self.state = state
        self.dry_run = dry_run
        self.data = {}
        self.backups = {}
        self.changed = []

    # -- manifest bookkeeping ------------------------------------------------

    def prior(self, destination, key=""):
        for entry in self.state["entries"]:
            if entry.get("dest") == str(destination) and entry.get("key", "") == key:
                return entry
        return None

    def any_prior(self, destination):
        for entry in self.state["entries"]:
            if entry.get("dest") == str(destination):
                return entry
        return None

    def record(self, item):
        self.state["entries"] = [old for old in self.state["entries"]
                                 if not (old.get("harness") == item["harness"]
                                         and old.get("dest") == item["dest"]
                                         and old.get("key", "") == item.get("key", ""))]
        self.state["entries"].append(item)
        self.changed.append(item)
        return item

    def pristine(self, destination):
        """Did this destination exist before Neva ever touched it? Answered once, then remembered."""
        earlier = self.any_prior(destination)
        if earlier is not None:
            return bool(earlier.get("existed"))
        return destination.exists() or destination.is_symlink()

    def guard_owned(self, destination, kind):
        """A destination Neva already owns must still be laid out the way Neva left it."""
        earlier = self.any_prior(destination)
        if earlier is not None:
            core.guard_owned(destination, kind, earlier.get("links"), earlier.get("leaf_link"))

    def created_dirs(self, destination, key):
        """Directories this entry's first write creates; a repair keeps the original list."""
        earlier = self.prior(destination, key)
        if earlier is not None:
            return list(earlier.get("created_dirs", []))
        return core.missing_dirs(destination)

    def backup_target(self, destination):
        """For a merge or block through a leaf link, a backup of the file the link points at.

        The link itself is backed up by backup(); this keeps the target's own bytes, so
        uninstall can put them back exactly instead of re-serialising what is left.
        """
        if not destination.is_symlink():
            return None
        key = "target:" + str(destination)
        if key not in self.backups:
            earlier = self.any_prior(destination)
            if earlier is not None:
                self.backups[key] = earlier.get("target_backup")
            elif self.dry_run:
                self.backups[key] = None
            else:
                self.backups[key] = core.backup(core.write_target(destination))
        return self.backups[key]

    @staticmethod
    def leaf_link(destination):
        return os.readlink(destination) if destination.is_symlink() else None

    def backup(self, destination):
        """One timestamped backup per destination per run; a re-run keeps the original one."""
        key = str(destination)
        if key in self.backups:
            return self.backups[key]
        earlier = self.any_prior(destination)
        if earlier is not None and earlier.get("backup"):
            self.backups[key] = earlier["backup"]
        elif earlier is not None:
            self.backups[key] = None
        elif self.dry_run:
            self.backups[key] = None
        else:
            self.backups[key] = core.backup(destination)
        return self.backups[key]

    # -- the five modes ------------------------------------------------------

    def apply_file(self, harness, source, destination, mode):
        if not source.is_file():
            raise ValueError("adapter source missing: " + str(source) +
                             ". fix: restore that file or correct src in install.json")
        # A symlink destination is replaced, never written through, so only its directory has
        # to stay inside HOME. A copy follows its leaf unless that leaf is unlinked first.
        core.guard_destination(destination, follow_leaf=(mode != "symlink"))
        self.guard_owned(destination, mode)
        dirs = self.created_dirs(destination, "")
        existed = self.pristine(destination)
        saved = self.backup(destination)
        if not self.dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if mode == "symlink":
                if destination.exists() or destination.is_symlink():
                    destination.unlink()
                os.symlink(source, destination)
            else:
                # A link at a path Neva owns is replaced, never written through.
                core.atomic_write_bytes(destination, source.read_bytes(),
                                        os.stat(source).st_mode & 0o777)
        checksum = (core.sha256_bytes(str(source).encode("utf-8")) if mode == "symlink"
                    else core.sha256_file(source))
        return self.record({"harness": harness, "kind": mode, "dest": str(destination),
                            "source": str(source), "existed": existed, "backup": saved,
                            "checksum": checksum, "links": core.symlink_layout(destination),
                            "created_dirs": dirs})

    def merge_mapping(self, destination, kind):
        key = str(destination)
        if key not in self.data:
            self.data[key] = core.load_mapping(destination, kind)
        return self.data[key]

    def flush_mapping(self, destination, kind):
        if self.dry_run:
            return
        data = self.data[str(destination)]
        target = core.write_target(destination)
        if kind == "merge-toml":
            core.write_toml(target, data)
        else:
            core.write_json(target, data)

    def apply_merge(self, harness, destination, kind, key, value, source=None):
        if value is core.MISSING:
            raise ValueError("adapter source key missing: " + (key or "<root>") +
                             ". fix: add that key to the adapter source file")
        core.guard_destination(destination)
        self.guard_owned(destination, kind)
        data = self.merge_mapping(destination, kind)
        blocked = core.blocking_parent(data, key)
        if blocked is not None:
            prefix, found = blocked
            shown = "null" if found is None else type(found).__name__
            raise ValueError("cannot merge " + key + " into " + str(destination) + ": " + prefix +
                             " holds a " + shown + ", not a table. fix: rename or remove " + prefix +
                             " in that file by hand, then re-run; Neva left it unchanged")
        plan = self.toml_plan(destination, data, key, value) if kind == "merge-toml" else ("rewrite",)
        dirs = self.created_dirs(destination, key)
        existed = self.pristine(destination)
        saved = self.backup(destination)
        target_saved = self.backup_target(destination)
        earlier = self.prior(destination, key)
        if earlier is not None:
            previous = earlier.get("previous", {"present": False, "value": None})
            created = earlier.get("created_parents", [])
        else:
            found = core.lookup(data, key, core.MISSING)
            previous = {"present": found is not core.MISSING,
                        "value": None if found is core.MISSING else found}
            created = core.missing_parents(data, key)
        core.assign(data, key, value)
        appended = earlier.get("appended") if earlier is not None else None
        if plan[0] == "append":
            appended = plan[2]
            if not self.dry_run:
                core.atomic_write_bytes(core.write_target(destination), plan[1].encode("utf-8"))
        elif plan[0] == "rewrite":
            appended = None
            self.flush_mapping(destination, kind)
        record = {"harness": harness, "kind": kind, "dest": str(destination),
                  "source": str(source) if source else None, "key": key, "value": value,
                  "existed": existed, "backup": saved, "previous": previous,
                  "created_parents": created, "checksum": core.sha256_value(value),
                  "links": core.symlink_layout(destination),
                  "leaf_link": self.leaf_link(destination), "target_backup": target_saved,
                  "created_dirs": dirs}
        if kind == "merge-toml":
            record["appended"] = appended
        return self.record(record)

    @staticmethod
    def toml_plan(destination, data, key, value):
        """How a TOML merge will change the file, decided before anything is backed up.

        ("same",) when the key already holds the value; ("append", text, appended) when the
        table can be added at the end, leaving every other byte alone; ("rewrite",) when the
        file has no comments, so regenerating it loses nothing. Otherwise refuse: a rewrite
        would silently drop the owner's comments.
        """
        if core.lookup(data, key, core.MISSING) == value:
            return ("same",)
        target = core.write_target(destination)
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        appended = core.toml_append(text, data, key, value)
        if appended is not None:
            return ("append",) + appended
        if core.toml_has_comments(text):
            raise ValueError(str(destination) + " has comments that rewriting it to set " + key +
                             " would drop, and " + key + " cannot be added by appending because it "
                             "already exists there. fix: set " + key + " by hand, or remove the "
                             "comments, then re-run; Neva left the file unchanged")
        return ("rewrite",)

    def apply_block(self, harness, source, destination, key):
        if not source.is_file():
            raise ValueError("adapter source missing: " + str(source) +
                             ". fix: restore that file or correct src in install.json")
        body = source.read_text(encoding="utf-8").rstrip("\n")
        begin, end = core.block_markers(key)
        core.guard_destination(destination)
        self.guard_owned(destination, "append-block")
        dirs = self.created_dirs(destination, key)
        existed = self.pristine(destination)
        saved = self.backup(destination)
        target_saved = self.backup_target(destination)
        current = destination.read_text(encoding="utf-8") if destination.is_file() else ""
        replacement = begin + "\n" + body + "\n" + end + "\n"
        text, count = core.block_pattern(key).subn(lambda _: replacement, current, count=1)
        appended = None
        if not count:
            appended = ("" if not current or current.endswith("\n") else "\n") + replacement
            text = current + appended
        if not self.dry_run:
            core.atomic_write_bytes(core.write_target(destination), text.encode("utf-8"))
        earlier = self.prior(destination, key)
        if earlier is not None and earlier.get("appended"):
            appended = earlier["appended"]
        return self.record({"harness": harness, "kind": "append-block", "dest": str(destination),
                            "source": str(source), "key": key, "body": body, "existed": existed,
                            "backup": saved, "appended": appended,
                            "checksum": core.sha256_bytes(("\n" + body + "\n").encode("utf-8")),
                            "links": core.symlink_layout(destination),
                            "leaf_link": self.leaf_link(destination), "target_backup": target_saved,
                            "created_dirs": dirs})

    def apply_registration(self, harness, kind, key, binary, source=None):
        """Register one marketplace or plugin through the claude CLI and record it as Neva's."""
        command = registration_command(binary, kind, key, source)
        print(("would run: " if self.dry_run else "run: ") + " ".join(command))
        if not self.dry_run:
            core.run_claude(command)
        return self.record({"harness": harness, "kind": kind, "dest": REGISTRATION_DEST[kind],
                            "key": key, "source": str(source or core.REPO_ROOT), "existed": False,
                            "backup": None, "checksum": core.sha256_bytes(key.encode("utf-8"))})

    # -- contract driver -----------------------------------------------------

    def apply_adapter(self, harness, contract, adapter_path):
        for entry in contract.get("entries", []):
            mode = entry["mode"]
            destination = core.expand_destination(entry.get("dest"))
            source = core.source_path(adapter_path, entry.get("src"))
            key = entry.get("key", "")
            if mode in ("copy", "symlink"):
                self.apply_file(harness, source, destination, mode)
            elif mode in ("merge-json", "merge-toml"):
                if not source.is_file():
                    raise ValueError("adapter source missing: " + str(source) +
                                     ". fix: restore that file or correct src in install.json")
                loaded = (core.read_toml(source) if source.suffix.lower() == ".toml"
                          else core.read_json_object(source))
                self.apply_merge(harness, destination, mode, key,
                                 core.lookup(loaded, key, core.MISSING), source)
            elif mode == "append-block":
                self.apply_block(harness, source, destination, key)
        for command in contract.get("post", []):
            print("post " + harness + ": run this yourself: " + str(command))


# ---------------------------------------------------------------- Claude Code


def claude_rule_sources(selected):
    """(source, destination-relative) pairs: neva-core's rules, then each plugin's language packs."""
    pairs = []
    common = core.REPO_ROOT / "plugins" / "neva-core" / "rules"
    for source in sorted(common.glob("*.md")):
        pairs.append((source, Path("common") / source.name))
    if not pairs:
        raise ValueError("no neva-core rules at " + str(common) + ", so this neva cannot install "
                         "Claude Code. fix: re-run install.sh from a full Neva checkout")
    for plugin in selected:
        rules = core.REPO_ROOT / "plugins" / ("neva-" + plugin) / "rules"
        if not rules.is_dir():
            continue
        for source in sorted(rules.glob("*/*.md")):
            pairs.append((source, Path(source.parent.name) / source.name))
    return pairs


def install_claude(installer, selected, profile, no_settings=False):
    settings = core.home() / ".claude" / "settings.json"
    values = {"NEVA_HOOK_PROFILE": profile, "NEVA_PLUGINS": ",".join(selected)}
    binary = core.find_binary("claude")
    if binary:
        values["NEVA_CLAUDE_BIN"] = binary
    if no_settings:
        print("claude settings: left unchanged (--no-claude-settings). Neva will not write " +
              str(settings) + " or run claude plugin. To finish by hand, set these in its env "
              "object and run the commands below:")
        for key, value in values.items():
            print("  env." + key + " = " + json.dumps(value))
        for command in claude_commands("claude", selected):
            print("  " + " ".join(command))
    else:
        # Settings are validated before anything is written: a settings.json Neva cannot merge
        # into must stop the whole Claude install, not strand a half-copied rules tree beside it.
        core.guard_destination(settings)
        existing = core.read_json_object(settings)
        if "env" in existing and not isinstance(existing["env"], dict):
            raise ValueError(str(settings) + " env must hold a JSON object, found " +
                             type(existing["env"]).__name__ + ". fix: make env an object or remove it")
        for key, value in values.items():
            print("claude settings: will set env." + key + " = " + json.dumps(value) + " in " +
                  str(settings))
        print("claude settings: to leave Claude Code's settings and plugins alone, re-run with "
              "--no-claude-settings (install.sh: NEVA_CLAUDE_SETTINGS=no)")
    rules_root = core.home() / ".claude" / "rules" / "neva"
    for source, relative in claude_rule_sources(selected):
        installer.apply_file("claude", source, rules_root / relative, "copy")
    if no_settings:
        return
    for key, value in values.items():
        installer.apply_merge("claude", settings, "merge-json", "env." + key, value)
    register_claude_plugins(installer, selected)


MARKETPLACE = "neva"
REGISTRATION_DEST = {"claude-marketplace": "claude plugin marketplace", "claude-plugin": "claude plugin"}


def registration_command(binary, kind, key, source=None):
    if kind == "claude-marketplace":
        return [binary, "plugin", "marketplace", "add", str(source or core.REPO_ROOT)]
    return [binary, "plugin", "install", key]


def register_claude_plugins(installer, selected):
    """Register the marketplace and the selected plugins, recording only what this run adds.

    A registration the user already had is left alone and never recorded, so uninstall cannot
    take it away. One Neva created on an earlier run stays recorded as Neva's.
    """
    binary = core.find_binary("claude")
    if not binary:
        print("claude: CLI not on PATH, so the marketplace was not added. "
              "fix: install Claude Code, then run these yourself:")
        for command in claude_commands("claude", selected):
            print("  " + " ".join(command))
        return False
    marketplaces, plugins = core.claude_registered(binary)
    wanted = [("claude-marketplace", MARKETPLACE)]
    wanted.extend(("claude-plugin", "neva-" + plugin + "@" + MARKETPLACE) for plugin in selected)
    for kind, key in wanted:
        present = key in (marketplaces if kind == "claude-marketplace" else plugins)
        earlier = installer.prior(REGISTRATION_DEST[kind], key)
        if present and earlier is not None:
            installer.record(earlier)
        elif present:
            print(key + " was already registered with Claude Code, left as yours")
        else:
            installer.apply_registration("claude", kind, key, binary)
    return True


def claude_commands(binary, selected):
    commands = [[binary, "plugin", "marketplace", "add", str(core.REPO_ROOT)]]
    commands.extend([binary, "plugin", "install", "neva-" + plugin + "@" + MARKETPLACE]
                    for plugin in selected)
    return commands


# ---------------------------------------------------------------- entry point


def install_harness(harness, installer, selected, profile, no_settings=False):
    """Install one harness. Returns a reason string when it was skipped, otherwise None."""
    if harness == "claude":
        install_claude(installer, selected, profile, no_settings)
        installer.state["harnesses"]["claude"] = {
            "plugins": selected, "profile": profile, "claude_settings": not no_settings,
            "detected": bool(core.find_binary("claude")), "installed_at": core.now_stamp()}
        return None
    contract, path = core.read_adapter(harness)
    if contract is None:
        return (harness + ": no adapter contract at " + str(path) + ", skipped. fix: add that file, "
                "or run neva install --harness claude")
    installer.apply_adapter(harness, contract, path)
    installer.state["harnesses"][harness] = {
        "plugins": selected, "profile": profile,
        "detected": core.detected(contract), "installed_at": core.now_stamp()}
    return None


@core.reports_refusals
def run(args):
    available = known_plugins()
    selected = []
    for name in plugins(args.plugins):
        if available and name not in available:
            # A typo in one plugin name must not cost the buyer the whole install. Name it,
            # drop it, carry on with the rest. install.sh makes the same choice in shell.
            print("unknown plugin '" + name + "', skipped. fix: use any of " + ", ".join(available))
            continue
        selected.append(name)
    if not selected:
        selected = ["core"]
    targets = all_harnesses() if args.harness == "all" else [args.harness]
    if not args.dry_run and not confirm("Install Neva into: " + ", ".join(targets) + "?", args.yes):
        print("install cancelled, nothing was written")
        return 64
    state = core.load_state()
    installer = Installer(state, args.dry_run)
    failures, skipped, installed = 0, [], []
    for harness in targets:
        before = len(installer.changed)
        try:
            reason = install_harness(harness, installer, selected, args.profile,
                                     getattr(args, "no_claude_settings", False))
        except (OSError, ValueError, RuntimeError) as error:
            failures += 1
            print(harness + ": " + str(error))
            continue
        if reason:
            skipped.append(reason)
        else:
            installed.append((harness, len(installer.changed) - before))
    if not args.dry_run and installer.changed:
        core.save_state(state)
    for reason in skipped:
        print(reason)
    for harness, count in installed:
        print(harness + ": " + ("would manage " if args.dry_run else "managed ") + str(count) + " entries")
    if not installed and not failures:
        print("nothing installed. fix: name a harness with an adapter, or use --harness claude")
    return 1 if failures else 0
