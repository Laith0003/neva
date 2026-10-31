"""Secret rules: credential material sitting in harness configuration or instructions.

Nothing in this module ever puts a matched value into a Finding. Messages name the key,
the provider, or the field, and the fix names the rotation step. That is checked by a
test that plants a known value and asserts it appears in no output format.
"""
import re

from . import shared

KINDS = ("settings", "codex", "mcp", "hooks_config", "hook_script", "instructions", "credentials", "script", "marketplace")

PROVIDERS = (
    (re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), "a PEM private key"),
    (re.compile(r"\bsk-ant-api\d{2}-[A-Za-z0-9_-]{20,}"), "an Anthropic API key"),
    (re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}"), "an OpenAI project key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "an OpenAI style API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "a GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"), "a GitHub fine grained token"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{18,}"), "a GitLab token"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "a Google API key"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "an npm token"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "a Hugging Face token"),
    (re.compile(r"\bdop_v1_[a-f0-9]{60,}"), "a DigitalOcean token"),
    (re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"), "a Stripe key"),
    (re.compile(r"\bntn_[A-Za-z0-9]{40,}|\bsecret_[A-Za-z0-9]{43}\b"), "a Notion token"),
    (re.compile(r"\blin_(?:api|oauth)_[A-Za-z0-9]{32,}"), "a Linear key"),
    (re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"), "a SendGrid key"),
    (re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_-]{32,}"), "a Telegram bot token"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "a signed JWT"),
)

ASSIGNMENT = re.compile(
    r"(?im)(?<![A-Za-z0-9_.=-])(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,127})\s*(?::|=|:=|=>)\s*[\"']?(?P<value>[A-Za-z0-9_\-./+=~]{16,512})[\"']?(?=$|[\s,;)\]}])"
)


NEGATIVE_EXAMPLE = re.compile(r"(?i)\b(?:bad|wrong|insecure|vulnerable|unsafe|never|do not|don't|avoid|anti-?pattern|counterexample)\b")


def _documented_example(source, line):
    """True when the hit sits in a fenced block that a nearby line labels as a bad example.

    A language guide shows the hardcoded password it is telling you not to write. That is
    still worth reporting, because a real key pasted under a BAD heading reads the same,
    but it is reported at medium so a documentation repository can still gate on high.
    """
    if not source.has("instructions"):
        return False
    if line not in shared.fenced_lines(source.text):
        return False
    lines = source.text.splitlines()
    window = lines[max(0, line - 4):line]
    return any(NEGATIVE_EXAMPLE.search(item) for item in window)


def _report_provider(source, add, line, what):
    add("SECRET001", "critical", line,
        "This file contains " + what + ". The value is not reproduced here.",
        "Remove the literal from this file, rotate the credential at the provider now, and load it at run time from an environment variable.")


def check(source, add):
    text = source.text
    for pattern, what in PROVIDERS:
        for found in pattern.finditer(text):
            _report_provider(source, add, source.line_of(found.start()), what)

    is_toml = source.path.suffix.lower() == ".toml"
    data = source.toml() if is_toml else source.data()
    if data is not None:
        _check_json(source, add, data)
    if data is None or is_toml:
        _check_text(source, add, text)


def _strings(node, trail=()):
    """Yield (trail, text) for every string, and for each string list as one command line."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, trail + (str(key),))
    elif isinstance(node, list):
        if node and all(isinstance(item, str) for item in node):
            yield trail, " ".join(node)
        for index, value in enumerate(node):
            yield from _strings(value, trail + (str(index),))
    elif isinstance(node, str):
        yield trail, node


def _field(source, trail):
    return ".".join(source.printer.name(shared.mask_name(part), "field") for part in trail)


def _variable(source, key):
    return re.sub(r"[^A-Za-z0-9_]", "_", source.printer.name(shared.mask_name(key), "field")).upper()


def _check_json(source, add, data):
    for trail, value in shared.walk_json(data):
        if not isinstance(value, str) or not trail:
            continue
        key = trail[-1]
        # Codex env_http_headers maps a header to an environment variable name.
        if not shared.is_secret_key(key) or "env_http_headers" in trail:
            continue
        if not shared.is_literal_credential(key, value):
            continue
        add("SECRET002", "high", source.find_line('"' + key + '"', key),
            "Field " + _field(source, trail) + " holds a literal credential. The value is not reproduced here.",
            "Replace it with ${" + _variable(source, key) + "}, export that variable from your secret manager, and rotate the value that was committed.")
    for trail, value in _strings(data):
        if not trail or "env_http_headers" in trail or not shared.has_credential(value):
            continue
        add("SECRET002", "high", source.find_line(value, '"' + trail[-1] + '"'),
            "Field " + _field(source, trail) + " carries a literal credential inside its value. The value is not reproduced here.",
            "Move the credential to an environment variable, reference it here, and rotate the value that was committed.")


def _check_text(source, add, text):
    for found in ASSIGNMENT.finditer(text):
        key = found.group("key")
        value = found.group("value")
        if not shared.is_secret_key(key):
            continue
        if not shared.looks_like_secret_value(value):
            continue
        line = source.line_of(found.start())
        example = _documented_example(source, line)
        shown = source.printer.name(shared.mask_name(key), "field")
        add("SECRET002", "medium" if example else "high", line,
            "Assignment to " + shown + " holds a literal credential"
            + (" inside a block labelled as a bad example, so confirm it is not a real one" if example else "")
            + ". The value is not reproduced here.",
            "Replace it with ${" + re.sub(r"[^A-Za-z0-9_]", "_", shown).upper() + "}, export that variable from your secret manager, and rotate the value that was committed.")
    fenced = shared.fenced_lines(text)
    for number, line in enumerate(text.splitlines(), start=1):
        if not shared.has_credential(line):
            continue
        example = source.has("instructions") and number in fenced
        add("SECRET002", "medium" if example else "high", number,
            "This line carries a literal credential"
            + (" inside a code block, so confirm it is an example and not a real one" if example else "")
            + ". The value is not reproduced here.",
            "Move the credential to an environment variable, reference it here, and rotate the value that was committed.")
