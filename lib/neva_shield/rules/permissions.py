"""Permission rules: allow entries that hand an agent arbitrary execution or exfiltration."""
import re

from . import shared

KINDS = ("settings",)

SHELL_TOOLS = frozenset({"bash", "shell", "execute", "run", "terminal"})
SHELL_BINARIES = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "exec", "source", ".", "env", "xargs", "nohup", "setsid"})
WILDCARDS = frozenset({"", "*", ":*", "**", "*:*", "(*)"})
INTERPRETER_INLINE = re.compile(r"\b(?:python3?|node|deno|bun|ruby|perl|php|osascript)\b[^|]*?\s-(?:c|e|eval)\b")
FETCH_TO_SHELL = re.compile(r"\b(?:curl|wget|fetch)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|d)?sh\b")
UPLOAD = re.compile(r"(?i)(?:^|_)(?:file_)?upload|put_object|send_file|attach_file")
HOME_WRITE = re.compile(r"^(?:~|\$HOME|/home/[^/]+|/Users/[^/]+|/root)(?:/\*{1,2})*/?\*{0,2}$")
ROOT_WRITE = frozenset({"*", "**", "/", "/*", "/**", "/**/*"})
WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "notebookedit", "filewrite", "create"})
WEBFETCH_WILDCARD = re.compile(r"^WebFetch(?:\(\s*(?:\*|domain:\s*\*|:\*)?\s*\))?$", re.I)
PLAIN_PATH = re.compile(r"[\w.~/*+@-]+")
ASSIGNMENT_WORD = re.compile(r"[A-Za-z_]\w*=")
COMMAND_WORD = re.compile(r"[\w.+-]+(?::\*)?")
TOOL_NAME = re.compile(r"[\w.-]+")
PATH_WORD = re.compile(r"[A-Za-z]+(?:[._-][A-Za-z0-9]+)+")
SHORT_SEGMENT = 12
SECRET_DENY_MARKERS = (".ssh", ".env", ".aws", ".gnupg", "credential", "id_rsa", "secret", ".netrc", ".npmrc", "keychain")


def _blocks(data, printer):
    """Yield every permissions block in a settings document, with a label for the message."""
    if not isinstance(data, dict):
        return
    for key in ("permissions", "permission"):
        block = data.get(key)
        if isinstance(block, dict):
            yield block, key
    projects = data.get("projects")
    if isinstance(projects, dict):
        for name, project in projects.items():
            if isinstance(project, dict) and isinstance(project.get("permissions"), dict):
                yield project["permissions"], "projects." + printer.project_key(shared.mask_name(str(name))) + ".permissions"


def _entries(block, scope):
    value = block.get(scope)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        return [str(key) for key, setting in value.items() if str(setting).lower() in {"allow", "true"}]
    return []


def _split(entry):
    text = entry.strip()
    if "(" in text and text.endswith(")"):
        return text[:text.index("(")].strip(), text[text.index("(") + 1:-1].strip()
    return text, ""


def _command(body):
    """The first word of a shell command, and whether anything follows it."""
    words = [word for word in body.split() if not ASSIGNMENT_WORD.match(word)]
    if not words:
        return "<command>", False
    name = words[0].rsplit("/", 1)[-1]
    if not COMMAND_WORD.fullmatch(name) or shared.looks_like_secret_value(name):
        name = "<command>"
    return name, len(words) > 1


def _path_segment(part):
    if shared.looks_like_secret_value(part):
        return False
    return len(part) <= SHORT_SEGMENT or PATH_WORD.fullmatch(part) is not None


def _plain_path(body):
    if not PLAIN_PATH.fullmatch(body) or not ("/" in body or "*" in body or body.startswith((".", "~"))):
        return False
    return all(_path_segment(part) for part in body.split("/"))


