# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Shared, dependency-free primitives for Neva harness installation.

Everything the install, doctor, repair, uninstall and list subcommands need in order to write
into somebody else's home directory and be able to take it back out again byte for byte:
path expansion, adapter contracts, a tiny TOML reader and writer, timestamped backups, and the
install-state manifest that records every file, symlink, JSON key and TOML key Neva wrote.

Python standard library only.
"""
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_NAME = "install-state.json"
KINDS = ("copy", "symlink", "merge-json", "merge-toml", "append-block", "append-json")
#: The marker that makes an entry in a shared JSON array Neva's. append-json adds, replaces and
#: removes only entries whose JSON contains it; every other entry is the owner's and is kept.
APPEND_MARKER = "neva-core"
#: Manifest kinds for state that lives in Claude Code, not in a file Neva writes.
REGISTRATIONS = ("claude-marketplace", "claude-plugin")

#: Sentinel for "this key is not present", distinct from a stored ``None``.
MISSING = object()


class AdapterError(ValueError):
    """An adapter contract exists but cannot be used. The message names the fix."""


class ConfigError(ValueError):
    """A configuration file exists but cannot be used as-is. Neva refuses rather than replace it."""


class ClaudeCliError(ValueError):
    """The claude CLI is missing, failed, or printed something Neva cannot read."""


class BoundaryError(AdapterError):
    """A destination resolves outside HOME at the moment Neva is about to touch it."""


# ---------------------------------------------------------------- command wrapper


def reports_refusals(run):
    """Wrap a subcommand's run(): a refused file or path is a named failure, never a traceback.

    ConfigError and BoundaryError are raised before Neva writes anything it cannot account for
    (an unreadable manifest, a symlinked data directory), so the command stops with exit 1.
    """
    import functools

    @functools.wraps(run)
    def wrapper(args):
        try:
            return run(args)
        except (ConfigError, BoundaryError) as error:
            print("neva: " + str(error))
            return 1
    return wrapper


# ---------------------------------------------------------------- paths and state


def home():
    return Path(os.environ.get("HOME") or Path.home()).expanduser()


def data_dir():
    raw = os.environ.get("NEVA_DATA_DIR")
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    return home() / ".local" / "share" / "neva"


def state_path():
    return data_dir() / STATE_NAME


def adapters_dir():
    raw = os.environ.get("NEVA_ADAPTERS_DIR")
    return Path(raw).expanduser() if raw else REPO_ROOT / "adapters"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def sha256_value(value):
    return sha256_bytes(json.dumps(value, sort_keys=True).encode("utf-8"))


def now_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json_object(path):
    """A JSON object from ``path``: {} when the file is missing or blank, never when it is broken.

    Unreadable bytes, invalid JSON and a top level that is not an object each raise ConfigError
    naming the file and the fix, because treating the user's content as empty would let the next
    write replace it with nothing but Neva's own keys.
    """
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(str(path) + " cannot be read: " + str(error) +
                          ". fix: restore read access, or move the file aside, then re-run") from error
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ConfigError(str(path) + " is not valid JSON (" + str(error) + "). fix: correct that "
                          "line by hand, or move the file aside, then re-run; Neva left it unchanged") from error
    if not isinstance(value, dict):
        raise ConfigError(str(path) + " must hold a JSON object at the top level, found " +
                          type(value).__name__ + ". fix: wrap the content in {} or move the file "
                          "aside, then re-run; Neva left it unchanged")
    return value


def default_mode():
    """The mode a plain new file gets under the current umask."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def atomic_write_bytes(path, data, mode=None):
    """Replace ``path`` with ``data`` without ever following a link at or beside it.

    The temporary file gets an unpredictable name and is created exclusively (O_EXCL), so a
    symlink planted next to the destination can neither receive the bytes nor be moved into
    place. os.replace swaps the directory entry, so a link at ``path`` itself is replaced, never
    written through. The new file keeps the mode of the file it replaces unless told otherwise.
    """
    path = Path(path)
    if mode is None:
        mode = (path.stat().st_mode & 0o777) if path.is_file() and not path.is_symlink() \
            else default_mode()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".",
                                         suffix=".neva-tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_new_file(path, data, mode=0o600):
    """Create ``path`` with ``data``; fail rather than follow or reuse anything already there."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    handle = os.open(str(path), flags, mode)
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)


def write_json(path, value):
    atomic_write_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def empty_state():
    return {"schema": 1, "harnesses": {}, "entries": []}


def load_state():
    """The install-state manifest, or an empty one when none exists yet.

    Only a missing file means "nothing installed". A manifest that exists but is blank, is not
    JSON, or does not have the manifest's shape is refused by file and field, never read as an
    empty one: it is the only record of what uninstall must take back out, and an empty stand-in
    would be saved over it.
    """
    path = guard_data_path(state_path())
    guard_data_path(data_dir() / "backups")
    if not os.path.lexists(path):
        return empty_state()
    suffix = (" It is Neva's install-state manifest and the only record of what to undo. fix: "
              "restore it from a copy, or correct the field it names by hand; nothing was written")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(str(path) + " cannot be read: " + str(error) + "." + suffix) from error
    if not text.strip():
        raise ConfigError(str(path) + " is empty." + suffix)
    try:
        state = json.loads(text)
    except ValueError as error:
        raise ConfigError(str(path) + " is not valid JSON (" + str(error) + ")." + suffix) from error
    problem = state_problem(state)
    if problem:
        raise ConfigError(str(path) + ": " + problem + "." + suffix)
    return state


ENTRY_TYPES = {
    "harness": (str,), "kind": (str,), "dest": (str,), "checksum": (str,),
    "key": (str,), "source": (str, type(None)), "backup": (str, type(None)), "existed": (bool,),
    "previous": (dict,), "created_parents": (list,), "links": (list,), "appended": (str, type(None)),
    "body": (str,), "leaf_link": (str, type(None)), "target_backup": (str, type(None)),
    "created_dirs": (list,), "foreign": (list, dict),
}
REQUIRED = ("harness", "kind", "dest", "checksum")
KEYED = ("merge-json", "merge-toml", "append-block", "append-json") + REGISTRATIONS


def state_problem(state):
    """What is wrong with a parsed manifest, naming the field, or None when it is well formed."""
    if not isinstance(state, dict):
        return "the top level is a " + type(state).__name__ + ", not an object"
    if state.get("schema") != 1:
        return ("schema is " + repr(state.get("schema")) + ", this neva reads schema 1 (a newer Neva "
                "may have written it)")
    if not isinstance(state.get("harnesses"), dict):
        return "harnesses is a " + type(state.get("harnesses")).__name__ + ", not an object"
    for name, value in state["harnesses"].items():
        if not isinstance(value, dict):
            return "harnesses." + name + " is a " + type(value).__name__ + ", not an object"
    if not isinstance(state.get("entries"), list):
        return "entries is a " + type(state.get("entries")).__name__ + ", not a list"
    for index, entry in enumerate(state["entries"]):
        where = "entries[" + str(index) + "]"
        if not isinstance(entry, dict):
            return where + " is a " + type(entry).__name__ + ", not an object"
        for field in REQUIRED:
            if field not in entry:
                return where + "." + field + " is missing"
        for field, types in ENTRY_TYPES.items():
            if field in entry and not isinstance(entry[field], types):
                return where + "." + field + " is a " + type(entry[field]).__name__
        if entry["kind"] not in KINDS + REGISTRATIONS:
            return where + ".kind is " + repr(entry["kind"]) + ", not one of " + ", ".join(KINDS + REGISTRATIONS)
        if not entry["harness"] or not entry["dest"]:
            return where + (".harness" if not entry["harness"] else ".dest") + " is empty"
        if entry["kind"] not in REGISTRATIONS and not os.path.isabs(entry["dest"]):
            return where + ".dest is not an absolute path"
        if entry["kind"] in KEYED and not entry.get("key"):
            return where + ".key is missing or empty, which a " + entry["kind"] + " entry needs"
        if entry["kind"] in ("copy", "symlink", "append-block") and not entry.get("source"):
            return where + ".source is missing, which a " + entry["kind"] + " entry needs"
        for link in entry.get("links", []):
            if not (isinstance(link, list) and len(link) == 2 and all(isinstance(x, str) for x in link)):
                return where + ".links holds " + repr(link) + ", not a [path, target] pair"
        # Relationships: the fields uninstall decides by. A missing one must never default to
        # the destructive branch (delete instead of restore).
        if entry["kind"] in KINDS and "existed" not in entry:
            return where + ".existed is missing, which says whether uninstall restores or deletes"
        if entry["kind"] in ("copy", "symlink") and entry.get("existed") and not entry.get("backup"):
            return (where + ".backup is missing for a file that existed before install, so its "
                    "original could not be restored")
        if entry["kind"] == "append-json" and "value" not in entry:
            return where + ".value is missing, which holds the entries repair puts back"
        if entry["kind"] in ("merge-json", "merge-toml"):
            previous = entry.get("previous")
            if not isinstance(previous, dict):
                return where + ".previous is missing, which holds the value to hand back"
            if not isinstance(previous.get("present"), bool):
                return where + ".previous.present is not true or false"
            if previous["present"] and "value" not in previous:
                return where + ".previous.value is missing although previous.present is true"
    return None


def save_state(state):
    write_json(guard_data_path(state_path()), state)


def remove_state():
    path = guard_data_path(state_path())
    path.unlink(missing_ok=True)
    return path


def guard_data_path(path):
    """Refuse a path in Neva's data directory unless nothing on the way to it is a symlink.

    The data directory holds the manifest and the backups, so a link planted there would steer
    Neva's own bookkeeping somewhere else. The directory itself and everything below it must be
    real; in its default place under HOME it must also resolve inside HOME.
    """
    root = data_dir()
    path = Path(path)
    if ".." in path.parts or not (path == root or root in path.parents):
        raise BoundaryError("refusing to touch " + str(path) + ": it is not inside the Neva data "
                            "directory " + str(root) + ". fix: re-run neva install to rewrite the manifest")
    current = root
    link = root if root.is_symlink() else None
    if link is None:
        for part in path.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                link = current
                break
            if not current.exists():
                break
    if link is not None:
        raise BoundaryError("refusing to use " + str(path) + ": " + str(link) + " is a symlink (to " +
                            os.readlink(link) + "), and Neva keeps its manifest and backups only in real "
                            "directories. fix: replace " + str(link) + " with a real directory, then re-run")
    if not os.environ.get("NEVA_DATA_DIR"):
        guard_destination(path)
    return path


def expand_destination(raw):
    """Expand ~ and ${VAR} in an adapter destination, then insist it is a safe absolute path."""
    if not isinstance(raw, str) or not raw:
        raise AdapterError("adapter entry dest must be a non-empty string. fix: set dest in install.json")
    expanded = os.path.expandvars(str(home()) + raw[1:] if raw.startswith("~") else raw)
    if "${" in expanded or re.search(r"\$[A-Za-z_]", expanded):
        raise AdapterError("adapter entry dest has an unset variable: " + raw +
                           ". fix: export the variable or hardcode the path in install.json")
    path = Path(expanded)
    if not path.is_absolute():
        raise AdapterError("adapter entry dest must be absolute after expansion: " + raw +
                           ". fix: start dest with ~/ or /")
    # The directory is resolved, the leaf is not: the leaf may be Neva's own symlink from an
    # earlier run, whose target lives in the repo. Each write mode checks its leaf itself
    # (guard_destination) right before it touches it.
    resolved = path.parent.resolve() / path.name
    boundary = home().resolve()
    if boundary not in resolved.parents and resolved != boundary:
        raise AdapterError("adapter entry dest resolves outside HOME: " + raw +
                           ". fix: choose a destination inside your home directory")
    if ".." in path.parts:
        raise AdapterError("adapter entry dest must not contain '..': " + raw +
                           ". fix: write the destination out in full")
    return path


def first_symlink(path):
    """The first component of ``path`` below HOME that is a symlink, or None.

    Walks down from HOME rather than from /, because HOME itself may legitimately sit under a
    system symlink (macOS keeps temporary directories under /var, a link to /private/var).
    """
    path = Path(path)
    base = home()
    try:
        relative = path.relative_to(base)
    except ValueError:
        return None
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return current
        if not current.exists():
            return None
    return None


def guard_destination(path, follow_leaf=True):
    """Refuse ``path`` unless it resolves inside HOME right now. Returns ``path`` unchanged.

    Called by every write primitive immediately before it backs up, writes, replaces or
    deletes, so a symlink planted after install (on the file itself or on any directory above
    it) cannot steer a repair or an uninstall out of HOME. ``follow_leaf=False`` is for callers
    that replace or unlink the leaf itself and never write through it: only the directory it
    sits in has to stay inside HOME.
    """
    path = Path(path)
    boundary = home().resolve()
    if not path.is_absolute() or ".." in path.parts:
        raise BoundaryError("refusing to touch " + str(path) + ": a managed path must be absolute "
                            "with no '..'. fix: re-run neva install to rewrite the manifest entry")
    target = path.resolve() if follow_leaf else path.parent.resolve() / path.name
    if target == boundary or boundary in target.parents:
        return path
    link = first_symlink(path if follow_leaf else path.parent)
    fix = ("replace the symlink at " + str(link) + " with a real directory or file inside HOME"
           if link else "choose a destination inside your home directory")
    raise BoundaryError("refusing to touch " + str(path) + ": it resolves to " + str(target) +
                        ", outside HOME " + str(boundary) + ". fix: " + fix + ", then re-run")


def symlink_layout(path):
    """Every symlink between HOME and the directory holding ``path``, as [relative, target] pairs.

    Recorded when Neva writes a destination. A link that was already there (a dotfiles setup)
    is part of the layout and stays acceptable; a link that appears later is a substitution.
    """
    base = home()
    try:
        relative = Path(path).parent.relative_to(base)
    except ValueError:
        return []
    links, current = [], base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            links.append([str(current.relative_to(base)), os.readlink(current)])
        elif not current.exists():
            break
    return links


FILE_KINDS = ("copy", "merge-json", "merge-toml", "append-block", "append-json")


def write_target(path):
    """Where a merge or append-block writes: the file a leaf link points at, else ``path``.

    A dotfiles layout links ~/.claude/settings.json into a repository. Writing through the link
    keeps it a link; replacing the directory entry would cut the repository out. Callers have
    already checked that the link resolves inside HOME (guard_destination with follow_leaf).
    """
    path = Path(path)
    return Path(os.path.realpath(path)) if path.is_symlink() else path


def guard_owned(path, kind, links, leaf_link=None):
    """Refuse to touch a destination Neva already owns unless it is still what Neva left.

    The directories above it must have exactly the symlinks recorded when Neva wrote it, inside
    HOME or not, and the leaf must still be a real file (or, for a symlink entry, a link): a
    link Neva did not create is never followed, and a real file at a Neva link is never deleted.
    """
    path = Path(path)
    recorded = [list(item) for item in (links or [])]
    now = symlink_layout(path)
    if now != recorded:
        added = [item for item in now if item not in recorded]
        gone = [item for item in recorded if item not in now]
        if added:
            where = home() / added[0][0]
            detail = str(where) + " is now a symlink to " + added[0][1]
        else:
            where = home() / gone[0][0]
            detail = str(where) + " is no longer the symlink to " + gone[0][1] + " it was at install"
        raise BoundaryError("refusing to touch " + str(path) + ": " + detail + ". fix: put " +
                            str(where) + " back as it was when Neva installed, then re-run; "
                            "Neva followed nothing")
    if kind == "symlink":
        if os.path.lexists(path) and not path.is_symlink():
            raise BoundaryError("refusing to touch " + str(path) + ": Neva left a symlink there and it "
                                "is now a real file or directory, which Neva does not own. fix: move "
                                "it aside, then re-run")
    elif kind in FILE_KINDS and path.is_symlink():
        if kind != "copy" and leaf_link is not None and os.readlink(path) == leaf_link:
            return path
        was = ("a link to " + leaf_link) if leaf_link is not None else "the file Neva wrote"
        raise BoundaryError("refusing to touch " + str(path) + ": it is now a symlink (to " +
                            os.readlink(path) + "), not " + was + ". fix: put it back as it was "
                            "at install, or remove it, then re-run; Neva did not follow it")
    elif kind in FILE_KINDS and leaf_link is not None and os.path.lexists(path):
        raise BoundaryError("refusing to touch " + str(path) + ": it was a link to " + leaf_link +
                            " at install and is now a real file or directory. fix: put the link "
                            "back, then re-run")
    return path


def source_path(adapter_path, raw):
    """The adapter source an entry names, inside the adapter directory or the Neva checkout.

    An absolute src, or one with a '..' part, is refused: a contract is data, and a src that
    walks out of the checkout would let a directory entry copy anything readable into HOME.
    """
    if not isinstance(raw, str) or not raw:
        raise AdapterError("adapter entry src must be a non-empty string. fix: set src in install.json")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AdapterError("adapter entry src must be a path inside the adapter directory, got " + raw +
                           ". fix: name the file relative to adapters/<harness>, with no '..'")
    local = adapter_path.parent / candidate
    chosen = local if local.exists() else REPO_ROOT / candidate
    roots = [adapter_path.parent.resolve(), REPO_ROOT.resolve()]
    real = chosen.resolve()
    if not any(real == root or root in real.parents for root in roots):
        raise AdapterError("adapter entry src " + raw + " resolves to " + str(real) + ", outside the adapter "
                           "and the Neva checkout. fix: replace the link with the file itself")
    return chosen


#: Files an operating system drops into folders. Never part of an adapter, never installed.
OS_JUNK = (".DS_Store", "Thumbs.db", "desktop.ini")


def is_os_junk(path):
    return path.name in OS_JUNK or path.name.startswith("._")


# ---------------------------------------------------------------- adapter contracts


def read_adapter(name):
    """Return (contract, path). contract is None when no adapter file exists for this harness."""
    path = adapters_dir() / name / "install.json"
    if not path.is_file():
        return None, path
    try:
        with open(path, encoding="utf-8") as handle:
            contract = json.load(handle)
    except (OSError, ValueError) as error:
        raise AdapterError("adapter " + str(path) + " is not readable JSON: " + str(error) +
                           ". fix: correct the file or remove it") from error
    if not isinstance(contract, dict):
        raise AdapterError("adapter " + str(path) + " must hold a JSON object. fix: wrap it in {}")
    if contract.get("harness") and contract["harness"] != name:
        raise AdapterError("adapter harness is '" + str(contract["harness"]) + "' but the directory is '" +
                           name + "'. fix: make them match")
    entries = contract.get("entries", [])
    if not isinstance(entries, list):
        raise AdapterError("adapter entries must be a list. fix: set entries to [] or a list of objects")
    for entry in entries:
        if not isinstance(entry, dict):
            raise AdapterError("every adapter entry must be an object. fix: check entries in install.json")
        if entry.get("mode") not in KINDS:
            raise AdapterError("adapter entry mode must be one of " + ", ".join(KINDS) + ", got " +
                               repr(entry.get("mode")) + ". fix: correct mode in install.json")
        if entry.get("mode") in ("merge-json", "merge-toml") and not (
                isinstance(entry.get("key"), str) and entry["key"].strip(".")):
            raise AdapterError("a " + entry["mode"] + " entry needs a key naming what to merge, "
                               "got " + repr(entry.get("key")) + ". fix: set key to a dotted path "
                               "such as tool.neva in install.json; Neva never merges a whole file")
        if entry.get("mode") == "append-json" and not (
                isinstance(entry.get("key"), str) and entry["key"].strip(".")):
            raise AdapterError("an append-json entry needs a key naming the array, or the object of "
                               "arrays, Neva adds its entries to, got " + repr(entry.get("key")) +
                               ". fix: set key to a dotted path such as hooks in install.json")
        if entry.get("mode") == "append-block" and not entry.get("key"):
            raise AdapterError("an append-block entry needs a key for its begin and end markers. " +
                               "fix: add key to that entry in install.json")
    post = contract.get("post", [])
    if not isinstance(post, list):
        raise AdapterError("adapter post must be a list of commands to print. fix: set post to []")
    return contract, path


def find_binary(name):
    return shutil.which(name)


def detected(contract):
    """True when this harness looks installed: one of its binaries or paths is present."""
    detect = contract.get("detect") or {}
    for binary in detect.get("binaries", []):
        if find_binary(str(binary)):
            return True
    for raw in detect.get("paths", []):
        try:
            candidate = expand_destination(raw)
        except AdapterError:
            continue
        if candidate.exists():
            return True
    return False


# ---------------------------------------------------------------- claude registrations


def run_claude(command):
    """Run one claude CLI command. A failure raises with its own output and names the fix."""
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClaudeCliError(" ".join(command) + " failed: " + str(error) +
                             ". fix: run that command yourself and correct what it names") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "no output"
        raise ClaudeCliError(" ".join(command) + " failed: " + detail +
                             ". fix: run that command yourself and correct what it names")
    return result.stdout


def claude_registered(binary):
    """(marketplace names, plugin ids) that Claude Code reports right now."""
    found = []
    for args in (["marketplace", "list"], ["list"]):
        command = [binary, "plugin"] + args + ["--json"]
        output = run_claude(command)
        try:
            items = json.loads(output or "[]")
        except ValueError as error:
            raise ClaudeCliError(" ".join(command) + " did not print JSON: " + str(error) +
                                 ". fix: update Claude Code, then re-run") from error
        if not isinstance(items, list):
            raise ClaudeCliError(" ".join(command) + " printed a " + type(items).__name__ +
                                 ", not a list. fix: update Claude Code, then re-run")
        found.append({str(item.get("name" if args[0] == "marketplace" else "id"))
                      for item in items if isinstance(item, dict)})
    return found[0], found[1]


def registration_present(kind, key):
    binary = find_binary("claude")
    if not binary:
        raise ClaudeCliError("claude CLI not on PATH, so " + key + " cannot be checked. "
                             "fix: install Claude Code or put claude on PATH")
    marketplaces, plugins = claude_registered(binary)
    return key in (marketplaces if kind == "claude-marketplace" else plugins)


# ---------------------------------------------------------------- backups


def backup(path):
    """Copy a file or symlink aside before Neva touches it. Returns the backup path, or None."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    root = guard_data_path(data_dir() / "backups" / now_stamp())
    digest = sha256_bytes(str(path).encode("utf-8"))[:16]
    suffix = ".symlink" if path.is_symlink() else ""
    saved = root / (path.name + "." + digest + suffix)
    attempt = 1
    while os.path.lexists(saved):
        attempt += 1
        saved = root / (path.name + "." + digest + "-" + str(attempt) + suffix)
    saved.parent.mkdir(parents=True, exist_ok=True)
    guard_data_path(saved)
    if path.is_symlink():
        write_new_file(saved, os.readlink(path).encode("utf-8"))
    else:
        write_new_file(saved, path.read_bytes())
        shutil.copystat(path, saved)
    return str(saved)


