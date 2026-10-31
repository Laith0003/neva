"""Find and classify agent harness configuration files. Standard library only.

A Source is one readable file plus the set of kinds it belongs to. Rule families declare
the kinds they apply to, so a prose document is never checked with permission rules and a
settings file is never checked with prose rules. That classification is what keeps the
false positive rate low enough for a CI gate.

Symlinks are never followed. In a repository scan, one that could hide configuration stops
the scan, because anyone can commit it and a linked directory reads as an empty tree. On a
machine the owner made the links and the harness relies on them, so `links` collects them
for the report and the scan carries on. That is the only difference between the two modes.
"""
import json
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 1024 * 1024
LARGE_CONFIG_BYTES = 32 * 1024 * 1024
LARGE_CONFIG_NAMES = {".claude.json"}

IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
    "dist", "target", "vendor", ".next", ".nuxt", ".cache", ".parcel-cache",
    ".terraform", ".gradle", ".idea", "Pods", "DerivedData", ".Trash",
    "Library", ".npm", ".nvm", ".cargo", ".rustup", ".pyenv", ".docker",
    "Applications", "Pictures", "Movies", "Music",
    ".tmp", ".temp", "tmp", "temp", ".worktrees",
})

# Build and cache folders are skipped only outside a harness folder: the harness loads what sits
# inside one, so `skills/dist` is not a hiding place. Dependency folders are skipped there only
# below a skill's own root, because Claude Code loads `skills/venv` as a skill.
SKILL_DEPENDENCIES = frozenset({"node_modules", "__pycache__", ".venv", "venv", "site-packages"})
NO_DEPENDENCY_PARENTS = frozenset({"commands", "agents", "rules"})

SETTINGS_NAMES = frozenset({
    "settings.json", "settings.local.json", "managed-settings.json",
    ".claude.json", "opencode.json", "opencode.jsonc", "config.json",
})
MCP_NAMES = frozenset({".mcp.json", "mcp.json", "mcp_servers.json"})
CREDENTIAL_NAMES = frozenset({"auth.json", ".credentials.json", "credentials.json", ".credentials"})
INSTRUCTION_NAMES = frozenset({
    "claude.md", "agents.md", "agent.md", "gemini.md", "skill.md",
    ".cursorrules", ".windsurfrules", "copilot-instructions.md",
})
INSTRUCTION_DIRS = frozenset({"skills", "agents", "commands", "rules", "prompts", "output-styles", "contexts"})
CONFIG_DIRS = frozenset({".claude", ".codex", ".cursor", ".gemini", ".opencode", "opencode"})
# A dangling link has no target to inspect here, and may resolve on the machine that runs it.
LINK_BLOCKED_NAMES = CONFIG_DIRS | INSTRUCTION_DIRS | {"hooks", ".claude-plugin", "plugins", ".github", "workflows"}
HARNESS_PARENTS = CONFIG_DIRS | INSTRUCTION_DIRS | {"hooks", "plugins", ".claude-plugin"}
SCRIPT_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".ksh"})
HOOK_SCRIPT_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts"})
INSTRUCTION_SUFFIXES = frozenset({".md", ".mdc", ".markdown"})

SUPPRESS = re.compile(r"neva-shield:\s*ignore(?:\s+([A-Za-z0-9_,\s*-]+))?")


class SafeError(ValueError):
    """A diagnostic built from printed names, so it is safe in a machine report."""


class ScanError(SafeError):
    """A scan input that blocks the report. Carries the path so it prints like a finding."""

    def __init__(self, path, reason):
        super().__init__(str(path) + ": " + reason)
        self.path = Path(path)
        self.reason = reason

    def shown(self, printer):
        return printer.path(self.path) + ": " + self.reason


NOT_REGULAR = "configuration is not a regular file; restore a regular configuration file"


def relative_parts(path, base):
    """Path parts below the scan root, so a clone location cannot change a verdict."""
    try:
        return Path(path).relative_to(base).parts
    except ValueError:
        return (Path(path).name,)


def scan_parts(path, base):
    """The parts a verdict may use: those below the root, and the root's own name."""
    return (Path(base).name,) + relative_parts(path, base)


def parent_names(parts):
    return {part.lower() for part in parts[:-1]}


