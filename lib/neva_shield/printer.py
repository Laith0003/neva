"""How a machine scan prints what it found. Standard library only.

A machine report gets pasted into chats and uploaded by CI, and folder, skill, server and
host names can identify clients. Private therefore prints only known harness names and
replaces every other path segment and every echoed value with a keyed label. It works from
components at the source, because a pattern over finished text misses what it did not
anticipate. Labels come from a random per-machine key, so they stay stable between runs and
a dictionary of likely client names cannot reverse them.
"""
import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path

from . import collect
from .rules.permissions import SHELL_TOOLS, WRITE_TOOLS

KEY_DIRECTORY = ".neva"
KEY_NAME = "shield-label.key"
KEY_BYTES = 32
LABEL_HEX = 16

KEPT_NAMES = frozenset(name.lower() for name in (
    collect.CONFIG_DIRS | collect.INSTRUCTION_DIRS | collect.SETTINGS_NAMES | collect.MCP_NAMES
    | collect.CREDENTIAL_NAMES | collect.INSTRUCTION_NAMES | frozenset(collect.PROJECT_FILES)
    | frozenset({".config", "github-copilot", "hooks", "plugins", ".claude-plugin", ".github",
                 "workflows", "projects", "worktrees", "memory", "cache", "hooks.json",
                 "marketplace.json", "config.toml"})))
LABEL_KINDS = {"skills": "skill", "agents": "agent", "commands": "command", "worktrees": "worktree",
               "projects": "project", "rules": "rule"}
WILDCARD_BODIES = frozenset({"", "*", ":*", "**", "*:*", "(*)", "domain:*"})
KEPT_SUFFIXES = frozenset({".md", ".mdc", ".json", ".jsonc", ".toml", ".yml", ".yaml", ".txt",
                           ".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts"})
KNOWN_TOOLS = SHELL_TOOLS | WRITE_TOOLS | frozenset({"read", "glob", "grep", "ls", "webfetch", "websearch", "notebookread", "task"})


def load_key(home):
    """Read the machine key, creating it on first use. A home that cannot hold one still scans."""
    directory = Path(home) / KEY_DIRECTORY
    path = directory / KEY_NAME
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return os.urandom(KEY_BYTES)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("~/" + KEY_DIRECTORY + ": not a real directory; restore it so " + KEY_NAME + " stays private")
    if os.path.lexists(path):
        return _read_key(path)
    try:
        return _create_key(directory, path) or _read_key(path)
    except OSError:
        return os.urandom(KEY_BYTES)


def _create_key(directory, path):
    """Write to a temporary name and link it in, so nobody ever reads a partial key."""
    key = os.urandom(KEY_BYTES)
    temporary = directory / (KEY_NAME + "." + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return None
        return key
    finally:
        os.unlink(temporary)


def _read_key(path):
    shown = "~/" + KEY_DIRECTORY + "/" + KEY_NAME
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError(shown + ": cannot read the label key; restore a regular file or delete it to make a new one") from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(shown + ": not a regular file; delete it to make a new one")
        if info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError(shown + ": readable by others; run chmod 600 on it, or delete it to make a new one")
        key = handle.read(KEY_BYTES + 1)
    if len(key) != KEY_BYTES:
        raise ValueError(shown + ": wrong length; delete it to make a new one")
    return key


class Private:
    """The default for a machine scan: harness names stay, everything else becomes a label."""

    def __init__(self, home, roots):
        self.home = Path(home)
        self.kept = KEPT_NAMES | {root.lower() for root in roots}
        self.roots = {root.lower() for root in roots}
        self.key = load_key(home)

    def _label(self, kind, value):
        digest = hmac.new(self.key, value.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()
        return kind + "-" + digest[:LABEL_HEX]

    def _segment(self, part, previous, last):
        if part.lower() in self.kept:
            return part
        kind = "project" if previous in self.roots else LABEL_KINDS.get(previous, "name")
        suffix = Path(part).suffix if last else ""
        return self._label(kind, part) + (suffix if suffix.lower() in KEPT_SUFFIXES else "")

    def path(self, path):
        try:
            parts = Path(path).relative_to(self.home).parts
        except ValueError:
            return self._label("path", str(path))
        shown = ["~"]
        previous = ""
        for index, part in enumerate(parts):
            shown.append(self._segment(part, previous, index == len(parts) - 1))
            # A masked folder keeps the kind going down a checkout: ~/Code/venture/repo.
            if part.lower() in self.kept:
                previous = part.lower()
        return "/".join(shown)

    def name(self, value, kind="name"):
        return self._label(kind, str(value))

    def host(self, value):
        return self._label("host", value) if value else "an unnamed host"

    def package(self, value):
        return self._label("package", value)

    def entry(self, value):
        tool, opening, rest = value.partition("(")
        if tool.lower() not in KNOWN_TOOLS:
            return self._label("tool", value)
        body = rest[:-1].strip() if opening and rest.endswith(")") else ""
        return value if body in WILDCARD_BODIES else tool + "(" + self._label("entry", value) + ")"

    def project_key(self, value):
        return self.path(value) if str(value).startswith(str(self.home)) else self._label("project", str(value))

    def finish(self, text):
        return collect.shorten_home(text, self.home)

    def error(self, exc):
        """Free text can hold any path, so only diagnostics built from printed names pass."""
        if isinstance(exc, collect.SafeError):
            return self.finish(str(exc))
        return "the scan stopped on " + type(exc).__name__ + "; rerun with --show-paths for the detail"


class Shown(collect.Plain):
    """--show-paths: the owner's real names, with the home directory still shortened."""

    def __init__(self, home):
        super().__init__(home, home)