def restore_backup(destination, backup_path):
    """Put a backup back. False when it is gone; refuses a backup that became a symlink."""
    source = guard_data_path(Path(backup_path))
    if not source.is_file():
        return False
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.name.endswith(".symlink"):
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        os.symlink(source.read_text(encoding="utf-8"), destination)
    else:
        atomic_write_bytes(destination, source.read_bytes(), source.stat().st_mode & 0o777)
        shutil.copystat(source, destination)
    return True


# ---------------------------------------------------------------- dotted keys


def key_parts(dotted):
    """The parts of a dotted key. A part may be quoted as TOML quotes it, plugins."a@b", and a
    quoted part is one key whatever it holds. A key with no quotes splits on every dot."""
    if '"' not in dotted and "'" not in dotted:
        return dotted.split(".")
    return _split_key(dotted, 0)


def join_key(parts):
    """The inverse of key_parts: bare parts as they are, anything else quoted."""
    return ".".join(part if BARE_KEY.fullmatch(part) else json.dumps(part) for part in parts)



def lookup(value, dotted, missing=None):
    if not dotted:
        return value
    current = value
    for part in key_parts(dotted):
        if not isinstance(current, dict) or part not in current:
            return missing
        current = current[part]
    return current


def assign(value, dotted, replacement):
    if not dotted:
        raise ValueError("a merge needs a key; an empty key would replace the whole file. "
                         "fix: name the key in install.json")
    current = value
    parts = key_parts(dotted)
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = replacement
    return value