def is_ignored(name, parts):
    """True when a folder named `name`, at scan_parts `parts`, is not worth reading."""
    if name == ".git":
        return True
    parents = [part.lower() for part in parts[:-1]]
    if not set(parents) & HARNESS_PARENTS:
        return name in IGNORED_DIRS
    if name not in SKILL_DEPENDENCIES or set(parents) & NO_DEPENDENCY_PARENTS or "skills" not in parents:
        return False
    return parents[::-1].index("skills") >= 1


def _is_skipped(path, parts):
    return is_ignored(path.name, parts) and (path.name == ".git" or not os.path.lexists(path / ".claude-plugin"))


def classify(path, parts):
    """Return the set of kinds for a file. `parts` are its path parts relative to the scan root."""
    name = path.name
    lower = name.lower()
    suffix = path.suffix.lower()
    parents = {part.lower() for part in parts[:-1]}
    kinds = set()

    if lower in SETTINGS_NAMES and (parents & CONFIG_DIRS or lower in {".claude.json", "opencode.json", "opencode.jsonc"}):
        kinds.add("settings")
    if lower.startswith("settings.") and suffix == ".json":
        kinds.add("settings")
    if lower == "config.toml" and ".codex" in parents:
        kinds.add("codex")
    if lower in MCP_NAMES:
        kinds.add("mcp")
    if lower == "hooks.json":
        kinds.add("hooks_config")
    if "settings" in kinds:
        kinds.update(("mcp", "hooks_config"))
    if "codex" in kinds:
        kinds.add("mcp")
    if lower in CREDENTIAL_NAMES:
        kinds.add("credentials")
    if lower == "marketplace.json" or ".claude-plugin" in parents:
        kinds.add("marketplace")
    if lower in INSTRUCTION_NAMES or (suffix in INSTRUCTION_SUFFIXES and parents & INSTRUCTION_DIRS):
        kinds.add("instructions")
    if "hooks" in parents and suffix in HOOK_SCRIPT_SUFFIXES:
        kinds.add("hook_script")
    if suffix in SCRIPT_SUFFIXES:
        kinds.add("script")
    if "workflows" in parents and suffix in {".yml", ".yaml"}:
        kinds.add("script")
    return frozenset(kinds)


class Plain:
    """Prints names as they are: a repository scan's report describes that repository."""

    def __init__(self, root=None, home=None):
        self.root = Path(root) if root else None
        self.home = Path(home) if home else None

    def path(self, path):
        return display_for(Path(path), self.root, self.home)

    def name(self, value, kind="name"):
        return str(value)

    def host(self, value):
        return value or "an unnamed host"

    def package(self, value):
        return value

    def entry(self, value):
        return value

    def project_key(self, value):
        return str(value)

    def finish(self, text):
        return shorten_home(text, self.home)

    def error(self, exc):
        return self.finish(str(exc))


def shorten_home(text, home):
    """Print the home directory as ~, whatever rule or configuration key the path came from."""
    if home is None or len(Path(home).parts) < 2:
        return text
    return re.sub(re.escape(str(home)) + r"(?![\w.-])", "~", text)