def _shown(entry):
    """An allow entry as a report prints it.

    Only what can be recognized as safe is echoed. A command line can carry a credential in
    any flag or header, so a shell entry prints its first word, and any other tool prints
    its body only when that is a wildcard or a plain path.
    """
    tool, body = _split(entry)
    tool = shared.mask_name(tool) if TOOL_NAME.fullmatch(tool) else "<tool>"
    if not body:
        return tool + ("()" if entry.strip().endswith("()") else "")
    if body in WILDCARDS or re.fullmatch(r"domain:\s*\*", body):
        return tool + "(" + body + ")"
    if tool.lower() in SHELL_TOOLS:
        name, more = _command(body)
        return tool + "(" + name + (" ..." if more else "") + ")"
    return tool + "(" + (body if _plain_path(body) else "<body>") + ")"


def _exec_risk(entry):
    """Return (severity, what it grants) when an allow entry grants arbitrary execution."""
    tool, body = _split(entry)
    if tool.lower() not in SHELL_TOOLS:
        return None
    if body in WILDCARDS:
        return "critical", "any shell command at all"
    words = body.split()
    first = words[0].lstrip("$(").lower() if words else ""
    if first in SHELL_BINARIES and (len(words) == 1 or "*" in body):
        return "high", "an arbitrary shell through " + first
    if INTERPRETER_INLINE.search(body):
        return "high", "arbitrary code through an inline interpreter flag"
    if FETCH_TO_SHELL.search(body):
        return "high", "a download piped straight into a shell"
    return None


def check(source, add):
    data = source.data()
    if not isinstance(data, dict):
        return
    printer = source.printer
    for block, label in _blocks(data, printer):
        allow = _entries(block, "allow")
        deny = _entries(block, "deny")
        upload_entries = [item for item in allow if UPLOAD.search(item)]
        webfetch_wildcard = [item for item in allow if WEBFETCH_WILDCARD.match(item.strip())]

        for entry in allow:
            line = source.find_line(entry)
            shown = printer.entry(_shown(entry))
            risk = _exec_risk(entry)
            if risk:
                severity, grants = risk
                add("PERM001", severity, line,
                    "Allow rule " + shown + " grants " + grants + ".",
                    "Replace " + shown + " in " + label + ".allow with the exact command and arguments the agent needs, for example Bash(git status).")
            if UPLOAD.search(entry):
                add("PERM002", "high", line,
                    "Allow rule " + shown + " lets the agent upload files without a prompt.",
                    "Remove " + shown + " from " + label + ".allow, or move it to " + label + ".ask so each upload is confirmed.")
            tool, body = _split(entry)
            if tool.lower() in WRITE_TOOLS and body:
                target = body.strip()
                if target in ROOT_WRITE:
                    add("PERM003", "critical", line,
                        "Allow rule " + shown + " grants writes to the whole filesystem.",
                        "Replace " + shown + " with a single project directory, for example " + tool + "(./src/**).")
                elif HOME_WRITE.match(target):
                    add("PERM003", "high", line,
                        "Allow rule " + shown + " grants writes across the home directory.",
                        "Replace " + shown + " with a single project directory, for example " + tool + "(./src/**).")

        if webfetch_wildcard and upload_entries:
            add("PERM004", "high", source.find_line(webfetch_wildcard[0]),
                "Unrestricted " + printer.entry(_shown(webfetch_wildcard[0])) + " is allowed alongside the upload permission " + printer.entry(_shown(upload_entries[0])) + ", which is a complete exfiltration path.",
                "Restrict WebFetch to named domains, for example WebFetch(domain:docs.example.com), or remove " + printer.entry(_shown(upload_entries[0])) + " from " + label + ".allow.")

        if allow and not any(marker in item.lower() for item in deny for marker in SECRET_DENY_MARKERS):
            add("PERM005", "medium", source.find_line('"deny"', '"allow"', default=1),
                "Permission block " + label + " allows tools but has no deny rule covering secret paths.",
                'Add to ' + label + '.deny: "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(**/.env*)", "Read(**/credentials*)".')