def delete_key(value, dotted):
    if not dotted:
        raise ValueError("a merge needs a key; an empty key would empty the whole file. "
                         "fix: name the key in install.json")
    current = value
    parts = key_parts(dotted)
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return value
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    return value


def missing_parents(value, dotted):
    """Dotted prefixes of ``dotted`` that do not yet exist in ``value``, outermost first.

    Recorded at install time so uninstall can remove the containers Neva created and leave the
    ones it found. Without it, uninstalling an ``env.NEVA_PLUGINS`` key out of a settings file
    that never had an ``env`` object leaves an empty ``env`` behind forever.
    """
    created = []
    current = value
    parts = key_parts(dotted) if dotted else []
    for index, part in enumerate(parts[:-1]):
        if not isinstance(current, dict) or not isinstance(current.get(part), dict):
            created.append(join_key(parts[:index + 1]))
            current = None
        else:
            current = current[part]
    return created


def blocking_parent(value, dotted):
    """The first dotted prefix of ``dotted`` that exists in ``value`` but is not a mapping.

    Returns (prefix, found) or None. Merging through such a parent would replace the user's
    scalar, list or null with a mapping, and only the leaf's old value is ever recorded, so
    uninstall could never hand the parent back. Callers refuse instead.
    """
    current = value
    parts = key_parts(dotted) if dotted else []
    for index, part in enumerate(parts[:-1]):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
        if not isinstance(current, dict):
            return join_key(parts[:index + 1]), current
    return None