class Source:
    """One classified, readable file."""

    def __init__(self, path, display, kinds, text, mode, printer=None):
        self.path = path
        self.display = display
        self.printer = printer or Plain()
        self.kinds = kinds
        self.text = text
        self.mode = mode
        self._json = False
        self._toml = None
        self._suppressions = None

    def has(self, *kinds):
        return bool(self.kinds.intersection(kinds))

    def data(self):
        """Parsed JSON. Recognized JSON configuration must parse and match its shape."""
        if self._json is False:
            if self.path.suffix.lower() in {".json", ".jsonc"} or self.path.name == ".credentials":
                try:
                    data = json.loads(_strip_jsonc(self.text))
                except (ValueError, RecursionError) as exc:
                    raise SafeError(self.display + ": invalid JSON; repair the configuration JSON") from exc
                _validate_json(data, self.display)
                self._json = data
            else:
                self._json = None
        return self._json

    def toml(self):
        """Use the standard TOML parser rather than dropping nested tables or fields."""
        if self._toml is None:
            try:
                import tomllib
            except ImportError as exc:
                raise SafeError(self.display + ": TOML scanning requires Python 3.11 or newer; upgrade Python") from exc
            try:
                data = tomllib.loads(self.text)
            except (ValueError, RecursionError) as exc:
                raise SafeError(self.display + ": invalid TOML; repair the configuration TOML") from exc
            _validate_json(data, self.display)
            self._toml = data
        return self._toml

    def line_of(self, offset):
        return self.text.count("\n", 0, offset) + 1

    def find_line(self, *needles, **kwargs):
        """Line number of the first needle present in the raw text, else the fallback.

        A value taken from parsed JSON is also looked for in its escaped form, so a hook
        command containing quotes still resolves to the line it was written on.
        """
        for needle in needles:
            if not needle or not isinstance(needle, str):
                continue
            for form in (needle, json.dumps(needle)[1:-1]):
                offset = self.text.find(form)
                if offset >= 0:
                    return self.line_of(offset)
        return kwargs.get("default", 1)

    def suppressions(self):
        """Map of line number to the rule ids suppressed on it.

        An inline `neva-shield: ignore RULEID` comment suppresses that rule on its own line
        and on the line below it, so a comment can sit above the line it excuses. `ignore`
        with no rule id suppresses every rule on those lines. Suppressions are counted and
        reported so they cannot hide silently.
        """
        if self._suppressions is None:
            table = {}
            for index, line in enumerate(self.text.splitlines(), start=1):
                found = SUPPRESS.search(line)
                if not found:
                    continue
                raw = (found.group(1) or "*").replace(",", " ").split()
                ids = {item.upper() for item in raw} or {"*"}
                for target in (index, index + 1):
                    table.setdefault(target, set()).update(ids)
            self._suppressions = table
        return self._suppressions

    def is_suppressed(self, line, rule_id):
        ids = self.suppressions().get(line, set())
        return "*" in ids or rule_id.upper() in ids


def _strip_jsonc(text):
    """Remove // and /* */ comments outside strings so .jsonc settings parse."""
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            end = index + 1
            while end < length:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == '"':
                    break
                end += 1
            out.append(text[index:end + 1])
            index = end + 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            end = text.find("\n", index)
            index = length if end < 0 else end
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index)
            if end < 0:
                raise ValueError("unterminated JSON comment")
            index = end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _validate_json(data, display):
    def error(field):
        raise SafeError(display + ": invalid " + field + "; repair the configuration shape")

    if not isinstance(data, dict):
        error("root (expected an object)")
    for key in ("permissions", "permission"):
        if key not in data:
            continue
        block = data[key]
        if not isinstance(block, dict):
            error(key + " (expected an object)")
        for scope in ("allow", "deny", "ask"):
            if scope in block:
                value = block[scope]
                if not (isinstance(value, list) and all(isinstance(x, str) for x in value)
                        or isinstance(value, dict) and all(
                            isinstance(setting, bool) or isinstance(setting, str)
                            and setting.lower() in {"allow", "deny", "ask", "true", "false"}
                            for setting in value.values())):
                    error(key + "." + scope + " (expected a string array or object)")
    for key in ("mcpServers", "mcp_servers", "servers", "context_servers"):
        if key not in data:
            continue
        if not isinstance(data[key], dict):
            error(key + " (expected an object)")
        for name, server in data[key].items():
            if not isinstance(server, dict):
                error(key + ".<server>" + " (expected an object)")
            for field in ("url", "endpoint", "serverUrl", "httpUrl", "sse_url"):
                if field in server and not isinstance(server[field], str):
                    error(key + ".<server>" + "." + field + " (expected a string)")
            if "args" in server and not (isinstance(server["args"], list)
                                        and all(isinstance(x, str) for x in server["args"])):
                error(key + ".<server>" + ".args (expected a string array)")
            for field in ("env", "headers", "http_headers", "env_http_headers"):
                if field in server and not isinstance(server[field], dict):
                    error(key + ".<server>" + "." + field + " (expected an object)")
    if "mcp" in data:
        block = data["mcp"]
        if not isinstance(block, dict):
            error("mcp (expected an object)")
        _validate_json({"mcpServers": block.get("servers", block)}, display)
    if "projects" in data:
        if not isinstance(data["projects"], dict):
            error("projects (expected an object)")
        for project in data["projects"].values():
            _validate_json(project, display)


