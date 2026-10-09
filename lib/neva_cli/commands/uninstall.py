# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Remove exactly what the install-state manifest says Neva owns, and nothing else.

The rule this file exists to enforce: a shared file is never restored wholesale from a backup,
because the user may have edited the rest of it since. Neva takes its own key, its own block or
its own file back out, then checks whether what is left is byte for byte what it found. Only a
file Neva created outright is deleted.
"""
import copy
import os
from pathlib import Path

from neva_cli import core
from neva_cli.commands.install import confirm

HELP = "remove Neva-managed harness entries and restore what they replaced"


def add_arguments(parser):
    parser.add_argument("--harness", help="remove one harness instead of all of them")
    parser.add_argument("--dry-run", action="store_true", help="print what would be removed, write nothing")
    parser.add_argument("--yes", action="store_true", help="confirm a non-interactive uninstall")


def remove_file(entry, destination, dry_run):
    # The leaf is unlinked or replaced, never written through, so its directory is what has
    # to be checked: a parent swapped for an outside symlink would aim the unlink out of HOME.
    core.guard_destination(destination, follow_leaf=False)
    if os.path.lexists(destination):
        # Only a file that still matches what Neva wrote is Neva's to delete or overwrite. An
        # edit made after install is the owner's work, so it stays, named, for them to decide.
        current = core.entry_checksum(entry)
        if current != entry.get("checksum"):
            raise ValueError(str(destination) + " was edited after Neva installed it (its checksum "
                             "no longer matches), so uninstall keeps it. fix: move your edits "
                             "elsewhere and run neva repair, or delete the file yourself, then re-run "
                             "neva uninstall")
    if entry.get("backup"):
        saved = core.guard_data_path(Path(entry["backup"]))
        if not saved.is_file():
            # The only way back to the user's original. Fail and keep the entry so a later run,
            # once the backup is back, can still restore it.
            raise ValueError("backup " + str(saved) + " for " + str(destination) + " is " +
                             ("missing" if not os.path.lexists(saved) else "not a regular file") +
                             ", so the original cannot be restored and Neva keeps owning it. fix: put "
                             "the backup back at that path and re-run neva uninstall")
        if dry_run:
            return "would restore " + str(destination)
        core.restore_backup(destination, saved)
        return "restored " + str(destination)
    if not destination.exists() and not destination.is_symlink():
        return "already gone " + str(destination)
    if not dry_run:
        destination.unlink()
    return ("would remove " if dry_run else "removed ") + str(destination)


def remove_merge(entry, destination, dry_run):
    kind = entry["kind"]
    if not destination.is_file():
        return "already gone " + str(destination)
    core.guard_destination(destination)
    data = core.load_mapping(destination, kind)
    loaded = copy.deepcopy(data)
    key = entry.get("key", "")
    previous = entry.get("previous") or {"present": False, "value": None}
    if previous.get("present"):
        core.assign(data, key, previous.get("value"))
    else:
        core.delete_key(data, key)
        core.prune_keys(data, entry.get("created_parents", []))
    target = core.write_target(destination)
    if kind == "merge-toml" and entry.get("appended"):
        # Neva added these exact bytes at the end. Taking exactly them out, wherever later edits
        # left them, keeps every other byte and comment as the owner has it now.
        text = target.read_text(encoding="utf-8")
        appended = entry["appended"]
        if text.count(appended) == 1:
            remaining = text.replace(appended, "", 1)
            try:
                same = core.parse_toml(remaining) == data
            except ValueError:
                same = False
            if same:
                if dry_run:
                    return "would remove " + key + " from " + str(destination)
                if not remaining.strip() and not entry.get("existed"):
                    destination.unlink()
                    return "removed " + str(destination) + " (Neva created it)"
                core.atomic_write_bytes(target, remaining.encode("utf-8"))
                return "removed " + key + " from " + str(destination)
    if data == loaded and (data or entry.get("existed")):
        return "already removed " + key + " from " + str(destination)
    if kind == "merge-toml" and core.toml_has_comments(target.read_text(encoding="utf-8")):
        raise ValueError(str(destination) + " has comments that rewriting it to remove " + key +
                         " would drop. fix: remove " + key + " from that file by hand, then re-run "
                         "neva uninstall; Neva left the file unchanged")
    if dry_run:
        return "would remove " + key + " from " + str(destination)
    if not data and not entry.get("existed"):
        destination.unlink()
        return "removed " + str(destination) + " (Neva created it)"
    # Through a dotfiles link, the bytes to compare and restore are the link target's; the link
    # itself was never replaced, so it needs no restoring.
    saved = entry.get("target_backup") or entry.get("backup")
    if saved:
        core.guard_data_path(Path(saved))
    if saved and Path(saved).is_file() and not Path(saved).name.endswith(".symlink"):
        try:
            original = core.load_mapping(Path(saved), kind)
        except (OSError, ValueError):
            original = None
        if original == data:
            core.restore_backup(target, saved)
            return "restored " + str(destination)
    if kind == "merge-toml":
        core.write_toml(target, data)
    else:
        core.write_json(target, data)
    return "removed " + key + " from " + str(destination)


def remove_append_json(entry, destination, dry_run):
    """Take out only Neva's marked entries, then hand back the owner's bytes when nothing else changed."""
    if not destination.is_file():
        return "already gone " + str(destination)
    core.guard_destination(destination)
    data = core.read_json_object(destination)
    loaded = copy.deepcopy(data)
    key = entry.get("key", "")
    core.strip_neva_entries(data, key, entry.get("value", []), entry.get("created_parents", []),
                            entry.get("foreign"), destination)
    if data == loaded and (data or entry.get("existed")):
        return "already removed Neva's entries at " + key + " from " + str(destination)
    if dry_run:
        return "would remove Neva's entries at " + key + " from " + str(destination)
    if not data and not entry.get("existed"):
        destination.unlink()
        return "removed " + str(destination) + " (Neva created it)"
    target = core.write_target(destination)
    saved = entry.get("target_backup") or entry.get("backup")
    if saved:
        core.guard_data_path(Path(saved))
    if saved and Path(saved).is_file() and not Path(saved).name.endswith(".symlink"):
        try:
            original = core.read_json_object(Path(saved))
        except (OSError, ValueError):
            original = None
        if original == data:
            core.restore_backup(target, saved)
            return "restored " + str(destination)
    core.write_json(target, data)
    return "removed Neva's entries at " + key + " from " + str(destination)


def remove_block(entry, destination, dry_run):
    if not destination.is_file():
        return "already gone " + str(destination)
    core.guard_destination(destination)
    text = destination.read_text(encoding="utf-8")
    appended = entry.get("appended")
    if appended and text.endswith(appended):
        # Neva appended exactly these bytes, so taking exactly them off is a byte-for-byte undo.
        text = text[:-len(appended)]
    else:
        text = core.block_pattern(entry["key"]).sub("", text)
    if dry_run:
        return "would remove block " + entry["key"] + " from " + str(destination)
    if not text.strip() and not entry.get("existed"):
        destination.unlink()
        return "removed " + str(destination) + " (Neva created it)"
    core.atomic_write_bytes(core.write_target(destination), text.encode("utf-8"))
    return "removed block " + entry["key"] + " from " + str(destination)


def remove_registration(entry, dry_run):
    """Unregister a marketplace or plugin this install created. Never one the user had."""
    kind, key = entry["kind"], entry["key"]
    noun = "plugin" if kind == "claude-plugin" else "marketplace"
    tail = ["uninstall", key] if kind == "claude-plugin" else ["marketplace", "remove", key]
    binary = core.find_binary("claude")
    if not binary:
        raise ValueError("claude CLI not on PATH, so " + noun + " " + key + " is still registered. "
                         "fix: put claude on PATH and re-run neva uninstall, or run: claude plugin " +
                         " ".join(tail))
    marketplaces, plugins = core.claude_registered(binary)
    if key not in (plugins if kind == "claude-plugin" else marketplaces):
        return "already unregistered " + noun + " " + key
    if dry_run:
        return ("would uninstall plugin " if kind == "claude-plugin" else "would remove marketplace ") + key
    core.run_claude([binary, "plugin"] + tail)
    return ("uninstalled plugin " if kind == "claude-plugin" else "removed marketplace ") + key


def remove_entry(entry, dry_run):
    kind = entry["kind"]
    if kind in core.REGISTRATIONS:
        return remove_registration(entry, dry_run)
    destination = Path(entry["dest"])
    # Outside HOME first, so that refusal names the boundary; then ownership inside HOME.
    core.guard_destination(destination, follow_leaf=kind not in ("copy", "symlink"))
    core.guard_owned(destination, kind, entry.get("links"), entry.get("leaf_link"))
    if kind in ("copy", "symlink"):
        return remove_file(entry, destination, dry_run)
    if kind in ("merge-json", "merge-toml"):
        return remove_merge(entry, destination, dry_run)
    if kind == "append-block":
        return remove_block(entry, destination, dry_run)
    if kind == "append-json":
        return remove_append_json(entry, destination, dry_run)
    raise ValueError("unsupported manifest entry kind: " + str(kind) +
                     ". fix: delete " + str(core.state_path()) + " and re-run neva install")


def drop_state(state, removed):
    keep = []
    dropped = [id(entry) for entry in removed]
    for entry in state["entries"]:
        if id(entry) not in dropped:
            keep.append(entry)
    state["entries"] = keep
    for harness in {entry.get("harness") for entry in removed}:
        if not any(entry.get("harness") == harness for entry in keep):
            state["harnesses"].pop(harness, None)


@core.reports_refusals
def run(args):
    state = core.load_state()
    selected = [entry for entry in state.get("entries", [])
                if not args.harness or entry.get("harness") == args.harness]
    if not selected:
        print("no owned entries found" + (" for " + args.harness if args.harness else "") +
              ". fix: nothing to do, or check " + str(core.state_path()))
        return 0
    scope = args.harness or "every installed harness"
    if not args.dry_run and not confirm("Remove " + str(len(selected)) + " Neva entries from " +
                                        scope + "?", args.yes):
        print("uninstall cancelled, nothing was removed")
        return 64
    failures, removed = 0, []
    # Reverse order so a file written late is undone before the directory it sits in is pruned.
    for entry in reversed(selected):
        try:
            print(remove_entry(entry, args.dry_run))
            removed.append(entry)
        except ValueError as error:
            # Refusals carry their own fix; appending a permission hint would point the wrong way.
            failures += 1
            print("cannot remove " + entry.get("dest", "<unknown>") + ": " + str(error))
        except OSError as error:
            failures += 1
            print("cannot remove " + entry.get("dest", "<unknown>") + ": " + str(error) +
                  ". fix: restore write permission to that path and re-run neva uninstall")
    if args.dry_run:
        return 1 if failures else 0
    # Only directories install created, and only once nothing Neva still owns sits in them.
    core.prune_created([directory for entry in removed for directory in entry.get("created_dirs", [])])
    drop_state(state, removed)
    if state["entries"]:
        core.save_state(state)
    else:
        path = core.remove_state()
        core.prune_empty_parents(path, boundary=core.data_dir().parent)
    return 1 if failures else 0