def prune_keys(value, dotted_parents):
    """Delete each dotted parent, outermost last, as long as it is an empty mapping."""
    for dotted in sorted(dotted_parents, key=lambda item: len(key_parts(item)), reverse=True):
        container = lookup(value, dotted, MISSING)
        if isinstance(container, dict) and not container:
            delete_key(value, dotted)


# ---------------------------------------------------------------- a very small TOML


def _strip_comment(line):
    """Drop a trailing TOML comment without cutting a '#' that sits inside a string."""
    out = []
    quote = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(line):
                out.append(line[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = None
        elif char == "#":
            break
        elif char in "\"'":
            quote = char
        out.append(char)
        index += 1
    return "".join(out).strip()


def _split_items(body):
    """Split a TOML array body on top-level commas, respecting quotes and nested brackets."""
    items, current, depth, quote = [], [], 0, None
    index = 0
    while index < len(body):
        char = body[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(body):
                current.append(body[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            items.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return [item.strip() for item in items if item.strip()]


def toml_value(raw):
    raw = raw.strip()
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"[-+]?\d+", raw):
        return int(raw)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", raw):
        return float(raw)
    if raw.startswith("[") and raw.endswith("]"):
        return [toml_value(item) for item in _split_items(raw[1:-1])]
    if raw.startswith(("\'\'\'", '"""')):
        raise ValueError("unsupported TOML multi-line string: " + raw + ". fix: Neva cannot write a "
                         "multi-line string back unchanged, so it refuses the file; make that value "
                         "a single-line string, or edit the file by hand")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)
        except ValueError as error:
            raise ValueError("unsupported TOML string: " + raw + " (" + str(error) + "). fix: use a "
                             "plain single-line string, or edit the file by hand") from error
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    raise ValueError("unsupported TOML value: " + raw +
                     ". fix: Neva's TOML support covers strings, integers, floats, booleans and "
                     "flat arrays; use a merge-json entry for anything richer")


BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _unsupported_key(raw, number):
    return ValueError("unsupported TOML key on line " + str(number) + ": " + raw.strip() +
                      ". fix: use bare, \"quoted\" or 'literal' keys joined by dots, or edit that "
                      "file by hand")


def _split_key(raw, number):
    """The parts of a TOML key: bare, "basic" and 'literal' parts joined by dots.

    A quoted part keeps its dots, so "model.name" is one key and model.name is two.
    """
    parts, index, text = [], 0, raw
    while True:
        while index < len(text) and text[index] in " \t":
            index += 1
        if index >= len(text):
            raise _unsupported_key(raw, number)
        char = text[index]
        if char == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                raise _unsupported_key(raw, number)
            try:
                parts.append(json.loads(text[index:end + 1]))
            except ValueError as error:
                raise _unsupported_key(raw, number) from error
            index = end + 1
        elif char == "'":
            end = text.find("'", index + 1)
            if end < 0:
                raise _unsupported_key(raw, number)
            parts.append(text[index + 1:end])
            index = end + 1
        else:
            match = BARE_KEY.match(text, index)
            if not match:
                raise _unsupported_key(raw, number)
            parts.append(match.group(0))
            index = match.end()
        while index < len(text) and text[index] in " \t":
            index += 1
        if index == len(text):
            return parts
        if text[index] != ".":
            raise _unsupported_key(raw, number)
        index += 1


def _split_assignment(line):
    """(key text, value text) split on the first '=' that is not inside a quoted key."""
    quote, index = None, 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\" and quote == '"':
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "=":
            return line[:index], line[index + 1:]
        index += 1
    return None


def _descend(mapping, parts, raw, number):
    for part in parts:
        nested = mapping.setdefault(part, {})
        if not isinstance(nested, dict):
            raise ValueError("TOML line " + str(number) + " redefines " + raw.strip() +
                             " as a table. fix: correct that file by hand")
        mapping = nested
    return mapping


def parse_toml(text):
    result = {}
    section = result
    declared = set()
    for number, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith("[["):
            raise ValueError("unsupported TOML array of tables on line " + str(number) +
                             ". fix: Neva only merges plain tables; edit that file by hand")
        if line.startswith("[") and line.endswith("]"):
            parts = tuple(_split_key(line[1:-1], number))
            if parts in declared:
                raise ValueError("TOML table " + line + " is declared twice, again on line " +
                                 str(number) + ". fix: merge the two tables by hand; Python's "
                                 "tomllib refuses this file too")
            declared.add(parts)
            section = _descend(result, parts, line, number)
            continue
        split = _split_assignment(line)
        if split is None:
            raise ValueError("unsupported TOML line " + str(number) + ": " + line +
                             ". fix: Neva reads key = value lines and [table] headers only")
        parts = _split_key(split[0], number)
        target = _descend(section, parts[:-1], split[0], number)
        if parts[-1] in target:
            raise ValueError("TOML key " + split[0].strip() + " is set twice, again on line " +
                             str(number) + ". fix: keep one of the two lines; Python's tomllib "
                             "refuses this file too")
        target[parts[-1]] = toml_value(split[1])
    return result


def toml_has_comments(text):
    """True when any line of ``text`` carries a comment a rewrite would lose."""
    return any(_strip_comment(raw) != raw.strip() for raw in text.splitlines())


def _standard_toml(text):
    """tomllib's reading of ``text`` where the interpreter has it, else Neva's own."""
    try:
        import tomllib
    except ImportError:
        return parse_toml(text)
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(str(error)) from error


def toml_append(text, current, key, value):
    """(new text, appended) that sets ``key`` by adding a table at the end, or None.

    Appending leaves every existing byte, comments included, where it was, and uninstall can
    take exactly the appended bytes off again. It works only when the table it adds does not
    exist yet, and the result must read the same to Neva and, where present, to tomllib.
    """
    parts = key_parts(key)
    if isinstance(value, dict):
        header, body = parts, value
    else:
        header, body = parts[:-1], {parts[-1]: value}
    if header and lookup(current, join_key(header), MISSING) is not MISSING:
        return None
    if not header and any(_strip_comment(raw).startswith("[") for raw in text.splitlines()):
        return None
    lines = toml_lines(body, tuple(header))
    if not lines:
        return None
    lead = ("" if not text or text.endswith("\n") else "\n") + ("\n" if text.strip() else "")
    appended = lead + "\n".join(lines) + "\n"
    expected = copy.deepcopy(current)
    assign(expected, key, value)
    try:
        if parse_toml(text + appended) != expected or _standard_toml(text + appended) != expected:
            return None
    except ValueError:
        return None
    return text + appended, appended


def read_toml(path):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return parse_toml(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ConfigError(str(path) + ": " + str(error)) from error


def format_toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
    raise ValueError("unsupported TOML value type: " + type(value).__name__ +
                     ". fix: adapter TOML values must be strings, numbers, booleans or flat arrays")


def toml_string(value):
    """A TOML basic string. Non-ASCII stays literal: JSON's surrogate-pair escapes are not TOML."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_key(part):
    """One key part, quoted unless it is a bare key, so a dot or space inside it keeps its meaning."""
    return part if BARE_KEY.fullmatch(part) else toml_string(part)


def toml_lines(mapping, prefix=()):
    """``mapping`` as TOML lines: its scalars under ``[prefix]``, then each nested table."""
    lines = []

    def emit(table, path):
        scalars = {key: item for key, item in table.items() if not isinstance(item, dict)}
        nested = {key: item for key, item in table.items() if isinstance(item, dict)}
        if path:
            lines.append("[" + ".".join(toml_key(part) for part in path) + "]")
        lines.extend(toml_key(key) + " = " + format_toml_value(item) for key, item in scalars.items())
        for key, item in nested.items():
            if lines and lines[-1] != "":
                lines.append("")
            emit(item, path + (key,))

    emit(mapping, tuple(prefix))
    return lines


def write_toml(path, value):
    lines = toml_lines(value)
    atomic_write_bytes(path, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


# ---------------------------------------------------------------- manifest entries


def block_markers(key):
    return "# neva begin " + key, "# neva end " + key


def block_pattern(key):
    begin, end = block_markers(key)
    return re.compile(re.escape(begin) + r"\n.*?" + re.escape(end) + r"\n?", re.S)


def load_mapping(destination, kind):
    """Read a merge destination as a mapping, whatever its state on disk."""
    if kind == "merge-toml":
        return read_toml(destination)
    return read_json_object(destination)


def entry_checksum(record):
    """Checksum of exactly what Neva owns at this destination, or None when it is gone.

    Raises OSError or ValueError when the destination exists but cannot be read; callers report
    that as a failure with its error, never as an absent entry.
    """
    kind = record["kind"]
    if kind in REGISTRATIONS:
        key = record["key"]
        return sha256_bytes(key.encode("utf-8")) if registration_present(kind, key) else None
    destination = Path(record["dest"])
    if kind == "symlink":
        return sha256_bytes(os.readlink(destination).encode("utf-8")) if destination.is_symlink() else None
    if kind == "copy":
        return sha256_file(destination) if destination.is_file() else None
    if kind in ("merge-json", "merge-toml"):
        if not destination.is_file():
            return None
        value = lookup(load_mapping(destination, kind), record.get("key", ""), MISSING)
        return None if value is MISSING else sha256_value(value)
    if kind == "append-json":
        if not destination.is_file():
            return None
        recorded = record.get("value", [])
        present = written_entries(lookup(read_json_object(destination), record["key"], MISSING), recorded)
        if present == reshape(recorded, arrays(recorded)) or any(arrays(present).values()):
            return sha256_value(present)
        return None
    if kind == "append-block":
        if not destination.is_file():
            return None
        text = destination.read_text(encoding="utf-8")
        begin, end = block_markers(record["key"])
        if begin not in text or end not in text:
            return None
        return sha256_bytes(text.split(begin, 1)[1].split(end, 1)[0].encode("utf-8"))
    raise ValueError("unsupported manifest entry kind: " + str(kind) +
                     ". fix: re-run neva install to rewrite the install-state manifest")


# ---------------------------------------------------------------- append-json


def is_neva_entry(item):
    return APPEND_MARKER in json.dumps(item, sort_keys=True)


def append_shape(value, where):
    """The arrays an append-json value holds: [(subkey or None, list)]. Anything else is refused."""
    if isinstance(value, list):
        return [(None, value)]
    if isinstance(value, dict) and all(isinstance(items, list) for items in value.values()):
        return list(value.items())
    raise ValueError(where + " must be an array, or an object whose values are arrays, found " +
                     type(value).__name__ + ". fix: correct it in that file, then re-run; Neva left it unchanged")


def arrays(value):
    """An append-json value as {subkey or None: list}: None for a plain array."""
    if isinstance(value, list):
        return {None: value}
    if isinstance(value, dict):
        return {sub: items for sub, items in value.items() if isinstance(items, list)}
    return {}


def reshape(template, by_sub):
    """{subkey or None: list} back into the shape of ``template``, dropping empty arrays."""
    if isinstance(template, list):
        return list(by_sub.get(None, []))
    return {sub: items for sub, items in by_sub.items() if items}


def take_out(items, owned):
    """``items`` without one occurrence of each ``owned`` entry, latest first, compared whole.

    Returns (kept, missing): the entries left, and the owned entries that were not found.
    Identity, never a substring: an owner entry that mentions neva-core is not Neva's.
    """
    kept, missing = list(items), []
    for item in reversed(list(owned)):
        for index in range(len(kept) - 1, -1, -1):
            if kept[index] == item:
                del kept[index]
                break
        else:
            missing.append(item)
    return kept, missing


def slot_name(key, sub, index=None):
    name = key if sub is None else join_key(key_parts(key) + [sub])
    return name + ("" if index is None else "[" + str(index) + "]")


def written_entries(destination_value, recorded):
    """The entries of ``recorded`` (what Neva wrote) still present at the destination, in its shape."""
    present = {}
    current = arrays(destination_value) if destination_value is not MISSING else {}
    for sub, items in arrays(recorded).items():
        kept, missing = take_out(current.get(sub, []), items)
        found = list(items)
        for item in missing:
            found.remove(item)
        present[sub] = found
    return reshape(recorded, present)


def edited_slot(kept, missing, foreign_items):
    """True when an entry Neva wrote is gone and a marker-carrying entry that was not the
    owner's at install sits in that array instead: the owner edited Neva's entry."""
    if not missing:
        return False
    new_marked = [item for item in kept if is_neva_entry(item)]
    leftover, _ = take_out(new_marked, foreign_items)
    return bool(leftover)


def edited_message(destination, key, sub):
    return (str(destination) + ": Neva's entry at " + slot_name(key, sub) + " was edited after Neva installed "
            "it (it no longer matches what Neva wrote), so Neva keeps it as it is. fix: move your edits into "
            "an entry of your own and run neva repair, or delete the entry yourself, then re-run")


def append_into(data, key, value, destination, previous=None, foreign=None):
    """Put Neva's entries from ``value`` beside the owner's at ``key`` in ``data``.

    Neva owns exactly what it recorded writing, ``previous``: those entries are taken out and
    the new ones added. Every other entry is the owner's and keeps its content and its place,
    even one that mentions neva-core, and an entry the owner already holds is not added twice.
    Only the arrays ``value`` and ``previous`` cover are touched.

    Returns (created, written, marked, names): the dotted paths this call created, what Neva
    wrote and the owner's entries that carry the marker, both in the shape of ``value``, and
    those owner entries by slot name for the report.
    """
    created = missing_parents(data, key)
    current = lookup(data, key, MISSING)
    if current is MISSING:
        created.append(key)
    wanted, before = arrays(value), arrays(previous) if previous is not None else {}
    if isinstance(value, list):
        if current is not MISSING and not isinstance(current, list):
            raise ValueError("cannot add Neva's entries to " + key + " in " + str(destination) + ": it holds a " +
                             type(current).__name__ + ", not an array. fix: make it an array or remove it "
                             "by hand, then re-run; Neva left the file unchanged")
        holder, slots = None, [None]
    else:
        if current is not MISSING and not isinstance(current, dict):
            raise ValueError("cannot add Neva's entries to " + key + " in " + str(destination) + ": it holds a " +
                             type(current).__name__ + ", not an object. fix: make it an object or remove it "
                             "by hand, then re-run; Neva left the file unchanged")
        holder = dict(current) if current is not MISSING else {}
        slots = list(wanted) + [sub for sub in before if sub not in wanted]
    written, marked, names = {}, {}, []
    foreign = arrays(foreign) if foreign is not None else {}
    for sub in slots:
        existing = (current if sub is None else holder.get(sub, MISSING))
        existing = [] if existing is MISSING else existing
        if not isinstance(existing, list):
            raise ValueError("cannot add Neva's entries to " + slot_name(key, sub) + " in " + str(destination) +
                             ": it holds a " + type(existing).__name__ + ", not an array. fix: make it an "
                             "array or remove it by hand, then re-run; Neva left the file unchanged")
        if sub is not None and sub not in holder:
            created.append(slot_name(key, sub))
        kept, missing = take_out(existing, before.get(sub, []))
        if edited_slot(kept, missing, foreign.get(sub, [])):
            raise ValueError(edited_message(destination, key, sub))
        add = [item for item in wanted.get(sub, []) if item not in kept]
        marked[sub] = [item for item in kept if is_neva_entry(item)]
        names.extend(slot_name(key, sub, index) for index, item in enumerate(kept) if is_neva_entry(item))
        written[sub] = add
        if sub is None:
            assign(data, key, kept + add)
        else:
            holder[sub] = kept + add
    if holder is not None:
        assign(data, key, holder)
    return created, reshape(value, written), reshape(value, marked), names


def strip_neva_entries(data, key, recorded, created, foreign=None, destination=""):
    """Take out exactly the entries Neva recorded writing, then any container it created and left empty.

    An entry Neva wrote that the owner has since edited is refused by name, never discarded,
    the same rule copy mode keeps for an edited file.
    """
    current = lookup(data, key, MISSING)
    foreign = arrays(foreign) if foreign is not None else {}
    for sub, items in arrays(recorded).items():
        existing = current if sub is None else (current.get(sub, MISSING) if isinstance(current, dict) else MISSING)
        if not isinstance(existing, list):
            continue
        kept, missing = take_out(existing, items)
        if edited_slot(kept, missing, foreign.get(sub, [])):
            raise ValueError(edited_message(destination, key, sub))
        if sub is None:
            assign(data, key, kept)
        else:
            current[sub] = kept
    for dotted in sorted(created, key=lambda item: len(key_parts(item)), reverse=True):
        if lookup(data, dotted, MISSING) in ([], {}):
            delete_key(data, dotted)
    return data


def missing_dirs(path):
    """Directories between HOME and ``path`` that do not exist yet, outermost first."""
    base = home()
    try:
        relative = Path(path).parent.relative_to(base)
    except ValueError:
        return []
    missing, current = [], base
    for part in relative.parts:
        current = current / part
        if not os.path.lexists(current):
            missing.append(str(current))
    return missing


def prune_created(directories):
    """Remove the directories install created, deepest first, and only while they are empty.

    A directory the owner had before install is never in this list, so it is never removed,
    even when it is empty. Symlinks and paths outside HOME are skipped.
    """
    boundary = home()
    for raw in sorted(set(directories), key=lambda item: item.count(os.sep), reverse=True):
        path = Path(raw)
        if boundary not in path.parents or path.is_symlink() or not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            pass


def prune_empty_parents(path, boundary=None):
    """Remove now-empty directories above ``path``, stopping at ``boundary`` (default: HOME).

    Never follows symlinks: if any parent in the chain is a symlink, or if the resolved
    parent would escape the boundary, pruning stops immediately.
    """
    boundary = Path(boundary).resolve() if boundary else home().resolve()
    parent = Path(path).parent
    while parent != boundary and parent != parent.parent:
        try:
            resolved_parent = parent.resolve()
        except OSError:
            break
        if boundary not in resolved_parent.parents and resolved_parent != boundary:
            break
        if parent.is_symlink():
            break
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