def read_file(path):
    cap = LARGE_CONFIG_BYTES if path.name in LARGE_CONFIG_NAMES else MAX_BYTES
    directory = None
    fd = None
    try:
        path = Path(path).absolute()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(path.anchor, flags)
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ScanError(path, NOT_REGULAR)
        if info.st_size > cap:
            raise ScanError(path, "exceeds scan size limit; reduce the file size before scanning")
        with open(fd, "rb", closefd=True) as handle:
            fd = None
            raw = handle.read(cap + 1)
    except OSError as exc:
        raise ScanError(path, "cannot read configuration; restore read access and retry") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)
    if len(raw) > cap:
        raise ScanError(path, "exceeds scan size limit; reduce the file size before scanning")
    if b"\0" in raw:
        raise ScanError(path, "binary configuration; repair the file as UTF-8 text")
    try:
        return raw.decode("utf-8"), info.st_mode
    except UnicodeDecodeError as exc:
        raise ScanError(path, "invalid UTF-8; repair the file encoding") from exc


def safe_path(path, root):
    """Reject every symlink component and paths outside the intended real root."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if any(part.is_symlink() for part in (path, *path.parents, root, *root.parents)):
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def require_safe_path(path, root):
    """Fail closed when a recognized scan entry has an unmanaged path component."""
    if not safe_path(path, root):
        raise ScanError(path, "configuration path contains a symlink or escapes the scan root; restore a regular file or directory")


def reject_special(path):
    """Fail closed when something other than a file or directory sits at a known location."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ScanError(path, "cannot read configuration; restore read access and retry") from exc
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
        raise ScanError(path, NOT_REGULAR)


SCORED_KINDS = frozenset({"settings", "codex", "mcp", "hooks_config", "hook_script", "credentials",
                          "instructions", "marketplace"})


class LinkLog:
    """Every link a machine scan did not follow, with the location it was meant to reach."""

    def __init__(self):
        self.rows = {}

    def scoped(self, origin, target):
        return _ScopedLinks(self, origin, target)

    def add(self, path, origin, target, whole=False):
        self.rows.setdefault(path, (origin, target, whole))


class _ScopedLinks:
    def __init__(self, log, origin, target):
        self.log, self.origin, self.target = log, origin, target

    def append(self, path):
        self.log.add(path, self.origin, self.target)


def link_severity(path, origin, target, home, whole=False):
    """Score a link by what it stands in for, from the location the scan meant to read.

    In a checkout a link is committed content, so a harness location there is high: a clone
    carries it to every machine. At home the owner made it, so it is medium where it could
    hold enforced configuration or instructions, and low where it is only a coverage note.
    """
    name = path.name.lower()
    kinds = classify(path, relative_parts(path, home))
    if origin == "project":
        try:
            parts = {part.lower() for part in path.relative_to(target).parts}
        except ValueError:
            parts = {name}
        harness = parts & CONFIG_DIRS or name in {item.lower() for item in PROJECT_FILES} or kinds
        return "high" if harness else "medium"
    if whole or name in LINK_BLOCKED_NAMES or kinds & SCORED_KINDS:
        return "medium"
    return "low"


def first_link(path, root):
    """The first symlink at or under root on the way to path, or None."""
    current = Path(root)
    for part in Path(path).relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _entries(directory, links=None, base=None):
    """Sorted entries. An entry that could hide configuration stops the scan or joins links."""
    base = base or directory
    try:
        with os.scandir(directory) as handle:
            rows = []
            for entry in handle:
                path = Path(directory) / entry.name
                parts = scan_parts(path, base)
                parents = parent_names(parts)
                try:
                    if entry.is_symlink():
                        if _is_skipped(path, parts):
                            continue
                        linked_dir = entry.is_dir()
                        recognized = (classify(path, parts) or entry.name.lower() in LINK_BLOCKED_NAMES
                                      or parents & HARNESS_PARENTS)
                        if links is not None:
                            if linked_dir or recognized:
                                links.append(path)
                            continue
                        if linked_dir:
                            raise ScanError(path, "symlinked directory hides its contents from the scan; restore a regular directory or remove the link")
                        if recognized:
                            require_safe_path(path, directory)
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                    if not is_dir and not is_file and classify(path, parts):
                        raise ScanError(path, NOT_REGULAR)
                    rows.append((entry.name, is_dir, is_file))
                except OSError as exc:
                    raise ScanError(directory, "cannot read directory entry; restore read access and retry") from exc
    except OSError as exc:
        raise ScanError(directory, "cannot read directory; restore read access and retry") from exc
    return sorted(rows)


