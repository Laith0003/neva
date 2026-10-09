# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Re-apply the manifest entries that are missing or modified, and only those.

repair never installs anything new and never reads an adapter contract. It walks the
install-state manifest, compares each owned destination against the checksum recorded when
Neva wrote it, and rewrites the ones that no longer match. A file Neva does not own is never
touched, however broken it looks.
"""
from pathlib import Path

from neva_cli import core
from neva_cli.commands.install import Installer

HELP = "re-apply missing or modified Neva-managed harness entries"


def add_arguments(parser):
    parser.add_argument("--harness", help="repair one installed harness instead of all of them")
    parser.add_argument("--dry-run", action="store_true", help="print what would be repaired, write nothing")


def status(entry):
    """(needs_repair, detail). A destination that cannot be read is reported, never assumed gone."""
    try:
        current = core.entry_checksum(entry)
    except (OSError, ValueError) as error:
        return True, str(error)
    if current is None:
        return True, "missing"
    if current != entry.get("checksum"):
        return True, "modified"
    return False, "unmodified"


def repair_entry(entry, installer):
    kind = entry["kind"]
    harness = entry.get("harness", "claude")
    destination = Path(entry["dest"])
    if kind in ("copy", "symlink"):
        return installer.apply_file(harness, Path(entry["source"]), destination, kind)
    if kind in ("merge-json", "merge-toml"):
        return installer.apply_merge(harness, destination, kind, entry.get("key", ""),
                                     entry.get("value"), entry.get("source"))
    if kind == "append-json":
        return installer.apply_append_json(harness, destination, entry.get("key", ""),
                                           entry.get("source_value", entry.get("value")), entry.get("source"))
    if kind == "append-block":
        return installer.apply_block(harness, Path(entry["source"]), destination, entry["key"])
    if kind in core.REGISTRATIONS:
        binary = core.find_binary("claude")
        if not binary:
            raise ValueError("claude CLI not on PATH, so " + entry["key"] + " cannot be registered "
                             "again. fix: install Claude Code or put claude on PATH")
        return installer.apply_registration(harness, kind, entry["key"], binary, entry.get("source"))
    raise ValueError("unsupported manifest entry kind: " + str(kind) +
                     ". fix: run neva uninstall then neva install to rewrite the manifest")


@core.reports_refusals
def run(args):
    state = core.load_state()
    entries = [entry for entry in state.get("entries", [])
               if not args.harness or entry.get("harness") == args.harness]
    if not entries:
        print("no owned entries found" + (" for " + args.harness if args.harness else "") +
              ". fix: run neva install --harness claude --yes first")
        return 0
    installer = Installer(state, args.dry_run)
    repaired, failures = 0, 0
    for entry in entries:
        broken, detail = status(entry)
        if not broken:
            continue
        try:
            repair_entry(entry, installer)
        except (OSError, ValueError) as error:
            failures += 1
            print("cannot repair " + entry["dest"] + ": " + str(error))
            continue
        repaired += 1
        print(("would repair " if args.dry_run else "repaired ") + entry["dest"] + " (" + detail + ")")
    if not args.dry_run and installer.changed:
        core.save_state(state)
    if not repaired and not failures:
        print("nothing to repair, every owned entry matches its checksum")
    return 1 if failures else 0
