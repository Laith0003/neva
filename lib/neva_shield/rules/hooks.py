"""Hook rules: a hook runs on every tool call, so a weakness here runs constantly."""
import re

from . import shared

KINDS = ("hooks_config", "hook_script", "settings")

PAYLOAD_VARS = (
    "payload", "tool_input", "tool_response", "tool_name", "user_prompt", "prompt",
    "file_path", "file_paths", "command", "cwd", "arguments", "message", "transcript",
    "TOOL_INPUT", "TOOL_NAME", "USER_PROMPT", "FILE_PATH", "ARGUMENTS",
    "CLAUDE_TOOL_INPUT", "CLAUDE_TOOL_NAME", "CLAUDE_FILE_PATHS", "CLAUDE_USER_PROMPT",
    "CLAUDE_NOTIFICATION", "CLAUDE_COMMAND",
)
PAYLOAD_VAR = re.compile(r"\$\{?(" + "|".join(PAYLOAD_VARS) + r")\b")
REPARSE = re.compile(r"(?:^|[|;&]|\$\(|&&|\|\|)\s*(?:eval\b|(?:ba|z|d)?sh\s+-c\b|python3?\s+-c\b|node\s+-e\b)")
FETCH_TO_SHELL = re.compile(shared.COMMAND_POSITION + r"(?:sudo\s+)?(?:curl|wget)\b[^|\n]*https?://[^|\n]*\|\s*(?:sudo\s+)?(?:ba|z|d)?sh\b", re.M)
NETWORK_SHELL = re.compile(shared.COMMAND_POSITION + r"(?:curl|wget|nc|ncat|netcat|telnet|scp|sftp|rsync|ssh)\b", re.M)
NETWORK_PYTHON = re.compile(r"\b(?:urllib\.request\.urlopen|urlopen\(|requests\.(?:get|post|put)|http\.client\.HTTP|socket\.socket|smtplib\.)")
NETWORK_NODE = re.compile(r"\b(?:fetch\(|https?\.request\(|axios\.)")
# A swallowed block is a decision plus an error suppressor on the same statement. The
# decision words are past tense on purpose: "Exit 2 = block" in a docstring is a comment
# about the protocol, not a discarded decision, and the comment filter drops those too.
DECISION = re.compile(r"(?i)\b(?:denied|deny|blocked|rejected|reject|refused|violation)\b")
SUPPRESSOR = re.compile(r"2\s*>\s*/dev/null|\|\|\s*(?:true|:)(?:\s|$)|(?:^|[;&|]\s*)exit\s+0\b|sys\.exit\(0\)|except[^:\n]*:\s*pass")
COMMENT_LINE = re.compile(r"^\s*(?:#|//|\*|\"\"\"|'''|-\s|\d+[.)]\s)")


def _commands(source):
    """Yield (command text, line) for every hook command in a config document."""
    data = source.data()
    if not isinstance(data, (dict, list)):
        return
    for trail, value in shared.walk_json(data):
        if not isinstance(value, str) or not value.strip():
            continue
        if trail and trail[-1] in {"command", "cmd", "script", "run", "exec"}:
            yield value, source.find_line(value)


def _scan_command(source, add, text, base_line, label):
    for index, line in enumerate(text.splitlines()):
        number = base_line + index
        unquoted = PAYLOAD_VAR.search(shared.strip_quoted(line))
        if unquoted:
            add("HOOK001", "high", number,
                label + " splices the unquoted payload field $" + unquoted.group(1) + " into a shell command, so hostile tool input becomes shell source.",
                'Quote it as "$' + unquoted.group(1) + '", or read the field with python3 -c and pass it as an argument rather than splicing it into the command line.')
        elif REPARSE.search(line):
            quoted = PAYLOAD_VAR.search(line)
            if quoted:
                add("HOOK001", "high", number,
                    label + " passes the payload field $" + quoted.group(1) + " to a command that reparses its argument as code, so quoting does not contain it.",
                    "Remove the eval or -c wrapper and run the program directly with $" + quoted.group(1) + " as a quoted positional argument.")
        if FETCH_TO_SHELL.search(line):
            add("HOOK002", "high", number,
                label + " downloads a remote script and executes it immediately.",
                "Download to a file, verify its checksum against a pinned value, then run the verified file.")


def check(source, add):
    text = source.text
    is_script = source.has("hook_script")

    if source.has("hooks_config", "settings"):
        for command, line in _commands(source):
            _scan_command(source, add, command, line, "Hook command")

    if is_script:
        _scan_command(source, add, text, 1, "Hook script")
        for found in NETWORK_SHELL.finditer(text):
            add("HOOK003", "medium", source.line_of(found.start()),
                "Hook script runs " + found.group(0).strip().strip("|;&`$( ") + ", so every tool call can reach the network.",
                "Remove the network call, or restrict it to one allowlisted host and log every request.")
        for pattern in (NETWORK_PYTHON, NETWORK_NODE):
            for found in pattern.finditer(text):
                add("HOOK003", "medium", source.line_of(found.start()),
                    "Hook script makes an outbound request with " + found.group(0).strip("( ") + ", so every tool call can reach the network.",
                    "Remove the network call, or restrict it to one allowlisted host and log every request.")

    if source.has("hooks_config", "hook_script"):
        for number, line in enumerate(text.splitlines(), start=1):
            if COMMENT_LINE.match(line) or not DECISION.search(line) or not SUPPRESSOR.search(line):
                continue
            add("HOOK004", "high", number,
                "A blocking decision on this line is discarded by an error suppressor, so a blocked action can look like a clean pass.",
                "Drop the suppressor, exit nonzero, and print the reason the action was blocked to stderr.")

    if is_script and source.mode & 0o002:
        add("HOOK005", "high", 1,
            "Hook script is world writable (mode " + oct(source.mode & 0o777) + "), so any local process can rewrite what runs on every tool call.",
            "Run chmod o-w on this file, and chmod go-w if it does not need group write.")