def walk(root, max_depth=None, links=None, base=None):
    """Yield files under root, handling configuration symlinks and skipping ignored trees."""
    root = Path(root)
    base = Path(base) if base else root
    require_safe_path(root, root)
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        for name, is_dir, is_file in _entries(directory, links, base):
            if is_dir:
                if _is_skipped(directory / name, scan_parts(directory / name, base)):
                    continue
                if max_depth is not None and depth + 1 > max_depth:
                    continue
                pending.append((directory / name, depth + 1))
            elif is_file:
                yield directory / name


def walk_projects(root, max_depth, links=None):
    """Yield candidate project directories under root.

    Only directories are stepped through, and hidden directories are never descended
    into, because a project's agent configuration is either a file at its top level or a
    dot directory inside it. Walking every file under a code home instead takes minutes.
    """
    root = Path(root)
    require_safe_path(root, root)
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        yield directory
        if depth >= max_depth:
            continue
        for name, is_dir, _ in _entries(directory, links, root):
            if is_dir and not _is_skipped(directory / name, scan_parts(directory / name, root)) and not name.startswith("."):
                pending.append((directory / name, depth + 1))


def display_for(path, root, home):
    """How a finding names this file: relative to the scan root, or ~/ for a machine scan."""
    if root != home:
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    try:
        return os.path.join("~", str(path.relative_to(home)))
    except ValueError:
        return str(path)


PROJECT_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".mcp.json", ".cursorrules", ".windsurfrules")
PROJECT_CONFIG_DIRS = (".claude", ".codex", ".cursor", ".gemini", ".opencode")
PROJECT_CONFIG_DEPTH = 3


def project_sources(root, home, max_depth, links=None, printer=None):
    """Yield Sources for the agent configuration of every checkout under a code home."""
    home = Path(home)
    for directory in walk_projects(root, max_depth, links):
        for name in PROJECT_FILES:
            path = directory / name
            if links is not None and path.is_symlink():
                links.append(path)
                continue
            require_safe_path(path, directory)
            reject_special(path)
            if not path.is_file():
                continue
            source = _source(path, (name,), home, home, printer)
            if source is not None:
                yield source
        for name in PROJECT_CONFIG_DIRS:
            sub = directory / name
            if links is not None and sub.is_symlink():
                links.append(sub)
                continue
            require_safe_path(sub, directory)
            reject_special(sub)
            if sub.is_dir():
                yield from sources(sub, home=home, max_depth=PROJECT_CONFIG_DEPTH,
                                   relative_to=directory, display_root=home, links=links, printer=printer)


def _source(path, parts, base_for_display, home, printer=None):
    require_safe_path(path, base_for_display)
    kinds = classify(path, parts)
    if not kinds:
        return None
    read = read_file(path)
    text, mode = read
    display = printer.path(path) if printer else display_for(path, base_for_display, home)
    return Source(path, display, kinds, text, mode, printer)


def sources(root, home=None, max_depth=None, skip=(), relative_to=None, display_root=None, links=None, printer=None):
    """Yield a Source for every classified, readable file under root.

    `relative_to` is the base that classification sees, and `display_root` is the base a
    finding's path is printed against. Both default to root. A machine scan sets them to
    the home directory so that ~/.codex/config.toml is still recognised as a Codex config
    even though the walk starts inside ~/.codex.
    """
    root = Path(root)
    home = Path(home) if home else Path.home()
    base = Path(relative_to) if relative_to else root
    shown = Path(display_root) if display_root else root
    skip = tuple(Path(item).resolve() for item in skip)
    for path in walk(root, max_depth=max_depth, links=links, base=base):
        require_safe_path(path, root)
        resolved = path.resolve()
        if any(resolved == item or item in resolved.parents for item in skip):
            continue
        kinds = classify(path, scan_parts(path, base))
        if not kinds:
            continue
        read = read_file(path)
        if read is None:
            continue
        text, mode = read
        display = printer.path(path) if printer else display_for(path, shown, home)
        yield Source(path, display, kinds, text, mode, printer)
